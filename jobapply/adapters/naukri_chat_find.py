"""Find Naukri's question side bar by what it SAYS, not by its class names: Naukri's own reply lists the exact text of every question it will ask.

The class names in naukri_chat.py are unverified guesses (its script was refused on the network they were written on), and a wrong one makes the bar
invisible. The text of a question is certain, so this looks for that text on the page and works outwards: the bar is the largest container around it
that holds the answer controls and none of the page's own boxes (its search field), and the answer box, the choices, Save and Close are found by what
they are. What it finds is marked with `data-jb` so the same Drawer code can read and answer through it, whichever markup Naukri really uses.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

# What Drawer reads through once the bar has been found by its text. 'user' is never marked: what you answered is read from the box you typed in.
TAGGED = {
    "bar": "[data-jb='bar']",
    "bot_message": "[data-jb='question']",
    "user_message": "[data-jb='user']",
    "chips": "[data-jb='chip']",
    "input": "[data-jb='input']",
    "send": "[data-jb='send']",
    "close": "[data-jb='close']",
}

FIND_JS = r"""(known) => {
  const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  for (const e of document.querySelectorAll('[data-jb]')) e.removeAttribute('data-jb');
  for (const e of document.querySelectorAll('[data-jbq]')) e.removeAttribute('data-jbq');
  const wanted = known.map(norm);
  const describe = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).join('.') : '');

  // 1. the question: the deepest visible element holding one of the known questions, the lowest on the page being the newest in a chat
  const hits = [];
  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('script, style, noscript, template') || e.children.length > 6 || !visible(e)) continue;
    const text = norm(e.textContent);
    if (text.length > 800) continue;
    const at = wanted.findIndex(w => w && text.includes(w));
    if (at >= 0) hits.push({e, at, r: e.getBoundingClientRect()});
  }
  const deepest = hits.filter(h => !hits.some(o => o !== h && h.e.contains(o.e)));
  if (!deepest.length) return null;
  const last = deepest.reduce((a, b) => b.r.bottom >= a.r.bottom ? b : a);
  const q = last.e, top = last.r.top;

  // 2. the bar: the largest container around it with answer controls at or after the question and no text box of the page's own before it
  const CONTROLS = 'input:not([type=hidden]), textarea, [contenteditable=""], [contenteditable="true"], [role=textbox], [role=radio], [role=checkbox], [role=option]';
  const ENTRY = e => e.matches('textarea, [contenteditable=""], [contenteditable="true"], [role=textbox]')
                  || (e.matches('input') && !['radio', 'checkbox', 'button', 'submit', 'file', 'image', 'reset'].includes(e.type));
  const after = e => visible(e) && e.getBoundingClientRect().top >= top - 2 && !q.contains(e);  // starts no higher than the question: the older questions' choices are above it
  let bar = null, past = false;
  for (let a = q.parentElement; a && a !== document.body && a !== document.documentElement && !past; a = a.parentElement) {
    const inside = [...a.querySelectorAll(CONTROLS)].filter(visible);
    if (inside.some(c => ENTRY(c) && c.getBoundingClientRect().bottom <= top)) break;  // the page's own search box: this is no longer the bar
    if (inside.some(after)) bar = a;
    if (getComputedStyle(a).position === 'fixed') past = true;  // a drawer is fixed to the window: nothing outside it belongs to it
  }
  if (!bar) return null;

  // 3. what is in it, below the question
  const within = sel => [...bar.querySelectorAll(sel)].filter(after);
  const mark = (e, role) => { if (e) e.setAttribute('data-jb', role); return e; };
  const labelOf = i => i.closest('label') || (i.id && document.querySelector('label[for="' + i.id + '"]')) || i.parentElement;
  let chips = within('input[type=radio], input[type=checkbox]').map(labelOf).filter(e => e && visible(e));
  if (!chips.length) chips = within('[role=radio], [role=checkbox], [role=option]');
  chips = [...new Set(chips)];
  const box = within('textarea, [contenteditable=""], [contenteditable="true"], [role=textbox], input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([type=button]):not([type=submit]):not([type=file])').pop();
  const SEND = /^(save|send|submit|next|done|continue|ok)$/i, SENDING = /send|save|submit/i;
  const send = within('button, [role=button], a, div, span').filter(e => !chips.includes(e) && !chips.some(c => c.contains(e)) && (
    (e.children.length === 0 && SEND.test((e.textContent || '').trim())) || SENDING.test(e.getAttribute('aria-label') || e.getAttribute('title') || ''))).pop();
  const shut = [...bar.querySelectorAll('[aria-label], [title], [class], button, span, div')].filter(e => visible(e) && !chips.includes(e) && (
    /close/i.test(e.getAttribute('aria-label') || e.getAttribute('title') || (typeof e.className === 'string' ? e.className : '')) ||
    (e.children.length === 0 && /^(x|\u00d7|\u2715|close)$/i.test((e.textContent || '').trim())))).shift();

  mark(bar, 'bar'); mark(q, 'question'); chips.forEach(c => mark(c, 'chip')); mark(box, 'input'); mark(send, 'send'); mark(shut, 'close');
  q.setAttribute('data-jbq', known[last.at]);
  // What you answer by hand is read at the moment you send it (a press of Save, or Enter in the box), before the page clears the box: the exact text, and the
  // question on screen then. Polling the box would miss a quick send, or keep half of what you typed.
  if (!document.documentElement.__jbWatch) {
    document.documentElement.__jbWatch = true;
    const record = () => {
      const box = document.querySelector('[data-jb=input]'), q = document.querySelector('[data-jb=question]');
      const text = box ? (('value' in box ? box.value : box.innerText) || '').trim() : '';
      if (q && text) document.documentElement.__jbSent = {q: q.getAttribute('data-jbq'), text};
    };
    document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-jb=send]')) record(); }, true);
    document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.closest && e.target.closest('[data-jb=input]')) record(); }, true);
  }
  const found = {bar: describe(bar), question: describe(q)};
  if (chips.length) found.chips = chips.map(describe).join(' | ');
  if (box) found.input = describe(box);
  if (send) found.send = describe(send);
  if (shut) found.close = describe(shut);
  return {question: known[last.at], found};
}"""


def find_bar(page, known: Sequence[str]) -> Optional[Dict[str, object]]:
    """Mark the bar on the page by the text of the questions Naukri said it would ask. None when no such text is on the page with answer controls beside it.
    Otherwise {"question": the known question shown lowest, "found": {role: what was found, as tag#id.class}}: the second is what to put in naukri_chat.SEL."""
    wanted = [question for question in known if question and question.strip()]
    if not wanted:
        return None
    try:
        return page.evaluate(FIND_JS, wanted)
    except Exception:  # the page is changing or gone: there is nothing to find right now
        return None
