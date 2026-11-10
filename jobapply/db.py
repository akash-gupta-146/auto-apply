"""SQLite state: job queue, unanswered questions, LLM request budget."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .models import JobCard, Result, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    portal TEXT NOT NULL, url TEXT NOT NULL, title TEXT, company TEXT, location TEXT, experience TEXT DEFAULT '',
    status TEXT NOT NULL, reason TEXT DEFAULT '', score REAL, updated_at TEXT,
    PRIMARY KEY (portal, url)
);
CREATE TABLE IF NOT EXISTS questions (
    norm TEXT PRIMARY KEY, raw TEXT, options TEXT, portal TEXT
);
CREATE TABLE IF NOT EXISTS llm_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path) if isinstance(path, Path) else path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """A job list saved by an older version has no experience column: add it, keeping every job in it."""
        if "experience" not in {row["name"] for row in self.conn.execute("PRAGMA table_info(jobs)")}:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN experience TEXT DEFAULT ''")
            self.conn.commit()

    # -- jobs ---------------------------------------------------------------
    def upsert_job(self, card: JobCard) -> bool:
        """Insert if unseen. Returns True when the job is new. A job seen before gets the experience it lacked."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO jobs (portal, url, title, company, location, experience, status, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (card.portal, card.url, card.title, card.company, card.location, card.experience, Status.NEW.value, _now()),
        )
        if cur.rowcount == 0 and card.experience:
            self.conn.execute(
                "UPDATE jobs SET experience = ? WHERE portal = ? AND url = ? AND COALESCE(experience, '') = ''",
                (card.experience, card.portal, card.url),
            )
        self.conn.commit()
        return cur.rowcount == 1

    def candidates(self, portal: str, statuses: Sequence[Status]) -> List[JobCard]:
        marks = ",".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"SELECT * FROM jobs WHERE portal = ? AND status IN ({marks}) ORDER BY rowid",
            [portal, *[s.value for s in statuses]],
        ).fetchall()
        return [JobCard(r["portal"], r["url"], r["title"], r["company"], r["location"], r["experience"] or "")
                for r in rows]

    def set_status(self, card: JobCard, result: Result) -> None:
        self.conn.execute(
            "UPDATE jobs SET status = ?, reason = ?, score = COALESCE(?, score), updated_at = ?"
            " WHERE portal = ? AND url = ?",
            (result.status.value, result.reason, result.score, _now(), card.portal, card.url),
        )
        self.conn.commit()

    def counts(self, portal: Optional[str] = None) -> Dict[str, Dict[str, int]]:
        sql = "SELECT portal, status, COUNT(*) AS n FROM jobs"
        args: list = []
        if portal:
            sql += " WHERE portal = ?"
            args.append(portal)
        sql += " GROUP BY portal, status"
        out: Dict[str, Dict[str, int]] = {}
        for row in self.conn.execute(sql, args):
            out.setdefault(row["portal"], {})[row["status"]] = row["n"]
        return out

    # -- questions ----------------------------------------------------------
    def add_question(self, norm: str, raw: str, options: Optional[Sequence[str]], portal: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO questions (norm, raw, options, portal) VALUES (?, ?, ?, ?)",
            (norm, raw, json.dumps(list(options)) if options else None, portal),
        )
        self.conn.commit()

    def pending_questions(self) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM questions ORDER BY rowid").fetchall()

    def drop_question(self, norm: str) -> None:
        self.conn.execute("DELETE FROM questions WHERE norm = ?", (norm,))
        self.conn.commit()

    # -- LLM budget ---------------------------------------------------------
    def llm_calls_today(self) -> int:
        row = self.conn.execute(
            "SELECT calls FROM llm_usage WHERE day = ?", (date.today().isoformat(),)
        ).fetchone()
        return row["calls"] if row else 0

    def record_llm_call(self) -> None:
        self.conn.execute(
            "INSERT INTO llm_usage (day, calls) VALUES (?, 1)"
            " ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
            (date.today().isoformat(),),
        )
        self.conn.commit()
