"""Tailoring a resume to a job as a list of small, checked changes, never as a rewrite.

The AI (or the rules below) proposes changes: "at this place, this text becomes that text, because...". Nothing is applied until you accept it, and every
proposal is checked here, again, before it is shown and again before it is applied (so a changed request cannot get round the checks):

  * only a few places can change: the summary, a bullet of a job or project, a new bullet under a job (only when you ask for the fullest tailoring), and
    the order of the items in a skills group. Names, employers, dates, schools, degrees and contact details can never change;
  * "original" must be what is really there now (so an edit that was made up about text that does not exist is refused);
  * the new text must say nothing your resume does not already say: no new number, skill, tool or name, no seniority you did not claim, no "I", and no
    blank like [X%]. The text of the *job* never counts as something you said: a job can ask for Kubernetes; only you can have used it;
  * a reorder must be the same items, only in another order.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence

from ..ai_answers import squash
from .ai import FIRST_PERSON, new_facts
from .doc import LIMITS, PLACEHOLDER, full_text, normalize
from .tailor import pretty

STRENGTHS = {
    "nudge": "A light touch: rephrase the lines that already fit the job, nothing else.",
    "keywords": "Work the job's own words into lines that already show them (nothing is added).",
    "full": "The fullest: also lets a line be expanded, and the job's skills be put first. Still nothing that is not already in your resume.",
}
STRENGTH_NAMES = {"nudge": "Light touch", "keywords": "Match its words (recommended)", "full": "Fullest"}
ACTIONS = {"nudge": ("replace",), "keywords": ("replace", "reorder"), "full": ("replace", "append", "reorder")}
MOST = {"nudge": 6, "keywords": 10, "full": 12}
SUMMARY = "/summary"
BULLET = re.compile(r"^/(experience|projects)/(\d+)/bullets/(\d+)$")
BULLETS = re.compile(r"^/(experience|projects)/(\d+)/bullets$")
SKILLS = re.compile(r"^/skills/(\d+)/items$")
LEVEL_WORDS = frozenset({"senior", "sr", "lead", "principal", "staff", "manager", "head", "director", "architect", "chief", "vp", "intern", "junior"})
MAX_REASON = 160


class Change(NamedTuple):
    id: str
    path: str
    action: str  # replace | append | reorder
    original: Any  # the text there now (replace), or None (append), or the items now (reorder)
    value: Any  # the new text, or the items in their new order
    reason: str
    label: str = ""  # where it is, in words: "Senior Backend Engineer, bullet 2"

    def as_dict(self) -> Dict[str, Any]:
        return self._asdict()


class Refused(NamedTuple):
    path: str
    why: str


class Checked(NamedTuple):
    changes: List[Change]
    refused: List[Refused]


# -- finding the place ---------------------------------------------------------------------------------------------------------------------
def _entry(doc: Mapping, kind: str, index: int) -> Optional[Mapping]:
    items = doc.get(kind) or []
    return items[index] if 0 <= index < len(items) else None


def current(doc: Mapping, path: str) -> Any:
    """What is at this place now (a text, or a list of items), or None if there is no such place or it may not be changed."""
    if path == SUMMARY:
        return doc["summary"]
    found = BULLET.match(path)
    if found:
        entry = _entry(doc, found.group(1), int(found.group(2)))
        bullets = entry["bullets"] if entry else []
        return bullets[int(found.group(3))] if int(found.group(3)) < len(bullets) else None
    found = BULLETS.match(path)
    if found:
        entry = _entry(doc, found.group(1), int(found.group(2)))
        return list(entry["bullets"]) if entry else None
    found = SKILLS.match(path)
    if found:
        entry = _entry(doc, "skills", int(found.group(1)))
        return list(entry["items"]) if entry else None
    return None


def label_for(doc: Mapping, path: str) -> str:
    if path == SUMMARY:
        return "Summary"
    found = BULLET.match(path) or BULLETS.match(path)
    if found:
        entry = _entry(doc, found.group(1), int(found.group(2))) or {}
        name = entry.get("title") or entry.get("name") or found.group(1)
        return f"{name}, bullet {int(found.group(3)) + 1}" if BULLET.match(path) else f"{name}, a new bullet"
    found = SKILLS.match(path)
    entry = _entry(doc, "skills", int(found.group(1))) if found else None
    return f"Skills: {entry['group'] or 'your skills'}" if entry else path


def _words(text: str) -> set:
    return set(re.findall(r"[a-z]+", text.lower()))


# -- checking a proposal -------------------------------------------------------------------------------------------------------------------
def _refuse(path: str, why: str) -> Refused:
    return Refused(path[:60], why)


def check_one(doc: Mapping, raw: Mapping, source: str, strength: str) -> "Change | Refused":
    """One proposed change: the Change it really is (the text it replaces read from the resume, not from the proposal), or why it is refused."""
    path, action = raw.get("path"), raw.get("action")
    if not isinstance(path, str) or not isinstance(action, str):
        return _refuse(str(path), "it did not say where, or what to do")
    if action not in ACTIONS[strength]:
        return _refuse(path, f"\"{action}\" is not allowed at this strength")
    here = current(doc, path)
    reason = " ".join(str(raw.get("reason") or "").split())[:MAX_REASON]
    if action == "reorder":
        if not SKILLS.match(path) or here is None:
            return _refuse(path, "only a skills group can be put in a new order")
        value = raw.get("value")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value) or sorted(i.lower() for i in value) != sorted(i.lower() for i in here):
            return _refuse(path, "a new order must have exactly the same skills")
        by_name = {item.lower(): item for item in here}
        ordered = [by_name[item.lower()] for item in value]
        if ordered == here:
            return _refuse(path, "it is already in that order")
        return Change("", path, action, here, ordered, reason or "The skills this job asks for come first.", label_for(doc, path))
    value = raw.get("value")
    if not isinstance(value, str) or "\n" in value.strip():
        return _refuse(path, "the new text must be one line")
    value = " ".join(value.split())
    if action == "replace":
        if not (path == SUMMARY or BULLET.match(path)) or here is None or not here:
            return _refuse(path, "there is nothing there to replace")
        if squash(str(raw.get("original") or "")) != squash(here):
            return _refuse(path, "the text it says it is changing is not what is there")
        if squash(value) == squash(here):
            return _refuse(path, "it changes nothing")
    elif action == "append":
        if not BULLETS.match(path) or here is None or len(here) >= LIMITS["bullets"]:
            return _refuse(path, "no room for another bullet there")
        here = None
    limit = LIMITS["summary"] if path == SUMMARY else LIMITS["bullet"]
    if not value or len(value) > limit:
        return _refuse(path, "the new text is empty or too long")
    if FIRST_PERSON.search(value) or PLACEHOLDER.search(value):
        return _refuse(path, "it uses \"I\" or leaves a blank like [X%]")
    added = new_facts(value, source)
    if added:
        return _refuse(path, f"it adds what your resume does not say ({', '.join(added[:3])})")
    claimed = (_words(value) & LEVEL_WORDS) - _words(source)
    if claimed:
        return _refuse(path, f"it claims a level your resume does not ({', '.join(sorted(claimed))})")
    return Change("", path, action, here, value, reason, label_for(doc, path))


def check(doc: Mapping, raw_changes: object, strength: str = "keywords", extra_facts: str = "") -> Checked:
    """The changes among those proposed that pass every check, numbered, and a plain reason for each one that did not. `extra_facts` is what you told us
    yourself (your answers to a question): it counts as yours. The text of the job is never passed here."""
    strength = strength if strength in STRENGTHS else "keywords"
    source = f"{full_text(doc)}\n{extra_facts}"
    kept: List[Change] = []
    refused: List[Refused] = []
    seen = set()
    for raw in raw_changes if isinstance(raw_changes, list) else []:
        if not isinstance(raw, Mapping):
            continue
        result = check_one(doc, raw, source, strength)
        if isinstance(result, Refused):
            refused.append(result)
        elif (result.path, result.action) in seen:
            refused.append(_refuse(result.path, "another change already covers this place"))
        elif len(kept) >= MOST[strength]:
            refused.append(_refuse(result.path, "that is as many changes as this strength makes"))
        else:
            seen.add((result.path, result.action))
            kept.append(result._replace(id=f"c{len(kept) + 1}"))
    return Checked(kept, refused)


# -- applying what you accepted ------------------------------------------------------------------------------------------------------------
def apply(doc: Mapping, changes: Sequence[Change]) -> Dict[str, Any]:
    """A copy of the resume with these changes made (the resume given is not touched), written out clean."""
    updated = copy.deepcopy(dict(doc))
    for change in changes:
        if change.path == SUMMARY:
            updated["summary"] = change.value
        elif BULLET.match(change.path):
            kind, i, j = BULLET.match(change.path).groups()
            updated[kind][int(i)]["bullets"][int(j)] = change.value
        elif BULLETS.match(change.path):
            kind, i = BULLETS.match(change.path).groups()
            updated[kind][int(i)]["bullets"].append(change.value)
        elif SKILLS.match(change.path):
            updated["skills"][int(SKILLS.match(change.path).group(1))]["items"] = list(change.value)
    return normalize(updated)


def tailored_title(job_title: str, company: str) -> str:
    named = " at ".join(part for part in (job_title.strip(), company.strip()) if part)
    return f"Tailored: {named}"[:LIMITS["title"]] if named else "Tailored copy"


# -- the changes that need no AI -------------------------------------------------------------------------------------------------------------
def _is(item: str, name: str) -> bool:
    """Is this item of a skills group that skill (named in lower case, as the project's list has it)? "Kubernetes" is "kubernetes"; "CI/CD" is "ci/cd"."""
    return item.lower() in (name, pretty(name).lower())


def skill_order(doc: Mapping, wanted: Sequence[str]) -> List[Change]:
    """For each skills group that has some of the skills the job asks for (`wanted`, canonical names): the same skills with those first, in the order the job
    lists them. Only an order: nothing is added, so it is safe to offer without asking an AI."""
    found: List[Change] = []
    for i, group in enumerate(doc["skills"]):
        items = list(group["items"])
        asked = sorted((item for item in items if any(_is(item, name) for name in wanted)), key=lambda item: next(n for n, name in enumerate(wanted) if _is(item, name)))
        ordered = asked + [item for item in items if item not in asked]
        if asked and ordered != items:
            path = f"/skills/{i}/items"
            found.append(Change(f"s{len(found) + 1}", path, "reorder", items, ordered, "The skills this job asks for come first, where a reader looks.", label_for(doc, path)))
    return found
