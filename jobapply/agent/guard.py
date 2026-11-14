"""Check every action before it is carried out, whoever proposed it. The AI proposes; this decides.

What it enforces, because a mistaken or manipulated plan must not be able to do these:
  * a control is named by a number that exists on the page right now (or by a name that is unique), and can be used;
  * nothing is typed into a password, one-time-code or security-check box: those belong to the person;
  * a login or sign-up button is never pressed: the person signs in, then the agent carries on;
  * only the resume files the agent was given can be attached, whatever path an AI suggests;
  * anything that may send the application is marked as one, and always needs the person's approval;
  * the same press is not tried again and again.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Set
from urllib.parse import urlparse

from .labels import DENY_LABEL, LOGIN_LABEL, is_secret, sends
from .models import NEEDS_TARGET, Action, ActionType, Element, Observation, PageInfo

MAX_VALUE = 2_000
MIN_CONFIDENCE = 0.5  # an AI that is less sure than this is not acted on
MAX_REPEATS = 3
SAFE_SCHEMES = ("http", "https", "")


@dataclass
class Verdict:
    ok: bool
    action: Action  # as it will be carried out: its target resolved, and marked if it may send the application
    reason: str = ""
    needs_approval: bool = False  # pressing it may send the application
    needs_user: bool = False  # only a person can do this: sign in, a code, a security check


def action_key(action: Action, obs: Observation) -> str:
    return f"{action.type.value}|{obs.url}|{action.label or action.ref}|{action.value[:30]}"


def _resolve(action: Action, obs: Observation) -> Optional[Element]:
    """The control an action means. A name must match exactly one control: guessing between two is how a wrong button is pressed."""
    if action.strategy == "label" and action.label:
        found = [e for e in obs.scope() if e.name.strip().lower() == action.label.strip().lower()]
        return found[0] if len(found) == 1 else None
    return obs.find(action.ref)


def check(action: Action, obs: Observation, info: PageInfo, *, allowed_files: Set[Path],
          repeats: Optional[Dict[str, int]] = None) -> Verdict:
    if action.source == "ai" and action.confidence < MIN_CONFIDENCE:
        return Verdict(False, action, f"the AI was not sure enough ({action.confidence:.0%})")
    if action.type not in NEEDS_TARGET:
        return Verdict(True, action)
    element = _resolve(action, obs)
    if element is None:
        return Verdict(False, action, "that control is not on the page (or its name matches more than one)")
    action = replace(action, ref=element.ref, label=action.label or element.question or element.name)
    if element.disabled:
        return Verdict(False, action, "that control is disabled")
    if repeats is not None and repeats.get(action_key(action, obs), 0) >= MAX_REPEATS:
        return Verdict(False, action, f"already tried {MAX_REPEATS} times with no effect")
    return _CHECKS[action.type](action, element, info, allowed_files)


def _typing(action: Action, element: Element, info: PageInfo, allowed: Set[Path]) -> Verdict:
    if is_secret(element.name, element.legend, element.placeholder) or element.type == "password":
        return Verdict(False, action, "that box is for a password or a security code: only you can fill it in", needs_user=True)
    if not element.is_field:
        return Verdict(False, action, "that control is not a box or a choice")
    if not action.value.strip() or len(action.value) > MAX_VALUE:
        return Verdict(False, action, "there is nothing to type, or it is far too long")
    return Verdict(True, action)


def _upload(action: Action, element: Element, info: PageInfo, allowed: Set[Path]) -> Verdict:
    if not element.is_file:
        return Verdict(False, action, "that control does not take a file")
    if Path(action.value).resolve() not in allowed:
        return Verdict(False, action, "that file is not one of your resumes")
    return Verdict(True, action)


def _click(action: Action, element: Element, info: PageInfo, allowed: Set[Path]) -> Verdict:
    label = element.name
    if element.href and urlparse(element.href).scheme not in SAFE_SCHEMES:
        return Verdict(False, action, "that link is not a web page")
    if LOGIN_LABEL.search(label):
        return Verdict(False, action, "it needs you to sign in or create an account", needs_user=True)
    if DENY_LABEL.search(label):
        return Verdict(False, action, f"'{label[:40]}' is not something the agent presses")
    if action.submits or sends(label, info.kind.in_application):
        return Verdict(True, replace(action, submits=True), needs_approval=True)
    return Verdict(True, action)


_CHECKS = {
    ActionType.FILL_FIELD: _typing, ActionType.SELECT_OPTION: _typing, ActionType.UPLOAD_FILE: _upload, ActionType.CLICK_ELEMENT: _click,
}
