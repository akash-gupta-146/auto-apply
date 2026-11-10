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
from .prompts import Judge, dismiss_prompts

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


def looks_like_challenge(page) -> bool:
    """Visible captcha / bot-wall on this page? Conservative: text is checked at the top only."""
    url = page.url.lower()
    if any(hint in url for hint in CHALLENGE_URL_HINTS):
        return True
    for selector in CHALLENGE_SELECTORS:
        try:
            if page.locator(selector).first.is_visible():
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

    def sync_resume(self, path: Path) -> None:
        raise NotImplementedError(f"{self.name}: applies with the resume stored in your portal profile")

    # -- shared plumbing --------------------------------------------------------
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
        """Screenshot + trimmed HTML so a selector can be repaired without re-running."""
        if not self.failures_dir:
            return None
        self.failures_dir.mkdir(parents=True, exist_ok=True)
        stem = self.failures_dir / f"{self.name}-{int(time.time())}"
        try:
            self.active.screenshot(path=f"{stem}.png")
            Path(f"{stem}.html").write_text(self.active.content()[:300_000], encoding="utf-8")
            Path(f"{stem}.txt").write_text(f"{card.url}\n", encoding="utf-8")
        except Exception:
            return None
        return stem
