"""Sort the jobs that searches found and no run has opened: `jobapply triage <portal>`.

Searches list up to three times a run's limit, and a run stops at its limit, so jobs pile up unopened (622 on LinkedIn once). A real run then spends its
few attempts on whatever comes first. A triage reads each waiting job the way a run does, with the same judge, and sends nothing:

* not a match, or the listing is closed -> `skipped_match` (a run never opens it again), with the reason
* already applied -> `skipped_duplicate`
* worth applying to -> stays `new` (nothing was tried) but is stamped, and every later run queues those first
* cannot be read (a page that would not load) -> left alone, as it was: that says nothing about the job

It is paced like a run and stops at once on a login wall, a captcha, a closed browser, or three unreadable jobs in a row (the selectors probably broke).
"""
from __future__ import annotations

import dataclasses
import logging
import random
import time
from collections import Counter
from typing import Callable, List, Optional

from .adapters.base import Adapter
from .config import Criteria, Profile
from .db import Database
from .engine import CLOSED_REASON, pace_delay
from .matching import Decision, judge
from .models import ChallengeDetected, Job, JobCard, NotLoggedIn, Result, Status
from .system import announce

log = logging.getLogger("jobapply")

UNREADABLE_IN_A_ROW = 3  # this many jobs that will not load, one after another, is the site or the selectors, not three bad jobs
READY, NOT_A_MATCH, CLOSED, APPLIED, UNREADABLE = "ready", "not a match", "closed", "already applied", "could not be read"


@dataclasses.dataclass
class TriageSummary:
    portal: str
    counts: Counter = dataclasses.field(default_factory=Counter)
    stop_reason: str = ""
    unread: int = 0  # jobs still waiting for a triage when it ended
    ready: int = 0  # jobs known worth applying to, from this and earlier triages, that no run has tried
    notes: List[str] = dataclasses.field(default_factory=list)

    def lines(self) -> List[str]:
        read = sum(self.counts.values())
        parts = ", ".join(f"{self.counts[kind]} {kind}" for kind in (READY, NOT_A_MATCH, CLOSED, APPLIED, UNREADABLE) if self.counts[kind])
        out = [f"{self.portal} triage: read {read} job(s)" + (f": {parts}" if parts else "") + f". Stopped: {self.stop_reason}."]
        out.append(f"{self.ready} job(s) are known worth applying to, and {self.unread} still wait to be read" + (
            ". Run it again to carry on." if self.unread else "."))
        return out + self.notes


class Triage:
    def __init__(
        self, adapter: Adapter, db: Database, profile: Profile, criteria: Criteria, *, limit: int = 50, minutes: float = 30,
        fit_judge: Optional[Callable[[Job, Decision], Decision]] = None, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep, rng: Optional[random.Random] = None, alert: Callable[[str], None] = announce,
    ):
        self.adapter, self.db, self.profile, self.criteria = adapter, db, profile, criteria
        self.limit, self.minutes, self.fit_judge = limit, minutes, fit_judge
        self.clock, self.sleep, self.rng, self.alert = clock, sleep, rng or random.Random(), alert
        self.summary = TriageSummary(adapter.name)
        self.deadline = 0.0
        self._unreadable_streak = 0

    def run(self) -> TriageSummary:
        self.deadline = self.clock() + self.minutes * 60
        cards = self.db.candidates(self.adapter.name, [Status.NEW], untriaged=True)
        if not cards:
            self.summary.stop_reason = "nothing is waiting: every job found so far has been read"
        try:
            self._check_login()
            for card in cards:
                if sum(self.summary.counts.values()) >= self.limit:
                    self.summary.stop_reason = f"the limit of {self.limit} jobs was reached"
                elif self.clock() >= self.deadline:
                    self.summary.stop_reason = "the time budget was used up"
                if self.summary.stop_reason:
                    break
                self._sort(card)
                if self.summary.stop_reason:
                    break
                self.sleep(max(0.0, min(pace_delay(self.adapter, self.criteria, self.rng), self.deadline - self.clock())))
        except NotLoggedIn as exc:
            self.summary.stop_reason = f"{exc}. Log in again in the automation browser window, then re-run"
        except ChallengeDetected:
            self.summary.stop_reason = "the site asked for a captcha or verification: solve it in the browser window, then re-run"
        self.summary.stop_reason = self.summary.stop_reason or "every waiting job was read"
        self.summary.unread = len(self.db.candidates(self.adapter.name, [Status.NEW], untriaged=True))
        self.summary.ready = self.db.ready(self.adapter.name)
        return self.summary

    def _check_login(self) -> None:
        try:
            logged_in = self.adapter.is_logged_in()
        except ChallengeDetected:
            logged_in = False
        if not logged_in:
            raise NotLoggedIn(f"not logged in to {self.adapter.name}")

    def _sort(self, card: JobCard) -> None:
        try:
            job = self.adapter.read_job(card)
        except (NotLoggedIn, ChallengeDetected):
            raise
        except Exception as exc:
            return self._unreadable(card, exc)
        self._unreadable_streak = 0
        if job.already_applied:
            return self._settle(card, APPLIED, Result(Status.SKIPPED_DUPLICATE, "portal says already applied"))
        if job.closed:
            return self._settle(card, CLOSED, Result(Status.SKIPPED_MATCH, CLOSED_REASON))
        decision = judge(job, self.profile, self.criteria, self.fit_judge)
        if not decision.ok:
            return self._settle(card, NOT_A_MATCH, Result(Status.SKIPPED_MATCH, decision.reason, decision.score))
        self.db.mark_checked(card, decision.score, f"ready: {decision.reason}")
        self._count(card, READY, decision.reason)

    def _settle(self, card: JobCard, kind: str, result: Result) -> None:
        self.db.set_status(card, result)
        self._count(card, kind, result.reason)

    def _count(self, card: JobCard, kind: str, reason: str) -> None:
        self.summary.counts[kind] += 1
        log.info("triage | %s | %s @ %s | %s %s", kind, card.title, card.company, card.url, reason)

    def _unreadable(self, card: JobCard, exc: Exception) -> None:
        """A page that would not load or read. The job keeps its status: nothing here says it is a bad job, only that it could not be seen."""
        log.warning("triage: could not read %s: %s", card.url, exc)
        if self.adapter.tab_lost():  # you closed the tab: a new one in the same browser, or stop if the browser is gone
            if not self.adapter.reopen_tab():
                self.summary.stop_reason = "the automation browser was closed. Open it again (the panel's \"Open the browser\" step), then re-run"
                return
            self.summary.notes.append("the browser tab was closed: opened a new one and carried on")
            return  # not this job's fault, and not counted against it
        self.summary.counts[UNREADABLE] += 1
        self._unreadable_streak += 1
        if self._unreadable_streak >= UNREADABLE_IN_A_ROW:
            self.summary.stop_reason = f"{UNREADABLE_IN_A_ROW} jobs in a row could not be read: the site or its selectors probably changed (see data/failures/, and run `jobapply probe`)"
            try:
                self.adapter.capture_failure(card)
            except Exception:
                pass
