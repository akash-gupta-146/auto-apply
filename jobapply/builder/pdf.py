"""Make a PDF from the very page the preview shows: Chrome (the one this program already uses) prints it, so the preview and the file cannot differ.

The PDF has real, selectable text, so an applicant tracking system can read it. Chrome is started for this one job with JavaScript off and no
network at all: a resume is only ever printed, never run. One PDF is made at a time (each starts a browser): a second request is told to wait.
"""
from __future__ import annotations

import io
import threading
import unicodedata
from typing import NamedTuple, Optional

from pypdf import PdfReader

from ..browser import find_browser

NO_BROWSER = "Chrome is needed to make the PDF, and none was found. Install Chrome (the Install Chrome button on the Apply tab), then try again."
_ONE_AT_A_TIME = threading.Lock()


class PdfError(RuntimeError):
    """The PDF could not be made. The message is written for the person."""


class Exported(NamedTuple):
    data: bytes
    pages: int


def filename(name: str) -> str:
    """`{FullName}_Resume.pdf`, with nothing in it a file system or a download header could object to."""
    kept = "".join(char if _fit_for_a_name(char) else "_" for char in name)  # not \\w: that drops the vowel signs of Hindi, Tamil and others
    cleaned = "_".join(part for part in (piece.strip(".") for piece in kept.split("_")) if part)  # "..", "." and empty pieces are nothing
    return f"{cleaned[:60] or 'My'}_Resume.pdf"


def _fit_for_a_name(char: str) -> bool:
    """A letter or digit in any script, the marks that belong to letters (a vowel sign is a mark), and a dot or hyphen."""
    return char.isalnum() or unicodedata.category(char).startswith("M") or char in ".-"


def make_pdf(page_html: str, page_size: str = "A4", browser: Optional[str] = None) -> Exported:
    """The page (from render.document) as a PDF, and how many pages it came to."""
    executable = browser or find_browser()
    if not executable:
        raise PdfError(NO_BROWSER)
    if not _ONE_AT_A_TIME.acquire(blocking=False):
        raise PdfError("A PDF is already being made. Wait a moment, then try again.")
    try:
        data = _print(page_html, page_size, executable)
    finally:
        _ONE_AT_A_TIME.release()
    try:
        return Exported(data, len(PdfReader(io.BytesIO(data)).pages))
    except Exception as exc:  # a file Chrome made that cannot be read back is not one to hand over
        raise PdfError("The PDF came out damaged. Try again.") from exc


def _print(page_html: str, page_size: str, executable: str) -> bytes:
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            chrome = playwright.chromium.launch(executable_path=executable, headless=True)
            try:
                context = chrome.new_context(java_script_enabled=False)  # a page to print, not a program to run
                context.route("**/*", lambda route: route.abort())  # and nothing is fetched from anywhere
                page = context.new_page()
                page.set_content(page_html, wait_until="load")
                return page.pdf(format=page_size, print_background=True, prefer_css_page_size=True)
            finally:
                chrome.close()
    except Error as exc:
        raise PdfError(f"Chrome could not make the PDF: {str(exc).splitlines()[0][:200]}") from exc
