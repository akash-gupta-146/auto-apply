"""One look at the current page: its text, its alerts, its job data, and every control a person could use, numbered.

It reads the page the way an accessibility tool does (names, roles, states), not by any site's markup, so it works on any page.
Each control gets a number (a data-ja-ref attribute) that the agent uses to act on it: the number is only good until the next look.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..adapters.forms import LABEL_JS
from .labels import GENERIC_NAME
from .models import Element, Observation

MAX_ELEMENTS = 150
MAX_TEXT = 4000
FRAME_TEXT = 2000  # how much of each frame's words is added to the page's own
MAX_FRAMES = 6  # an ad-heavy page has many frames; the first few real ones settle what the page is
MIN_FRAME_WIDTH, MIN_FRAME_HEIGHT = 100, 40  # trackers, beacons and spacers are a pixel or so: a form a person fills in is not
CAPTCHA_FRAME = re.compile(r"captcha|turnstile|challenges\.cloudflare\.com|arkoselabs|funcaptcha", re.I)  # never offered: a person solves these

SNAPSHOT_JS = """(base = 0) => {  // base: how many controls the page's other frames already numbered, so every number is unique
  const labelOf = __LABEL_JS__;
  const clean = t => (t || '').replace(/\\s+/g, ' ').trim();
  const INTERACTIVE = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=combobox], [role=checkbox], '
    + '[role=radio], [role=switch], [role=tab], [role=option], [role=textbox], [role=searchbox], [contenteditable=""], [contenteditable=true]';
  const shown = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[aria-hidden=true]');
  const stylable = e => ['radio', 'checkbox'].includes(e.type) && !shown(e) && e.labels && [...e.labels].some(shown);  // a styled box hides its input
  const collect = (root, out) => {
    root.querySelectorAll('[data-ja-ref]').forEach(e => e.removeAttribute('data-ja-ref'));
    root.querySelectorAll(INTERACTIVE).forEach(e => out.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) collect(e.shadowRoot, out); });
    return out;
  };
  const GENERIC = new RegExp('__GENERIC__', 'i');
  const nameOf = e => {
    const role = e.getAttribute('role') || '', tag = e.tagName.toLowerCase();
    let t = '';
    const by = e.getAttribute('aria-labelledby');
    if (by) { const root = e.getRootNode(); t = by.split(/\\s+/).map(id => { const n = root.getElementById ? root.getElementById(id) : null; return n ? n.innerText : ''; }).join(' '); }
    if (!t) { t = e.getAttribute('aria-label') || ''; if (GENERIC.test(t.trim())) t = ''; }  // "textbox" says what it is, not what it asks
    const words = ['button', 'a', 'summary'].includes(tag) || ['button', 'link', 'tab', 'option', 'radio', 'checkbox', 'switch', 'menuitem'].includes(role);
    if (!t && words) t = e.innerText || e.textContent;
    if (!t && tag === 'input' && ['submit', 'button', 'reset'].includes(e.type)) t = e.value;
    if (!t && !words) t = labelOf(e);
    return clean(t || e.getAttribute('title') || e.placeholder || e.getAttribute('name') || '').slice(0, 160);
  };
  const PLACEHOLDER = /^(select|choose|please|--)/i;
  const ids = new WeakMap();
  const groupId = g => { if (!g) return ''; if (!ids.has(g)) ids.set(g, 'aria-' + (ids.size + 1)); return ids.get(g); };  // a radio group built from divs
  const valueOf = (e, popup) => {
    if (e.type === 'password') return '';
    if (e.type === 'file') return e.files && e.files.length ? e.files[0].name : '';
    if (e.tagName === 'SELECT') { const o = e.selectedOptions[0]; return o && o.value !== '' && !PLACEHOLDER.test(clean(o.innerText)) ? clean(o.innerText) : ''; }
    if (e.tagName !== 'INPUT' && e.tagName !== 'TEXTAREA') { const t = popup || e.isContentEditable ? clean(e.innerText) : ''; return PLACEHOLDER.test(t) ? '' : t; }
    return ['radio', 'checkbox'].includes(e.type) ? '' : (e.value || '');
  };
  const legendOf = e => {
    const fs = e.closest('fieldset'), lg = fs && fs.querySelector('legend');
    if (lg) return clean(lg.innerText);
    const g = e.closest('[role=radiogroup], [role=group]');
    if (g) {
      const ids = g.getAttribute('aria-labelledby'), n = ids && document.getElementById(ids.split(' ')[0]);
      const t = g.getAttribute('aria-label') || (n ? n.innerText : '');
      if (t) return clean(t);
    }
    const same = e.name ? [...document.getElementsByName(e.name)] : [e];
    if (same.length < 2) return '';
    const own = new Set(same.map(s => clean(((s.labels && s.labels[0]) || {}).innerText)));
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      if (!same.every(s => p.contains(s))) continue;
      const line = (p.innerText || '').split('\\n').map(clean).find(l => l && !own.has(l));
      if (line) return line.slice(0, 200);
    }
    return '';
  };
  const relevant = m => m.querySelector('input, select, textarea') || /appl|resume|\\bcv\\b|question|candidate|sign in|log in/i.test(m.innerText || '');
  const modals = [...document.querySelectorAll('dialog[open], [role=dialog], [role=alertdialog], [aria-modal=true]')]
    .filter(m => m !== document.body && shown(m) && relevant(m));
  const modal = modals.length ? modals[modals.length - 1] : null;

  const seen = new Set(), elements = [];
  collect(document, []).forEach(e => {
    if (seen.has(e)) return; seen.add(e);
    if (!(shown(e) || stylable(e) || (e.type === 'file' && (!e.parentElement || shown(e.parentElement))))) return;  // a file input is hidden behind its button, but not inside a hidden popup
    const tag = e.tagName.toLowerCase(), role = e.getAttribute('role') || '', aria = e.getAttribute('aria-haspopup') || '';
    const popup = tag !== 'select' && (role === 'combobox' || aria === 'listbox' || aria === 'true' && role !== 'button' && role !== 'link');
    const editable = e.isContentEditable && tag !== 'input' && tag !== 'textarea';
    const ref = base + elements.length + 1;
    e.setAttribute('data-ja-ref', ref);
    const choice = ['radio', 'checkbox'].includes(e.type) || ['radio', 'checkbox', 'switch'].includes(role);
    const name = nameOf(e), legend = choice ? legendOf(e) : '';
    elements.push({
      ref, tag, role, type: editable ? 'contenteditable' : (e.type || ''), name, value: valueOf(e, popup).slice(0, 300),
      required: !!e.required || e.getAttribute('aria-required') === 'true' || /\\*\\s*$/.test(legend || name),
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
      checked: !!e.checked || e.getAttribute('aria-checked') === 'true',
      invalid: e.getAttribute('aria-invalid') === 'true',
      options: tag === 'select' ? [...e.options].map(o => clean(o.innerText)).filter(o => o && !PLACEHOLDER.test(o)) : [],
      group: ['radio', 'checkbox'].includes(e.type) ? (e.name || '') : (role === 'radio' ? groupId(e.closest('[role=radiogroup]')) : ''), legend,
      in_modal: !!modal && modal.contains(e),
      region: e.closest('form, main, [role=main], dialog, [role=dialog]') ? 'main'
        : (e.closest('nav, header, footer, aside, [role=navigation], [role=banner], [role=contentinfo]') ? 'chrome' : 'body'),
      href: tag === 'a' ? (e.href || '').slice(0, 300) : '', placeholder: e.placeholder || '', popup,
    });
  });

  const job = {};
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try {
      const walk = n => {
        if (Array.isArray(n)) return n.forEach(walk);
        if (!n || typeof n !== 'object') return;
        const types = [].concat(n['@type'] || []);
        if (types.includes('JobPosting') && !job.title) {
          const org = n.hiringOrganization || {}, loc = [].concat(n.jobLocation || [])[0] || {}, adr = loc.address || {};
          const id = n.identifier && typeof n.identifier === 'object' ? n.identifier.value : n.identifier;
          Object.assign(job, {
            title: clean(n.title), company: clean(typeof org === 'string' ? org : org.name),
            location: clean([adr.addressLocality, adr.addressRegion, adr.addressCountry && (adr.addressCountry.name || adr.addressCountry)].filter(Boolean).join(', ')),
            job_id: clean(id), employment_type: clean([].concat(n.employmentType || []).join(', ')),
            experience: clean(typeof n.experienceRequirements === 'string' ? n.experienceRequirements : ''),
            description: clean(String(n.description || '').replace(/<[^>]+>/g, ' ')).slice(0, 3000), url: clean(n.url),
          });
        }
        Object.values(n).forEach(walk);
      };
      walk(JSON.parse(s.textContent));
    } catch (e) {}
  });

  const alerts = [...new Set([...document.querySelectorAll('[role=alert], [aria-live=assertive], [class*=error i], [class*=invalid i], [data-testid*=error i]')]
    .filter(shown).map(e => clean(e.innerText)).filter(t => t.length > 2 && t.length < 220))].slice(0, 6);
  const meta = n => { const m = document.querySelector('meta[name="' + n + '"], meta[property="' + n + '"]'); return m ? clean(m.content) : ''; };
  return {
    url: location.href, title: document.title, description: meta('description') || meta('og:description'),
    text: (document.body ? document.body.innerText : '').slice(0, __MAX_TEXT__), modal_text: modal ? clean(modal.innerText).slice(0, 1500) : '',
    has_modal: !!modal, headings: [...document.querySelectorAll('h1, h2, h3')].filter(shown).map(h => clean(h.innerText)).filter(Boolean).slice(0, 8),
    elements, job, alerts,
  };
}"""
SNAPSHOT_JS = SNAPSHOT_JS.replace("__GENERIC__", GENERIC_NAME.pattern).replace("__LABEL_JS__", LABEL_JS).replace("__MAX_TEXT__", str(MAX_TEXT))


class PageUnreadable(RuntimeError):
    """The page kept changing under the look (it was navigating): try again a moment later."""


def _keep(elements: List[Element], cap: int) -> List[Element]:
    """Over the cap, drop navigation and footer links first: the page's own content is what the next step is about."""
    if len(elements) <= cap:
        return elements
    ranked = sorted(elements, key=lambda e: (not e.in_modal, e.region == "chrome", e.ref))
    return sorted(ranked[:cap], key=lambda e: e.ref)


def to_observation(raw: Dict, cap: int = MAX_ELEMENTS) -> Observation:
    elements = [Element(**{**item, "options": list(item.get("options") or [])}) for item in raw.get("elements", [])]
    return Observation(
        url=raw.get("url", ""), title=raw.get("title", ""), description=raw.get("description", ""), text=raw.get("text", ""),
        headings=list(raw.get("headings", [])), elements=_keep(elements, cap), modal_text=raw.get("modal_text", ""),
        has_modal=bool(raw.get("has_modal")), job_posting={k: v for k, v in (raw.get("job") or {}).items() if v},
        alerts=list(raw.get("alerts", [])),
    )


def readable_frames(page) -> List[Any]:
    """The frames inside the page that a person could be using: shown, and big enough to hold a form. Not the page itself, not a hidden
    tracker, not a captcha. (Application forms are often an iframe of the company's recruiting system, on another site.)"""
    found = []
    for frame in page.frames:
        if frame.parent_frame is None or frame.is_detached() or CAPTCHA_FRAME.search(frame.url or ""):  # (no parent: the page itself)
            continue
        try:
            owner = frame.frame_element()
            box = owner.bounding_box()
            if box and box["width"] >= MIN_FRAME_WIDTH and box["height"] >= MIN_FRAME_HEIGHT and owner.is_visible():
                found.append(frame)
        except Exception:
            continue  # a frame that went away while it was looked at
        if len(found) >= MAX_FRAMES:
            break
    return found


def _merge_frame(raw: Dict[str, Any], inner: Dict[str, Any]) -> None:
    """Add what a frame holds to the page's own look: its controls (numbered after the page's), its words, its alerts and its dialog."""
    raw["elements"] = list(raw.get("elements", [])) + list(inner.get("elements", []))
    raw["text"] = f"{raw.get('text', '')}\n{(inner.get('text') or '')[:FRAME_TEXT]}"
    raw["headings"] = (list(raw.get("headings", [])) + list(inner.get("headings", [])))[:8]
    raw["alerts"] = (list(raw.get("alerts", [])) + [a for a in inner.get("alerts", []) if a not in raw.get("alerts", [])])[:6]
    if not raw.get("has_modal") and inner.get("has_modal"):
        raw["has_modal"], raw["modal_text"] = True, inner.get("modal_text", "")
    if not raw.get("job") and inner.get("job"):
        raw["job"] = inner["job"]


def snapshot(page) -> Dict[str, Any]:
    """The page and the frames inside it, as one look. A frame that goes away between the two is read without."""
    raw = page.evaluate(SNAPSHOT_JS)
    for frame in readable_frames(page):
        try:
            _merge_frame(raw, frame.evaluate(SNAPSHOT_JS, len(raw["elements"])))
        except Exception:
            continue
    return raw


def observe(page, cap: int = MAX_ELEMENTS, tries: int = 3) -> Observation:
    """Look at the page now. A page in the middle of a navigation is looked at again once it has settled."""
    last: Exception = PageUnreadable("the page could not be read")
    for _ in range(tries):
        try:
            return to_observation(snapshot(page), cap)
        except Exception as exc:  # "Execution context was destroyed": the page moved under us
            last = exc
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                page.wait_for_timeout(300)
    raise PageUnreadable(str(last)[:160])
