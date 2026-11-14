"""A job the portal cannot apply to by itself (it applies on the company's own site) is handed to the agent, in the same tab.

The engine asks for this only when an adapter says `elsewhere` and the person turned it on. What comes back is the engine's own
kind of result, so reports, the queue and the run's limits work as they do for any job.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..ai_guess import AiGuesser
from ..ai_ledger import Ledger
from ..answers import AnswerResolver
from ..guess_book import GuessBook
from ..models import Job, Result, Status
from .agent import STEP_NAMES, Agent
from .brain import Brain
from .hitl import APPROVAL_STEP
from .models import AppStatus, JobInfo, PageKind
from .session import Session

log = logging.getLogger("jobapply")

MINUTES_PER_JOB = 15  # one job never takes more of the run than this
SENT = (AppStatus.SUBMITTED, AppStatus.ALREADY_SUBMITTED, AppStatus.DUPLICATE)  # the site has it
KEEP_TABS_OPEN = (AppStatus.REQUIRES_USER, AppStatus.INCOMPLETE)  # the person may want to finish these by hand
WALLS = (STEP_NAMES[PageKind.LOGIN], STEP_NAMES[PageKind.SIGNUP])  # the step the agent is on when a company's site wants an account first
BY_STATUS = {
    AppStatus.SUBMITTED: Status.APPLIED,
    AppStatus.READY: Status.DRY_RUN_OK,  # a rehearsal: everything filled in, nothing sent
    AppStatus.ALREADY_SUBMITTED: Status.SKIPPED_DUPLICATE,
    AppStatus.DUPLICATE: Status.SKIPPED_DUPLICATE,
    AppStatus.REQUIRES_USER: Status.NEEDS_ANSWER,  # a login, a question, a check: only the person can go on
}
Builder = Callable[[Any, Optional[Session], float], Agent]


def agent_builder(profile, paths, db, book, ai, *, submit: bool, ask_approval: bool, answer_wait_s: float = 300, guess: bool = False) -> Builder:
    """How to make an agent for a page. A fresh answerer each time: an agent wraps the one it is given.

    `guess` lets the agent make a best guess at a question nothing else can answer, and say so. It needs the AI helper, and it is never
    allowed to send without your approval: a guess is acceptable because you see it, listed first, before anything goes out."""
    guessing = guess and ai is not None and not (submit and not ask_approval)

    def build(page, session: Optional[Session], minutes: float) -> Agent:
        guesser = AiGuesser.from_answerer(ai, paths.ai_guess_log) if guessing else None
        resolver = AnswerResolver(profile, book.wordings(), db, "agent", ai=ai, persist=lambda question, answer: book.remember(question, answer),
                                  guesser=guesser, guesses=GuessBook(paths.guesses) if guessing else None)
        brain = Brain(ai.client, Ledger(paths.agent_ai_log)) if ai is not None else None
        return Agent(page, profile, paths, db, resolver, brain=brain, submit=submit, ask_approval=ask_approval, session=session,
                     minutes=minutes, answer_wait_s=answer_wait_s, answers_loader=book.wordings, guess=guessing)
    return build


def outcome(session: Session, unrelated: bool) -> Result:
    """What the agent's application means to the engine. When in doubt about a send, the job is never tried again."""
    if unrelated:
        return Result(Status.SKIPPED_EXTERNAL, "AI agent: that page is not about a job, so nothing was done")
    status = session.status
    said = f"AI agent: {status.label}"
    if session.submit_pressed and status not in SENT:  # Send was pressed and nothing proves it arrived: trying again could send it twice
        return Result(Status.SKIPPED_DUPLICATE, f"{said}. Send was pressed but could not be confirmed: check on the site. It will not be sent again.")
    if session.step in WALLS and status not in SENT:  # nothing automatic can get past this (it never types a password): not a failure, and not worth trying every run
        who = f"{session.job.company}'s site" if session.job.company else "the company's site"
        return Result(Status.SKIPPED_EXTERNAL, f"{said}: {who} wants you to sign in or register first, which only you can do. Nothing was sent. "
                                              "Do that in the browser, then run the AI agent on that page")
    if status is AppStatus.REQUIRES_USER and session.step == APPROVAL_STEP:
        return Result(Status.SKIPPED_MATCH, f"{said}: you did not approve sending it")
    detail = session.confirmation or "; ".join(session.missing) or "; ".join(session.errors[:2])
    return Result(BY_STATUS.get(status, Status.FAILED), f"{said}. {detail}".strip()[:300])


class Handoff:
    def __init__(self, adapter, paths, build: Builder, minutes_per_job: float = MINUTES_PER_JOB):
        self.adapter, self.paths, self.build, self.minutes_per_job = adapter, paths, build, minutes_per_job

    def __call__(self, job: Job, minutes_left: float) -> Result:
        page = self.adapter.page
        session = Session.create(self.paths.agent_dir, JobInfo(title=job.title, company=job.company, location=job.location,
                                                               experience=job.experience, description=job.description[:2000], url=job.url))
        session.say(f"{job.portal} cannot apply to this job itself: the AI agent takes over.")
        before = set(page.context.pages)
        agent = self.build(page, session, max(0.5, min(self.minutes_per_job, minutes_left)))
        finished = agent.run()
        self._tidy(page, before, finished.status)
        return outcome(finished, agent.unrelated)

    @staticmethod
    def _tidy(page, before: set, status: AppStatus) -> None:
        """Close the company-site tabs it opened, so a run of many jobs does not pile them up (unless the person may want one)."""
        if status in KEEP_TABS_OPEN:
            return
        for tab in list(page.context.pages):
            if tab not in before and tab is not page:
                try:
                    tab.close()
                except Exception:
                    log.debug("could not close a tab the agent opened", exc_info=True)
