"""Read the exported PDF the way a parser would, and say what it could not read. The checks in builder/ats.py look at the resume as data; this looks at the file
a recruiter's system actually receives, because a resume can be fine as data and still come out of the PDF scrambled.

Deterministic, no AI, and no program is run: the PDF is only read. The whole scoring table is `RULES`, one place to audit:
  * a "blocker" is something that makes the file unreadable or the layout a gamble, and puts a ceiling on the score (a PDF with no text cannot score 80
    however tidy its margins are);
  * a "warning" takes points off its category, once however many times it happens (nine odd dates are one habit);
  * a "tip" is advice about taste. It is listed beside the score and never inside it.
The text the parser gets is returned too, so you can read it for yourself: where a sidebar comes out after your experience, or a word is split, it shows.

No HTTP and no HTML in here.
"""
from __future__ import annotations

import io
import math
import re
import statistics
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from pypdf import PdfReader

MAX_BYTES = 5_000_000
MAX_TEXT = 20_000
MAX_PAGES_READ = 6
# code -> (severity, category, points: a blocker's ceiling on the whole score, a warning's cost to its category)
RULES: Dict[str, Tuple[str, str, int]] = {
    "ENCRYPTED_PDF": ("blocker", "parseability", 40), "FILE_TOO_LARGE": ("blocker", "parseability", 40), "NO_TEXT_LAYER": ("blocker", "parseability", 10),
    "GARBLED_TEXT": ("blocker", "parseability", 25), "REPLACEMENT_CHARACTERS": ("warning", "parseability", 15), "LIGATURE_CHARACTERS": ("warning", "parseability", 10),
    "LOST_WORD_SPACING": ("warning", "parseability", 10), "FIELDS_LOST": ("warning", "parseability", 15),
    "MULTI_COLUMN_LAYOUT": ("blocker", "layout", 70), "READING_ORDER": ("warning", "layout", 15), "SMALL_BODY_TEXT": ("warning", "layout", 10),
    "NARROW_PAGE_MARGINS": ("warning", "layout", 5), "TEXT_OUTSIDE_PAGE": ("warning", "layout", 10), "HIGH_PAGE_COUNT": ("tip", "layout", 0),
    "NO_EMAIL": ("blocker", "contact", 50), "NO_PHONE": ("warning", "contact", 15), "NO_NAME_LINE": ("warning", "contact", 15),
    "NO_EXPERIENCE_SECTION": ("blocker", "sections", 60), "NO_RECOGNIZED_HEADINGS": ("warning", "sections", 15), "NO_EDUCATION_SECTION": ("warning", "sections", 10),
    "NO_SKILLS_SECTION": ("warning", "sections", 10), "VERY_SHORT_DOCUMENT": ("warning", "sections", 15),
    "DOCX_TEXT_BOX": ("warning", "layout", 15), "DOCX_TABLES": ("warning", "layout", 10), "DOCX_HEADER_FOOTER": ("warning", "contact", 15), "DOCX_IMAGES": ("tip", "layout", 0),
    "NO_DATES_FOUND": ("blocker", "dates", 60), "FEW_DATES": ("warning", "dates", 15), "MIXED_DATE_FORMATS": ("warning", "dates", 5),
}
WEIGHTS = {"parseability": 35, "layout": 20, "sections": 20, "contact": 15, "dates": 10}  # sums to 100
LABELS = {"parseability": "Readability", "layout": "Layout", "sections": "Sections", "contact": "Contact details", "dates": "Dates"}
BLOCKER_COST = 60  # what a blocker costs its own category, on top of the ceiling it puts on the whole score
POINTERS = {"NO_EMAIL": "/basics/email", "NO_PHONE": "/basics/phone", "NO_NAME_LINE": "/basics/name", "NO_DATES_FOUND": "/experience/0/start",
            "FEW_DATES": "/experience/0/start", "MULTI_COLUMN_LAYOUT": "/template", "SMALL_BODY_TEXT": "/theme/size", "NARROW_PAGE_MARGINS": "/theme/spacing"}
MESSAGES: Dict[str, Tuple[str, str]] = {
    "ENCRYPTED_PDF": ("The PDF is locked, so a system cannot read it.", "Export it again without a password."),
    "FILE_TOO_LARGE": ("The file is very large.", "Many systems refuse big files. A resume is a few hundred kilobytes."),
    "NO_TEXT_LAYER": ("There is no text in this file: it looks like a picture of text.", "A system cannot read pictures. Export the PDF again from a program that keeps the text (the builder does)."),
    "GARBLED_TEXT": ("Much of the text comes out as symbols.", "The fonts did not carry their letters. Use a plain font (Sans or Serif) and export again."),
    "REPLACEMENT_CHARACTERS": ("Some characters come out as boxes or question marks.", "Replace unusual symbols with plain letters and digits."),
    "LIGATURE_CHARACTERS": ("Some letter pairs (fi, fl) are joined into one symbol, which a system may not match to the word.", "Use a plain font, or avoid those words in your headings."),
    "LOST_WORD_SPACING": ("Some words run together with no space between them.", "Check how the text reads below and re-export; a different font often fixes it."),
    "FIELDS_LOST": ("Some of what you wrote does not come out of the file.", "See the list below: those parts would be missing for a system."),
    "MULTI_COLUMN_LAYOUT": ("The page has two columns. Some systems read across the page and mix them up.", "Choose a one-column template for applications."),
    "READING_ORDER": ("The text comes out in a different order from the page: a system would read your jobs in the wrong order.", "Use a one-column template."),
    "SMALL_BODY_TEXT": ("The body text is small.", "Use 10 points or more."),
    "NARROW_PAGE_MARGINS": ("The text runs very close to the edge of the page.", "Use roomier spacing: some systems cut off text at the edge."),
    "TEXT_OUTSIDE_PAGE": ("Some text sits outside the page.", "It will be cut off. Use roomier spacing, or a shorter line."),
    "HIGH_PAGE_COUNT": ("It runs to more than two pages.", "Two pages is as much as most recruiters read."),
    "NO_EMAIL": ("No email address comes out of the file.", "A system needs it to reach you. Check it in your details."),
    "NO_PHONE": ("No phone number comes out of the file.", "Add one with the country code."),
    "NO_NAME_LINE": ("Your name is not at the top of the text.", "Put your full name first: it is the first thing a system reads."),
    "NO_EXPERIENCE_SECTION": ("There is no Experience heading in the text.", "Systems look for it by name. Add your jobs, and keep the heading plain."),
    "NO_RECOGNIZED_HEADINGS": ("None of the section headings are ones a system looks for.", "Use plain headings: Experience, Education, Skills."),
    "NO_EDUCATION_SECTION": ("There is no Education heading in the text.", "Add your education, or show the section."),
    "NO_SKILLS_SECTION": ("There is no Skills heading in the text.", "Add a Skills section: it is the first place a keyword search looks."),
    "VERY_SHORT_DOCUMENT": ("The document is very short.", "Say more about what you did in each job."),
    "DOCX_TEXT_BOX": ("Some text is in a text box, and many systems skip text boxes entirely.", "Put it in ordinary paragraphs."),
    "DOCX_TABLES": ("The document uses a table. Some systems read tables cell by cell, in an order you did not intend.", "Use plain paragraphs and tabs instead of a table."),
    "DOCX_HEADER_FOOTER": ("Text sits in the page header or footer, often your contact details, and many systems ignore headers and footers.", "Move it into the body of the page."),
    "DOCX_IMAGES": ("The document has pictures. Software cannot read a picture, so anything written in one is lost.", "Keep your name and contact details as text, not as a picture."),
    "NO_DATES_FOUND": ("No dates come out of the file.", "Systems work out your experience from dates. Add the month each job began and ended."),
    "FEW_DATES": ("Only one date comes out of the file.", "Give every job a start and an end date."),
    "MIXED_DATE_FORMATS": ("Dates are written in more than one style.", "Use one style (like Jan 2020) throughout."),
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
HEADINGS = {"experience": ("experience", "work history", "employment", "professional experience", "work experience", "employment history"),
            "education": ("education", "academic", "qualifications"), "skills": ("skills", "technical skills", "core skills", "technologies", "competencies"),
            "summary": ("summary", "profile", "objective", "about")}
_MONTH = r"(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_YEAR = r"(?:19|20)\d{2}"
DATE_STYLES = re.compile(rf"(?P<iso>\b{_YEAR}[-/]\d{{1,2}}\b)|(?P<numeric>\b\d{{1,2}}[/.-]{_YEAR}\b)|(?P<name_year>\b{_MONTH}\.?,?\s+{_YEAR}\b)|(?P<year>\b{_YEAR}\b)")
LIGATURES = "\ufb00\ufb01\ufb02\ufb03\ufb04"
SIZE_FLOOR, MARGIN_FLOOR = 9.0, 28.0  # points: smaller text, or text nearer the edge than this, is flagged


class Box(NamedTuple):
    x: float
    y: float
    size: float
    text: str
    page: int


class Finding(NamedTuple):
    code: str
    severity: str
    category: str
    message: str
    fix: str
    pointer: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return self._asdict()


# -- reading the file ------------------------------------------------------------------------------------------------------------------------
def _read(data: bytes) -> Tuple[List[Box], str, List[Tuple[float, float]]]:
    """(the pieces of text with where each sits, the text as a parser gets it, the size of each page)."""
    reader = PdfReader(io.BytesIO(data))
    boxes: List[Box] = []
    pages, sizes, number = [], [], 0

    def visit(text, cm, tm, font, size):
        if text.strip():
            scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
            boxes.append(Box(tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], round(size * scale, 1), text.strip(), number))
    for number, page in enumerate(reader.pages[:MAX_PAGES_READ]):
        pages.append(page.extract_text(visitor_text=visit) or "")
        sizes.append((float(page.mediabox.width), float(page.mediabox.height)))
    return boxes, "\n".join(pages), sizes


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def has_columns(boxes: Sequence[Box], width: float) -> bool:
    """Whether the page has two columns of running text side by side. Dates pushed to the right edge are not a column: they end at one edge and are short;
    a column is a stack of lines that all start at one left edge, well to the right of where the others start."""
    if not boxes:
        return False
    right_edge = max(b.x + len(b.text) * b.size * 0.5 for b in boxes)
    body = [b for b in boxes if not (len(b.text) < 24 and abs(b.x + len(b.text) * b.size * 0.5 - right_edge) < 10) and len(b.text) >= 6]
    if not body:
        return False
    left = min(b.x for b in body)
    stacks: Dict[Tuple[int, int], List[Box]] = {}
    for b in body:
        if b.x - left >= width * 0.18:
            stacks.setdefault((b.page, round(b.x / 4)), []).append(b)
    for stack in stacks.values():
        rows = {round(b.y / 3) for b in stack}
        beside = [b for b in body if b.x - left < 6 and round(b.y / 3) in rows]  # lines at the left edge on the very same rows
        if len(stack) >= 4 and len(beside) >= 3 and statistics.mean(len(b.text) for b in stack) >= 12:
            return True
    return False


# -- the checks ------------------------------------------------------------------------------------------------------------------------------
def _fields(doc: Optional[Mapping]) -> List[Tuple[str, str]]:
    """(what it is, what you wrote) for what a parser must recover: your name and details, each job's title and company, each school."""
    if not doc:
        return []
    basics = doc["basics"]
    found = [("your name", basics["name"]), ("your email", basics["email"]), ("your location", basics["location"])]
    found += [("a job title", job["title"]) for job in doc["experience"]] + [("an employer", job["company"]) for job in doc["experience"]]
    found += [("a school", entry["school"]) for entry in doc["education"]]
    return [(what, value) for what, value in found if value.strip()]


def round_trip(text: str, doc: Optional[Mapping]) -> List[Dict[str, str]]:
    """For each field you wrote: does it come out of the PDF whole ("found"), in pieces ("garbled"), or not at all ("missing")?"""
    haystack, results = _norm(text), []
    squashed = haystack.replace(" ", "")
    for what, value in _fields(doc):
        wanted = _norm(value)
        tokens = wanted.split()
        if wanted in haystack or wanted.replace(" ", "") in squashed:
            status = "found"
        elif tokens and sum(token in haystack for token in tokens) / len(tokens) >= 0.6:
            status = "garbled"
        else:
            status = "missing"
        results.append({"field": what, "value": value[:60], "status": status})
    return results


def _order_ok(text: str, doc: Optional[Mapping]) -> bool:
    """Do the jobs come out in the order they are on the page? (A sidebar or a table can swap them.)"""
    if not doc or len(doc["experience"]) < 2:
        return True
    haystack = _norm(text)
    spots = [haystack.find(_norm(job["title"])) for job in doc["experience"] if job["title"].strip()]
    spots = [spot for spot in spots if spot >= 0]
    return spots == sorted(spots)


def _headings(text: str) -> Dict[str, bool]:
    lines = [_norm(line) for line in text.splitlines()]
    return {key: any(line in names or any(line == f"{name} and {other}" for name in names for other in ("projects", "skills", "education")) for line in lines)
            for key, names in HEADINGS.items()}


def _date_styles(text: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for match in DATE_STYLES.finditer(text):
        if match.lastgroup:
            counts[match.lastgroup] = counts.get(match.lastgroup, 0) + 1
    return counts


def findings_for(data: bytes, boxes: Sequence[Box], text: str, sizes: Sequence[Tuple[float, float]], doc: Optional[Mapping], pages: int) -> List[str]:
    """The codes of every rule this file breaks, in the order they were found."""
    hit: List[str] = []
    visible = re.sub(r"\s", "", text)
    if len(data) > MAX_BYTES:
        hit.append("FILE_TOO_LARGE")
    if len(visible) < 20:
        hit.append("NO_TEXT_LAYER")
        return hit  # nothing else can be judged about text that is not there
    odd = sum(1 for ch in visible if ch == "\ufffd" or "\ue000" <= ch <= "\uf8ff" or ord(ch) < 32)
    if odd / len(visible) > 0.02:
        hit.append("GARBLED_TEXT")
    elif "\ufffd" in text:
        hit.append("REPLACEMENT_CHARACTERS")
    if any(ch in text for ch in LIGATURES):
        hit.append("LIGATURE_CHARACTERS")
    if any(len(word) > 28 and not re.search(r"[@/:.]", word) for word in text.split()):
        hit.append("LOST_WORD_SPACING")
    if any(item["status"] != "found" for item in round_trip(text, doc)):
        hit.append("FIELDS_LOST")
    width = sizes[0][0] if sizes else 595.0
    if has_columns(boxes, width):
        hit.append("MULTI_COLUMN_LAYOUT")
    if not _order_ok(text, doc):
        hit.append("READING_ORDER")
    body = [b.size for b in boxes if len(b.text) >= 12]
    if body and statistics.median(body) < SIZE_FLOOR:
        hit.append("SMALL_BODY_TEXT")
    if boxes and min(b.x for b in boxes) < MARGIN_FLOOR:
        hit.append("NARROW_PAGE_MARGINS")
    if any(b.x < -1 or b.y < -1 or b.x > sizes[min(b.page, len(sizes) - 1)][0] or b.y > sizes[min(b.page, len(sizes) - 1)][1] for b in boxes):
        hit.append("TEXT_OUTSIDE_PAGE")
    if pages > 2:
        hit.append("HIGH_PAGE_COUNT")
    emails = EMAIL.findall(text)
    if not emails:
        hit.append("NO_EMAIL")
    if not any(len(re.sub(r"\D", "", run)) >= 7 for run in re.findall(r"\+?\d[\d\s().-]{6,}\d", text)):
        hit.append("NO_PHONE")
    first = [line.strip() for line in text.splitlines() if line.strip()][:4]
    name = _norm(doc["basics"]["name"]) if doc and doc["basics"]["name"] else ""
    if (name and not any(name in _norm(line) for line in first)) or (not name and not any(re.fullmatch(r"[A-Za-z.'-]+(?: [A-Za-z.'-]+){1,3}", line) for line in first)):
        hit.append("NO_NAME_LINE")
    found = _headings(text)
    if not found["experience"]:
        hit.append("NO_EXPERIENCE_SECTION")
    if not any(found.values()):
        hit.append("NO_RECOGNIZED_HEADINGS")
    if not found["education"]:
        hit.append("NO_EDUCATION_SECTION")
    if not found["skills"]:
        hit.append("NO_SKILLS_SECTION")
    if len(text.split()) < 120:
        hit.append("VERY_SHORT_DOCUMENT")
    styles = _date_styles(text)
    total = sum(styles.values())
    if total == 0:
        hit.append("NO_DATES_FOUND")
    elif total == 1:
        hit.append("FEW_DATES")
    if len([count for count in styles.values() if count]) > 1 and total >= 2:
        hit.append("MIXED_DATE_FORMATS")
    return hit


# -- the score -------------------------------------------------------------------------------------------------------------------------------
def score(codes: Sequence[str]) -> Dict[str, Any]:
    """Overall 0 to 100 (whole numbers: a parse check has no business saying 82.4), the score of each category, and what put a ceiling on it."""
    scored = {code for code in codes if RULES[code][0] != "tip"}
    categories = {}
    for category in WEIGHTS:
        cost = sum(BLOCKER_COST if RULES[code][0] == "blocker" else RULES[code][2] for code in scored if RULES[code][1] == category)
        categories[category] = max(0, 100 - cost)
    overall = sum(categories[category] * weight for category, weight in WEIGHTS.items()) / 100
    ceilings = [(RULES[code][2], code) for code in scored if RULES[code][0] == "blocker"]
    capped = [code for cap, code in ceilings if cap < overall]
    if ceilings:
        overall = min(overall, min(cap for cap, _ in ceilings))
    return {"score": round(overall), "categories": [{"id": key, "label": LABELS[key], "score": value} for key, value in categories.items()], "capped_by": capped}


def verdict(points: int, findings: int) -> Tuple[str, str]:
    if points >= 80 and findings == 0:
        return "clean", "Reads cleanly"
    if points >= 50:
        return "mostly", "Mostly readable"
    return "hard", "Hard for software to read"


def _report(codes: Sequence[str], text: str, doc: Optional[Mapping], pages: int, messages: Mapping[str, Tuple[str, str]] = MESSAGES) -> Dict[str, Any]:
    result = score(codes)
    findings = [Finding(code, RULES[code][0], RULES[code][1], *messages.get(code, MESSAGES[code]), POINTERS.get(code, "") if doc else "") for code in codes]
    key, label = verdict(result["score"], len([f for f in findings if f.severity != "tip"]))
    return {**result, "verdict": key, "label": label, "findings": [f.as_dict() for f in findings if f.severity != "tip"], "tips": [f.as_dict() for f in findings if f.severity == "tip"],
            "text": text[:MAX_TEXT], "fields": round_trip(text, doc), "pages": pages}


def analyze(data: bytes, doc: Optional[Mapping] = None) -> Dict[str, Any]:
    """The report on one exported PDF: a score, a score per category, every finding with its fix, the text a parser gets, and what survived of what you wrote."""
    if len(data) > MAX_BYTES * 4:
        raise ValueError("That file is too big to check.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            codes, boxes, text, sizes, pages = ["ENCRYPTED_PDF"], [], "", [], 0
        else:
            pages = len(reader.pages)
            boxes, text, sizes = _read(data)
            codes = findings_for(data, boxes, text, sizes, doc, pages)
    except ValueError:
        raise
    except Exception as exc:  # pypdf raises many different errors on a damaged file
        raise ValueError(f"That PDF could not be read ({str(exc)[:80]}).") from None
    return _report(codes, text, doc, pages)


NO_TEXT_IN_WORD = ("No text could be read from this Word file.", "The text may be in text boxes or pictures. Put it in ordinary paragraphs.")


def analyze_text(text: str, found_inside: Sequence[str] = (), size: int = 0) -> Dict[str, Any]:
    """The same report for a document that has no pages to look at (a Word file): only the rules that read text apply, plus `found_inside`, the codes of the rules
    the caller found by looking inside the file (a text box, a table, a header). The layout and the order cannot be seen from a Word file, and are not guessed."""
    codes = findings_for(b"", [], text, [], None, 0) + [code for code in found_inside if code not in ("NO_TEXT_LAYER",)]
    if size > MAX_BYTES and "FILE_TOO_LARGE" not in codes:
        codes.insert(0, "FILE_TOO_LARGE")
    return _report(codes, text, None, 0, {"NO_TEXT_LAYER": NO_TEXT_IN_WORD})
