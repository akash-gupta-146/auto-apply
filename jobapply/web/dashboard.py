"""What the Profile tab's dashboard shows: every job each site has been through, sorted into a few plain groups, and the list of
jobs behind each number.

No HTTP and no HTML in here. The counts come from the jobs table (already read for the rest of the panel); this only decides which
group each job status belongs to, so a status added later cannot quietly vanish from the totals (a test checks every one is placed).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Tuple

from ..models import Status

GROUPS = ("submitted", "rehearsed", "skipped", "errors", "waiting")  # the order the dashboard shows them in
LABELS = {  # what each group is called on screen, and what is in it
    "submitted": ("Submitted", "Applications that were sent."),
    "rehearsed": ("Rehearsed", "Rehearsals that filled the form in and stopped before sending: nothing was sent."),
    "skipped": ("Skipped", "Jobs turned away: not a match, no way to apply, already applied to, or stopped by a check."),
    "errors": ("Errors", "Jobs where something went wrong. They are tried again on the next run."),
    "waiting": ("Waiting", "Found but not looked at yet, or waiting for your answer."),
}
PLACED: Dict[str, Tuple[str, str]] = {  # job status -> (its group, what a list calls it)
    Status.APPLIED.value: ("submitted", "Sent"),
    Status.DRY_RUN_OK.value: ("rehearsed", "Would send"),  # filled in and stopped before the final button: nothing was sent
    Status.SKIPPED_MATCH.value: ("skipped", "Not a match"),
    Status.SKIPPED_EXTERNAL.value: ("skipped", "Applies elsewhere"),
    Status.SKIPPED_DUPLICATE.value: ("skipped", "Already applied"),
    Status.SKIPPED_CHALLENGE.value: ("skipped", "Stopped by a check"),
    Status.FAILED.value: ("errors", "Error"),
    Status.NEW.value: ("waiting", "Not looked at yet"),
    Status.NEEDS_ANSWER.value: ("waiting", "Needs your answer"),
}
BY_STATUS: Dict[str, str] = {status: group for status, (group, _) in PLACED.items()}
DAY_CHOICES = (0, 1, 7, 30)  # a list can be narrowed to: any time, today, the last week, the last month
TEXT_LIMIT = 100  # the most characters of a search word that mean anything
LIST_LIMIT = 200  # a list is for looking at: the newest jobs, with a note when there are more
SAFE_LINKS = ("http://", "https://")  # a link in the list opens only a web page, whatever the database holds
_MARKS = {group: ",".join("?" * sum(1 for g in BY_STATUS.values() if g == group)) for group in GROUPS}  # fixed: never built from a request


def counts(connection: sqlite3.Connection) -> Dict[str, Dict[str, int]]:
    """{site: {job status: how many jobs}}: the numbers `summarize` puts into groups."""
    found: Dict[str, Dict[str, int]] = {}
    for portal, status, number in connection.execute("SELECT portal, status, COUNT(*) FROM jobs GROUP BY portal, status"):
        found.setdefault(portal, {})[status] = number
    return found


def summarize(counts: Mapping[str, Mapping[str, int]], portals: Mapping[str, str]) -> Dict[str, Any]:
    """`counts` is {portal: {status: number of jobs}}; `portals` is {portal: the name to show}. Every portal is listed, even with no jobs."""
    totals = dict.fromkeys(GROUPS, 0)
    rows = []
    for portal, label in portals.items():
        row = dict.fromkeys(GROUPS, 0)
        for status, number in counts.get(portal, {}).items():
            group = BY_STATUS.get(status)
            if group is not None:  # a status this program does not know is not guessed at
                row[group] += number
        for group in GROUPS:
            totals[group] += row[group]
        rows.append({"id": portal, "label": label, **row, "total": sum(row.values())})
    return {"groups": [{"id": group, "label": LABELS[group][0], "about": LABELS[group][1]} for group in GROUPS],
            "portals": rows, "totals": {**totals, "total": sum(totals.values())}}



def check(group: str, site: str, sites: Mapping[str, str]) -> None:
    if group not in GROUPS:
        raise ValueError("That is not one of the groups on the dashboard.")
    if site and site not in sites:
        raise ValueError("That is not one of the sites.")


def packed(group: str, site: str, total: int, jobs: List[Dict[str, str]]) -> Dict[str, Any]:
    return {"group": group, "site": site, "label": LABELS[group][0], "total": total, "limit": LIST_LIMIT, "jobs": jobs}


def listing(connection: sqlite3.Connection, group: str, site: str, sites: Mapping[str, str]) -> Dict[str, Any]:
    """The jobs behind one number: the newest first. `group` and `site` have been through `check`; `site` \"\" means every site."""
    where = f"status IN ({_MARKS[group]})" + (" AND portal = ?" if site else "")
    arguments = [*_statuses(group), *([site] if site else [])]
    total = connection.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", arguments).fetchone()[0]
    rows = connection.execute(
        f"SELECT portal, url, title, company, location, status, reason, updated_at FROM jobs WHERE {where}"
        " ORDER BY updated_at DESC, rowid DESC LIMIT ?", [*arguments, LIST_LIMIT]).fetchall()
    return packed(group, site, total, _jobs(rows, sites))


def _jobs(rows: List[Tuple], sites: Mapping[str, str]) -> List[Dict[str, str]]:
    """Rows of (portal, url, title, company, location, status, reason, updated_at) as what a list shows: text, and a link only to a web page."""
    return [{"portal": portal, "site": sites.get(portal, portal), "title": title or "", "company": company or "", "location": location or "",
             "result": PLACED.get(status, ("", status))[1], "reason": reason or "", "when": when or "",
             "url": url if url and url.startswith(SAFE_LINKS) else ""}
            for portal, url, title, company, location, status, reason, when in rows]


def _statuses(group: str) -> List[str]:
    return [status for status, placed in BY_STATUS.items() if placed == group]


def check_filters(group: str, text: str, days: int) -> None:
    if group and group not in GROUPS:
        raise ValueError("That is not one of the outcomes.")
    if days not in DAY_CHOICES:
        raise ValueError("Choose any time, today, the last 7 days or the last 30 days.")
    if len(text) > TEXT_LIMIT:
        raise ValueError(f"Search for at most {TEXT_LIMIT} characters.")


def tried(connection: sqlite3.Connection, sites: Mapping[str, str], limit: int = -1, group: str = "", text: str = "", days: int = 0) -> List[Dict[str, str]]:
    """Every job a run has acted on (all but the ones not looked at yet), the newest first; `limit` -1 is all of them. Narrowed to one outcome
    group, to jobs whose company or title holds `text`, and to the last `days` days (today is 1): all of it already through `check_filters`."""
    where, arguments = ["status != ?"], [Status.NEW.value]
    if group:
        where.append(f"status IN ({_MARKS[group]})")
        arguments += _statuses(group)
    if text.strip():  # instr, not LIKE: what is typed is words to find, so a % or _ in it means nothing special
        where.append("instr(lower(coalesce(company, '') || ' ' || coalesce(title, '')), ?) > 0")
        arguments.append(text.strip().lower())
    if days:
        where.append("substr(updated_at, 1, 10) >= ?")
        arguments.append((date.today() - timedelta(days=days - 1)).isoformat())
    return _jobs(connection.execute(
        f"SELECT portal, url, title, company, location, status, reason, updated_at FROM jobs WHERE {' AND '.join(where)}"
        " ORDER BY updated_at DESC, rowid DESC LIMIT ?", [*arguments, limit]).fetchall(), sites)
