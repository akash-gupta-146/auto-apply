"""What the Applications page shows and does: the agent's live state, what is waiting for you, and every application's outcome.

Read without disturbing the agent (it may be writing the same files and database); no HTTP and no HTML in here.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..agent import history
from ..agent.hitl import APPROVE, REJECT, AgentState, Channel, process_alive
from ..agent.session import Session
from ..config import Paths

FEED_LINES = 25


def snapshot(paths: Paths) -> Dict[str, Any]:
    channel = Channel(paths)
    state = channel.read_state()
    conn = history.read_only(paths.db)
    try:
        rows = history.recent(conn) if conn else []
        totals = history.totals(conn) if conn else {}
    finally:
        if conn:
            conn.close()
    return {"state": state, "approval": channel.pending_approval(), "paused": channel.paused(), "feed": _feed(paths, state.get("session", "")),
            "rows": rows, "totals": totals}


def live(paths: Paths) -> Dict[str, Any]:
    """The few things the control panel shows while the agent works (read on every poll, so kept small)."""
    channel = Channel(paths)
    state = channel.read_state()
    active = state.get("state") not in (AgentState.IDLE.value, AgentState.COMPLETED.value, AgentState.FAILED.value)
    if active and not process_alive(state.get("pid")):  # it was stopped without a chance to say so
        state = {"state": AgentState.IDLE.value, "detail": "The agent stopped. Your application is saved: use Continue to carry on."}
    session = state.get("session", "")
    return {"state": state.get("state", AgentState.IDLE.value), "detail": state.get("detail", ""), "job": state.get("job", ""),
            "questions": state.get("questions", []), "session": session, "approval": channel.pending_approval(),
            "paused": channel.paused(), "feed": _feed(paths, session)[-8:]}


def unfinished(paths: Paths) -> bool:
    return Session.latest_open(paths.agent_dir) is not None


def _feed(paths: Paths, session_id: str) -> List[Dict[str, str]]:
    """What the agent has been doing: the live application's log, or the latest one's."""
    try:
        session = Session.load(paths.agent_dir, session_id) if session_id else None
    except (OSError, ValueError, KeyError, TypeError):
        session = None
    if session is None:
        latest = sorted((paths.agent_dir / "sessions").glob("*.feed"), reverse=True)
        if not latest:
            return []
        session = Session(id=latest[0].stem)
        session.path = latest[0].with_suffix(".json")
    return session.feed(FEED_LINES)


def decide(paths: Paths, session_id: str, decision: str) -> bool:
    """Your answer to 'may I send this?'. Only counts for the application that asked."""
    return decision in (APPROVE, REJECT) and Channel(paths).decide(session_id, decision)


def pause(paths: Paths, paused: bool) -> None:
    Channel(paths).set_paused(paused)

