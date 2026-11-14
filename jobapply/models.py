"""Plain data types shared by the engine and the portal adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Optional


class Status(str, Enum):
    NEW = "new"
    APPLIED = "applied"
    DRY_RUN_OK = "dry_run_ok"
    SKIPPED_MATCH = "skipped_match"
    SKIPPED_EXTERNAL = "skipped_external"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_CHALLENGE = "skipped_challenge"
    NEEDS_ANSWER = "needs_answer"
    FAILED = "failed"


@dataclass
class JobCard:
    """What a search-results page tells us about a job."""

    portal: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    experience: str = ""  # what the posting asks for, as the portal words it: "5-8 Yrs"


@dataclass
class Job(JobCard):
    """A card plus what the job page tells us."""

    description: str = ""
    salary: str = ""
    already_applied: bool = False
    closed: bool = False  # the page itself says the listing no longer takes applications (set only where its words are there to read)

    @classmethod
    def from_card(cls, card: JobCard, **extra) -> "Job":
        return cls(**{**asdict(card), **extra})


@dataclass
class Result:
    status: Status
    reason: str = ""
    score: Optional[float] = None
    elsewhere: bool = False  # SKIPPED_EXTERNAL only: the portal has no apply of its own here, but the job may be open on the company's site
    blameless: bool = False  # FAILED only, for a reason that says nothing about the site (the tab was closed): not a sign its selectors broke


class ChallengeDetected(Exception):
    """A captcha / bot-check / verification wall needs a human."""


class NotLoggedIn(Exception):
    """The browser profile is not logged in to the portal."""


class SetupIncomplete(Exception):
    """The portal will not show its jobs until the person finishes something only they can do (a profile wizard)."""


class BrowserGone(Exception):
    """The automation browser itself was closed, so there is no tab to open and nothing more can be done until the person opens it again."""


class FormBlocked(Exception):
    """A form cannot go on, for reasons that are about particular questions."""

    def __init__(self, questions: Iterable[str]):
        self.questions = list(questions)
        super().__init__("; ".join(self.questions))


class NeedsAnswer(FormBlocked):
    """A form asked something the profile cannot honestly answer."""


class Declined(FormBlocked):
    """The person's own answer to a required tick box is not Yes, and ticking it is the only way on: the job cannot be
    applied to as things stand (and is looked at again if the answer changes)."""


class NothingSent(RuntimeError):
    """A failure before anything could be sent (a window that never opened, a step the portal would not accept).
    It is reported as failed, but it did not use one of the run's applications."""
