"""The AI helper page: what it asks for, and checking what was typed."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from ..ai_settings import DEFAULT_DAILY_CAP, AiSettings, Backup
from .forms import Field

NOTES_MAX_CHARS = 20_000
MAX_DAILY_CAP = 1000
MAX_BACKUPS = 3

AI_FIELDS = (
    Field("model", "Model name", "text", True,
          "Copy a model name from the provider's model list (linked above). A small, cheap model is plenty."),
    Field("api_key", "API key", "password", False,
          "Paste the key you created. It is saved only in this program's data folder on this computer. "
          "Ollama needs no key: leave this blank."),
    Field("daily_cap", "Most AI requests per day", "integer", True,
          "A safety limit on cost. One question is one request; repeated questions are remembered."),
    Field("notes", "Anything else the AI should know about you", "textarea", False,
          "Optional. Facts in your own words, such as projects, achievements, preferences. "
          "The AI may only use what is written here and in your documents."),
)


@dataclass
class ParsedAi:
    settings: AiSettings
    notes: str
    errors: Dict[str, str]


def backup_fields(n: int) -> Tuple[str, str, str]:
    return f"backup_provider_{n}", f"backup_model_{n}", f"backup_key_{n}"


def _kept_key(existing: AiSettings, slot: int, provider: str, main_provider: str, main_key: str) -> str:
    """A blank key box keeps the key already saved for this same AI in this same slot, or, for another model of the main
    AI's company, the main key. Never a key that belongs to a different AI."""
    saved = existing.backups[slot - 1] if slot <= len(existing.backups) else None
    if saved is not None and saved.provider == provider and saved.api_key:
        return saved.api_key
    return main_key if provider == main_provider else ""


def _parse_backups(raw: Mapping[str, str], existing: AiSettings, main_provider: str, main_model: str,
                   main_key: str) -> Tuple[List[Backup], Dict[str, str]]:
    providers = existing.providers()
    backups: List[Backup] = []
    errors: Dict[str, str] = {}
    asked = [(main_provider, main_model)]  # an AI listed twice would only be asked twice
    for slot in range(1, MAX_BACKUPS + 1):
        name_provider, name_model, name_key = backup_fields(slot)
        chosen, model, key = (raw.get(name, "").strip() for name in (name_provider, name_model, name_key))
        if not (chosen or model or key):
            continue  # an empty row: no backup here
        who = f"Backup {slot}"
        if chosen not in providers:  # typed details are never dropped without a word
            errors[name_provider] = f"{who}: choose which AI to ask, or clear the row."
            continue
        if not model:
            errors[name_model] = f"{who}: model name is required."
        elif (chosen, model) in asked:
            errors[name_model] = f"{who} is the same AI and model as one above it. Use a different model or AI."
        asked.append((chosen, model))
        if not providers[chosen].needs_key:
            key = ""
        elif not key:
            key = _kept_key(existing, slot, chosen, main_provider, main_key)
            if not key:
                errors[name_key] = f"{who}: enter its API key."
        elif re.search(r"\s", key):
            errors[name_key] = f"{who}: the key must not contain spaces or line breaks. Copy it again."
        backups.append(Backup(chosen, model, key))
    return backups, errors


def parse_ai_form(raw: Mapping[str, str], existing: AiSettings) -> ParsedAi:
    errors: Dict[str, str] = {}
    providers = existing.providers()  # the built-in AIs and the ones the person added
    provider = raw.get("provider", "")
    if provider not in providers:
        errors["provider"] = "Choose which AI to use."
    model = raw.get("model", "").strip()
    if not model:
        errors["model"] = "Model name is required."
    key = raw.get("api_key", "").strip()
    needs_key = providers[provider].needs_key if provider in providers else True
    if not needs_key:
        key = ""  # nothing to protect, and a key left over from another AI should not linger
    elif not key and existing.api_key and provider == existing.provider:
        key = existing.api_key  # blank means keep the saved one: but only for the AI it belongs to
    if needs_key and not key:
        errors["api_key"] = ("You changed the AI, so enter its API key." if existing.api_key and provider in providers
                             else "API key is required.")
    elif needs_key and re.search(r"\s", key):
        errors["api_key"] = "The key must not contain spaces or line breaks. Copy it again."
    cap = DEFAULT_DAILY_CAP
    try:
        cap = int(raw.get("daily_cap", "").strip())
        if not 1 <= cap <= MAX_DAILY_CAP:
            raise ValueError
    except ValueError:
        errors["daily_cap"] = f"Most AI requests per day: enter a whole number from 1 to {MAX_DAILY_CAP}."
    notes = raw.get("notes", "").strip()
    if len(notes) > NOTES_MAX_CHARS:
        errors["notes"] = f"Keep the notes under {NOTES_MAX_CHARS:,} characters."
    backups, backup_errors = _parse_backups(raw, existing, provider, model, key)
    errors.update(backup_errors)
    return ParsedAi(AiSettings(provider, model, key, cap, backups, dict(existing.custom)), notes, errors)
