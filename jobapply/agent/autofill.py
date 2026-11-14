"""Turn the fields on the page into actions: what to type, tick or attach, and what only you can answer.

A field is understood by its meaning (the words around it), never by its name or id. The answer comes from the same place as on every
other portal: your saved answers, then the profile's rules, then the grounded AI (see answers.py). Nothing is invented. If you allow it
(`guess`), the AI's best guess comes last, before you are asked (see ai_guess.py): it is flagged as a guess, and a guess the form
refuses is withdrawn and asked of you. A question with no answer is recorded for you and waited on.

Two kinds of question are never settled by an AI, only by an answer you saved yourself: declarations ("I certify...", terms, consent)
and legally significant ones (work authorization, sponsorship, background checks).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..adapters.forms import OPTIONAL, field_text
from ..answers import AnswerResolver, pick_option
from .labels import LEGAL, SEARCH_BOX, SIDE_WIDGET, is_consent, is_secret
from .models import Action, ActionType, Element, Observation

RESUME_WORDS = re.compile(r"\b(?:resume|r[eé]sum[eé]|cv|curriculum vitae)\b", re.I)
CHOICE_KINDS = ("select", "popup")


def shown(question: str, limit: int) -> str:
    """A question as the person is told about it: without the form's own required-marker (\"Full name *\")."""
    return question.strip().rstrip("*").strip()[:limit]


@dataclass
class FillPlan:
    actions: List[Action] = field(default_factory=list)
    manual: List[str] = field(default_factory=list)  # required, and only a person can do it: a password, a document that is not the resume
    declined: List[str] = field(default_factory=list)  # a required tick box that your own answer says not to tick


class Autofill:
    def __init__(self, resolver: AnswerResolver, browser, resume: Optional[Path] = None, guess: bool = False):
        self.resolver, self.browser, self.resume, self.guess = resolver, browser, resume, guess

    def plan(self, obs: Observation) -> FillPlan:
        self.resolver.start_pass()
        found = FillPlan()
        for unit in self._units(obs):
            first = unit[0]
            if first.is_file:
                self._file(first, found)
            elif first.is_choice:
                self._choices(unit, found)
            else:
                self._box(first, found)
        found.declined = list(self.resolver.refused.values())
        return found

    # -- what is on the page, as questions ----------------------------------------------------------------------
    @staticmethod
    def _units(obs: Observation) -> List[List[Element]]:
        """Fields in page order; the buttons of one radio group (or tick-box group) are one question, not several."""
        units: List[List[Element]] = []
        grouped: Dict[str, List[Element]] = {}
        for e in obs.scope():
            if not e.is_field or e.disabled or e.type == "search" or e.role == "searchbox":
                continue
            if SIDE_WIDGET.search(f"{e.name} {e.question} {e.placeholder}"):
                continue  # a bookmark, a follow, a job-alert or newsletter opt-in: nothing the application asks for, and never ticked for you
            if e.is_choice and e.group and (e.legend or e.is_radio):  # a radio group is one question even with no legend
                key = f"{e.group}|{e.legend}"
                if key not in grouped:
                    grouped[key] = []
                    units.append(grouped[key])
                grouped[key].append(e)
            else:
                units.append([e])
        return units

    @staticmethod
    def _required(elements: List[Element], question: str) -> bool:
        if OPTIONAL.search(question):
            return False
        return any(e.required or e.invalid for e in elements) or question.rstrip().endswith("*")

    # -- one question ----------------------------------------------------------------------------------------------
    def _answer(self, question: str, options: Optional[List[str]], required: bool, elements: List[Element]) -> Optional[str]:
        """The answer, or None. A question nobody can answer is recorded, and watched, so you may answer it in the form or the panel."""
        if is_consent(question, *(options or [])) or LEGAL.search(question):
            answer = self.resolver.known(question)
            answer = pick_option(answer, options) if answer is not None and options else answer
        else:
            answer = self.resolver.resolve(question, options, required=required, may_guess=self.guess)
        if answer is None and required:
            self.resolver.park(question, options, self.browser.reader(elements))
        return answer

    def _box(self, e: Element, found: FillPlan) -> None:
        question = e.question
        if question and e.invalid and self.resolver.is_guessed(question):  # the form refused my guess: ask you, do not type over it
            self.resolver.reject_guess(question, e.options or None, self.browser.reader([e]))
            return
        if e.filled or not question or SEARCH_BOX.search(question) and not e.required:
            return
        required = self._required([e], question)
        if is_secret(question, e.placeholder) or e.type == "password":
            if required:
                found.manual.append(question[:80])
            return
        popup_or_select = e.tag == "select" or e.popup
        answer = self._answer(question, e.options or None, required, [e])
        if answer is None:
            return
        text = answer if popup_or_select else field_text(e.type if e.type != "contenteditable" else "text", answer)
        if text is None:  # an answer that cannot be typed here ("30 days" in a date box): left for the person
            return
        kind = ActionType.SELECT_OPTION if popup_or_select else ActionType.FILL_FIELD
        found.actions.append(Action(kind, e.ref, label=shown(question, 80), value=text, reason="your saved answer, a rule, or the AI",
                                    expected="the box holds it"))

    def _choices(self, unit: List[Element], found: FillPlan) -> None:
        lone = len(unit) == 1 and not unit[0].is_radio
        options = ["Yes", "No"] if lone else [e.name for e in unit]
        question = unit[0].legend or (unit[0].name if lone else "Choose one of: " + ", ".join(options))
        if any(e.invalid for e in unit) and self.resolver.is_guessed(question):  # the form refused my guess: ask you
            self.resolver.reject_guess(question, options, self.browser.reader(unit))
            return
        if any(e.checked for e in unit):
            return  # already chosen, by the page or by an earlier step
        required = self._required(unit, question)
        answer = self._answer(question, options, required, unit)
        if answer is None:
            return
        if lone:
            if answer == "Yes":
                found.actions.append(Action(ActionType.SELECT_OPTION, unit[0].ref, label=shown(question, 80), value="yes", expected="it is ticked"))
            elif required:
                self.resolver.refuse(question)  # the page will not go on without the tick, and the answer says not to tick
            return
        chosen = next((e for e in unit if e.name == answer), None)
        if chosen is not None:
            found.actions.append(Action(ActionType.SELECT_OPTION, chosen.ref, label=f"{shown(question, 60)} -> {chosen.name[:40]}",
                                        value=chosen.name, expected="it is chosen"))

    def _file(self, e: Element, found: FillPlan) -> None:
        if e.filled:
            return
        if RESUME_WORDS.search(f"{e.name} {e.legend}") and self.resume is not None:
            found.actions.append(Action(ActionType.UPLOAD_FILE, e.ref, label=shown(e.name, 80), value=str(self.resume),
                                        reason="the resume chosen for this job", expected="the file is attached"))
        elif e.required:
            found.manual.append(f"Attach: {e.name[:70] or 'a document'}")  # a cover letter or certificate is yours to write or choose
