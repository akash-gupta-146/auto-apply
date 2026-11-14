"""Answers the AI GUESSED, kept apart from the answers you gave.

Never mixed into answers.yaml: a guess is not something you said. Your own answers outrank it everywhere, the AI that reads your
answers as facts must not read a guess as one, and what only you may decide (an agreement, a legal declaration) is never settled by
it. It is kept so the same question, asked again on another job, is answered the same way without asking the AI again, and so you
can look at every guess, keep one as your own answer, or forget it.

One entry per question, in a file you can read: the question's own words, the guess, when it was made and for which job. A missing or
damaged file is simply no guesses: they only ever save a request.
"""
from __future__ import annotations

import dataclasses
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .answers import normalize


@dataclasses.dataclass(frozen=True)
class Guess:
    question: str
    answer: str
    when: str = ""
    job: str = ""  # the job that asked, as the agent named it ("Acme: Senior Engineer")


class GuessBook:
    def __init__(self, path: Path):
        self.path = path

    def all(self) -> List[Guess]:
        """Every guess, newest first."""
        found = [Guess(question, str(entry.get("answer", "")), str(entry.get("when", "")), str(entry.get("job", "")))
                 for question, entry in self._read().items() if isinstance(entry, dict) and str(entry.get("answer", "")).strip()]
        return sorted(found, key=lambda guess: guess.when, reverse=True)

    def get(self, question: str) -> Optional[Guess]:
        """The guess for this question, whatever its capitalisation or punctuation."""
        norm = normalize(question)
        return next((guess for guess in self.all() if norm and normalize(guess.question) == norm), None)

    def remember(self, question: str, answer: str, job: str = "") -> None:
        """Keep a guess; a question guessed before is replaced, never repeated."""
        entries = self._read()
        for old in [key for key in entries if normalize(key) == normalize(question)]:
            del entries[old]
        entries[" ".join(question.split())] = {"answer": answer.strip(), "when": datetime.now().isoformat(timespec="seconds"), "job": job}
        self._write(entries)

    def forget(self, question: str) -> bool:
        entries = self._read()
        gone = [key for key in entries if normalize(key) == normalize(question)]
        for key in gone:
            del entries[key]
        if gone:
            self._write(entries)
        return bool(gone)

    # -- the file ---------------------------------------------------------------------------------------------
    def _read(self) -> Dict[str, dict]:
        try:
            found = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return {str(key): value for key, value in found.items()} if isinstance(found, dict) else {}

    def _write(self, entries: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".tmp")
        scratch.write_text(yaml.safe_dump(entries, sort_keys=True, allow_unicode=True), encoding="utf-8")
        os.replace(scratch, self.path)  # whole or not at all: the panel reads this file while a run writes it
