"""Choose which of your resumes to attach to a job, and say why. Never edits a resume, never writes one."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import Paths, Profile
from ..resume import read_text

SUFFIXES = {".pdf", ".doc", ".docx"}
WORD = re.compile(r"[a-z][a-z0-9+#.]{2,}")


def candidates(paths: Paths, profile: Profile) -> List[Path]:
    """Every resume you have: the one in your profile, and any others you put in the resume folder."""
    found = [Path(profile.resume_path).expanduser()] if profile.resume_path else []
    if paths.resume_dir.is_dir():
        found += sorted(p for p in paths.resume_dir.iterdir() if p.suffix.lower() in SUFFIXES)
    unique: List[Path] = []
    for path in found:
        if path.is_file() and path.resolve() not in {u.resolve() for u in unique}:
            unique.append(path)
    return unique


def _overlap(job_text: str, resume_text: str) -> float:
    wanted = set(WORD.findall(job_text.lower()))
    return len(wanted & set(WORD.findall(resume_text.lower()))) / len(wanted) if wanted else 0.0


def choose(paths: Paths, profile: Profile, job_text: str) -> Tuple[Optional[Path], str]:
    """(the resume to attach, why). With one resume there is no choice; with several, the one whose words overlap the job's most."""
    options = candidates(paths, profile)
    if not options:
        return None, "no resume found"
    if len(options) == 1:
        return options[0], f"your only resume ({options[0].name})"
    scored = sorted(((_overlap(job_text, read_text(p)), p) for p in options), key=lambda item: -item[0])
    best_score, best = scored[0]
    return best, f"{best.name}: {best_score:.0%} of the job's words appear in it (best of {len(options)})"
