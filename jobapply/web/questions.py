"""Questions a run could not answer for you, and saving your answers to them. No HTTP and no HTML in here.

A run parks a job on a question only you can answer (it is written to the database); you answer it once on the Questions
page, it goes into your answer bank, and every later job that asks the same thing is answered from there. The AI helper
reads the bank too, so it can answer the same question asked in other words; that is why a wrong answer can be taken out again.
With the AI helper on, the other questions that ask the same fact are folded into the answer you just gave (see answer_book).

You can also add a question and its answer yourself, before any job asks it (`add`): it goes into the same bank, so it is used
exactly like an answer given to a waiting question: by wording for a job that asks it, and by the AI helper for the same question put
in other words, whatever the control (radio buttons, tick boxes, a drop-down, a text box).

Answers the AI agent GUESSED are kept apart (see guess_book): listed here for you to check. `keep_guess` makes one your own answer, by
the same road as an answer you add (`add`); `forget_guess` drops it. Answering the question yourself, any way, drops its guess too.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from ..ai_answers import CONSENT
from ..answer_book import AnswerBook
from ..answers import normalize
from ..config import ConfigError, Paths, load_answers, save_answers
from ..db import Database
from ..guess_book import Guess, GuessBook

MAX_ANSWER_CHARS = 600
MAX_QUESTION_CHARS = 300  # a question, not a paragraph: long enough for any form's wording
FIELD_PREFIX = "a:"  # a form field is named for the question it answers: a:<normalised question>


def field_name(norm: str) -> str:
    return FIELD_PREFIX + norm


def waiting(paths: Paths) -> List[Dict[str, Any]]:
    """The questions runs met and could not answer, minus the ones answered since. Read without disturbing a run."""
    if not paths.db.exists():
        return []
    try:
        connection = sqlite3.connect(f"{paths.db.as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(questions)")}
            context = "context" if "context" in columns else "'' AS context"  # a database from before the agent has no such column
            rows = connection.execute(f"SELECT norm, raw, options, portal, {context} FROM questions ORDER BY rowid").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    known = {normalize(question) for question in AnswerBook(paths).wordings()}  # a wording folded into an answer is answered too
    return [{"norm": norm, "raw": raw, "options": json.loads(options) if options else [], "portal": portal or "", "context": context or ""}
            for norm, raw, options, portal, context in rows if norm not in known]


def saved(paths: Paths) -> List[Tuple[str, str]]:
    """Every answer you have given, as (question, answer), for you to look over."""
    return sorted(load_answers(paths.answers).items(), key=lambda item: item[0].lower())


def guesses(paths: Paths) -> List[Guess]:
    """Every answer the AI agent guessed, newest first, for you to look over."""
    return GuessBook(paths.guesses).all()


def forget_guess(paths: Paths, question: str) -> bool:
    """Drop one guess. Only a question really in the book counts: nothing typed can name anything else."""
    return GuessBook(paths.guesses).forget(question)


def keep_guess(paths: Paths, question: str, judge=None) -> bool:
    """Make a guess your own answer: it joins the saved answers exactly as one you typed yourself, and stops being a guess.
    Only a question really in the book counts. False when it is not there, or cannot be kept as an answer."""
    guess = GuessBook(paths.guesses).get(question)
    if guess is None:
        return False
    try:
        add(paths, guess.question, guess.answer, judge)  # also drops the guess: it is answered now
    except NotSaved:
        return False
    return True


def forget(paths: Paths, question: str) -> bool:
    """Take one saved answer out of the bank. Only a question really in it counts: nothing typed can name anything else.
    A job that asks it again will wait for you again."""
    return AnswerBook(paths).forget(question)


def change(paths: Paths, question: str, answer: str) -> bool:
    """Give a saved answer new words. Only a question really in the bank, and never a blank (that is what Remove is for)."""
    answer = answer.strip()[:MAX_ANSWER_CHARS]
    bank = load_answers(paths.answers)
    if not answer or question not in bank:
        return False
    bank[question] = answer
    save_answers(bank, paths.answers)
    return True


def _file(book: AnswerBook, db: Database, raw: str, answer: str, open_questions: Sequence[Mapping[str, Any]],
          skip: Set[str] = frozenset()) -> List[str]:
    """Remember one answer, then stop waiting on its question and on every other wording the AI judged to be the same fact.
    A waiting question that has choices only joins if this answer is one of them. Returns the wordings that joined."""
    leave = set(skip) | {normalize(raw)}
    others = [other for other in open_questions
              if other["norm"] not in leave and (not other["options"] or answer in other["options"])]
    folded = book.remember(raw, answer, [other["raw"] for other in others])  # saved first: nothing is hidden before its answer is safe
    for norm in [normalize(raw), *(normalize(wording) for wording in folded)]:
        db.drop_question(norm)
    return folded


def _drop_guesses(paths: Paths, wordings: Sequence[str]) -> None:
    """You have answered these questions yourself: a guess for any of them is of no use any more."""
    book = GuessBook(paths.guesses)
    for wording in wordings:
        book.forget(wording)


class NotSaved(ConfigError):
    """What is wrong with the question or answer that was typed, as a sentence for the page (or the command line) to show."""


@dataclasses.dataclass
class Added:
    updated: bool  # the question was already saved (in these or other punctuation): its answer was replaced, nothing was duplicated
    folded: List[str]  # other wordings of the same fact that now share this answer (only with the AI helper)
    consent: bool  # a consent wording: the AI is never shown it, so it is used only when a form asks it in these same words


def add(paths: Paths, question: str, answer: str, judge=None) -> Added:
    """Save a question and answer you typed yourself. The same bank, rules and AI helper as every other saved answer: this is only
    another way in. Anything already waiting on this question stops waiting. Raises NotSaved for a blank, a question with no words in
    it, or one too long to be a question; a long answer is cut, as when you edit one."""
    question, answer = " ".join(question.split()), answer.strip()[:MAX_ANSWER_CHARS]
    if not question or not answer:
        raise NotSaved("Type the question and your answer, both.")
    if not normalize(question):
        raise NotSaved("That does not look like a question: it has no words in it.")
    if len(question) > MAX_QUESTION_CHARS:
        raise NotSaved(f"That question is longer than {MAX_QUESTION_CHARS} characters. Copy just the question itself, not the text around it.")
    book = AnswerBook(paths, judge)
    updated = normalize(question) in {normalize(wording) for wording in book.wordings()}
    folded = _file(book, Database(paths.db), question, answer, waiting(paths))
    _drop_guesses(paths, [question, *folded])  # what you said outranks a guess
    return Added(updated, folded, bool(CONSENT.search(question)))


def save(paths: Paths, form: Mapping[str, str], judge=None) -> int:
    """Save the answers typed for questions that are really waiting. Anything else in the form is ignored. Returns how many.
    With a `judge` (the AI helper), the other waiting and saved questions that ask the same fact join each answer, and stop waiting."""
    open_questions = waiting(paths)
    typed = []
    for question in open_questions:
        answer = form.get(field_name(question["norm"]), "").strip()[:MAX_ANSWER_CHARS]
        if answer and (not question["options"] or answer in question["options"]):  # a choice must be one of the choices
            typed.append((question, answer))
    if not typed:
        return 0
    book, db = AnswerBook(paths, judge), Database(paths.db)
    answered = {question["norm"] for question, _ in typed}  # questions answered together never fold into each other
    for question, answer in typed:
        folded = _file(book, db, question["raw"], answer, open_questions, answered)
        _drop_guesses(paths, [question["raw"], *folded])
    return len(typed)
