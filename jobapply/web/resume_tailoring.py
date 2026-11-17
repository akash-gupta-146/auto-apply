"""Tailoring for the Create Resume tab: the changes that would suit a job (some from rules, some from the AI helper, all checked), and making a separate copy
with the ones you accepted. The resume you tailored from is never changed.

The proposals are not kept on the server. When you accept some, the browser sends them back and each one is checked again against the saved resume, so the
checks do not depend on the browser having behaved.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from ..builder import ai as resume_ai
from ..builder import doc as store
from ..builder import match as fit
from ..builder import tailoring
from ..config import Paths
from ..db import Database
from .actions import ActionError

SHOWN_REFUSALS = 6  # of the proposals thrown away, how many are explained to the person (the rest are counted)


class Tailorer:
    def __init__(self, paths: Paths, make_ai: Callable[..., resume_ai.ResumeAi]):
        self.paths, self._make_ai = paths, make_ai

    def propose(self, doc: Mapping, job_text: str, title: str, strength: str, use_ai: bool, extra: List[str]) -> Dict[str, Any]:
        strength = strength if strength in tailoring.STRENGTHS else "keywords"
        facts = fit.evaluate(doc, job_text, title, extra)["skills"]
        have = facts["required"]["matched"] + facts["nice"]["matched"]  # what the job asks for that the resume already shows, in the job's order
        rules = tailoring.skill_order(doc, [name.lower() for name in have]) if strength != "nudge" else []
        result: Dict[str, Any] = {"strength": strength, "ai": False, "ai_note": "", "notes": "", "refused": [], "refused_count": 0}
        ai_changes: List[tailoring.Change] = []
        if use_ai:
            try:
                proposal = self._ask(doc, job_text, strength, have)
                checked = tailoring.check(doc, proposal.changes, strength)
                ai_changes, result["ai"], result["notes"] = checked.changes, True, proposal.notes
                result["refused"] = [{"path": r.path, "why": r.why} for r in checked.refused[:SHOWN_REFUSALS]]
                result["refused_count"] = len(checked.refused)
            except resume_ai.AiUnavailable as exc:
                result["ai_note"] = str(exc)  # the rule-based changes are still offered
        taken = {change.path for change in ai_changes if change.action == "reorder"}
        merged = ai_changes + [change for change in rules if change.path not in taken]
        result["changes"] = [change._replace(id=f"c{n}").as_dict() for n, change in enumerate(merged, start=1)]
        return result

    def _ask(self, doc: Mapping, job_text: str, strength: str, keywords: List[str]) -> resume_ai.Proposal:
        db = Database(self.paths.db)  # the daily limit counts this like any other request
        try:
            return self._make_ai(self.paths, db).propose_tailoring(doc, job_text, strength, keywords)
        finally:
            db.conn.close()

    def make_copy(self, resume_id: object, raw_changes: object, job: Mapping[str, Any], name: str = "") -> Dict[str, Any]:
        """A new resume: the saved one with the accepted changes made, named as you chose (else for the job), remembering the job."""
        base = store.load(self.paths, resume_id)
        checked = tailoring.check(base, raw_changes, "full")  # every strength is allowed here: you chose these, one by one, and each is checked all the same
        if not checked.changes:
            raise ActionError("None of those changes fit the resume as it is now: it has changed since they were suggested. Check the job again.")
        job_title, company = _short(job.get("title")), _short(job.get("company"))
        copy = tailoring.apply(base, checked.changes)
        copy["title"] = name or tailoring.tailored_title(job_title, company)
        copy["job"] = {"title": job_title, "company": company, "url": job.get("url") if isinstance(job.get("url"), str) else ""}
        made = store.create(self.paths, copy)
        asked = len(raw_changes) if isinstance(raw_changes, list) else 0
        return {"resume": made, "applied": len(checked.changes), "skipped": max(0, asked - len(checked.changes))}


def _short(value: object) -> str:
    return value.strip()[:store.LIMITS["short"]] if isinstance(value, str) else ""
