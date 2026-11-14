"""Is this panel still running the code that is on disk? A panel left open for days keeps what it started with: after an update its
buttons and checks are the old ones, and nothing says so. (It once ran for six days, started with a command that no longer existed.)

Only the program's own Python files count: a running server has already read those, while a page picks up the others when it reloads.
No HTTP in here, like the rest of the panel's logic: the page asks the panel, which asks this.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

PACKAGE = Path(__file__).resolve().parent.parent  # the `jobapply` folder


def fingerprint(root: Path = PACKAGE) -> str:
    """One short word for what the code looks like now: which files there are, and when and how big each was last written."""
    seen = hashlib.sha1()
    for path in sorted(root.rglob("*.py")):
        try:
            info = path.stat()
        except OSError:  # deleted between listing and looking: that is a change too, and the listing will not have it next time
            continue
        seen.update(f"{path.relative_to(root)}|{info.st_mtime_ns}|{info.st_size}\n".encode())
    return seen.hexdigest()


class Freshness:
    def __init__(self, look: Callable[[], str] = fingerprint):
        self._look = look
        self._at_start = look()

    def stale(self) -> bool:
        """True once the code on disk is no longer what this program started with. It stays true: only a restart cures it."""
        return self._look() != self._at_start
