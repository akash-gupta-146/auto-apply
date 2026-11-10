"""Your saved answers as one book: ONE entry per fact, with the other ways the same question is worded pointing at it.

answers.yaml holds one question and one answer for each fact. data/answer_aliases.yaml says "this other wording means that
question". A form that words a question in a way you answered before is then served from the file, with no AI, ever again.

The book is a helper, never a gate. Without an AI helper (not set up, daily limit reached, offline) an answer is simply saved
as typed, exactly as before; with one, the other wordings of the same fact are folded into the entry. Code, not the AI, decides
what may never be folded: consent wordings, and two figures that differ by orders of magnitude (70 and 6500000 are lakhs and
rupees, not a disagreement). When the AI does fold two wordings whose answers differ, the answer you just typed wins: an
explicit correction from you outranks everything else. What it replaced is kept in the AI's ledger.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import yaml

from .ai_answers import CONSENT, same_answer
from .config import Paths, load_answers, save_answers
from .similarity import nearest

log = logging.getLogger("jobapply")

MAX_COMPARED = 12  # saved and waiting questions a new answer is compared with: the most alike, never the whole list
UNIT_GAP = 50  # two single figures this far apart are different units (lakhs and rupees), not two opinions


def load_aliases(path) -> Dict[str, str]:
    """Other wording -> the question it means. A damaged or missing file is simply no aliases: they only ever save an AI call."""
    try:
        found = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def save_aliases(aliases: Mapping[str, str], path) -> None:
    path.write_text(yaml.safe_dump(dict(aliases), sort_keys=True, allow_unicode=True), encoding="utf-8")


def expand(bank: Mapping[str, str], aliases: Mapping[str, str]) -> Dict[str, str]:
    """Every wording a saved answer serves: the entries themselves, and each alias with its entry's answer. An alias whose entry
    is gone is ignored, and an entry always beats an alias of the same words."""
    wording = dict(bank)
    for alias, canonical in aliases.items():
        if canonical in bank and alias not in wording:
            wording[alias] = bank[canonical]
    return wording


def equivalent(first: str, second: str) -> bool:
    """The same answer: the same words, or one is the first words of the other ("30" and "30 Days")."""
    return same_answer(first, second) or same_answer(second, first)


def unit_mismatch(first: str, second: str) -> bool:
    """Single figures wildly apart: 70 (lakhs) and 6500000 (rupees) are one fact in two units, never a conflict to settle."""
    numbers = [re.findall(r"\d[\d,]*(?:\.\d+)?", text) for text in (first, second)]
    if any(len(found) != 1 for found in numbers):
        return False
    low, high = sorted(float(found[0].replace(",", "")) for found in numbers)
    return low > 0 and high / low >= UNIT_GAP


def merge(bank: Dict[str, str], aliases: Dict[str, str], canonical: str, wordings: Iterable[str], answer: Optional[str] = None) -> None:
    """Make `wordings` other ways of asking `canonical`, optionally giving it `answer`. Their own entries go; any wording that
    pointed at one of them now points at `canonical`, so a wording is never an alias of an alias."""
    for wording in wordings:
        if wording == canonical:
            continue
        bank.pop(wording, None)
        aliases[wording] = canonical
        for other, target in list(aliases.items()):
            if target == wording:
                aliases[other] = canonical
    if answer is not None:
        bank[canonical] = answer


class AnswerBook:
    def __init__(self, paths: Paths, judge=None):
        self.paths, self.judge = paths, judge  # judge: an ai_facts.FactJudge, or None for "save exactly as typed"

    def saved(self) -> Dict[str, str]:
        """One entry per fact: what the Questions page lists."""
        return load_answers(self.paths.answers)

    def wordings(self) -> Dict[str, str]:
        """Every wording a saved answer serves: what a form's question is looked up in."""
        return expand(self.saved(), load_aliases(self.paths.aliases))

    def remember(self, question: str, answer: str, waiting: Sequence[str] = ()) -> List[str]:
        """Save an answer. With an AI helper, also fold into it the saved and `waiting` questions that ask the same fact; those
        wordings are returned so the caller can stop waiting on them. Saving never fails because the AI did."""
        bank, aliases = self.saved(), load_aliases(self.paths.aliases)
        target = aliases.get(question, question)  # answering a wording we already know updates its entry
        bank[target] = answer
        folded = self._fold(bank, aliases, target, answer, waiting)
        save_answers(bank, self.paths.answers)
        save_aliases(aliases, self.paths.aliases)
        return folded

    def forget(self, question: str) -> bool:
        """Remove an entry and every wording that pointed at it. Only a real entry counts."""
        bank, aliases = self.saved(), load_aliases(self.paths.aliases)
        if question not in bank:
            return False
        del bank[question]
        save_answers(bank, self.paths.answers)
        save_aliases({alias: target for alias, target in aliases.items() if target != question}, self.paths.aliases)
        return True

    # -- folding the wordings of one fact together ------------------------------------------------
    def _fold(self, bank: Dict[str, str], aliases: Dict[str, str], target: str, answer: str, waiting: Sequence[str]) -> List[str]:
        if self.judge is None or CONSENT.search(target):
            return []
        known = set(bank) | set(aliases)
        pool = [q for q in bank if q != target and not CONSENT.search(q)]
        pool += [w for w in waiting if w != target and w not in known and not CONSENT.search(w)]
        near = nearest(target, pool, MAX_COMPARED)
        if not near:
            return []
        try:
            same = self.judge.same_fact(target, near)
        except Exception as exc:  # an AI that is down, slow or confused must never lose the answer that was just typed
            log.warning("could not compare %r with your saved answers: %s", target[:60], exc)
            return []
        folded = []
        for wording in same:
            old = bank.get(wording)
            if old is not None and not equivalent(old, answer) and unit_mismatch(old, answer):
                continue
            merge(bank, aliases, target, [wording])
            if old is not None and not equivalent(old, answer):
                self.judge.ledger.note(kind="replaced", kept=target, answer=answer, wording=wording, replaced_answer=old)
            folded.append(wording)
        return folded
