"""Skill vocabulary used to compare job text with the resume (no LLM needed)."""
from __future__ import annotations

import re
from typing import Set

# Ambiguous English words ("go", "c", "r", "rest") are deliberately left out.
VOCAB = sorted(
    """
    python java javascript typescript node.js react angular vue next.js html css sass tailwind redux
    graphql rest-api restful grpc microservices spring spring-boot hibernate django flask fastapi
    c++ c# .net asp.net golang rust kotlin swift scala php laravel ruby rails sql mysql postgresql
    mongodb redis elasticsearch cassandra dynamodb oracle sqlite kafka rabbitmq aws azure gcp docker
    kubernetes terraform ansible jenkins ci/cd git github-actions linux bash hadoop spark pyspark
    airflow dbt snowflake bigquery databricks etl pandas numpy scikit-learn tensorflow pytorch keras
    nlp computer-vision machine-learning deep-learning llm langchain generative-ai openai power-bi
    tableau excel selenium cypress playwright junit pytest jest appium android ios flutter
    react-native unity figma jira agile scrum devops sre prometheus grafana splunk datadog oauth jwt
    websockets system-design data-structures algorithms oop tdd salesforce sap servicenow
    """.split(),
    key=len,
    reverse=True,
)

ALIASES = {
    "react.js": "react",
    "reactjs": "react",
    "nodejs": "node.js",
    "node": "node.js",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
    "js": "javascript",
    "ml": "machine-learning",
    "gen-ai": "generative-ai",
    "ci-cd": "ci/cd",
}

_TERMS = set(VOCAB) | set(ALIASES)
_PATTERN = re.compile(
    r"(?<![\w+#.])("
    + "|".join(
        re.escape(term).replace(r"\-", r"[-\s]")
        for term in sorted(_TERMS, key=len, reverse=True)
    )
    + r")(?![\w+#])",
    re.IGNORECASE,
)


def _canonical(term: str) -> str:
    term = re.sub(r"\s+", "-", term.lower())
    return ALIASES.get(term, term)


def detect_skills(text: str) -> Set[str]:
    """Canonical skills mentioned in text."""
    return {_canonical(m.group(1)) for m in _PATTERN.finditer(text or "")}
