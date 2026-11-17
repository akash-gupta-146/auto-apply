"""The ATS check for the Create Resume tab: one verdict for a resume made here (its PDF printed and read back, and what was written), and the same verdict for a
resume file you already have: the one your runs send, or any PDF or Word file you choose.

A resume made here has its last verdict remembered (builder/checkstore.py) so the list can show it. A file you choose is checked and forgotten: nothing of it is
kept. The browser gets the text a parser read from the file back, because that is what you need to see; it goes no further than your own screen.
"""
from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ..builder import ats, checkstore, filecheck, pdfcheck, verdict
from ..config import Paths, Profile
from .actions import ActionError

MAX_FILE = 8 * 1024 * 1024  # bytes of a resume file to check: a resume is a few hundred kilobytes, and anything near this is itself a finding
FILE_BODY = MAX_FILE * 4 // 3 + 64 * 1024  # what the web server lets a request carry for a file: base64 is a third bigger, plus the name


class AtsChecker:
    def __init__(self, paths: Paths, read_profile: Callable[[], Optional[Profile]], printed: Callable[[object], Tuple[Dict[str, Any], bytes]]):
        self.paths, self._profile, self._printed = paths, read_profile, printed

    def of_resume(self, resume_id: object) -> Dict[str, Any]:
        """The verdict on a saved resume, with the two reports it is made of. What was written is judged as saved, and so is the PDF: both from the same file."""
        doc, data = self._printed(resume_id)
        report, written = pdfcheck.analyze(data, doc), ats.analyze(doc)
        found = verdict.decide(report, written)
        checkstore.save(self.paths, doc["id"], doc["version"], found, {"data": written["score"], "pdf": report["score"]})
        return {"verdict": found, "data": written, "pdf": report, "version": doc["version"]}

    def of_current(self) -> Dict[str, Any]:
        """The verdict on the resume your runs send now."""
        profile = self._profile()
        if not profile or not profile.resume_path:
            raise ActionError("No resume is saved for your runs yet. Save one on the Profile tab, or choose a file to check.")
        path = Path(profile.resume_path)
        if not path.is_file():
            raise ActionError(f"The resume your runs send ({path.name}) is not where it was saved. Save it again on the Profile tab, or choose a file to check.")
        if path.stat().st_size > MAX_FILE:
            raise ValueError("That file is too big to check: a resume is a few hundred kilobytes.")
        return self._of_file(path.read_bytes(), path.name)

    def of_file(self, name: str, encoded: object) -> Dict[str, Any]:
        """The verdict on a file you chose (sent as base64 text). Told apart by what is inside it, never by its name."""
        if not isinstance(encoded, str) or not encoded:
            raise ActionError("Choose a PDF or a Word (.docx) file first.")
        if len(encoded) > MAX_FILE * 4 // 3 + 8:
            raise ValueError("That file is too big to check: a resume is a few hundred kilobytes.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("That file did not arrive whole. Choose it again.") from None
        return self._of_file(data, name)

    @staticmethod
    def _of_file(data: bytes, name: str) -> Dict[str, Any]:
        report = filecheck.analyze(data)
        return {"verdict": verdict.decide(report), "report": report, "file": name[:120], "kind": report["kind"]}
