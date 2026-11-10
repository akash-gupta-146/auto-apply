"""Tidy the answers you already have: fold the wordings of one fact into one entry, and settle the ones that disagree.

`jobapply answers --tidy` shows the plan and changes nothing; `--tidy --apply` makes a dated backup first, then does it.

What is decided here, in code, before and after any AI:
* Answers that are the same ("30" and "30 Days") are merged with no AI. The fuller one is kept.
* Answers that disagree are settled by the AI's "most reliable" choice (see ai_facts), which can only pick one of YOUR answers.
* Never settled by anyone but you: a personal question (gender, race, disability...), figures in different units, and any
  conflict the AI says it cannot judge. These are listed as needing you, and left exactly as they are.
* Consent wordings are never touched.
"""
from __future__ import annotations

import dataclasses
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from .ai_answers import CONSENT
from .ai_facts import FactJudge
from .answer_book import equivalent, load_aliases, merge, save_aliases, unit_mismatch
from .answers import SENSITIVE
from .config import Paths, load_answers, save_answers


@dataclasses.dataclass
class Merge:
    canonical: str  # the wording that stays
    answer: str  # the answer that stays
    wordings: List[str]  # the other wordings, now pointing at it
    replaced: List[Tuple[str, str]]  # (wording, answer) given up because they disagreed
    reason: str


@dataclasses.dataclass
class NeedsYou:
    answers: Dict[str, str]  # wording -> answer
    reason: str


@dataclasses.dataclass
class Plan:
    merges: List[Merge] = dataclasses.field(default_factory=list)
    needs_you: List[NeedsYou] = dataclasses.field(default_factory=list)


def _distinct(answers: Mapping[str, str]) -> Dict[str, List[str]]:
    """Each different answer, with the wordings it was given for. The fullest form of an answer represents it."""
    groups: Dict[str, List[str]] = {}
    for wording, answer in sorted(answers.items(), key=lambda item: (-len(item[1]), item[0])):
        home = next((known for known in groups if equivalent(known, answer)), None)
        groups.setdefault(home or answer, []).append(wording)
    return groups


def plan_tidy(bank: Mapping[str, str], judge: FactJudge) -> Plan:
    plan = Plan()
    for group in judge.group(sorted(bank)):
        answers = {wording: bank[wording] for wording in group if wording in bank and not CONSENT.search(wording)}  # whatever the AI grouped
        if len(answers) < 2:
            continue
        distinct = _distinct(answers)
        canonical = max(answers, key=lambda wording: (len(wording.split()), wording))  # the fullest wording is the clearest one
        others = [wording for wording in answers if wording != canonical]
        if len(distinct) == 1:
            plan.merges.append(Merge(canonical, next(iter(distinct)), others, [], "the same answer under different words"))
            continue
        kept = list(distinct)
        if any(SENSITIVE.search(wording) for wording in answers):
            plan.needs_you.append(NeedsYou(answers, "a personal question: only you can say which is right"))
        elif any(unit_mismatch(a, b) for a in kept for b in kept):
            plan.needs_you.append(NeedsYou(answers, "the figures look like different units (lakhs and rupees): check them"))
        else:
            choice = judge.most_reliable(distinct)
            if choice is None:
                plan.needs_you.append(NeedsYou(answers, "the AI could not tell which is right"))
            else:
                answer, why = choice
                replaced = [(w, a) for w, a in answers.items() if not equivalent(a, answer)]
                plan.merges.append(Merge(canonical, answer, others, replaced, why or "the most reliable of the answers"))
    return plan


def describe(plan: Plan) -> str:
    lines: List[str] = []
    for item in plan.merges:
        lines.append(f'MERGE  keep "{item.canonical}" -> {item.answer}   ({item.reason})')
        lines += [f'         also asked as: "{wording}"' for wording in item.wordings]
        lines += [f'         gives up: "{wording}" -> {answer}' for wording, answer in item.replaced]
    for item in plan.needs_you:
        lines.append(f"NEEDS YOU  {item.reason}")
        lines += [f'         "{wording}" -> {answer}' for wording, answer in item.answers.items()]
    return "\n".join(lines) or "nothing to tidy"


def apply_plan(paths: Paths, plan: Plan) -> Path:
    """Back up first, then rewrite. The backup is the undo: copy it over answers.yaml (and answer_aliases.yaml)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = paths.answers.with_name(f"{paths.answers.name}.bak-{stamp}")
    shutil.copy2(paths.answers, backup)
    if paths.aliases.exists():
        shutil.copy2(paths.aliases, paths.aliases.with_name(f"{paths.aliases.name}.bak-{stamp}"))
    bank, aliases = load_answers(paths.answers), load_aliases(paths.aliases)
    for item in plan.merges:
        merge(bank, aliases, item.canonical, item.wordings, item.answer)
    save_answers(bank, paths.answers)
    save_aliases(aliases, paths.aliases)
    return backup
