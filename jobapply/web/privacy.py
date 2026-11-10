"""Deleting what this program keeps about you.

All of it lives in the data folder, and nothing outside it is ever touched. Each kind below is a short, fixed list of
things directly inside that folder: nothing a person (or a web page) types can choose a path. A link is removed, never
followed. A kind that cannot be removed (a file still in use) is reported, not hidden.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

import yaml

from ..config import Paths, load_profile, save_profile
from .actions import PORTALS

DAMAGED = (OSError, ValueError, TypeError, yaml.YAMLError)  # a damaged profile must not stop a deletion


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    what: str  # in words a person can check against what they expect to lose
    targets: Callable[[Paths], Sequence[Path]]


def _database(paths: Paths) -> List[Path]:
    """The job database and the side files SQLite keeps next to it."""
    return [paths.db, *(paths.db.with_name(paths.db.name + suffix) for suffix in ("-wal", "-shm", "-journal"))]


KINDS = (
    Kind("details", "Your details and job preferences",
         "name, email, phone, saved answers, job titles, locations and salary",
         lambda p: (p.profile, p.criteria, p.answers, p.aliases)),
    Kind("documents", "Your resume and extra documents",
         "the copy of your resume and the documents you added for the AI helper",
         lambda p: (p.resume_dir, p.about)),
    Kind("ai", "AI helper key and its logs",
         "the keys (the main AI's and any backups'), the AIs you added, the settings, and the record of what the AI was asked",
         lambda p: (p.ai, p.ai_log, p.ai_fit_log, p.prompt_log, p.facts_log)),
    Kind("login", f"Your saved site logins ({', '.join(PORTALS.values())})",
         "the browser session this program keeps, so you will have to log in again",
         lambda p: (p.browser_profile,)),
    Kind("history", "Jobs seen, applications and reports",
         "every job it has seen, what it did with each one, and all reports",
         lambda p: (*_database(p), p.reports)),
    Kind("logs", "Logs and screenshots of problems",
         "the run log and the pictures taken when a page did not look right",
         lambda p: (p.run_log, p.failures)),
)
BY_ID = {kind.id: kind for kind in KINDS}


def _exists(path: Path) -> bool:
    return path.is_symlink() or path.exists()  # a broken link is still something that is there


def _has_content(path: Path) -> bool:
    if path.is_dir() and not path.is_symlink():
        return any(path.iterdir())  # the program keeps empty reports/ and failures/ folders: that is not "something saved"
    return _exists(path)


def present(paths: Paths, kind: Kind) -> bool:
    return any(_has_content(target) for target in kind.targets(paths))


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()  # for a link this removes the link itself, never what it points at
    elif path.is_dir():
        shutil.rmtree(path)


def _forget_resume(paths: Paths) -> None:
    """The profile stays, but must no longer point at a resume that is gone."""
    if not paths.profile.exists():
        return
    try:
        profile = load_profile(paths)
        profile.resume_path = profile.resume_hash = ""
        save_profile(profile, paths)
    except DAMAGED:
        pass


def erase(paths: Paths, kind_ids: Sequence[str]) -> Tuple[List[str], Dict[str, str]]:
    """Delete these kinds. Returns (the ones deleted, {the ones that could not be: why}). One failing does not stop the rest."""
    deleted: List[str] = []
    failed: Dict[str, str] = {}
    for kind in (kind for kind in KINDS if kind.id in kind_ids):
        try:
            for target in kind.targets(paths):
                if _exists(target):
                    _remove(target)
        except OSError as exc:
            failed[kind.id] = exc.strerror or str(exc)
            continue
        deleted.append(kind.id)
        if kind.id == "documents":
            _forget_resume(paths)
    paths.ensure()  # the folders the program expects to find are put back, empty
    return deleted, failed
