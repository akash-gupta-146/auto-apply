"""The agent: Observe -> Understand -> Plan -> Validate -> Act -> Verify, until the application is done or needs you.

It starts on whatever tab you have open. It works out what the page is, finds the way to apply, fills what your facts can answer,
asks you for the rest, and stops before sending until you approve. After sending it checks the page for proof, and records the result.
Every step is bounded (steps, time, repeated presses), and the agent never presses Submit twice for one application.
"""
from __future__ import annotations

import logging
import os
import re
import time
import traceback
from collections import Counter
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from ..adapters.base import RENDERED_MIN_CHARS, looks_like_challenge
from ..adapters.forms import let_person_answer
from ..adapters.prompts import dismiss_prompts
from ..answers import AnswerResolver, Attention
from ..config import Paths, Profile
from ..db import Database
from . import guard, history, resumes, verify
from .act import Browser
from .autofill import Autofill, shown
from .brain import Brain
from .hitl import APPROVAL_STEP, APPROVE, AgentState, Channel, wait_for
from .models import Action, ActionType, AppStatus, Observation, PageInfo, PageKind
from .observe import PageUnreadable, observe
from .planner import Plan, Planner
from .session import Session
from .understand import classify

log = logging.getLogger("jobapply")

MAX_STEPS = 80
SETTLE_LOOKS = 5  # a page that looks like nothing yet, and says almost nothing, is looked at again this many times
SETTLE_MS = 1000  # ...this far apart: a single-page app draws itself a moment after the click that opened it
MAX_SAME = 3  # the same page and the same action this many times in a row means the agent is going in circles
MAX_RESUBMITS = 2  # a form that refuses a send may be fixed and sent again, with a fresh approval, this many times
KEEP_OPEN = re.compile(r"appl|resume|\bcv\b|submit|continue|next|question|upload|sign in|log in|login|candidate|"
                       r"(?:your|create|complete|finish|update|edit|build) (?:a |your |the )?profile|cookie preferences", re.I)  # not a bare "profile": cookie notices say "a personal profile on you"

STEP_NAMES = {
    PageKind.JOB_DETAILS: "Job details", PageKind.APPLICATION_FORM: "Application form", PageKind.RESUME_UPLOAD: "Resume upload",
    PageKind.SCREENING_QUESTIONS: "Screening questions", PageKind.APPLICATION_REVIEW: "Review", PageKind.CANDIDATE_PROFILE: "Candidate profile",
    PageKind.CONFIRMATION: "Confirmation", PageKind.LOGIN: "Sign in", PageKind.SIGNUP: "Sign up", PageKind.ASSESSMENT: "Assessment",
    PageKind.INTERVIEW_SCHEDULING: "Interview scheduling", PageKind.JOB_LISTING: "Job list", PageKind.CAREERS_PAGE: "Careers page",
}


def where_it_happened(exc: BaseException) -> str:
    """\" (in brain.py line 59, _ask)\": where in this program an error came from, so the one line the report keeps (the feed, the job's reason)
    can be traced without the log. (Three crashes said only \"'int' object is not callable\", and the traceback was not kept.)"""
    ours = [frame for frame in traceback.extract_tb(exc.__traceback__) if f"{os.sep}jobapply{os.sep}" in frame.filename]
    return f" (in {os.path.basename(ours[-1].filename)} line {ours[-1].lineno}, {ours[-1].name})" if ours else ""


class Agent:
    def __init__(self, page, profile: Profile, paths: Paths, db: Database, resolver: AnswerResolver, *, brain: Optional[Brain] = None,
                 submit: bool = False, ask_approval: bool = True, session: Optional[Session] = None, minutes: float = 30, answer_wait_s: float = 300,
                 challenge_wait_s: float = 300, approval_wait_s: float = 600, answers_loader: Optional[Callable[[], Dict[str, str]]] = None,
                 clock: Callable[[], float] = time.monotonic, max_steps: int = MAX_STEPS, channel: Optional[Channel] = None,
                 verify_ms: int = verify.VERIFY_MS, guess: bool = False):
        self.profile, self.paths, self.db, self.resolver, self.brain = profile, paths, db, resolver, brain
        self.allow_submit, self.clock, self.max_steps, self.verify_ms = submit, clock, max_steps, verify_ms
        self.ask_approval = ask_approval  # False only when the person chose, up front, to let it send without asking each time
        self.answer_wait_s, self.challenge_wait_s, self.approval_wait_s = answer_wait_s, challenge_wait_s, approval_wait_s
        self.deadline = clock() + minutes * 60
        self.session = session or Session.create(paths.agent_dir)
        self.channel = channel or Channel(paths)
        self.browser = Browser(page)
        self.autofill = Autofill(resolver, self.browser, guess=guess)  # guess: the AI's best guess at what nothing else can answer
        self.planner = Planner(self.autofill, brain)
        self.resume_chosen = False
        self.unrelated = False  # the page was not about a job: nothing was done and nothing is recorded
        self.verdict = ""  # ...and then, what was looked at and what to do about it: said to the person, never left to guesswork
        self._repeats: Dict[str, int] = {}
        self._circles: Counter = Counter()
        self._resubmits = 0
        self._backs = 0
        self._last_kind: Optional[PageKind] = None
        self._given_up: Set[str] = set()
        resolver.attention = Attention(self._patience, self.session.say, answers_loader or (lambda: dict(resolver.raw_bank)), self._given_up)
        self._keep_answers_in_session(resolver)

    def _keep_answers_in_session(self, resolver: AnswerResolver) -> None:
        saved = resolver.persist

        def persist(question: str, answer: str) -> None:
            self.session.answers[question[:120]] = answer[:200]  # what you told the agent, kept with this application
            if saved is not None:
                saved(question, answer)

        resolver.persist = persist

    def _patience(self) -> float:
        return max(0.0, min(self.answer_wait_s, self.deadline - self.clock()))

    # -- the run -------------------------------------------------------------------------------------------------------------
    def run(self) -> Session:
        s = self.session
        self._state(AgentState.ANALYZING, "reading the current page")
        try:
            self._loop()
        except KeyboardInterrupt:
            s.say("Stopped by you. Your progress is saved: resume it with `jobapply agent --resume-session`.")
        except Exception as exc:  # the agent never takes the program down: it reports what stopped it, and keeps the application
            log.exception("agent stopped by an error")  # the traceback goes to the run log: the feed only has room for one line
            where = where_it_happened(exc)
            s.say(f"Stopped by an error: {type(exc).__name__}: {' '.join(str(exc).split())[:160]}{where}")
            s.errors.append(f"{type(exc).__name__}: {str(exc)[:160]}{where}")
            s.finish(AppStatus.FAILED if s.submit_pressed else AppStatus.INCOMPLETE)
        finally:
            self._finish_up()
        return s

    def _finish_up(self) -> None:
        s = self.session
        if self.unrelated:
            self._forget_session()
            self.channel.set_state(AgentState.IDLE, detail=self.verdict)
            return
        self._save()
        done = {AppStatus.SUBMITTED: AgentState.COMPLETED, AppStatus.FAILED: AgentState.FAILED}.get(s.status, AgentState.IDLE)
        self.channel.set_state(done, s, s.status.label)

    def _forget_session(self) -> None:
        for suffix in (".json", ".feed"):
            if self.session.path is not None:
                self.session.path.with_suffix(suffix).unlink(missing_ok=True)

    def _save(self) -> None:
        self.session.save()
        history.record(self.db, self.session)

    def _state(self, state: AgentState, detail: str = "", questions: Optional[List[str]] = None) -> None:
        self.channel.set_state(state, self.session, detail, questions)

    # -- the loop -------------------------------------------------------------------------------------------------------------
    def _loop(self) -> None:
        s = self.session
        for _ in range(self.max_steps):
            if self.clock() >= self.deadline:
                s.say("Out of time. Your progress is saved; resume it later with `jobapply agent --resume-session`.")
                return
            self._while_paused()
            if not self.browser.ensure_page():
                s.finish(AppStatus.REQUIRES_USER)
                s.say("Every tab was closed.")
                return
            dismiss_prompts(self.browser.page, None, KEEP_OPEN)  # a cookie banner or advert: its "no", never anything that holds the application
            try:
                obs = self._observe_settled()
            except PageUnreadable:
                continue
            if looks_like_challenge(self.browser.page) and not self._human_check():
                return
            s.visit(obs.url)
            info = self._understand(obs)
            if self._unrelated_start(info):
                return
            if self._already_applied(obs, info):
                return
            plan = self._plan(obs, info)
            if self._carry_out(plan, obs, info):
                return
        s.say(f"Stopped after {self.max_steps} steps without finishing: a person should look at this one.")
        s.finish(AppStatus.REQUIRES_USER)

    def _observe_settled(self) -> Observation:
        """Look at the page. If it looks like nothing and says almost nothing, it is probably still drawing (a single-page app, just after
        the click that opened it): give it a moment and look again, rather than take a blank page for a detour out of the application."""
        page = self.browser.page
        obs = observe(page)
        for _ in range(SETTLE_LOOKS):
            if len(obs.text.strip()) >= RENDERED_MIN_CHARS or classify(obs).kind is not PageKind.UNRELATED:
                break
            page.wait_for_timeout(SETTLE_MS)
            obs = observe(page)
        return obs

    def _while_paused(self) -> None:
        if not self.channel.paused():
            return
        self._state(AgentState.PAUSED, "paused by you")
        self.session.say("Paused. Press Resume to go on.")
        wait_for(lambda: "" if self.channel.paused() else "go", max(self.deadline - self.clock(), 0), poll_s=1.0)
        self._state(AgentState.ANALYZING, "resumed")

    def _human_check(self) -> bool:
        """A security check: only you may solve it. Waits for you, and gives up (without trying anything) if nobody comes."""
        s = self.session
        s.say("A security check (captcha) is showing. Please solve it in the browser; I will not try to get past it.")
        self._state(AgentState.WAITING, "a security check needs you")
        outcome = wait_for(lambda: "" if looks_like_challenge(self.browser.page) else "solved", min(self.challenge_wait_s, self.deadline - self.clock()))
        if outcome == "solved":
            s.say("Thanks, the check is solved. Carrying on.")
            return True
        s.finish(AppStatus.REQUIRES_USER, step="Security check")
        s.say("Nobody solved the security check in time, so I stopped here.")
        return False

    # -- understanding -----------------------------------------------------------------------------------------------------------
    def _understand(self, obs: Observation) -> PageInfo:
        s = self.session
        info = classify(obs)
        if info.confidence < 0.6 and self.brain is not None:
            asked = self.brain.classify(obs)
            if asked is not None and asked.confidence >= info.confidence:
                asked.job.merge(info.job)
                info = asked
        if info.kind != self._last_kind:
            step = STEP_NAMES.get(info.kind, "")
            if self._last_kind in STEP_NAMES:  # the page moved on: the step it was on is done
                s.complete(STEP_NAMES[self._last_kind])
            s.step = step or s.step
            s.say(f"Page: {step or info.kind.value.replace('_', ' ')} ({info.reason}).")
            self._last_kind = info.kind
        if info.kind not in (PageKind.UNRELATED, PageKind.LOGIN, PageKind.SIGNUP):
            first = not s.job.known
            s.job.merge(info.job)
            self.resolver.context = s.job.context()
            if first and s.job.known:
                self._state(AgentState.JOB_DETECTED, s.job.context())
                s.say(f"Job detected: {s.job.context()}" + (f", {s.job.location}" if s.job.location else "") + ".")
            self._choose_resume(obs)
        return info

    def _choose_resume(self, obs: Observation) -> None:
        if self.resume_chosen:
            return
        self.resume_chosen = True
        chosen, why = resumes.choose(self.paths, self.profile, self.session.job.description or obs.text)
        if chosen is None:
            self.session.say("No resume found: I will ask you if a form needs one.")
            return
        self.autofill.resume = chosen
        self.browser.allowed_files = {chosen.resolve()}
        self.session.resume = chosen.name
        self.session.say(f"Resume chosen: {why}.")

    def _unrelated_start(self, info: PageInfo) -> bool:
        """The very first page is not about a job: do nothing at all, and record nothing."""
        s = self.session
        if info.kind is PageKind.UNRELATED and info.confidence >= 0.5 and not (s.clicked or s.filled or s.completed):
            self.unrelated, self.verdict = True, self._nothing_to_do()
            s.say(self.verdict)
            return True
        return False

    def _nothing_to_do(self) -> str:
        """Say which page was looked at: the likeliest reason for 'nothing happened' is that it was not the page the person meant."""
        page = self.browser.page
        try:
            title, host = " ".join(page.title().split())[:60], urlparse(page.url).hostname or ""
        except Exception:  # the page closed or is mid-navigation: say what is certain
            title = host = ""
        seen = f'"{title}" ({host})' if title and host else (host or "the page")
        return (f"I looked at {seen}. It is not a job or an application, so I did nothing. If your job is in another tab, bring that tab "
                "to the front, or give me its address (the Job page address box, or --url).")

    def _already_applied(self, obs: Observation, info: PageInfo) -> bool:
        """The site says you applied to this job before: nothing to do, and nothing to press."""
        s = self.session
        if s.submit_pressed or info.kind is PageKind.CONFIRMATION or not verify.DUPLICATE.search(obs.text[:1500]):
            return False
        s.finish(AppStatus.ALREADY_SUBMITTED, confirmation="")
        s.say(f"The site says you already applied to this job. Nothing sent. ({verify.decide(obs, obs.url, after_submit=False).evidence})")
        return True

    def _plan(self, obs: Observation, info: PageInfo) -> Plan:
        s = self.session
        if info.kind is PageKind.UNRELATED and (s.clicked or s.filled):  # a detour left the application: go back once, then ask
            if self._backs < 1:
                self._backs += 1
                s.say("This page is not part of the application. Going back.")
                return Plan([Action(ActionType.NAVIGATE_BACK, reason="a detour left the application")])
            return Plan([Action(ActionType.ASK_USER, value="The browser is on a page that is not part of the application. Please get back to it.")])
        return self.planner.plan(obs, info, s)

    # -- carrying out a plan -------------------------------------------------------------------------------------------------------
    def _carry_out(self, plan: Plan, obs: Observation, info: PageInfo) -> bool:
        """Returns True when the run is over."""
        s = self.session
        if plan.declined:
            s.finish(AppStatus.REQUIRES_USER, step=s.step)
            s.errors.append("A required tick box is answered No: " + "; ".join(plan.declined))
            s.say("Your saved answer to a required tick box is No, so this application cannot go on: " + "; ".join(plan.declined))
            return True
        moved, blocked = False, []
        for action in plan.actions:
            if action.type in (ActionType.COMPLETE, ActionType.VERIFY_SUBMISSION, ActionType.ASK_USER, ActionType.NAVIGATE_BACK):
                return self._special(action, obs, info)
            if self._circling(obs, action):
                return self._ask_and_wait("I seem to be going in circles on this page. Please take the next step in the browser.")
            verdict = guard.check(action, obs, info, allowed_files=self.browser.allowed_files, repeats=self._repeats)
            if verdict.needs_user:
                return self._ask_and_wait(verdict.reason.capitalize() + ". Please do it in the browser; I will carry on.")
            if not verdict.ok:
                s.say(f"Not doing '{action.label or action.type.value}': {verdict.reason}.")
                blocked.append(f"I will not do '{action.label or action.type.value}' ({verdict.reason}).")
                continue
            if verdict.needs_approval:
                return self._submit(verdict.action, obs, info)
            moved = self._do(verdict.action, obs) or moved
        if plan.waiting or plan.manual:
            return not self._wait_for_person(plan)
        if blocked:  # what was refused is yours to do: wait for the page to change, as it does when you do it
            return self._ask_and_wait(" ".join(blocked[:2]) + " Please do that in the browser yourself, and I will carry on.")
        if not moved and not plan.actions:
            self.browser.page.wait_for_timeout(300)
        return False

    def _do(self, action: Action, obs: Observation) -> bool:
        """Carry out one validated action and check its result. True when the page took it."""
        s = self.session
        key = guard.action_key(action, obs)
        if action.type is ActionType.UPLOAD_FILE:
            self._state(AgentState.UPLOADING, f"attaching {s.resume}")
        elif action.type is not ActionType.CLICK_ELEMENT:
            self._state(AgentState.APPLYING, action.label)
        outcome = self.browser.run(action)
        if action.type is ActionType.CLICK_ELEMENT:
            s.clicked.append(action.label)
        if outcome.ok and (action.type is not ActionType.CLICK_ELEMENT or outcome.detail != "the page did not change"):
            self._repeats.pop(key, None)
        else:
            self._repeats[key] = self._repeats.get(key, 0) + 1
        if outcome.page is not None:
            s.say(f"Continuing in a new tab ({outcome.page.url[:80]}).")
            s.visit(outcome.page.url)
        if outcome.ok and action.type in (ActionType.FILL_FIELD, ActionType.SELECT_OPTION):
            s.filled_in(action.label, action.value)
            s.say(f"Filled: {action.label}.")
        elif outcome.ok and action.type is ActionType.UPLOAD_FILE:
            s.say(f"Resume uploaded: {outcome.detail}.")
        elif outcome.ok:
            s.say(f"{action.describe()}: {outcome.detail}.")
        else:
            s.say(f"Could not {action.describe()}: {outcome.detail}.")
        return outcome.ok

    def _circling(self, obs: Observation, action: Action) -> bool:
        key = f"{obs.signature()}|{action.type.value}|{action.label}"
        self._circles[key] += 1
        return self._circles[key] > MAX_SAME

    # -- special actions ---------------------------------------------------------------------------------------------------------
    def _special(self, action: Action, obs: Observation, info: PageInfo) -> bool:
        s = self.session
        if action.type is ActionType.COMPLETE:
            s.say(f"Nothing more to do: {action.reason}.")
            return True
        if action.type is ActionType.VERIFY_SUBMISSION:
            return self._verify(obs.url, already=True)
        if action.type is ActionType.NAVIGATE_BACK:
            outcome = self.browser.run(action)
            s.say(f"Went back: {outcome.detail}.")
            return not outcome.ok and self._ask_and_wait("I could not get back to the application. Please open it again in the browser.")
        return self._ask_and_wait(action.value or action.reason)

    def _ask_and_wait(self, message: str) -> bool:
        """Something only you can do: say so, and wait for the page to change (you did it). True when the run is over."""
        s = self.session
        s.say(message)
        s.missing = [message[:160]]
        self._state(AgentState.WAITING, message, [message])
        self._save()
        start = self._signature()
        wait = min(self.answer_wait_s, max(self.deadline - self.clock(), 0))
        result = wait_for(lambda: "changed" if self._page_changed(start) else "", wait, poll_s=1.0)
        s.missing = []
        if result == "changed":
            s.say("The page changed: carrying on.")
            self._state(AgentState.APPLYING)
            return False
        s.finish(AppStatus.REQUIRES_USER)
        s.say("Waited for you, and nobody came. Your progress is saved: resume it later with `jobapply agent --resume-session`.")
        return True

    def _signature(self) -> str:
        try:
            return observe(self.browser.page, tries=1).signature()
        except PageUnreadable:
            return "moving"  # the page is in the middle of a move

    def _page_changed(self, start: str) -> bool:
        return self._signature() != start

    def _wait_for_person(self, plan: Plan) -> bool:
        """Questions no one could answer, or things only you can do. Returns True once they are done; False if nobody came."""
        s = self.session
        asked = plan.waiting + plan.manual
        s.missing = asked[:10]
        s.say("Missing information: " + "; ".join(asked[:4]) + ". Waiting for your answer: type it in the form, or answer on the Questions page.")
        self._state(AgentState.WAITING, "your answer is needed", asked[:6])
        self._save()
        if plan.waiting:
            let_person_answer(self.browser.page, self.resolver, self._fill_pass)
            if self.resolver.waiting_on():
                s.finish(AppStatus.REQUIRES_USER)
                s.say("Waited for your answer, and none came. Resume this application later, after answering on the Questions page.")
                return False
        if plan.manual:
            done = wait_for(lambda: "" if self.autofill.plan(observe(self.browser.page)).manual else "done", self._patience())
            if done != "done":
                s.finish(AppStatus.REQUIRES_USER)
                s.say("Waited for you to do: " + "; ".join(plan.manual[:3]) + ". Nobody came.")
                return False
        s.missing = []
        self._state(AgentState.APPLYING)
        return True

    def _fill_pass(self) -> None:
        """One more go at the form with the answers the person has just given."""
        try:
            obs = observe(self.browser.page)
        except PageUnreadable:
            return
        info = self._understand(obs)
        for action in self.autofill.plan(obs).actions:
            verdict = guard.check(action, obs, info, allowed_files=self.browser.allowed_files, repeats=self._repeats)
            if verdict.ok:
                self._do(verdict.action, obs)

    # -- sending and checking ------------------------------------------------------------------------------------------------------
    def _submit(self, action: Action, obs: Observation, info: PageInfo) -> bool:
        s = self.session
        if s.submit_pressed:  # never a second send for one application: look at what the first one did
            s.say("Submit was already pressed for this application: checking what happened instead of sending again.")
            return self._verify(obs.url)
        if not self.allow_submit:
            s.finish(AppStatus.READY, step="Ready to submit")
            s.say("Everything is filled in and the form is ready to send. This was a rehearsal, so I stopped before the final button. "
                  "Run with --submit to send it, after your approval." + self._guess_note())
            return True
        if self.ask_approval:
            self.channel.ask_approval(s, self._approval_summary())
            self._state(AgentState.WAITING, "approve the submission")
            s.say("Ready to submit. Waiting for your approval (press Approve in the panel, or run `jobapply agent --approve`).")
            decision = wait_for(lambda: self.channel.decision(s.id), min(self.approval_wait_s, max(self.deadline - self.clock(), 0)))
            self.channel.clear_approval()
        else:
            decision = APPROVE
            s.say("Ready to submit. You chose not to wait for approval, so it is being sent now.")
        if decision != APPROVE:
            s.finish(AppStatus.REQUIRES_USER, step=APPROVAL_STEP)
            s.say("Not approved, so nothing was sent." if decision != "timeout" else "No approval came in time, so nothing was sent.")
            return True
        s.submit_pressed = True
        self._save()  # recorded before the press: a crash right after it must never lead to a second send
        s.say("Approved. Submitting.")
        outcome = self.browser.run(action)
        s.clicked.append(action.label)
        if not outcome.ok:
            s.say(f"The submit press did not register: {outcome.detail}.")
        if outcome.page is not None:
            s.visit(outcome.page.url)
        return self._verify(obs.url)

    def _approval_summary(self) -> List[str]:
        """What is about to be sent. Every guess comes first and says so (the cap on lines can never cut one off), and is not listed twice."""
        s = self.session
        guesses = list(self.resolver.guessed.values())
        mine = tuple(shown(question, 60) for question, _ in guesses)
        rest = [f"{label}: {value}" for label, value in s.filled.items() if not label.startswith(mine)]
        return ([f"Job: {s.job.context() or 'unknown'}", f"Resume: {s.resume or 'none'}"]
                + [f"GUESSED, please check - {shown(question, 80)}: {answer}" for question, answer in guesses] + rest[:25])

    def _guess_note(self) -> str:
        guesses = list(self.resolver.guessed.values())
        if not guesses:
            return ""
        listed = "; ".join(f"{shown(question, 60)} -> {answer[:60]}" for question, answer in guesses[:5])
        return f" I guessed {len(guesses)} answer{'s' if len(guesses) != 1 else ''}, so please check: {listed}."

    def _verify(self, started_on: str, already: bool = False) -> bool:
        """Look for proof. True when the application is finished (one way or another); False to fix the form and try again."""
        s = self.session
        self._state(AgentState.VERIFYING, "checking the result")
        s.say("Checking whether the application was really received...")
        judge = self.brain.judge_submission if self.brain is not None else None
        page = self.browser.page
        verdict = verify.wait_for_verdict(lambda: observe(self.browser.page), started_on, judge, self.verify_ms, pause=page.wait_for_timeout)
        if verdict.status in (AppStatus.SUBMITTED, AppStatus.DUPLICATE) and not s.submit_pressed:
            verdict.status = AppStatus.ALREADY_SUBMITTED  # the site says it was received, but not by this run
        s.errors = verdict.errors or ([verdict.evidence] if verdict.status not in (AppStatus.SUBMITTED, AppStatus.ALREADY_SUBMITTED) else [])
        if verdict.status is AppStatus.INCOMPLETE and self._resubmits < MAX_RESUBMITS - 1:
            self._resubmits += 1
            s.submit_pressed = False  # nothing was sent: the form refused it. It may be sent again, with a fresh approval
            s.say(f"The form was not accepted ({verdict.evidence}). I will fix what I can and ask you again before sending.")
            return False
        s.finish(verdict.status, confirmation=verdict.evidence if verdict.status is AppStatus.SUBMITTED else s.confirmation, reference=verdict.reference)
        s.say(f"{verdict.status.label}." + (f" Evidence: {verdict.evidence}" if verdict.evidence else "")
              + (f" Reference: {verdict.reference}." if verdict.reference else ""))
        return True
