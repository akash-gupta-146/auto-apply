"""Paths and the user-editable YAML files (profile, criteria, answer banks)."""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class ConfigError(Exception):
    """Something the user must fix before a run can start."""


@dataclass
class Paths:
    home: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(Path(os.environ.get("JOBAPPLY_HOME", "data")).expanduser().resolve())

    profile = property(lambda self: self.home / "profile.yaml")
    criteria = property(lambda self: self.home / "criteria.yaml")
    answers = property(lambda self: self.home / "answers.yaml")
    aliases = property(lambda self: self.home / "answer_aliases.yaml")  # other wordings of a saved question -> that question
    db = property(lambda self: self.home / "jobs.db")
    reports = property(lambda self: self.home / "reports")
    failures = property(lambda self: self.home / "failures")
    browser_profile = property(lambda self: self.home / "browser-profile")
    ai = property(lambda self: self.home / "ai.yaml")  # which AI + its key: never shared
    about = property(lambda self: self.home / "about")  # extra documents about you (LinkedIn PDF, notes...)
    ai_log = property(lambda self: self.home / "ai_answers.jsonl")  # every answer the AI was asked for
    ai_fit_log = property(lambda self: self.home / "ai_fit.jsonl")  # every job the AI judged from its description
    prompt_log = property(lambda self: self.home / "ai_prompts.jsonl")  # every pop-up the AI was asked about
    facts_log = property(lambda self: self.home / "ai_facts.jsonl")  # every time the AI was asked whether questions are the same fact
    resume_dir = property(lambda self: self.home / "resume")  # the copy of the resume that was uploaded
    run_log = property(lambda self: self.home / "run.log")

    def ensure(self) -> None:
        for directory in (self.home, self.reports, self.failures):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass
class Profile:
    name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    current_title: str = ""
    current_company: str = ""
    total_experience_years: float = 0.0
    notice_period: str = ""
    current_ctc: str = ""
    expected_ctc: str = ""
    willing_to_relocate: bool = False
    ok_with_onsite: bool = True
    education: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    resume_path: str = ""
    resume_hash: str = ""
    # skill -> years of experience, or null when unknown. Questions about a null skill's years are
    # parked for you, never guessed. Fill these in for the skills you want answered automatically.
    skills: Dict[str, Optional[float]] = field(default_factory=dict)


@dataclass
class Criteria:
    target_roles: List[str] = field(default_factory=list)  # e.g. "backend engineer"
    skip_roles: List[str] = field(default_factory=list)  # e.g. "qa", "sdet"
    locations: List[str] = field(default_factory=list)
    blocked_companies: List[str] = field(default_factory=list)
    similar_roles: bool = True  # also apply to a generic title ("Software Developer") whose text is about target_roles
    keywords: List[str] = field(default_factory=list)  # your own words for a good job: see matching.keyword_evidence
    min_score: int = 10  # 0-100 skill overlap between job text and profile: one bar for every way in, set low on purpose
    min_salary_lpa: Optional[float] = None  # only enforced when a salary is parsable
    # The decision ladder of the proficiently job-search skill (MIT): dealbreakers first, then must-haves, then nice-to-haves.
    # All off by default, so a job is judged exactly as before until you set them.
    dealbreakers: List[str] = field(default_factory=list)  # words that make a job a "never": "unpaid", "clearance", "contract"
    max_years_below: Optional[float] = None  # skip a job whose top experience ask is more than this many years under yours
    max_years_above: Optional[float] = None  # skip a job whose lowest experience ask is more than this many years over yours
    min_fit: str = "Low"  # the lowest rating to apply to: Low (anything that passed), Medium (>=1 nice-to-have) or High (>=2)
    max_applications_per_run: int = 100
    pacing_min_s: float = 20
    pacing_max_s: float = 90
    challenge_wait_s: float = 300  # human-in-the-loop window, then skip
    answer_wait_s: float = 300  # how long a job waits for you to answer a question in the panel, then it is skipped
    poll_s: float = 10
    breaker_threshold: int = 3  # consecutive challenges before backing off
    breaker_backoff_s: float = 1800
    max_consecutive_failures: int = 5  # selectors probably broke -> stop, don't hammer
    indeed_domain: str = "in.indeed.com"


def _load(cls, path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in known})


def _save(obj, path: Path) -> None:
    path.write_text(
        yaml.safe_dump(dataclasses.asdict(obj), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_profile(paths: Paths) -> Profile:
    if not paths.profile.exists():
        raise ConfigError("No profile yet. Run: jobapply init --resume <path-to-resume>")
    return _load(Profile, paths.profile)


def load_criteria(paths: Paths) -> Criteria:
    return _load(Criteria, paths.criteria) if paths.criteria.exists() else Criteria()


def save_profile(profile: Profile, paths: Paths) -> None:
    _save(profile, paths.profile)


def save_criteria(criteria: Criteria, paths: Paths) -> None:
    _save(criteria, paths.criteria)


def load_answers(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items()}


def save_answers(answers: Dict[str, str], path: Path) -> None:
    path.write_text(yaml.safe_dump(answers, sort_keys=True, allow_unicode=True), encoding="utf-8")


def remember_answer(path: Path, question: str, answer: str) -> None:
    """Add one answer to the saved ones, keeping all the others: what a run does when you answer on the portal's own form."""
    answers = load_answers(path)
    answers[question] = answer
    save_answers(answers, path)
