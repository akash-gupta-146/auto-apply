"""The Applications page: what the agent is doing now, what it needs from you, and every application's outcome."""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Mapping
from urllib.parse import urlparse

from .pages import _page, _token

TOTAL_NAMES = (("total", "Applications"), ("submitted", "Submitted"), ("in_progress", "In progress"), ("needs_you", "Need you"),
               ("unconfirmed", "Not confirmed"), ("failed", "Failed"))


def _link(url: str, text: str) -> str:
    """A link to the job, only ever to a web address: a stored address is never trusted to be one."""
    if urlparse(url).scheme in ("http", "https"):
        return f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer" target="_blank">{escape(text)}</a>'
    return escape(text)


def _approval(token: str, asked: Mapping[str, Any]) -> str:
    summary = "".join(f"<li>{escape(str(line))}</li>" for line in asked.get("summary", []))
    session = escape(str(asked.get("session", "")), quote=True)
    return f"""<section class="card" aria-labelledby="h-approve">
<h2 id="h-approve">Waiting for your approval to send</h2>
<p><strong>{escape(str(asked.get("job") or "An application"))}</strong> is filled in and ready. Nothing is sent until you say so.</p>
<ul>{summary}</ul>
<form method="post" action="/agent/approve">{_token(token)}<input type="hidden" name="session" value="{session}"><button class="btn btn-primary" type="submit">Approve and send</button></form>
<form method="post" action="/agent/reject">{_token(token)}<input type="hidden" name="session" value="{session}"><button class="btn" type="submit">Do not send</button></form>
</section>"""


def _state(token: str, data: Mapping[str, Any]) -> str:
    state, paused = data["state"], data["paused"]
    questions = state.get("questions") or []
    asked = ("<p>It is waiting for you:</p><ul>" + "".join(f"<li>{escape(str(q))}</li>" for q in questions[:6]) + "</ul>"
             '<p><a href="/questions">Answer questions</a></p>') if questions else ""
    job = f"<p>Job: <strong>{escape(str(state['job']))}</strong></p>" if state.get("job") else ""
    detail = f"<p>{escape(str(state['detail']))}</p>" if state.get("detail") else ""
    switch = (f'<form method="post" action="/agent/pause">{_token(token)}<input type="hidden" name="paused" value="{0 if paused else 1}">'
              f'<button class="btn" type="submit">{"Resume the agent" if paused else "Pause the agent"}</button></form>')
    return f"""<section class="card" aria-labelledby="h-state">
<h2 id="h-state">Right now</h2>
<p role="status">The agent is: <strong>{escape(str(state.get("state", "Idle")))}</strong>{" (paused)" if paused and state.get("state") != "Paused" else ""}</p>
{job}{detail}{asked}{switch}
<p><a href="/applications">Refresh this page</a></p>
</section>"""


def _totals(totals: Mapping[str, int]) -> str:
    items = "".join(f"<div><dt>{name}</dt><dd>{totals.get(key, 0)}</dd></div>" for key, name in TOTAL_NAMES)
    return f'<section aria-labelledby="h-totals"><h2 id="h-totals">So far</h2><dl class="totals">{items}</dl></section>'


def _feed(feed: List[Mapping[str, str]]) -> str:
    if not feed:
        return ""
    lines = "".join(f"<li><time>{escape(entry['at'][11:])}</time> {escape(entry['text'])}</li>" for entry in reversed(feed))
    return f'<section aria-labelledby="h-feed"><h2 id="h-feed">What it has been doing</h2><ol class="feed" reversed>{lines}</ol></section>'


def _history(rows: List[Mapping[str, Any]]) -> str:
    if not rows:
        return '<section><h2>Every application</h2><p>None yet. Open a job page in the browser and run <code>jobapply agent</code>.</p></section>'
    body = "".join(
        f"<tr><td>{_link(r['url'], r['title'] or r['url'] or 'Unknown job')}</td><td>{escape(r['company'])}</td>"
        f"<td>{escape(r['status_label'])}</td><td>{escape(r['reference'])}</td><td>{escape(r['resume'])}</td>"
        f"<td><time>{escape((r['applied_at'] or r['started_at'] or '')[:16].replace('T', ' '))}</time></td>"
        f"<td>{escape('; '.join(r['errors'][:2]) or '; '.join(r['missing'][:2]))}</td></tr>" for r in rows)
    return f"""<section aria-labelledby="h-history"><h2 id="h-history">Every application</h2>
<table><caption class="sr-only">Applications the agent has worked on, newest first</caption>
<thead><tr><th scope="col">Job</th><th scope="col">Company</th><th scope="col">Outcome</th><th scope="col">Reference</th>
<th scope="col">Resume</th><th scope="col">When</th><th scope="col">Notes</th></tr></thead><tbody>{body}</tbody></table></section>"""


def applications_page(token: str, data: Dict[str, Any]) -> str:
    approval = _approval(token, data["approval"]) if data["approval"] else ""
    return _page("Applications", f"""<h1>Applications</h1>
<p>The AI agent works on the job page you have open in the browser. Start it with <code>jobapply agent</code>. It fills what it can,
asks you for the rest, and never sends an application without your approval.</p>
{approval}{_state(token, data)}{_totals(data["totals"])}{_feed(data["feed"])}{_history(data["rows"])}""")
