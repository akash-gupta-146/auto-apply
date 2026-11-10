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
    """The /jobapi/v4/job/<id> object for this job: has the full description, salary, apply type."""
    job_id = job_url.split("?")[0].rstrip("/").rsplit("-", 1)[-1]

    def find(node) -> Optional[dict]:
        if isinstance(node, dict):
            if str(node.get("jobId")) == job_id and "description" in node:
                return node
            for value in node.values():
                hit = find(value)
                if hit:
                    return hit
        elif isinstance(node, list):
            for value in node:
                hit = find(value)
                if hit:
                    return hit
        return None

    for payload in payloads:
        hit = find(payload)
        if hit:
            return hit
    return None


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
    text = re.sub(r"<\s*(br|/p|/li|/div|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
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
