"""What a job description says, as facts: its title, the years of experience it asks for, its seniority, each requirement on its own line, and the words
it repeats. Deterministic, no AI, and it only reports what the text literally says: where it cannot tell, it says nothing (an empty title, no years)
rather than guess. The skills are the project's own list (skills_vocab.py); `tailor.py` is what says which of them your resume has.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterable, List, NamedTuple, Optional

from ..skills_vocab import mentions
from .tailor import HEADING_MAX, NICE_CUES, REQUIRED_CUES, Lookup, detect

ROLE_WORDS = frozenset({"engineer", "developer", "manager", "analyst", "architect", "scientist", "designer", "consultant", "specialist", "lead", "administrator",
                        "devops", "sde", "sdet", "qa", "tester", "programmer", "officer", "executive", "associate", "intern", "director", "head", "owner",
                        "technician", "coordinator", "recruiter", "researcher", "writer", "strategist", "representative", "advisor", "accountant", "sre"})
TITLE_LABEL = re.compile(r"^\s*(?:job\s*title|position(?:\s*title)?|role|designation|title)\s*[:\-–—]\s*(\S.{2,100})$", re.I | re.M)
BULLET = re.compile(r"^\s*(?:[-*•·▪◦–—]|\d{1,2}[.)])\s+")
DUTY_CUES = ("experience", "proficien", "knowledge", "familiar", "ability to", "must ", "required", "expertise", "understanding", "skilled", "hands-on",
             "background in", "degree", "certif", "strong ", "proven", "responsible for", "design", "build", "develop", "maintain", "lead", "own ")
NOT_REQUIREMENTS = ("salary", "insurance", "paid leave", "bonus", "perks", "401", "equal opportunity", "how to apply", "click apply", "benefits", "work from home",
                    "free lunch", "stock options", "we offer", "about us", "our mission")
MAX_REQUIREMENTS = 15
MAX_LINE = 220
SENIORITY = (("intern", ("intern", "trainee", "apprentice")), ("junior", ("junior", "jr", "graduate", "entry level", "entry-level", "fresher", "associate")),
             ("senior", ("senior", "sr", "sde iii", "sde 3", "sde-iii")), ("lead", ("lead", "staff", "principal", "architect")),
             ("manager", ("manager", "head of", "director", "vp ", "vice president")))
YEARS_RANGE = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b(?!\s*old)", re.I)
YEARS_ONE = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:years?|yrs?)\b(?!\s*old)", re.I)
EXPERIENCE_WORDS = re.compile(r"experience|exp\b|minimum|at least|required|proven|hands-on|background", re.I)
PLUS_OR_RANGE = re.compile(r"\d\s*(?:\+|plus)\s*(?:years?|yrs?)|\d\s*(?:-|–|—|to)\s*\d{1,2}\s*\+?\s*(?:years?|yrs?)", re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")
STOP = frozenset("""about above ability able across after again all also always among and any are area areas around as at away back based be because been before being below
best better between both but by can candidate candidates career change come company contribute could create day days deliver delivering demonstrated different do
does doing done down drive during each eg either else employees enable ensure environment equal etc even every excellent experience experienced experiences
extensive familiar fast few field find first for from full further get give global good great grow growing growth had has have having help high how however
ideal ideally if impact important in including industry into is it its job join just keep key know large last learn least less like little long look looking
lot make making many may meet might more most much must need needs new next no non not now of off offer often on once one only open opportunity or other our
out over own part passion passionate people per place plan please plus position possible practice prefer preferred problem problems process product products
proven provide quality question questions range rather real really related remote required requirements responsible results right role roles same scale see seek
senior should show similar since skills solid solution solutions some someone something strong such support sure take team teams than that the their them then
there these they thing things think this those through time to together too tools top toward try two type under understand understanding until up upon us use used
using very view want was way we well were what when where whether which while who whom why will with within without work working works would year years you
your yourself able apply application applicants applicant benefits hiring employer employment opportunity qualified qualifications equivalent degree bachelor bachelors
master masters""".split())


class Requirement(NamedTuple):
    text: str
    kind: str  # "required" or "nice"
    skills: List[str]  # the named skills in it (canonical)
    years: Optional[int]  # the years of experience it asks for, if it says

    def as_dict(self) -> Dict[str, Any]:
        return self._asdict()


# -- title and level -------------------------------------------------------------------------------------------------------------------------
def _trim_title(line: str) -> str:
    line = re.split(r"\s+(?:\||@|at|-|–|—)\s+", line.strip(), maxsplit=1)[0]  # "Engineer | Acme", "Engineer at Acme", "Engineer - Remote"
    return re.sub(r"\s*[\[(][^\])]{0,40}[\])]\s*$", "", line).strip(" :-–—")[:100]


def title_of(text: str) -> str:
    """The job's title if the text names it ("Job Title: ...", or a short first line that reads like a role); otherwise nothing."""
    labelled = TITLE_LABEL.search(text)
    if labelled:
        return _trim_title(labelled.group(1))
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        words = {word.lower() for word in WORD.findall(line)}
        if len(line) <= 80 and not line.endswith((".", ",", ";")) and words & ROLE_WORDS:
            return _trim_title(line)
        break  # only the very first line: a role word further down is just prose
    return ""


def seniority_of(title: str) -> str:
    """intern, junior, senior, lead or manager, by the words of the title; nothing for a plain title (it may be mid-level, or not say)."""
    lowered = f" {title.lower()} "
    for level, cues in SENIORITY:
        if any(re.search(rf"(?<![a-z]){re.escape(cue.strip())}(?![a-z])", lowered) for cue in cues):
            return level
    return ""


# -- years -----------------------------------------------------------------------------------------------------------------------------------
def line_years(line: str) -> Optional[int]:
    """The least number of years one line asks for ("5+ years" is 5, "3-5 years" is 3). A line must be about experience, or say "3+" or "3-5", or it
    is only a number of years ("for 3 years", "10 years old")."""
    found = [int(low) for low, _ in YEARS_RANGE.findall(line)]
    if not found:
        found = [int(number) for number in YEARS_ONE.findall(line)]
    asks = EXPERIENCE_WORDS.search(line) or PLUS_OR_RANGE.search(line)
    found = [number for number in found if 0 < number <= 40]
    return min(found) if found and asks else None


def years_required(text: str) -> Optional[int]:
    """The years of experience the job asks for overall: the biggest figure on a line that is not about one particular skill (a line about one skill
    is a requirement of its own); failing that, the biggest figure there is. Nothing if the text names none."""
    general, specific = [], []
    for line in text.splitlines():
        years = line_years(line)
        if years is not None:
            (specific if mentions(line) else general).append(years)
    pool = general or specific
    return max(pool) if pool else None


# -- requirements, one to a line ---------------------------------------------------------------------------------------------------------------
def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", BULLET.sub("", line)).strip()[:MAX_LINE]


def requirements(text: str, look: Lookup = Lookup((), frozenset())) -> List[Requirement]:
    """The job's requirements, each as it was written: the bullets (and, under a heading about requirements, the sentences) that ask for something. A
    line under "nice to have" or ending "a plus" is a nice-to-have. Lines about pay, perks and the employer are not requirements."""
    mode, found, seen = "required", [], set()
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        bullet = bool(BULLET.match(raw))
        heading = not bullet and len(stripped) <= HEADING_MAX and not stripped.endswith((".", ",", ";"))
        cued_nice = heading and any(cue in lowered for cue in NICE_CUES)
        if cued_nice or (heading and any(cue in lowered for cue in REQUIRED_CUES)):
            mode = "nice" if cued_nice else "required"
            tail = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if not (tail and detect(tail, look)):
                continue
            raw = tail  # "Nice to have: Kafka" is a heading and a requirement in one line
        elif heading:
            continue
        line = _clean_line(raw)
        skills = detect(line, look)  # a line that names a skill is a requirement however short: "- Kubernetes"
        if any(cue in lowered for cue in NOT_REQUIREMENTS) or (not skills and (len(line) < 12 or not re.search(r"[A-Za-z]{3}", line))):
            continue
        if not (bullet or skills or any(cue in lowered for cue in DUTY_CUES)):
            continue
        kind = "nice" if mode == "nice" or any(cue in lowered for cue in NICE_CUES) else "required"
        if line.lower() in seen:
            continue
        seen.add(line.lower())
        found.append(Requirement(line, kind, skills, line_years(line)))
    return found[:MAX_REQUIREMENTS]


# -- the words a job repeats -----------------------------------------------------------------------------------------------------------------
def _words(text: str) -> List[str]:
    return [word.strip("./-+#").lower() for word in WORD.findall(text) if len(word.strip("./-+#")) >= 4]


def _plain(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 4 and not word.endswith("ss") else word


def other_terms(text: str, skip: Iterable[str] = (), most: int = 12) -> List[Dict[str, Any]]:
    """Words and two-word phrases the job uses at least twice that are not a skill the project knows and not its title, company or place: the
    domain words ("microservices", "payment systems") a recruiter searching for this job would also type. Counted and ordered as they appear."""
    skipped: FrozenSet[str] = frozenset(_plain(word) for phrase in skip for word in _words(phrase))
    raw = _words(text)
    tokens = [_plain(word) for word in raw]
    counts: Dict[str, int] = {}
    first: Dict[str, int] = {}
    shown: Dict[str, str] = {}  # counted with plurals folded (system, systems), shown as the job wrote it the first time
    for at, word in enumerate(tokens):
        if word in STOP or word in skipped or word.isdigit():
            continue
        counts[word] = counts.get(word, 0) + 1
        first.setdefault(word, at)
        shown.setdefault(word, raw[at])
    for at in range(len(tokens) - 1):
        pair = (tokens[at], tokens[at + 1])
        if any(word in STOP or word in skipped for word in pair):
            continue
        phrase = " ".join(pair)
        counts[phrase] = counts.get(phrase, 0) + 1
        first.setdefault(phrase, at)
        shown.setdefault(phrase, f"{raw[at]} {raw[at + 1]}")
    wanted = [term for term, number in counts.items() if number >= 2 and not mentions(term)]
    wanted = [term for term in wanted if not any(term != other and term in other and counts[other] >= counts[term] for other in wanted if " " in other)]
    wanted.sort(key=lambda term: (-counts[term], first[term]))
    return [{"term": shown[term], "count": counts[term]} for term in wanted[:most]]


class Facts(NamedTuple):
    title: str
    seniority: str
    years: Optional[int]
    requirements: List[Requirement]

    def as_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "seniority": self.seniority, "years": self.years, "requirements": [item.as_dict() for item in self.requirements]}


def read(text: str, title: str = "", look: Lookup = Lookup((), frozenset())) -> Facts:
    """Everything the text says about itself. `title` is the one the page gave (if it did): the text's own is only used when there is none."""
    chosen = title or title_of(text)
    return Facts(chosen, seniority_of(chosen), years_required(text), requirements(text, look))
