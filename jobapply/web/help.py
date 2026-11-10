"""A "?" button that shows an explanation when the pointer rests on it or it has the keyboard focus.

No JavaScript: the explanation sits in the page right after the button and the stylesheet keeps it hidden until then. It is real
page text, so the button points at it for a screen reader (aria-describedby) and a test can find it. The text is ours (it may hold
emphasis, a code sample or a line break), never something a person typed, so it is not escaped.
"""
from __future__ import annotations

from html import escape
from typing import Sequence, Tuple


def help_button(key: str, topic: str, body_html: str) -> str:
    """key: unique on the page (it names the explanation). topic: plain words for the button's name, e.g. 'AI Fill'."""
    tip = f"help-{key}"
    return (f'<span class="help"><button type="button" class="help-btn" aria-label="Help: {escape(topic, quote=True)}" '
            f'aria-describedby="{tip}">?</button><span class="help-tip" id="{tip}" role="tooltip">{body_html}</span></span>')


def topic_list(items: Sequence[Tuple[str, str, str]]) -> str:
    """A short list: each line is a title and, when there is more to say, a "?" with the rest. items: (key, title, body_html)."""
    rows = "".join(f"<li>{escape(title)}{help_button(key, title, body) if body else ''}</li>" for key, title, body in items)
    return f'<ul class="topics">{rows}</ul>'
