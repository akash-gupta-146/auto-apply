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
    status TEXT NOT NULL, reason TEXT DEFAULT '', score REAL, updated_at TEXT, checked_at TEXT,
    PRIMARY KEY (portal, url)
);
CREATE TABLE IF NOT EXISTS questions (
    norm TEXT PRIMARY KEY, raw TEXT, options TEXT, portal TEXT
);
CREATE TABLE IF NOT EXISTS llm_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS answer_use (  -- how often a run answered a question from your saved answers, by the question's normalised wording
    norm TEXT PRIMARY KEY, uses INTEGER NOT NULL, first_used TEXT, last_used TEXT
);
CREATE TABLE IF NOT EXISTS answer_ack (  -- a disagreement between a saved answer and your profile that you looked at and chose to keep
    norm TEXT PRIMARY KEY, saved TEXT NOT NULL, profile TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (  -- one row per application the AI agent worked on (see agent/history.py)
    id TEXT PRIMARY KEY, company TEXT DEFAULT '', title TEXT DEFAULT '', job_id TEXT DEFAULT '', url TEXT DEFAULT '',
    resume TEXT DEFAULT '', status TEXT NOT NULL, step TEXT DEFAULT '', confirmation TEXT DEFAULT '', reference TEXT DEFAULT '',
    errors TEXT DEFAULT '[]', missing TEXT DEFAULT '[]', answers TEXT DEFAULT '{}', started_at TEXT, applied_at TEXT, updated_at TEXT
);
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
        """A database saved by an older version lacks some columns: add them, keeping everything in it."""
        for table, column, definition in (("jobs", "experience", "TEXT DEFAULT ''"), ("questions", "context", "TEXT DEFAULT ''"), ("jobs", "checked_at", "TEXT")):
            if column not in {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
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

    def candidates(self, portal: str, statuses: Sequence[Status], untriaged: bool = False) -> List[JobCard]:
        """The jobs to work on, in the order they were found, except that ones which already failed come after the rest (a run must reach the
        jobs it has not tried before the ones that already failed it, else a job that always fails sits first, every run, and blocks them), and
        ones a triage found worth applying to come first (see triage.py). `untriaged`: only jobs no triage has looked at."""
        marks = ",".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"SELECT * FROM jobs WHERE portal = ? AND status IN ({marks}){' AND checked_at IS NULL' if untriaged else ''}"
            " ORDER BY status = ?, NOT (status = ? AND checked_at IS NOT NULL), rowid",
            [portal, *[s.value for s in statuses], Status.FAILED.value, Status.NEW.value],
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

    def mark_checked(self, card: JobCard, score: float, reason: str) -> None:
        """A triage read this job and found it worth applying to: it stays `new` (nothing has been tried), but is known good, and queues first."""
        self.conn.execute("UPDATE jobs SET score = ?, reason = ?, checked_at = ?, updated_at = ? WHERE portal = ? AND url = ?",
                          (score, reason, _now(), _now(), card.portal, card.url))
        self.conn.commit()

    def ready(self, portal: str) -> int:
        """How many jobs a triage found worth applying to and no run has tried yet."""
        return self.conn.execute("SELECT COUNT(*) FROM jobs WHERE portal = ? AND status = ? AND checked_at IS NOT NULL", (portal, Status.NEW.value)).fetchone()[0]

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
    def add_question(self, norm: str, raw: str, options: Optional[Sequence[str]], portal: str, context: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO questions (norm, raw, options, portal, context) VALUES (?, ?, ?, ?, ?)",
            (norm, raw, json.dumps(list(options)) if options else None, portal, context),
        )
        self.conn.commit()

    def pending_questions(self) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM questions ORDER BY rowid").fetchall()

    def drop_question(self, norm: str) -> None:
        self.conn.execute("DELETE FROM questions WHERE norm = ?", (norm,))
        self.conn.commit()

    # -- how saved answers are doing -----------------------------------------
    def record_answer_use(self, norm: str) -> None:
        """A run answered a question from your saved answers (once per job, whatever the number of passes over its form)."""
        now = _now()
        self.conn.execute("INSERT INTO answer_use (norm, uses, first_used, last_used) VALUES (?, 1, ?, ?)"
                          " ON CONFLICT(norm) DO UPDATE SET uses = uses + 1, last_used = ?", (norm, now, now, now))
        self.conn.commit()

    def answer_uses(self) -> Dict[str, Dict[str, object]]:
        return {row["norm"]: {"uses": row["uses"], "first": row["first_used"], "last": row["last_used"]}
                for row in self.conn.execute("SELECT * FROM answer_use")}

    def acknowledge(self, norm: str, saved: str, profile: str) -> None:
        """You looked at a saved answer that disagrees with your profile and chose to keep it as it is. Only that pair of texts counts: a change
        to either one makes the disagreement worth showing again."""
        self.conn.execute("INSERT INTO answer_ack (norm, saved, profile) VALUES (?, ?, ?)"
                          " ON CONFLICT(norm) DO UPDATE SET saved = excluded.saved, profile = excluded.profile", (norm, saved, profile))
        self.conn.commit()

    def acknowledged(self) -> Dict[str, tuple]:
        return {row["norm"]: (row["saved"], row["profile"]) for row in self.conn.execute("SELECT * FROM answer_ack")}

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
