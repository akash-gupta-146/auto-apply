"""The agent's memory of one application: the job, what is done, what is missing, and what happened. Saved after every change.

Because it is on disk, a page reload, a closed tab or a stopped run loses nothing: `jobapply agent --resume-session` picks it up and the
agent knows which job this is, which steps are done and whether Submit was already pressed (it is never pressed twice).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import AppStatus, JobInfo

log = logging.getLogger("jobapply")
MAX_FILLED = 200  # fields remembered: enough for any form, never unbounded


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write(path: Path, text: str) -> None:
    """The panel reads these files while the agent writes them: a reader sees the old file or the new one, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)


@dataclass
class Session:
    id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4])
    job: JobInfo = field(default_factory=JobInfo)
    status: AppStatus = AppStatus.IN_PROGRESS
    step: str = ""  # what the page is asking now: "Application form", "Screening questions"...
    completed: List[str] = field(default_factory=list)  # steps already done, in order
    filled: Dict[str, str] = field(default_factory=dict)  # field -> what went in
    clicked: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)  # what only you can supply, right now
    answers: Dict[str, str] = field(default_factory=dict)  # what you told the agent during this application
    urls: List[str] = field(default_factory=list)  # every address the application passed through, so a redirect keeps its context
    resume: str = ""
    confirmation: str = ""  # the words the site used to say it was sent
    reference: str = ""
    errors: List[str] = field(default_factory=list)
    submit_pressed: bool = False  # never pressed a second time: that is how duplicates are made
    started_at: str = field(default_factory=_now)
    applied_at: str = ""
    path: Optional[Path] = field(default=None, repr=False, compare=False)

    # -- remembering ----------------------------------------------------------------------------------------------
    def say(self, text: str) -> None:
        """One line of the live activity feed: written to the run log (which the panel shows) and kept with the session."""
        log.info("agent: %s", text)
        if self.path is not None:
            with self.path.with_suffix(".feed").open("a", encoding="utf-8") as feed:
                feed.write(json.dumps({"at": _now(), "text": text}, ensure_ascii=False) + "\n")

    def visit(self, url: str) -> None:
        if url and url not in self.urls[-1:]:
            self.urls.append(url)

    def complete(self, step: str) -> None:
        if step and step not in self.completed:
            self.completed.append(step)

    def filled_in(self, label: str, value: str) -> None:
        if len(self.filled) < MAX_FILLED:
            self.filled[label[:80]] = value[:120]

    def finish(self, status: AppStatus, **details: str) -> None:
        self.status = status
        for name, value in details.items():
            setattr(self, name, value)
        if status is AppStatus.SUBMITTED and not self.applied_at:
            self.applied_at = _now()

    # -- on disk -------------------------------------------------------------------------------------------------
    def save(self) -> None:
        if self.path is not None:
            data = dataclasses.asdict(self)
            data.pop("path")
            atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=1, default=str))

    @classmethod
    def create(cls, directory: Path, job: Optional[JobInfo] = None) -> "Session":
        session = cls(job=job or JobInfo())
        session.path = directory / "sessions" / f"{session.id}.json"
        session.save()
        return session

    @classmethod
    def load(cls, directory: Path, session_id: str) -> "Session":
        path = directory / "sessions" / f"{session_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["job"] = JobInfo(**data["job"])
        data["status"] = AppStatus(data["status"])
        known = {f.name for f in dataclasses.fields(cls)}
        session = cls(**{k: v for k, v in data.items() if k in known})
        session.path = path
        return session

    @classmethod
    def latest_open(cls, directory: Path) -> Optional["Session"]:
        """The newest application that can still be picked up."""
        files = sorted((directory / "sessions").glob("*.json"), reverse=True)
        for path in files:
            try:
                session = cls.load(directory, path.stem)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if session.status.open:
                return session
        return None

    def feed(self, last: int = 40) -> List[Dict[str, str]]:
        path = self.path.with_suffix(".feed") if self.path else None
        if path is None or not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-last:]
        return [json.loads(line) for line in lines if line.strip()]
