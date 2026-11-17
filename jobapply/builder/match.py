"""How well a resume lines up with one job, explained: which of the job's requirements the resume shows (with the very line that shows it), what is missing, and
where the title and the years stand. Deterministic, no AI: the same resume and job give the same answer, and every row says why.

This is a comparison of two texts, not a forecast. It cannot know who else applied, what the recruiter looks for, or what is not written down, so it
never says "chance" and never gives a percentage: it gives a band (Strong, Good, Partial, Weak) from the factors listed beside it, and the NOTICE below
goes with every answer. A requirement is only "supported" by something that can be checked on the page: a skill the resume names, the same two-word
phrase, or dates that add up. Related wording alone is "partly", and a row with no evidence says "no evidence found", which is not "you cannot do it".

No HTTP and no HTML in here.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from . import job_facts
from .doc import PRESENT
from .tailor import Lookup, coverage, detect, lookup, pretty

NOTICE = ("This compares the words of your resume with the words of the job. It is not a prediction of whether you would be shortlisted: that depends on who "
          "else applied, what the recruiter is looking for, and things neither of us can see from here.")
WEIGHTS = {"skills": 35, "requirements": 30, "title": 15, "experience": 20}  # the points each factor can earn; a factor that cannot be judged is left out and the rest share its points
BANDS = ((80, "strong", "Strong match"), (60, "good", "Good match"), (40, "partial", "Partial match"), (0, "weak", "Weak match"))
QUOTE_MAX = 160
MIN_OVERLAP = 2  # content words in common before "related wording" is mentioned at all
STATES = {"supported": "ok", "partly": "warn", "none": "bad"}


class Line(NamedTuple):
    pointer: str  # where in the resume (a JSON pointer: the editor can jump to it)
    text: str


def resume_lines(doc: Mapping) -> List[Line]:
    """Every line of the resume that says something about your work, with where it is."""
    lines = [Line("/basics/headline", doc["basics"]["headline"]), Line("/summary", doc["summary"])]
    for i, job in enumerate(doc["experience"]):
        lines.append(Line(f"/experience/{i}/title", " ".join(part for part in (job["title"], job["company"]) if part)))
        lines += [Line(f"/experience/{i}/bullets/{j}", bullet) for j, bullet in enumerate(job["bullets"])]
    for i, entry in enumerate(doc["skills"]):
        lines.append(Line(f"/skills/{i}/items", ": ".join(part for part in (entry["group"], ", ".join(entry["items"])) if part)))
    for i, project in enumerate(doc["projects"]):
        lines += [Line(f"/projects/{i}/bullets/{j}", bullet) for j, bullet in enumerate(project["bullets"])]
    for i, entry in enumerate(doc["education"]):
        lines.append(Line(f"/education/{i}/degree", " ".join(part for part in (entry["degree"], entry["field"]) if part)))
        lines += [Line(f"/education/{i}/details/{j}", detail) for j, detail in enumerate(entry["details"])]
    lines += [Line(f"/certifications/{i}/name", entry["name"]) for i, entry in enumerate(doc["certifications"])]
    return [line for line in lines if line.text.strip()]


def _quote(text: str) -> str:
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX - 1].rstrip() + "…"


# -- years and title -------------------------------------------------------------------------------------------------------------------------
def _month(value: str) -> Optional[int]:
    return int(value[:4]) * 12 + int(value[5:7]) - 1 if re.match(r"^\d{4}-\d{2}$", value or "") else None


def years_of_experience(doc: Mapping, today: Optional[date] = None) -> Optional[float]:
    """The years your jobs add up to, from their dates (months two jobs share are counted once). Nothing if no job has a start date."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans = []
    for job in doc["experience"]:
        start = _month(job["start"])
        end = now if job["end"] in ("", PRESENT) else _month(job["end"])
        if start is not None and end is not None and end >= start:
            spans.append((start, min(end, now)))
    if not spans:
        return None
    months, reach = 0, None
    for start, end in sorted(spans):
        if reach is None or start > reach:
            months, reach = months + (end - start + 1), end
        elif end > reach:
            months, reach = months + (end - reach), end
    return round(months / 12, 1)


def _tokens(text: str) -> List[str]:
    return [job_facts._plain(word) for word in job_facts._words(text)]


TITLE_FILLER = frozenset({"a", "an", "and", "of", "the", "for", "at", "in", "to", "with"})


def _title_words(text: str) -> List[str]:
    """The words of a job title. Short ones (SDE, QA) and level words (senior, lead) count: they are what tells one job from another."""
    return [job_facts._plain(word) for word in re.findall(r"[a-z0-9+#]+", text.lower()) if word not in TITLE_FILLER]


def title_match(doc: Mapping, job_title: str) -> Optional[Dict[str, str]]:
    """Whether the job's title is in your headline or one of your job titles: "yes" (every word of it is), "partly" (half or more), or "no". Nothing if
    the job has no title."""
    wanted = _title_words(job_title)
    if not wanted:
        return None
    titles = [doc["basics"]["headline"]] + [job["title"] for job in doc["experience"]]
    best, shown = 0.0, ""
    for title in titles:
        have = set(_title_words(title))
        share = sum(word in have for word in wanted) / len(wanted)
        if share > best:
            best, shown = share, title
    status = "yes" if best == 1 else "partly" if best >= 0.5 else "no"
    missing = [word for word in wanted if word not in set(_title_words(shown))] if shown else wanted
    detail = {"yes": f'"{shown}" has every word of "{job_title}".', "partly": f'"{shown}" has part of "{job_title}" (not: {", ".join(missing)}).',
              "no": f'Nothing in your headline or job titles resembles "{job_title}".'}[status]
    return {"status": status, "detail": detail, "job_title": job_title}


# -- one requirement against the resume ------------------------------------------------------------------------------------------------------
def _content(text: str) -> List[str]:
    return [word for word in _tokens(text) if word not in job_facts.STOP]


def _phrase_in(words: Sequence[str], haystack: Sequence[str]) -> bool:
    pairs = {(a, b) for a, b in zip(haystack, haystack[1:])}
    return any(pair in pairs for pair in zip(words, words[1:]))


def _showing(skill: str, lines: Sequence[Line], look: Lookup) -> Optional[Line]:
    """The line that best shows a skill: one where you used it (a bullet of a job or project) before a mention in the summary or the skills list."""
    named = [line for line in lines if skill in detect(line.text, look)]
    return next((line for line in named if "/bullets/" in line.pointer), named[0] if named else None)


def judge(req: job_facts.Requirement, lines: Sequence[Line], look: Lookup, years: Optional[float]) -> Dict[str, Any]:
    """One requirement: what the resume shows for it, as a status, the line that shows it (a real line, quoted), where it is, and why."""
    row: Dict[str, Any] = {"text": req.text, "kind": req.kind, "status": "none", "quote": "", "pointer": "", "reason": "No evidence found in your resume."}
    short = years is not None and req.years is not None and years < req.years
    if req.skills:
        found = {skill: _showing(skill, lines, look) for skill in req.skills}
        have = [skill for skill, line in found.items() if line]
        if have:
            where = found[have[0]]
            row.update(quote=_quote(where.text), pointer=where.pointer)
        if len(have) == len(req.skills):
            row.update(status="supported", reason=f"Your resume names {', '.join(pretty(s) for s in have)}.")
        elif have:
            gone = ", ".join(pretty(s) for s in req.skills if s not in have)
            row.update(status="partly", reason=f"Your resume names {', '.join(pretty(s) for s in have)}, but not {gone}.")
        else:
            row["reason"] = f"Your resume does not mention {', '.join(pretty(s) for s in req.skills)}."
    else:
        words = _content(req.text)
        best, score, shared = None, 0, []
        for line in lines:
            have = set(_tokens(line.text))
            common = [word for word in dict.fromkeys(words) if word in have]
            if len(common) > score:
                best, score, shared = line, len(common), common
        if best and _phrase_in(words, _tokens(best.text)):
            row.update(status="supported", quote=_quote(best.text), pointer=best.pointer, reason="Your resume uses the same words for it.")
        elif best and score >= MIN_OVERLAP and score / max(len(set(words)), 1) >= 0.4:
            row.update(status="partly", quote=_quote(best.text), pointer=best.pointer, reason=f"Related wording ({', '.join(shared[:4])}); read it and decide if it covers this.")
    if req.years is not None and years is not None:
        if short:  # the years are not there yet, whatever else the resume shows
            row.update(status="partly" if row["status"] == "supported" else row["status"],
                       reason=f"{row['reason']} It asks for {req.years}+ years and your dated jobs add up to about {years:g}.")
        elif not req.skills and len(set(_content(req.text))) <= 1:  # a requirement that is only about years: the dates are the evidence
            row.update(status="supported", reason=f"Your jobs add up to about {years:g} years.")
    return row


# -- the whole answer ------------------------------------------------------------------------------------------------------------------------
def _factor(fid: str, label: str, detail: str, share: Optional[float]) -> Dict[str, Any]:
    state = "unknown" if share is None else "ok" if share >= 0.8 else "warn" if share >= 0.4 else "bad"
    return {"id": fid, "label": label, "detail": detail, "state": state, "share": share}


def band_for(points: float) -> Tuple[str, str]:
    return next((key, label) for floor, key, label in BANDS if points >= floor)


def evaluate(doc: Mapping, job_text: str, title: str = "", extra: Sequence[str] = (), today: Optional[date] = None) -> Dict[str, Any]:
    """The match of a resume to a job: band, factors, the evidence table, the skills and the words the job repeats. All of it explained, none of it a forecast."""
    look = lookup(extra)
    facts = job_facts.read(job_text, title, look)
    found = coverage(doc, job_text, extra)
    lines = resume_lines(doc)
    years = years_of_experience(doc, today)
    rows = [judge(req, lines, look, years) for req in facts.requirements]
    required = [row for row in rows if row["kind"] == "required"]
    tm = title_match(doc, facts.title)

    shares: Dict[str, Optional[float]] = {"skills": found.ratio, "requirements": None, "title": None, "experience": None}
    if required:
        shares["requirements"] = sum({"supported": 1, "partly": 0.5}.get(row["status"], 0) for row in required) / len(required)
    if tm:
        shares["title"] = {"yes": 1.0, "partly": 0.5, "no": 0.0}[tm["status"]]
    if facts.years is not None and years is not None:
        shares["experience"] = min(1.0, years / facts.years)

    needed, have = len(found.required_matched) + len(found.required_missing), len(found.required_matched)
    factors = [
        _factor("skills", "Skills the job requires", f"{have} of {needed} are in your resume" if needed else "The job names no skills I know", shares["skills"]),
        _factor("requirements", "Requirements shown", f"{sum(r['status'] == 'supported' for r in required)} of {len(required)} supported by your resume"
                if required else "No separate requirements found in the text", shares["requirements"]),
        _factor("title", "Job title", tm["detail"] if tm else "The text does not give a title", shares["title"]),
        _factor("experience", "Years of experience",
                (f"It asks for {facts.years}+; your jobs add up to about {years:g}" if years is not None else f"It asks for {facts.years}+; your jobs have no dates to add up")
                if facts.years is not None else "The text does not say how many years", shares["experience"]),
    ]
    judged = {key: share for key, share in shares.items() if share is not None}
    total = sum(WEIGHTS[key] for key in judged)
    points = round(sum(WEIGHTS[key] * share for key, share in judged.items()) / total * 100) if total else None
    band, label = band_for(points) if points is not None else ("unknown", "Not enough in the job text to judge")
    covered_terms = [item for item in job_facts.other_terms(job_text, skip=[facts.title, doc["basics"]["name"]])]
    have_words = set(_tokens(" ".join(line.text for line in lines)))
    terms = [{**item, "in_resume": all(job_facts._plain(word) in have_words for word in job_facts._words(item["term"]))} for item in covered_terms]
    return {"band": band, "label": label, "factors": factors, "evidence": rows, "skills": found.as_dict(), "terms": terms, "notice": NOTICE,
            "job": {"title": facts.title, "seniority": facts.seniority, "years": facts.years}, "your_years": years}
