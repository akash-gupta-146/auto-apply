"""Pop-ups that get between the program and the page, and the safe way to close them.

LinkedIn offers "Turn your resume into a profile that recruiters notice" once an application is sent; Indeed offers a job alert
in the middle of the results. Left open they cover the page (a covered "Next" cannot be clicked) and one asks for an email address.

The only thing ever pressed is a NO: "Not now", "No thanks", "Maybe later", Close, or a close icon. Never "Update profile",
"Activate", "Subscribe", "Accept", "Save" or anything else that says yes, whoever suggested it (the rules, or the AI helper).
A pop-up that holds the application itself is never touched, and neither is one nobody can tell is safe to close.

Rules decide first and cost nothing. Only for a pop-up the rules do not recognise is the AI helper asked (when it is on): which
button is the no, and is this safe to close at all. Its answer must be one of the pop-up's real buttons, and passes the same
never-a-yes check. The text it sees is the pop-up's own wording with emails and long numbers removed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Pattern

log = logging.getLogger("jobapply")

CLOSE_ICON = "close icon"
MAX_ROUNDS = 3  # a pop-up that closes may reveal another (LinkedIn: confirmation, then the profile upsell)
SETTLE_MS = 600  # after pressing, the page gets a moment to remove the pop-up before it is looked at again
PRESS_MS = 2_000
MAX_TEXT = 600

# The "no" side, best first. Matched against the whole label, so "Update profile" can never be a "Not now".
NO_WORDS = (
    re.compile(r"(?:not now|no,? thanks?|no thank you|maybe later|remind me later|ask me later|not interested|skip(?: for now)?|later)\W*", re.I),
    re.compile(r"(?:dismiss|decline|reject(?: all)?|cancel|no|close|got it|ok|okay)\W*", re.I),
)
# Never pressed, from any source. A label that says yes (or moves an application on) is refused even if the AI picked it.
YES_WORDS = re.compile(
    r"\b(?:submit|send|apply|update|activate|subscribe|sign|join|upgrade|premium|try|accept|agree|allow|enable|confirm|continue|yes|"
    r"save|connect|follow|add|turn on|download|install|buy|pay|start|get|create|upload|verify|share|post|invite|message|next|review)\b", re.I)
CLOSE_HINT = re.compile(r"\b(?:close|dismiss)\b|^[×x]$", re.I)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LONG_NUMBER = re.compile(r"\+?\d[\d\s().-]{6,}\d")

SCAN_JS = """() => {
  const SELECTOR = 'dialog, [role=dialog], [role=alertdialog], [aria-modal=true], [class*=popup i], [class*=modal i]';
  const CONTROLS = 'button, [role=button], a[role=button], input[type=button], input[type=submit]';
  const shown = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[aria-hidden=true]');
  const fixed = e => { for (let n = e; n && n !== document.body; n = n.parentElement) if (getComputedStyle(n).position === 'fixed') return true; return false; };
  document.querySelectorAll('[data-jobapply-prompt], [data-jobapply-control]').forEach(e => {
    e.removeAttribute('data-jobapply-prompt'); e.removeAttribute('data-jobapply-control'); });
  const found = [...document.querySelectorAll(SELECTOR)].filter(e => e !== document.body && e !== document.documentElement && shown(e)
    && (e.matches('dialog, [role=dialog], [role=alertdialog], [aria-modal=true]') || fixed(e)));
  const outer = found.filter(e => !found.some(o => o !== e && o.contains(e)));
  return outer.map((root, i) => {
    root.setAttribute('data-jobapply-prompt', i);
    const controls = [...root.querySelectorAll(CONTROLS)].filter(shown).map((c, j) => {
      c.setAttribute('data-jobapply-control', j);
      const label = (c.innerText || c.value || '').trim().replace(/\\s+/g, ' ');
      return {index: j, name: label || c.getAttribute('aria-label') || c.getAttribute('title') || '', icon: !label || /^[×xX]$/.test(label)};
    });
    return {index: i, text: (root.innerText || '').replace(/\\s+/g, ' ').trim(), controls};
  });
}"""


@dataclass
class Control:
    index: int
    name: str
    icon: bool  # drawn as a picture or a single cross, with no words of its own


@dataclass
class Prompt:
    index: int
    text: str  # its own wording, with emails and long numbers removed
    controls: List[Control]

    @property
    def labels(self) -> List[str]:
        return [control.name for control in self.controls if control.name and not control.icon]

    @property
    def closer(self) -> Optional[Control]:
        return next((c for c in self.controls if c.icon and CLOSE_HINT.search(c.name)), None)

    def headline(self) -> str:
        return self.text[:70] + ("..." if len(self.text) > 70 else "")


Judge = Callable[[str, List[str], bool], Optional[str]]  # (pop-up text, its button labels, has a close icon) -> the no side


def mask(text: str) -> str:
    """Nothing personal rides along in a pop-up's wording (Indeed's job-alert pop-up shows your own email)."""
    return LONG_NUMBER.sub("<number>", EMAIL.sub("<email>", text))[:MAX_TEXT]


def scan(page) -> List[Prompt]:
    try:
        raw = page.evaluate(SCAN_JS)
    except Exception:
        return []  # the page is mid-navigation: there is nothing to look at
    return [Prompt(item["index"], mask(item["text"]), [Control(**control) for control in item["controls"]]) for item in raw if item["controls"]]


def no_side(prompt: Prompt) -> Optional[Control]:
    """The button that says no, by its words alone (the whole label, so "Update profile" can never pass for one); else a close icon."""
    for pattern in NO_WORDS:
        for control in prompt.controls:
            if control.name and not control.icon and pattern.fullmatch(control.name.strip()):
                return control
    return prompt.closer


def _chosen_by_ai(prompt: Prompt, judge: Optional[Judge]) -> Optional[Control]:
    if judge is None:
        return None
    name = judge(prompt.text, prompt.labels, prompt.closer is not None)
    if not name or YES_WORDS.search(name):
        return None  # whatever the AI says, a yes is never pressed
    if name.strip().lower() == CLOSE_ICON:
        return prompt.closer
    return next((c for c in prompt.controls if not c.icon and c.name.strip().lower() == name.strip().lower()), None)


def _press(page, prompt: Prompt, control: Control) -> bool:
    try:
        page.locator(f'[data-jobapply-prompt="{prompt.index}"] [data-jobapply-control="{control.index}"]').first.click(timeout=PRESS_MS)
        page.wait_for_timeout(SETTLE_MS)
        return True
    except Exception:
        return False


def dismiss_prompts(page, judge: Optional[Judge] = None, protected: Optional[Pattern] = None, rounds: int = MAX_ROUNDS) -> List[str]:
    """Close every pop-up in the way that is safe to close. Returns a line for each one pressed: what it said and what was pressed."""
    closed: List[str] = []
    left_alone = set()  # pop-ups already judged this time: not looked at (or asked about) again
    for _ in range(rounds):
        pressed = False
        for prompt in scan(page):
            if prompt.text in left_alone or (protected is not None and protected.search(prompt.text)):
                continue
            control, how = no_side(prompt), "rule"
            if control is None:
                control, how = _chosen_by_ai(prompt, judge), "AI"
            if control is None or not _press(page, prompt, control):
                left_alone.add(prompt.text)
                continue
            closed.append(f"{prompt.headline()} -> pressed '{control.name or CLOSE_ICON}' ({how})")
            log.info("closed a pop-up: %s", closed[-1])
            pressed = True
            break  # the page has changed: look again
        if not pressed:
            break
    return closed
