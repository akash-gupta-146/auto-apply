"""Naukri's job list arrives as JSON from the page's own network calls (GET /jobapi/v3/search ...).

Reading that JSON is sturdier than scraping the redesigned, class-obfuscated job cards: the page
renders them from this very data (verified live: 13 jobs per call, each with `title`, `jobId`,
`companyName`, `jdURL`). The browser makes the calls, so there are no auth tokens for us to handle.
Pure functions only, so they are unit-tested against a real (public-data) sample.
"""
from __future__ import annotations

import html
import re
from typing import List, Optional

from ..models import JobCard

THIN_DESCRIPTION_CHARS = 200  # a posting that names its role and skills takes more than this; less is worth a line in the log

BASE = "https://www.naukri.com"


def job_items(payload) -> List[dict]:
    """Every dict in the JSON that looks like a job posting (has jobId and title), at any depth."""
    found: List[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "jobId" in node and "title" in node:
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def logged_in_flag(payload) -> Optional[bool]:
    """The server's own verdict on the session, or None if the payload has none.

    Search responses call it `isLoggedIn`, job-detail responses `loggedIn` (both seen live).
    """
    if not isinstance(payload, dict):
        return None
    for key in ("isLoggedIn", "loggedIn"):
        if isinstance(payload.get(key), bool):
            return payload[key]
    return None


def job_detail(payloads: List[object], job_url: str) -> Optional[dict]:
    """The /jobapi/v4/job/<id> object for this job: has the full description, salary, apply type.

    A page's calls can hold several objects for the same job id that carry a `description` (the job itself, a preview, a card). The one with
    the most text is the job: taking the first would let a short blurb win whenever it arrived first."""
    job_id = job_url.split("?")[0].rstrip("/").rsplit("-", 1)[-1]
    found: List[dict] = []

    def find(node) -> None:
        if isinstance(node, dict):
            if str(node.get("jobId")) == job_id and "description" in node:
                found.append(node)
            for value in node.values():
                find(value)
        elif isinstance(node, list):
            for value in node:
                find(value)

    for payload in payloads:
        find(payload)
    return max(found, key=lambda node: len(plain_text(node.get("description"))), default=None)  # max keeps the first of equals


def thin_description_note(detail: Optional[dict], description: str, job_url: str) -> str:
    """When a job's description is too short to judge it by: what it was and which fields the job object does carry (their names only, never
    their values), so a short read can be explained from the log instead of guessed at. Empty when the description is long enough."""
    if len(description) >= THIN_DESCRIPTION_CHARS:
        return ""
    where = job_url.split("?")[0]
    fields = ", ".join(sorted(detail)) if detail else "none: the page's own text was used"
    return f"thin description ({len(description)} characters) for {where}; fields in the job object: {fields}"


def apply_questions(payload) -> List[str]:
    """Screening questions in a Quick-apply response (jobs[].questionnaire[].questionName).

    Verified live: for jobs with mandatory questions the apply call answers HTTP 200 with the QUESTIONS,
    not with a confirmation, and Naukri's page then never shows them in the automation browser.
    """
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    names: List[str] = []
    for job in jobs if isinstance(jobs, list) else []:
        questionnaire = job.get("questionnaire") if isinstance(job, dict) else None
        for question in questionnaire if isinstance(questionnaire, list) else []:
            if isinstance(question, dict) and question.get("questionName"):
                names.append(str(question["questionName"]).strip())
    return names


def plain_text(markup: str) -> str:
    """Job descriptions arrive as HTML: keep the line structure, drop the tags."""
    text = re.sub(r"<\s*(br|/p|/li|/div|/h\d)[^>]*>", "\n", markup if isinstance(markup, str) else "", flags=re.I)  # (not text: nothing to read)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = (re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


def salary_text(detail: dict) -> str:
    """e.g. '35-50 Lacs P.A.'; empty when the employer hides it."""
    salary = detail.get("salaryDetail") or {}
    if salary.get("hideSalary"):
        return ""
    return str(salary.get("salaryText") or salary.get("label") or "")


def _placeholder(item: dict, kind: str) -> str:
    """A search result lists its facts as placeholders: {"type": "experience", "label": "5-8 Yrs"}, and so on."""
    return next((str(p.get("label", "")) for p in item.get("placeholders") or [] if p.get("type") == kind), "")


def card_from_item(item: dict, portal: str) -> Optional[JobCard]:
    path = item.get("jdURL") or ""
    if not path:
        return None
    url = (BASE + path if path.startswith("/") else path).split("?")[0]
    company = str(item.get("companyName", "")).strip()
    return JobCard(portal, url, str(item["title"]).strip(), company, _placeholder(item, "location"),
                   _placeholder(item, "experience"))


def paged_url(query: str, page_no: int) -> str:
    """Naukri paginates search URLs with a -N suffix before the query string."""
    if page_no <= 1:
        return query
    path, sep, params = query.partition("?")
    return f"{path}-{page_no}{sep}{params}"
