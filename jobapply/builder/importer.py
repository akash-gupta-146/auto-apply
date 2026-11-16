"""Start a resume from what the project already knows about you: the resume you uploaded, and your saved profile.

The job and heading parsers are the ones the profile form already uses (resume_details.py). What they cannot read is left empty, never guessed: a date
that gives a year but no month stays blank. The result is a draft for the person to review, and `notes` say what to look at; nothing is sent anywhere.
The details of your *profile* (name, email, phone, city, links) win over what was guessed from the file: you checked those.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Pattern, Tuple

from ..config import Profile
from ..resume import guess_facts, read_text
from ..resume_details import BULLET, COLLEGE, DATE_RANGE, DEGREE, EDUCATION_HEADING, EXPERIENCE_HEADING, SPLITTERS, TITLE, _job_entry, _split_place
from .doc import LIMITS, normalize
from .tailor import pretty

MONTHS = {name: number for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
HEADINGS: Dict[str, Pattern[str]] = {
    "summary": re.compile(r"^(?:professional\s+|career\s+)?(?:summary|profile|objective|about(?:\s+me)?)$", re.I),
    "experience": EXPERIENCE_HEADING,
    "education": EDUCATION_HEADING,
    "skills": re.compile(r"^(?:(?:key|core|technical|professional)\s+)?(?:skills|competencies|technologies|tech\s+stack)(?:\s+summary)?$", re.I),
    "projects": re.compile(r"^(?:(?:personal|academic|key|selected)\s+)?projects$", re.I),
    "certifications": re.compile(r"^(?:licen[sc]es\s*(?:&|and)\s*)?(?:certifications?|certificates|courses)$", re.I),
    "languages": re.compile(r"^languages(?:\s+known)?$", re.I),
}
HEADING_MAX = 40
PARAGRAPH = 70  # chars: a line this long under a job is a sentence about it, not another job's heading
ENDED = re.compile(r"present|current|now|till\s+date", re.I)


def _heading(line: str) -> Optional[str]:
    if len(line.strip()) > HEADING_MAX:
        return None
    text = " ".join(re.sub(r"[^\w&\s]", " ", line).split())
    return next((key for key, pattern in HEADINGS.items() if pattern.match(text)), None)


def _sections(lines: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """The lines before the first heading (the header), and the lines under each heading."""
    header: List[str] = []
    found: Dict[str, List[str]] = {}
    here: Optional[List[str]] = header
    for line in lines:
        key = _heading(line)
        if key and key not in found:
            here = found.setdefault(key, [])
        elif here is not None:
            here.append(line)
    return header, found


def _iso(token: str) -> str:
    match = re.match(r"\s*([a-z]{3})[a-z]*\.?,?\s*((?:19|20)\d\d)", token, re.I)
    return f"{match.group(2)}-{MONTHS[match.group(1).lower()]:02d}" if match and match.group(1).lower() in MONTHS else ""  # a bare year has no month: left for you


def _dates(text: str) -> Tuple[str, str]:
    """(start, end) of the date range in a line, as months; an end of "now" is `present`. A date that is only a year is left blank."""
    found = DATE_RANGE.search(text)
    if not found:
        return "", ""
    pieces = re.split(r"\s*(?:-|\u2013|\u2014|\bto\b)\s*", found.group(0).strip("() "), maxsplit=1, flags=re.I)
    start, end = pieces[0], pieces[-1]
    return _iso(start), "present" if ENDED.search(end) else _iso(end)


def _plain(line: str) -> str:
    return " ".join(BULLET.sub("", line, count=1).split())


def _without_dates(line: str) -> str:
    return " ".join(DATE_RANGE.sub(" ", line).split()).strip(" |,-\u2013\u2014")


def _split_title(title: str, company: str, place: str) -> Tuple[str, str, str]:
    """'Senior Engineer, Acme Corp, Pune' arrives as one title: the job is the first part, and what follows is the company and where it is."""
    first, _, rest = title.partition(",")
    if rest and not company and TITLE.search(first):
        company, place = _split_place(rest.strip())
        return first.strip(), company, place
    return title, company, place


# -- one reader per section --------------------------------------------------------------------------------------------------------------
def _experience(lines: List[str]) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    waiting = ""  # a short line that may turn out to be the company of the job on the next line
    for line in lines:
        job = jobs[-1] if jobs else None
        if BULLET.match(line):
            if job is not None and _plain(line):
                job["bullets"].append(_plain(line))
            continue
        entry = _job_entry(line)
        if entry and (job is None or job["bullets"] or not job["title"]):
            title, company, place = _split_title(*entry)
            jobs.append({"title": title, "company": company or waiting, "location": place, "bullets": [], "start": _dates(line)[0], "end": _dates(line)[1]})
            waiting = ""
        elif job is not None and DATE_RANGE.search(line) and not job["start"]:
            job["start"], job["end"] = _dates(line)
        elif job is not None and len(line) > PARAGRAPH:
            job["bullets"].append(" ".join(line.split()))  # a resume written in sentences, not bullets
        elif job is not None and not job["company"] and len(line) <= PARAGRAPH:
            job["company"], job["location"] = _split_place(_without_dates(line))
        elif (job is None or job["bullets"]) and len(line) <= PARAGRAPH and not TITLE.search(line):
            waiting = _without_dates(line)  # perhaps the company of the job that comes next
    return jobs


def _education(lines: List[str]) -> List[Dict[str, Any]]:
    schools: List[Dict[str, Any]] = []
    for line in lines:
        if BULLET.match(line) and schools:
            schools[-1]["details"].append(_plain(line))
        elif DEGREE.search(line) or COLLEGE.search(line):
            parts = [piece.strip() for chunk in SPLITTERS.split(_without_dates(line)) for piece in chunk.split(",") if piece.strip()]
            school = next((p for p in parts if COLLEGE.search(p)), "")
            degree = next((p for p in parts if DEGREE.search(p) and p != school), "")
            start, end = _dates(line)
            schools.append({"school": school or (parts[-1] if parts and not degree else ""), "degree": degree or (parts[0] if parts and not school else ""),
                            "field": "", "start": start, "end": end, "details": []})
        elif schools and DATE_RANGE.search(line) and not schools[-1]["start"]:
            schools[-1]["start"], schools[-1]["end"] = _dates(line)
    return schools


def _skills(lines: List[str]) -> List[Dict[str, Any]]:
    groups = []
    for line in lines:
        group, colon, rest = _plain(line).partition(":")
        groups.append({"group": group.strip() if colon else "", "items": re.split(r"[,;|\u2022]", rest if colon else group)})
    return groups


def _projects(lines: List[str]) -> List[Dict[str, Any]]:
    projects: List[Dict[str, Any]] = []
    for line in lines:
        if BULLET.match(line) and projects:
            projects[-1]["bullets"].append(_plain(line))
        elif not BULLET.match(line) and len(line) <= PARAGRAPH:
            projects.append({"name": _without_dates(line), "bullets": []})
        elif projects:
            projects[-1]["bullets"].append(_plain(line))
    return projects


def _certification(line: str) -> Dict[str, str]:
    """'AWS Certified Developer - Amazon' is the certificate, then who gave it."""
    parts = re.split(r"\s+[-\u2013\u2014|]\s+", _without_dates(_plain(line)), maxsplit=1)
    return {"name": parts[0], "issuer": parts[1] if len(parts) > 1 else ""}


def _languages(lines: List[str]) -> List[Dict[str, str]]:
    found = []
    for chunk in re.split(r"[,;\n|]", "\n".join(_plain(line) for line in lines)):
        match = re.match(r"\s*([^()\-:]+?)\s*(?:[(\-:]\s*([^)]+?)\)?)?\s*$", chunk)
        if match and match.group(1).strip():
            found.append({"name": match.group(1).strip(), "level": (match.group(2) or "").strip()})
    return found


# -- the whole resume ----------------------------------------------------------------------------------------------------------------------
def from_text(text: str, profile: Optional[Profile] = None, source: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """(a draft resume, what to check) from the text of a resume. Your profile's checked details win over the guesses."""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    header, found = _sections(lines)
    facts = guess_facts(text)
    mine = profile or Profile()
    links = [{"label": label, "url": url} for label, url in (("LinkedIn", mine.linkedin or facts.get("linkedin")), ("GitHub", mine.github or facts.get("github")),
                                                              ("Portfolio", mine.portfolio or facts.get("portfolio"))) if url]
    headline = next((line for line in header[1:4] if TITLE.search(line) and "@" not in line and len(line) <= 80), mine.current_title or str(facts.get("current_title", "")))
    doc = normalize({
        "title": f"Imported from {source}" if source else "Imported resume",
        "basics": {"name": mine.name or facts.get("name"), "headline": headline, "email": mine.email or facts.get("email"),
                   "phone": mine.phone or facts.get("phone"), "location": mine.city or facts.get("city"), "links": links},
        "summary": " ".join(found.get("summary", [])),
        "experience": _experience(found.get("experience", [])), "education": _education(found.get("education", [])),
        "skills": _skills(found["skills"]) if "skills" in found else [{"group": "Skills", "items": [pretty(skill) for skill in mine.skills][:LIMITS["items"]]}],
        "projects": _projects(found.get("projects", [])), "certifications": [_certification(line) for line in found.get("certifications", [])],
        "languages": _languages(found.get("languages", []))})
    return doc, _notes(doc, found)


def _notes(doc: Mapping, found: Mapping) -> List[str]:
    notes = [f"No {key} section was found in the file: add it if you have one." for key in ("experience", "education") if key not in found]
    undated = [job for job in doc["experience"] if not job["start"]]
    if undated:
        notes.append(f"{len(undated)} job{'s have' if len(undated) != 1 else ' has'} no start month (the file gave a year, or no date): fill in the month.")
    if doc["experience"] and not any(job["bullets"] for job in doc["experience"]):
        notes.append("No bullets were found under your jobs: they may be in a layout that could not be read.")
    return notes + ["This is a draft read from the file: check every section before you use it."]


def from_profile(profile: Profile) -> Dict[str, Any]:
    """A first resume from your saved profile alone (for someone with no resume file yet): what you already confirmed, and nothing invented."""
    links = [{"label": label, "url": url} for label, url in (("LinkedIn", profile.linkedin), ("GitHub", profile.github), ("Portfolio", profile.portfolio)) if url]
    job = [{"title": profile.current_title, "company": profile.current_company, "end": "present"}] if profile.current_title or profile.current_company else []
    return normalize({"title": "My resume", "basics": {"name": profile.name, "headline": profile.current_title, "email": profile.email, "phone": profile.phone,
                                                        "location": profile.city, "links": links},
                      "experience": job, "skills": [{"group": "Skills", "items": [pretty(skill) for skill in profile.skills]}]})


def from_uploaded(profile: Profile) -> Tuple[Dict[str, Any], List[str]]:
    """A draft from the resume saved in your profile (the one your runs upload)."""
    if not profile.resume_path:
        raise ValueError("No resume has been saved yet. Save one on the Profile tab first, or start from your details.")
    path = Path(profile.resume_path).expanduser()
    return from_text(read_text(path), profile, path.name)
