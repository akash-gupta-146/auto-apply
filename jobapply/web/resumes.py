"""What the Create Resume tab does. No HTTP in here: the server calls these and sends back what they return.

Every method takes what a request carried (all of it untrusted), and raises `ActionError` with a message written for the person when something is off.
A resume that comes in with a request goes through `doc.normalize` first, like everything else: the ATS check and the AI work on what you are looking at
in the editor, saved or not.
"""
from __future__ import annotations

import functools
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .. import skills_vocab
from ..ai_settings import load_ai_settings
from ..builder import ai as resume_ai
from ..builder import ats, doc as store, importer, pdf, render, tailor
from ..config import ConfigError, Criteria, Paths, Profile, load_criteria, load_profile, save_profile
from ..db import Database
from ..resume import read_text, sync_profile
from .actions import ActionError

MAX_JOB_TEXT = 20_000  # chars of a pasted job description
MAX_EXTRA = 20  # words you can ask to have looked for
PLAIN = (store.NotFound, store.Conflict, ValueError, pdf.PdfError, resume_ai.AiUnavailable, ConfigError)  # each says what is wrong in words for the person


def plainly(method: Callable) -> Callable:
    """A method of the tab that tells the person what went wrong, as an ActionError, instead of a stack trace."""
    @functools.wraps(method)
    def wrapped(*args: Any, **kwargs: Any):
        try:
            return method(*args, **kwargs)
        except PLAIN as exc:
            raise ActionError(str(exc)) from None
    return wrapped


def _text(value: object, limit: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ActionError(f"The {what} was not understood.")
    return value[:limit]


class ResumeTab:
    def __init__(self, paths: Paths, read_profile: Callable[[], Optional[Profile]],
                 make_ai: Callable[..., resume_ai.ResumeAi] = resume_ai.make_resume_ai, make_pdf: Callable[..., pdf.Exported] = pdf.make_pdf):
        self.paths, self._profile, self._make_ai, self._make_pdf = paths, read_profile, make_ai, make_pdf
        self._writes = threading.Lock()  # the server answers each request in its own thread: one change to the saved resumes at a time

    # -- the list and the choices ---------------------------------------------------------------
    @plainly
    def overview(self) -> Dict[str, Any]:
        profile = self._profile()
        settings = load_ai_settings(self.paths) if self.paths.ai.exists() else None
        return {
            "resumes": store.listing(self.paths), "templates": render.catalog(),
            "uploaded": Path(profile.resume_path).name if profile and profile.resume_path else "", "has_profile": bool(profile),
            "ai": bool(settings and settings.configured),
            "choices": {"fonts": list(store.FONTS), "sizes": list(store.SIZES), "spacings": list(store.SPACINGS), "pages": list(store.PAGES),
                        "sections": [{"id": key, "heading": store.HEADINGS[key]} for key in store.SECTIONS], "limits": store.LIMITS},
        }

    @plainly
    def get(self, resume_id: object) -> Dict[str, Any]:
        doc = store.load(self.paths, resume_id)
        return {"resume": doc, "pages": render.estimate_pages(doc)}

    @plainly
    def create(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """A new resume: blank, from your saved details, or read from the resume you uploaded (a draft to check)."""
        mode, notes = body.get("mode", "blank"), []
        if mode == "blank":
            start: Mapping[str, Any] = {}
        elif mode == "profile":
            profile = self._profile()
            start = importer.from_profile(profile) if profile else {}
        elif mode == "upload":
            profile = self._profile()
            if not profile:
                raise ActionError("Save your details on the Profile tab first: the resume you uploaded is kept there.")
            start, notes = importer.from_uploaded(profile)
        else:
            raise ActionError("Choose how to start: blank, from your details, or from your uploaded resume.")
        title = _text(body.get("title"), store.LIMITS["title"], "title")
        made = store.create(self.paths, {**start, **({"title": title} if title.strip() else {})})
        return {"resume": made, "notes": notes, "pages": render.estimate_pages(made)}

    @plainly
    def save(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        with self._writes:  # the version check and the write are one step: two saves of the same version cannot both win
            saved = store.save(self.paths, body.get("id"), body.get("resume"), body.get("version"))
        return {"resume": saved, "pages": render.estimate_pages(saved)}

    @plainly
    def duplicate(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        title = _text(body.get("title"), store.LIMITS["title"], "title").strip() or None
        with self._writes:
            return {"resume": store.duplicate(self.paths, body.get("id"), title)}

    @plainly
    def delete(self, body: Mapping[str, Any]) -> Dict[str, bool]:
        with self._writes:
            store.remove(self.paths, body.get("id"))
        return {"deleted": True}

    # -- checking and tailoring ------------------------------------------------------------------
    @plainly
    def check(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """The ATS report on the resume as it is in the editor, and with a job description pasted, how well it fits that job."""
        doc = store.normalize(body.get("resume"))
        job = _text(body.get("job"), MAX_JOB_TEXT, "job description").strip()
        coverage = tailor.coverage(doc, job, self._words(body.get("extra"))) if job else None
        return ats.analyze(doc, coverage)

    def _words(self, typed: object) -> List[str]:
        """The words to look for besides the shared skills list: what you typed, then your own profile skills and search words that the list does not know."""
        typed = [word for word in typed if isinstance(word, str)][:MAX_EXTRA] if isinstance(typed, list) else []
        profile, criteria = self._profile(), self._criteria()
        own = list(profile.skills) if profile else []
        own += criteria.keywords if criteria else []
        return typed + [word for word in own if not skills_vocab.detect_skills(word)][:MAX_EXTRA]

    def _criteria(self) -> Optional[Criteria]:
        try:
            return load_criteria(self.paths) if self.paths.criteria.exists() else None
        except (OSError, ValueError, TypeError):
            return None

    @plainly
    def add_skill(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """A skill you said you really have, added to the skills of the resume in the editor. Never called by anything but that press."""
        name = _text(body.get("name"), store.LIMITS["item"], "skill").strip()
        return {"skills": tailor.with_skill(store.normalize(body.get("resume")), name)["skills"]}

    # -- the AI ----------------------------------------------------------------------------------
    @plainly
    def suggest(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Rewrites of one bullet, or summaries, from the AI helper. Suggestions only: nothing is changed here."""
        kind, doc = body.get("kind"), store.normalize(body.get("resume"))
        db = Database(self.paths.db)  # the daily limit counts this like any other request
        try:
            helper = self._make_ai(self.paths, db)
            if kind == "bullet":
                emphasise = [word for word in (body.get("emphasise") if isinstance(body.get("emphasise"), list) else []) if isinstance(word, str)][:MAX_EXTRA]
                result = helper.rewrite_bullet(doc, _text(body.get("bullet"), store.LIMITS["bullet"], "bullet"), _text(body.get("title"), store.LIMITS["short"], "title"), emphasise)
            elif kind == "summary":
                result = helper.summaries(doc)
            else:
                raise ActionError("Ask for a better bullet or for a summary.")
        finally:
            db.conn.close()
        return {"options": result.options, "dropped": result.dropped}

    # -- the page and the file -------------------------------------------------------------------
    def _page(self, resume_id: object, template: object) -> Tuple[Dict[str, Any], str]:
        doc = store.load(self.paths, resume_id)
        chosen = template if isinstance(template, str) and template else None
        return doc, render.document(render.render(doc, chosen), doc["title"])

    @plainly
    def preview(self, resume_id: object, template: object = "") -> str:
        """The resume as a complete page: what the PDF is printed from, so what you see is what you get."""
        return self._page(resume_id, template)[1]

    @plainly
    def export(self, resume_id: object, template: object = "") -> Tuple[bytes, str, int]:
        """(the PDF, its file name, its page count)."""
        doc, page = self._page(resume_id, template)
        made = self._make_pdf(page, doc["theme"]["page"])
        return made.data, pdf.filename(doc["basics"]["name"]), made.pages

    @plainly
    def use(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Make this resume the one your runs send: print it, keep the file where an uploaded resume is kept, and point your profile at it."""
        if body.get("confirm") is not True:
            raise ActionError("Confirm that this resume should replace the one your runs send.")
        profile = self._profile()
        if not profile:
            raise ActionError("Save your details on the Profile tab first: that is where the resume your runs send is chosen.")
        data, name, pages = self.export(body.get("id"), body.get("template"))
        self.paths.resume_dir.mkdir(parents=True, exist_ok=True)
        destination, staging = self.paths.resume_dir / name, self.paths.resume_dir / f"new-{name}"
        staging.write_bytes(data)
        try:
            read_text(staging)  # the file must read back, as an uploaded one must, before it replaces anything
        except Exception as exc:  # pypdf raises many different errors on a damaged PDF
            staging.unlink(missing_ok=True)
            raise ActionError(f"The PDF could not be read back ({str(exc)[:120]}), so nothing was changed. Try again.") from exc
        try:
            staging.replace(destination)
        except OSError as exc:  # Windows will not replace a file another program has open (a PDF viewer, a virus scanner)
            staging.unlink(missing_ok=True)
            raise ActionError(f"{name} could not be replaced ({exc.strerror or exc}). If it is open in another program, close it and try again. "
                              "Nothing was changed.") from exc
        added = sync_profile(profile, destination)  # as when you upload one: new skills get unknown years, never made-up ones
        save_profile(profile, self.paths)
        return {"file": name, "pages": pages, "added": added}
