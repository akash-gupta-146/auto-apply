"""See what Naukri's question side bar really looks like, without answering it: `jobapply probe naukri --chat`.

The bar's markup has never been seen live (fix-plan N1: its script is refused on some networks), so the selectors in naukri_chat.py are unverified.
Run this once on a network that loads static.naukri.com and the answer is on screen and in a file, instead of waiting for a real job to fail.

SAFETY: pressing Quick apply is Naukri's submit. A job that has questions waits for answers in the bar, so nothing goes out; a job that turns out to
have none is APPLIED TO by the press. So the probe only ever opens a job Naukri has already asked questions on (parked as needs_answer), and says
so loudly if Naukri answers without any.
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..models import JobCard
from .base import first_visible
from .naukri import DRAWER_POLLS, SEL, NaukriAdapter
from .naukri_api import apply_questions
from .naukri_chat import SEL as BAR_SEL, Drawer
from .naukri_chat_find import TAGGED

CONTAINER_JS = "() => { const box = document.querySelector('#desktopChatBotContainer'); return box ? box.innerHTML : ''; }"
NOTHING_DRAWN = "<!-- the bar selector matched nothing and #desktopChatBotContainer is empty: nothing was drawn -->"
MUST_MATCH = {"bar": "the bar itself", "bot_message": "the question, so it cannot be read"}  # without these nothing works, whatever else matches


@dataclasses.dataclass
class BarReport:
    url: str
    note: str = ""  # why nothing could be read, when so
    questions: List[str] = dataclasses.field(default_factory=list)  # what Naukri's reply to Quick apply said it would ask
    pressed: bool = False
    opened: bool = False
    refused: Optional[int] = None  # the HTTP status the bar's script was refused with, if it was
    matches: Dict[str, int] = dataclasses.field(default_factory=dict)  # selector name -> how many things on the page it found
    question: str = ""  # the question the bar showed first
    options: List[str] = dataclasses.field(default_factory=list)
    markup: Optional[Path] = None  # the bar's own markup, saved
    by_text: Dict[str, str] = dataclasses.field(default_factory=dict)  # the bar was found by the text of its questions, not by SEL: what was found, as tag#id.class

    def lines(self) -> List[str]:
        out = [f"Naukri question side bar probe: {self.url}"]
        if self.note:
            out.append(f"  {self.note}")
        if self.pressed:
            out.append(f"  Naukri's reply to Quick apply lists {len(self.questions)} question(s)" + (": " + " | ".join(q[:60] for q in self.questions[:5]) if self.questions else ""))
            out.append("  the side bar: " + ("OPENED" if self.opened else "did not open" + (f" (its script was refused: HTTP {self.refused} from static.naukri.com)" if self.refused else " (no script was refused, so the cause is unknown: see the saved page)")))
        if self.matches:
            out.append("  what each selector finds on the page: " + ", ".join(f"{name}={count}" for name, count in self.matches.items()))
            out += [f"  PROBLEM: '{name}' matched nothing: {why}. Repair SEL['{name}'] in naukri_chat.py from the saved markup." for name, why in MUST_MATCH.items() if not self.matches.get(name)]
        if self.by_text:
            out.append("  SEL missed the bar, but it WAS found by the text of its questions, so answering works. To make the guesses right, put these in naukri_chat.SEL: "
                       + ", ".join(f"{role}={what}" for role, what in self.by_text.items()))
        if self.question:
            out.append(f"  the first question it read: {self.question[:100]!r}" + (f" with choices {self.options}" if self.options else " (a text answer)"))
        if self.markup:
            out.append(f"  the bar's markup is saved in {self.markup}")
        if self.opened:
            out.append("  Nothing was answered or sent; the bar was closed.")
        return out


def pick_job(cards: Sequence[JobCard], url: str = "") -> Tuple[Optional[JobCard], str]:
    """The job to probe on, and a message when there is none. Only a job Naukri has already asked questions on (`cards` are those): see the safety note."""
    if not cards:
        return None, ("No Naukri job is known to have questions yet. The probe presses Quick apply, which SENDS the application if a job has none, so it only uses a job "
                      "Naukri already asked questions on (parked as needs_answer). Do a normal Naukri run first; jobs with questions are parked, then run this again.")
    if not url:
        return cards[0], ""
    match = next((card for card in cards if card.url.split("?")[0] == url.split("?")[0]), None)
    return match, "" if match else ("That job is not one Naukri has asked questions on. The probe presses Quick apply, which sends the application if a job has no questions, "
                                    "so it only opens jobs parked as needs_answer: " + ", ".join(card.url for card in cards[:5]))


def probe_bar(adapter: NaukriAdapter, url: str) -> BarReport:
    """Press Quick apply on `url` (a job known to have questions), look at the bar if it opens, close it, answer nothing."""
    report = BarReport(url)
    adapter.goto(url)
    button = first_visible(adapter.active, [SEL["apply"]])
    if button is None:
        report.note = "no Quick apply button on this page (already applied, or it applies somewhere else): nothing was pressed"
        return report
    calls: list = []
    on_response = adapter._watch_apply(calls)
    adapter.active.on("response", on_response)
    try:
        button.click()
        report.pressed = True
        drawer = Drawer(adapter.active)
        for _ in range(DRAWER_POLLS):
            drawer.known = _asked(adapter, calls)  # once Naukri's reply is in, a bar SEL does not match is looked for by its questions
            if drawer.is_open():
                break
            adapter.active.wait_for_timeout(500)
        report.opened, report.refused = drawer.is_open(), adapter._chat_refused
        replies = [call for call in calls if call.status == 200]
        report.questions = _asked(adapter, calls)
        if replies and not report.questions and not report.opened:
            report.note = "WARNING: Naukri accepted the press with no questions, so the application may have been SENT. Check Naukri's Applied jobs."
        _look(adapter, drawer, report)
        if report.opened:
            drawer.close()
    finally:
        adapter.active.remove_listener("response", on_response)
    return report


def _asked(adapter: NaukriAdapter, calls: list) -> List[str]:
    """The questions Naukri's replies to Quick apply say it will ask."""
    return [q for call in calls if call.status == 200 for q in apply_questions(adapter._body(call))]


def _look(adapter: NaukriAdapter, drawer: Drawer, report: BarReport) -> None:
    """What the page holds, as far as it can be read; each look is kept even if another fails."""
    for name, selector in BAR_SEL.items():
        try:
            report.matches[name] = adapter.active.locator(selector).count()
        except Exception:
            report.matches[name] = 0
    if report.opened:
        report.by_text = dict(drawer.how) if drawer.found_by_text() else {}
        for attempt in (lambda: setattr(report, "question", drawer.question()), lambda: setattr(report, "options", drawer.options())):
            try:
                attempt()
            except Exception:
                pass
    adapter.capture_failure(JobCard(adapter.name, report.url, "probe: question side bar"))  # picture, page and network note, like any failure
    folder = adapter.failures_dir
    if folder is None:
        return
    try:
        # The bar is added late in the page, which the saved page may cut off, so its markup is kept apart: the bar itself if the selector finds it,
        # else whatever fills the container where it is expected (which is exactly what shows a wrong selector).
        bar = BAR_SEL["bar"] if report.matches.get("bar") else TAGGED["bar"] if report.by_text else ""
        markup = adapter.active.locator(bar).first.evaluate("e => e.outerHTML") if bar else adapter.active.evaluate(CONTAINER_JS)
        folder.mkdir(parents=True, exist_ok=True)
        report.markup = folder / f"{adapter.name}-bar-{int(time.time())}.html"
        report.markup.write_text(markup or NOTHING_DRAWN, encoding="utf-8")
    except Exception:
        report.markup = None
