"""The only place an LLM is called at run time.

Speaks to OpenRouter, OpenAI and Gemini (all "chat/completions"), to Claude ("messages") and to a local
Ollama ("api/chat"), or to any AI that speaks one of those. `LlmClient` is one AI; `FailoverClient` is a list of them
that moves on to the next when one errors.
Budget-aware: every HTTP attempt (even failures) is counted against the daily cap,
because free tiers count them too.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Tuple

import httpx

from .db import Database

BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_NUM_CTX = 16384  # Ollama's own default window is tiny and would silently cut off your documents
OLLAMA_TIMEOUT_S = 180  # the first request has to load the model into memory
MAX_SWITCH_NOTES = 20  # a run reports its switches; a long outage must not grow that list without end

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status  # the HTTP status when there was one: it tells a full quota from a wrong key


class BudgetExceeded(LlmError):
    pass


def extract_json(text: str):
    cleaned = re.sub(r"```(?:json)?", "", text or "")
    start = cleaned.find("{")
    if start < 0:
        raise LlmError("no JSON object in model reply")
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except ValueError as exc:
        raise LlmError(f"bad JSON from model: {exc}") from exc
    return obj


class LlmClient:
    def __init__(
        self,
        db: Database,
        daily_cap: int,
        *,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
        base_url: str = BASE_URL,
        style: str = "openai",
        temperature: Optional[float] = 0,
        require_key: Optional[bool] = None,
        http: Optional[httpx.Client] = None,
    ):
        self.db = db
        self.daily_cap = daily_cap
        self.api_key = api_key or ""
        self.models = list(models or [])
        self.base_url = base_url.rstrip("/")
        self.style, self.temperature = style, temperature
        self.require_key = style != "ollama" if require_key is None else require_key  # None: the format decides; a local server may need no key
        self.switches: List[str] = []  # one AI has nothing to switch to; here so every client can be asked, as FailoverClient's can
        self.http = http or httpx.Client(timeout=OLLAMA_TIMEOUT_S if style == "ollama" else 60)

    @property
    def configured(self) -> bool:
        return bool((self.api_key or not self.require_key) and self.models)

    @property
    def remaining(self) -> int:
        return max(0, self.daily_cap - self.db.llm_calls_today())

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1024) -> str:
        """max_tokens: how long a reply may be. Only Claude's API makes the caller say; the others have their own limits."""
        if not self.configured:
            raise LlmError("the AI helper is not set up: it needs a model (and a key, unless it is Ollama)")
        last, status = "", None
        for model in self.models:  # first = primary, rest = fallbacks
            if self.remaining <= 0:
                raise BudgetExceeded(f"daily LLM cap of {self.daily_cap} reached")
            self.db.record_llm_call()
            url, headers, body = self._request(model, system, user, json_mode, max_tokens)
            try:
                response = self.http.post(url, headers=headers, json=body)
                response.raise_for_status()
                return self._text(response.json())
            except httpx.HTTPStatusError as exc:
                last, status = f"HTTP {exc.response.status_code}: {self._scrub(exc.response.text)[:200]}", exc.response.status_code
            except httpx.ConnectError:
                last, status = f"could not connect to {self.base_url}: is it running?", None
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last, status = f"{type(exc).__name__}: {self._scrub(str(exc))}", None
        raise LlmError(f"all models failed: {last}", status)

    def _request(self, model: str, system: str, user: str, json_mode: bool = False, max_tokens: int = 1024):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.style == "ollama":
            options = {"num_ctx": OLLAMA_NUM_CTX}
            if self.temperature is not None:
                options["temperature"] = self.temperature
            body = {"model": model, "stream": False, "messages": messages, "options": options}
            if json_mode:
                body["format"] = "json"  # a small local model is far likelier to answer in valid JSON
            return f"{self.base_url}/api/chat", {}, body
        if self.style == "anthropic":
            headers = {"anthropic-version": "2023-06-01", **({"x-api-key": self.api_key} if self.api_key else {})}
            body = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
            if self.temperature is not None:
                body["temperature"] = self.temperature
            return f"{self.base_url}/messages", headers, body
        body = {"model": model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}  # a server that needs no key gets no header
        return f"{self.base_url}/chat/completions", headers, body

    def _text(self, data) -> str:
        if self.style == "ollama":
            return data["message"]["content"]
        if self.style == "anthropic":
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        return data["choices"][0]["message"]["content"]

    def _scrub(self, text: str) -> str:
        """Error text is shown to people and logged: never let the key ride along in it."""
        return text.replace(self.api_key, "***") if self.api_key else text


class Completer(Protocol):
    """What every AI feature needs from a client: ask, and know how many requests are left today. `switches` is what the
    run report says about AIs that errored (always empty for one AI)."""

    switches: List[str]

    @property
    def remaining(self) -> int: ...

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1024) -> str: ...


def rest_seconds(status: Optional[int]) -> int:
    """How long to leave an AI alone after it errored. Asking again at once only wastes a request that is counted against
    the daily limit: so long when waiting cannot help (wrong key, no such model), shorter for a full quota, short for a blip."""
    if status in (401, 403, 404):
        return 3600
    if status == 429:
        return 600
    return 60


class FailoverClient:
    """Several AIs in order of preference. A request goes to the first one that is not resting; if it errors, to the next.

    The one that errored rests for a while (`rest_seconds`), so later requests go straight to the one that works, and the
    first is tried again by itself once its rest is over. If every AI is resting they are all tried anyway: one may have
    recovered. A reached daily limit is not an AI's error (the limit covers all of them) and is raised as it is.
    Every switch is kept in `switches` for the run report; `last_label` says who answered last."""

    def __init__(self, legs: Sequence[Tuple[str, LlmClient]], clock: Callable[[], float] = time.monotonic):
        self.legs = list(legs)  # (what to call it in messages, the client)
        self._clock = clock
        self._resting_until: Dict[int, float] = {}
        self.switches: List[str] = []
        self.last_label = ""

    @property
    def configured(self) -> bool:
        return any(client.configured for _, client in self.legs)

    @property
    def remaining(self) -> int:
        return self.legs[0][1].remaining if self.legs else 0  # one daily limit, kept in one database, for all of them

    def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 1024) -> str:
        if not self.legs:
            raise LlmError("the AI helper is not set up: it needs a model (and a key, unless it is Ollama)")
        order = self._order()
        failures: List[Tuple[str, LlmError]] = []
        for position, index in enumerate(order):
            label, client = self.legs[index]
            try:
                text = client.complete(system, user, json_mode=json_mode, max_tokens=max_tokens)
            except BudgetExceeded:
                raise
            except LlmError as exc:
                failures.append((label, exc))
                self._rest(index, exc, [self.legs[i][0] for i in order[position + 1:]])
                continue
            if not text.strip() and position < len(order) - 1:  # an empty reply is a fault too, if there is another to ask
                exc = LlmError("it sent an empty reply")
                failures.append((label, exc))
                self._rest(index, exc, [self.legs[i][0] for i in order[position + 1:]])
                continue
            self.last_label = label
            return text
        if len(failures) == 1:
            raise failures[0][1]  # only one was asked: its own message says it best
        raise LlmError("every AI failed: " + "; ".join(f"{label}: {exc}" for label, exc in failures), failures[-1][1].status)

    def _order(self) -> List[int]:
        now = self._clock()
        ready = [i for i in range(len(self.legs)) if self._resting_until.get(i, 0) <= now]
        return ready or list(range(len(self.legs)))

    def _rest(self, index: int, exc: LlmError, next_up: List[str]) -> None:
        label = self.legs[index][0]
        self._resting_until[index] = self._clock() + rest_seconds(exc.status)
        note = f"{label} failed ({' '.join(str(exc).split())[:160]})" + (f"; asking {next_up[0]} instead." if next_up else ".")
        log.warning("AI switch: %s", note)
        if len(self.switches) < MAX_SWITCH_NOTES:
            self.switches.append(note)
