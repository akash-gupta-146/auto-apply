"""AI Fill: an AI reads your resume and suggests what goes in the empty boxes of the details form, and has to prove it.

Same rule as the AI that answers application questions: for everything it suggests it must quote, word for word, the
line of the resume it used, and we check that the quote really is in the resume. Past that:
  * a value may only be made of words and numbers that appear in the resume (an address must appear exactly);
  * a skill's YEARS are accepted only when the resume itself states them ("5+ years of React"): never worked out from
    job dates, because a number made up here would later be sent to employers;
  * job titles are the one place it may put its own words (a resume says "Senior UI developer", a job ad says
    "Frontend Engineer"), but each still needs a quote showing that kind of work.
Whatever fails a check is dropped and counted, so the person is told how much was ignored. What survives is only a
suggestion: it fills EMPTY boxes of a form the person still reads and saves themselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ai_answers import MAX_DOC_CHARS, MIN_EVIDENCE_CHARS, NUMBER, redact, squash
from .llm import Completer, extract_json

BOXES = {  # form box -> what the AI is asked for
    "city": "the city where the candidate lives or works now",
    "current_title": "the candidate's current (most recent) job title",
    "current_company": "the candidate's current (most recent) employer",
    "total_experience_years": "total years of professional experience, as a number, only if the resume states it",
    "notice_period": "the notice period, only if the resume states it",
    "current_ctc": "the current salary (CTC), only if the resume states it",
    "expected_ctc": "the expected salary (CTC), only if the resume states it",
    "education": "the highest education on one line: degree, college and years",
    "linkedin": "the candidate's LinkedIn address, exactly as written",
    "github": "the candidate's GitHub address, exactly as written",
    "portfolio": "the candidate's own website or portfolio address, exactly as written",
}
ADDRESSES = ("linkedin", "github", "portfolio")
MAX_YEARS = 60
MAX_VALUE_CHARS, MAX_TITLE_CHARS, MAX_KEYWORD_CHARS, MAX_SKILL_CHARS = 160, 60, 40, 60
MAX_ROLES, MAX_KEYWORDS, MAX_SKILLS = 6, 15, 25
MAX_REPLY_TOKENS = 3000  # room for a long list of skills (Claude's API cuts a reply off at what the caller allows)
WORD = re.compile(r"\w+")

SYSTEM = (
    "You read a candidate's resume and suggest what to put in a job-application profile form. Use ONLY the resume.\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"boxes": {"<box>": {"value": "...", "evidence": "..."}},\n'
    ' "target_roles": [{"value": "...", "evidence": "..."}],\n'
    ' "keywords": [{"value": "...", "evidence": "..."}],\n'
    ' "skills": [{"name": "...", "years": <number or null>, "evidence": "..."}]}\n'
    "Rules:\n"
    '- "evidence" is a short exact quote (under 15 words) copied word for word from the resume that supports the item. '
    "Boxes and target_roles need one: no quote, no item.\n"
    "- Leave out any box the resume does not clearly state. Never guess, estimate or infer. "
    "Copy numbers and addresses exactly as written.\n"
    f"- target_roles: up to {MAX_ROLES} job titles this candidate could apply for, written the way job ads write them "
    "(for example Frontend Engineer), most fitting first. The quote must show that kind of work.\n"
    f"- keywords: up to {MAX_KEYWORDS} important skills, tools or fields from the resume that job ads would mention, "
    "written as they appear in the resume.\n"
    f"- skills: up to {MAX_SKILLS} skills the resume names. Set \"years\" ONLY when the resume itself says how long the "
    'candidate used that skill (for example "5+ years of React" gives 5, and that sentence is the evidence). '
    "Otherwise years is null. Never add up job dates and never work years out.\n"
    "BOXES you may fill (use these exact names):\n"
    + "\n".join(f"- {name}: {meaning}" for name, meaning in BOXES.items())
)


@dataclass
class Suggestions:
    boxes: Dict[str, str] = field(default_factory=dict)  # box -> text for it
    target_roles: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    skills: List[Tuple[str, Optional[float]]] = field(default_factory=list)  # (name, years the resume states, or None)
    ignored: int = 0  # suggestions dropped because the resume does not back them up


class Proof:
    """What the resume really contains, for checking the AI's claims against."""

    def __init__(self, corpus: str):
        self.text = squash(corpus)
        self.words = set(WORD.findall(self.text))
        self.numbers = set(NUMBER.findall(corpus))

    def quoted(self, evidence: object) -> bool:
        quote = str(evidence or "").strip()
        return len(quote) >= MIN_EVIDENCE_CHARS and squash(quote) in self.text

    def mentions(self, value: str) -> bool:
        """Every word and number of the value is in the resume (so nothing was added)."""
        words = WORD.findall(squash(value))
        return bool(words) and all(word in self.words for word in words) \
            and all(number in self.numbers for number in NUMBER.findall(value))

    def says_years(self, years: float, evidence: object) -> bool:
        return any(float(number) == years for number in NUMBER.findall(str(evidence or "")))


def _pair(entry: object) -> Tuple[str, str]:
    """(value, evidence) as text, from an entry the AI wrote (a bare string is a value with no evidence)."""
    if isinstance(entry, str):
        return " ".join(entry.split()), ""
    if not isinstance(entry, dict):
        return "", ""
    value = entry.get("value")
    return " ".join(str(value if value is not None else "").split()), str(entry.get("evidence") or "")


def _years(raw: object) -> Optional[float]:
    if isinstance(raw, bool) or raw in (None, ""):
        return None
    try:
        years = float(raw)
    except (TypeError, ValueError):
        return None
    return years if 0 <= years <= MAX_YEARS else None


def _box(name: str, value: str, evidence: str, proof: Proof) -> Optional[str]:
    if not value or len(value) > MAX_VALUE_CHARS:
        return None
    if name in ADDRESSES:  # an address is worth nothing unless it is exactly the one in the resume
        if squash(value) not in proof.text:
            return None
        return value if value.lower().startswith("http") else "https://" + value
    if name == "total_experience_years":
        years = _years(value)
        return f"{years:g}" if years is not None and proof.quoted(evidence) and proof.says_years(years, evidence) else None
    return value if proof.quoted(evidence) and proof.mentions(value) else None


def _names(entries: object, proof: Proof, found: Suggestions, *, limit: int, max_chars: int,
           own_words: bool) -> List[str]:
    """Job titles (own_words: the AI may choose the wording, so each needs a real quote showing that kind of work) or
    keywords (they must be made of the resume's own words, which is proof enough)."""
    kept: List[str] = []
    for entry in entries if isinstance(entries, list) else []:
        value, evidence = _pair(entry)
        if not value:
            continue
        grounded = proof.quoted(evidence) if own_words else proof.mentions(value)
        if not (2 <= len(value) <= max_chars and grounded):
            found.ignored += 1
        elif value.lower() not in {k.lower() for k in kept} and len(kept) < limit:
            kept.append(value)
    return kept


def _skills(entries: object, proof: Proof, found: Suggestions) -> List[Tuple[str, Optional[float]]]:
    kept: Dict[str, Optional[float]] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = " ".join(str(entry.get("name") or "").split()).lower()
        if not name:
            continue
        if len(name) > MAX_SKILL_CHARS or not proof.mentions(name):
            found.ignored += 1
            continue
        if name in kept or len(kept) >= MAX_SKILLS:
            continue
        years = _years(entry.get("years"))
        if entry.get("years") not in (None, ""):  # the resume must say the years in the same breath as the skill
            stated = years is not None and proof.quoted(entry.get("evidence")) and name in squash(str(entry.get("evidence"))) \
                and proof.says_years(years, entry.get("evidence"))
            if not stated:
                found.ignored += 1
                years = None
        kept[name] = years
    return list(kept.items())


def check(reply: object, corpus: str) -> Suggestions:
    """Keep only what the resume backs up. Never raises: a reply that makes no sense is simply nothing."""
    found = Suggestions()
    if not isinstance(reply, dict):
        return found
    proof = Proof(corpus)
    boxes = reply.get("boxes") if isinstance(reply.get("boxes"), dict) else {}
    for name in BOXES:
        value, evidence = _pair(boxes.get(name))
        if not value:
            continue
        text = _box(name, value, evidence, proof)
        if text is None:
            found.ignored += 1
        else:
            found.boxes[name] = text
    found.target_roles = _names(reply.get("target_roles"), proof, found, limit=MAX_ROLES, max_chars=MAX_TITLE_CHARS, own_words=True)
    found.keywords = _names(reply.get("keywords"), proof, found, limit=MAX_KEYWORDS, max_chars=MAX_KEYWORD_CHARS, own_words=False)
    found.skills = _skills(reply.get("skills"), proof, found)
    return found


def suggest(client: Completer, resume_text: str) -> Suggestions:
    """Ask the AI about this resume (its email and phone number removed first, as for every AI request)."""
    corpus = redact(resume_text)[:MAX_DOC_CHARS]
    prompt = f"RESUME:\n<<<\n{corpus}\n>>>"
    reply = extract_json(client.complete(SYSTEM, prompt, json_mode=True, max_tokens=MAX_REPLY_TOKENS))
    return check(reply, corpus)
