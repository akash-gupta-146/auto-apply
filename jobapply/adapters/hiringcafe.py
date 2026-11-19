"""HiringCafe adapter: a job SEARCH engine, not an application form.

HiringCafe gathers jobs from employers' own application systems (Lever, Greenhouse, Ashby, Workday...). It has nothing to apply with of
its own, so every job is applied for on the employer's site. This adapter therefore finds and reads jobs, takes the tab to the employer's
own application address (the job page publishes it in its data, so no HiringCafe button is pressed), and hands the job to the AI agent
(`Result.elsewhere`). Once the agent has CONFIRMED a send, `applied()` records it in your HiringCafe tracker, as the site's own flow does.

Verified live (read-only): search by address, the job links on a result, the job record in the page's `__NEXT_DATA__`, and the tracker
menu's wording. Choosing "Mark Applied" has not been run on a real job, so a failure there is logged, never fatal.
"""
from __future__ import annotations

import json
import re
from typing import Iterator, List
from urllib.parse import quote, urlparse

from ..builder.job_source import html_to_text
from ..models import Job, JobCard, Result, Status
from .base import Adapter, find_salary, first_visible

SEARCH = "https://hiringcafe.com/classic?searchState="
MAX_SCROLLS = 8
DRAW_MS = 3000
SEL = {
    # The visible account button (the page keeps a hidden second copy called "Account menu"). Signed-out look not seen: if a signed-out page shows
    # it too, the only cost is that the tracker cannot be written to, which is logged and never fatal.
    "account": "button[aria-label='Account']",
    "tracker": "button:has-text('Update Job Tracker')",
}
MARK_APPLIED = "Mark Applied"

# Each result card holds one "Job Posting" link. Its title is not in the link: it is in the card around it, after the job's age ("3mo").
CARDS_JS = r"""() => [...document.querySelectorAll('a[href^="/job/"]')].map(a => {
  let card = a;
  while (card.innerText.length < 100 && card.parentElement && card.parentElement.querySelectorAll('a[href^="/job/"]').length === 1) card = card.parentElement;
  return {url: a.href.split('?')[0], lines: card.innerText.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 4)};
})"""
DATA_JS = "() => { const n = document.getElementById('__NEXT_DATA__'); return n ? n.textContent : ''; }"
AGE = re.compile(r"\d+\s?(?:mo|[smhdwy])|new|today|yesterday", re.I)


def card_from(item: dict) -> JobCard:
    lines = list(item.get("lines") or [])
    if lines and AGE.fullmatch(lines[0]):
        lines = lines[1:]
    title = lines[0] if lines else item["url"].rsplit("/", 1)[-1].rsplit("-", 1)[0].replace("-", " ")  # the address's own words, if the card says nothing
    return JobCard("hiringcafe", item["url"], title, location=lines[1] if len(lines) > 1 else "")


def read_record(raw: str) -> dict:
    """The job record the page embeds for itself, or {} when the page does not have one."""
    try:
        return json.loads(raw)["props"]["pageProps"]["job"] or {}
    except (ValueError, KeyError, TypeError):
        return {}


def employer_url(record: dict) -> str:
    """Where the employer takes applications: only a web address (a mailto: or a blank is nowhere the agent can go)."""
    url = str(record.get("apply_url") or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else ""


def job_fields(record: dict) -> dict:
    """What the page's own record says about the job: the company, the place, what is asked and paid."""
    detail, info = record.get("v5_processed_job_data") or {}, record.get("job_information") or {}
    description = html_to_text(info.get("description") or "")
    low, high, currency = detail.get("yearly_min_compensation"), detail.get("yearly_max_compensation"), detail.get("listed_compensation_currency")
    pay = f"{currency} {low:,.0f} - {high:,.0f} a year" if currency and low and high else find_salary(description)
    years = detail.get("min_industry_and_role_yoe")
    return {
        "title": info.get("title") or detail.get("core_job_title") or "", "company": detail.get("company_name") or "",
        "location": ", ".join(filter(None, [", ".join(detail.get("workplace_cities") or []), detail.get("workplace_type") or ""])),
        "description": description, "salary": pay, "experience": f"{years:g}+ Yrs" if years else "",
    }


class HiringCafeAdapter(Adapter):
    name = "hiringcafe"
    applies_elsewhere = True  # nothing here can be applied to on the site itself: the agent is always needed

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._employer, self._expired = "", False  # about the job read last: where it is applied for, and whether it is still open

    def is_logged_in(self) -> bool:
        self.goto("https://hiringcafe.com/classic")
        self.active.wait_for_timeout(DRAW_MS)  # the menu is drawn after the page loads: judging at once would call a signed-in person signed out
        return first_visible(self.active, [SEL["account"]]) is not None

    def queries(self) -> Iterator[str]:
        for role in self.criteria.target_roles or [""]:
            yield SEARCH + quote(json.dumps({"searchQuery": role}))

    def discover(self, query: str) -> Iterator[JobCard]:
        self.goto(query)
        self.active.wait_for_timeout(DRAW_MS)  # the results draw themselves after the page loads
        seen: set = set()
        for _ in range(MAX_SCROLLS):
            fresh: List[dict] = [i for i in self.active.evaluate(CARDS_JS) if i["url"] not in seen]
            for item in fresh:
                seen.add(item["url"])
                yield card_from(item)
            if not fresh:
                return
            self.active.mouse.wheel(0, 3000)
            self.settle(1.2, 2.5)

    def read_job(self, card: JobCard) -> Job:
        self.goto(card.url)
        record = read_record(self.active.evaluate(DATA_JS))
        self._employer, self._expired = employer_url(record), bool(record.get("is_expired"))
        fields = job_fields(record)
        if not fields["description"]:  # a page with no record of its own: read what it shows
            fields["description"] = self.body_text()
        return Job.from_card(card, **{key: value for key, value in fields.items() if value})

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        if self._expired:
            return Result(Status.SKIPPED_EXTERNAL, "HiringCafe lists this job as expired")
        if not self._employer:
            return Result(Status.SKIPPED_EXTERNAL, "the job page gives no employer application link")
        self.active.goto(self._employer, wait_until="domcontentloaded", timeout=45_000)  # not goto(): no HiringCafe login check on their site
        self.settle()
        self.check_challenge()
        return Result(Status.SKIPPED_EXTERNAL, f"applies on the employer's site ({urlparse(self._employer).hostname})", elsewhere=True)

    def applied(self, job: Job) -> None:
        """The agent confirmed the send: record it in the tracker, from the job's own page (never a card's overlay: it holds Hide and Flag)."""
        self.goto(job.url)
        button = first_visible(self.active, [SEL["tracker"]])
        if button is None:
            raise LookupError("no 'Update Job Tracker' button on the job page")
        button.click()
        self.active.get_by_text(MARK_APPLIED, exact=True).first.click(timeout=8000)
        self.settle(1.0, 2.0)
