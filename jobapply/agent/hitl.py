"""How the agent and the panel talk: a live state file, a pause switch, and your approval before anything is sent.

Plain files in data/agent/, written atomically, so the panel (a separate process) can show the agent's state and the person can answer
without a socket or a shared memory. Nothing here knows about HTTP or HTML.
"""
from __future__ import annotations

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import Paths
from .session import Session, _now, atomic_write

APPROVE, REJECT, TIMEOUT = "approve", "reject", "timeout"
APPROVAL_STEP = "Waiting for approval"  # the step an application is left at when you did not approve it


class AgentState(str, Enum):
    IDLE = "Idle"
    ANALYZING = "Analyzing Page"
    JOB_DETECTED = "Job Detected"
    APPLYING = "Applying"
    WAITING = "Waiting for User"
    UPLOADING = "Uploading Resume"
    VERIFYING = "Verifying Submission"
    COMPLETED = "Completed"
    FAILED = "Failed"
    PAUSED = "Paused"


def process_alive(pid: object) -> bool:
    """Is the program that wrote the state file still running? (If it was killed it could not say it had stopped.)
    Never kills anything: on Windows `os.kill` would end the process, so that is asked in another way. When unsure: alive."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION: look, never touch
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
            return bool(handle)
        os.kill(pid, 0)  # signal 0 only checks that the process exists
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


class Channel:
    def __init__(self, paths: Paths):
        self.dir = paths.agent_dir
        self.state_file, self.control_file, self.approval_file = (self.dir / name for name in ("state.json", "control.json", "approval.json"))

    # -- what the agent is doing, for the panel -------------------------------------------------------------------
    def set_state(self, state: AgentState, session: Optional[Session] = None, detail: str = "", questions: Optional[List[str]] = None) -> None:
        atomic_write(self.state_file, json.dumps({
            "state": state.value, "detail": detail, "session": session.id if session else "", "job": session.job.context() if session else "",
            "questions": questions or [], "updated": _now(), "pid": os.getpid(),
        }, ensure_ascii=False))

    def read_state(self) -> Dict[str, Any]:
        return self._read(self.state_file) or {"state": AgentState.IDLE.value}

    @staticmethod
    def _read(path: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # -- pause ----------------------------------------------------------------------------------------------------
    def paused(self) -> bool:
        return bool((self._read(self.control_file) or {}).get("paused"))

    def set_paused(self, paused: bool) -> None:
        atomic_write(self.control_file, json.dumps({"paused": paused}))

    # -- approval before anything is sent -------------------------------------------------------------------------
    def ask_approval(self, session: Session, summary: List[str]) -> None:
        atomic_write(self.approval_file, json.dumps({"session": session.id, "job": session.job.context(), "url": (session.urls[-1:] or [""])[0],
                                                      "summary": summary, "asked": _now(), "decision": ""}, ensure_ascii=False))

    def pending_approval(self) -> Optional[Dict[str, Any]]:
        asked = self._read(self.approval_file)
        return asked if asked and not asked.get("decision") else None

    def decide(self, session_id: str, decision: str) -> bool:
        """Record the person's answer, but only for the application that asked: a stale click can never approve a different one."""
        asked = self._read(self.approval_file)
        if not asked or asked.get("session") != session_id or decision not in (APPROVE, REJECT):
            return False
        asked["decision"] = decision
        atomic_write(self.approval_file, json.dumps(asked, ensure_ascii=False))
        return True

    def decision(self, session_id: str) -> str:
        asked = self._read(self.approval_file) or {}
        return asked.get("decision", "") if asked.get("session") == session_id else ""

    def clear_approval(self) -> None:
        self.approval_file.unlink(missing_ok=True)


def wait_for(done: Callable[[], str], timeout_s: float, poll_s: float = 1.0, sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic) -> str:
    """Poll until `done()` says something (anything but ""), or the time is up (TIMEOUT)."""
    end = clock() + timeout_s
    while True:
        answer = done()
        if answer:
            return answer
        if clock() >= end:
            return TIMEOUT
        sleep(poll_s)
