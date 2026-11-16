"""What the Auto-apply v2 tab shows and does: the job a run is asking you about, how much of today's limit is used, and what happened lately.

Read without disturbing a run (it may be writing the same files and database). No HTTP and no HTML in here.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Dict, Mapping

from ..config import Criteria, Paths, load_criteria, save_criteria
from ..db import sent_today_counts
from ..review import PauseSwitch, ReviewChannel
from . import dashboard, tracker

MAX_DAILY_CAP = 200
ReadDb = Callable[[Callable[..., Any], Any], Any]  # Panel._read_db: runs a read on the jobs file, or gives the default when it cannot


def live(paths: Paths, criteria: Criteria, read_db: ReadDb, sites: Mapping[str, str]) -> Dict[str, Any]:
    """What the tab draws on every look: kept small, because it is read while a run works."""
    asked = ReviewChannel(paths).pending()
    return {
        "review": {"token": asked["token"], "job": asked["job"]} if asked else None,
        "cap": criteria.daily_cap,
        "sent": read_db(sent_today_counts, {}),
        "paused": PauseSwitch(paths).paused(),
    }


def pause(paths: Paths, paused: bool) -> None:
    PauseSwitch(paths).set(paused)


def narrowed(group: object, text: object, days: object) -> Dict[str, Any]:
    """The tracker's filters as they arrive in a request (all text), checked. Raises ValueError, in words for the person, when one is off."""
    try:
        number = int(str(days or 0))
    except ValueError:
        raise ValueError("Choose any time, today, the last 7 days or the last 30 days.") from None
    found = {"group": str(group or ""), "text": str(text or ""), "days": number}
    dashboard.check_filters(**found)
    return found


def history(read_db: ReadDb, sites: Mapping[str, str], **filters: Any) -> Dict[str, Any]:
    """What the tracker table shows: the newest jobs a run acted on that fit the filters, and whether there are more than are shown."""
    jobs = read_db(lambda connection: dashboard.tried(connection, sites, dashboard.LIST_LIMIT + 1, **filters), [])
    return {"jobs": jobs[:dashboard.LIST_LIMIT], "more": len(jobs) > dashboard.LIST_LIMIT}


def decide(paths: Paths, token: str, decision: str) -> bool:
    """Your answer to 'apply to this one?'. Only counts for the job that asked."""
    return ReviewChannel(paths).decide(token, decision)


def set_cap(paths: Paths, value: object) -> int:
    """Save a new daily limit (it applies from the next run). Raises ValueError, in words for the person, when it is not a sensible number."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("The daily limit must be a whole number.")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValueError("The daily limit must be a whole number.") from None
    if not 1 <= number <= MAX_DAILY_CAP:
        raise ValueError(f"The daily limit must be between 1 and {MAX_DAILY_CAP}.")
    save_criteria(dataclasses.replace(load_criteria(paths), daily_cap=number), paths)
    return number


def export(read_db: ReadDb, sites: Mapping[str, str], **filters: Any) -> str:
    """The jobs the tracker table shows, but all of them (not only the newest), as the text of a CSV file."""
    return tracker.export(read_db(lambda connection: dashboard.tried(connection, sites, **filters), []))
