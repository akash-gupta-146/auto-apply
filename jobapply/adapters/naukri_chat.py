"""Naukri's side bar of screening questions: read what it asks, answer it, and notice what you answered yourself.

Every selector is UNVERIFIED against Naukri's current site: the bar's script is refused on some networks (docs/fix-plan.md, N1), so
it could not be seen live. They sit in SEL so a repair is a one-line edit, and a bar that never opens saves the page to data/failures.

So they are only the first try. When Naukri's reply has told us which questions it will ask, a bar that SEL does not match is looked for by the
text of those questions instead (naukri_chat_find.py), and read through what that finds. `Drawer.how` says what was found, for the log and the probe.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .base import first_visible
from .naukri_chat_find import TAGGED, find_bar

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

    def __init__(self, page, known: Sequence[str] = ()):
        self.page = page
        self.known = [question for question in known if question and question.strip()]  # what Naukri's reply said it will ask: the one certain thing
        self.how: Dict[str, str] = {}  # when the bar was found by the text of its questions: what was found, as tag#id.class
        self._question = ""  # the question shown, when found by its text

    def _look(self) -> Dict[str, str]:
        """The selectors that read the bar right now: the guessed ones if they match it, else those found from the text of its questions."""
        guessed = first_visible(self.page, [SEL["bar"]]) is not None and (not self.known or self.page.locator(SEL["bot_message"]).count() > 0)
        found = None if guessed or not self.known else find_bar(self.page, self.known)
        if found:
            self._question, self.how = str(found["question"]), dict(found["found"])  # type: ignore[arg-type]
            return TAGGED
        return SEL

    def found_by_text(self) -> bool:
        """The bar is open but the guessed selectors do not match it: they need repairing (`how` says to what)."""
        return self._look() is TAGGED

    def is_open(self) -> bool:
        return first_visible(self.page, [self._look()["bar"]]) is not None

    def question(self) -> str:
        """What the bar asked last."""
        sel = self._look()
        if sel is TAGGED:
            return self._question
        messages = self.page.locator(sel["bot_message"])
        return messages.last.inner_text().strip() if messages.count() else ""

    def options(self) -> List[str]:
        return [text.strip() for text in self.page.locator(self._look()["chips"]).all_inner_texts() if text.strip()]

    def said(self) -> int:
        """How many answers the chat holds. A rise since a question was asked means that question has been answered."""
        return self.page.locator(self._look()["user_message"]).count()

    def moved_on(self, question: str, said_before: int) -> bool:
        """The question was answered, here in the bar or by something else, and must not be answered a second time."""
        return self.question() != question or self.said() > said_before or self._sent_by_hand(question) is not None

    def given(self, options: List[str], said_before: int, question: Optional[str] = None) -> Optional[str]:
        """What you answered by hand: the choice you ticked, or the answer you sent. A half-typed text is never read, it may still
        change. Raises once the bar is gone, so the wait for you ends at once. `question` is the one being waited on."""
        sel = self._look()
        if first_visible(self.page, [sel["bar"]]) is None:
            raise LookupError("the question window is gone")
        if options:
            ticked = self.page.locator(sel["chips"]).evaluate_all(CHOSEN_JS)
            if ticked:
                return ticked
        if self.said() > said_before:
            return self.page.locator(sel["user_message"]).last.inner_text(timeout=READ_MS).strip()
        return self._sent_by_hand(question) if sel is TAGGED else None

    def _sent_by_hand(self, question: Optional[str]) -> Optional[str]:
        """A bar found by its text shows no bubble for your answer: it was recorded in the page as you sent it (see naukri_chat_find.py), with the question that was
        on screen. It is given only for that question. It is not consumed by being read: the one who reads wants the same value on two looks in a row (to be sure
        you have finished), and the record goes when the program answers something itself (`send`) or the page changes."""
        sent = self._page_eval("() => document.documentElement.__jbSent || null")
        if not sent or (question is not None and sent.get("q") != question):
            return None
        return str(sent.get("text") or "").strip() or None

    def _forget_sent(self) -> None:
        self._page_eval("() => { document.documentElement.__jbSent = null; }")

    def _page_eval(self, script: str):
        try:
            return self.page.evaluate(script)
        except Exception:  # the page is changing or gone: there is nothing to read
            return None

    def send(self, answer: str, is_choice: bool) -> None:
        page, sel = self.page, self._look()
        if is_choice:
            chip = page.locator(sel["chips"]).filter(has_text=re.compile(rf"^\s*{re.escape(answer)}\s*$", re.I)).first
            if not chip.evaluate(IS_TICKED_JS):  # clicking a ticked tick box would untick it
                chip.click()
        else:
            box = first_visible(page, [sel["input"]])
            if box is None:
                raise RuntimeError("the question window's text box was not found")
            box.click()
            page.keyboard.press("ControlOrMeta+A")  # replace whatever half-typed text is there
            page.keyboard.type(answer, delay=40)
        button = first_visible(page, [sel["send"]])
        if button is not None:
            button.click()
        elif not is_choice:
            page.keyboard.press("Enter")
        self._forget_sent()  # that was the program's answer, not yours: it must never be read back as one you gave

    def close(self) -> None:
        button = first_visible(self.page, [self._look()["close"]])
        if button is not None:
            button.click()
        else:
            self.page.keyboard.press("Escape")
