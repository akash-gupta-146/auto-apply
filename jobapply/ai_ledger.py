"""A file of what an AI helper decided: readable by you, and remembered so the same question is never paid for twice.

One line of JSON per decision, appended to a file in data/. A decision carries a key (what was asked) and a value (what was
decided); a note carries only facts worth keeping (what a merge replaced) and is never read back as a decision.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._memory: Dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    record = json.loads(line)
                    self._memory[record["key"]] = record["value"]
                except (ValueError, KeyError, TypeError):
                    continue  # a damaged line, or a note: only a lost memory, never an error

    def get(self, key: str) -> Optional[Any]:
        """What was decided for this key, or None when it was never decided (so a decision of "nothing" is `[]`, not None)."""
        return self._memory.get(key)

    def remember(self, key: str, value: Any, **context: Any) -> None:
        self._memory[key] = value
        self._append({"key": key, "value": value, **context})

    def note(self, **facts: Any) -> None:
        self._append(facts)

    def _append(self, record: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), **record}, ensure_ascii=False) + "\n")
