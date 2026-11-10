"""Answer screening questions from facts, never from guesses.

Order: answer bank -> deterministic rules -> (opt-in) the grounded AI helper.
Anything else is recorded as unknown, and the job is parked as NEEDS_ANSWER.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from .config import Profile
from .db import Database
from .models import Declined, NeedsAnswer


def normalize(question: str) -> str:
    text = re.sub(r"[^\w+#.\s]", " ", (question or "").lower())
    return re.sub(r"\s+", " ", text).strip(" .")


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def _years(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _skill_years(profile: Profile, question: str) -> Optional[str]:
    if not re.search(r"\b(experience|exp)\b", question):
        return None
    hits = [
        years
        for skill, years in profile.skills.items()
        if years is not None and re.search(rf"(?<![\w+#.]){re.escape(skill.lower())}(?![\w+#])", question)
    ]
    return _years(min(hits)) if hits else None


def _total_years(profile: Profile, question: str) -> Optional[str]:
    match = re.search(r"\bexperience\b(.*)$", question)
    if not match:
        return None
    if re.search(r"\b(total|overall)\b", question):
        return _years(profile.total_experience_years)
    if re.search(r"\b(in|with|on|using|of)\s+\w", match.group(1)):
        return None  # asks about something specific we have no fact for
    return _years(profile.total_experience_years)


def _when(pattern: str, getter: Callable[[Profile], Optional[str]]):
    regex = re.compile(pattern)
    return lambda profile, question: getter(profile) if regex.search(question) else None


def _name_part(profile: Profile, first: bool) -> Optional[str]:
    """First word of the name, or everything after it. One word only: there is no last name to give."""
    words = profile.name.split()
    return (words[0] if first else " ".join(words[1:])) or None


MONEY = r"(ctc|salary|compensation|package)"
RULES: List[Callable[[Profile, str], Optional[str]]] = [
    _skill_years,
    _when(r"\bnotice\b", lambda p: p.notice_period),
    _when(rf"\bexpect\w*\b.*\b{MONEY}\b|\b{MONEY}\b.*\bexpect", lambda p: p.expected_ctc),
    _when(rf"\b(current|present)\b.*\b{MONEY}\b|\b{MONEY}\b.*\bcurrent", lambda p: p.current_ctc),
    _when(r"\brelocat", lambda p: _yes_no(p.willing_to_relocate)),
    _when(r"\b(hybrid|work from office|wfo|onsite|on site|in office)\b", lambda p: _yes_no(p.ok_with_onsite)),
    _when(r"\b(current|present)\b.*\b(city|location)\b|\bwhere are you (located|based)\b", lambda p: p.city),
    _when(r"\b(current|present)\b.*\b(company|employer|organi[sz]ation)\b", lambda p: p.current_company),
    _when(r"\b(current|present)\b.*\b(title|designation|job role)\b", lambda p: p.current_title),
    _when(r"\be ?mail\b", lambda p: p.email),
    _when(r"\b(phone|mobile|contact number)\b", lambda p: p.phone),
    _when(r"\blinkedin\b", lambda p: p.linkedin),
    _when(r"\bgithub\b", lambda p: p.github),
    _when(r"\b(portfolio|website)\b", lambda p: p.portfolio),
    _when(r"\b(full name|your name)\b|^name$", lambda p: p.name),
    _when(r"^(first|given) name$", lambda p: _name_part(p, first=True)),
    _when(r"^(last|family) name$|^surname$", lambda p: _name_part(p, first=False)),
    _when(r"\b(education|qualification|highest degree)\b", lambda p: p.education),
    _total_years,
]


def _in_range(value: float, text: str) -> bool:
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    lowered = text.lower()
    if len(numbers) >= 2:
        return numbers[0] <= value <= numbers[1]
    if len(numbers) == 1:
        if any(word in lowered for word in ("+", "more", "above", "over")):
            return value >= numbers[0]
        if any(word in lowered for word in ("less", "below", "under")):
            return value < numbers[0]
        return value == numbers[0]
    return False


def pick_option(answer: str, options: Sequence[str]) -> Optional[str]:
    """Map a fact onto one of a form's choices, or None if none fits."""
    wanted = str(answer).strip().lower()
    for option in options:
        if option.strip().lower() == wanted:
            return option
    if wanted in ("yes", "no"):
        return next((o for o in options if re.match(rf"^{wanted}\b", o.strip().lower())), None)
    try:
        number = float(wanted)
    except ValueError:
        number = None
    if number is not None:
        for option in options:
            if _in_range(number, option):
                return option
    return next((o for o in options if len(wanted) >= 3 and wanted in o.lower()), None)


# Voluntary self-identification: what a person says about themselves, never a fact about the job. A wrong answer here is a wrong
# statement about the person, so code (not an AI) refuses to settle a conflict, and a form that offers "prefer not to say" gets it.
SENSITIVE = re.compile(r"\b(gender|sex|race|racial|ethnic\w*|veteran|disabilit\w*|disabled|religio\w*|caste|sexual|orientation|"
                       r"pronouns?|marital|transgender|lgbtq\w*)\b", re.I)
DECLINE = re.compile(r"\b(decline|prefer not|rather not|(?:do not|don't|dont) wish|choose not|not to (?:say|answer|disclose|identify|specify|state))\b", re.I)


def decline_option(options: Sequence[str]) -> Optional[str]:
    """The form's own "prefer not to say" choice (the default the proficiently skills use for every voluntary question)."""
    return next((option for option in options if DECLINE.search(option)), None)


@dataclasses.dataclass
class Attention:
    """What an adapter is lent so it can wait for a person at the portal's own form. The engine owns the policy (how long, and
    whether this run has already waited on a question in vain); the adapter only waits."""

    seconds: Callable[[], float]  # how long may be waited now: the answer wait, or what is left of the run if that is less
    alert: Callable[[str], None]  # how the person is told what is needed, and what was done
    load_bank: Callable[[], Dict[str, str]]  # the saved answers as they are on disk now: what was answered in the panel
    given_up: Set[str]  # questions this run already waited on in vain: a later job asking one is not waited for again


Reader = Callable[[], Optional[str]]  # reads what the person has put in one control of the form, or None if it is still empty


class AnswerResolver:
    def __init__(
        self,
        profile: Profile,
        bank: Dict[str, str],
        db: Database,
        portal: str,
        ai: Optional[Callable[[str, Optional[Sequence[str]]], Optional[str]]] = None,
        persist: Optional[Callable[[str, str], None]] = None,
        attention: Optional[Attention] = None,
    ):
        self.profile = profile
        self.ai = ai  # asked last, and only about questions that must be answered
        self.persist = persist  # keeps an answer you gave on the portal's own form; without it such an answer lasts one reload
        self.attention = attention  # set by the engine for each job: lets an adapter wait for you at the form
        self._watching: Dict[str, Tuple[str, Optional[Sequence[str]], Reader]] = {}  # unanswered question -> how to read its control
        self._seen: Dict[str, str] = {}  # what a watched control held at the last look: an answer is taken once it holds still
        self.raw_bank: Dict[str, str] = {}  # the same answers under the question's own words (the AI is shown these)
        self.bank: Dict[str, str] = {}
        self.reload(bank)
        self.db = db
        self.portal = portal
        self.unknown: Dict[str, str] = {}
        self.refused: Dict[str, str] = {}  # required tick boxes the person's answer says not to tick
        self.waited = False  # an adapter already waited for you on the form: the engine must not make the job wait again

    def reload(self, bank: Dict[str, str]) -> None:
        """Take the answer bank as it is now: you may have answered a question while a job was waiting for it."""
        self.raw_bank = dict(bank)
        self.bank = {normalize(k): v for k, v in bank.items()}
        for norm in [norm for norm in self._watching if norm in self.bank]:
            self._stop_watching(norm)  # answered in the panel: nothing left to read from the form
        self._tell_ai()

    def _tell_ai(self) -> None:
        learn = getattr(self.ai, "learn", None)  # the AI helper reads your answers too, and must hear about a new one at once
        if learn is not None:
            learn(self.raw_bank)

    def start_pass(self) -> None:
        """A fresh look at one form: what cannot be answered is found again. The controls being watched are NOT forgotten: a box
        you have typed in is skipped by the filler (it looks pre-filled), yet it still has to be read until it is taken."""
        self.unknown.clear()
        self.refused.clear()

    def reset(self) -> None:
        """A fresh attempt at a job."""
        self.start_pass()
        self._watching.clear()
        self._seen.clear()
        self.waited = False

    def waiting_on(self) -> Set[str]:
        """The questions still unanswered: those the filler could not answer, and those a person has begun to answer but that
        are not yet taken."""
        return set(self.unknown) | set(self._watching)

    def questions_of(self, norms: Set[str]) -> List[str]:
        """The questions' own words, for telling the person what is needed."""
        raw = {**{norm: watched[0] for norm, watched in self._watching.items()}, **self.unknown}
        return [raw[norm] for norm in raw if norm in norms]

    def _stop_watching(self, norm: str) -> None:
        self._watching.pop(norm, None)
        self._seen.pop(norm, None)

    def refuse(self, question: str) -> None:
        self.refused[normalize(question)] = question.strip()

    def _lookup(self, norm: str) -> Optional[str]:
        if norm in self.bank:
            return self.bank[norm]
        for rule in RULES:
            answer = rule(self.profile, norm)
            if answer:
                return answer
        return None

    def resolve(
        self, question: str, options: Optional[Sequence[str]] = None, required: bool = True, read: Optional[Reader] = None
    ) -> Optional[str]:
        norm = normalize(question)
        if not norm:
            return None
        answer = self._lookup(norm)
        if answer is not None and options:
            answer = pick_option(answer, options)  # a saved fact in other words than this form's choices is not yet an answer
        if answer is None and required and self.ai is not None:
            answer = self.ai(question.strip(), options)  # it reads your saved answers too: they help it, they never stop it
            if answer is not None and options:
                answer = pick_option(answer, options)
        if answer is None and required and options and SENSITIVE.search(question):
            answer = decline_option(options)  # never guess about the person, and never stall a job on a voluntary question
        if answer is None and required:
            self.unknown[norm] = question.strip()
            if read is not None:  # the form is open: you may answer it right there, and then it is read back from the control
                self._watching[norm] = (question.strip(), options, read)
            self.db.add_question(norm, question.strip(), options, self.portal)
        return answer

    def take_answers(self) -> List[str]:
        """Pick up what the person has done since the last look: typed or ticked an answer into the portal's own form (it is
        saved like any other answer), or answered in the panel. Returns the questions answered on the form."""
        taken = self._take_typed()
        if self.attention is not None:
            self.reload(self.attention.load_bank())
        return taken

    def _take_typed(self) -> List[str]:
        taken = []
        for norm, (raw, options, read) in list(self._watching.items()):
            try:
                value = (read() or "").strip()
            except Exception:
                self._stop_watching(norm)  # the control is gone (you pressed Next yourself): nothing to read, nothing to wait for
                continue
            if not value or (options and value not in options):  # empty, or not one of the form's own choices
                self._seen.pop(norm, None)
                continue
            if self._seen.get(norm) != value:  # still being typed in: it must hold still for one more look
                self._seen[norm] = value
                continue
            self._keep(norm, raw, value)
            taken.append(raw)
        return taken

    def _keep(self, norm: str, raw: str, value: str) -> None:
        self.raw_bank[raw] = value
        self.bank[norm] = value
        if self.persist is not None:
            self.persist(raw, value)
        self._tell_ai()
        self.db.drop_question(norm)  # it is answered now: the Questions button stops glowing for it
        self.unknown.pop(norm, None)
        self._stop_watching(norm)
        if self.attention is not None:
            self.attention.alert(f"Saved your answer to: {raw[:90]}")

    def require_complete(self) -> None:
        """Adapters call this before submitting. A required tick box answered No ends the job (asking more is pointless);
        any unknown question parks it."""
        if self.refused:
            raise Declined(self.refused.values())
        if self.unknown:
            raise NeedsAnswer(self.unknown.values())
