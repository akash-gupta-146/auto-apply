"""What the last ATS check of each resume said, so the list of resumes can show it without running anything again.

One small file per resume under data/resumes/checks/ (so "delete my resumes" on the privacy page takes them too). It holds the verdict and the version of the
resume that was checked, and nothing from the PDF: no text, no name. If the resume has been edited since, the answer is "out of date", never silently reused.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from ..agent.session import atomic_write
from ..config import Paths
from .doc import ID


def _file(paths: Paths, resume_id: object):
    if not isinstance(resume_id, str) or not ID.match(resume_id):
        return None
    return paths.resumes / "checks" / f"{resume_id}.json"


def save(paths: Paths, resume_id: object, version: int, verdict: Dict[str, Any], scores: Dict[str, int]) -> None:
    path = _file(paths, resume_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    note = {"key": verdict["key"], "label": verdict["label"], "version": version, "scores": scores, "at": datetime.now().isoformat(timespec="seconds")}
    atomic_write(path, json.dumps(note, indent=1))


def load(paths: Paths, resume_id: object, version: object) -> Optional[Dict[str, Any]]:
    """The last check of this resume (None if there was none, or the file is damaged), with `stale` true if the resume has changed since."""
    path = _file(paths, resume_id)
    try:
        note = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
    except (OSError, ValueError):
        return None
    if not isinstance(note, dict) or note.get("key") not in ("compatible", "mostly", "not"):
        return None
    return {"key": note["key"], "label": str(note.get("label", "")), "at": str(note.get("at", "")), "scores": note.get("scores", {}), "stale": note.get("version") != version}


def forget(paths: Paths, resume_id: object) -> None:
    path = _file(paths, resume_id)
    if path is not None:
        path.unlink(missing_ok=True)
