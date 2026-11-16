"""The Auto-apply v2 tab's record as a spreadsheet file: every job a run has acted on, as CSV. No HTTP and no HTML in here.

The words in it come from job sites, and a spreadsheet runs a cell that starts with = + - or @ as a formula. So such a cell is made plain
text first: a posting can then never run anything on your computer when you open the file.
"""
from __future__ import annotations

import csv
import io
from typing import Dict, Iterable

FILENAME = "applications.csv"
BOM = "\ufeff"  # tells Excel the file is UTF-8, so names in any script show as they should
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
COLUMNS = (("when", "When"), ("site", "Site"), ("company", "Company"), ("title", "Job"), ("location", "Location"),
           ("result", "Outcome"), ("reason", "Details"), ("url", "Link"))  # keys are those of dashboard.tried()


def plain(text: str) -> str:
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def export(jobs: Iterable[Dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([heading for _, heading in COLUMNS])
    for job in jobs:
        writer.writerow([plain(job.get(key, "")) for key, _ in COLUMNS])
    return BOM + out.getvalue()
