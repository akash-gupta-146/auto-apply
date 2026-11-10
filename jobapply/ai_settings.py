"""The AI helper's settings and the documents it may read. Everything lives in data/, never in the zip.

* data/ai.yaml        which AI, which model, the key; the backups to ask if it errors; the AIs you added yourself
* data/about/         extra documents about you (a LinkedIn "Save to PDF", project write-ups, notes.txt)
* your resume         always included
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import yaml

from .config import ConfigError, Paths, Profile
from .db import Database
from .llm import FailoverClient, LlmClient, LlmError
from .resume import read_text

NOTES_FILE = "notes.txt"
DEFAULT_DAILY_CAP = 60


@dataclass(frozen=True)
class Provider:
    label: str
    base_url: str
    style: str  # "openai" = POST /chat/completions, "anthropic" = POST /messages, "ollama" = POST /api/chat
    temperature: Optional[float]  # None = do not send one (some newer OpenAI models reject it)
    key_page: str
    models_page: str
    model_example: str
    needs_key: bool = True
    key_label: str = "Get a key"
    note: str = ""


PROVIDERS = {
    "anthropic": Provider(
        "Claude (Anthropic)", "https://api.anthropic.com/v1", "anthropic", 0,
        "https://console.anthropic.com/settings/keys", "https://docs.anthropic.com/en/docs/about-claude/models",
        "claude-3-5-haiku-latest"),
    "openai": Provider(
        "ChatGPT (OpenAI)", "https://api.openai.com/v1", "openai", None,
        "https://platform.openai.com/api-keys", "https://platform.openai.com/docs/models", "gpt-4o-mini"),
    "gemini": Provider(
        "Gemini (Google)", "https://generativelanguage.googleapis.com/v1beta/openai", "openai", 0,
        "https://aistudio.google.com/apikey", "https://ai.google.dev/gemini-api/docs/models", "gemini-2.0-flash"),
    "openrouter": Provider(
        "OpenRouter (has free models)", "https://openrouter.ai/api/v1", "openai", 0,
        "https://openrouter.ai/keys", "https://openrouter.ai/models?max_price=0", "for free use, pick an id ending in :free"),
    "ollama": Provider(
        "Ollama (free, runs on your own computer)", "http://127.0.0.1:11434", "ollama", 0,
        "https://ollama.com/download", "https://ollama.com/library", "llama3.1:8b",
        needs_key=False, key_label="Install it",
        note="No key needed, and nothing you send leaves this computer. After installing, run ollama pull followed by "
             "the model name, and keep Ollama running. Small local models are less reliable, so expect more questions "
             "to be left for you."),
}


@dataclass
class Backup:
    """An AI to ask when the one before it in the list errors."""
    provider: str = ""
    model: str = ""
    api_key: str = ""

    @property
    def masked_key(self) -> str:
        return mask_key(self.api_key)


@dataclass
class CustomProvider:
    """An AI that is not in PROVIDERS, added by the person. It must speak one of the three formats we know (`style`)."""
    label: str
    base_url: str
    style: str = "openai"
    needs_key: bool = True

    def as_provider(self) -> Provider:
        # no temperature: some servers reject one, and an AI that fails every request is worse than a slightly livelier one
        return Provider(self.label, self.base_url, self.style, None, "", "", "", needs_key=self.needs_key and self.style != "ollama")


@dataclass(frozen=True)
class Connection:
    """One AI that can be asked: a provider, one of its models, and the key for it."""
    provider: Provider
    model: str
    api_key: str

    @property
    def label(self) -> str:
        return f"{self.provider.label}, {self.model}"


def mask_key(key: str) -> str:
    return f"ends in {key[-4:]}" if len(key) >= 8 else ""


@dataclass
class AiSettings:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    daily_cap: int = DEFAULT_DAILY_CAP
    backups: List[Backup] = field(default_factory=list)  # asked in this order when the AI before them errors
    custom: Dict[str, CustomProvider] = field(default_factory=dict)  # AIs added by the person, by id

    def providers(self) -> Dict[str, Provider]:
        """Every AI that can be chosen: the built-in ones, then the ones the person added."""
        return {**PROVIDERS, **{key: custom.as_provider() for key, custom in self.custom.items()}}

    @staticmethod
    def _usable(provider: Optional[Provider], model: str, key: str) -> bool:
        return provider is not None and bool(model.strip()) and (bool(key.strip()) or not provider.needs_key)

    @property
    def configured(self) -> bool:
        return self._usable(self.providers().get(self.provider), self.model, self.api_key)

    def connections(self) -> List[Connection]:
        """The AIs that can be asked, the main one first. Empty when the main one is not set up: backups never stand in for it."""
        if not self.configured:
            return []
        providers = self.providers()
        chain = [Connection(providers[self.provider], self.model.strip(), self.api_key)]
        chain += [Connection(providers[b.provider], b.model.strip(), b.api_key)
                  for b in self.backups if self._usable(providers.get(b.provider), b.model, b.api_key)]
        return chain

    @property
    def summary(self) -> str:
        """The AI in a few words, for the panel and the command line."""
        chain = self.connections()
        if not chain:
            return ""
        more = len(chain) - 1
        return chain[0].label + (f" (+{more} backup{'' if more == 1 else 's'})" if more else "")

    @property
    def masked_key(self) -> str:
        return mask_key(self.api_key)


def _entries(raw, cls) -> list:
    """Read a saved list or table of `cls`. An entry that is damaged is dropped: a bad entry must not lose the rest."""
    items = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    kept = []
    for item in items:
        try:
            kept.append(cls(**{k: v for k, v in item.items() if k in cls.__dataclass_fields__}))
        except (AttributeError, TypeError):
            continue
    return kept


def load_ai_settings(paths: Paths) -> AiSettings:
    if not paths.ai.exists():
        return AiSettings()
    data = yaml.safe_load(paths.ai.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return AiSettings()
    plain = {k: v for k, v in data.items() if k in ("provider", "model", "api_key", "daily_cap")}
    custom_raw = data.get("custom") if isinstance(data.get("custom"), dict) else {}
    custom = {key: entry for key, raw in custom_raw.items() for entry in _entries([raw], CustomProvider)}
    return AiSettings(**plain, backups=_entries(data.get("backups"), Backup), custom=custom)


def save_ai_settings(settings: AiSettings, paths: Paths) -> None:
    paths.home.mkdir(parents=True, exist_ok=True)
    paths.ai.write_text(yaml.safe_dump(asdict(settings), sort_keys=False), encoding="utf-8")
    try:
        os.chmod(paths.ai, 0o600)  # the keys are in here: owner only (Windows ignores this)
    except OSError:
        pass


def _client(connection: Connection, db: Database, cap: int, http: Optional[httpx.Client]) -> LlmClient:
    provider = connection.provider
    return LlmClient(
        db, cap, api_key=connection.api_key, models=[connection.model],
        base_url=provider.base_url, style=provider.style, temperature=provider.temperature,
        require_key=provider.needs_key, http=http,
    )


def make_client(settings: AiSettings, db: Database, http: Optional[httpx.Client] = None) -> FailoverClient:
    """The main AI, then each backup: whichever errors, the next is asked. One daily limit covers them all."""
    return FailoverClient([(c.label, _client(c, db, settings.daily_cap, http)) for c in settings.connections()])


def check_one(connection: Connection, http: Optional[httpx.Client] = None) -> str:
    """One tiny request to this AI alone (never to a backup). '' when its key and model work, else a message to act on."""
    try:
        reply = _client(connection, Database(":memory:"), 1, http).complete("You are a connection test.", "Reply with the single word OK.")
    except LlmError as exc:
        message = str(exc)
        if connection.provider.style == "ollama" and "HTTP 404" in message:  # Ollama only says "not found"
            message += f"\nIf that model has not been downloaded yet, run:  ollama pull {connection.model}"
        return message
    return "" if reply and reply.strip() else "The AI answered with nothing. Check the model name."


def check_connection(settings: AiSettings, http: Optional[httpx.Client] = None) -> str:
    """The main AI only. Returns '' when it works, else a message the person can act on."""
    chain = settings.connections()
    return check_one(chain[0], http) if chain else "Choose an AI, a model, and enter a key first."


def check_all(settings: AiSettings, http: Optional[httpx.Client] = None) -> List[Tuple[str, str]]:
    """(name, problem) for the main AI and each backup, every one on its own: '' as the problem means it works."""
    return [(c.label, check_one(c, http)) for c in settings.connections()]


# -- the documents the AI may read --------------------------------------------------------------------
def about_files(paths: Paths) -> List[Path]:
    if not paths.about.exists():
        return []
    return sorted(p for p in paths.about.iterdir() if p.is_file() and p.name != NOTES_FILE)


def read_notes(paths: Paths) -> str:
    notes = paths.about / NOTES_FILE
    return notes.read_text(encoding="utf-8", errors="ignore") if notes.exists() else ""


def save_notes(paths: Paths, text: str) -> None:
    paths.about.mkdir(parents=True, exist_ok=True)
    (paths.about / NOTES_FILE).write_text(text.strip() + "\n" if text.strip() else "", encoding="utf-8")


def build_documents(paths: Paths, profile: Profile) -> str:
    """Resume + extra documents + notes, labelled, as the one text the AI is allowed to read."""
    blocks: List[str] = []
    resume = Path(profile.resume_path) if profile.resume_path else None
    if resume is not None and resume.exists():
        blocks.append(f"RESUME ({resume.name}):\n{read_text(resume)}")
    for path in about_files(paths):
        try:
            blocks.append(f"DOCUMENT ({path.name}):\n{read_text(path)}")
        except (ConfigError, OSError, ValueError):
            continue  # a file that cannot be read adds nothing; it was checked when it was added
    notes = read_notes(paths).strip()
    if notes:
        blocks.append(f"NOTES FROM THE CANDIDATE:\n{notes}")
    return "\n\n".join(b for b in blocks if b.strip())
