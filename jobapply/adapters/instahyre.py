"""Instahyre adapter.

Instahyre is a curated queue, not a list of links: each opportunity is a card headed "Company - Role" with
"View job" and "Not interested". "View job" opens an overlay (a fixed-position block, no dialog role) holding the
full description and the real "Apply" next to a second "Not interested".
Cards have no URL, so we tag each card's DOM node with a stable id and use a pseudo-URL
(`<query-url>#<id>`) as the queue key; read_job() reloads the query page that found it.

Seen live (November 2026): the cards, their headers, the overlay and its Apply button. NOT yet seen: what the
page does after a real Apply press (the code only checks that the button went away).
"""
from __future__ import annotations

import re
from typing import Iterator, Tuple

from ..models import Job, JobCard, NotLoggedIn, Result, SetupIncomplete, Status
from .base import Adapter, first_visible

OPPORTUNITIES = "https://www.instahyre.com/candidate/opportunities/?matching=true"
SEARCH_OTHER = "https://www.instahyre.com/candidate/opportunities/?matching=true&search=true&years={years}"
MAX_SCROLLS = 6

# Until a new profile is finished, Instahyre shows a 4-step wizard (Add skills, Job preferences, Upload resume, Privacy
# settings) INSTEAD of the opportunities (seen live). Those steps set the person's preferences, resume and privacy:
# only they can do them, so the program recognises the wizard, stops, and says so rather than finding "0 jobs".
SETUP_STEPS = ("job preferences", "upload resume", "privacy settings")
SETUP_MESSAGE = ("Instahyre is asking you to finish setting up your profile first (Add skills, Job preferences, Upload "
                 "resume, Privacy settings). Do that yourself in the automation browser window, then check again. "
                 "This program never fills those steps in for you.")

SEL = {
    "apply": "button:text-is('Apply')",
    "undecided": "label:has-text('Undecided')",
}

VIEW = re.compile(r"^\s*view", re.I)

# Find every card and tag it with data-ja-id. DOM-agnostic on purpose, but two different blocks matter:
#  - the HEADER: the smallest block around a "View" button that holds "Not interested" AND words that are not
#    button labels (live: "Swiggy - SDE III", "Work From Home", ...). The smallest block holding both buttons is only
#    the button row, whose "title" would be "View job >>".
#  - the CARD: the biggest block that still holds only this one "View" button. It is what gets the tag.
TAG_JS = """() => {
  const ACTION = /^\\s*(view|not interested)/i;
  const lines = (el) => el.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
  const isView = (b) => /^\\s*view/i.test(b.innerText);
  const views = [...document.querySelectorAll('button, a')].filter(isView);
  const out = [];
  for (const v of views) {
    let head = v;
    while (head.parentElement && !(/not interested/i.test(head.innerText) && lines(head).some(l => !ACTION.test(l)))) head = head.parentElement;
    if (head === document.body || head === document.documentElement) continue;
    let card = head;
    while (card.parentElement && card.parentElement !== document.body
           && [...card.parentElement.querySelectorAll('button, a')].filter(isView).length === 1) card = card.parentElement;
    const words = lines(head).filter(l => !ACTION.test(l));
    const id = (words[0] + '-' + (words[1] || '')).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 80);
    card.setAttribute('data-ja-id', id);
    out.push({id, name: words[0]});
  }
  return out;
}"""

# The overlay "View job" opens: the nearest fixed-position block around the visible Apply button.
APPLY_MODAL_JS = """() => {
  const apply = [...document.querySelectorAll('button')].find(b => /^\\s*apply\\s*$/i.test(b.textContent) && b.offsetParent !== null);
  if (!apply) return false;
  let el = apply;
  while (el && el !== document.body && getComputedStyle(el).position !== 'fixed') el = el.parentElement;
  if (!el || el === document.body) return false;
  el.setAttribute('data-ja-modal', '1');
  return true;
}"""
MODAL = "[data-ja-modal]"


def split_name(name: str) -> Tuple[str, str]:
    """Instahyre heads a card "Company - Role": (company, role). Without the dash it is all role."""
    company, dash, role = name.partition(" - ")
    return (company.strip(), role.strip()) if dash and role.strip() else ("", name.strip())


class InstahyreAdapter(Adapter):
    name = "instahyre"
    logged_out_markers = ("a:text-is('Login')", "button:text-is('Login')")

    def is_logged_in(self) -> bool:
        try:
            self.goto("https://www.instahyre.com/")
        except NotLoggedIn:
            return False
        return "/candidate/" in self.active.url

    def queries(self) -> Iterator[str]:
        yield OPPORTUNITIES
        yield SEARCH_OTHER.format(years=int(round(self.profile.total_experience_years)))

    def suggested_queries(self) -> Iterator[str]:
        yield OPPORTUNITIES

    def check_setup(self) -> None:
        """Raise SetupIncomplete if the setup wizard is showing where the opportunities should be."""
        text = self.body_text(20_000).lower()
        if all(step in text for step in SETUP_STEPS) and "not interested" not in text:  # real cards always say that
            raise SetupIncomplete(SETUP_MESSAGE)

    def discover(self, query: str) -> Iterator[JobCard]:
        self.goto(query)
        self.check_setup()
        seen = set()
        for _ in range(MAX_SCROLLS):
            for item in self.active.evaluate(TAG_JS):
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                company, title = split_name(item["name"])
                yield JobCard(self.name, f"{query}#{item['id']}", title, company)
            self.active.mouse.wheel(0, 2500)
            self.settle(1, 2)

    def read_job(self, card: JobCard) -> Job:
        source, card_id = card.url.split("#", 1)  # the query page the card was found on
        self.goto(source)
        box = self._find_card(card_id)
        if box is None:
            raise RuntimeError("opportunity no longer listed (decided elsewhere?)")
        box.locator("button, a").filter(has_text=VIEW).first.click()  # not get_by_text: "Overview" in a blurb would match
        self.settle()
        return Job.from_card(card, description=self._open_modal().inner_text()[:8000])  # Instahyre shows no salary

    def _open_modal(self):
        """The overlay that "View job" opens: the whole description, and the real Apply button."""
        for _ in range(10):
            if self.active.evaluate(APPLY_MODAL_JS):
                return self.active.locator(MODAL).first
            self.settle(0.5, 1)
        raise RuntimeError("the job's details did not open after pressing View")

    def _find_card(self, card_id: str):
        """Scroll the infinite list until the tagged card shows up."""
        for _ in range(MAX_SCROLLS):
            self.active.evaluate(TAG_JS)
            box = self.active.locator(f'[data-ja-id="{card_id}"]').first
            if box.count():
                return box
            self.active.mouse.wheel(0, 2500)
            self.settle(0.8, 1.5)
        return None

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        modal = self.active.locator(MODAL).first  # opened by read_job, which always runs just before this
        button = first_visible(modal, [SEL["apply"]])  # the exact text "Apply": never its neighbour "Not interested"
        if button is None:
            raise RuntimeError("Apply button not found in the job's details")
        if dry_run:
            return Result(Status.DRY_RUN_OK, "apply button present")
        button.click()
        self.settle(1.5, 2.5)
        self.check_challenge()
        if first_visible(modal, [SEL["apply"]]) is not None:  # still there: click did not register
            raise RuntimeError("Apply click did not register")
        return Result(Status.APPLIED, "Apply was pressed and its button went away (Instahyre shows no other confirmation)")
