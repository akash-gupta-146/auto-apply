"""A small, safe reader for the Markdown that run reports are written in, so the panel can show a rendered preview.

It produces plain data, never HTML: a list of blocks, each made of text pieces. The page turns the pieces into
elements one at a time with textContent, so nothing a job site put in a title or a company name can become markup
or script. Only what `report.py` writes is understood: # headings, | tables |, - lists, paragraphs, **bold**,
`code` and http(s) links. Anything else is simply shown as the text it is.

    block:  {"type": "heading", "level": 1-3, "spans": [...]}   {"type": "paragraph", "spans": [...]}
            {"type": "list", "items": [spans, ...]}             {"type": "table", "head": [spans, ...], "rows": [[spans, ...], ...]}
    span:   ["text" | "bold" | "code" | "link", "the text, or the address of a link"]
"""
from __future__ import annotations

import re
from typing import Dict, List

Span = List[str]

INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|(https?://[^\s<>\"')\]]+)")
HEADING = re.compile(r"(#{1,3})\s+(.*\S)")
BULLET = re.compile(r"\s*[-*]\s+")
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
SENTENCE_END = ".,;:!?"  # a full stop after an address belongs to the sentence, not to the address


def spans(text: str) -> List[Span]:
    """The pieces of one line of text."""
    pieces: List[Span] = []
    last = 0
    for found in INLINE.finditer(text):
        if found.start() > last:
            pieces.append(["text", text[last:found.start()]])
        bold, code, address = found.groups()
        if bold is not None:
            pieces.append(["bold", bold])
        elif code is not None:
            pieces.append(["code", code])
        else:
            trimmed = address.rstrip(SENTENCE_END)
            pieces.append(["link", trimmed])
            if len(trimmed) < len(address):
                pieces.append(["text", address[len(trimmed):]])
        last = found.end()
    if last < len(text):
        pieces.append(["text", text[last:]])
    return pieces


def _cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _starts_block(line: str) -> bool:
    return bool(HEADING.match(line) or line.lstrip().startswith("|") or BULLET.match(line))


def _table(rows: List[List[str]]) -> Dict[str, object]:
    has_head = len(rows) > 1 and all(SEPARATOR_CELL.fullmatch(cell) for cell in rows[1])
    head, body = (rows[0], rows[2:]) if has_head else ([], rows)
    return {"type": "table", "head": [spans(c) for c in head], "rows": [[spans(c) for c in row] for row in body]}


def parse_markdown(text: str) -> List[Dict[str, object]]:
    lines = [line.rstrip() for line in text.splitlines()]  # one view of every line, so no loop below can stall on one
    blocks: List[Dict[str, object]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif HEADING.match(line):
            heading = HEADING.match(line)
            blocks.append({"type": "heading", "level": len(heading.group(1)), "spans": spans(heading.group(2))})
            i += 1
        elif line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append(_table(rows))
        elif BULLET.match(line):
            items = []
            while i < len(lines) and BULLET.match(lines[i]):
                items.append(spans(BULLET.sub("", lines[i], count=1).strip()))
                i += 1
            blocks.append({"type": "list", "items": items})
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                paragraph.append(lines[i].strip())
                i += 1
            blocks.append({"type": "paragraph", "spans": spans(" ".join(paragraph))})
    return blocks
