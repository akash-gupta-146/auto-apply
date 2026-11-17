"""Draw a resume. Pure: the same resume and template always give the same page, and nothing else is touched.

`render(doc, template)` returns the page's HTML and its CSS; `document(...)` wraps them into one complete page. The preview in the panel and the PDF are
both made from that very page, so what you see is what is exported. Every word goes through `escape`: a resume can never put markup, a script or
a link to anything but a web page on the page. The templates that are safe for applicant tracking systems (single column, real text, plain headings,
no tables, no pictures) are marked so; the creative one is marked as less safe, and says why.

No HTTP in here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional

from .doc import HEADINGS, PRESENT, SECTIONS, bullets_of, visible_sections

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FONT_STACKS = {"sans": '"Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif',
               "serif": 'Georgia, "Times New Roman", "Liberation Serif", serif'}
GAPS = {"compact": "0.55em", "normal": "0.9em", "relaxed": "1.3em"}
PAPER = {"A4": ("210mm", "297mm"), "Letter": ("8.5in", "11in")}
SIDEBAR_SECTIONS = ("education", "skills", "certifications", "languages")  # a two-column template puts these beside the rest


class Rendered(NamedTuple):
    html: str
    css: str


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    about: str
    css: str
    ats_safe: bool = True
    columns: bool = False


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def month(iso: str) -> str:
    """'2021-03' as 'Mar 2021'; 'present' as 'Present'. Dates are kept as ISO months, so how they look is only ever decided here."""
    if iso == PRESENT:
        return "Present"
    return f"{MONTHS[int(iso[5:7]) - 1]} {iso[:4]}" if iso else ""


def dates(start: str, end: str) -> str:
    return " \u2013 ".join(part for part in (month(start), month(end)) if part) if (start or end) else ""


# -- the parts a template is made of -------------------------------------------------------------------------------------------------------
def _bullets(items: List[str]) -> str:
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>" if items else ""


def _row(what: str, when: str) -> str:
    return f'<div class="row"><span class="what">{what}</span>' + (f'<span class="when">{_e(when)}</span>' if when else "") + "</div>"


def _join(*parts: str) -> str:
    return ", ".join(part for part in parts if part)


def _link(url: str, label: str) -> str:
    return f'<a href="{_e(url)}">{_e(label)}</a>'  # a stored address is always http(s): doc.normalize saw to that


def header(doc: Mapping) -> str:
    basics = doc["basics"]
    contact = [_e(value) for value in (basics["email"], basics["phone"], basics["location"]) if value]
    contact += [_link(link["url"], link["label"]) for link in basics["links"]]
    return ('<header class="top">' + (f"<h1>{_e(basics['name'])}</h1>" if basics["name"] else "")
            + (f'<p class="headline">{_e(basics["headline"])}</p>' if basics["headline"] else "")
            + (f'<p class="contact">{" | ".join(contact)}</p>' if contact else "") + "</header>")


def _summary(doc: Mapping) -> str:
    return f"<p>{_e(doc['summary'])}</p>"


def _experience(doc: Mapping) -> str:
    return "".join('<div class="entry">' + _row(f"<strong>{_e(e['title'])}</strong>" + (f", {_e(_join(e['company'], e['location']))}" if e["company"] or e["location"] else ""),
                                                  dates(e["start"], e["end"])) + _bullets(e["bullets"]) + "</div>" for e in doc["experience"])


def _education(doc: Mapping) -> str:
    return "".join('<div class="entry">' + _row(f"<strong>{_e(_join(e['degree'], e['field']))}</strong>" + (f", {_e(e['school'])}" if e["school"] else ""),
                                                  dates(e["start"], e["end"])) + _bullets(e["details"]) + "</div>" for e in doc["education"])


def _skills(doc: Mapping) -> str:
    return "".join('<p class="skills">' + (f"<strong>{_e(s['group'])}:</strong> " if s["group"] else "") + _e(", ".join(s["items"])) + "</p>" for s in doc["skills"])


def _projects(doc: Mapping) -> str:
    return "".join('<div class="entry">' + _row(f"<strong>{_e(p['name'])}</strong>" + (f" ({_link(p['url'], p['url'])})" if p["url"] else ""), "") + _bullets(p["bullets"]) + "</div>"
                   for p in doc["projects"])


def _certifications(doc: Mapping) -> str:
    return "".join('<div class="entry">' + _row(f"<strong>{_e(c['name'])}</strong>" + (f", {_e(c['issuer'])}" if c["issuer"] else ""), month(c["date"])) + "</div>"
                   for c in doc["certifications"])


def _languages(doc: Mapping) -> str:
    return "<p>" + _e(", ".join(l["name"] + (f" ({l['level']})" if l["level"] else "") for l in doc["languages"])) + "</p>"


BODIES: Dict[str, Callable[[Mapping], str]] = {"summary": _summary, "experience": _experience, "education": _education, "skills": _skills,
                                               "projects": _projects, "certifications": _certifications, "languages": _languages}
assert set(BODIES) == set(SECTIONS)  # a section the document knows has a way to be drawn


def section(doc: Mapping, key: str) -> str:
    return f'<section class="sec sec-{key}"><h2>{HEADINGS[key]}</h2>{BODIES[key](doc)}</section>'


# -- the templates ---------------------------------------------------------------------------------------------------------------------------
TEMPLATES: Dict[str, Template] = {t.id: t for t in (
    Template("classic", "Classic", "One column, plain headings with a rule under them. The safest choice.",
             "h1{text-align:center;font-size:1.9em;margin:0}.headline,.contact{text-align:center;margin:.2em 0}"
             "h2{font-size:1em;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #444;padding-bottom:.15em;margin:var(--gap) 0 .4em}"),
    Template("compact", "Compact", "One column with tighter spacing and a left-aligned header: fits more on a page.",
             "h1{font-size:1.6em;margin:0}.headline,.contact{margin:.1em 0}h2{font-size:1em;font-weight:700;margin:calc(var(--gap) * .7) 0 .25em}"
             ".entry{margin-bottom:.35em}ul{margin:.15em 0}"),
    Template("modern", "Modern", "One column with your accent colour on the name and headings. Still plain text underneath.",
             "h1{font-size:2em;margin:0;color:var(--accent)}.headline{margin:.1em 0;font-weight:600}.contact{margin:.2em 0}"
             "h2{font-size:1.05em;color:var(--accent);border-left:4px solid var(--accent);padding-left:.5em;margin:var(--gap) 0 .4em}"),
    Template("simple", "Simple", "One column, no rules and no colour: nothing but text. What a parser reads most easily.",
             "h1{font-size:1.7em;margin:0}.headline,.contact{margin:.15em 0}h2{font-size:1em;font-weight:700;text-transform:uppercase;margin:var(--gap) 0 .3em}"),
    Template("elegant", "Elegant", "One column, centred, with a serif look to the headings and a fine rule in your accent colour. Still plain text underneath.",
             "h1{font-size:1.9em;margin:0;letter-spacing:.08em;font-weight:600;text-align:center;color:var(--accent)}.headline,.contact{text-align:center;margin:.2em 0}"
             "h2{font-family:Georgia,'Times New Roman',serif;font-size:1.1em;font-weight:600;color:var(--accent);border-bottom:2px solid var(--accent);padding-bottom:.1em;margin:var(--gap) 0 .4em}"),
    Template("sidebar", "Sidebar (creative)", "Two columns with the details beside the experience. Looks different, but some applicant tracking systems "
             "read columns out of order, so it is less safe for applications.",
             ".layout{display:grid;grid-template-columns:30% 1fr;column-gap:1.4em}h1{font-size:1.9em;margin:0;color:var(--accent)}"
             "h2{font-size:1em;text-transform:uppercase;color:var(--accent);margin:var(--gap) 0 .3em}.layout aside{border-right:1px solid #ccc;padding-right:1em}",
             ats_safe=False, columns=True),
)}


def catalog() -> List[Dict[str, Any]]:
    """What the template chooser shows."""
    return [{"id": t.id, "name": t.name, "about": t.about, "ats_safe": t.ats_safe} for t in TEMPLATES.values()]


def _theme_css(theme: Mapping) -> str:
    width, height = PAPER[theme["page"]]
    return (f":root{{--accent:{theme['accent']};--gap:{GAPS[theme['spacing']]};--font:{FONT_STACKS[theme['font']]};--size:{theme['size']}pt}}"
            f"@page{{size:{theme['page']};margin:16mm}}"
            f"body{{margin:0;font-family:var(--font);font-size:var(--size);line-height:1.35;color:#111;"
            f"font-variant-ligatures:none;font-feature-settings:'liga' 0,'clig' 0}}"  # no ligatures: a PDF would hold one glyph for "fi", and a system searching for "Certified" would not find it
            f".resume a{{color:inherit;text-decoration:none}}.resume ul{{margin:.25em 0;padding-left:1.2em}}.resume p{{margin:.25em 0}}"
            f".row{{display:flex;justify-content:space-between;gap:1em}}.when{{white-space:nowrap}}.entry{{margin-bottom:.6em;break-inside:avoid}}"
            f"h2{{break-after:avoid}}"
            f"@media screen{{body{{background:#e6e8ee;padding:14px 0}}.page{{box-sizing:border-box;width:{width};min-height:{height};margin:0 auto;padding:16mm;"
            f"background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.25)}}}}")


def render(doc: Mapping, template_id: Optional[str] = None) -> Rendered:
    """The resume as a page. `template_id` tries another look without changing the resume (the preview's template chooser)."""
    template = TEMPLATES.get(template_id or doc["template"])
    if template is None:
        raise ValueError("There is no such template.")
    shown = visible_sections(doc)
    if template.columns:
        aside = "".join(section(doc, key) for key in shown if key in SIDEBAR_SECTIONS)
        main = "".join(section(doc, key) for key in shown if key not in SIDEBAR_SECTIONS)
        body = f'{header(doc)}<div class="layout"><aside>{aside}</aside><div class="main">{main}</div></div>'
    else:
        body = header(doc) + "".join(section(doc, key) for key in shown)
    return Rendered(f'<article class="resume tpl-{template.id}">{body}</article>', _theme_css(doc["theme"]) + template.css)


def document(rendered: Rendered, title: str = "Resume") -> str:
    """One complete page: what the preview shows and what the PDF is printed from."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title><style>{rendered.css}</style></head>'
            f'<body><main class="page">{rendered.html}</main></body></html>')


# -- how long it will be ---------------------------------------------------------------------------------------------------------------------
def estimate_pages(doc: Mapping) -> int:
    """A careful guess at the page count (the real one is only known when the PDF is made): lines of text at this size, over lines a page holds."""
    theme = doc["theme"]
    per_line = 95 * 10.5 / theme["size"]
    lines = 4.0 + sum(2.0 + sum(_lines_of(text, per_line) for text in _texts(doc, key)) + _rows(doc, key) for key in visible_sections(doc))
    per_page = 62 * (10.5 / theme["size"]) / {"compact": 0.92, "normal": 1.0, "relaxed": 1.12}[theme["spacing"]] * (0.94 if theme["page"] == "Letter" else 1.0)
    return max(1, math.ceil(lines / per_page))


def _texts(doc: Mapping, key: str) -> List[str]:
    if key == "summary":
        return [doc["summary"]]
    texts: List[str] = []
    for entry in doc[key]:
        texts += bullets_of(entry) + ([", ".join(entry["items"])] if entry.get("items") else [])
    return texts


def _rows(doc: Mapping, key: str) -> float:
    return 0.0 if key in ("summary", "skills") else len(doc[key]) * 1.4  # an entry's heading line, and the gap after it


def _lines_of(text: str, per_line: float) -> int:
    return max(1, math.ceil(len(text) / per_line))
