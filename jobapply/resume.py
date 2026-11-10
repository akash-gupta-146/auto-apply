"""Read a resume and fold it into the profile."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree

from .config import ConfigError, Profile
from .resume_details import extract_details
from .skills_vocab import detect_skills

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path: Path) -> str:
    """Plain text of a .docx (paragraphs and table cells), standard library only."""
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ConfigError(f"{path.name} is not a readable .docx ({exc}). Re-save it as .docx or PDF.") from exc
    lines = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{WORD_NS}t"))
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _tidy(text: str) -> str:
    """Layout mode pads lines with runs of spaces to keep columns apart: keep a clear gap, drop the padding."""
    lines = [re.sub(r"[ \t]{3,}", "   ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _solid(text: str) -> int:
    return len(re.sub(r"\s", "", text))  # the characters that are not spacing


def _read_pdf(path: Path) -> str:
    """Text of a PDF with its LINES kept whole.

    The default reading of many PDFs (those made by design tools and browsers) comes out one word per line:
    a name is cut to its first word and a phone number is split across lines, so nothing can be recognised in it.
    Layout mode reads the page the way it looks. If it ever returns clearly less text, the default reading is used.
    """
    from pypdf import PdfReader

    pages = PdfReader(str(path)).pages
    plain = "\n".join(page.extract_text() or "" for page in pages)
    try:
        layout = _tidy("\n".join(page.extract_text(extraction_mode="layout") or "" for page in pages))
    except Exception:  # a PDF layout mode cannot read is still readable the plain way
        return plain
    return layout if _solid(layout) >= 0.8 * _solid(plain) else plain


def read_text(path: Path) -> str:
    if not path.exists():
        raise ConfigError(f"Resume not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ConfigError(f"Unsupported resume type {path.suffix!r}: use PDF, DOCX or TXT")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def normalize_phone(raw: str) -> str:
    """Indian mobile numbers: keep the last 10 digits (drops +91, spaces and dashes)."""
    return re.sub(r"\D", "", raw)[-10:]


def guess_facts(text: str) -> Dict[str, object]:
    """Cheap regex guesses, shown on the details form for the person to check. Details a resume only implies are not
    guessed (see resume_details.py): the key is simply absent."""
    flat = re.sub(r"[ \t]+", " ", text)  # reading by layout can leave several spaces inside a number or a name
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", flat)
    # 10 digits, optionally grouped with spaces/dashes ("+91 9876 543 210"); keep the last 10 digits.
    phone = re.search(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9}\d(?!\d)", flat)
    phone_digits = normalize_phone(phone.group(0)) if phone else ""
    years = [float(y) for y in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)", flat, re.I)]
    first_line = next((" ".join(line.split()) for line in text.splitlines() if line.strip()), "")
    return {
        **extract_details(text),
        "name": first_line if len(first_line) < 50 else "",
        "email": email.group(0) if email else "",
        "phone": phone_digits,
        "years": max((y for y in years if y <= 40), default=0.0),
        "skills": sorted(detect_skills(text)),
    }


def sync_profile(profile: Profile, path: Path) -> List[str]:
    """Point the profile at this resume; add skills it mentions. Never removes any.

    New skills get NO years (None): a resume lists skills but not how long you used each, and
    inventing a number would be sent to employers. Questions about an unset skill's years are
    parked for you instead of answered.
    """
    resume_hash = file_hash(path)
    added: List[str] = []
    if resume_hash != profile.resume_hash:
        for skill in detect_skills(read_text(path)):
            if skill not in profile.skills:
                profile.skills[skill] = None
                added.append(skill)
    profile.resume_path = str(path)
    profile.resume_hash = resume_hash
    return sorted(added)
