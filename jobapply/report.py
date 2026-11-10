"""Human-readable run report."""
from __future__ import annotations

from pathlib import Path

from .engine import RunSummary
from .models import Status
from .report_names import report_filename

# What a row says when the portal gave no reason of its own: never a blank, because every job is owed a "why".
NO_REASON = "no reason was recorded"
FALLBACK_WHY = {
    Status.APPLIED: "recorded as applied; no more detail was saved",
    Status.DRY_RUN_OK: "the form was filled up to the review step; nothing was sent",
}


def _sections(dry_run: bool):
    """(heading, statuses, what to do about them). Every job of the run is listed in exactly one of these."""
    return (
        ("Would apply (nothing was sent)" if dry_run else "Applied", (Status.APPLIED, Status.DRY_RUN_OK), ""),
        ("Failed", (Status.FAILED,),
         "Each is tried again on the next run. A picture of the page where it went wrong is in `data/failures/`."),
        ("Needs an answer from you", (Status.NEEDS_ANSWER,),
         "Answer these on the panel's Questions page, then run again."),
        ("Skipped: did not fit your rules", (Status.SKIPPED_MATCH,),
         "Changed your rules or answers? Tick **Also re-check jobs skipped earlier** to look at these again."),
        ("Skipped: nothing to press", (Status.SKIPPED_EXTERNAL,),
         "No apply button the program can use: the job applies on the company's own site, or is closed."),
        ("Skipped: already applied", (Status.SKIPPED_DUPLICATE,), ""),
        ("Skipped by a challenge", (Status.SKIPPED_CHALLENGE,),
         "A captcha or check was waiting for a human. These are tried again on the next run."),
    )


LEAD = {Status.NEEDS_ANSWER: "waiting for your answer to: "}  # what the bare reason is, when it is only a question


def _row(card, result) -> str:
    reason = result.reason.strip()
    why = LEAD.get(result.status, "") + reason if reason else FALLBACK_WHY.get(result.status, NO_REASON)
    return f"- {card.title} @ {card.company} - {card.url} - **why:** {why}"


def write_report(summary: RunSummary, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    mode = "dry-run" if summary.dry_run else "live"
    path = reports_dir / report_filename(summary.started, summary.portal, summary.dry_run)
    lines = [
        f"# {summary.portal} ({mode}) - {summary.started:%Y-%m-%d %H:%M}",
        "",
        f"Stopped because: **{summary.stop_reason}**",
        "",
        "| status | count |",
        "|---|---|",
        *[f"| {status} | {count} |" for status, count in sorted(summary.counts.items())],
        "",
    ]
    if not summary.counts:
        lines += ["No jobs were processed in this run.", ""]
    if summary.queue:
        lines += [
            f"Whole {summary.portal} queue after this run (all runs): "
            + ", ".join(f"{status}={count}" for status, count in sorted(summary.queue.items())),
            "",
        ]
    for title, statuses, advice in _sections(summary.dry_run):
        rows = [(c, r) for c, r in summary.items if r.status in statuses]
        if rows:
            lines += [f"## {title} ({len(rows)})", "", *([advice, ""] if advice else []), *[_row(c, r) for c, r in rows], ""]
    if summary.notes:
        lines += ["## Problems noticed", *[f"- {note}" for note in summary.notes], ""]
    if summary.ai_answers:
        lines += [
            "## Answers the AI wrote from your documents (please check them)",
            *[f'- **{q}** -> {a}  (from: "{quote}")' for q, (a, quote) in summary.ai_answers.items()],
            "",
        ]
    if summary.ai_fit:
        counts = ", ".join(f"{n} {what}" for what, n in sorted(summary.ai_fit.items()))
        lines += [
            "## Jobs the AI judged from their description (their titles did not match your roles)",
            f"{counts}. Every verdict, with the lines of your documents it relied on, is in data/ai_fit.jsonl.",
            *(["Some were not judged: the daily AI limit was reached or the AI could not be asked; they stay skipped."]
              if summary.ai_fit.get("not judged") else []),
            "",
        ]
    if summary.dismissed:
        asked = ", ".join(f"{n} {what}" for what, n in sorted(summary.ai_popups.items()))
        lines += [
            f"## Pop-ups closed by pressing their no ({len(summary.dismissed)})",
            *[f"- {what}" for what in summary.dismissed],
            *([f"The AI was asked about the ones the rules did not know: {asked}. Every verdict is in data/ai_prompts.jsonl."] if asked else []),
            "",
        ]
    if summary.ai_declined:
        lines += [
            "## Questions the AI could not answer from your documents (these jobs wait for you)",
            *[f"- {q}" for q in summary.ai_declined],
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
