"""Match a resume to a job description: which of the skills it asks for are already in your resume, and which are not. Deterministic, no AI.

The skills are the project's own (skills_vocab.py, the same list the job matcher and your profile use), plus any words you add (your profile's skills
that are not in the list, or words typed into the Create Resume tab). A skill the job asks for and your resume lacks is only ever *reported*: it is never added
for you. `with_skill` adds one, and is only called when you say you really have it.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Collection, Dict, FrozenSet, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ..skills_vocab import _canonical, mentions
from .doc import LIMITS, full_text, normalize

HEADING_MAX = 70  # chars: a short line that does not end like a sentence is a heading ("Nice to have:"), and sets the mode for the lines after it
OTHER_GROUP = "Other skills"  # where a skill you say you have is put
REQUIRED_CUES = ("required", "requirement", "must have", "must-have", "mandatory", "qualification", "you have", "you will need", "what you need",
                 "what we need", "skills", "responsibilit", "you bring", "about you", "looking for", "experience with", "proficien")
NICE_CUES = ("nice to have", "nice-to-have", "good to have", "good-to-have", "preferred", "bonus", "desirable", "optional", "a plus", "is a plus",
             "would be a plus", "added advantage", "advantage")

# How a skill is written on a resume. The list stores them lower case (kubernetes); most just need a capital, these need more.
SPELLINGS = {"aws": "AWS", "gcp": "GCP", "sql": "SQL", "css": "CSS", "html": "HTML", "php": "PHP", "nlp": "NLP", "llm": "LLM", "etl": "ETL", "sre": "SRE",
             "jwt": "JWT", "oop": "OOP", "tdd": "TDD", "sap": "SAP", "ios": "iOS", "ci/cd": "CI/CD", "oauth": "OAuth", ".net": ".NET", "asp.net": "ASP.NET",
             "node.js": "Node.js", "next.js": "Next.js", "graphql": "GraphQL", "grpc": "gRPC", "postgresql": "PostgreSQL", "mysql": "MySQL", "mongodb": "MongoDB",
             "javascript": "JavaScript", "typescript": "TypeScript", "fastapi": "FastAPI", "pytorch": "PyTorch", "tensorflow": "TensorFlow", "dbt": "dbt",
             "github-actions": "GitHub Actions", "power-bi": "Power BI", "pyspark": "PySpark", "dynamodb": "DynamoDB", "rabbitmq": "RabbitMQ",
             "bigquery": "BigQuery", "scikit-learn": "scikit-learn", "sqlite": "SQLite", "servicenow": "ServiceNow", "websockets": "WebSockets",
             "devops": "DevOps", "numpy": "NumPy", "langchain": "LangChain", "openai": "OpenAI", "elasticsearch": "Elasticsearch", "rest-api": "REST API",
             "restful": "RESTful", "junit": "JUnit", "pytest": "pytest", "jira": "Jira", "c++": "C++", "c#": "C#", "databricks": "Databricks", "go": "Go"}


def pretty(skill: str) -> str:
    """A skill as a resume writes it: 'kubernetes' as 'Kubernetes', 'aws' as 'AWS'. A word you typed with capitals of its own (iOS, dbt) keeps them."""
    if skill in SPELLINGS:
        return SPELLINGS[skill]
    return skill.replace("-", " ").title() if skill == skill.lower() else skill


def _clean(word: object) -> str:
    return " ".join(str(word).split())[:LIMITS["item"]]


class Lookup(NamedTuple):
    custom: Tuple[Tuple[str, "re.Pattern[str]"], ...]  # words that are not in the project's list: (the word, how to find it)
    wanted: FrozenSet[str]  # the words you asked for, lower case: required wherever a job names them


def lookup(extra: Sequence[str] = ()) -> Lookup:
    """What to look for besides the project's list. A word the list already knows is not looked for twice, it is only marked as wanted."""
    custom, wanted = [], set()
    for word in extra:
        word = _clean(word)
        if not word:
            continue
        known = mentions(word)
        if len(known) == 1 and known[0][1] == _canonical(word):
            wanted.add(known[0][1])
        elif word.lower() not in wanted:
            wanted.add(word.lower())
            custom.append((word, re.compile(rf"(?<![\w+#]){re.escape(word)}(?![\w+#])", re.I)))
    return Lookup(tuple(custom), frozenset(wanted))


def detect(text: str, look: Lookup = Lookup((), frozenset())) -> List[str]:
    """The skills named in a text (canonical, or as you typed them), each once, in the order they first appear."""
    found = mentions(text) + [(match.start(), name) for name, pattern in look.custom for match in [pattern.search(text)] if match]
    return list(dict.fromkeys(name for _, name in sorted(found)))


class Keywords(NamedTuple):
    required: List[str]
    nice: List[str]


def extract(job_text: str, look: Lookup = Lookup((), frozenset())) -> Keywords:
    """The skills a job names, split into what it requires and what it only prefers. A line (or a heading and what is under it) that says "nice to have",
    "preferred" or "a plus" is the second kind; everything else is the first, and a skill named as required anywhere is required.
    A skill in `look.wanted` (the words you asked to have checked) is required wherever the job names it."""
    mode, required, nice = "required", [], []
    for line in job_text.splitlines():
        text = line.strip()
        if not text:
            continue
        lowered = text.lower()
        heading = len(text) <= HEADING_MAX and not text.endswith((".", ",", ";"))
        if any(cue in lowered for cue in NICE_CUES):
            here = "nice"
            mode = here if heading else mode
        elif heading and any(cue in lowered for cue in REQUIRED_CUES):
            here = mode = "required"
        else:
            here = mode
        for name in detect(text, look):
            (required if here == "required" or name.lower() in look.wanted else nice).append(name)
    required = list(dict.fromkeys(required))
    return Keywords(required, [name for name in dict.fromkeys(nice) if name not in required])


class Coverage(NamedTuple):
    required_matched: List[str]
    required_missing: List[str]
    nice_matched: List[str]
    nice_missing: List[str]

    @property
    def ratio(self) -> Optional[float]:
        """The share of the required skills that the resume has, or None when the job names none (then there is nothing to be short of)."""
        total = len(self.required_matched) + len(self.required_missing)
        return len(self.required_matched) / total if total else None

    def as_dict(self) -> Dict[str, Any]:
        """For the panel, with the skills written as a resume writes them."""
        names = lambda skills: [pretty(skill) for skill in skills]  # noqa: E731
        return {"required": {"matched": names(self.required_matched), "missing": names(self.required_missing)},
                "nice": {"matched": names(self.nice_matched), "missing": names(self.nice_missing)}, "coverage": self.ratio}


def coverage(doc: Mapping, job_text: str, extra: Sequence[str] = ()) -> Coverage:
    """Which skills the job asks for are in the resume, and which are not. The resume is only read, never changed."""
    look = lookup(extra)
    wanted = extract(job_text, look)
    have = set(detect(full_text(doc), look))
    split = lambda names: ([n for n in names if n in have], [n for n in names if n not in have])  # noqa: E731
    return Coverage(*split(wanted.required), *split(wanted.nice))


def with_skill(doc: Mapping, name: str) -> Dict[str, Any]:
    """The resume with one more skill in it. Only for a skill the person has said they really have."""
    updated = copy.deepcopy(dict(doc))
    group = next((entry for entry in updated["skills"] if entry["group"] == OTHER_GROUP), None)
    if group is None:
        group = {"group": OTHER_GROUP, "items": []}
        updated["skills"].append(group)
    group["items"].append(name)
    result = {**{key: doc[key] for key in ("id", "version", "updated") if key in doc}, **normalize(updated)}
    if not any(name.lower() == item.lower() for entry in result["skills"] for item in entry["items"]):
        raise ValueError("That skill could not be added: the skills list is full or the name is empty.")
    return result
