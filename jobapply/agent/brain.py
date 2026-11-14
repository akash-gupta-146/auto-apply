"""The AI's part of the agent: classify an unclear page, choose the next press when the rules cannot, judge an unclear submission.

It is asked only when the rules are unsure, so most pages cost nothing. Everything it says is checked, never trusted:
  * it returns JSON, and a reply that is not valid for the question is thrown away;
  * it may propose pressing, scrolling, waiting, going back, asking you, or stopping. It can never type a value into a form: what goes
    in a field comes only from your own facts (see autofill.py);
  * what it says about a page it must quote from the page, and the quote is checked: "submitted" without one is "unclear";
  * it sees a short description of the page with your email and phone number removed, never the page itself or what you typed.
Each request is capped per application, and every answer is appended to data/ai_agent.jsonl.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from ..ai_answers import redact, squash
from ..ai_ledger import Ledger
from ..llm import Completer, LlmError, extract_json
from .models import Action, ActionType, AppStatus, JobInfo, Observation, PageInfo, PageKind

log = logging.getLogger("jobapply")
MAX_CALLS = 25  # per application: the agent must not spend a day's AI allowance on one stubborn page
PROPOSABLE = (ActionType.CLICK_ELEMENT, ActionType.SCROLL_PAGE, ActionType.WAIT_FOR_CHANGE, ActionType.NAVIGATE_BACK,
              ActionType.ASK_USER, ActionType.COMPLETE)

CLASSIFY = (
    "You classify one web page for a job-application assistant. Reply with a single JSON object: "
    '{"kind": one of ' + str([k.value for k in PageKind]) + ', "confidence": number 0 to 1, '
    '"job": {"title": str, "company": str, "location": str, "job_id": str, "employment_type": str, "experience": str} or null, '
    '"reason": short sentence}. Use "unrelated" for anything that is not part of finding or applying for a job. '
    "Copy job facts exactly as the page words them; leave a fact empty rather than guess it."
)
NEXT_STEP = (
    "You steer a browser through a job application. The page is described below; controls are numbered [ref]. Reply with a single JSON "
    'object: {"action": one of ' + str([a.value for a in PROPOSABLE]) + ', "ref": the number of the control to press or null, '
    '"reason": short sentence, "expected": what should change afterwards, "confidence": number 0 to 1}. '
    "Choose the control that moves the application forward (the way to apply, to continue, to open the form). Never choose sign-in, "
    "sign-up, delete, share or anything unrelated to applying. If the way forward is not clear, reply ASK_USER. If the page is not "
    "about a job application, reply COMPLETE. You cannot type into fields: that is done separately."
)
SUBMISSION = (
    "A job application form was just submitted. From the page text, decide what happened. Reply with a single JSON object: "
    '{"status": "submitted" | "failed" | "incomplete" | "unclear", "evidence": a sentence copied exactly from the page text, '
    '"reason": short sentence}. "submitted" only when the page itself says the application was received; "incomplete" for '
    'validation errors; "failed" for a server error; otherwise "unclear". Never guess.'
)


class Brain:
    def __init__(self, client: Completer, ledger: Optional[Ledger] = None, max_calls: int = MAX_CALLS):
        self.client, self.ledger, self.max_calls = client, ledger, max_calls
        self.calls = 0
        self._cache: Dict[str, Any] = {}

    # -- asking ---------------------------------------------------------------------------------------------------------
    def _ask(self, purpose: str, system: str, user: str, key: str, cache: bool = True) -> Optional[Dict[str, Any]]:
        if cache and key in self._cache:
            return self._cache[key]
        if self.calls >= self.max_calls or self.client.remaining <= 0:
            return None
        self.calls += 1
        try:
            reply = extract_json(self.client.complete(system, redact(user), json_mode=True, max_tokens=400))
        except LlmError as exc:
            log.warning("agent AI (%s) failed: %s", purpose, str(exc)[:160])
            return None
        if not isinstance(reply, dict):
            return None
        if cache:
            self._cache[key] = reply
        if self.ledger is not None:
            self.ledger.note(purpose=purpose, key=key, reply=reply)
        return reply

    # -- what kind of page ------------------------------------------------------------------------------------------------
    def classify(self, obs: Observation) -> Optional[PageInfo]:
        reply = self._ask("classify", CLASSIFY, obs.brief(40), f"classify|{obs.signature()}")
        if reply is None:
            return None
        try:
            kind = PageKind(str(reply.get("kind")))
        except ValueError:
            return None
        return PageInfo(kind, _confidence(reply.get("confidence")), "ai", self._job(reply.get("job"), obs), str(reply.get("reason", ""))[:160])

    @staticmethod
    def _job(raw: object, obs: Observation) -> JobInfo:
        """Job facts from the AI count only when the page really says them: a title or company it made up is dropped."""
        if not isinstance(raw, dict):
            return JobInfo()
        page = squash(f"{obs.title} {obs.text} {' '.join(obs.headings)}")
        facts = {name: str(raw.get(name) or "").strip()[:150] for name in ("title", "company", "location", "job_id", "employment_type", "experience")}
        return JobInfo(**{name: value for name, value in facts.items() if value and squash(value) in page}, url=obs.url)

    # -- what to press ----------------------------------------------------------------------------------------------------------
    def next_action(self, obs: Observation, info: PageInfo, progress: str) -> Optional[Action]:
        context = f"Page kind: {info.kind.value}\nProgress so far: {progress or 'just started'}\n\n{obs.brief()}"
        reply = self._ask("next_step", NEXT_STEP, context, f"next|{obs.signature()}|{progress[-80:]}", cache=False)
        if reply is None:
            return None
        try:
            kind = ActionType(str(reply.get("action")))
        except ValueError:
            return None
        if kind not in PROPOSABLE:
            return None
        ref = reply.get("ref") if isinstance(reply.get("ref"), int) else None
        element = obs.find(ref)
        if kind is ActionType.CLICK_ELEMENT and element is None:
            return None  # a press on a control that is not on the page
        return Action(kind, ref, label=element.name if element else "", reason=str(reply.get("reason", ""))[:160],
                      expected=str(reply.get("expected", ""))[:160], confidence=_confidence(reply.get("confidence")), source="ai")

    # -- what happened -----------------------------------------------------------------------------------------------------------
    def judge_submission(self, obs: Observation) -> Optional[Tuple[AppStatus, str]]:
        reply = self._ask("submission", SUBMISSION, f"Page text:\n{obs.text[:2500]}", f"judge|{obs.signature()}")
        if reply is None:
            return None
        status = {"submitted": AppStatus.SUBMITTED, "failed": AppStatus.FAILED, "incomplete": AppStatus.INCOMPLETE}.get(str(reply.get("status")))
        evidence = str(reply.get("evidence") or "").strip()
        if status is None or not evidence or squash(evidence) not in squash(obs.text):
            return None  # no verdict that cannot be shown on the page itself
        return status, evidence[:200]


def _confidence(raw: object) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0
