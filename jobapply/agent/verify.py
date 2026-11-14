"""After Submit: find out, from the page itself, whether the application really went through. Never assume, never press Submit again.

Evidence, strongest first: the page says the application was received (a confirmation or reference number); the site says it is a
duplicate; the page shows validation errors (the form did not go: some fields need answers); the page shows a server error. A page that
shows none of these is ambiguous, and an ambiguous result is "Verification Pending" for you to check, not a success and not a retry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .labels import CONFIRMED
from .models import AppStatus, Observation

VERIFY_MS = 15_000
POLL_MS = 500
DUPLICATE = re.compile(r"\b(?:already (?:applied|submitted)|you(?:'ve| have) already|duplicate application|application already (?:exists|received))\b", re.I)
SERVER_ERROR = re.compile(
    r"\b(?:something went wrong|try again later|unable to (?:submit|process|complete)|server error|failed to submit|error (?:occurred|submitting)|"
    r"service unavailable|internal error|(?:http )?50[0-4])\b", re.I)
VALIDATION = re.compile(r"\b(?:required|invalid|please (?:enter|select|provide|fill|choose|correct|complete)|must (?:be|not)|can't be blank|is not valid)\b", re.I)
REFERENCE = re.compile(r"(?:reference|confirmation|application|tracking)\s*(?:number|no\.?|id|code|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.I)
CONFIRMATION_URL = re.compile(r"(?:confirm|thank|success|submitted|post-?apply|applied|complete)", re.I)


@dataclass
class Verdict:
    status: AppStatus
    evidence: str = ""
    reference: str = ""
    errors: List[str] = field(default_factory=list)


def _sentence(text: str, pattern: re.Pattern) -> str:
    found = pattern.search(text)
    if not found:
        return ""
    start = max(text.rfind("\n", 0, found.start()), 0)
    end = text.find("\n", found.end())
    return " ".join(text[start:end if end >= 0 else None].split())[:200]


def reference_in(text: str) -> str:
    found = REFERENCE.search(text)
    return found.group(1) if found else ""


def decide(obs: Observation, started_on: str, *, after_submit: bool = True) -> Optional[Verdict]:
    """What this page proves, or None while it proves nothing yet."""
    fields = [e for e in obs.scope() if e.is_field and not e.disabled]
    if DUPLICATE.search(obs.text):
        status = AppStatus.DUPLICATE if after_submit else AppStatus.ALREADY_SUBMITTED
        return Verdict(status, _sentence(obs.text, DUPLICATE))
    if CONFIRMED.search(obs.text) and len(fields) <= 1:
        return Verdict(AppStatus.SUBMITTED, _sentence(obs.text, CONFIRMED), reference_in(obs.text))
    if after_submit and obs.url != started_on and CONFIRMATION_URL.search(obs.url.split("?")[0]) and not fields:
        return Verdict(AppStatus.SUBMITTED, f"the page moved to {obs.url[:120]}, which has no form left", reference_in(obs.text))
    errors = [a for a in obs.alerts if VALIDATION.search(a)] + [f"'{e.question[:60]}' is not accepted" for e in fields if e.invalid]
    if errors:
        return Verdict(AppStatus.INCOMPLETE, errors[0], errors=errors[:6])
    if SERVER_ERROR.search(" ".join(obs.alerts) or obs.text[:1500]):
        return Verdict(AppStatus.FAILED, _sentence(obs.text, SERVER_ERROR) or "the site reported an error")
    return None


def wait_for_verdict(look: Callable[[], Observation], started_on: str, judge=None, wait_ms: int = VERIFY_MS, pause=lambda ms: None,
                     poll_ms: int = POLL_MS) -> Verdict:
    """Keep looking, for a bounded while, until the page proves what happened. If it never does, an AI may read the page (its answer
    must quote the page); if that proves nothing either, the application is Verification Pending."""
    seen: Optional[Observation] = None
    for _ in range(max(1, wait_ms // poll_ms)):
        seen = look()
        verdict = decide(seen, started_on)
        if verdict is not None:
            return verdict
        pause(poll_ms)
    if judge is not None and seen is not None:
        judged = judge(seen)
        if judged is not None:
            status, evidence = judged
            return Verdict(status, evidence, reference_in(seen.text))
    return Verdict(AppStatus.VERIFICATION_PENDING, "the page did not say whether the application was received")
