"""What the profile and AI-helper pages do: keep an uploaded resume, check the forms, save profile.yaml,
criteria.yaml and the AI settings. No HTTP in here; `server.py` carries the requests."""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import httpx

from . import pages
from ..ai_facts import build_fact_judge
from ..ai_fill import suggest
from ..ai_providers import add_custom_provider, remove_custom_provider
from ..ai_settings import (AiSettings, about_files, check_all, load_ai_settings, make_client, read_notes,
                           save_ai_settings, save_notes)
from ..config import ConfigError, Criteria, Paths, Profile, load_criteria, load_profile, save_criteria, save_profile
from ..db import Database
from ..llm import BudgetExceeded, LlmError
from ..resume import guess_facts, read_text, sync_profile
from .ai_form import MAX_BACKUPS, backup_fields, parse_ai_form
from . import questions
from .forms import (
    ALL_FIELDS,
    MAX_UPLOAD_BYTES,
    apply_form,
    ai_fill_summary,
    form_values,
    merge_suggestions,
    parse_form,
    safe_resume_name,
    skills_with_years,
    typed_skills,
)

DEFAULT_PORT = 8765
ENVELOPE_BYTES = 64 * 1024  # room for form fields around an upload
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                               "base-uri 'none'; frame-ancestors 'none'",
}


class UploadError(Exception):
    """An uploaded document that cannot be used; the message is written for the person."""


class UiApp:
    """What the pages do. No HTTP in here."""

    def __init__(self, paths: Paths):
        self.paths = paths
        self.http: Optional[httpx.Client] = None  # None = the real network; tests plug a fake one in
        self.token = secrets.token_urlsafe(24)
        self.allowed_hosts: set = set()
        self.resume: Optional[Path] = None  # uploaded during this session
        self.facts: Dict[str, object] = {}  # what was read off that resume

    def token_ok(self, candidate: Optional[str]) -> bool:
        return hmac.compare_digest((candidate or "").encode(), self.token.encode())

    def saved_profile(self) -> Optional[Profile]:
        return load_profile(self.paths) if self.paths.profile.exists() else None

    def _resume_path(self) -> Optional[Path]:
        saved = self.saved_profile()
        return self.resume or (Path(saved.resume_path) if saved and saved.resume_path else None)

    def resume_name(self) -> str:
        path = self._resume_path()
        return path.name if path else ""

    def upload_html(self, error: str = "") -> str:
        return pages.upload_page(self.token, error, has_saved_profile=bool(self.saved_profile()))

    @staticmethod
    def _store_upload(folder: Path, filename: str, data: bytes) -> Tuple[Path, str]:
        """Check an uploaded document, keep it in `folder`, return (where, its text). Raises UploadError."""
        name = safe_resume_name(filename or "")
        if not name:
            raise UploadError("Please choose a PDF, DOCX or TXT file.")
        if not data:
            raise UploadError("That file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise UploadError("That file is larger than 10 MB.")
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / name
        destination.write_bytes(data)
        try:
            return destination, read_text(destination)
        except Exception as exc:  # pypdf raises many different errors on a damaged PDF
            destination.unlink(missing_ok=True)
            raise UploadError(
                f"I could not read that file ({str(exc)[:160]}). Try saving it again as PDF or DOCX.") from exc

    def accept_resume(self, filename: str, data: bytes) -> str:
        """Keep an uploaded resume. Returns an error message for the person, or '' on success."""
        try:
            destination, text = self._store_upload(self.paths.resume_dir, filename, data)
        except UploadError as exc:
            return str(exc)
        self.resume, self.facts = destination, guess_facts(text)
        return ""

    def has_resume(self) -> bool:
        return bool(self.resume_name())

    def form_html(self, values: Optional[Mapping[str, str]] = None, errors: Optional[Mapping[str, str]] = None,
                  skill_rows: Optional[Sequence[Tuple[str, str]]] = None, focus_new_skill: bool = False,
                  banner: Tuple[str, str] = ("", "")) -> str:
        profile = self.saved_profile() or Profile()
        if values is None:
            values = form_values(profile, load_criteria(self.paths), self.facts)
        if skill_rows is None:  # the skills already given years, and an empty row to start typing in
            skill_rows = skills_with_years(profile) + [("", "")]
        settings = load_ai_settings(self.paths)
        ai_provider = ""
        if settings.configured:
            ai_provider = settings.providers()[settings.provider].label
            if settings.backups:  # the resume text may go to a backup when the main AI errors: say so where it is sent
                ai_provider += " (or, if it errors, a backup AI you added)"
        return pages.form_page(self.token, values, errors or {}, skill_rows, self.resume_name(), focus_new_skill,
                               banner, ai_provider)

    @staticmethod
    def _typed(raw: Mapping[str, str]) -> Dict[str, str]:
        return {spec.name: raw.get(spec.name, "") for spec in ALL_FIELDS}

    def form_with_another_skill(self, raw: Mapping[str, str]) -> str:
        """The form again, everything typed so far kept, with one more empty skill row. Nothing is checked or saved."""
        return self.form_html(self._typed(raw), {}, typed_skills(raw) + [("", "")], focus_new_skill=True)

    def _ask_ai_about_resume(self):
        """What the AI suggests from the resume. Raises ConfigError / LlmError with a message written for the person."""
        settings = load_ai_settings(self.paths)
        if not settings.configured:
            raise ConfigError("The AI helper is not set up yet. Open the AI helper page, choose an AI and add a key.")
        path = self._resume_path()
        text = read_text(path) if path else ""
        if not text.strip():
            raise ConfigError("I could not read any text in your resume, so there is nothing for the AI to read. "
                              "If it is a scanned picture, save it again as a text PDF or DOCX.")
        db = Database(self.paths.db)  # the daily limit counts this request like any other
        try:
            return suggest(make_client(settings, db, self.http), text)
        finally:
            db.conn.close()

    def form_with_ai(self, raw: Mapping[str, str]) -> str:
        """The AI Fill button: the form again with the AI's suggestions in the EMPTY boxes. Nothing is saved."""
        values, rows = self._typed(raw), typed_skills(raw) or [("", "")]
        try:
            found = self._ask_ai_about_resume()
        except BudgetExceeded:
            banner = ("error", "The AI helper's daily limit is used up. Raise it on the AI helper page, or try tomorrow.")
        except (ConfigError, LlmError) as exc:
            banner = ("error", f"AI Fill did not work: {str(exc)[:400]}")
        else:
            filled = merge_suggestions(values, rows, found)
            values, rows, banner = filled.values, filled.rows, ("ok", ai_fill_summary(filled, found.ignored))
        return self.form_html(values, {}, rows, banner=banner)

    def accept_form(self, raw: Mapping[str, str]) -> Optional[str]:
        """Save the answers. Returns None when saved, or the page to show again with the errors."""
        parsed = parse_form(raw)
        if parsed.errors:
            return self.form_html(self._typed(raw), parsed.errors, typed_skills(raw) or [("", "")])
        profile: Profile = self.saved_profile() or Profile()
        criteria: Criteria = load_criteria(self.paths)
        if self.resume:
            sync_profile(profile, self.resume)  # points at the resume; new skills get unknown years
        apply_form(parsed, profile, criteria)
        save_profile(profile, self.paths)
        save_criteria(criteria, self.paths)
        return None

    def done_html(self) -> str:
        profile = self.saved_profile() or Profile()
        return pages.done_page(profile.name, self.resume_name(), str(self.paths.profile), str(self.paths.criteria))

    # -- the AI helper page ----------------------------------------------------------------------
    @staticmethod
    def _saved_ai_values(saved: AiSettings, notes: str) -> Dict[str, str]:
        values = {"provider": saved.provider, "model": saved.model, "daily_cap": str(saved.daily_cap), "notes": notes}
        for slot, backup in enumerate(saved.backups[:MAX_BACKUPS], start=1):  # keys are never sent back to the page
            name_provider, name_model, _ = backup_fields(slot)
            values[name_provider], values[name_model] = backup.provider, backup.model
        return values

    def ai_html(self, values: Optional[Mapping[str, str]] = None, errors: Optional[Mapping[str, str]] = None,
                banner: Tuple[str, str] = ("", "")) -> str:
        saved = load_ai_settings(self.paths)
        if values is None:
            values = self._saved_ai_values(saved, read_notes(self.paths))
        names = [path.name for path in about_files(self.paths)]
        return pages.ai_page(self.token, values, errors or {}, saved, names, banner)

    def accept_ai(self, fields: Mapping[str, str], files: Mapping[str, Tuple[str, bytes]]) -> Optional[str]:
        """Save the AI settings, notes and an optional document. None when saved, else the page to show again."""
        parsed = parse_ai_form(fields, load_ai_settings(self.paths))
        errors = dict(parsed.errors)
        filename, data = files.get("about_file", ("", b""))
        if filename and errors:
            errors["about_file"] = "Please choose the document again after fixing the problems above."
        elif filename:
            try:
                self._store_upload(self.paths.about, filename, data)
            except UploadError as exc:
                errors["about_file"] = str(exc)
        if errors:  # all or nothing: a half-saved setup is worse than none
            typed_names = ("provider", "model", "daily_cap", "notes") + tuple(
                name for slot in range(1, MAX_BACKUPS + 1) for name in backup_fields(slot)[:2])  # never a key
            typed = {name: fields.get(name, "") for name in typed_names}
            return self.ai_html(typed, errors)
        save_ai_settings(parsed.settings, self.paths)
        save_notes(self.paths, parsed.notes)
        return None

    def add_provider(self, fields: Mapping[str, str]) -> Optional[str]:
        """Add an AI that is not in the list. None when added, else the page to show again with what is wrong."""
        saved = load_ai_settings(self.paths)
        updated, errors = add_custom_provider(saved, fields)
        if errors:
            typed = {**self._saved_ai_values(saved, read_notes(self.paths)),
                     **{name: fields.get(name, "") for name in ("custom_name", "custom_url", "custom_style", "custom_needs_key")}}
            return self.ai_html(typed, errors)
        save_ai_settings(updated, self.paths)
        return None

    def remove_provider(self, key: str) -> Tuple[str, str]:
        """Remove an AI the person added. (kind, message) for the page: the main AI cannot be removed."""
        saved = load_ai_settings(self.paths)
        updated, problem = remove_custom_provider(saved, key)
        if problem:
            return "error", problem
        if updated is not saved:
            save_ai_settings(updated, self.paths)
            return "ok", f"Removed {saved.custom[key].label}."
        return "", ""

    def remove_about(self, name: str) -> None:
        for path in about_files(self.paths):
            if path.name == name:  # only names we listed ourselves: nothing typed can point elsewhere
                path.unlink()

    # -- the questions page ----------------------------------------------------------------------
    def questions_html(self, banner: Tuple[str, str] = ("", ""), saved_open: bool = False) -> str:
        return pages.questions_page(self.token, questions.waiting(self.paths), banner, questions.saved(self.paths), saved_open)

    def accept_answers(self, form: Mapping[str, str]) -> int:
        return questions.save(self.paths, form, build_fact_judge(self.paths))  # None when no AI is set up: saved as typed

    def forget_answer(self, question: str) -> bool:
        return questions.forget(self.paths, question)

    def change_answer(self, question: str, answer: str) -> bool:
        return questions.change(self.paths, question, answer)

    def test_ai(self) -> Tuple[str, str]:
        results = check_all(load_ai_settings(self.paths), self.http)
        if not results:
            return "error", "The AI did not accept the request: Choose an AI, a model, and enter a key first."
        if len(results) == 1:
            label, problem = results[0]
            if problem:
                return "error", f"The AI did not accept the request: {problem}"
            return "ok", "It works: the AI answered, so your key and model are fine."
        lines = [f"{'Main AI' if n == 0 else f'Backup {n}'} ({label}): " + (f"did not accept the request: {problem}" if problem else "works.")
                 for n, (label, problem) in enumerate(results)]
        if any(problem for _, problem in results):
            return "error", "\n".join(lines)
        return "ok", "It works: every AI answered.\n" + "\n".join(lines)
