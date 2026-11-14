"""Decide what kind of page this is, and which job it is about, from the page alone: no site names, no addresses.

Cheap rules go first. They say how sure they are, and only a page they are unsure about is shown to an AI (see brain.py).
The page's own structured job data (schema.org JobPosting, which most job pages publish) beats any guess from the text.
"""
from __future__ import annotations

import re
from typing import List

from .labels import APPLY_LABEL, CONFIRMED, SEARCH_BOX, SIDE_WIDGET, SUBMIT_LABEL
from .models import Element, JobInfo, Observation, PageInfo, PageKind

SIGNUP_WORDS = re.compile(r"\b(?:create (?:an |your )?account|sign ?up|register|join now)\b", re.I)
LOGIN_HEADING = re.compile(r"^\W*(?:sign ?in|log ?in|login)\b", re.I)
ASSESSMENT = re.compile(r"\b(?:assessment|coding (?:challenge|test)|online test|take the test|hackerrank|codility)\b", re.I)
SCHEDULING = re.compile(r"\b(?:schedule (?:an |your )?interview|pick a (?:time|slot|date)|book (?:a |your )?(?:slot|time|interview)|calendly)\b", re.I)
APPLICATION_WORDS = re.compile(r"\b(?:appl(?:y|ication|icant)|resume|\bcv\b|cover letter|candidate|notice period|salary|work experience|screening|additional questions|questions from the employer)\b", re.I)
REVIEW = re.compile(r"\b(?:review (?:your )?application|review (?:and|&) submit|please review|summary of your application)\b", re.I)
JOB_BODY = re.compile(r"\b(?:responsibilit\w+|requirements?|qualifications?|about the (?:role|job|position)|job description|what you(?:'ll| will) (?:do|bring)|skills)\b", re.I)
JOB_LINK = re.compile(r"\b(?:engineer|developer|manager|analyst|designer|intern|specialist|consultant|lead|architect|scientist|administrator|associate|executive)\b", re.I)
CAREERS = re.compile(r"\b(?:careers|join our team|open positions|open roles|work with us|current openings)\b", re.I)
JOB_WORDS = re.compile(r"\b(?:jobs?|hiring|careers?|vacanc\w+|openings?|recruit\w+)\b", re.I)
PROFILE_HEADING = re.compile(r"\b(?:your profile|candidate profile|my profile)\b", re.I)
TITLE_SPLIT = re.compile(r"\s+(?:\||-|–|—|at|@)\s+")


def _fillable(scope: List[Element]) -> List[Element]:
    """The boxes of an application: not the site's own search box, a password, nor a bookmark or job-alert sign-up on the side."""
    return [e for e in scope if e.is_field and not e.disabled and e.type != "password"
            and e.type != "search" and e.role != "searchbox" and not SEARCH_BOX.search(e.name + " " + e.placeholder)
            and not SIDE_WIDGET.search(f"{e.name} {e.question} {e.placeholder}")]


def _questions(fields: List[Element]) -> bool:
    """Mostly choices and long answers rather than name-and-contact boxes."""
    asking = [e for e in fields if e.is_choice or e.tag in ("select", "textarea") or "?" in e.question]
    return len(asking) * 2 > len(fields)


def classify(obs: Observation) -> PageInfo:
    scope = obs.scope()
    text = (obs.modal_text if obs.has_modal else obs.text)
    headings = " ".join(obs.headings)
    context = f"{obs.title} {headings} {text[:1500]}"
    fields = _fillable(scope)
    passwords = [e for e in scope if e.type == "password"]
    labels = [e.name for e in scope if e.is_button]
    has_apply = any(APPLY_LABEL.search(label) for label in labels)
    has_submit = any(SUBMIT_LABEL.search(label) for label in labels)
    job = obs.job_posting
    kind, confidence, why = PageKind.UNRELATED, 0.5, "nothing on the page is about a job"

    if CONFIRMED.search(text) and len(fields) <= 1:
        kind, confidence, why = PageKind.CONFIRMATION, 0.9, "the page says the application was received"
    elif len(passwords) >= 2 or (passwords and SIGNUP_WORDS.search(context)):
        kind, confidence, why = PageKind.SIGNUP, 0.85, "it asks to create an account"
    elif passwords or (LOGIN_HEADING.search(headings) and len(fields) <= 3 and not APPLICATION_WORDS.search(text[:600])):
        kind, confidence, why = PageKind.LOGIN, 0.85 if passwords else 0.7, "it asks to sign in"
    elif ASSESSMENT.search(context) and len(fields) <= 3:
        kind, confidence, why = PageKind.ASSESSMENT, 0.7, "it is a test or assessment"
    elif SCHEDULING.search(context) and len(fields) <= 3:
        kind, confidence, why = PageKind.INTERVIEW_SCHEDULING, 0.7, "it is about booking an interview time"
    elif fields and (APPLICATION_WORDS.search(context) or obs.has_modal or len(fields) >= 4) and (
            len(fields) >= 2 or obs.has_modal or any(e.is_file for e in fields)):  # one stray box (a newsletter) is not an application
        if any(e.is_file for e in fields) and len(fields) <= 3:
            kind, why = PageKind.RESUME_UPLOAD, "it asks for a resume"
        elif REVIEW.search(context) and has_submit:
            kind, why = PageKind.APPLICATION_REVIEW, "it asks to review the application before sending"
        elif _questions(fields):
            kind, why = PageKind.SCREENING_QUESTIONS, "it asks questions"
        else:
            kind, why = PageKind.APPLICATION_FORM, "it is a form with the details of an application"
        confidence = 0.8
    elif REVIEW.search(context) and has_submit:
        kind, confidence, why = PageKind.APPLICATION_REVIEW, 0.75, "it asks to review the application before sending"
    elif job or (has_apply and JOB_BODY.search(text)):
        kind, confidence, why = PageKind.JOB_DETAILS, 0.9 if job else 0.75, "it describes one job"
    elif sum(1 for e in scope if e.tag == "a" and e.href and JOB_LINK.search(e.name)) >= 6:
        kind, confidence, why = PageKind.JOB_LISTING, 0.65, "it lists many jobs"
    elif CAREERS.search(f"{obs.title} {headings}"):
        kind, confidence, why = PageKind.CAREERS_PAGE, 0.6, "it is a careers page"
    elif PROFILE_HEADING.search(headings) and fields:
        kind, confidence, why = PageKind.CANDIDATE_PROFILE, 0.6, "it is a candidate profile"
    elif JOB_WORDS.search(context) or has_apply:
        confidence, why = 0.4, "it mentions jobs but is not clearly one"
    return PageInfo(kind, confidence, "rules", extract_job(obs, kind), why)


def extract_job(obs: Observation, kind: PageKind) -> JobInfo:
    """The job this page is about: its own structured data first, then the heading and title; nothing is invented."""
    data = obs.job_posting
    job = JobInfo(**{k: v for k, v in data.items() if k in JobInfo.__dataclass_fields__})
    job.url = job.url or obs.url
    if kind is PageKind.UNRELATED or kind is PageKind.LOGIN or kind is PageKind.SIGNUP:
        return job
    parts = TITLE_SPLIT.split(obs.title) if obs.title else []
    if not job.title and kind in (PageKind.JOB_DETAILS, PageKind.APPLICATION_FORM) and obs.headings:
        job.title = obs.headings[0][:120]
    if not job.company and len(parts) >= 2:
        job.company = parts[-1].strip()[:80]
    if not job.description and kind is PageKind.JOB_DETAILS:
        job.description = obs.text[:3000]
    return job
