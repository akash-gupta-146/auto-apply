"""A resume as data: the one thing the editor, the preview, the PDF, the ATS check and the AI all read.

A resume is a plain dict (JSON on disk, one file per resume in data/resumes/). Everything that comes in goes through `normalize`, which builds a
clean document from untrusted input: unknown keys dropped, text cut to a sensible length, dates and web addresses checked. So nothing stored, and
nothing rendered later, can be anything but short plain text. Templates only change how it looks, never what it says.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse

from ..agent.session import atomic_write
from ..config import Paths

SECTIONS = ("summary", "experience", "education", "skills", "projects", "certifications", "languages")  # the default order
HEADINGS = {"summary": "Summary", "experience": "Experience", "education": "Education", "skills": "Skills",
            "projects": "Projects", "certifications": "Certifications", "languages": "Languages"}  # the plain names an ATS looks for
TEMPLATES = ("classic", "compact", "modern", "sidebar")
FONTS, SPACINGS, PAGES = ("sans", "serif"), ("compact", "normal", "relaxed"), ("A4", "Letter")
SIZES = (9.5, 10, 10.5, 11, 11.5, 12)  # font size in points
DEFAULT_THEME = {"font": "sans", "size": 10.5, "accent": "#1f4e8c", "spacing": "normal", "page": "A4"}
LIMITS = {"title": 80, "short": 120, "long": 300, "summary": 1200, "bullet": 400, "bullets": 12, "entries": 20, "links": 6, "items": 40, "item": 60}

ID = re.compile(r"^[0-9a-f]{12}$")
ENTRY_ID = re.compile(r"^[0-9a-f]{8}$")
DATE = re.compile(r"^(?:19|20)\d\d-(?:0[1-9]|1[0-2])$")
ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")
PRESENT = "present"
PLACEHOLDER = re.compile(r"\[[^\[\]]{1,20}\]")  # [X%], [N users]: a blank the AI leaves for you to fill in, which must not reach an employer


class NotFound(LookupError):
    """No such resume (or not a resume id at all: an id is checked before it is ever made into a path)."""


class Conflict(RuntimeError):
    """The resume was saved somewhere else since this copy was loaded (another tab): saving would overwrite that."""


# -- cleaning what comes in ---------------------------------------------------------------------------------------------------------------
def _text(value: object, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _date(value: object, allow_present: bool = False) -> str:
    text = _text(value, 12).lower()
    return text if DATE.match(text) or (allow_present and text == PRESENT) else ""


def _url(value: object) -> str:
    text = _text(value, LIMITS["long"])
    return text if urlparse(text).scheme in ("http", "https") and urlparse(text).netloc else ""


def _lines(value: object, each: int, most: int) -> List[str]:
    found = [_text(line, each) for line in (value if isinstance(value, list) else [])]
    return [line for line in found if line][:most]


def _entries(value: object) -> List[Mapping]:
    return [entry for entry in (value if isinstance(value, list) else []) if isinstance(entry, Mapping)][:LIMITS["entries"]]


def _entry_id(entry: Mapping) -> str:
    given = entry.get("id")
    return given if isinstance(given, str) and ENTRY_ID.match(given) else secrets.token_hex(4)


def _items(value: object) -> List[str]:
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    seen, items = set(), []
    for item in (value if isinstance(value, list) else []):
        text = _text(item, LIMITS["item"])
        if text and text.lower() not in seen:
            seen.add(text.lower())
            items.append(text)
    return items[:LIMITS["items"]]


def _theme(raw: object) -> Dict[str, Any]:
    raw = raw if isinstance(raw, Mapping) else {}
    size = raw.get("size")
    return {"font": raw.get("font") if raw.get("font") in FONTS else DEFAULT_THEME["font"],
            "size": size if size in SIZES and not isinstance(size, bool) else DEFAULT_THEME["size"],
            "accent": raw["accent"].lower() if isinstance(raw.get("accent"), str) and ACCENT.match(raw["accent"]) else DEFAULT_THEME["accent"],
            "spacing": raw.get("spacing") if raw.get("spacing") in SPACINGS else DEFAULT_THEME["spacing"],
            "page": raw.get("page") if raw.get("page") in PAGES else DEFAULT_THEME["page"]}


def _basics(raw: object) -> Dict[str, Any]:
    raw = raw if isinstance(raw, Mapping) else {}
    links = []
    for link in _entries(raw.get("links"))[:LIMITS["links"]]:
        url = _url(link.get("url"))
        if url:
            links.append({"label": _text(link.get("label"), LIMITS["short"]) or urlparse(url).netloc, "url": url})
    return {"name": _text(raw.get("name"), LIMITS["short"]), "headline": _text(raw.get("headline"), LIMITS["long"]),
            "email": _text(raw.get("email"), LIMITS["short"]), "phone": _text(raw.get("phone"), 40),
            "location": _text(raw.get("location"), LIMITS["short"]), "links": links}


def _kept(entries: Iterable[Dict[str, Any]], *fields: str) -> List[Dict[str, Any]]:
    """Entries that say anything at all: one with every field empty is a form row nobody filled in."""
    return [entry for entry in entries if any(entry[field] for field in fields)]


def _sections(raw: Mapping) -> Dict[str, Any]:
    short, bullets = LIMITS["short"], lambda value: _lines(value, LIMITS["bullet"], LIMITS["bullets"])
    return {
        "summary": _text(raw.get("summary"), LIMITS["summary"]),
        "experience": _kept(({"id": _entry_id(e), "company": _text(e.get("company"), short), "title": _text(e.get("title"), short),
                              "location": _text(e.get("location"), short), "start": _date(e.get("start")), "end": _date(e.get("end"), True),
                              "bullets": bullets(e.get("bullets"))} for e in _entries(raw.get("experience"))), "company", "title", "bullets"),
        "education": _kept(({"id": _entry_id(e), "school": _text(e.get("school"), short), "degree": _text(e.get("degree"), short),
                             "field": _text(e.get("field"), short), "start": _date(e.get("start")), "end": _date(e.get("end"), True),
                             "details": bullets(e.get("details"))} for e in _entries(raw.get("education"))), "school", "degree", "details"),
        "skills": _kept(({"id": _entry_id(e), "group": _text(e.get("group"), short), "items": _items(e.get("items"))}
                         for e in _entries(raw.get("skills"))), "items"),
        "projects": _kept(({"id": _entry_id(e), "name": _text(e.get("name"), short), "url": _url(e.get("url")), "bullets": bullets(e.get("bullets"))}
                           for e in _entries(raw.get("projects"))), "name", "bullets"),
        "certifications": _kept(({"id": _entry_id(e), "name": _text(e.get("name"), short), "issuer": _text(e.get("issuer"), short),
                                  "date": _date(e.get("date"))} for e in _entries(raw.get("certifications"))), "name"),
        "languages": _kept(({"id": _entry_id(e), "name": _text(e.get("name"), short), "level": _text(e.get("level"), 40)}
                            for e in _entries(raw.get("languages"))), "name"),
    }


def _order(raw: object) -> List[str]:
    chosen = [s for s in (raw if isinstance(raw, list) else []) if s in SECTIONS]
    unique = list(dict.fromkeys(chosen))
    return unique + [s for s in SECTIONS if s not in unique]  # a section left out of the list is still there, at the end


def normalize(raw: object) -> Dict[str, Any]:
    """A clean resume from whatever was sent: the content only (the id, version and time are the store's). Normalising a normal resume changes nothing."""
    raw = raw if isinstance(raw, Mapping) else {}
    hidden = [s for s in dict.fromkeys(raw.get("hidden") if isinstance(raw.get("hidden"), list) else []) if s in SECTIONS]
    template = raw.get("template")
    return {"title": _text(raw.get("title"), LIMITS["title"]) or "My resume", "template": template if template in TEMPLATES else TEMPLATES[0],
            "theme": _theme(raw.get("theme")), "order": _order(raw.get("order")), "hidden": hidden,
            "basics": _basics(raw.get("basics")), **_sections(raw)}


# -- what a resume says -------------------------------------------------------------------------------------------------------------------
def has_content(doc: Mapping, section: str) -> bool:
    return bool(doc.get(section))


def visible_sections(doc: Mapping) -> List[str]:
    """The sections that are in the resume, in order: not hidden, and not empty. What the preview, the PDF and the ATS check all see."""
    return [s for s in doc["order"] if s not in doc["hidden"] and has_content(doc, s)]


def bullets_of(entry: Mapping) -> List[str]:
    return list(entry.get("bullets") or entry.get("details") or [])


def full_text(doc: Mapping) -> str:
    """All the words a reader of the resume would read, one line each: what keywords are looked for in."""
    basics, lines = doc["basics"], [doc["basics"]["name"], doc["basics"]["headline"]]
    lines += [basics["email"], basics["phone"], basics["location"]]
    for section in visible_sections(doc):
        if section == "summary":
            lines.append(doc["summary"])
            continue
        for entry in doc[section]:
            lines += [str(value) for key, value in entry.items() if key != "id" and isinstance(value, str)]
            lines += bullets_of(entry) + list(entry.get("items") or [])
    return "\n".join(line for line in lines if line)


# -- keeping them -------------------------------------------------------------------------------------------------------------------------
def new_id() -> str:
    return secrets.token_hex(6)


def _file(paths: Paths, resume_id: object):
    if not isinstance(resume_id, str) or not ID.match(resume_id):
        raise NotFound("There is no such resume.")
    return paths.resumes / f"{resume_id}.json"


def _stamp(doc: Dict[str, Any], resume_id: str, version: int, updated: str = "") -> Dict[str, Any]:
    return {"id": resume_id, "version": version, "updated": updated or datetime.now().isoformat(timespec="seconds"), **doc}


def _write(paths: Paths, doc: Dict[str, Any]) -> Dict[str, Any]:
    atomic_write(_file(paths, doc["id"]), json.dumps(doc, ensure_ascii=False, indent=1))
    return doc


def create(paths: Paths, raw: object = None) -> Dict[str, Any]:
    return _write(paths, _stamp(normalize(raw), new_id(), 1))


def load(paths: Paths, resume_id: object) -> Dict[str, Any]:
    try:
        data = json.loads(_file(paths, resume_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise NotFound("There is no such resume.") from None
    if not isinstance(data, dict):
        raise NotFound("That resume file is damaged.")
    version = data["version"] if isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool) else 1
    return _stamp(normalize(data), resume_id, version, str(data.get("updated", "")))


def save(paths: Paths, resume_id: object, raw: object, version: object) -> Dict[str, Any]:
    """Keep an edited resume. `version` is the one the editor loaded: if the file has moved on since, nothing is overwritten."""
    current = load(paths, resume_id)
    if version != current["version"]:
        raise Conflict("This resume was changed somewhere else (another tab?). Reload it to see the latest.")
    return _write(paths, _stamp(normalize(raw), current["id"], current["version"] + 1))


def duplicate(paths: Paths, resume_id: object, title: Optional[str] = None) -> Dict[str, Any]:
    original = load(paths, resume_id)
    copy = normalize({**original, "title": title or f"{original['title']} (copy)"})
    for section in SECTIONS:  # a copy has entries of its own: ids are only for telling rows apart
        if isinstance(copy[section], list):
            for entry in copy[section]:
                entry["id"] = secrets.token_hex(4)
    return _write(paths, _stamp(copy, new_id(), 1))


def remove(paths: Paths, resume_id: object) -> None:
    path = _file(paths, resume_id)
    if not path.exists():
        raise NotFound("There is no such resume.")
    path.unlink()  # gone for good: there is no copy kept


def listing(paths: Paths) -> List[Dict[str, Any]]:
    """What the dashboard shows, newest edit first. A damaged file is left out, not allowed to hide the others."""
    found = []
    for path in sorted(paths.resumes.glob("*.json")) if paths.resumes.is_dir() else []:
        try:
            doc = load(paths, path.stem)
        except NotFound:
            continue
        found.append({"id": doc["id"], "title": doc["title"], "template": doc["template"], "updated": doc["updated"], "name": doc["basics"]["name"]})
    return sorted(found, key=lambda item: item["updated"], reverse=True)
