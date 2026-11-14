"""The agent's hands: click, type, choose, upload, scroll, go back, follow a new tab, and check that each one worked.

An action names a control by the number the latest look gave it. After acting, the control is read back (what a box holds, which
choice is ticked, which file is attached) and a mismatch is reported, never assumed away. Nothing waits a fixed time: after a click
the page is watched until it changes, for a bounded while.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Sequence, Set

from ..adapters.forms import click_choice
from .models import Action, ActionType, Element
from .observe import readable_frames

CLICK_MS = 4_000
CHANGE_MS = 5_000
POLL_MS = 150
QUIET_MS = 700  # a page that has changed is read only after this long without changing again: a form slides in after its frame
SETTLE_MAX_MS = 4_000  # ...but a page that never stops (a ticker, an animation) is not waited for longer than this
OPTION_MS = 3_000
YES = {"yes", "true", "on", "checked", "tick"}

SIGNATURE_JS = """() => location.href + '|' + document.title + '|' + (document.body ? document.body.innerText.length : 0) + '|'
  + document.querySelectorAll('input, select, textarea, button, a, [role=dialog], dialog').length"""
READ_JS = """e => {
  if (!e.isConnected) return null;
  if (e.tagName === 'SELECT') return e.selectedOptions.length ? e.selectedOptions[0].innerText.trim() : '';
  if (e.type === 'radio' || e.type === 'checkbox') return e.checked ? 'on' : '';
  if (e.type === 'file') return e.files && e.files.length ? e.files[0].name : '';
  if (e.tagName === 'INPUT' || e.tagName === 'TEXTAREA') return e.value;
  const role = e.getAttribute('role');
  if (role === 'radio' || role === 'checkbox' || role === 'switch') return e.getAttribute('aria-checked') === 'true' ? 'on' : '';
  return (e.innerText || '').trim();
}"""


class Outcome:
    def __init__(self, ok: bool, detail: str = "", page=None):
        self.ok, self.detail, self.page = ok, detail, page  # page: a tab that this action opened, now being driven

    def __repr__(self) -> str:
        return f"Outcome({self.ok}, {self.detail!r})"


def _same(typed: str, held: str) -> bool:
    """A box holds what was typed. Masks reformat a phone number and a drop-down shows its own wording, so those are compared leniently."""
    a, b = " ".join(typed.lower().split()), " ".join(held.lower().split())
    if a == b or (a and a in b):
        return True
    digits_a, digits_b = re.sub(r"\D", "", typed), re.sub(r"\D", "", held)
    return len(digits_a) >= 6 and digits_a == digits_b


class Browser:
    def __init__(self, page, allowed_files: Optional[Set[Path]] = None):
        self.page = page
        self.allowed_files = {Path(f).resolve() for f in (allowed_files or ())}  # the only files an upload may attach

    # -- tabs -----------------------------------------------------------------
    @property
    def context(self):
        return self.page.context

    def ensure_page(self) -> bool:
        """The tab being driven may have closed itself (a pop-up that finished its job): carry on in one that is still open."""
        if not self.page.is_closed():
            return True
        open_tabs = [p for p in self.context.pages if not p.is_closed()]
        if not open_tabs:
            return False
        self.page = open_tabs[-1]
        return True

    # -- reading ----------------------------------------------------------------
    def _locator(self, ref: int):
        selector = f'[data-ja-ref="{ref}"]'
        for frame in [self.page.main_frame, *readable_frames(self.page)]:  # the numbers are unique across the page and its frames
            try:
                if frame.locator(selector).count():
                    return frame.locator(selector).first
            except Exception:
                continue  # a frame that went away: look in the rest
        return self.page.locator(selector).first  # nowhere: the page's own, which says the control is gone in the usual way

    def handle(self, ref: int):
        """The control itself (not its number): still the same control after the page is looked at again, gone if it is removed."""
        return self._locator(ref).element_handle(timeout=OPTION_MS)

    def read(self, handle) -> str:
        value = handle.evaluate(READ_JS)
        if value is None:
            raise LookupError("the control is gone from the page")
        return value

    def reader(self, elements: Sequence[Element]) -> Callable[[], Optional[str]]:
        """What the person has put in this control, or in this group of choices (the option they ticked), read from the control
        itself. Raises once it is gone, so a wait for them ends."""
        handles = [(self.handle(e.ref), e) for e in elements]
        if len(handles) == 1 and not handles[0][1].is_choice:
            return lambda: self.read(handles[0][0]).strip() or None
        if len(handles) == 1:
            return lambda: "Yes" if self.read(handles[0][0]) else None
        return lambda: next((e.name for h, e in handles if self.read(h)), None)

    # -- acting -------------------------------------------------------------------
    def run(self, action: Action) -> Outcome:
        if not self.ensure_page():
            return Outcome(False, "every tab was closed")
        try:
            handler = {
                ActionType.CLICK_ELEMENT: self._click, ActionType.FILL_FIELD: self._fill, ActionType.SELECT_OPTION: self._choose,
                ActionType.UPLOAD_FILE: self._upload, ActionType.SCROLL_PAGE: self._scroll, ActionType.WAIT_FOR_CHANGE: self._wait,
                ActionType.NAVIGATE_BACK: self._back,
            }[action.type]
        except KeyError:
            return Outcome(False, f"{action.type.value} is not something the browser does")
        try:
            return handler(action)
        except Exception as exc:  # a control that vanished or a page mid-navigation is a result to report, not a crash
            return Outcome(False, f"{type(exc).__name__}: {' '.join(str(exc).split())[:160]}")

    def _signature(self) -> str:
        try:
            return "|".join([self.page.evaluate(SIGNATURE_JS), *(frame.evaluate(SIGNATURE_JS) for frame in readable_frames(self.page))])
        except Exception:
            return "navigating"  # the page is being replaced: that is a change

    def _watch(self, before: str, known: Set) -> Optional[object]:
        """Wait until the page changes or a new tab opens, for a bounded while. Returns the new tab, if there is one."""
        for _ in range(CHANGE_MS // POLL_MS):
            fresh = [p for p in self.context.pages if p not in known and not p.is_closed()]
            if fresh:
                return fresh[-1]
            if self._signature() != before:
                return None
            self.page.wait_for_timeout(POLL_MS)
        return None

    def _click(self, action: Action) -> Outcome:
        control, before, known = self._locator(action.ref), self._signature(), set(self.context.pages)
        if control.count() == 0:
            return Outcome(False, "the control is gone from the page")
        control.scroll_into_view_if_needed(timeout=CLICK_MS)
        try:
            control.click(timeout=CLICK_MS)
        except Exception:  # an overlay in the way, or a custom control that only answers a script click; or a click that worked, and
            if self._signature() == before and control.count():  # whose page is still loading: only press again if nothing happened
                control.evaluate("e => e.click()", timeout=CLICK_MS)
        tab = self._watch(before, known)
        if tab is not None:
            tab.wait_for_load_state("domcontentloaded")
            self.page = tab
            return Outcome(True, "opened a new tab", tab)
        return Outcome(True, "the page changed" if self._settled_change(before) else "the page did not change")

    def _settled_change(self, before: str) -> bool:
        """Did the page change, and has it finished? A form opened from a button commonly shows its (empty) frame at once and its fields half a
        second later: read at the first change it still looks like the page before, and its button gets pressed again, closing it."""
        last = self._signature()
        changed, quiet = last != before, 0
        for _ in range(SETTLE_MAX_MS // POLL_MS if changed else 0):
            self.page.wait_for_timeout(POLL_MS)
            now = self._signature()
            quiet = quiet + POLL_MS if now == last and now != "navigating" else 0
            last = now
            if quiet >= QUIET_MS:
                break
        return changed

    def _fill(self, action: Action) -> Outcome:
        control = self._locator(action.ref)
        control.fill(action.value, timeout=CLICK_MS)
        if _same(action.value, self.read(control.element_handle())):
            return Outcome(True, "filled")
        control.click()  # a framework box that ignored the quick fill: type it the way a person does
        self.page.keyboard.press("ControlOrMeta+A")
        self.page.keyboard.type(action.value, delay=20)
        held = self.read(control.element_handle())
        return Outcome(_same(action.value, held), "filled" if _same(action.value, held) else f"the box holds '{held[:40]}', not what was typed")

    def _choose(self, action: Action) -> Outcome:
        control = self._locator(action.ref)
        info = control.evaluate("e => ({tag: e.tagName.toLowerCase(), type: e.type || '', role: e.getAttribute('role') || ''})")
        if info["tag"] == "select":
            return self._choose_native(control, action.value)
        if info["type"] in ("radio", "checkbox") or info["role"] in ("radio", "checkbox", "switch"):
            return self._tick(control, action.value, radio=info["type"] == "radio" or info["role"] == "radio")
        return self._choose_custom(control, action.value)

    def _choose_native(self, control, wanted: str) -> Outcome:
        options = [o.strip() for o in control.locator("option").all_inner_texts()]
        match = next((o for o in options if o.lower() == wanted.lower()), None) or next((o for o in options if wanted.lower() in o.lower()), None)
        if match is None:
            return Outcome(False, f"the drop-down has no option like '{wanted[:40]}'")
        control.select_option(label=match, timeout=CLICK_MS)
        held = self.read(control.element_handle())
        return Outcome(held == match, "chosen" if held == match else f"the drop-down shows '{held[:40]}'")

    def _tick(self, control, value: str, radio: bool) -> Outcome:
        want = radio or value.strip().lower() in YES
        handle = control.element_handle()
        if bool(self.read(handle)) != want:
            click_choice(control)
        ticked = bool(self.read(handle))
        return Outcome(ticked == want, "chosen" if ticked == want else "the choice did not take")

    def _choose_custom(self, control, wanted: str) -> Outcome:
        """A drop-down drawn by script: open it, type to narrow it if it takes text, press the option that reads as the answer."""
        control.click(timeout=CLICK_MS)
        if control.evaluate("e => e.tagName === 'INPUT' || e.isContentEditable"):
            self.page.keyboard.type(wanted, delay=20)
        pattern = re.compile(re.escape(wanted), re.I)
        option = self.page.get_by_role("option", name=pattern).first
        option.wait_for(state="visible", timeout=OPTION_MS)
        option.click(timeout=CLICK_MS)
        held = self.read(control.element_handle())
        return Outcome(_same(wanted, held), "chosen" if _same(wanted, held) else f"the drop-down shows '{held[:40]}'")

    def _upload(self, action: Action) -> Outcome:
        path = Path(action.value).resolve()
        if path not in self.allowed_files or not path.is_file():
            return Outcome(False, "that file is not one the agent may attach")
        control = self._locator(action.ref)
        control.set_input_files(str(path), timeout=CLICK_MS)
        held = self.read(control.element_handle())
        return Outcome(bool(held), f"attached {held}" if held else "the page shows no file attached")

    def _scroll(self, action: Action) -> Outcome:
        script = {"up": "window.scrollBy(0, -700)", "top": "window.scrollTo(0, 0)"}.get(action.value, "window.scrollBy(0, 700)")
        self.page.evaluate(f"() => {script}")
        return Outcome(True, "scrolled")

    def _wait(self, action: Action) -> Outcome:
        before = self._signature()
        tab = self._watch(before, set(self.context.pages))
        if tab is not None:
            self.page = tab
            return Outcome(True, "a new tab opened", tab)
        return Outcome(self._signature() != before, "the page changed" if self._signature() != before else "nothing changed")

    def _back(self, action: Action) -> Outcome:
        if self.page.go_back(timeout=CLICK_MS, wait_until="domcontentloaded") is not None:
            return Outcome(True, "went back")
        others = [p for p in self.context.pages if p is not self.page and not p.is_closed()]
        if others:  # no history here: this tab was opened for the detour, so close it and return to the one before
            self.page.close()
            self.page = others[-1]
            return Outcome(True, "closed the tab and went back to the one before", self.page)
        return Outcome(False, "there is nowhere to go back to")

