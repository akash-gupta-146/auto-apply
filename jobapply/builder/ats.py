"""Read a resume the way an applicant tracking system would, and say what is wrong with it and why. Deterministic: no AI, the same resume gives the same report.

The score is 100 minus the points of every check that fails, and the points are all in CHECKS below, the one place to change them. A score is never shown
without its reasons: every failing check says what is wrong, how to fix it, and where (`pointer`, a JSON pointer into the resume, so the editor can jump
to the field).

No HTTP and no HTML in here.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Tuple

from .doc import HEADINGS, PLACEHOLDER, full_text
from .render import TEMPLATES, estimate_pages
from .tailor import Coverage, pretty

# check id -> (category, severity, points lost when it fails). The score is decided here and nowhere else.
CHECKS: Dict[str, Tuple[str, str, int]] = {
    "name": ("contact", "error", 10), "email": ("contact", "error", 10), "phone": ("contact", "warn", 4), "location": ("contact", "warn", 3),
    "sections": ("format", "warn", 30), "pages": ("format", "warn", 6), "dates": ("format", "warn", 4), "template": ("format", "info", 2),
    "bullets-per-job": ("content", "warn", 5), "verbs": ("content", "warn", 5), "length": ("content", "warn", 4), "impact": ("content", "info", 3), "placeholders": ("content", "warn", 6),
    "summary": ("content", "info", 2), "keywords": ("keywords", "warn", 20),
}
CATEGORIES = {"contact": "Contact details", "format": "Format", "content": "Content", "keywords": "Keywords for this job"}
PASSED = {"name": "Your name is there", "email": "Your email is there and looks right", "phone": "Your phone number is there", "location": "Your location is there",
          "sections": "Experience, education and skills are all there", "pages": "Short enough to read quickly", "dates": "Every job has dates that make sense",
          "template": "The template is plain text in one column", "bullets-per-job": "Every job has at least two bullets", "verbs": "Bullets start with what you did",
          "length": "Bullets are a good length", "impact": "Enough bullets show numbers or results", "placeholders": "No blanks like [X%] are left to fill in", "summary": "The summary is a good length and in your own voice",
          "keywords": "The job's required skills are in your resume"}
MAX_PAGES, MIN_BULLET_WORDS, MAX_BULLET_WORDS, MIN_IMPACT_SHARE = 2, 8, 30, 0.3
MIN_SUMMARY_WORDS, MAX_SUMMARY_WORDS, MIN_PHONE_DIGITS = 20, 80, 7
ESSENTIAL = ("experience", "education", "skills")  # what a resume is mostly made of: the points of "sections" are shared out between these
MAX_PER_CHECK = 8  # how many places one check lists: the rest are the same advice again

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'll|my|me|myself)\b", re.I)
IMPACT = re.compile(r"\d|%")  # a placeholder ([X%]) is a blank for a number, not a number
WEAK_OPENERS = {"responsible", "worked", "helped", "duties", "tasked", "assisted", "involved", "handled", "various", "participated", "familiar", "exposure"}
ACTION_VERBS = set("""achieved administered analyzed analysed architected authored automated built championed collaborated completed configured consolidated
contributed converted coordinated created cut debugged decreased defined delivered deployed designed developed directed drove eliminated enabled engineered
established evaluated executed expanded facilitated founded generated guided identified implemented improved increased initiated integrated introduced launched led
maintained managed mentored migrated modernized modernised monitored negotiated optimized optimised orchestrated organized organised oversaw owned partnered
piloted planned prepared presented prioritized produced programmed proposed prototyped published raised rebuilt redesigned reduced refactored released
replaced researched resolved restructured reviewed revamped saved scaled secured set shipped simplified solved spearheaded standardized streamlined strengthened
supported tested trained transformed tuned upgraded validated wrote won""".split())


class Check(NamedTuple):
    id: str
    category: str
    severity: str
    message: str
    fix: str
    pointer: str


Finding = Tuple[str, str, str]  # message, how to fix it, where
Finder = Callable[[Mapping], List[Finding]]


def _words(text: str) -> int:
    return len(text.split())


def _bullets(doc: Mapping) -> List[Tuple[str, str]]:
    """(pointer, text) of every bullet of the jobs and projects."""
    return [(f"/{key}/{i}/bullets/{j}", bullet) for key in ("experience", "projects") for i, entry in enumerate(doc[key]) for j, bullet in enumerate(entry["bullets"])]


def _snippet(text: str) -> str:
    return f'"{text[:45]}{"..." if len(text) > 45 else ""}"'


# -- one function per check ------------------------------------------------------------------------------------------------------------------
def _name(doc: Mapping) -> List[Finding]:
    return [] if doc["basics"]["name"] else [("Your name is missing.", "Put your full name at the top: it is the first thing a system reads.", "/basics/name")]


def _email(doc: Mapping) -> List[Finding]:
    email = doc["basics"]["email"]
    if not email:
        return [("Your email address is missing.", "Add it: employers use it to reach you, and most systems require it.", "/basics/email")]
    return [] if EMAIL.match(email) else [(f"{_snippet(email)} does not look like an email address.", "Check it for typos, for example a missing @ or dot.", "/basics/email")]


def _phone(doc: Mapping) -> List[Finding]:
    digits = re.sub(r"\D", "", doc["basics"]["phone"])
    return [] if len(digits) >= MIN_PHONE_DIGITS else [("Your phone number is missing or too short.", "Add one with the country code, like +91 98765 43210.", "/basics/phone")]


def _location(doc: Mapping) -> List[Finding]:
    return [] if doc["basics"]["location"] else [("Your location is missing.", "Add your city: many systems filter jobs by place.", "/basics/location")]


def _sections(doc: Mapping) -> List[Finding]:
    found = []
    for key in ESSENTIAL:
        if key in doc["hidden"] and doc[key]:
            found.append((f"{HEADINGS[key]} is hidden, so it is not in your resume.", f"Show the {HEADINGS[key]} section.", f"/{key}"))
        elif not doc[key]:
            found.append((f"There is no {HEADINGS[key]} section.", f"Add your {HEADINGS[key].lower()}: systems look for this heading by name.", f"/{key}"))
    return found


def _pages(doc: Mapping) -> List[Finding]:
    pages = estimate_pages(doc)
    return [(f"It will run to about {pages} pages.", "Tighten the spacing, use a smaller size, or cut your oldest roles: two pages is as much as most recruiters read.", "/theme/spacing")] \
        if pages > MAX_PAGES else []


def _dates(doc: Mapping) -> List[Finding]:
    found = []
    for i, job in enumerate(doc["experience"]):
        label = job["title"] or job["company"] or f"Job {i + 1}"
        if not job["start"]:
            found.append((f"{label} has no start date.", "Add the month it began: systems work out your experience from dates.", f"/experience/{i}/start"))
        elif job["end"] and job["end"] != "present" and job["end"] < job["start"]:
            found.append((f"{label} ends before it starts.", "Check the two dates.", f"/experience/{i}/end"))
    return found


def _template(doc: Mapping) -> List[Finding]:
    template = TEMPLATES[doc["template"]]
    return [] if template.ats_safe else [(f"The {template.name} template uses columns.", "Some systems read columns out of order. Use Classic, Compact or Modern when you apply.", "/template")]


def _bullets_per_job(doc: Mapping) -> List[Finding]:
    return [(f"{job['title'] or job['company']} has {len(job['bullets'])} bullet{'s' if len(job['bullets']) != 1 else ''}.", "Say two or three things you did or achieved there.", f"/experience/{i}/bullets")
            for i, job in enumerate(doc["experience"]) if len(job["bullets"]) < 2]


def _verbs(doc: Mapping) -> List[Finding]:
    found = []
    for pointer, bullet in _bullets(doc):
        opener = re.match(r"[A-Za-z]+", bullet.lstrip(" -*\u2022"))
        first = opener.group(0).lower() if opener else ""  # a bullet that starts with a number has no verb to start with
        if first in WEAK_OPENERS or not (first in ACTION_VERBS or (len(first) > 3 and first.endswith("ed"))):
            found.append((f"{_snippet(bullet)} does not start with an action verb.", "Start with what you did: Built, Led, Reduced, Migrated...", pointer))
    return found


def _length(doc: Mapping) -> List[Finding]:
    found = []
    for pointer, bullet in _bullets(doc):
        count = _words(bullet)
        if count < MIN_BULLET_WORDS:
            found.append((f"{_snippet(bullet)} is only {count} words.", f"Say what the result was: aim for {MIN_BULLET_WORDS} to {MAX_BULLET_WORDS} words.", pointer))
        elif count > MAX_BULLET_WORDS:
            found.append((f"{_snippet(bullet)} is {count} words long.", f"Split it or cut it to {MAX_BULLET_WORDS} words or fewer.", pointer))
    return found


def _impact(doc: Mapping) -> List[Finding]:
    bullets = _bullets(doc)
    shown = sum(1 for _, bullet in bullets if IMPACT.search(bullet))
    if len(bullets) < 3 or shown / len(bullets) >= MIN_IMPACT_SHARE:
        return []
    return [(f"Only {shown} of your {len(bullets)} bullets show a number or result.", "Add what changed and by how much, where you honestly know it: users, time saved, money, size.", "/experience")]


def _placeholders(doc: Mapping) -> List[Finding]:
    places = _bullets(doc) + [(f"/education/{i}/details/{j}", line) for i, entry in enumerate(doc["education"]) for j, line in enumerate(entry["details"])]
    places.append(("/summary", doc["summary"]))
    return [(f"{_snippet(text)} still has {PLACEHOLDER.search(text).group(0)} in it.", "Fill in the real figure, or take the blank out: it would go to the employer as it is.", pointer)
            for pointer, text in places if PLACEHOLDER.search(text)]


def _summary(doc: Mapping) -> List[Finding]:
    text = doc["summary"]
    if not text:
        return [("There is no summary.", "Add two or three sentences on who you are and what you are good at.", "/summary")]
    found = []
    if not MIN_SUMMARY_WORDS <= _words(text) <= MAX_SUMMARY_WORDS:
        found.append((f"Your summary is {_words(text)} words.", f"Aim for {MIN_SUMMARY_WORDS} to {MAX_SUMMARY_WORDS} words.", "/summary"))
    if FIRST_PERSON.search(text):
        found.append(("Your summary uses \"I\" or \"my\".", "Resumes leave it out: write \"Backend engineer with six years...\" rather than \"I am a...\".", "/summary"))
    return found


FINDERS: Dict[str, Finder] = {"name": _name, "email": _email, "phone": _phone, "location": _location, "sections": _sections, "pages": _pages, "dates": _dates,
                              "template": _template, "bullets-per-job": _bullets_per_job, "verbs": _verbs, "length": _length, "impact": _impact, "placeholders": _placeholders, "summary": _summary}
assert set(FINDERS) | {"keywords"} == set(CHECKS) == set(PASSED)  # a check has its points, its words, and its rule: all three


def _keywords(coverage: Coverage) -> List[Finding]:
    if not coverage.required_missing:
        return []
    names = ", ".join(pretty(skill) for skill in coverage.required_missing)
    return [(f"The job asks for {len(coverage.required_missing)} skill{'s' if len(coverage.required_missing) != 1 else ''} your resume does not mention: {names}.",
             "Add each one only if it is true: in your skills, or in a bullet where you used it. Never add what you cannot do.", "/skills")]


def _share(key: str, findings: List[Finding], coverage: Optional[Coverage]) -> float:
    """How much of a failed check's points are lost: all of them, except where how bad it is can be measured (how many parts are missing, how much of the job)."""
    if key == "sections":
        return min(1.0, len(findings) / len(ESSENTIAL))
    if key == "keywords" and coverage is not None and coverage.ratio is not None:
        return 1 - coverage.ratio
    return 1.0


# -- the report ------------------------------------------------------------------------------------------------------------------------------
def analyze(doc: Mapping, coverage: Optional[Coverage] = None) -> Dict[str, Any]:
    """The report on a resume (and, with the job's `coverage`, on how well it fits that job). JSON-able."""
    failed: Dict[str, List[Finding]] = {key: finder(doc) for key, finder in FINDERS.items()}
    failed["keywords"] = _keywords(coverage) if coverage else []
    active = [key for key in CHECKS if key != "keywords" or coverage]
    lost: Dict[str, float] = {}
    for key in active:
        if failed[key]:
            lost[key] = CHECKS[key][2] * _share(key, failed[key], coverage)
    categories = {}
    for category, label in CATEGORIES.items():
        ids = [key for key in active if CHECKS[key][0] == category]
        if ids:
            possible = sum(CHECKS[key][2] for key in ids)
            categories[category] = {"label": label, "score": round(100 * (1 - sum(lost.get(key, 0) for key in ids) / possible))}
    order = {"error": 0, "warn": 1, "info": 2}
    checks = [Check(key, CHECKS[key][0], CHECKS[key][1], *finding) for key in active for finding in failed[key][:MAX_PER_CHECK]]
    checks.sort(key=lambda check: order[check.severity])
    return {"score": max(0, round(100 - sum(lost.values()))), "categories": categories, "checks": [check._asdict() for check in checks],
            "passed": [PASSED[key] for key in active if not failed[key]], "pages": estimate_pages(doc), "words": _words(full_text(doc)),
            "keywords": coverage.as_dict() if coverage else None}
