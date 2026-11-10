"""Generic form filler used by Wellfound, LinkedIn and Indeed (and any future portal).

Fills what the profile can honestly answer; reports (via the resolver) what it cannot.
Optional empty fields are skipped silently; required ones with no answer park the job.

How a portal marks a required question differs: most mark it (`required`, a `*`), Indeed marks the OPTIONAL ones
"(optional)" and leaves the rest bare. `default_required` is for that second kind of portal.
"""
from __future__ import annotations

import re
from time import monotonic
from typing import Optional

from ..answers import AnswerResolver

TEXT_TYPES = {"text", "number", "tel", "email", "url", "search", ""}
OPTIONAL = re.compile(r"\(\s*optional\s*\)|\boptional\s*$", re.I)  # "(optional)" or a label that ends in the word
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")

LABEL_JS = """e => {
  let t = '';
  if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) t = l.innerText; }
  if (!t) { const l = e.closest('label'); if (l) t = l.innerText; }
  if (!t) t = e.getAttribute('aria-label') || '';
  if (!t) { const by = e.getAttribute('aria-labelledby'); if (by) { const n = document.getElementById(by.split(' ')[0]); if (n) t = n.innerText; } }
  if (!t) { let p = e.parentElement; for (let i = 0; i < 3 && p && !t; i++, p = p.parentElement) {
      const x = p.querySelector('label, legend, [class*=label]'); if (x) t = x.innerText; } }
  return (t || e.placeholder || '').trim();
}"""

RADIO_JS = """box => {
  const groups = {};
  const words = r => {  // a radio with an empty label (LinkedIn): the words beside it, up to where a second radio begins
    for (let e = r.parentElement; e && e !== box; e = e.parentElement) {
      if (e.querySelectorAll('input[type=radio]').length > 1) return '';
      const t = (e.innerText || '').trim(); if (t) return t;
    }
    return '';
  };
  box.querySelectorAll('input[type=radio]').forEach(r => {
    const g = groups[r.name] = groups[r.name] || {name: r.name, legend: '', options: []};
    let text = r.labels && r.labels[0] ? r.labels[0].innerText.trim() : '';
    if (!text) text = words(r);
    if (!g.legend) {
      const fs = r.closest('fieldset'); const rg = r.closest('[role=radiogroup]');
      g.legend = (fs && fs.querySelector('legend') ? fs.querySelector('legend').innerText
                  : (rg && (rg.getAttribute('aria-label') || '')) || '').trim();
      const aria = (r.getAttribute('aria-label') || '').trim();  // the question can ride on the inputs themselves
      if (!g.legend && aria && aria !== text) g.legend = aria;
      if (!g.legend) { const p = r.closest('fieldset, [role=radiogroup], div'); g.legend = p ? p.innerText.split('\\n')[0].trim() : ''; }
    }
    g.options.push((text || r.value || '').trim());
  });
  return Object.values(groups).filter(g => g.name);
}"""


CHECKBOX_JS = """box => {  // groups of tick boxes (several in one fieldset) and lone ones, in page order
  const boxes = [...box.querySelectorAll('input[type=checkbox]')];
  // A lone box is often just "I acknowledge": the question is the block of text around it (up to the next input), minus any
  // error the portal added after a failed Next. Only when that block says more than the label does.
  const context = (e, label) => {
    let best = '';
    for (let a = e.parentElement, n = 0; a && a !== box && n < 6; a = a.parentElement, n++) {
      if (a.querySelectorAll('input, select, textarea').length > 1) break;
      best = a.innerText || '';
    }
    best = best.replace(/This field is required\\.?|Please enter a valid answer\\.?/gi, ' ').replace(/\\s+/g, ' ').trim();
    return best.length > label.length + 15 ? best.slice(0, 400) : '';
  };
  const groups = new Map();
  boxes.forEach((e, index) => {
    const holder = e.closest('fieldset, [role=group]');
    const key = holder && holder.querySelectorAll('input[type=checkbox]').length > 1 ? holder : e;
    if (!groups.has(key)) groups.set(key, {legend: '', options: [], indexes: [], ticked: false, context: ''});
    const g = groups.get(key);
    if (key !== e && !g.legend) {
      const l = holder.querySelector('legend');
      g.legend = ((l && l.innerText) || holder.getAttribute('aria-label') || '').trim();
    }
    const label = ((e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute('aria-label')) || '').trim();
    g.options.push(label);
    if (key === e) g.context = context(e, label);
    g.indexes.push(index);
    g.ticked = g.ticked || e.checked;
  });
  return [...groups.values()];
}"""


def _is_required(field, label: str, default: bool = False) -> bool:
    """A question marked "(optional)" is never required; otherwise the portal's own mark, else the portal's habit."""
    if OPTIONAL.search(label):
        return False
    return (
        field.get_attribute("required") is not None
        or field.get_attribute("aria-required") == "true"
        or label.rstrip().endswith("*")
        or default
    )


def _field_text(kind: str, answer: str):
    """What to type for this answer in this kind of box, or None when it cannot be typed there at all."""
    if kind == "number":  # "5 years" and "4.0" are answers, but a number box takes only the digits
        found = NUMBER.search(answer)
        return None if found is None else found.group(0).removesuffix(".0")
    if kind == "date":  # a date box takes only YYYY-MM-DD: "30 days" is a real answer that does not fit
        return answer if ISO_DATE.match(answer.strip()) else None
    return answer


def _fill_text_fields(box, resolver: AnswerResolver, default_required: bool = False) -> None:
    for field in box.locator("input, textarea").all():
        try:
            tag = field.evaluate("e => e.tagName.toLowerCase()")
            kind = (field.get_attribute("type") or "").lower()
            if not field.is_visible() or not field.is_editable():
                continue
            if tag == "input" and kind not in TEXT_TYPES | {"date"}:
                continue
            if field.input_value().strip():
                continue  # already filled by the portal (profile pre-fill)
            label = field.evaluate(LABEL_JS)
            if not label:
                continue
            answer = resolver.resolve(label, required=_is_required(field, label, default_required),
                                      read=lambda field=field: field.input_value(timeout=READ_MS))
            text = None if answer is None else _field_text(kind, answer)
            if text is not None:
                field.fill(text)
        except Exception:
            continue  # a flaky widget must not sink the whole form


PLACEHOLDER = re.compile(r"^(select|choose|please)", re.I)
READ_MS = 500  # reading a control you may have moved on from must fail fast, not wait out the browser's 30 second default


def _chosen(select, options) -> Optional[str]:
    """What the person picked in a dropdown, if it is one of the real choices (not the \"Select...\" placeholder)."""
    text = select.evaluate("e => e.selectedOptions.length ? e.selectedOptions[0].innerText.trim() : ''", timeout=READ_MS)
    return text if text in options else None


def _ticked(radios, options) -> Optional[str]:
    """The option whose radio button the person ticked, or None while none is. Raises once the buttons are gone from the page."""
    count = radios.count()
    if count == 0:
        raise LookupError("the radio buttons are gone from the form")
    for index in range(count):
        if radios.nth(index).is_checked(timeout=READ_MS):
            return options[index]
    return None


def _ticked_box(boxes, group, lone: bool) -> Optional[str]:
    """A lone tick box ticked is Yes; in a group it is the option ticked. None while nothing is ticked."""
    for position, index in enumerate(group["indexes"]):
        if boxes.nth(index).is_checked(timeout=READ_MS):
            return "Yes" if lone else group["options"][position]
    return None


def _fill_selects(box, resolver: AnswerResolver, keep_chosen: bool = False, default_required: bool = False) -> None:
    for select in box.locator("select").all():
        try:
            if not select.is_visible():
                continue
            chosen = select.evaluate("e => e.selectedOptions.length ? e.selectedOptions[0].innerText.trim() : ''")
            if keep_chosen and chosen and not PLACEHOLDER.match(chosen):
                continue  # the portal already chose (LinkedIn pre-fills your email and phone code): never overwrite that
            label = select.evaluate(LABEL_JS)
            options = [o.strip() for o in select.locator("option").all_inner_texts() if o.strip()]
            options = [o for o in options if not PLACEHOLDER.match(o)]
            required = _is_required(select, label, default_required)
            answer = resolver.resolve(label, options, required=required, read=lambda select=select: _chosen(select, options)) if label else None
            if answer is not None:
                select.select_option(label=answer)
        except Exception:
            continue


def radio_groups(box) -> list:
    """Every group of radio buttons in `box`: {name, legend, options}."""
    return box.evaluate(RADIO_JS)


def click_choice(control) -> None:
    """Tick a radio or tick box. Custom-styled ones hide the input: click its label, then verify it registered."""
    control.evaluate("e => (e.labels && e.labels[0]) ? e.labels[0].click() : e.click()")
    if not control.is_checked():
        control.check(force=True)


def _fill_radios(box, resolver: AnswerResolver) -> None:
    for group in radio_groups(box):
        radios = box.locator(f'input[type="radio"][name="{group["name"]}"]')
        if any(radios.nth(i).is_checked() for i in range(radios.count())):
            continue
        answer = resolver.resolve(group["legend"], group["options"], required=not OPTIONAL.search(group["legend"]),
                                  read=lambda radios=radios, options=group["options"]: _ticked(radios, options))
        if answer is None:
            continue
        click_choice(radios.nth(group["options"].index(answer)))


def _fill_checkboxes(box, resolver: AnswerResolver) -> None:
    """A lone tick box is a yes/no question (tick on Yes); a group is a pick-one question. Never unticks, never
    touches a group the portal already ticked something in. Required only when the portal says so: a "send me job
    alerts" box must not park the job just because nobody answered it."""
    boxes = box.locator("input[type=checkbox]")
    for group in box.evaluate(CHECKBOX_JS):
        try:
            if group["ticked"]:
                continue
            lone = len(group["options"]) == 1
            first = boxes.nth(group["indexes"][0])
            question = (group["context"] or group["options"][0]) if lone else group["legend"]
            # the portal marks the question, not always the box: a "*" in the text around a lone box makes it required
            required = _is_required(first, question) or (lone and "*" in group["context"])
            options = ["Yes", "No"] if lone else group["options"]
            answer = resolver.resolve(question, options, required=required, read=lambda first=first, group=group, lone=lone: _ticked_box(
                boxes, group, lone))
            if answer is None:
                continue
            if lone and answer != "Yes":
                if required:
                    resolver.refuse(question)  # the portal will not go on without the tick, and the answer says not to tick
                continue
            click_choice(boxes.nth(group["indexes"][0 if lone else group["options"].index(answer)]))
        except Exception:
            continue


POLL_MS = 1000


def _say_needed(resolver: AnswerResolver, norms, seconds: float, also: bool = False) -> None:
    shown = "; ".join(resolver.questions_of(norms)[:3])
    resolver.attention.alert(
        f"Your answer is {'also ' if also else ''}needed on {resolver.portal}: {shown}. Type or tick it in the form in the browser, "
        f"or answer it in the panel (Questions); waiting up to {seconds:.0f}s, then this job is skipped.")


def let_person_answer(page, resolver: AnswerResolver, refill) -> None:
    """Questions nobody could answer are on screen. Instead of giving up on the spot, keep the form open for the usual wait: the
    person may type or tick the answers into the portal's own form (each is saved as an ordinary saved answer), or answer in the
    panel (the form is filled from it). `refill` fills whatever has become answerable. Returns when nothing is left to answer or
    the wait is over; the caller then goes on, or parks the job, exactly as before.

    Answering one question can open another (LinkedIn shows "Last working date" once you say you are serving notice). A question
    that appears during the wait is announced and given a wait of its own, so a person answering step by step is not cut off by
    a clock that started at the first question; the run's own time limit still bounds it.

    A question this run already waited on in vain is not waited on again, and a run with no panel to answer in never waits."""
    attention = resolver.attention
    unanswered = resolver.waiting_on()
    if attention is None or not unanswered or unanswered <= attention.given_up:
        return
    patience = attention.seconds()
    if patience <= 0:
        return
    _say_needed(resolver, unanswered, patience)
    announced = set(unanswered)
    resolver.waited = True
    end = monotonic() + patience
    while True:
        resolver.take_answers()  # first what was typed here, so that the fill below does not overwrite or ignore it
        resolver.start_pass()
        refill()
        pending = resolver.waiting_on()
        if not pending:
            return
        fresh = pending - announced
        if fresh:  # answering one question opened another: say so, and give it a wait of its own
            announced |= fresh
            patience = attention.seconds()
            if patience > 0:
                _say_needed(resolver, fresh, patience, also=True)
            end = monotonic() + patience
        if monotonic() >= end:
            break
        page.wait_for_timeout(POLL_MS)
    attention.given_up.update(resolver.waiting_on())


def fill_form(box, resolver: AnswerResolver, keep_chosen: bool = False, default_required: bool = False) -> None:
    """Fill every field in `box` (a page or locator) that the profile can answer.

    keep_chosen: leave a dropdown alone when something real is already selected in it (a portal's own pre-fill).
    Off by default: on a plain form the first option is just the browser's default, not an answer.
    default_required: treat a text box or dropdown as required unless its label says "(optional)" (Indeed's way).
    """
    _fill_text_fields(box, resolver, default_required)
    _fill_selects(box, resolver, keep_chosen, default_required)
    _fill_radios(box, resolver)
    _fill_checkboxes(box, resolver)
