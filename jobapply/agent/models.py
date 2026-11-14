"""The words the agent thinks in: page kinds, actions, statuses, and what one look at a page contains."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class PageKind(str, Enum):
    JOB_LISTING = "job_listing"
    JOB_DETAILS = "job_details"
    CAREERS_PAGE = "careers_page"
    APPLICATION_FORM = "application_form"
    LOGIN = "login"
    SIGNUP = "signup"
    RESUME_UPLOAD = "resume_upload"
    CANDIDATE_PROFILE = "candidate_profile"
    SCREENING_QUESTIONS = "screening_questions"
    ASSESSMENT = "assessment"
    INTERVIEW_SCHEDULING = "interview_scheduling"
    APPLICATION_REVIEW = "application_review"
    CONFIRMATION = "application_confirmation"
    UNRELATED = "unrelated"

    @property
    def in_application(self) -> bool:
        """A page that is part of filling in an application (as opposed to finding the job or being done)."""
        return self in FORM_KINDS


FORM_KINDS = frozenset({PageKind.APPLICATION_FORM, PageKind.RESUME_UPLOAD, PageKind.CANDIDATE_PROFILE,
                        PageKind.SCREENING_QUESTIONS, PageKind.APPLICATION_REVIEW})


class AppStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    READY = "ready_to_submit"  # a rehearsal stopped at the final Submit: nothing was sent
    SUBMITTED = "submitted"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    REQUIRES_USER = "requires_user_action"
    VERIFICATION_PENDING = "verification_pending"
    DUPLICATE = "duplicate"
    ALREADY_SUBMITTED = "already_submitted"

    @property
    def label(self) -> str:
        return LABELS[self]

    @property
    def open(self) -> bool:
        """Still worth coming back to: the person can resume it."""
        return self in (AppStatus.IN_PROGRESS, AppStatus.READY, AppStatus.INCOMPLETE, AppStatus.REQUIRES_USER)


LABELS = {
    AppStatus.IN_PROGRESS: "In progress", AppStatus.READY: "Ready to submit (rehearsal)", AppStatus.SUBMITTED: "Application Submitted",
    AppStatus.FAILED: "Submission Failed", AppStatus.INCOMPLETE: "Incomplete", AppStatus.REQUIRES_USER: "Requires User Action",
    AppStatus.VERIFICATION_PENDING: "Verification Pending", AppStatus.DUPLICATE: "Duplicate Application",
    AppStatus.ALREADY_SUBMITTED: "Application Already Submitted",
}


class ActionType(str, Enum):
    CLICK_ELEMENT = "CLICK_ELEMENT"
    FILL_FIELD = "FILL_FIELD"
    SELECT_OPTION = "SELECT_OPTION"  # a drop-down choice, a radio button, a tick box (value: the option, or "yes"/"no")
    UPLOAD_FILE = "UPLOAD_FILE"
    SCROLL_PAGE = "SCROLL_PAGE"
    WAIT_FOR_CHANGE = "WAIT_FOR_CHANGE"
    NAVIGATE_BACK = "NAVIGATE_BACK"
    ASK_USER = "ASK_USER"
    VERIFY_SUBMISSION = "VERIFY_SUBMISSION"
    COMPLETE = "COMPLETE"


NEEDS_TARGET = frozenset({ActionType.CLICK_ELEMENT, ActionType.FILL_FIELD, ActionType.SELECT_OPTION, ActionType.UPLOAD_FILE})


@dataclass
class Action:
    """One step the agent proposes. Whoever proposed it (rules or the AI), it is checked by guard.py before anything happens."""

    type: ActionType
    ref: Optional[int] = None  # the element, as numbered in the latest Observation
    strategy: str = "ref"  # how the target is named: "ref" (its number) or "label" (its accessible name, which must be unique)
    label: str = ""  # the target's name, for the log and for strategy "label"
    value: str = ""
    reason: str = ""
    expected: str = ""  # what should be true afterwards: checked against the next look at the page
    confidence: float = 1.0
    submits: bool = False  # pressing this may send the application: needs the person's approval
    source: str = "rules"  # "rules" or "ai"

    def describe(self) -> str:
        target = f" '{self.label}'" if self.label else ""
        return f"{self.type.value}{target}" + (f" ({self.reason})" if self.reason else "")


@dataclass
class Element:
    ref: int
    tag: str
    role: str = ""
    type: str = ""
    name: str = ""  # the accessible name: what a person would call it
    value: str = ""
    required: bool = False
    disabled: bool = False
    checked: bool = False
    invalid: bool = False
    options: List[str] = field(default_factory=list)
    group: str = ""  # radio buttons and tick boxes that answer one question share this
    legend: str = ""  # that question's own words
    in_modal: bool = False
    region: str = "body"  # "main" (inside a form or main), "chrome" (navigation, header, footer) or "body"
    href: str = ""
    placeholder: str = ""
    popup: bool = False  # a custom drop-down (a combobox or listbox) rather than a native <select>

    @property
    def is_file(self) -> bool:
        return self.type == "file"

    @property
    def is_radio(self) -> bool:
        return self.type == "radio" or self.role == "radio"

    @property
    def is_choice(self) -> bool:
        return self.type in ("radio", "checkbox") or self.role in ("radio", "checkbox", "switch")

    @property
    def is_field(self) -> bool:
        if self.tag == "select" or self.popup or self.is_choice or self.is_file:
            return True
        if self.tag == "textarea" or self.role in ("textbox", "searchbox") or self.type == "contenteditable":
            return True
        return self.tag == "input" and self.type not in ("button", "submit", "reset", "image", "hidden")

    @property
    def is_button(self) -> bool:
        return not self.is_field and (self.tag in ("button", "summary") or self.role in ("button", "tab")
                                      or self.type in ("button", "submit") or (self.tag == "a" and bool(self.href)))

    @property
    def filled(self) -> bool:
        if self.is_choice:
            return self.checked
        return bool(self.value.strip())

    @property
    def question(self) -> str:
        return (self.legend or self.name or self.placeholder).strip()


@dataclass
class JobInfo:
    title: str = ""
    company: str = ""
    location: str = ""
    job_id: str = ""
    employment_type: str = ""
    experience: str = ""
    description: str = ""
    url: str = ""

    @property
    def known(self) -> bool:
        return bool(self.title or self.company)

    def context(self) -> str:
        """\"Acme: Backend Engineer\", or whatever of that is known: shown beside a question so you know which job asks."""
        return ": ".join(part for part in (self.company, self.title) if part)

    def merge(self, other: "JobInfo") -> None:
        """Take what `other` knows and this does not: facts already found are never replaced by a guess."""
        for name in ("title", "company", "location", "job_id", "employment_type", "experience", "description", "url"):
            if not getattr(self, name) and getattr(other, name):
                setattr(self, name, getattr(other, name))


@dataclass
class PageInfo:
    kind: PageKind
    confidence: float
    source: str = "rules"
    job: JobInfo = field(default_factory=JobInfo)
    reason: str = ""


@dataclass
class Observation:
    """One look at the page: what is on it, in the order and size an AI can read."""

    url: str
    title: str = ""
    description: str = ""
    text: str = ""
    headings: List[str] = field(default_factory=list)
    elements: List[Element] = field(default_factory=list)
    modal_text: str = ""
    has_modal: bool = False
    job_posting: Dict[str, str] = field(default_factory=dict)  # the page's own structured data, when it publishes any
    alerts: List[str] = field(default_factory=list)  # what the page itself flags as an error or notice

    def find(self, ref: Optional[int]) -> Optional[Element]:
        return next((e for e in self.elements if e.ref == ref), None)

    def scope(self) -> List[Element]:
        """What the next step is about: an open modal if there is one, else the page's own content (not its navigation)."""
        if self.has_modal:
            return [e for e in self.elements if e.in_modal]
        content = [e for e in self.elements if e.region != "chrome"]
        return content or self.elements

    def signature(self) -> str:
        """A short fingerprint: equal before and after an action means the page did not react."""
        state = "|".join(f"{e.name}:{e.value}:{e.checked}" for e in self.elements[:80])
        return hashlib.sha1(f"{self.url}|{self.title}|{self.text[:400]}|{state}".encode()).hexdigest()[:16]

    def brief(self, limit: int = 70) -> str:
        """The page in a few hundred words: for an AI, never the page itself. Values are hidden: only whether a field is filled."""
        lines = [f"URL: {self.url}", f"Title: {self.title}"]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings[:6]))
        lines.append("Text: " + self.text[:1200].replace("\n", " "))
        if self.alerts:
            lines.append("Alerts: " + " | ".join(self.alerts[:4]))
        scope = self.scope()
        lines.append("Open modal: yes" if self.has_modal else "Open modal: no")
        for e in scope[:limit]:
            kind = e.role or e.type or e.tag
            flags = " required" if e.required else ""
            flags += " filled" if e.filled and not e.is_button else ""
            flags += " DISABLED" if e.disabled else ""
            flags += " INVALID" if e.invalid else ""
            options = f" options={e.options[:8]}" if e.options else ""
            asked = f"{e.legend[:80]} -> {e.name[:60]}" if e.is_choice and e.legend else (e.question or e.name)[:80]
            lines.append(f"[{e.ref}] {kind} \"{asked}\"{flags}{options}")
        return "\n".join(lines)
