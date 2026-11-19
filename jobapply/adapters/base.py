"""Portal adapter contract plus the helpers every adapter shares.

Lifecycle per job (the engine guarantees this order, on one page):
    read_job(card) -> apply(job, resolver, dry_run)
so apply() may rely on the page being the one read_job() just loaded.
"""
from __future__ import annotations

import abc
import random
import re
import time
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Pattern, Sequence, Tuple

from ..config import Criteria, Profile
from ..models import ChallengeDetected, Job, JobCard, NotLoggedIn, Result
from . import evidence
from .prompts import Judge, dismiss_prompts

MAX_WIDGETS_LOOKED_AT = 6  # a page can hold several copies of a widget; the first few settle it
CHALLENGE_URL_HINTS = ("captcha", "cdn-cgi/challenge", "/checkpoint/", "authwall")
RENDERED_MIN_CHARS = 300  # visible text needed before a page counts as rendered
MIN_AUTH_DWELL_S = 5.0  # Naukri redirects logged-out users to /nlogin at ~3s (measured live)
CHALLENGE_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare.com']",
    "div.g-recaptcha",
    "div.cf-turnstile",
)
CHALLENGE_PHRASES = (
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "press and hold",
    "checking your browser",
    "confirm you are not a robot",
    "additional verification required",  # Indeed's Cloudflare page
)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _shows_challenge(found) -> bool:
    """Is one of these captcha widgets really in front of the person? Not the small \"protected by reCAPTCHA\" badge that invisible
    reCAPTCHA parks on every form it guards: that one is on the page whether or not anything is being checked."""
    return any(found.nth(i).is_visible() and not found.nth(i).evaluate("e => !!e.closest('.grecaptcha-badge')")
               for i in range(min(found.count(), MAX_WIDGETS_LOOKED_AT)))


def looks_like_challenge(page) -> bool:
    """Visible captcha / bot-wall on this page? Conservative: text is checked at the top only."""
    url = page.url.lower()
    if any(hint in url for hint in CHALLENGE_URL_HINTS):
        return True
    for selector in CHALLENGE_SELECTORS:
        try:
            if _shows_challenge(page.locator(selector)):
                return True
        except Exception:
            continue
    try:
        title = page.title().lower()
        head = page.inner_text("body", timeout=2000).lower()[:2000]
    except Exception:
        return False
    return "just a moment" in title or any(phrase in head for phrase in CHALLENGE_PHRASES)


def first_visible(scope, selectors: Iterable[str]):
    """First visible locator among selectors (scope = page or locator), else None.

    Every match of a selector is considered, not just the first in the page: pages keep hidden copies of things
    (closed dialogs, duplicate buttons), and a hidden first match must not hide a visible second one.
    """
    for selector in selectors:
        try:
            for locator in scope.locator(selector).all():
                if locator.is_visible():
                    return locator
        except Exception:
            continue
    return None


def find_salary(text: str) -> str:
    match = re.search(
        r"(?:₹|\$|€|£|INR|USD)\s?[\d,.]+\s?(?:[kKmM]|lpa|lacs?)?"
        r"(?:\s?[–-]\s?(?:₹|\$|€|£)?\s?[\d,.]+\s?(?:[kKmM]|lpa|lacs?)?)?",
        text or "",
    )
    return match.group(0) if match else ""


class Adapter(abc.ABC):
    name: str = ""
    # Selectors that are visible ONLY when logged out (login button, password box). A URL check
    # alone is not enough: portals often show the login form on a normal-looking URL.
    logged_out_markers: Sequence[str] = ()
    logged_out_url_hints: Sequence[str] = ("login",)
    # A portal that must be treated gently asks for longer pauses than Criteria's: (min, max) seconds between jobs.
    pacing_floor_s: Optional[Tuple[float, float]] = None
    # True when a job parked for an unanswered question can never have been sent: every question is asked before the press
    # that sends. Only then does parking give the run's attempt back (a portal that applies on the first click cannot say so).
    parks_before_sending: bool = False
    # True for a portal that only LISTS jobs: every application is made on the employer's site, so the AI agent is always needed there.
    applies_elsewhere: bool = False
    # A pop-up whose wording matches this holds the application itself (or a question about it): never closed as a nuisance.
    protected_prompts: Optional[Pattern] = None

    def __init__(self, page, profile: Profile, criteria: Criteria, failures_dir: Optional[Path] = None):
        self.page = page
        self.active = page  # the tab currently being driven (wizards may open another)
        self.prompt_judge: Optional[Judge] = None  # the AI helper, for a pop-up the rules do not know (set when it is on)
        self.dismissed: List[str] = []  # every pop-up closed this run, for the report
        self.profile = profile
        self.criteria = criteria
        self.failures_dir = failures_dir
        self.network = evidence.NetworkWatch(page)  # what the browser last heard back, for the note a failure leaves
    # -- the contract ---------------------------------------------------------
    @abc.abstractmethod
    def is_logged_in(self) -> bool: ...

    @abc.abstractmethod
    def queries(self) -> Iterator[str]:
        """Opaque search handles (usually URLs) for discover()."""

    def suggested_queries(self) -> Iterator[str]:
        """Where the site itself suggests jobs. A site with no such page of its own falls back to your ordinary searches."""
        return self.queries()

    @abc.abstractmethod
    def discover(self, query: str) -> Iterator[JobCard]: ...

    @abc.abstractmethod
    def read_job(self, card: JobCard) -> Job: ...

    @abc.abstractmethod
    def apply(self, job: Job, resolver, dry_run: bool) -> Result: ...

    def applied(self, job: Job) -> None:
        """An application to this job was confirmed sent (here, or by the agent on the employer's site). A portal that keeps a record of
        what you applied to may write it there. Most do it themselves already, so the default does nothing."""

    def sync_resume(self, path: Path) -> None:
        raise NotImplementedError(f"{self.name}: applies with the resume stored in your portal profile")

    # -- shared plumbing --------------------------------------------------------
    def tab_lost(self) -> bool:
        """Has the tab this run drives been closed (by you, or by a crash)? Only the main tab counts: a form tab a wizard opened for itself and
        closed again is not a loss."""
        try:
            return bool(self.page.is_closed())
        except Exception:  # a stand-in page that cannot say: take it as open, and let the real error show
            return False

    def reopen_tab(self) -> bool:
        """A fresh tab in the same browser, so you are still logged in. False when the browser itself is gone: then there is nothing to open one in."""
        try:
            fresh = self.page.context.new_page()
        except Exception:
            return False
        self.page = self.active = fresh
        self.network = evidence.NetworkWatch(fresh)
        return True

    def is_challenge(self) -> bool:
        return looks_like_challenge(self.active)

    def check_challenge(self) -> None:
        if self.is_challenge():
            raise ChallengeDetected(self.active.url)

    def check_login(self) -> None:
        """Raise NotLoggedIn if a login wall is showing (session expired or never logged in)."""
        if self.logged_out_markers and first_visible(self.active, self.logged_out_markers) is not None:
            raise NotLoggedIn(f"{self.name}: a login page is showing at {self.active.url}")

    def wait_logged_in(self, timeout_s: float = 12.0, min_dwell_s: float = MIN_AUTH_DWELL_S) -> bool:
        """True only after the page has had time to decide, and still shows a non-login page.

        Single-page apps (Naukri) load in ~1s, show a spinner, and only redirect to the login screen
        at ~3s (measured), so judging right after load is a race. A login wall at ANY point in the
        window returns False at once; "logged in" needs min_dwell_s of clean, rendered page.
        Failing closed: a page that never settles counts as NOT logged in.
        """
        start = time.monotonic()
        while True:
            url = self.active.url.lower()
            if any(hint in url for hint in self.logged_out_url_hints):
                return False
            if self.logged_out_markers and first_visible(self.active, self.logged_out_markers) is not None:
                return False
            elapsed = time.monotonic() - start
            if elapsed >= min_dwell_s and len(self.body_text(2000).strip()) >= RENDERED_MIN_CHARS:
                return True
            if elapsed >= timeout_s:
                return False
            self.active.wait_for_timeout(500)

    def settle(self, low: float = 0.6, high: float = 1.5) -> None:
        self.active.wait_for_timeout(random.uniform(low, high) * 1000)

    def goto(self, url: str) -> None:
        self.active.goto(url, wait_until="domcontentloaded", timeout=45_000)
        self.settle()
        self.check_challenge()
        self.check_login()
        self.dismiss_prompts()

    def dismiss_prompts(self) -> None:
        """Close an advert, upsell or sign-up pop-up that covers the page, by pressing its no. Never during a challenge: that needs a person."""
        if self.is_challenge():
            return
        self.dismissed += dismiss_prompts(self.active, self.prompt_judge, self.protected_prompts)

    def body_text(self, limit: int = 8000) -> str:
        try:
            return self.active.inner_text("body", timeout=5000)[:limit]
        except Exception:
            return ""

    def capture_failure(self, card: JobCard) -> Optional[Path]:
        """What a failed job leaves behind so a selector can be repaired, or a cause read, without re-running: a picture, the page's HTML, the
        address, and a note of what the page showed and what the network just answered (see evidence.py). Each is kept even if another cannot be."""
        if not self.failures_dir:
            return None
        self.failures_dir.mkdir(parents=True, exist_ok=True)
        stem = self.failures_dir / f"{self.name}-{int(time.time())}"
        steps = (lambda: self.active.screenshot(path=f"{stem}.png"),
                 lambda: Path(f"{stem}.html").write_text(self.active.content()[:300_000], encoding="utf-8"),
                 lambda: Path(f"{stem}.txt").write_text(f"{card.url}\n", encoding="utf-8"),
                 lambda: evidence.save(Path(f"{stem}.json"), self.active, self.network, card.url, card.title))
        kept = 0
        for step in steps:
            try:
                step()
                kept += 1
            except Exception:
                evidence.log.debug("part of the failure capture could not be taken", exc_info=True)
        return stem if kept else None
