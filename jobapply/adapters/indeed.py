"""Indeed adapter (country domain from Criteria.indeed_domain, default in.indeed.com).

Flow: search URL -> job page -> "Apply now" opens Indeed's own application form (SmartApply, in a new tab or in this
one): resume -> questions -> review -> "Submit your application". It works with or without the AI helper: the
resolver the engine passes in decides who answers a question (your answers and rules, then the AI if it is on).

Rules that keep this safe:
  * a form is only ever filled while the address is Indeed's own application form (not just any indeed.com page: Indeed's
    /applystart redirect leads on to company websites). A job whose Apply button ends up elsewhere is skipped, and so is a
    form that wanders off half way: your details never go to a stranger's page.
  * "applied" is only reported after Indeed itself says so; a step Indeed will not accept is an error, not a guess.
  * Indeed sits behind Cloudflare: expect challenges here. That is what the 5-minute human window is for.

Checked live, read-only: the login check, search cards, a job page's text. NOT yet checked live: Indeed's own Apply button
and form (every job looked at so far said "Apply on company site"). See `jobapply probe indeed`.
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import quote_plus, urlparse

from ..models import ChallengeDetected, Job, JobCard, NotLoggedIn, Result, Status
from .base import Adapter, find_salary, first_visible, looks_like_challenge
from .forms import click_choice, fill_form, let_person_answer, radio_groups

MAX_PAGES = 3
MAX_WIZARD_STEPS = 12
STALLED_STEPS = 2  # the same step again after pressing Continue this many times: Indeed is not accepting it
STEP_WAIT_MS = 8_000  # after Continue, how long the page gets to show the next step before we look again
STEP_POLL_MS = 250
CONFIRM_WAIT_MS = 10_000  # after Submit, how long Indeed gets to say the application was sent
CONFIRM_POLL_MS = 500
FORM_OPEN_MS = 15_000

SEL = {
    "apply": "#indeedApplyButton, button[id*='indeedApply'], [data-testid*='indeedApply']",
    "description": "#jobDescriptionText",
    "salary": "#salaryInfoAndJobType, [data-testid*='salary']",
    "form": "main, form",
    "continue": "button:has-text('Continue'), button:has-text('Next')",
    "submit": "button:has-text('Submit your application'), button:has-text('Submit')",
    "problem": "[role='alert'], [id*='error' i], [data-testid*='error' i]",
}
SENT = re.compile(r"application (?:has been )?(?:submitted|sent)|thanks for applying", re.I)
EXPIRED = re.compile(r"no longer (?:available|accepting)|has expired|job has been (?:closed|removed)", re.I)
APPLIED_BEFORE = re.compile(r"\byou(?:'ve| have)? applied\b|already applied", re.I)
RESUME = re.compile(r"resume|\bcv\b", re.I)
NEW_RESUME = re.compile(r"upload|build|create|new|add|write", re.I)  # the options that are not a resume you already have

CARD_JS = """els => els.map(e => {
  const a = e.querySelector('h2.jobTitle a, a.jcs-JobTitle');
  const co = e.querySelector('[data-testid="company-name"], .companyName');
  const lo = e.querySelector('[data-testid="text-location"], .companyLocation');
  // a card a person cannot see is not one to follow (the live results page carries an unseen duplicate of a real card)
  const shown = !!a && a.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[aria-hidden=true]');
  return {jk: a ? (a.getAttribute('data-jk') || '') : '', title: a ? a.innerText.trim() : '',
          company: co ? co.innerText.trim() : '', location: lo ? lo.innerText.trim() : '',
          easy: /easily apply/i.test(e.innerText), shown};
})"""
STEP_JS = """() => [location.href, (document.querySelector('h1, h2') || {}).innerText || '',
                  document.querySelectorAll('input, select, textarea').length].join('|')"""


class OffSite(Exception):
    """The application form is no longer on Indeed."""


def on_indeed(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == "indeed.com" or host.endswith(".indeed.com")


def is_form(url: str) -> bool:
    """Indeed's own application form, not just any Indeed address: /applystart, for one, goes on to a company's site."""
    return on_indeed(url) and ("smartapply" in (urlparse(url).hostname or "") or "indeedapply" in url.lower())


class IndeedAdapter(Adapter):
    name = "indeed"
    logged_out_url_hints = ("secure.indeed.com/auth", "/account/login")
    pacing_floor_s = (30.0, 90.0)  # Cloudflare watches the pace: wait longer between jobs than the settings say
    _parked = None  # the form tab a person is being asked to help in (a captcha); kept open until they have

    @property
    def _base(self) -> str:
        return f"https://{self.criteria.indeed_domain}"

    def goto(self, url: str) -> None:
        self._close_parked()  # whoever was asked for help has had their time: move on
        super().goto(url)

    def is_challenge(self) -> bool:
        """While a person is solving a check in the form's tab, that tab is the one to watch (the engine waits on this)."""
        if self._parked is not None:
            if not self._parked.is_closed() and looks_like_challenge(self._parked):
                return True
            self._close_parked()  # solved, or closed by them: the engine can carry on
        return super().is_challenge()

    def _close_parked(self) -> None:
        tab, self._parked = self._parked, None
        if tab is not None:
            try:
                tab.close()
            except Exception:
                pass

    def is_logged_in(self) -> bool:
        self.goto("https://profile.indeed.com/")
        return not any(hint in self.active.url.lower() for hint in self.logged_out_url_hints)

    def queries(self) -> Iterator[str]:
        roles = " OR ".join(f'"{role}"' for role in self.criteria.target_roles)
        for location in self.criteria.locations or [""]:
            yield f"{self._base}/jobs?q={quote_plus(roles)}&l={quote_plus(location)}&fromage=7"

    def discover(self, query: str) -> Iterator[JobCard]:
        self.goto(query)
        for _ in range(MAX_PAGES):
            try:
                self.active.wait_for_selector("div.job_seen_beacon", timeout=10_000)
            except Exception:
                return
            items = [i for i in self.active.eval_on_selector_all("div.job_seen_beacon", CARD_JS) if i["jk"] and i["title"] and i["shown"]]
            easy = [i for i in items if i["easy"]]
            for item in easy or items:  # no card says "Easily apply" at all: the wording moved, apply() still checks
                yield JobCard(self.name, f"{self._base}/viewjob?jk={item['jk']}", item["title"], item["company"], item["location"])
            nxt = first_visible(self.active, ["a[data-testid='pagination-page-next']", "a[aria-label='Next Page']"])
            if nxt is None:
                return
            self.dismiss_prompts()  # Indeed's job-alert pop-up appears mid-results and covers the page: a covered Next cannot be clicked
            nxt.click()
            self.settle(1.5, 3)
            self.check_challenge()

    def read_job(self, card: JobCard) -> Job:
        self.goto(card.url)
        description = self._text(SEL["description"]) or self.body_text()
        salary = self._text(SEL["salary"]) or find_salary(description)
        applied = first_visible(self.page, [SEL["apply"]]) is None and bool(APPLIED_BEFORE.search(self.body_text(2500)))
        return Job.from_card(card, description=description[:8000], salary=salary, already_applied=applied)

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        self.dismiss_prompts()  # a pop-up that came up since the page was read would swallow the click on Apply
        button = first_visible(self.page, [SEL["apply"]])
        if button is None:
            closed = EXPIRED.search(self.body_text(3000))
            return Result(Status.SKIPPED_EXTERNAL, "no longer accepting applications" if closed else "no Indeed-native apply")
        tab, is_new_tab = self._open_form(button)
        self.active = tab  # challenge checks now watch the form
        try:
            self._guard(tab)
            return self._walk(tab, resolver, dry_run)
        except OffSite as exc:
            return Result(Status.SKIPPED_EXTERNAL, f"{exc}: not Indeed's own form, so nothing was filled in")
        except ChallengeDetected:
            if is_new_tab:  # leave the tab open: the person solves the check IN it, and is_challenge() watches it
                self._parked, is_new_tab = tab, False
            raise
        finally:
            self.active = self.page
            if is_new_tab:
                try:
                    tab.close()
                except Exception:
                    pass

    # -- internals -----------------------------------------------------------------
    def _text(self, selector: str) -> str:
        locator = first_visible(self.page, [selector])
        return locator.inner_text() if locator is not None else ""

    def _open_form(self, button):
        """Press Apply. The form opens in a new tab or in this one; returns (page showing it, whether it is a new tab)."""
        try:
            with self.page.context.expect_page(timeout=FORM_OPEN_MS) as opened:
                button.click()
            tab, is_new_tab = opened.value, True
            tab.wait_for_load_state("domcontentloaded")
        except Exception:
            tab, is_new_tab = self.page, False
        self._let_redirects_land(tab)
        return tab, is_new_tab

    def _let_redirects_land(self, tab) -> None:
        """Apply goes through /applystart, which moves on to Indeed's own form or to the company's site.
        Judge the address only once it has: an address that is about to change proves nothing."""
        for _ in range(STEP_WAIT_MS // STEP_POLL_MS):
            if "/applystart" not in tab.url:
                return
            tab.wait_for_timeout(STEP_POLL_MS)

    def _guard(self, tab) -> None:
        """Stop, before anything is typed, if the session ended or the form is not Indeed's own."""
        url = tab.url
        if any(hint in url.lower() for hint in self.logged_out_url_hints):
            raise NotLoggedIn(f"{self.name}: a login page is showing at {url}")
        if not is_form(url):
            where = urlparse(url)
            raise OffSite(f"the Apply button leads to {(where.hostname or 'nowhere') + where.path[:40]}")

    def _walk(self, tab, resolver, dry_run: bool) -> Result:
        stalled, last = 0, None
        for _ in range(MAX_WIZARD_STEPS):
            self.settle(1, 2)
            self.check_challenge()
            self._guard(tab)
            form = first_visible(tab, [SEL["form"]]) or tab.locator("body")
            self._pick_resume(form)
            def fill():
                fill_form(form, resolver, default_required=True)  # Indeed marks what is optional, not what is required

            fill()
            let_person_answer(tab, resolver, fill)  # you may answer what it could not, right here in the form
            resolver.require_complete()  # an answer nobody can give parks the job, before anything moves on
            submit = first_visible(tab, [SEL["submit"]])
            if submit is not None:
                if dry_run:
                    return Result(Status.DRY_RUN_OK, "reached the review step; nothing was sent")
                submit.click()
                return self._confirm_sent(tab)
            advance = first_visible(tab, [SEL["continue"]])
            if advance is None:
                raise RuntimeError("the application form has neither Continue nor Submit")
            signature = tab.evaluate(STEP_JS)
            stalled = stalled + 1 if signature == last else 0
            if stalled >= STALLED_STEPS:
                problem = first_visible(tab, [SEL["problem"]])
                raise RuntimeError(f"Indeed did not accept this step: {problem.inner_text().strip() if problem else 'a required answer is missing or not valid'}")
            last = signature
            advance.click()
            self._wait_for_new_step(tab, signature)
        raise RuntimeError("the application form did not finish")

    def _wait_for_new_step(self, tab, before: str) -> None:
        """Continue starts a move that lands a moment later: type nothing until the page has really changed.

        Typing into a page that is being replaced loses the answer (and makes the browser wait for fields that are
        gone). A page that never changes is not an error here: the stall check on the next round says so.
        """
        for _ in range(STEP_WAIT_MS // STEP_POLL_MS):
            tab.wait_for_timeout(STEP_POLL_MS)
            try:
                if tab.evaluate(STEP_JS) != before:
                    tab.wait_for_load_state("domcontentloaded")
                    return
            except Exception:
                return  # the page is in the middle of the move, which is the change we were waiting for

    def _pick_resume(self, form) -> None:
        """The resume step is not a question to answer: use a resume the account already has, never invent one."""
        for group in radio_groups(form):
            try:
                if not RESUME.search(group["legend"]):
                    continue
                radios = form.locator(f'input[type="radio"][name="{group["name"]}"]')
                if any(radios.nth(i).is_checked() for i in range(radios.count())):
                    continue  # Indeed already chose one
                have = [i for i, text in enumerate(group["options"]) if not NEW_RESUME.search(text)]
                if have:
                    click_choice(radios.nth(have[0]))
            except Exception:
                continue

    def _confirm_sent(self, tab) -> Result:
        """Applied only when Indeed itself says so. Anything else is a failure, never a guess."""
        for _ in range(CONFIRM_WAIT_MS // CONFIRM_POLL_MS):
            tab.wait_for_timeout(CONFIRM_POLL_MS)  # a real wait: this is not a pause to look human
            if "post-apply" in tab.url or SENT.search(self.body_text(3000)):
                return Result(Status.APPLIED, "Indeed confirmed it sent (its post-apply page, or \"application sent\")")
        raise RuntimeError("submitted, but Indeed did not show that the application was sent")
