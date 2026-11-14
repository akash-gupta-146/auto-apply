"""What the `jobapply agent` command says to you: the answer to an approval request, and how an application ended."""
from __future__ import annotations

from ..config import Paths
from .hitl import APPROVE, Channel
from .models import AppStatus
from .session import Session

NEXT = {
    AppStatus.READY: "This was a rehearsal, so nothing was sent. To really apply, run it again with --submit.",
    AppStatus.SUBMITTED: "It went through, and the page said so.",
    AppStatus.REQUIRES_USER: "It needs you. Do what the last message asked, then run `jobapply agent --continue` to carry on.",
    AppStatus.INCOMPLETE: "The form was not accepted. Look at the page, fix it, then run `jobapply agent --continue`.",
    AppStatus.VERIFICATION_PENDING: "Press Submit may have worked, but the page did not say. Check your email or the site before trying again.",
    AppStatus.FAILED: "The site reported an error. Check whether the application went through before trying again.",
    AppStatus.DUPLICATE: "The site says it already has this application.",
    AppStatus.ALREADY_SUBMITTED: "You had already applied to this job. Nothing was sent.",
    AppStatus.IN_PROGRESS: "It stopped part-way. Run `jobapply agent --continue` to carry on from there.",
}


def decide(paths: Paths, decision: str) -> str:
    """Answer the approval request that is waiting, from a second terminal."""
    channel = Channel(paths)
    asked = channel.pending_approval()
    if asked is None:
        return "Nothing is waiting for your approval."
    channel.decide(asked["session"], decision)
    return f"{'Approved' if decision == APPROVE else 'Rejected'}: {asked.get('job') or 'the application'}."


def summary(session: Session) -> str:
    job = session.job.context() or "this page"
    line = f"{job}: {session.status.label}. {NEXT.get(session.status, '')}"
    if session.reference:
        line += f" Reference: {session.reference}."
    return line.strip()
