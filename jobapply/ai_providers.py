"""Adding an AI that is not in the list, and removing it again. Plain functions: the pages and the tests both use them."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import replace
from typing import Dict, Mapping, Tuple
from urllib.parse import urlsplit

from .ai_settings import AiSettings, CustomProvider

MAX_CUSTOM = 10
MAX_NAME_CHARS = 40
MAX_URL_CHARS = 200
STYLES = {
    "openai": "OpenAI-compatible (most AI services: Groq, Together, Mistral, DeepSeek, LM Studio, vLLM...)",
    "anthropic": "Claude-compatible (Anthropic's own format)",
    "ollama": "Ollama-compatible (a server on your own network)",
}


def _on_own_network(host: str) -> bool:
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def valid_base_url(text: str) -> Tuple[str, str]:
    """(the address to use, a problem). The key is sent to this address, so it must be one the person means."""
    url = text.strip().rstrip("/")
    if len(url) > MAX_URL_CHARS:
        return "", f"That address is too long (up to {MAX_URL_CHARS} characters)."
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port  # a bad port number raises ValueError here, not later
    except ValueError:
        return "", "That does not look like a web address. Example: https://api.example.com/v1"
    if parts.scheme not in ("http", "https") or not host:
        return "", "Start the address with https://, for example https://api.example.com/v1"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "", "Enter only the address, with no login, ? or # part: the key goes in the key box."
    if parts.scheme == "http" and not _on_own_network(host):
        return "", ("Use https:// here. A key sent over plain http can be read by anyone on the way. "
                    "Plain http:// is accepted only for a computer on your own network.")
    return url, ""


def custom_id(label: str, taken: Mapping[str, object]) -> str:
    """A short id for the settings file and the page: letters, digits and hyphens, never one that is already used."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:30].strip("-") or "ai"
    key, number = f"custom-{slug}", 2
    while key in taken:
        key, number = f"custom-{slug}-{number}", number + 1
    return key


def add_custom_provider(settings: AiSettings, raw: Mapping[str, str]) -> Tuple[AiSettings, Dict[str, str]]:
    """The settings with the new AI added, or the settings unchanged and what is wrong (by field name)."""
    errors: Dict[str, str] = {}
    label = " ".join(raw.get("custom_name", "").split())
    known = settings.providers()
    if not label:
        errors["custom_name"] = "Give the AI a name you will recognise."
    elif len(label) > MAX_NAME_CHARS:
        errors["custom_name"] = f"Keep the name under {MAX_NAME_CHARS} characters."
    elif label.lower() in {provider.label.lower() for provider in known.values()}:
        errors["custom_name"] = "There is already an AI with that name."
    elif len(settings.custom) >= MAX_CUSTOM:
        errors["custom_name"] = f"You can add up to {MAX_CUSTOM} AIs. Remove one first."
    url, problem = valid_base_url(raw.get("custom_url", ""))
    if problem:
        errors["custom_url"] = problem
    style = raw.get("custom_style", "openai")
    if style not in STYLES:
        errors["custom_style"] = "Choose which format it speaks."
    if errors:
        return settings, errors
    provider = CustomProvider(label, url, style, needs_key=bool(raw.get("custom_needs_key")) and style != "ollama")
    return replace(settings, custom={**settings.custom, custom_id(label, known): provider}), {}


def remove_custom_provider(settings: AiSettings, key: str) -> Tuple[AiSettings, str]:
    """The settings without that AI (and without any backup that used it), or a reason it cannot go. A key that is not
    one we listed does nothing: a typed id cannot point at anything else."""
    if key not in settings.custom:
        return settings, ""
    if settings.provider == key:
        return settings, (f"{settings.custom[key].label} is your main AI. Choose another main AI and save, then remove it.")
    return replace(settings, custom={k: v for k, v in settings.custom.items() if k != key},
                   backups=[b for b in settings.backups if b.provider != key]), ""
