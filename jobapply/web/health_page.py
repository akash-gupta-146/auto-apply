"""The Check my saved answers page: where your saved answers disagree with your profile, which ones repeat, and which no run uses."""
from __future__ import annotations

from html import escape
from typing import Dict, List, Sequence, Tuple

from ..answer_health import Alike, Conflict, Health, Use
from .pages import _banner, _page, _token

ACTIONS = ("profile", "keep", "merge", "forget")  # the fixes a button can ask for: each names a saved question and nothing else
DONE = {
    "profile": "Replaced your saved answer with what your profile says.",
    "keep": "Kept your answer. It will not be flagged again unless it or your profile changes.",
    "merge": "Merged. The other wordings still work: they are answered by the one you kept.",
    "forget": "Removed that saved answer. A job that asks it again will wait for you.",
}


def banner_for(query: Dict[str, List[str]]) -> Tuple[str, str]:
    """The message on top of the page after a fix (it arrives in the address)."""
    done = query.get("done", [""])[0]
    if done in DONE:
        return "ok", DONE[done]
    if "failed" in query:
        return "error", "Nothing was changed: that answer is no longer there, or no longer needs this."
    return "", ""


def _fix(token: str, action: str, question: str, label: str, about: str) -> str:
    """One button: it names the saved question it is about, and the server works out what to do from what is saved."""
    return (f'<form method="post" action="/answers/health/{action}">{_token(token)}'
            f'<input type="hidden" name="question" value="{escape(question, quote=True)}">'
            f'<button type="submit" class="btn btn-small" aria-label="{escape(label + ": " + about, quote=True)}">{escape(label)}</button></form>')


def _conflicts(token: str, found: Sequence[Conflict], has_profile: bool) -> str:
    if not has_profile:
        return ('<section aria-labelledby="h-conflicts"><h2 id="h-conflicts">Disagreeing with your profile</h2>'
                '<p>Save your <a href="/profile">profile</a> first: there is nothing to compare your answers with yet.</p></section>')
    if not found:
        return ('<section aria-labelledby="h-conflicts"><h2 id="h-conflicts">Disagreeing with your profile</h2>'
                "<p>None. No saved answer says something different from your profile about the same thing.</p></section>")
    rows = "".join(
        f'<li class="decide"><div class="what"><span class="q">{escape(c.question)}</span><br>You saved: <strong>{escape(c.saved)}</strong>'
        f'<br>Your profile says: <strong>{escape(c.profile)}</strong></div>'
        f'<div class="choices">{_fix(token, "profile", c.question, "Use my profile", c.question)}'
        f'{_fix(token, "keep", c.question, "Keep my saved answer", c.question)}</div></li>' for c in found)
    return f"""<section aria-labelledby="h-conflicts"><h2 id="h-conflicts">Disagreeing with your profile ({len(found)})</h2>
<p>A run uses the saved answer, so a form that words the question differently can send something else. Choose which one is right.
Only answers that are a short fact (a figure, a name) are compared with your profile.</p><ul class="saved">{rows}</ul></section>"""


def _alike(token: str, groups: Sequence[Alike]) -> str:
    if not groups:
        return ('<section aria-labelledby="h-alike"><h2 id="h-alike">Questions that may be the same</h2>'
                "<p>None found. Only questions that agree on the answer and where one is wholly contained in the other are offered here.</p></section>")
    items = ""
    for group in groups:
        wordings = "".join(f'<li><div class="what"><span class="q">{escape(q)}</span><br><strong>{escape(a)}</strong></div>'
                           f'{_fix(token, "merge", q, "Keep this wording", q)}</li>' for q, a in group.entries)
        items += f'<li><div class="what">These agree on the answer:<ul class="saved">{wordings}</ul></div></li>'
    return f"""<section aria-labelledby="h-alike"><h2 id="h-alike">Questions that may be the same ({len(groups)})</h2>
<p>Merge only if they really ask the same thing. Keeping one wording folds the others into it, and the others still work: they are answered by the
one you kept.</p><ul class="saved">{items}</ul></section>"""


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ") if stamp else "never"


def _used(rows: Sequence[Use]) -> str:
    if not rows:
        return ""
    body = "".join(f"<tr><td>{escape(r.question)}</td><td>{escape(r.answer)}</td><td>{r.uses}</td><td><time>{escape(_when(r.last))}</time></td></tr>"
                   for r in rows)
    return f"""<section aria-labelledby="h-used"><h2 id="h-used">Answers runs use ({len(rows)})</h2><details class="saved-list"><summary>Show them</summary>
<table><caption class="sr-only">Saved answers that runs have used, most used first</caption><thead><tr><th scope="col">Question</th>
<th scope="col">Your answer</th><th scope="col">Jobs</th><th scope="col">Last used</th></tr></thead><tbody>{body}</tbody></table></details></section>"""


def _unused(token: str, health: Health) -> str:
    if not health.counting_since:
        return ('<section aria-labelledby="h-unused"><h2 id="h-unused">Answers no run uses</h2><p>No run has used a saved answer since counting began, '
                "so there is nothing to say yet. After a few runs, the answers nobody uses are listed here.</p></section>")
    if not health.unused:
        return '<section aria-labelledby="h-unused"><h2 id="h-unused">Answers no run uses</h2><p>None: every saved answer has been used.</p></section>'
    items = "".join(f'<li><div class="what"><span class="q">{escape(u.question)}</span><br><strong>{escape(u.answer)}</strong></div>'
                    f'{_fix(token, "forget", u.question, "Remove", u.question)}</li>' for u in health.unused)
    return f"""<section aria-labelledby="h-unused"><h2 id="h-unused">Answers no run uses ({len(health.unused)})</h2>
<p>Counting began {escape(_when(health.counting_since))}. These have not been asked since, which does not make them wrong: a question may simply not
have come up yet. Remove only what you know is stale.</p><details class="saved-list"><summary>Show them</summary><ul class="saved">{items}</ul></details></section>"""


def health_page(token: str, health: Health, banner: Tuple[str, str] = ("", "")) -> str:
    saved = len(health.used) + len(health.unused)
    state = (f"{health.problems} thing{'' if health.problems == 1 else 's'} to look at." if health.problems else "Nothing needs your attention.")
    return _page("Check my saved answers", f"""<h1>Check my saved answers</h1>
{_banner(banner)}
<p role="status">You have {saved} saved answer{'' if saved == 1 else 's'}. {state}</p>
<p>Nothing here is changed until you press a button, and every button only uses an answer you already gave or your profile already says.
<a href="/questions">Back to your questions</a></p>
{_conflicts(token, health.conflicts, health.has_profile)}{_alike(token, health.alike)}{_unused(token, health)}{_used(health.used)}""")
