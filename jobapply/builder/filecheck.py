"""Check any resume file, not only one made here: a PDF, or a Word (.docx) file. Which of the two is told from the file's first bytes, never from its name.

A PDF is read by builder/pdfcheck.py, exactly as a PDF made here is. A Word file has no pages to look at, so only the rules that read text apply, plus four that
need a look inside the file (text boxes, tables, text in the header or footer, pictures). What a Word file would look like when printed is not guessed.

Nothing is run and nothing is opened with another program: the file is only read, with size limits, and a .docx that declares an XML entity is refused (a real one
never does; a hostile one could use it to use up memory). No HTTP and no HTML in here.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Dict, List, Tuple
from xml.etree import ElementTree

from . import pdfcheck

WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_UNZIPPED = 20_000_000  # bytes, all the parts of a .docx together
HEADER_FOOTER_PART = re.compile(r"word/(?:header|footer)\d*\.xml")
NOT_A_RESUME_FILE = "That is not a PDF or a Word (.docx) file. Other kinds (an old .doc, an image) cannot be checked: save it as a PDF or a .docx."


def kind_of(data: bytes) -> str:
    """"pdf", "docx", or "" for anything else."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            return "docx" if "word/document.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist() else ""
        except zipfile.BadZipFile:
            return ""
    return ""


def _xml(raw: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("That Word file has something in it that a real one does not, so it was not opened.")
    return ElementTree.fromstring(raw)


def _letters(root: ElementTree.Element) -> int:
    return sum(len(re.findall(r"[A-Za-z]", node.text or "")) for node in root.iter(f"{WORD}t"))


def _docx(data: bytes) -> Tuple[str, List[str]]:
    """(the text a plain reader gets: the body, without text boxes; the codes of what is wrong inside the file)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
            if sum(part.file_size for part in parts) > MAX_UNZIPPED:
                raise ValueError("That Word file is too big to check.")
            root = _xml(archive.read("word/document.xml"))
            sides = [_xml(archive.read(part.filename)) for part in parts if HEADER_FOOTER_PART.fullmatch(part.filename)]
            pictures = any(part.filename.startswith("word/media/") for part in parts)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise ValueError("That Word file could not be read. Re-save it as a .docx or a PDF.") from None
    parents = {child: parent for parent in root.iter() for child in parent}
    boxes = list(root.iter(f"{WORD}txbxContent"))
    for box in boxes:  # many systems skip them, so what is inside is not part of the text a plain reader gets
        parents[box].remove(box)
    tables = list(root.iter(f"{WORD}tbl"))
    lines = ["".join(node.text or "" for node in paragraph.iter(f"{WORD}t")).strip() for paragraph in root.iter(f"{WORD}p")]
    found = [code for code, present in (("DOCX_TEXT_BOX", boxes), ("DOCX_TABLES", tables), ("DOCX_HEADER_FOOTER", any(_letters(side) >= 10 for side in sides)),
                                        ("DOCX_IMAGES", pictures)) if present]  # a page number alone is under 10 letters: it is not "text in the header"
    return "\n".join(line for line in lines if line), found


def analyze(data: bytes) -> Dict[str, Any]:
    """The report on a PDF or a Word file, in one shape (see pdfcheck.analyze), with `kind` saying which it was."""
    if len(data) > pdfcheck.MAX_BYTES * 4:
        raise ValueError("That file is too big to check.")
    kind = kind_of(data)
    if kind == "pdf":
        report = pdfcheck.analyze(data)
    elif kind == "docx":
        text, found = _docx(data)
        report = pdfcheck.analyze_text(text, found, len(data))
    else:
        raise ValueError(NOT_A_RESUME_FILE)
    return {**report, "kind": kind}
