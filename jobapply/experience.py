"""How many years of experience a posting asks for, read cautiously: a wrong reading would turn away a good job.

The portal's own experience field ("5-8 Yrs") is trusted. In free text only ONE clear statement, in a sentence that speaks of
experience, is: a second, different one is usually about a single skill ("3+ years of React" inside a job that asks for eight
overall), and "20+ years" without the word experience is usually about the company. Then nothing is concluded.
"""
from __future__ import annotations

import re
from typing import Optional, Set, Tuple

YEARS = r"(?:years?|yrs?)\b"
NUMBER = r"(\d{1,2}(?:\.\d)?)"
RANGE = re.compile(rf"{NUMBER}\s*(?:-|–|—|to)\s*{NUMBER}\s*\+?\s*{YEARS}", re.I)
FLOOR = re.compile(rf"(?:{NUMBER}\s*\+\s*{YEARS}|(?:minimum|at least|min\.?)\s*(?:of\s*)?{NUMBER}\s*\+?\s*{YEARS})", re.I)

Asked = Tuple[float, Optional[float]]  # (fewest years, most years); most is None for "N+ years"


def _statements(text: str) -> Set[Asked]:
    found: Set[Asked] = set()
    for first, second in RANGE.findall(text or ""):
        low, high = sorted((float(first), float(second)))
        found.add((low, high))
    for plus, minimum in FLOOR.findall(text or ""):
        found.add((float(plus or minimum), None))
    return found


def _about_experience(description: str) -> str:
    """Only the sentences that speak of experience: "20+ years of history" is about the company, not about you."""
    return "\n".join(part for part in re.split(r"[.\n;\u2022]", description or "") if "experience" in part.lower())


def years_asked(experience: str, description: str = "") -> Optional[Asked]:
    """What the job asks for, or None when it says nothing clear."""
    for text in (experience, _about_experience(description)):
        found = _statements(text)
        if len(found) == 1:
            return next(iter(found))
    return None
