"""The logic behind the profile and AI forms, with no HTTP in it: what the form asks, and how an answer becomes
a Profile / Criteria. Everything here is a pure function, so it is tested without a server."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from typing import Dict, List, Mapping, Optional, Tuple

from ..ai_fill import Suggestions
from ..config import Criteria, Profile
from ..resume import normalize_phone

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RESUME_SUFFIXES = (".pdf", ".docx", ".txt")
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
SKILL_NAME, SKILL_YEARS = "skill_name_", "skill_years_"  # one pair of boxes per row: skill_name_0 / skill_years_0, ...
SKILL_KEY = re.compile(r"^skill_(name|years)_(\d+)$")
ADD_SKILL = "add_skill"  # the button that adds a blank row
AI_FILL = "ai_fill"  # the button that has the AI fill the empty boxes from the resume
MAX_SKILL_YEARS = 60
MAX_SKILL_NAME = 60


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"  # text | email | tel | number | integer | percent | checkbox | list
    required: bool = False
    hint: str = ""


PROFILE_FIELDS = (
    Field("name", "Full name", required=True),
    Field("email", "Email", "email", True),
    Field("phone", "Mobile number", "tel", True, "10 digits. +91 and spaces are fine."),
    Field("city", "Current city"),
    Field("current_title", "Current job title"),
    Field("current_company", "Current company"),
    Field("total_experience_years", "Total years of experience", "number", True, "Decimals are fine, e.g. 8.5"),
    Field("notice_period", "Notice period", hint="e.g. Immediate, or 30 days"),
    Field("current_ctc", "Current CTC", hint="e.g. 12 LPA"),
    Field("expected_ctc", "Expected CTC", hint="e.g. 18 LPA"),
    Field("education", "Highest education", hint="Degree, college, year"),
    Field("linkedin", "LinkedIn URL (optional)"),
    Field("github", "GitHub URL (optional)"),
    Field("portfolio", "Portfolio URL (optional)"),
    Field("willing_to_relocate", "I am willing to relocate", "checkbox"),
    Field("ok_with_onsite", "I am OK with hybrid or work-from-office jobs", "checkbox"),
)

CRITERIA_FIELDS = (
    Field("target_roles", "Job titles to apply for", "list", True,
          "Comma separated. List the variants, e.g. frontend engineer, react developer. A generic title like Software Developer is also applied to when the job text is clearly about these"),
    Field("keywords", "Keywords (optional)", "list",
          hint="Comma separated, e.g. react, design systems, accessibility. A job whose title, experience or description "
               "uses at least two of them is applied to even when its title is not in your list, if your skills fit it too"),
    Field("skip_roles", "Titles to skip", "list", hint="Comma separated, e.g. qa, sales"),
    Field("locations", "Locations", "list", hint="Comma separated, e.g. Bengaluru, Hyderabad"),
    Field("blocked_companies", "Companies to never apply to", "list", hint="Comma separated"),
    Field("min_score", "Minimum skill match, in %", "percent",
          hint="A job names some skills; this is the share of them that you have. A job below it is skipped. 10 applies to almost "
               "anything that fits you, 50 only to close matches, 0 switches the check off for jobs with one of your titles"),
    Field("min_salary_lpa", "Minimum salary in LPA (optional)", "number",
          hint="Only enforced when a job shows its salary"),
    Field("max_applications_per_run", "Most applications in one run", "integer", True,
          "The most one run will send. Start small (like 5) until you have seen it work."),
)

ALL_FIELDS = PROFILE_FIELDS + CRITERIA_FIELDS


@dataclass
class ParsedForm:
    profile: Dict[str, object] = field(default_factory=dict)
    criteria: Dict[str, object] = field(default_factory=dict)
    skills: Dict[str, float] = field(default_factory=dict)  # name -> years, only what was filled in
    skills_listed: bool = False  # did the form carry the skills section at all (a post without it must not wipe years)
    errors: Dict[str, str] = field(default_factory=dict)


# -- reading what the browser sent ----------------------------------------------------------------
def parse_multipart(content_type: str, body: bytes) -> Tuple[Dict[str, str], Dict[str, Tuple[str, bytes]]]:
    """Fields and uploaded files from a multipart/form-data body.

    Uses the email parser: the stdlib `cgi` module was removed in Python 3.13.
    """
    raw = b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    message = BytesParser(policy=policy.HTTP).parsebytes(raw)
    fields: Dict[str, str] = {}
    files: Dict[str, Tuple[str, bytes]] = {}
    if not message.is_multipart():
        return fields, files
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            files[name] = (filename, payload)
        else:
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


def safe_resume_name(filename: str) -> Optional[str]:
    """A harmless file name for an upload, or None when the type is not a resume type."""
    name = re.sub(r"[^\w.\- ]", "_", filename.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in RESUME_SUFFIXES:
        return None
    stem = name[: -len(suffix)][:60] or "resume"
    return stem + suffix


def split_list(text: str) -> List[str]:
    seen: List[str] = []
    for item in re.split(r"[,\n;]", text):
        item = item.strip()
        if item and item.lower() not in {s.lower() for s in seen}:
            seen.append(item)
    return seen


# -- turning answers into config ------------------------------------------------------------------
def _number(spec: Field, text: str, errors: Dict[str, str]) -> Optional[float]:
    try:
        value = float(text)
    except ValueError:
        errors[spec.name] = f"{spec.label}: enter a number."
        return None
    if value < 0:
        errors[spec.name] = f"{spec.label}: cannot be negative."
        return None
    if spec.kind == "percent":  # 0 is a real answer here (no skill check), unlike a count
        if value != int(value) or value > 100:
            errors[spec.name] = f"{spec.label}: enter a whole number from 0 to 100."
            return None
        return int(value)
    if spec.kind == "integer":
        if value != int(value) or value < 1:
            errors[spec.name] = f"{spec.label}: enter a whole number, at least 1."
            return None
        return int(value)
    return value


def _read_one(spec: Field, raw: Mapping[str, str], out: Dict[str, object], errors: Dict[str, str]) -> None:
    if spec.kind == "checkbox":  # browsers send unchecked boxes as nothing at all
        out[spec.name] = spec.name in raw
        return
    text = raw.get(spec.name, "").strip()
    empty: object = [] if spec.kind == "list" else None if spec.kind in ("number", "integer") else ""
    if not text:
        if spec.kind == "percent":
            return  # nothing typed (or an older page that has no such box): keep what is saved, never wipe it
        out[spec.name] = empty
        if spec.required:
            errors[spec.name] = f"{spec.label} is required."
        return
    if spec.kind == "list":
        out[spec.name] = split_list(text)
    elif spec.kind in ("number", "integer", "percent"):
        out[spec.name] = _number(spec, text, errors)
    elif spec.kind == "tel":
        digits = normalize_phone(text)
        out[spec.name] = digits
        if len(digits) != 10:
            errors[spec.name] = f"{spec.label}: enter a 10-digit mobile number."
    elif spec.kind == "email":
        out[spec.name] = text
        if not EMAIL.match(text):
            errors[spec.name] = f"{spec.label}: that does not look like an email address."
    else:
        out[spec.name] = text


def typed_skills(raw: Mapping[str, str]) -> List[Tuple[str, str]]:
    """The (name, years) rows exactly as typed, in page order. An empty pair is a blank row."""
    rows: Dict[int, Dict[str, str]] = {}
    for key, text in raw.items():
        match = SKILL_KEY.match(key)
        if match:
            rows.setdefault(int(match.group(2)), {})[match.group(1)] = text
    return [(row.get("name", ""), row.get("years", "")) for _, row in sorted(rows.items())]


def _read_skills(raw: Mapping[str, str], errors: Dict[str, str]) -> Dict[str, float]:
    """A skill is a name AND the years: a name alone would be a skill nobody could answer a question about."""
    skills: Dict[str, float] = {}
    for n, (name, text) in enumerate(typed_skills(raw)):
        name, text = " ".join(name.split()).lower(), text.strip()  # saved the way the resume reader saves them
        if not name and not text:
            continue  # a blank row
        if not name:
            errors[f"{SKILL_NAME}{n}"] = f"Skill {n + 1}: enter the skill's name, or clear its years."
        elif len(name) > MAX_SKILL_NAME:
            errors[f"{SKILL_NAME}{n}"] = f"Skill {n + 1}: the name is too long ({MAX_SKILL_NAME} characters at most)."
        elif name in skills:
            errors[f"{SKILL_NAME}{n}"] = f"{name} is listed twice: keep one row for it."
        else:
            try:
                years = float(text)
            except ValueError:
                years = -1
            if 0 <= years <= MAX_SKILL_YEARS:
                skills[name] = years
            else:
                errors[f"{SKILL_YEARS}{n}"] = f"Years of {name}: enter a number between 0 and {MAX_SKILL_YEARS}."
    return skills


def parse_form(raw: Mapping[str, str]) -> ParsedForm:
    parsed = ParsedForm()
    for spec in PROFILE_FIELDS:
        _read_one(spec, raw, parsed.profile, parsed.errors)
    for spec in CRITERIA_FIELDS:
        _read_one(spec, raw, parsed.criteria, parsed.errors)
    parsed.skills = _read_skills(raw, parsed.errors)
    parsed.skills_listed = bool(typed_skills(raw))
    return parsed


def apply_form(parsed: ParsedForm, profile: Profile, criteria: Criteria) -> None:
    for key, value in parsed.profile.items():
        setattr(profile, key, value)
    for key, value in parsed.criteria.items():
        setattr(criteria, key, value)
    if parsed.skills_listed:
        for skill, years in profile.skills.items():
            if years is not None and skill not in parsed.skills:
                profile.skills[skill] = None  # taken off the list: its years are forgotten, so never answered (it still counts for matching)
    profile.skills.update(parsed.skills)


# -- turning config into what the form shows ------------------------------------------------------
def _text(value: object) -> str:
    """6.0 shows as 6, 8.5 stays 8.5."""
    return f"{value:g}" if isinstance(value, float) else str(value)


FACT_FOR_BOX = {"total_experience_years": "years"}  # a box the resume reader calls something else


def form_values(profile: Profile, criteria: Criteria, facts: Mapping[str, object]) -> Dict[str, str]:
    """Current values as strings; blank boxes are filled from what was read off the resume (and stay blank if it said nothing)."""
    values: Dict[str, str] = {}
    for spec in ALL_FIELDS:
        source = criteria if spec in CRITERIA_FIELDS else profile
        current = getattr(source, spec.name)
        if spec.kind == "checkbox":
            values[spec.name] = "on" if current else ""
        elif spec.kind == "list":
            values[spec.name] = ", ".join(current)
        elif spec.kind == "percent":
            values[spec.name] = str(current)  # 0 must show as 0, not as an empty box
        else:
            values[spec.name] = "" if current in (None, "", 0, 0.0) else _text(current)
    for spec in PROFILE_FIELDS:
        fact = facts.get(FACT_FOR_BOX.get(spec.name, spec.name))
        if spec.kind != "checkbox" and not values[spec.name] and fact:
            values[spec.name] = _text(fact)
    return values


def skills_with_years(profile: Profile) -> List[Tuple[str, str]]:
    """The rows to show: only skills whose years the person gave. The resume reader also notes skills it spots, with
    no years, so that job matching can use them; those are not shown here, because a skill without years is no answer."""
    return [(skill, _text(years)) for skill, years in sorted(profile.skills.items()) if years is not None]


# -- AI Fill: what the AI suggested, put into the form --------------------------------------------------------------
@dataclass
class Filled:
    values: Dict[str, str]
    rows: List[Tuple[str, str]]  # the skill rows, ending with an empty one
    boxes: int  # how many boxes were filled
    new_skills: int
    skills_without_years: int  # new skills whose years the resume does not state: the person types them, or clears the row


def merge_suggestions(values: Mapping[str, str], rows: List[Tuple[str, str]], found: Suggestions) -> Filled:
    """Put suggestions into the form WITHOUT touching anything the person has typed: only empty boxes are filled, and a
    skill already in the list keeps its row. (Clear a box and press the button again to have it redone.)"""
    merged = dict(values)
    boxes = 0
    suggested = dict(found.boxes)
    suggested["target_roles"] = ", ".join(found.target_roles)
    suggested["keywords"] = ", ".join(found.keywords)
    for name, text in suggested.items():
        if text and not merged.get(name, "").strip():
            merged[name] = text
            boxes += 1
    kept = [(name, years) for name, years in rows if name.strip() or years.strip()]  # drop the empty rows
    have = {" ".join(name.split()).lower() for name, _ in kept}
    added = [(name, "" if years is None else _text(years)) for name, years in found.skills if name not in have]
    return Filled(merged, kept + added + [("", "")], boxes, len(added), sum(1 for _, years in added if not years))


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def ai_fill_summary(filled: Filled, ignored: int) -> str:
    """What to tell the person after AI Fill: what it did, what is still theirs to do, and what it refused to add.
    One short paragraph per point (a new line between them), so the thing to act on is not buried."""
    if not filled.boxes and not filled.new_skills:
        lines = ["AI Fill found nothing new to add. It only fills empty boxes, and it only adds what your resume backs up."]
    else:
        done = [_count(filled.boxes, "box", "boxes")] if filled.boxes else []
        done += [_count(filled.new_skills, "skill", "skills")] if filled.new_skills else []
        lines = [f"AI Fill added {' and '.join(done)}. Nothing is saved yet: check every box, then press Save."]
    if filled.skills_without_years:
        lines.append(f"{_count(filled.skills_without_years, 'new skill has', 'new skills have')} no years, because your "
                     "resume does not say how long you used them: type the years, or clear the row.")
    if ignored:
        lines.append(f"{_count(ignored, 'suggestion was', 'suggestions were')} left out because your resume does not back them up.")
    return "\n".join(lines)
