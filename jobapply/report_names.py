"""The names run reports are saved under, and what to call them on screen.

One place knows the format, so the code that writes a report and the code that lists it cannot drift apart.
"""
from __future__ import annotations

import re
from datetime import datetime

NAME = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{6})-([a-z0-9]+)-(live|dry-run)\.md$")


def report_filename(started: datetime, portal: str, dry_run: bool) -> str:
    """e.g. 20261108-003000-naukri-live.md (sorts by time, so the newest is first when listed backwards)."""
    return f"{started:%Y%m%d-%H%M%S}-{portal}-{'dry-run' if dry_run else 'live'}.md"


def report_label(name: str) -> str:
    """What the panel calls a report: 11-08-26--003000--live (month-day-year, the time of the run, live or dry-run).

    A file whose name is not in the usual format (one you saved there yourself) is shown under its own name.
    """
    found = NAME.match(name)
    if not found:
        return name
    year, month, day, clock, _site, mode = found.groups()
    return f"{month}-{day}-{year[2:]}--{clock}--{mode}"


def report_portal(name: str) -> str:
    """The site a report was made for (e.g. "instahyre"), or "" for a file that is not in the usual format."""
    found = NAME.match(name)
    return found.group(5) if found else ""
