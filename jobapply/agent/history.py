"""Every application the agent worked on, and what became of it: the dashboard's data.

One row per session, updated as the application moves on. A row is a summary (the full record is the session file), so the
dashboard is quick and survives a deleted session file.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..db import Database
from .models import AppStatus
from .session import Session, _now

COLUMNS = ("id", "company", "title", "job_id", "url", "resume", "status", "step", "confirmation", "reference", "errors", "missing",
           "answers", "started_at", "applied_at")


def record(db: Database, session: Session) -> None:
    job = session.job
    values = {
        "id": session.id, "company": job.company, "title": job.title, "job_id": job.job_id, "url": job.url or (session.urls[-1:] or [""])[0],
        "resume": session.resume, "status": session.status.value, "step": session.step, "confirmation": session.confirmation,
        "reference": session.reference, "errors": json.dumps(session.errors), "missing": json.dumps(session.missing),
        "answers": json.dumps(session.answers), "started_at": session.started_at, "applied_at": session.applied_at,
    }
    db.conn.execute(
        f"INSERT INTO applications ({', '.join(COLUMNS)}, updated_at) VALUES ({', '.join('?' for _ in COLUMNS)}, ?)"
        f" ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in COLUMNS[1:])}, updated_at = excluded.updated_at",
        [values[c] for c in COLUMNS] + [_now()])
    db.conn.commit()


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for name in ("errors", "missing"):
        data[name] = json.loads(data[name] or "[]")
    data["answers"] = json.loads(data["answers"] or "{}")
    data["status_label"] = AppStatus(data["status"]).label
    return data


Source = Union[Database, sqlite3.Connection]


def read_only(path: Path) -> Optional[sqlite3.Connection]:
    """A look at the history that cannot disturb an agent that is writing it (the panel's way in). None if there is none yet."""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM applications LIMIT 1")  # an older database has no such table yet
        return conn
    except sqlite3.Error:
        return None


def recent(source: Source, limit: int = 50) -> List[Dict[str, Any]]:
    conn = getattr(source, "conn", source)
    return [_row(r) for r in conn.execute("SELECT * FROM applications ORDER BY updated_at DESC, rowid DESC LIMIT ?", (limit,))]


def totals(source: Source) -> Dict[str, int]:
    """The dashboard's numbers: how many in total, sent, failed, in progress, and waiting for you."""
    conn = getattr(source, "conn", source)
    counts = {row["status"]: row["n"] for row in conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status")}
    sent = counts.get(AppStatus.SUBMITTED.value, 0)
    failed = counts.get(AppStatus.FAILED.value, 0)
    waiting = counts.get(AppStatus.REQUIRES_USER.value, 0)
    progress = counts.get(AppStatus.IN_PROGRESS.value, 0) + counts.get(AppStatus.READY.value, 0) + counts.get(AppStatus.INCOMPLETE.value, 0)
    return {"total": sum(counts.values()), "submitted": sent, "failed": failed, "in_progress": progress, "needs_you": waiting,
            "unconfirmed": counts.get(AppStatus.VERIFICATION_PENDING.value, 0)}
