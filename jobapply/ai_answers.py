"""An AI that answers form questions ONLY from documents you gave it, and has to prove it.

For every answer the model must quote, word for word, the sentence it used. We then check that the quote
really is in your documents, and that every number in the answer appears in them too, so it cannot do
sums or invent years. An answer that fails either check is thrown away and the job is parked for you,
exactly as if the AI did not exist. Every request and verdict is appended to data/ai_answers.jsonl.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import httpx

from .ai_settings import build_documents, load_ai_settings, make_client
from .answers import SENSITIVE, normalize, pick_option
from .config import ConfigError, Paths, Profile
from .db import Database
from .llm import BudgetExceeded, Completer, LlmError, extract_json
from .similarity import similarity

# Profile fields that never leave this computer: the AI is told what you have done, not who you are or how to reach you.
PRIVATE_FIELDS = {"email", "phone", "resume_path", "resume_hash", "name"}

log = logging.getLogger("jobapply")

MAX_DOC_CHARS = 40_000  # sent with every question: bounds both cost and what leaves this computer
MAX_ANSWER_CHARS = 600
MAX_EARLIER_CHARS = 8_000  # of your own earlier answers: whole lines only, so the quote it gives is always a real line
EARLIER_HEADING = "YOUR EARLIER ANSWERS (questions the candidate answered themselves on earlier applications)"
# An answer to a consent is an answer to that one text. It is still reused when the very same words come up again (the
# answer bank does that), but the AI is never shown it, so it cannot stretch "yes" to a consent worded differently.
CONSENT = re.compile(r"\b(certif\w*|consent\w*|acknowledg\w*|agree\w*|declar\w*|privacy|terms)\b", re.I)
MIN_EVIDENCE_CHARS = 4
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LONG_NUMBER = re.compile(r"\+?\d(?:[\s-]?\d){9,}")  # phone-like: 10 or more digits in a row
NUMBER = re.compile(r"\d+(?:\.\d+)?")
TYPOGRAPHY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                            "\u2013": "-", "\u2014": "-", "\u00a0": " "})

SYSTEM = (
    "You fill in ONE question of a job application for a candidate, using ONLY the candidate's documents.\n"
    'Reply with a single JSON object: {"answer": <short string or null>, "evidence": <string or null>, "source": <string or null>}.\n'
    "Rules:\n"
    '- "evidence" must be an exact quote, copied word for word, from the documents that supports the answer. '
    "No quote, no answer.\n"
    '- If the documents do not clearly support an answer, reply {"answer": null, "evidence": null}. '
    "Never guess, estimate, calculate or infer. Copy numbers exactly as written; never add up years.\n"
    '- If OPTIONS are listed, answer with the plain fact (for example "Yes", "No" or a number), not with the '
    "option text: the program picks the matching option.\n"
    "- Lines under YOUR EARLIER ANSWERS are answers the candidate typed themselves to earlier application questions. "
    "Each starts with an id such as [A3]. If the question asks for exactly the same fact as one of them (even in other "
    'words), answer with that line\'s answer and put its id in "source" (for example "A3"); "evidence" may then be null. '
    "A question that is only related is not the same fact: reply null. If two of them give different answers to the same "
    "fact, choose the most reliable one and name its id: first the one that agrees with the documents, then the one given for "
    "more wordings, then the one that states its figure with a unit. Never combine, average or convert them. If you cannot tell "
    "which is right, reply null. Never choose between conflicting answers about gender, race, ethnicity, disability, veteran "
    "status, religion or orientation: reply null.\n"
    "- Write in the first person, plainly, with no markdown. Keep it under 500 characters."
)


def redact(text: str) -> str:
    """Contact details never go to an AI: the rules answer those questions from your profile."""
    return LONG_NUMBER.sub("[phone]", EMAIL.sub("[email]", text))


def squash(text: str) -> str:
    """Lower-case, plain quotes and dashes, single spaces: so a quote still matches after the model retypes it."""
    return re.sub(r"\s+", " ", text.translate(TYPOGRAPHY).lower()).strip()


def profile_facts(profile: Profile) -> str:
    facts = {k: v for k, v in dataclasses.asdict(profile).items() if k not in PRIVATE_FIELDS and v not in ("", None)}
    skills = facts.pop("skills", None) or {}
    lines = []
    for key, value in facts.items():
        text = ("Yes" if value else "No") if isinstance(value, bool) else value
        lines.append(f"{key.replace('_', ' ')}: {text}")
    lines += [f"{skill}: {years:g} years" for skill, years in sorted(skills.items()) if years is not None]
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class Earlier:
    question: str
    answer: str
    line: str  # one quotable line: - When asked "<question>" the candidate answered: <answer>


def earlier_entries(bank: Mapping[str, str]) -> List[Earlier]:
    """Your own answers, one entry each, naming the question they answered. Consents are left out (see CONSENT)."""
    entries = []
    for question, answer in bank.items():
        asked, given = " ".join(str(question).split()), " ".join(str(answer).split())
        if asked and given and not CONSENT.search(str(question)):
            entries.append(Earlier(asked, given, f'- When asked "{asked}" the candidate answered: {given}'))
    return entries


def earlier_answers(bank: Mapping[str, str]) -> str:
    """The first of your answers that fit, as whole lines in the order you gave them."""
    kept, size = [], 0
    for entry in earlier_entries(bank):
        size += len(entry.line) + 1
        if size > MAX_EARLIER_CHARS:
            break
        kept.append(entry.line)
    return "\n".join(kept)


def most_relevant(entries: Sequence[Earlier], question: str, limit: int = MAX_EARLIER_CHARS) -> List[Earlier]:
    """All of your answers when they fit. When they do not, the ones whose question is most like this one (a word that few of
    your questions use counts for more), still in the order you gave them. Cutting the end off instead would hide your newest
    answers, which are the ones a question that keeps coming back is about."""
    if sum(len(entry.line) + 1 for entry in entries) <= limit:
        return list(entries)
    score = similarity(question, [entry.question for entry in entries])
    chosen, size = [], 0
    for index in sorted(range(len(entries)), key=lambda i: (-score[i], i)):
        cost = len(entries[index].line) + 1
        if size + cost <= limit:
            chosen.append(index)
            size += cost
    return [entries[index] for index in sorted(chosen)]


def personal_conflict(question: str, shown: Mapping[str, "Earlier"]) -> bool:
    """Gender, race, disability, veteran status and the like: when the answers shown about the same topic differ, no AI may
    pick one (a wrong pick is a wrong statement about the person). Code decides this, not the model."""
    topics = {word.lower() for word in SENSITIVE.findall(question)}
    about = [entry for entry in shown.values() if topics & {word.lower() for word in SENSITIVE.findall(entry.question)}]
    return len({squash(entry.answer) for entry in about}) > 1


def same_answer(answer: str, saved: str) -> bool:
    """The AI's answer is the answer you saved: the same words, or its first words ("30" for "30 Days")."""
    given, kept = squash(answer), squash(saved)
    return bool(given) and re.match(re.escape(given) + r"(?!\w)", kept) is not None  # "no" is "No, I am not...", never "Not listed"


@dataclasses.dataclass
class Verdict:
    answer: Optional[str]
    evidence: str = ""
    reason: str = ""


class AiAnswerer:
    """Callable as `answerer(question, options) -> answer or None`; plugs into AnswerResolver."""

    def __init__(self, client: Completer, profile: Profile, documents: str, log_path: Path, portal: str,
                 answers: Optional[Mapping[str, str]] = None):
        self.client, self.portal, self.log_path = client, portal, log_path
        facts = profile_facts(profile)
        self._base = redact(documents)[:MAX_DOC_CHARS] + (f"\n\nPROFILE FACTS:\n{facts}" if facts else "")
        self.used: Dict[str, Tuple[str, str]] = {}  # question -> (answer, quote), for the run report
        self.declined: List[str] = []  # questions it could not ground in your documents
        self._earlier: Optional[str] = None
        self._entries: List[Earlier] = []
        self.learn(answers or {})

    @property
    def documents(self) -> str:
        """Your documents and profile facts exactly as the AI is shown them (contact details removed)."""
        return self._base

    def learn(self, bank: Mapping[str, str]) -> None:
        """Take the answers you have given so far as part of what it may quote, so a question you answered once is answered
        the same way when it comes back in other words. Called again whenever you answer something while a run is going; a
        verdict made on the old words is not reused (the fingerprint changes), so a question it could not answer before is
        asked again now that it knows more."""
        entries = earlier_entries(bank)
        everything = redact("\n".join(entry.line for entry in entries))
        if everything == self._earlier:
            return
        self._earlier, self._entries = everything, entries
        self.corpus, self._ids = self._compose(most_relevant(entries, ""))  # what the other helpers read: the first that fit
        self.fingerprint = hashlib.sha256((self._base + "\n" + everything).encode("utf-8")).hexdigest()[:12]
        self._cache = self._load_cache()

    def _compose(self, chosen: Sequence[Earlier]) -> Tuple[str, Dict[str, Earlier]]:
        """The documents plus these earlier answers, each given an id the AI can name instead of copying the line."""
        ids = {f"A{number}": entry for number, entry in enumerate(chosen, 1)}
        lines = [redact(f"[{name}] {entry.line}") for name, entry in ids.items()]
        return self._base + (f"\n\n{EARLIER_HEADING}:\n" + "\n".join(lines) if lines else ""), ids

    # -- the one public move ---------------------------------------------------------------------
    def __call__(self, question: str, options: Optional[Sequence[str]] = None) -> Optional[str]:
        question = question.strip()
        key = self._key(question, options)
        verdict = self._cache.get(key)
        if verdict is None:
            verdict = self._ask(question, options)
            if verdict is None:  # could not ask (daily limit, network): remember nothing
                self._note(question, Verdict(None, reason="the AI could not be asked"))
                return None
            self._cache[key] = verdict
            self._log(question, options, verdict)
        self._note(question, verdict)
        return verdict.answer

    # -- asking and checking ---------------------------------------------------------------------
    def _ask(self, question: str, options: Optional[Sequence[str]]) -> Optional[Verdict]:
        if self.client.remaining <= 0:
            return None
        choices = json.dumps(list(options), ensure_ascii=False) if options else "none (free text)"
        corpus, ids = self._compose(most_relevant(self._entries, question))  # the answers most like THIS question, not just the first ones
        prompt = f"CANDIDATE DOCUMENTS:\n<<<\n{corpus}\n>>>\n\nQUESTION: {question}\nOPTIONS: {choices}"
        try:
            reply = extract_json(self.client.complete(SYSTEM, prompt, json_mode=True))
        except BudgetExceeded:
            return None
        except LlmError as exc:
            log.warning("AI helper could not answer %r: %s", question[:60], exc)
            return None
        return self.check(reply, options, corpus, ids, question)

    def check(self, reply: object, options: Optional[Sequence[str]], corpus: Optional[str] = None,
              ids: Optional[Mapping[str, Earlier]] = None, question: str = "") -> Verdict:
        """Accept an answer only if it is backed by your own words."""
        if not isinstance(reply, dict):
            return Verdict(None, reason="the reply was not a JSON object")
        answer, evidence = reply.get("answer"), str(reply.get("evidence") or "").strip()
        if isinstance(answer, bool):
            answer = "Yes" if answer else "No"
        if answer is None or not str(answer).strip():
            return Verdict(None, reason="your documents do not say")
        answer = str(answer).strip()
        if len(answer) > MAX_ANSWER_CHARS:
            return Verdict(None, evidence, "the answer was too long")
        corpus = self.corpus if corpus is None else corpus
        ids = self._ids if ids is None else ids
        if personal_conflict(question, ids):
            return Verdict(None, evidence, "your saved answers disagree about a personal question: only you can settle it")
        saved = ids.get(str(reply.get("source") or "").strip().strip("[]").upper())
        if saved is not None and same_answer(answer, redact(saved.answer)):
            evidence = saved.line[2:]  # named, not copied: it is one of your own saved answers, and the answer is that answer
        else:
            if len(evidence) < MIN_EVIDENCE_CHARS or squash(evidence) not in squash(corpus):
                return Verdict(None, evidence, "the quote is not in your documents")
            invented = [n for n in NUMBER.findall(answer) if n not in set(NUMBER.findall(corpus))]
            if invented:
                return Verdict(None, evidence, f"number(s) {', '.join(invented)} are not in your documents")
        if options:
            chosen = pick_option(answer, options)
            if chosen is None:
                return Verdict(None, evidence, "the answer matches none of the choices")
            answer = chosen
        return Verdict(answer, evidence)

    # -- memory and audit trail ------------------------------------------------------------------
    @staticmethod
    def _key(question: str, options: Optional[Sequence[str]]) -> str:
        return normalize(question) + "|" + "|".join(options or [])

    def _note(self, question: str, verdict: Verdict) -> None:
        if verdict.answer:
            self.used[question] = (verdict.answer, verdict.evidence)
        elif question not in self.declined:
            self.declined.append(question)

    def _log(self, question: str, options: Optional[Sequence[str]], verdict: Verdict) -> None:
        record = {
            "when": datetime.now().isoformat(timespec="seconds"), "portal": self.portal, "docs": self.fingerprint,
            "question": question, "options": list(options or []), "accepted": verdict.answer is not None,
            "answer": verdict.answer, "evidence": verdict.evidence, "reason": verdict.reason,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load_cache(self) -> Dict[str, Verdict]:
        """Earlier verdicts on THESE documents are reused: the same question is not paid for twice."""
        cache: Dict[str, Verdict] = {}
        if not self.log_path.exists():
            return cache
        for line in self.log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rec = json.loads(line)
                if rec["docs"] != self.fingerprint:
                    continue
                cache[self._key(rec["question"], rec["options"])] = Verdict(
                    rec["answer"] if rec["accepted"] else None, rec.get("evidence", ""), rec.get("reason", ""))
            except (ValueError, KeyError, TypeError):
                continue  # a damaged line is only a lost cache entry
        return cache


def build_answerer(paths: Paths, profile: Profile, db: Database, portal: str,
                   http: Optional[httpx.Client] = None) -> AiAnswerer:
    settings = load_ai_settings(paths)
    if not settings.configured:
        raise ConfigError("The AI helper is not set up yet. In the control panel (`jobapply panel`) choose AI helper and fill it in.")
    documents = build_documents(paths, profile)
    if not documents.strip():
        raise ConfigError("There is nothing for the AI to read: save your resume in step 2 first.")
    return AiAnswerer(make_client(settings, db, http), profile, documents, paths.ai_log, portal)
