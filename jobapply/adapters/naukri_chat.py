"""Naukri's side bar of screening questions: read what it asks, answer it, and notice what you answered yourself.

Every selector is UNVERIFIED against Naukri's current site: the bar's script is refused on some networks (docs/fix-plan.md, N1), so
it could not be seen live. They sit in SEL so a repair is a one-line edit, and a bar that never opens saves the page to data/failures.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .base import first_visible

READ_MS = 500  # reading a bar you may have closed must fail fast, not wait out the browser's 30 second default

SEL = {
    "bar": "[class*='chatbot_Drawer'], .chatbot_DrawerContentWrapper",
    "bot_message": "[class*='botMsg'], .botItem, [class*='botItem']",
    "user_message": "[class*='userMsg'], .userItem, [class*='userItem']",  # what has been answered so far, yours included
    "chips": "[class*='chatbot_Chip'], .ssrc__label, [class*='singleselect'] label, [class*='multiselect'] label",
    "input": "div[contenteditable='true'], [class*='chatbot'] input[type='text'], [class*='chatbot'] textarea",
    "send": "[class*='sendMsg'], button:has-text('Save'), button:has-text('Send')",
    "close": "[class*='chatbot_Close'], [class*='chatbot'] [class*='close']",
}

# A choice counts as ticked when the radio or tick box in (or for) it is checked, or the choice itself says so.
TICKED = """const ticked = e => {
  const i = e.matches('input') ? e : (e.querySelector('input') || (e.htmlFor && document.getElementById(e.htmlFor)));
  return i ? i.checked : ['aria-checked', 'aria-pressed'].some(a => e.getAttribute(a) === 'true');
};"""
CHOSEN_JS = "els => {" + TICKED + " const e = els.find(ticked); return e ? e.innerText.trim() : ''; }"
IS_TICKED_JS = "e => {" + TICKED + " return ticked(e); }"


class Drawer:
    """One look at the side bar, and the few things that can be done in it."""

    def __init__(self, page):
        self.page = page

    def is_open(self) -> bool:
        return first_visible(self.page, [SEL["bar"]]) is not None

    def question(self) -> str:
        """What the bar asked last."""
        messages = self.page.locator(SEL["bot_message"])
        return messages.last.inner_text().strip() if messages.count() else ""

    def options(self) -> List[str]:
        return [text.strip() for text in self.page.locator(SEL["chips"]).all_inner_texts() if text.strip()]

    def said(self) -> int:
        """How many answers the chat holds. A rise since a question was asked means that question has been answered."""
        return self.page.locator(SEL["user_message"]).count()

    def moved_on(self, question: str, said_before: int) -> bool:
        """The question was answered, here in the bar or by something else, and must not be answered a second time."""
        return self.question() != question or self.said() > said_before

    def given(self, options: List[str], said_before: int) -> Optional[str]:
        """What you answered by hand: the choice you ticked, or the answer you sent. A half-typed text is never read, it may still
        change. Raises once the bar is gone, so the wait for you ends at once."""
        if not self.is_open():
            raise LookupError("the question window is gone")
        if options:
            ticked = self.page.locator(SEL["chips"]).evaluate_all(CHOSEN_JS)
            if ticked:
                return ticked
        if self.said() > said_before:
            return self.page.locator(SEL["user_message"]).last.inner_text(timeout=READ_MS).strip()
        return None

    def send(self, answer: str, is_choice: bool) -> None:
        page = self.page
        if is_choice:
            chip = page.locator(SEL["chips"]).filter(has_text=re.compile(rf"^\s*{re.escape(answer)}\s*$", re.I)).first
            if not chip.evaluate(IS_TICKED_JS):  # clicking a ticked tick box would untick it
                chip.click()
        else:
            box = first_visible(page, [SEL["input"]])
            if box is None:
                raise RuntimeError("the question window's text box was not found")
            box.click()
            page.keyboard.press("ControlOrMeta+A")  # replace whatever half-typed text is there
            page.keyboard.type(answer, delay=40)
        button = first_visible(page, [SEL["send"]])
        if button is not None:
            button.click()
        elif not is_choice:
            page.keyboard.press("Enter")

    def close(self) -> None:
        button = first_visible(self.page, [SEL["close"]])
        if button is not None:
            button.click()
        else:
            self.page.keyboard.press("Escape")
