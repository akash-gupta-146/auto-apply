"""Wellfound adapter.

Flow (references/wellfound.md): job page -> "Apply now" -> modal with screening questions
and custom-styled radios -> "Send application".

!! Selectors are UNVERIFIED; see jobapply probe wellfound.
"""
from __future__ import annotations

import re
from typing import Iterator

from ..models import Job, JobCard, NotLoggedIn, Result, Status
from .base import Adapter, find_salary, first_visible, slug
from .forms import fill_form, let_person_answer

MAX_SCROLLS = 8

SEL = {
    "apply": "button:has-text('Apply now'), a:has-text('Apply now')",
    "external": "a:has-text('Apply on company website'), a:has-text('Apply on company site')",
    "dialog": "[role='dialog']",
    "send": "button:has-text('Send application'), button:has-text('Submit application')",
}

LINK_JS = """() => [...document.querySelectorAll('a[href*="/jobs/"]')]
  .filter(a => /\\/jobs\\/\\d+/.test(a.href))
  .map(a => ({url: a.href.split('?')[0], title: a.innerText.trim()}))
  .filter(x => x.title)"""


class WellfoundAdapter(Adapter):
    name = "wellfound"
    logged_out_markers = ("a:has-text('Log In')", "a:has-text('Sign Up')")

    def is_logged_in(self) -> bool:
        try:
            self.goto("https://wellfound.com/jobs")
        except NotLoggedIn:
            return False
        return True

    def queries(self) -> Iterator[str]:
        for role in self.criteria.target_roles or [""]:
            for location in self.criteria.locations or [""]:
                if role and location:
                    yield f"https://wellfound.com/role/l/{slug(role)}/{slug(location)}"
                else:
                    yield f"https://wellfound.com/role/{slug(role)}" if role else "https://wellfound.com/jobs"

    def discover(self, query: str) -> Iterator[JobCard]:
        self.goto(query)
        seen = set()
        for _ in range(MAX_SCROLLS):
            fresh = [i for i in self.active.evaluate(LINK_JS) if i["url"] not in seen]
            for item in fresh:
                seen.add(item["url"])
                yield JobCard(self.name, item["url"], item["title"])
            self.active.mouse.wheel(0, 3000)
            self.settle(1.2, 2.5)
            if not fresh:
                return

    def read_job(self, card: JobCard) -> Job:
        self.goto(card.url)
        text = self.body_text()
        company = card.company
        title_match = re.search(r" at (.+?)(?: \||$| - )", self.active.title())
        if not company and title_match:
            company = title_match.group(1).strip()
        return Job.from_card(
            card, company=company, description=text, salary=find_salary(text)
        )

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        button = first_visible(self.active, [SEL["apply"]])
        if button is None:
            if first_visible(self.active, [SEL["external"]]) is not None:
                return Result(Status.SKIPPED_EXTERNAL, "applies on the company site")
            raise RuntimeError("Apply now button not found")
        button.click()
        dialog = self.active.locator(SEL["dialog"]).first
        dialog.wait_for(state="visible", timeout=10_000)
        fill_form(dialog, resolver)
        let_person_answer(self.active, resolver, lambda: fill_form(dialog, resolver))  # you may answer what it could not, here
        if dry_run:
            self.active.keyboard.press("Escape")
            resolver.require_complete()
            return Result(Status.DRY_RUN_OK, "form fully answerable")
        resolver.require_complete()
        send = first_visible(dialog, [SEL["send"]])
        if send is None:
            raise RuntimeError("Send application button not found")
        send.click()
        self.settle(1.5, 3)
        self.check_challenge()
        if dialog.is_visible():
            raise RuntimeError("modal still open after Send: a required field is probably empty")
        return Result(Status.APPLIED, "Send was pressed and the application window closed")
