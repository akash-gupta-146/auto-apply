"""Decide the next step of an application. Rules first (free), the AI only when the page is not clear.

Order of thought: is there anything to fill in? Then fill it, and ask for what only you can give. When nothing is left to fill: send
(never without approval), or move the form on, or find the way to apply. Anything else goes to the AI, which may only propose
pressing, scrolling, waiting, going back, asking you, or stopping, and whose proposal is validated like any other (guard.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .autofill import Autofill
from .brain import Brain
from .labels import APPLY_LABEL, CONTINUE_LABEL, sends
from .models import Action, ActionType, Element, Observation, PageInfo, PageKind
from .session import Session

NEEDS_PERSON = {
    PageKind.LOGIN: "This page asks you to sign in. Sign in in the browser yourself; I never type a password. I will carry on once you are in.",
    PageKind.SIGNUP: "This page asks to create an account. I do not create accounts: do it yourself in the browser, and I will carry on.",
    PageKind.ASSESSMENT: "This is a test or assessment. Take it yourself; I will carry on afterwards.",
    PageKind.INTERVIEW_SCHEDULING: "This is about booking an interview time. Choose a time yourself; I will carry on afterwards.",
    PageKind.JOB_LISTING: "This is a list of jobs. Open the one you want and start the agent on that page: I do not choose a job for you.",
    PageKind.CAREERS_PAGE: "This is a careers page, not one job. Open the job you want and start the agent on that page.",
}


@dataclass
class Plan:
    actions: List[Action] = field(default_factory=list)
    waiting: List[str] = field(default_factory=list)  # questions nobody could answer: asked of you
    manual: List[str] = field(default_factory=list)  # things only you can do (a password, a document)
    declined: List[str] = field(default_factory=list)  # a required tick box your own answer says not to tick
    note: str = ""


def _press(e: Element, reason: str, **extra) -> Action:
    return Action(ActionType.CLICK_ELEMENT, e.ref, label=e.name[:80], reason=reason, **extra)


def _real_button_first(e: Element):
    """Sort key: an actual button, then anything else that can be pressed; a tab or a step label last; the page's main part before its edges."""
    return (e.tag != "button", e.role == "tab" or e.tag == "li", e.region != "main")


class Planner:
    def __init__(self, autofill: Autofill, brain: Optional[Brain] = None):
        self.autofill, self.brain = autofill, brain

    def plan(self, obs: Observation, info: PageInfo, session: Session) -> Plan:
        if info.kind is PageKind.UNRELATED and info.confidence >= 0.5:
            return Plan([Action(ActionType.COMPLETE, reason="this page is not about a job")], note="not a job page")
        if info.kind is PageKind.CONFIRMATION:
            return Plan([Action(ActionType.VERIFY_SUBMISSION, reason="the page looks like a confirmation")])
        if info.kind in NEEDS_PERSON:
            return Plan([Action(ActionType.ASK_USER, value=NEEDS_PERSON[info.kind], reason=info.kind.value)], manual=[NEEDS_PERSON[info.kind]])
        filled = self.autofill.plan(obs) if info.kind.in_application else Plan()  # a newsletter box on a job page is not part of the application
        waiting = list(self.autofill.resolver.unknown.values())
        if filled.actions or waiting or filled.manual or filled.declined:
            return Plan(filled.actions, waiting, filled.manual, filled.declined, "filling in the form")
        return Plan([self._navigate(obs, info, session)], note="moving on")

    # -- nothing is left to fill: which button? ---------------------------------------------------------------------------
    def _navigate(self, obs: Observation, info: PageInfo, session: Session) -> Action:
        buttons = [e for e in obs.scope() if e.is_button and not e.disabled and e.name]
        for e in buttons:
            if sends(e.name, info.kind.in_application):
                return _press(e, "the last step: this sends the application", submits=True)
        onward = sorted((e for e in buttons if CONTINUE_LABEL.search(e.name)), key=_real_button_first)
        if onward:  # a real button first: a stepper along the top ("My Information ... Review") has a label that reads like Continue, and does nothing
            return _press(onward[0], "move the form on")
        way_in = sorted((e for e in buttons if APPLY_LABEL.search(e.name)), key=_real_button_first)
        if way_in:
            return _press(way_in[0], "the way to apply for this job")
        if self.brain is not None:
            proposed = self.brain.next_action(obs, info, self._progress(session))
            if proposed is not None:
                return proposed
        return Action(ActionType.ASK_USER, value="I cannot tell how to go on from this page. Please take the next step in the browser, and I will carry on.",
                      reason="no clear next step")

    @staticmethod
    def _progress(session: Session) -> str:
        return f"done: {', '.join(session.completed[-5:]) or 'nothing'}; last pressed: {', '.join(session.clicked[-2:]) or 'nothing'}"
