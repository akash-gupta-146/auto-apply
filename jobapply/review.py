"""Your say before a run applies: the job it is about to apply to is shown on the panel's Auto-apply v2 tab, and the run goes on only when you
press Apply (or moves on when you press Skip). No HTTP and no HTML in here.

One plain file, data/review.json, written atomically (the panel is another process): which job is being asked about, who is asking, and your
answer once you give it. Each question has its own token, so a stale click can never decide a different job; and a question whose run has
stopped is not shown any more (the run's process id is in the file). It reuses the AI agent's pieces for the same job (see agent/hitl.py).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from .agent.hitl import APPROVE, REJECT, TIMEOUT, process_alive, wait_for
from .agent.session import _now, atomic_write
from .config import Paths
from .models import Job

__all__ = ["APPROVE", "REJECT", "TIMEOUT", "PauseSwitch", "ReviewChannel", "ReviewGate", "describe"]

LIMITS = {"title": 200, "company": 120, "location": 120, "experience": 60, "salary": 80, "why": 400}  # a page shows a few words, not a posting


def describe(job: Job, why: str) -> Dict[str, str]:
    """What you are shown about a job: the words the site gave, cut to a sensible length, and why it fits. A link only if it is a web address."""
    words = {"title": job.title, "company": job.company, "location": job.location, "experience": job.experience, "salary": job.salary, "why": why}
    shown = {key: " ".join(str(text).split())[:LIMITS[key]] for key, text in words.items()}
    shown["url"] = job.url if urlparse(job.url).scheme in ("http", "https") else ""
    return shown


class ReviewChannel:
    def __init__(self, paths: Paths):
        self.file = paths.review

    def ask(self, job: Dict[str, str]) -> str:
        """Put a job in front of you. Returns the token that its answer must carry."""
        token = secrets.token_hex(8)
        atomic_write(self.file, json.dumps({"token": token, "pid": os.getpid(), "job": job, "asked": _now(), "decision": ""}, ensure_ascii=False))
        return token

    def _read(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def pending(self) -> Optional[Dict[str, Any]]:
        """The job waiting for your answer, if a run is really waiting for it."""
        asked = self._read()
        return asked if asked and not asked.get("decision") and process_alive(asked.get("pid")) else None

    def decide(self, token: str, decision: str) -> bool:
        """Record your answer, but only for the job that was asked and only once."""
        asked = self._read()
        if not asked or asked.get("token") != token or asked.get("decision") or decision not in (APPROVE, REJECT):
            return False
        asked["decision"] = decision
        atomic_write(self.file, json.dumps(asked, ensure_ascii=False))
        return True

    def decision(self, token: str) -> str:
        asked = self._read() or {}
        return asked.get("decision", "") if asked.get("token") == token else ""

    def clear(self) -> None:
        self.file.unlink(missing_ok=True)


class PauseSwitch:
    """Pause and resume a run from the panel: a file that exists while paused. A run waits between two applications while it is there."""

    def __init__(self, paths: Paths):
        self.file = paths.pause

    def paused(self) -> bool:
        return self.file.exists()

    def set(self, paused: bool) -> None:
        if paused:
            atomic_write(self.file, json.dumps({"paused": _now()}))
        else:
            self.file.unlink(missing_ok=True)


class ReviewGate:
    """What a run calls with a job it is about to apply to: shows it to you and waits. Gives APPROVE, REJECT, or TIMEOUT (nobody answered)."""

    def __init__(self, channel: ReviewChannel, poll_s: float = 1.0, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.channel, self.poll_s, self.sleep, self.clock = channel, poll_s, sleep, clock

    def __call__(self, job: Job, why: str, patience_s: float) -> str:
        token = self.channel.ask(describe(job, why))
        try:
            return wait_for(lambda: self.channel.decision(token), patience_s, self.poll_s, self.sleep, self.clock)
        finally:
            self.channel.clear()  # whatever happened, nothing stays on the screen asking
