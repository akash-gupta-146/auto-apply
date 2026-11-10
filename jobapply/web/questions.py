"""Questions a run could not answer for you, and saving your answers to them. No HTTP and no HTML in here.

A run parks a job on a question only you can answer (it is written to the database); you answer it once on the Questions
page, it goes into your answer bank, and every later job that asks the same thing is answered from there. The AI helper
reads the bank too, so it can answer the same question asked in other words; that is why a wrong answer can be taken out again.
With the AI helper on, the other questions that ask the same fact are folded into the answer you just gave (see answer_book).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Mapping, Tuple

from ..answer_book import AnswerBook
from ..answers import normalize
from ..config import Paths, load_answers, save_answers
from ..db import Database

MAX_ANSWER_CHARS = 600
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
            rows = connection.execute("SELECT norm, raw, options, portal FROM questions ORDER BY rowid").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    known = {normalize(question) for question in AnswerBook(paths).wordings()}  # a wording folded into an answer is answered too
    return [{"norm": norm, "raw": raw, "options": json.loads(options) if options else [], "portal": portal or ""}
            for norm, raw, options, portal in rows if norm not in known]


def saved(paths: Paths) -> List[Tuple[str, str]]:
    """Every answer you have given, as (question, answer), for you to look over."""
    return sorted(load_answers(paths.answers).items(), key=lambda item: item[0].lower())


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
    answered = {question["norm"] for question, _ in typed}
    for question, answer in typed:
        others = [other for other in open_questions
                  if other["norm"] not in answered and (not other["options"] or answer in other["options"])]  # it must fit their choices
        folded = book.remember(question["raw"], answer, [other["raw"] for other in others])  # saved first: nothing is hidden before its answer is safe
        for norm in [question["norm"], *(normalize(wording) for wording in folded)]:
            db.drop_question(norm)
    return len(typed)
