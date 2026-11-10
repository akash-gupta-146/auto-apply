"""LinkedIn adapter: Easy Apply jobs only, and slowly.

LinkedIn's rules forbid automation and it restricts accounts that use it, so this adapter is deliberately narrow:
  * every search carries LinkedIn's own "Easy Apply" filter (f_AL=true), and nothing is read until the page shows that
    filter really is switched on (it never browses unfiltered results, which mix in ordinary "Apply" jobs);
  * a job is touched only if its own card says "Easy Apply" AND its page has the Easy Apply button; anything else
    (a company's own site, a closed or already-applied job) is skipped;
  * it goes through the Easy Apply window the way a person does (Next, Review, Submit), fills only what your profile can
    honestly answer, never presses "Follow company", and leaves nothing half-done (Dismiss, then Discard);
  * it waits longer between jobs than the other sites (pacing_floor_s).

Seen on the live site (the new /jobs/search-results layout, November 2026): the f_AL=true toggle and "&start=25" paging,
cards marked componentkey="job-card-component-ref-<job id>" each with an "Easy Apply" badge, the "Easy Apply to this
job" button, the "Apply to <company>" window (it opens EMPTY and fills in seconds later) with its 5 pages: contact
(pre-filled), resume (pre-selected), questions, Review, and the last page with "Submit application" and a ticked "Follow
<company>" box; and the "Save this application?" question with Discard. Questions and the Follow box have EMPTY labels: the
words live in aria-label, which is how they are read. A rehearsal has run all the way to the Submit button on a real job.
NOT yet seen: pressing Submit and the "Application sent" message (LinkedIn's long-standing words), other question types
(dropdowns, long text). Calibrate with one real application (`--attempts 1`) before trusting it with more.
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import quote_plus

from ..models import Job, JobCard, NotLoggedIn, NothingSent, Result, Status
from .base import Adapter, find_salary, first_visible
from .forms import fill_form, let_person_answer
from .linkedin_picks import PICKS, discover_picks

FEED = "https://www.linkedin.com/feed/"
SEARCH = "https://www.linkedin.com/jobs/search/?keywords={keywords}{where}&f_AL=true&f_TPR=r604800"  # Easy Apply, past week
PAGE_SIZE = 25
MAX_PAGES = 4
MAX_SCROLLS = 4
MAX_WIZARD_STEPS = 12
BUTTON_WAIT_MS = 8_000  # how long a job page gets to show its Easy Apply button
STEP_WAIT_MS = 12_000  # how long the Easy Apply window gets to fill in (it opens empty, and has been seen to take seconds)
STEP_POLL_MS = 300
STALLED_STEPS = 2  # pressing Next this many times without the window moving on means an answer is missing or wrong
FILTER_WAIT_MS = 10_000  # how long a fresh search gets to draw the Easy Apply toggle (it redraws the page once or twice)
DESCRIPTION_WAIT_MS = 15_000  # a job page draws its header first and "About the job" 3 to 5 seconds later
ABOUT = "About the job"
AFTER_DESCRIPTION = "Set alert for similar jobs"  # what follows the description; below it come OTHER jobs' titles
APPLIED_WINDOW = 3_000  # a job's applied status is near the top of its page; later text is the company's own words
SENT = re.compile(r"application (was )?sent", re.I)
SUBMITTED = re.compile(r"application submitted", re.I)  # the status block of a job you applied to
CONFIRMED = "LinkedIn confirmed it sent (\"Application sent\", or \"Application submitted\" on the job page)"
# What LinkedIn writes on a job you already applied to (seen live: "Application status" with "Application submitted").
ALREADY_APPLIED = re.compile(r"application (status|submitted)|you applied|applied (on|\d)", re.I)

CARD = '[componentkey^="job-card-component-ref-"]'
SEL = {
    "easy_apply": "button[aria-label^='Easy Apply']",
    "next": "button:has-text('Next')",
    "review": "button:has-text('Review')",
    "submit": "button:has-text('Submit application')",
    "dismiss": "dialog button[aria-label='Dismiss']",
    "discard": "dialog:has-text('Save this application') button:has-text('Discard')",
    "filter": "label:text-is('Easy Apply')",
}

# One entry per job. The first line of a card is a hidden accessible name that repeats the title (with "Selected, " and
# "(Verified job)" around it); the visible lines after it are the title, the company and the place.
CARDS_JS = """() => {
  const strip = s => s.replace(/^Selected,\\s*/i, '').replace(/\\s*\\(verified job\\)\\s*$/i, '').trim();
  const seen = new Set(), out = [];
  for (const el of document.querySelectorAll('[componentkey^="job-card-component-ref-"]')) {
    const id = (el.getAttribute('componentkey').match(/(\\d{6,})$/) || [])[1];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const lines = el.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
    const skip = lines.length > 1 && strip(lines[0]) === lines[1] ? 1 : 0;
    const easy = [...el.querySelectorAll('p, span')].some(e => /^easy apply$/i.test((e.innerText || '').trim()));
    // a job you already applied to keeps its card, marked "Applied"; its page has no Easy Apply button
    const applied = [...el.querySelectorAll('p, span')].some(e => /^applied$/i.test((e.innerText || '').trim()));
    out.push({id, title: lines[skip] || '', company: lines[skip + 1] || '', location: lines[skip + 2] || '', easy, applied});
  }
  return out;
}"""

# The Easy Apply toggle is a label over a checkbox: read the checkbox, not the label.
FILTER_JS = """() => [...document.querySelectorAll('label')].filter(l => /^easy apply$/i.test((l.innerText || '').trim()) && l.control)
  .map(l => ({checked: !!l.control.checked, visible: l.getBoundingClientRect().width > 0}))"""

# A job page draws the section a few seconds after its header: true once the text of <main> holds the section's title.
ABOUT_DRAWN_JS = "title => ((document.querySelector('main') || document.body).innerText || '').includes(title)"

# What a step is complaining about: a message LinkedIn announced as an alert, and every field it marked invalid.
OBJECTIONS_JS = """box => [...new Set([
  ...[...box.querySelectorAll('[role=alert], [aria-live=assertive]')].map(e => (e.innerText || '').trim()),
  // the live page does not announce them as alerts: a short line of red text such as "This field is required"
  ...[...box.querySelectorAll('p, span, div')].filter(e => e.children.length === 0
      && /^(this field is required|please .{3,60}|enter a valid .{3,40}|select an option.*)\\.?$/i.test((e.innerText || '').trim()))
      .map(e => (e.innerText || '').trim()),
  ...[...box.querySelectorAll('[aria-invalid=true]')].map(e => 'invalid field: ' + (e.getAttribute('aria-label')
      || (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.name || '').trim()),
].map(s => s.replace(/\\s+/g, ' ')))].filter(Boolean).slice(0, 6)"""

# A checkbox's name. On the live page the input is hidden, its label is EMPTY, and the words are only in aria-label.
NAME_JS = """c => c.getAttribute('aria-label') || (c.labels && c.labels[0] ? c.labels[0].innerText : '') || (c.parentElement ? c.parentElement.innerText : '')"""
CLICK_LABEL_JS = "c => (c.labels && c.labels[0] ? c.labels[0] : c).click()"  # what a person clicks: the visible label
FOLLOW = re.compile(r"\bfollow\b", re.I)


class LinkedInAdapter(Adapter):
    name = "linkedin"
    logged_out_markers = ("input[name=session_key]",)
    logged_out_url_hints = ("login", "authwall", "checkpoint", "/uas/")
    pacing_floor_s = (45.0, 120.0)
    parks_before_sending = True  # Submit is pressed only after every question is answered, and a parked window is Discarded
    protected_prompts = re.compile(r"\bApply to\b|Save this application", re.I)  # the Easy Apply window and its own "save?" question

    def is_logged_in(self) -> bool:
        try:
            self.goto(FEED)
        except NotLoggedIn:
            return False
        return "/feed" in self.active.url

    def queries(self) -> Iterator[str]:
        for role in self.criteria.target_roles:
            for location in self.criteria.locations or [""]:
                where = f"&location={quote_plus(location)}" if location else ""
                yield SEARCH.format(keywords=quote_plus(role), where=where)

    def suggested_queries(self) -> Iterator[str]:
        yield PICKS

    def discover(self, query: str) -> Iterator[JobCard]:
        if query.startswith(PICKS):
            yield from discover_picks(self, query)
            return
        seen = set()
        for page_no in range(MAX_PAGES):
            self.goto(query if page_no == 0 else f"{query}&start={page_no * PAGE_SIZE}")
            try:
                self.active.wait_for_selector(CARD, timeout=20_000)
            except Exception:
                return  # no cards: genuinely none, and the engine saves the page as evidence
            self._require_easy_apply_filter()
            listed = 0
            for _ in range(MAX_SCROLLS):  # the list fills in as it is scrolled
                fresh = [item for item in self.active.evaluate(CARDS_JS) if item["id"] not in seen]
                if not fresh:
                    break
                for item in fresh:
                    seen.add(item["id"])
                    if item["easy"] and item["title"]:  # the filter is on, but a card that does not say so is never trusted
                        listed += 1
                        if item["applied"]:
                            continue  # already applied: nothing to do, and no reason to open it
                        yield JobCard(self.name, f"https://www.linkedin.com/jobs/view/{item['id']}/", item["title"],
                                      item["company"], item["location"])
                try:
                    self.active.locator(CARD).last.scroll_into_view_if_needed()
                except Exception:
                    break  # the list was redrawn under us: keep what was read, the next search starts afresh
                self.settle(1, 2)
            if not listed:  # a page of only applied jobs is not the end of the results
                return

    def _filter_toggles(self) -> list:
        """The Easy Apply toggles that are drawn. A new search redraws the page, so give it a few seconds to show them
        (judging at once made a healthy search look like one with no filter)."""
        for _ in range(FILTER_WAIT_MS // STEP_POLL_MS):
            try:
                shown = [toggle for toggle in self.active.evaluate(FILTER_JS) if toggle["visible"]]
            except Exception:
                shown = []  # the page is being replaced right now
            if shown:
                return shown
            self.active.wait_for_timeout(STEP_POLL_MS)
        return []

    def _require_easy_apply_filter(self) -> None:
        """Fail closed: with the filter off the results include ordinary 'Apply' jobs, so nothing is read."""
        for attempt in (1, 2):
            shown = self._filter_toggles()
            if shown and all(toggle["checked"] for toggle in shown):
                return
            if attempt == 1:
                toggle = first_visible(self.active, [SEL["filter"]])
                if toggle is not None:
                    toggle.click()
                    self.settle(2, 3)
        raise RuntimeError("LinkedIn's Easy Apply filter is not on, and could not be switched on: nothing was read")

    def read_job(self, card: JobCard) -> Job:
        self.goto(card.url)
        try:
            self.active.wait_for_selector("main", timeout=15_000)
            # Reading the moment <main> appears gave every job NO description (so the rules and the AI judged an empty job).
            self.active.wait_for_function(ABOUT_DRAWN_JS, arg=ABOUT, polling=400, timeout=DESCRIPTION_WAIT_MS)
        except Exception:
            pass  # no such section on this page: judge it by whatever is there
        main = first_visible(self.active, ["main"])
        text = main.inner_text() if main is not None else self.body_text()
        applied = bool(ALREADY_APPLIED.search(text[:APPLIED_WINDOW]))
        return Job.from_card(card, description=self._description(text)[:8000], salary=find_salary(text), already_applied=applied)

    @staticmethod
    def _description(text: str) -> str:
        """The page up to where the description ends: what follows is other jobs, which must not count as this job's skills."""
        start = text.find(ABOUT)
        end = text.find(AFTER_DESCRIPTION, max(start, 0))
        return text[:end] if start >= 0 and end > start else text

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        button = self._easy_apply_button()
        if button is None:
            if ALREADY_APPLIED.search(self.body_text(APPLIED_WINDOW)):
                return Result(Status.SKIPPED_DUPLICATE, "LinkedIn shows this job as already applied")
            return Result(Status.SKIPPED_EXTERNAL, "no Easy Apply button (company site, closed, or already applied)")
        button.click()
        self.settle(1.5, 2.5)
        try:
            return self._walk(resolver, dry_run)
        except RuntimeError:
            self.capture_failure(job)  # while the window is still open: once it is closed the page no longer shows what was wrong
            raise
        finally:
            self._close_window()

    # -- internals -----------------------------------------------------------------
    def _easy_apply_button(self):
        try:
            self.active.wait_for_selector(SEL["easy_apply"], timeout=BUTTON_WAIT_MS)
        except Exception:
            return None
        return first_visible(self.active, [SEL["easy_apply"]])

    def _window(self):
        heading = self.active.get_by_role("heading", name=re.compile(r"^Apply to", re.I))
        return self.active.locator("dialog").filter(has=heading).first

    def _step_signature(self, window):
        progress = window.locator("[role=progressbar]").first
        heading = window.locator("h1, h2, h3").first
        return (progress.get_attribute("aria-valuenow") if progress.count() else None,
                heading.inner_text() if heading.count() else None)

    def _step_window(self):
        """The window opens empty and fills in later: wait until it shows a button that moves it on, not a fixed pause."""
        window = self._window()
        for _ in range(STEP_WAIT_MS // STEP_POLL_MS):
            if window.count() and first_visible(window, [SEL["submit"], SEL["review"], SEL["next"]]) is not None:
                break
            self.active.wait_for_timeout(STEP_POLL_MS)
        return window

    def _decline_follow(self, window) -> None:
        """LinkedIn ticks "Follow <company>" for you on the last step. That is not what was asked for: untick it, or stop."""
        for box in window.locator("input[type=checkbox]").all():
            if box.is_checked() and FOLLOW.search(box.evaluate(NAME_JS)):
                box.evaluate(CLICK_LABEL_JS)
                if box.is_checked():
                    try:
                        box.uncheck(force=True)
                    except Exception:
                        pass  # the check below is the verdict, not whatever the click complained about
                if box.is_checked():
                    raise NothingSent("could not untick 'Follow company': stopping rather than follow a company you did not choose")

    def _walk(self, resolver, dry_run: bool) -> Result:
        stalled, last = 0, None
        for _ in range(MAX_WIZARD_STEPS):
            self.settle(1, 2)
            self.check_challenge()
            window = self._step_window()
            if window.count() == 0:
                raise NothingSent("the Easy Apply window did not open")
            def fill():
                fill_form(window, resolver, keep_chosen=True)  # LinkedIn pre-fills your contact details: leave those alone

            fill()
            let_person_answer(self.active, resolver, fill)  # you may answer what it could not, right here in the form
            self._decline_follow(window)
            resolver.require_complete()  # an answer the profile cannot give parks the job, before anything moves on
            submit = first_visible(window, [SEL["submit"]])
            if submit is not None:
                if dry_run:
                    return Result(Status.DRY_RUN_OK, "reached the review step; nothing was sent")
                submit.click()
                return self._confirm_sent()
            advance = first_visible(window, [SEL["review"], SEL["next"]])
            if advance is None:
                raise NothingSent("the Easy Apply window has neither Next, Review nor Submit")
            signature = self._step_signature(window)
            stalled = stalled + 1 if signature == last else 0
            if stalled >= STALLED_STEPS:
                raise NothingSent("LinkedIn did not accept this step: a required answer is missing or not valid"
                                   + self._objections(window))
            last = signature
            advance.click()
        raise NothingSent("the Easy Apply window did not finish")

    @staticmethod
    def _objections(window) -> str:
        """What LinkedIn itself complained about on this step: its error messages and the fields it marked invalid."""
        try:
            found = window.evaluate(OBJECTIONS_JS)
        except Exception:
            return ""
        return f" (LinkedIn says: {'; '.join(found)})" if found else ""

    def _confirm_sent(self) -> Result:
        """Applied only when LinkedIn itself says so, in either of the two ways it was seen to: an "Application sent" window, or
        (live, November 2026) no window at all and the job page's own "Application status: Application submitted".
        Anything else is a failure, never a guess."""
        if self._sent_shown():
            self.dismiss_prompts()  # the "sent" window is the proof, read: now say no to its "update your profile" offer
            return Result(Status.APPLIED, CONFIRMED)
        self._close_window()  # the status may only be drawn once the window is gone
        if self._sent_shown(tries=5):
            return Result(Status.APPLIED, CONFIRMED)
        raise RuntimeError("submitted, but LinkedIn did not show 'Application sent'")

    def _sent_shown(self, tries: int = 10) -> bool:
        for _ in range(tries):
            self.settle(0.8, 1.2)
            for dialog in self.active.locator("dialog").all():
                if dialog.is_visible() and SENT.search(dialog.inner_text()):
                    return True
            if SUBMITTED.search(self.body_text(APPLIED_WINDOW)):
                return True  # this job showed no such status when it was read, so it is this press that put it there
        return False

    def _close_window(self) -> None:
        """Leave nothing half-done: Dismiss the window and, when LinkedIn asks whether to save, Discard."""
        for _ in range(3):
            try:
                discard = first_visible(self.active, [SEL["discard"]])
                if discard is not None:
                    discard.click()
                    self.settle(1, 1.5)
                    continue
                dismiss = first_visible(self.active, [SEL["dismiss"]])
                if dismiss is None:
                    return
                dismiss.click()
                self.settle(1, 1.5)
            except Exception:
                return  # best effort: this runs while another error may already be on its way up
