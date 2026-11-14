"""Is the book of saved answers in good shape? Three checks that need no AI, and the one-click fixes for what they find. No HTTP and no HTML in here.

* A saved answer that DISAGREES WITH YOUR PROFILE about the same fact (notice period 15 saved, 30 days in the profile). A run uses the saved one and
  says so (answers.py); here you choose: use the profile's answer, or keep yours (and it is not said again until either text changes).
* Saved questions that may be ONE QUESTION asked twice, offered for merging only when merging loses nothing: their answers agree ("30" and "30 days")
  and what one asks is wholly contained in the other ("notice period" / "notice period in days"; two cities or two skills are NOT contained in each
  other, so "years of experience with Python" and "...with Java" are never offered, nor "current CTC" in lakhs and in rupees). Consent and personal
  questions are never offered. Wordings that look alike but answer differently are left alone: they are usually one template asked about different things.
* Which saved answers runs actually USE, so a stale one is easy to see and remove. Counting began when this was added; a run counts an answer once
  per job.

Every fix is decided here from what is saved, never from text sent by the page: the page only says WHICH saved question, and the answer that results
is one you already gave or your profile already says. Nothing is invented.
"""
from __future__ import annotations

import dataclasses
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from .ai_answers import CONSENT
from .answer_book import disagree, equivalent, load_aliases, merge, save_aliases
from .answers import SENSITIVE, normalize, profile_answer
from .config import Paths, Profile, load_answers, save_answers
from .db import Database
from .similarity import words

MIN_WORDS, MAX_EXTRA_WORDS = 2, 2  # the smaller wording needs this many meaningful words; the larger may add at most this many


@dataclasses.dataclass(frozen=True)
class Conflict:
    question: str  # the saved wording
    saved: str  # what you saved
    profile: str  # what your profile says to the same question


@dataclasses.dataclass
class Alike:
    entries: List[Tuple[str, str]]  # (wording, answer) as saved: they agree, so merging loses nothing


@dataclasses.dataclass(frozen=True)
class Use:
    question: str
    answer: str
    uses: int
    last: str  # when a run last used it, "" if never


@dataclasses.dataclass
class Health:
    conflicts: List[Conflict]
    alike: List[Alike]
    used: List[Use]  # most used first
    unused: List[Use]
    counting_since: str  # when the first use was counted, "" if none yet
    has_profile: bool

    @property
    def problems(self) -> int:
        return len(self.conflicts) + len(self.alike)


def conflicts(profile: Profile, bank: Dict[str, str], acknowledged: Dict[str, tuple]) -> List[Conflict]:
    found = []
    for question, answer in sorted(bank.items(), key=lambda item: item[0].lower()):
        norm = normalize(question)
        ruled = profile_answer(profile, norm)
        if ruled and disagree(answer, ruled) and acknowledged.get(norm) != (answer, ruled):
            found.append(Conflict(question, answer, ruled))
    return found


def _contained(first: str, second: str) -> bool:
    """What the one asks is wholly inside the other, which adds only a word or two: the same question with a little more said."""
    smaller, larger = sorted((words(first), words(second)), key=len)
    return len(smaller) >= MIN_WORDS and smaller <= larger and len(larger) - len(smaller) <= MAX_EXTRA_WORDS


def alike(bank: Dict[str, str]) -> List[Alike]:
    """Groups of saved questions that look like one question asked more than once, and whose answers agree. A group is built from pairs, so it can
    be bigger than two."""
    questions = [q for q in sorted(bank, key=str.lower) if not CONSENT.search(q) and not SENSITIVE.search(q)]
    parent = {q: q for q in questions}

    def root(q: str) -> str:
        while parent[q] != q:
            q = parent[q]
        return q

    for one, other in combinations(questions, 2):
        if _contained(one, other) and equivalent(bank[one], bank[other]):
            parent[root(other)] = root(one)
    groups: Dict[str, List[str]] = {}
    for q in questions:
        groups.setdefault(root(q), []).append(q)
    return [Alike([(q, bank[q]) for q in group]) for group in groups.values() if len(group) > 1]


def usage(bank: Dict[str, str], aliases: Dict[str, str], uses: Dict[str, Dict[str, object]]) -> Tuple[List[Use], List[Use], str]:
    """How much each saved answer is used, counting every other wording that points at it. (used, unused, when counting began)"""
    wordings: Dict[str, List[str]] = {q: [normalize(q)] for q in bank}
    for alias, target in aliases.items():
        if target in wordings:
            wordings[target].append(normalize(alias))
    rows = []
    for question, answer in bank.items():
        hits = [uses[norm] for norm in wordings[question] if norm in uses]
        rows.append(Use(question, answer, sum(int(hit["uses"]) for hit in hits), max((str(hit["last"]) for hit in hits), default="")))
    rows.sort(key=lambda use: (-use.uses, use.question.lower()))
    began = min((str(row["first"]) for row in uses.values() if row["first"]), default="")
    return [r for r in rows if r.uses], [r for r in rows if not r.uses], began


def report(paths: Paths, profile: Optional[Profile], db: Database) -> Health:
    bank, aliases = load_answers(paths.answers), load_aliases(paths.aliases)
    used, unused, began = usage(bank, aliases, db.answer_uses())
    return Health(conflicts(profile, bank, db.acknowledged()) if profile is not None else [], alike(bank), used, unused, began, profile is not None)


# -- the fixes: each names a saved question, and nothing else ----------------------------------------------------------------------------
def use_profile(paths: Paths, profile: Profile, question: str) -> bool:
    """Replace a saved answer with what the profile says to the same question. False unless it really is a saved question the profile answers."""
    bank = load_answers(paths.answers)
    ruled = profile_answer(profile, normalize(question)) if question in bank else None
    if not ruled:
        return False
    bank[question] = ruled
    save_answers(bank, paths.answers)
    return True


def keep_mine(paths: Paths, db: Database, profile: Profile, question: str) -> bool:
    """Keep a saved answer that disagrees with the profile, and stop saying so until either text changes. False unless they really disagree."""
    bank = load_answers(paths.answers)
    saved = bank.get(question)
    ruled = profile_answer(profile, normalize(question)) if saved is not None else None
    if saved is None or not ruled or not disagree(saved, ruled):
        return False
    db.acknowledge(normalize(question), saved, ruled)
    return True


def merge_alike(paths: Paths, question: str) -> int:
    """Fold the saved questions that go with `question` into it; how many were folded. Their wordings still work (they point at it now), and the
    fullest of their agreeing answers is kept."""
    bank, aliases = load_answers(paths.answers), load_aliases(paths.aliases)
    group = next((g for g in alike(bank) if question in {q for q, _ in g.entries}), None)
    if group is None:
        return 0
    answer = max((a for _, a in group.entries), key=len)
    others: Sequence[str] = [q for q, _ in group.entries if q != question]
    merge(bank, aliases, question, others, answer)
    save_answers(bank, paths.answers)
    save_aliases(aliases, paths.aliases)
    return len(others)
