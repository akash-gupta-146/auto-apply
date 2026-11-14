"""What a failed job leaves behind, so its cause can be read without running it again.

A picture of the page is not enough: the Naukri failures all look the same in one ("Apply" showing three loading dots) and nothing says
whether Naukri answered, what it answered, or whether a script it needs was refused. So next to the picture goes a small JSON note of
what the page was showing (windows, buttons, spinners, fields it objected to) and what the browser had just heard back from the network.

Everything stays on this computer, in the failures folder, which the panel's "Logs and screenshots of problems" can delete.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List

log = logging.getLogger(__name__)

KEEP = 40  # the last replies and refusals kept: a failure is about what just happened
BODY_CHARS = 800  # of one reply: enough to read an error or a list of questions, not enough to be a copy of someone's data
SENT_BY_SCRIPT = {"fetch", "xhr"}  # what a page's own scripts ask for: the calls that decide whether a form went through

SEEN_JS = """() => {
  const shown = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const words = e => (e.innerText || '').replace(/\\s+/g, ' ').trim();
  const all = selector => [...document.querySelectorAll(selector)].filter(shown);
  return {
    title: document.title,
    windows: all('dialog[open], [role=dialog], [role=alertdialog], [aria-modal=true]').map(e => words(e).slice(0, 600)),
    buttons: all('button, [role=button], input[type=submit], a[role=button]')
      .map(e => words(e) || e.getAttribute('aria-label') || e.value || '(no label)').slice(0, 30),  // a spinner shows as "(no label)"
    busy: all('[aria-busy=true], [role=progressbar], [class*=spinner i], [class*=loading i], [class*=loader i]')
      .map(e => (e.tagName + ' ' + String(e.className && e.className.baseVal === undefined ? e.className : '')).trim().slice(0, 80)).slice(0, 8),
    objections: all('[aria-invalid=true]').map(e => e.getAttribute('aria-label') || e.id || e.name || e.tagName).slice(0, 12),
    notices: all('[role=alert], [role=status]').map(words).filter(Boolean).slice(0, 6),
  };
}"""


class NetworkWatch:
    """The last replies the browser got, in any tab. Holds the reply itself and reads its words only when asked: reading one inside the
    browser's own event could stall the page."""

    def __init__(self, page):
        self._replies: Deque[Any] = deque(maxlen=KEEP)
        self._refused: Deque[Dict[str, str]] = deque(maxlen=KEEP)  # blocked outright: no reply at all (a script the network refused)
        try:
            context = page.context
            # plain functions, not `self._replies.append` or a bound method: Playwright stamps a marker on whatever it is given, and those cannot
            # hold one. It raised, the except below hid it, and nothing was ever watched.
            context.on("response", lambda reply: self._replies.append(reply))
            context.on("requestfailed", lambda request: self._note_refused(request))
        except Exception:  # a stand-in page, or one already closed: no evidence of this kind, and nothing else is the worse for it
            log.warning("not watching the network: %s", "the page has no browser context" if page is None else "could not attach", exc_info=page is not None)

    def _note_refused(self, request) -> None:
        self._refused.append({"method": request.method, "url": _where(request.url), "why": str(request.failure or "")[:120]})

    def report(self) -> Dict[str, List[Dict[str, Any]]]:
        """What matters: anything that was not a plain read (a form going out) and anything that came back as an error."""
        replies = []
        for reply in self._replies:
            try:
                method, status, kind = reply.request.method, reply.status, reply.request.resource_type
                if method == "GET" and status < 400:
                    continue
                entry: Dict[str, Any] = {"method": method, "status": status, "url": _where(reply.url)}
                if kind in SENT_BY_SCRIPT or status >= 400:
                    entry["body"] = _words(reply)
                replies.append(entry)
            except Exception:  # a reply from a tab that has since closed
                continue
        return {"replies": replies, "refused": list(self._refused)}


def _where(url: str) -> str:
    return url.split("?")[0][:160]  # no query string: that is where tokens and ids live, and the address alone says what was asked


def _words(reply) -> str:
    try:
        return " ".join(reply.text().split())[:BODY_CHARS]
    except Exception:
        return "(could not be read)"


def save(path: Path, page, watch: NetworkWatch, url: str, why: str) -> None:
    note: Dict[str, Any] = {"url": url, "why": why, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        note["page"] = page.evaluate(SEEN_JS)
    except Exception as exc:
        note["page"] = {"unreadable": f"{type(exc).__name__}"}
    note["network"] = watch.report()
    path.write_text(json.dumps(note, indent=2, ensure_ascii=False), encoding="utf-8")
