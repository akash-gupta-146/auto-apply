"""Answer screening questions from facts, never from guesses.

Order: answer bank -> deterministic rules -> (opt-in) the grounded AI helper.
Anything else is recorded as unknown, and the job is parked as NEEDS_ANSWER.

One exception, and only where a caller asks for it (`may_guess`: the AI agent, when you allow it): a last step before asking you, the
AI's best guess (see ai_guess.py), kept apart from your answers (see guess_book.py). `known()` never returns one.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .config import Profile
from .db import Database
from .models import Declined, NeedsAnswer

log = logging.getLogger("jobapply")

if TYPE_CHECKING:  # only to name a type: guess_book imports this module
    from .guess_book import GuessBook


def normalize(question: str) -> str:
    text = re.sub(r"[^\w+#.\s]", " ", (question or "").lower())
    return re.sub(r"\s+", " ", text).strip(" .")


# What a control shows before anyone has answered it is an instruction ("Select an option", "Click Here..."), never an answer. Narrow on
# purpose: "Choose not to disclose" and "Select Committee" are answers, and wrongly refusing one only means it is not learned.
NOT_AN_ANSWER = re.compile(r"^(?:(?:please )?(?:select|choose|pick)(?: an?\b| one\b| your\b| the\b| from\b|\W*$)|click\b|tap\b|--)", re.I)


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
    _when(r"\bnotice\b|\bnp\b|\b(how soon|how early|when)\b.*\bjoin\w*|\bjoining (time|period|timeline)\b", lambda p: p.notice_period),  # ("official NP", "how soon can you join")
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
    _when(r"\b(full name|your name|candidate name|applicant name|legal name|complete name)\b|^name$", lambda p: p.name),
    _when(r"^(?:legal )?(first|given) names?(?: s)?$", lambda p: _name_part(p, first=True)),  # "Given Name(s)" is "given name s" once normalised
    _when(r"^(?:legal )?(last|family) names?(?: s)?$|^surname$", lambda p: _name_part(p, first=False)),
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


def profile_answer(profile: Profile, norm: str) -> Optional[str]:
    """What your profile says to this question, if it is one of the facts the profile holds (notice period, CTC, city...)."""
    for rule in RULES:
        answer = rule(profile, norm)
        if answer:
            return answer
    return None


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
        guesser: Optional[Callable[[str, Optional[Sequence[str]]], Optional[str]]] = None,
        guesses: Optional["GuessBook"] = None,
    ):
        self.profile = profile
        self.ai = ai  # asked last, and only about questions that must be answered
        self.persist = persist  # keeps an answer you gave on the portal's own form; without it such an answer lasts one reload
        self.attention = attention  # set by the engine for each job: lets an adapter wait for you at the form
        self.guesser = guesser  # asked only when a caller allows guessing, after everything else has failed
        self.guesses = guesses  # the guesses made so far, kept apart from your answers
        self.guessed: Dict[str, Tuple[str, str]] = {}  # this job's guesses (norm -> question, answer): the approval step lists them
        self._rejected: Dict[str, str] = {}  # a guess the form refused: never guessed again, never mistaken for your answer
        self._watching: Dict[str, Tuple[str, Optional[Sequence[str]], Reader]] = {}  # unanswered question -> how to read its control
        self._seen: Dict[str, str] = {}  # what a watched control held at the last look: an answer is taken once it holds still
        self._acks: Optional[Dict[str, Tuple[str, str]]] = None  # disagreements you looked at and chose to keep (read once: see _acknowledged)
        self._used: Set[str] = set()  # the saved answers this job has used, so a form read in several passes counts once
        self.conflicts: Dict[str, Tuple[str, str]] = {}  # question -> (your saved answer, what your profile says): told once per run, never cleared per job
        self.raw_bank: Dict[str, str] = {}  # the same answers under the question's own words (the AI is shown these)
        self.bank: Dict[str, str] = {}
        self.reload(bank)
        self.db = db
        self.portal = portal
        self.unknown: Dict[str, str] = {}
        self.refused: Dict[str, str] = {}  # required tick boxes the person's answer says not to tick
        self.waited = False  # an adapter already waited for you on the form: the engine must not make the job wait again
        self.context = ""  # the job being worked on ("Acme: Senior Engineer"): kept with each question so you know which job asked it

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
        self._used.clear()
        self._watching.clear()
        self._seen.clear()
        self.guessed.clear()
        self._rejected.clear()
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
        ruled = profile_answer(self.profile, norm)
        if norm in self.bank:
            self._check_conflict(norm, self.bank[norm], ruled)
            self._note_use(norm)
            return self.bank[norm]
        return ruled

    def _note_use(self, norm: str) -> None:
        """Count a saved answer being used, once per job: the answers page shows which ones no run ever uses, so stale ones can be removed."""
        if norm in self._used or self.db is None:
            return
        self._used.add(norm)
        try:
            self.db.record_answer_use(norm)
        except Exception:  # counting is never worth stopping a job for
            log.debug("could not count the use of a saved answer", exc_info=True)

    def _acknowledged(self) -> Dict[str, Tuple[str, str]]:
        if self._acks is None:
            try:
                self._acks = self.db.acknowledged() if self.db is not None else {}
            except Exception:
                self._acks = {}
        return self._acks

    def _check_conflict(self, norm: str, saved: str, ruled: Optional[str]) -> None:
        """A saved answer wins (you gave it for exactly this question), but if it says something else than your profile does about the same
        fact (notice period 15 here, 30 Days there), whichever wording a form happens to use decides what is sent, and nothing said so. Now it is
        said, once per question per run. The same figure in other units (70 lakhs, 6500000) is one fact, not a conflict."""
        from .answer_book import disagree  # here: answer_book imports this module

        if not ruled or norm in self.conflicts or not disagree(saved, ruled) or self._acknowledged().get(norm) == (saved, ruled):
            return  # (a disagreement you looked at and chose to keep is not said again, until either text changes)
        self.conflicts[norm] = (saved, ruled)
        message = f"Your saved answer to \"{norm[:70]}\" is \"{saved[:60]}\", but your profile says \"{ruled[:60]}\" for the same thing. I used the saved answer: fix whichever is wrong, or keep it, on the panel's Check my saved answers page."
        log.warning(message)
        if self.attention is not None:
            self.attention.alert(message)

    def resolve(
        self, question: str, options: Optional[Sequence[str]] = None, required: bool = True, read: Optional[Reader] = None,
        may_guess: bool = False,
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
        if answer is None and required and may_guess:
            answer = self._guess(question, options)  # the last step before asking you, and only where the caller allows it
        if answer is None and required:
            self.park(question, options, read)
        return answer

    def _guess(self, question: str, options: Optional[Sequence[str]]) -> Optional[str]:
        """A guess made before for this question, else a new one. Never about the person (gender, race...), whatever asks."""
        norm = normalize(question)
        if SENSITIVE.search(question) or norm in self._rejected:
            return None
        saved = self.guesses.get(question) if self.guesses is not None else None
        answer = saved.answer if saved is not None else None
        if answer is None and self.guesser is not None:
            answer = self.guesser(question.strip(), options)
            if answer is not None and self.guesses is not None:
                self.guesses.remember(question, answer, self.context)  # kept for the next job that asks it
        if answer is not None and options:
            answer = pick_option(answer, options)  # a guess in other words than this form's choices is not an answer
        if answer is not None:
            if norm not in self.guessed and self.attention is not None:
                self.attention.alert(f"Guessed, please check: {question.strip()[:90]} -> {answer[:90]}")
            self.guessed[norm] = (question.strip(), answer)
        return answer

    def is_guessed(self, question: str) -> bool:
        return normalize(question) in self.guessed

    def reject_guess(self, question: str, options: Optional[Sequence[str]] = None, read: Optional[Reader] = None) -> None:
        """The form refused a guess: forget it everywhere, never take it back as your answer, and ask you instead."""
        norm = normalize(question)
        question_, answer = self.guessed.pop(norm, (question.strip(), ""))
        self._rejected[norm] = answer
        if self.guesses is not None:
            self.guesses.forget(question)
        withdraw = getattr(self.guesser, "reject", None)  # the AI must not hand the same guess to the next job
        if withdraw is not None:
            withdraw(question, options)
        if self.attention is not None:
            self.attention.alert(f"The form did not accept my guess for: {question_[:90]}. I will ask you instead.")
        self.park(question, options, read)

    def known(self, question: str) -> Optional[str]:
        """What you yourself have said about this: a saved answer, or a fact from your profile. Never the AI's guess. Used for what
        only you may decide (an agreement, a legal declaration), where a guess is not an answer."""
        norm = normalize(question)
        return self._lookup(norm) if norm else None

    def park(self, question: str, options: Optional[Sequence[str]] = None, read: Optional[Reader] = None) -> None:
        """Nobody could answer this: record it for you (with the job that asked), and, if the form is open, watch its control so an
        answer typed there is read back and saved."""
        norm = normalize(question)
        if not norm:
            return
        self.unknown[norm] = question.strip()
        if read is not None:
            self._watching[norm] = (question.strip(), options, read)
        self.db.add_question(norm, question.strip(), options, self.portal, self.context)

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
            if not value or (options and value not in options) or value == self._rejected.get(norm) or NOT_AN_ANSWER.match(value):
                self._seen.pop(norm, None)  # empty, not a choice, the refused guess, or an instruction the control shows before anyone answers
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
        if self.guesses is not None:
            self.guesses.forget(raw)  # what you said outranks a guess: the guess is of no use any more
        self.db.drop_question(norm)  # it is answered now: the Questions button stops glowing for it
        self.unknown.pop(norm, None)
        self._stop_watching(norm)
        if self.attention is not None:
            self.attention.alert(f"Saved your answer to: {raw[:90]}")

    def note_unanswered(self, questions: Sequence[str]) -> None:
        """Record each question that has no saved answer, so the Questions page lists it for you. Never asks the AI: this is for
        questions a portal told us about but showed no form for, so nothing could be typed anywhere and an answer would be wasted."""
        for question in questions:
            norm = normalize(question)
            if norm and self._lookup(norm) is None:
                self.park(question)

    def require_complete(self) -> None:
        """Adapters call this before submitting. A required tick box answered No ends the job (asking more is pointless);
        any unknown question parks it."""
        if self.refused:
            raise Declined(self.refused.values())
        if self.unknown:
            raise NeedsAnswer(self.unknown.values())
