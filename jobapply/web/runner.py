"""Runs one program at a time for the panel, keeps what it prints, and can stop it politely.

Stopping is the same as pressing Ctrl+C in a terminal: the program notices, finishes the page it is on and
writes its report. Only if it ignores that for `grace_s` seconds is it killed.
"""
from __future__ import annotations

import itertools
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from typing import Deque, Dict, List, Mapping, Optional

MAX_LINES = 3000
MAX_LINE_CHARS = 2000
STOP_GRACE_S = 20

IDLE, RUNNING, STOPPING, FINISHED, FAILED, STOPPED = "idle", "running", "stopping", "finished", "failed", "stopped"
BUSY_STATES = (RUNNING, STOPPING)


class Busy(RuntimeError):
    """Something is already running."""


class JobRunner:
    def __init__(self, grace_s: float = STOP_GRACE_S):
        self.grace_s = grace_s
        self.run_id, self.state, self.label, self.exit_code = 0, IDLE, "", None
        self._lock = threading.Lock()
        self._lines: Deque[str] = deque()
        self._first = 0  # position, within this run's output, of the oldest line still kept
        self._proc: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._done = threading.Event()
        self._done.set()

    # -- starting ------------------------------------------------------------------------------
    def start(self, label: str, argv: List[str], env: Optional[Mapping[str, str]] = None, cwd: Optional[str] = None,
              banner: str = "") -> None:
        with self._lock:
            self._refuse_if_busy()
            self.run_id += 1
            self.label, self.exit_code, self._stop_requested = label, None, False
            self._lines.clear()
            self._first = 0
            self._done.clear()
            if banner:
                self._add(banner)
            try:
                self._proc = self._spawn(argv, env, cwd)
            except OSError as exc:  # the program itself is missing: say so in the log, do not crash the panel
                self._proc, self.state, self.exit_code = None, FAILED, -1
                self._add(f"Could not start: {exc}")
                self._done.set()
                return
            self.state = RUNNING
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()

    def ensure_idle(self) -> None:
        """Say so now, before any other checking, if something is already running."""
        with self._lock:
            self._refuse_if_busy()

    def _refuse_if_busy(self) -> None:  # caller holds the lock
        if self.state in BUSY_STATES:
            raise Busy(f"{self.label} is still running.")

    @staticmethod
    def _spawn(argv: List[str], env: Optional[Mapping[str, str]], cwd: Optional[str]) -> subprocess.Popen:
        options: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1, env=dict(env) if env else None, cwd=cwd)
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # lets Ctrl+Break reach only this program
        else:
            options["start_new_session"] = True  # its own group: a hard kill can take its helpers with it
        return subprocess.Popen(argv, **options)

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            with self._lock:
                self._add(line.rstrip("\r\n"))
        code = proc.wait()
        with self._lock:
            self.exit_code = code
            self.state = STOPPED if self._stop_requested else (FINISHED if code == 0 else FAILED)
        self._done.set()

    def _add(self, line: str) -> None:  # caller holds the lock
        if len(self._lines) >= MAX_LINES:
            self._lines.popleft()
            self._first += 1
        self._lines.append(line[:MAX_LINE_CHARS])

    # -- stopping ------------------------------------------------------------------------------
    def stop(self) -> bool:
        """Ask the running program to finish. False when nothing is running."""
        with self._lock:
            proc = self._proc
            if self.state != RUNNING or proc is None:
                return False
            self._stop_requested, self.state = True, STOPPING
        self._interrupt(proc)
        timer = threading.Timer(self.grace_s, self._kill_if_alive, args=(proc,))
        timer.daemon = True
        timer.start()
        return True

    @staticmethod
    def _interrupt(proc: subprocess.Popen) -> None:
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass  # it has just finished by itself

    def _kill_if_alive(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        with self._lock:
            self._add("It did not stop in time, so it was ended.")
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    def shutdown(self) -> None:
        """For when the panel itself closes: do not leave a run going with nobody watching."""
        if self.stop():
            self.wait(self.grace_s + 5)

    # -- looking -------------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.state in BUSY_STATES

    def forget_output(self) -> None:
        """Drop the output of the last run (it names jobs and companies). Does nothing while a run is going."""
        with self._lock:
            if not self.busy:
                self._first += len(self._lines)  # positions never go backwards, so a page that asks again simply gets nothing
                self._lines.clear()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._done.wait(timeout)

    def snapshot(self, since: int = 0) -> Dict[str, object]:
        """The state plus the output lines from position `since`. `next` is what to ask for next time."""
        with self._lock:
            start = max(since, self._first)
            lines = list(itertools.islice(self._lines, start - self._first, None))
            return {"run_id": self.run_id, "state": self.state, "label": self.label, "exit_code": self.exit_code,
                    "lines": lines, "next": self._first + len(self._lines), "dropped": since < self._first}
