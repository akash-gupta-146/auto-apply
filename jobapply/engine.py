"""The run loop: discover -> process queue with a time budget -> optional LLM second pass.

Policies (all in Criteria, all unit-tested with a fake clock):
  * time budget per run (--minutes), run cap, human-like pacing
  * a challenge gets `challenge_wait_s` for a human, then the job is skipped and the run continues
  * a question only you can answer gets `answer_wait_s` for you to answer it in the panel, then the job is skipped too
  * N challenges in a row => back off (the account/IP is flagged), then continue
  * N failures in a row => stop (selectors probably broke), don't hammer the site
"""
from __future__ import annotations

import logging
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from .adapters.base import Adapter
from .answers import AnswerResolver, Attention, normalize
from .config import Criteria, Profile
from .db import Database
from .matching import MATCH, SUGGESTED, Decision, accept_suggested, evaluate, fit_note, why_it_fits
from .models import (
    ChallengeDetected,
    Job,
    Declined,
    JobCard,
    NeedsAnswer,
    NothingSent,
    NotLoggedIn,
    SetupIncomplete,
    Result,
    Status,
)
from .system import announce

log = logging.getLogger("jobapply")

DISCOVERY_FACTOR = 3  # discover up to this many x the run cap, then stop searching
SUGGESTED_BATCH = 10  # a suggested run reads this many new picks, applies to them, then reads more
MAX_ANSWER_ROUNDS = 5  # a form asks its questions page by page: answering one page can reveal the next. Bounded, so a form that
#                        never ends cannot hold the run
# Results that mean the adapter found nothing to press (a company-site job, a job already applied to): no application
# was tried, so none of the run's attempts was used.
NOTHING_TRIED = (Status.SKIPPED_EXTERNAL, Status.SKIPPED_DUPLICATE)


@dataclass
class RunSummary:
    portal: str
    dry_run: bool
    started: datetime = field(default_factory=datetime.now)
    counts: Counter = field(default_factory=Counter)
    items: List[Tuple[JobCard, Result]] = field(default_factory=list)
    stop_reason: str = ""
    notes: List[str] = field(default_factory=list)  # problems worth reading; shown in the report
    queue: Dict[str, int] = field(default_factory=dict)  # this portal's whole queue, all runs
    ai_answers: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # question -> (answer, quote), --ai runs
    ai_declined: List[str] = field(default_factory=list)  # questions the AI could not ground in your documents
    ai_fit: Dict[str, int] = field(default_factory=dict)  # jobs the AI judged from their description: approved/declined/not judged
    dismissed: List[str] = field(default_factory=list)  # pop-ups closed by pressing their no: what each said and what was pressed
    ai_popups: Dict[str, int] = field(default_factory=dict)  # pop-ups the AI was asked about: closed / left alone / not asked

    def record(self, card: JobCard, result: Result) -> None:
        self.counts[result.status.value] += 1
        self.items.append((card, result))

    @property
    def done(self) -> int:
        return self.counts[Status.APPLIED.value] + self.counts[Status.DRY_RUN_OK.value]


class Engine:
    def __init__(
        self,
        adapter: Adapter,
        db: Database,
        profile: Profile,
        criteria: Criteria,
        resolver: AnswerResolver,
        *,
        minutes: float = 120,
        dry_run: bool = False,
        reevaluate: bool = False,
        suggested: bool = False,
        fit_judge: Optional[Callable[[Job, Decision], Decision]] = None,
        max_attempts: Optional[int] = None,
        answers_loader: Optional[Callable[[], Dict[str, str]]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Optional[random.Random] = None,
        alert: Callable[[str], None] = announce,
    ):
        self.adapter, self.db, self.profile = adapter, db, profile
        self.criteria, self.resolver = criteria, resolver
        self.minutes, self.dry_run = minutes, dry_run
        self.reevaluate, self.fit_judge = reevaluate, fit_judge
        self.suggested = suggested  # apply to every job the site itself suggests, with no roles/skills/salary matching
        self._shown: Set[str] = set()  # the addresses of every job the site showed this run: all a suggested run may open
        self._attempted: Set[str] = set()  # the jobs this run has already been through, so a later batch never repeats one
        self.max_attempts, self._attempts = max_attempts, 0  # hard cap on live Apply clicks, pass or fail
        self.answers_loader = answers_loader  # re-reads your answer bank while a job waits for you to answer in the panel
        self._given_up: Set[str] = set()  # questions nobody answered in time this run: later jobs asking them do not wait again
        self.clock, self.sleep, self.alert = clock, sleep, alert
        self.rng = rng or random.Random()
        self.summary = RunSummary(adapter.name, dry_run)
        self.deadline = 0.0
        self._fail_streak = 0
        self._challenge_streak = 0
        self._discovered = 0  # cards the portal showed us (new or already queued)

    # -- public ----------------------------------------------------------------
    def run(self) -> RunSummary:
        self.deadline = self.clock() + self.minutes * 60
        try:
            log.info("checking that you are logged in to %s", self.adapter.name)
            self._ensure_login()
            if self.suggested:
                self._work_through_suggestions()
            else:
                self._discover(self.criteria.max_applications_per_run * DISCOVERY_FACTOR)
                if self._nothing_to_do():
                    return self.summary
                self._process()
        except NotLoggedIn as exc:
            self.summary.stop_reason = f"{exc}. Log in again in the automation browser window, then re-run."
            self.alert(self.summary.stop_reason)
        except SetupIncomplete as exc:  # the remedy is different from a login, so the advice is too
            self.summary.stop_reason = str(exc)
            self.alert(self.summary.stop_reason)
        self.summary.stop_reason = self.summary.stop_reason or (
            "queue exhausted" if self.summary.items else self._explain_empty_queue()
        )
        self.summary.queue = self.db.counts(self.adapter.name).get(self.adapter.name, {})
        return self.summary

    # -- phases ------------------------------------------------------------------
    def _ensure_login(self) -> None:
        try:
            logged_in = self.adapter.is_logged_in()
        except ChallengeDetected:
            logged_in = False
        if not logged_in:
            raise NotLoggedIn(f"not logged in to {self.adapter.name}")

    def _first_pass_statuses(self) -> List[Status]:
        """What a run picks up. Applied and already-applied stay final; everything else can be retried.

        FAILED and SKIPPED_CHALLENGE are retried so a repaired selector or a solved captcha is not
        punished forever. SKIPPED_MATCH is re-checked in dry runs (you edit criteria after one) and
        whenever --reevaluate is given; a live run does not repeat page loads for known rejects. A suggested run takes
        them too: they were turned away by rules that run no longer uses.
        SKIPPED_EXTERNAL (no Easy Apply button) is re-opened only on --reevaluate: it costs a page load each,
        and the button may simply not have been drawn the first time.
        """
        statuses = [Status.NEW, Status.NEEDS_ANSWER, Status.DRY_RUN_OK, Status.FAILED, Status.SKIPPED_CHALLENGE]
        if self.dry_run or self.reevaluate or self.suggested:
            statuses.append(Status.SKIPPED_MATCH)
        if self.reevaluate:
            statuses.append(Status.SKIPPED_EXTERNAL)
        return statuses

    def _queue(self) -> List[JobCard]:
        """The jobs this run will open next. A suggested run takes only what the site showed it just now, never what an earlier
        search left in the database (those were not suggested to you), and not what it has already been through. Jobs waiting
        for your answer go last: each distinct question can hold a run for minutes, and nothing should wait behind them."""
        cards = self.db.candidates(self.adapter.name, self._first_pass_statuses())
        if not self.suggested:
            return cards
        waiting = {card.url for card in self.db.candidates(self.adapter.name, [Status.NEEDS_ANSWER])}
        fresh = [card for card in cards if card.url in self._shown and card.url not in self._attempted]
        return sorted(fresh, key=lambda card: card.url in waiting)  # sorted() is stable: the order the site gave is kept

    def _work_through_suggestions(self) -> None:
        """Read a few of the site's picks, apply to them, then read a few more. Reading the whole list first (a minute of
        scrolling with nothing applied) looked like a hang, and it was why a run was stopped before it ever began."""
        while not self._budget_exhausted():
            self._discover(SUGGESTED_BATCH)
            if self._nothing_to_do() or not self._queue():  # (nothing at all is a broken search; nothing new is just the end)
                return
            self._process()

    def _explain_empty_queue(self) -> str:
        counts = self.db.counts(self.adapter.name).get(self.adapter.name, {})
        summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items())) or "nothing"
        return (
            f"nothing to process: the portal showed {self._discovered} jobs but all were already handled in "
            f"earlier runs ({summary}). Edited your criteria? Tick \"Also re-check jobs skipped earlier\" in the panel (or use --reevaluate)"
        )

    def _note(self, message: str) -> None:
        log.warning(message)
        self.summary.notes.append(message)

    def _save_evidence(self, query: str, why: str) -> None:
        """Screenshot + HTML of the page we are on, so a broken search can be repaired."""
        try:
            self.adapter.capture_failure(JobCard(self.adapter.name, query, why))
        except Exception:
            pass

    def _nothing_to_do(self) -> bool:
        """Zero jobs is a broken search, not a finished queue: say so loudly."""
        if self._discovered or self._queue():
            return False
        self.summary.stop_reason = (
            f"found 0 jobs on {self.adapter.name}: the search pages showed nothing (selectors, filters or "
            f"target roles need repair). See data/failures/ and data/run.log, then run `jobapply probe {self.adapter.name}`"
        )
        self.alert(self.summary.stop_reason)
        return True

    def _still_to_do(self) -> Set[str]:
        """Jobs already in the database that a suggested run could still take: an earlier run saw them and stopped before it
        applied. They count towards a batch as much as brand-new ones. If only new ones counted, a list read once before would
        be read to its very end (a minute of scrolling) before anything was applied, which is what made a run look stuck."""
        if not self.suggested:
            return set()
        return {card.url for card in self.db.candidates(self.adapter.name, self._first_pass_statuses())} - self._attempted

    def _discover(self, limit: int) -> None:
        found = 0
        known = self._still_to_do()
        for query in self.adapter.suggested_queries() if self.suggested else self.adapter.queries():
            log.info("searching: %s", query)
            yielded = 0
            for attempt in (1, 2):
                try:
                    for card in self.adapter.discover(query):
                        yielded += 1
                        self._shown.add(card.url)
                        found += self.db.upsert_job(card) or card.url in known
                        if found >= limit or self._out_of_time():
                            self._discovered += yielded
                            return
                    break
                except ChallengeDetected:
                    if attempt == 2 or not self._clear_challenge():
                        self._note(f"skipped a query after a challenge: {query}")
                        break
                except (NotLoggedIn, SetupIncomplete):
                    raise  # a login wall or an unfinished setup is not "0 jobs": stop the run and say so
                except Exception as exc:  # one bad query must not sink the run
                    self._note(f"query failed ({type(exc).__name__}: {exc}): {query}")
                    self._save_evidence(query, "query failed")
                    break
            if yielded == 0:
                self._note(f"0 jobs from: {query}")
                self._save_evidence(query, "0 jobs found")
            self._discovered += yielded
            if self._out_of_time():
                return

    def _process(self) -> None:
        cards = self._queue()
        log.info("reading %d job(s)%s", len(cards), "; this can take a while" if cards else "")
        for card in cards:
            if self._budget_exhausted():
                return
            result = self._attempt(card)
            self._attempted.add(card.url)
            self.db.set_status(card, result)
            self.summary.record(card, result)
            log.info("%s | %s @ %s | %s %s", result.status.value, card.title, card.company, card.url, result.reason)
            if self._should_stop(result):
                return
            self._pace()

    # -- one job -----------------------------------------------------------------
    def _attempt(self, card: JobCard) -> Result:
        challenges = rounds = 0
        while True:
            self.resolver.reset()
            try:
                return self._try_once(card)
            except ChallengeDetected:
                challenges += 1
                if challenges == 2:
                    return Result(Status.SKIPPED_CHALLENGE, "challenge reappeared after the wait")
                if not self._clear_challenge():
                    return Result(Status.SKIPPED_CHALLENGE, f"no human within {self.criteria.challenge_wait_s:.0f}s")
            except NeedsAnswer as exc:
                rounds += 1
                if rounds < MAX_ANSWER_ROUNDS and self._await_answers(exc.questions):
                    continue  # you answered in the panel: the job gets another go, with your answers
                return Result(Status.NEEDS_ANSWER, "; ".join(exc.questions)[:300])
            except NotLoggedIn:
                raise  # session expired mid-run: stop, don't mark every remaining job failed
            except Exception as exc:
                return self._failure(card, exc)

    def _attention(self) -> Optional[Attention]:
        """What the adapter may use to wait for you at the form itself. With no panel to answer in, there is nobody to wait for."""
        if self.answers_loader is None:
            return None
        return Attention(self._patience, self.alert, self.answers_loader, self._given_up)

    def _patience(self) -> float:
        return max(0.0, min(self.criteria.answer_wait_s, self.deadline - self.clock()))

    def _try_once(self, card: JobCard) -> Result:
        self.resolver.attention = self._attention()
        job: Job = self.adapter.read_job(card)
        if job.already_applied:
            return Result(Status.SKIPPED_DUPLICATE, "portal says already applied")
        decision = self._judge(job)
        if not decision.ok:
            return Result(Status.SKIPPED_MATCH, decision.reason, decision.score)
        if not self.dry_run:
            self._attempts += 1  # counted BEFORE the click: a failed or ambiguous attempt still used one
        try:
            result = self.adapter.apply(job, self.resolver, self.dry_run)
        except NeedsAnswer:
            if self.adapter.parks_before_sending:
                self._give_back_attempt()  # it stopped to ask before anything could be sent
            raise
        except Declined as exc:
            if self.adapter.parks_before_sending:
                self._give_back_attempt()  # same: it stopped before anything could be sent
            return Result(Status.SKIPPED_MATCH, f"required tick box answered No: {'; '.join(exc.questions)}"[:300])
        except NothingSent:
            self._give_back_attempt()  # still a failure to report, but no application went out
            raise
        if result.status in NOTHING_TRIED:
            self._give_back_attempt()  # nothing was pressed: a job that cannot be applied to must not use up the run's attempts
        result.score = decision.score
        if result.status in (Status.APPLIED, Status.DRY_RUN_OK):  # say why it was let through, so the report can be audited
            why, rating = why_it_fits(job, self.profile, self.criteria, decision), fit_note(job, self.profile, self.criteria, decision)
            result.reason = f"{why}{'; ' + rating if rating else ''}. {result.reason}".strip()
        elif decision.reason not in (MATCH, SUGGESTED):  # a looser fit than the roles asked for
            result.reason = f"[{decision.reason}] {result.reason}".strip()
        return result

    def _judge(self, job: Job) -> Decision:
        if self.suggested:
            return accept_suggested(job, self.profile, self.criteria)
        decision = evaluate(job, self.profile, self.criteria)
        if not decision.ok and decision.rescuable and self.fit_judge is not None:
            decision = self.fit_judge(job, decision)  # the title said no: let the description have its say
        return decision

    def _give_back_attempt(self) -> None:
        if not self.dry_run:
            self._attempts -= 1

    def _failure(self, card: JobCard, exc: Exception) -> Result:
        log.exception("failed: %s", card.url)
        try:
            self.adapter.capture_failure(card)
        except Exception:
            pass
        return Result(Status.FAILED, f"{type(exc).__name__}: {exc}"[:300])

    # -- policies ----------------------------------------------------------------
    def _out_of_time(self) -> bool:
        return self.clock() >= self.deadline

    def _budget_exhausted(self) -> bool:
        if self._out_of_time():
            self.summary.stop_reason = "time budget used up"
            if not self.summary.items:  # a short budget can be spent entirely on searching: say so, or it looks like a bug
                self.summary.stop_reason += " before any job was read (the search itself used it all: allow more minutes)"
        elif self.summary.done >= self.criteria.max_applications_per_run:
            self.summary.stop_reason = "run cap reached"
        elif self.max_attempts is not None and self._attempts >= self.max_attempts:
            self.summary.stop_reason = f"attempt limit reached ({self.max_attempts})"
        return bool(self.summary.stop_reason)

    def _should_stop(self, result: Result) -> bool:
        self._fail_streak = self._fail_streak + 1 if result.status is Status.FAILED else 0
        if self._fail_streak >= self.criteria.max_consecutive_failures:
            self.summary.stop_reason = (
                f"{self._fail_streak} failures in a row: selectors probably broke, see failures/ and run `jobapply probe`"
            )
            return True
        self._challenge_streak = self._challenge_streak + 1 if result.status is Status.SKIPPED_CHALLENGE else 0
        if self._challenge_streak >= self.criteria.breaker_threshold:
            return self._back_off()
        return False

    def _back_off(self) -> bool:
        backoff = self.criteria.breaker_backoff_s
        if backoff >= self.deadline - self.clock():
            self.summary.stop_reason = "repeated challenges: back-off would outlast the time budget"
            return True
        self.alert(f"{self._challenge_streak} challenges in a row; backing off {backoff / 60:.0f} min")
        self.sleep(backoff)
        self._challenge_streak = 0
        return False

    def _await_answers(self, questions: List[str]) -> bool:
        """Give a person `answer_wait_s` to answer in the panel. True once every question has an answer; False means skip the job."""
        pending = {normalize(question) for question in questions}
        wait = self.criteria.answer_wait_s
        if self.answers_loader is None or wait <= 0 or pending <= self._given_up or self.resolver.waited:
            return False  # nobody can answer, this exact question already went unanswered, or the form itself was already waited at
        shown = "; ".join(questions[:3])
        self.alert(f"Your answer is needed on {self.adapter.name}: {shown}. Answer it in the panel (Questions); "
                   f"waiting up to {wait:.0f}s, then this job is skipped.")

        def answered() -> bool:
            self.resolver.reload(self.answers_loader())
            return pending <= set(self.resolver.bank)

        if self._wait_until(answered, min(wait, max(0.0, self.deadline - self.clock()))):
            return True
        self._given_up |= pending
        return False

    def _clear_challenge(self) -> bool:
        wait = self.criteria.challenge_wait_s
        self.alert(f"Human needed on {self.adapter.name}: solve it in the browser. Waiting up to {wait:.0f}s, then skipping.")
        return self._wait_until(lambda: not self.adapter.is_challenge(), wait)

    def _wait_until(self, predicate: Callable[[], bool], timeout: float) -> bool:
        end = self.clock() + timeout
        while True:
            try:
                if predicate():
                    return True
            except Exception:
                pass  # page mid-navigation: try again next poll
            remaining = end - self.clock()
            if remaining <= 0:
                return False
            self.sleep(min(self.criteria.poll_s, remaining))

    def _pace(self) -> None:
        low, high = self.criteria.pacing_min_s, self.criteria.pacing_max_s
        if self.adapter.pacing_floor_s:  # the portal asked for gentler pacing than the settings give
            low, high = max(low, self.adapter.pacing_floor_s[0]), max(high, self.adapter.pacing_floor_s[1])
        delay = self.rng.uniform(low, high)
        self.sleep(max(0.0, min(delay, self.deadline - self.clock())))
