"""Get a job description from where the person has it: pasted, from a link, or from the job page open in their own browser.

A link is fetched like a browser would, once, for the one page the person gave, and read the way Google reads a job page: most job sites publish a
schema.org `JobPosting` block (JSON-LD) with the title, company, place and the description, so that is read first; the page's visible text is the
fallback. What comes back is *shown to the person in the job box*, where they can read and trim it: nothing here decides what the job says.

What a fetch refuses, and says so in words: a page that is not on the public internet (this computer, your network: an address that resolves to a
private, loopback or link-local place, checked again at every redirect), a page that is not text, one that is too big or too slow, and one that is a
sign-in wall, a CAPTCHA or "access denied" instead of a job (a program is not meant to get past those: paste the text, or read it with your own
browser). The page's text is data, never instructions: it is cut to a fixed length here and fenced again wherever an AI is shown it.

No HTML is made in here, and nothing is stored.
"""
from __future__ import annotations

import html as htmllib
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence
from urllib.parse import urljoin, urlparse

import httpx

MAX_TEXT = 20_000  # characters kept: the same as the pasted limit (the job box)
MAX_BYTES = 1_500_000  # of a page read
TIMEOUT_S = 10.0
MAX_HOPS = 4  # redirects followed, each one checked
MAX_ADDRESS = 2048
MIN_USEFUL = 200  # characters: less than this is a stub (a loading page, a teaser), not a job description
STRUCTURED_NOTE = "Read from the job data the page publishes."
USER_AGENT = "Mozilla/5.0 (compatible; jobapply-resume-tab; one page, on request)"
SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "iframe", "button", "select", "option"})
BLOCKS = frozenset({"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "main", "table", "dt", "dd", "header"})
HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
HEADING_GAP = "\x00"  # stands for "a blank line goes here" until the plain line breaks have been collapsed
BLOCKED_STATUS = {401: "needs you to sign in", 403: "would not show the page to a program", 429: "is limiting requests"}
WALLS = ("access denied", "captcha", "verify you are human", "verify you're human", "just a moment", "unusual traffic", "are you a robot", "sign in to view",
         "log in to view", "sign in to see", "join now to see", "enable javascript and cookies", "request blocked", "pardon our interruption")
EXTRA_FIELDS = (("responsibilities", "Responsibilities"), ("skills", "Skills"), ("qualifications", "Qualifications"),
                ("experienceRequirements", "Experience"), ("educationRequirements", "Education"))  # JobPosting fields Google lets a site fill in


class JobSourceError(ValueError):
    """A job could not be read. The message says why, in words for the person."""


class JobText(NamedTuple):
    text: str
    title: str = ""
    company: str = ""
    location: str = ""
    source: str = "pasted"  # pasted | structured | page | browser
    url: str = ""
    note: str = ""  # what the person should know about how this was read

    def as_dict(self) -> Dict[str, Any]:
        return self._asdict()


class Fetched(NamedTuple):
    status: int
    url: str
    content_type: str
    body: bytes
    location: str = ""  # the redirect target, when there is one


# -- text ----------------------------------------------------------------------------------------------------------------------------------
def tidy(text: str, limit: int = MAX_TEXT) -> str:
    """Plain text with one blank line at most and trailing spaces gone."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: List[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()[:limit]


class _Text(HTMLParser):
    """The words a reader sees: scripts, styles, menus and forms left out; a break where a block ends; a dash before a list item."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self.h1 = ""
        self._in_h1 = False
        self.meta: Dict[str, str] = {}
        self.scripts: List[str] = []
        self._ld = False

    def handle_starttag(self, tag: str, attrs: Sequence) -> None:
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self._in_h1 = True
        if tag == "meta":
            fields = dict(attrs)
            key = fields.get("property") or fields.get("name")
            if key and fields.get("content"):
                self.meta.setdefault(key.lower(), str(fields["content"]))
        if tag == "script" and "ld+json" in str(dict(attrs).get("type", "")).lower():
            self._ld = True
            self.scripts.append("")
            return
        if tag in SKIPPED:
            self.skip += 1
            return
        if not self.skip:
            if tag in HEADINGS:
                self.parts.append(HEADING_GAP)
            if tag in BLOCKS:
                self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._in_h1 = False
        if tag == "script" and self._ld:
            self._ld = False
            return
        if tag in SKIPPED:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ld:
            self.scripts[-1] += data
            return
        if self._in_title:
            self.title += data
        if self._in_h1 and not self.skip:
            self.h1 += data
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        joined = re.sub(r"\n{2,}", "\n", "".join(self.parts))  # where one block ends and the next begins is one line break, not a blank line...
        return tidy(joined.replace(HEADING_GAP, "\n"))  # ...except before a heading, which gets a blank line so the sections stay visible


def _parse(markup: str) -> _Text:
    reader = _Text()
    try:
        reader.feed(markup)
        reader.close()
    except Exception:  # broken markup is the normal case on the web: read what there is
        pass
    return reader


def html_to_text(markup: str) -> str:
    return _parse(markup).text()


def _description(value: Any) -> str:
    """A JobPosting's description is usually HTML, sometimes HTML that has been escaped again: both come out as plain lines."""
    text = value if isinstance(value, str) else ""
    if "\n" not in text and "\\n" in text:  # some sites double-escape their JSON: the two characters \ and n where a line break was meant
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    if "&lt;" in text or "&amp;" in text:
        text = htmllib.unescape(text)
    return html_to_text(text) if "<" in text else tidy(text)


# -- structured data -----------------------------------------------------------------------------------------------------------------------
def _walk(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        kinds = node.get("@type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if "JobPosting" in kinds:
            yield node
        yield from _walk(node.get("@graph"))


def _name(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or ""
    return " ".join(value.split())[:120] if isinstance(value, str) else ""


def _place(value: Any) -> str:
    place = value[0] if isinstance(value, list) and value else value
    address = place.get("address") if isinstance(place, dict) else None
    if isinstance(address, dict):
        parts = [_name(address.get(key)) for key in ("addressLocality", "addressRegion", "addressCountry")]
        return ", ".join(part for part in parts if part and not re.search(r"not applicable|^n/?a$", part, re.I))
    return address[:120] if isinstance(address, str) else ""


def postings_in(scripts: Iterable[str]) -> List[Dict[str, Any]]:
    """Every JobPosting the page's JSON-LD blocks describe (a block that is not valid JSON is skipped, not fatal)."""
    found: List[Dict[str, Any]] = []
    for script in scripts:
        try:
            data = json.loads(script.strip())
        except ValueError:
            continue
        found += list(_walk(data))
    return found


def _posting_text(posting: Dict[str, Any]) -> str:
    text = _description(posting.get("description"))
    for key, label in EXTRA_FIELDS:
        extra = _description(posting.get(key)) if isinstance(posting.get(key), str) else ""
        if extra and extra[:60].lower() not in text.lower():
            text += f"\n\n{label}:\n{extra}"
    return tidy(text)


def from_html(markup: str, url: str = "", source: str = "page") -> JobText:
    """A job from a page's HTML: its JobPosting data if it has one (the longest, if several), else the page's own text."""
    reader = _parse(markup)
    postings = sorted(postings_in(reader.scripts), key=lambda p: len(str(p.get("description") or "")), reverse=True)
    if postings:
        posting = postings[0]
        text = _posting_text(posting)
        if len(text) >= MIN_USEFUL:
            return JobText(text, _name(posting.get("title")), _name(posting.get("hiringOrganization")), _place(posting.get("jobLocation")),
                           "structured" if source == "page" else source, url, STRUCTURED_NOTE)
    text = reader.text()
    title = " ".join((reader.meta.get("og:title") or reader.h1 or reader.title).split())[:120]
    return JobText(text, title, "", "", source, url, "Read from the page's own text: check it is the whole description, and trim anything that is not.")


# -- is it a job at all, or a wall ---------------------------------------------------------------------------------------------------------
def blocked_reason(status: int, text: str, structured: bool = False) -> str:
    """Why this is not a job description, in words, or "" if it looks like one."""
    if status in BLOCKED_STATUS:
        return f"The site {BLOCKED_STATUS[status]}."
    if status >= 400:
        return f"The site answered with an error ({status})."
    lowered = text.lower()
    if not structured and len(text) < 1500 and any(wall in lowered for wall in WALLS):
        return "The page is a sign-in or security check, not the job."
    if not structured and len(text) < MIN_USEFUL:
        return "The page had almost no text (it may need to load in a browser first)."
    return ""


# -- the public internet only --------------------------------------------------------------------------------------------------------------
Resolver = Callable[[str], List[str]]
Opener = Callable[[str], Fetched]


def resolve(host: str) -> List[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except (socket.gaierror, UnicodeError, OSError):
        return []


def public_address(url: str, lookup: Resolver = resolve) -> str:
    """The address, if it is a web page on the public internet; otherwise a plain refusal. Checked before every request and every redirect."""
    url = (url or "").strip()
    parts = urlparse(url)
    if not url or len(url) > MAX_ADDRESS or any(c.isspace() or ord(c) < 32 for c in url) or parts.scheme not in ("http", "https") or not parts.hostname:
        raise JobSourceError("That is not a web address. Paste the job page's full address, starting with https://")
    if parts.username or parts.password:
        raise JobSourceError("Leave the name and password out of the address.")
    addresses = [parts.hostname] if _is_ip(parts.hostname) else lookup(parts.hostname)
    if not addresses:
        raise JobSourceError(f"Could not find {parts.hostname} on the internet. Check the address.")
    for address in addresses:
        ip = _ip(address)
        if ip is None:
            raise JobSourceError("That address could not be checked, so it was not opened.")
        if not ip.is_global:
            raise JobSourceError("That address is on this computer or your own network, not on a job site.")
    return url


def _ip(host: str):
    try:
        return ipaddress.ip_address(host.split("%")[0])  # a zone id (fe80::1%en0) is not part of the address
    except ValueError:
        return None


def _is_ip(host: str) -> bool:
    return _ip(host) is not None


def http_get(url: str) -> Fetched:
    """One GET, no redirects followed (the caller checks each), at most MAX_BYTES read."""
    try:
        with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}) as client:
            with client.stream("GET", url) as response:
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        body = body[:MAX_BYTES]
                        break
                return Fetched(response.status_code, str(response.url), response.headers.get("content-type", ""), body, response.headers.get("location", ""))
    except httpx.TimeoutException:
        raise JobSourceError("The site took too long to answer. Try again, or paste the job text.") from None
    except httpx.HTTPError:
        raise JobSourceError("The page could not be reached. Check the address, or paste the job text.") from None


def _decode(fetched: Fetched) -> str:
    charset = re.search(r"charset=([\w-]+)", fetched.content_type, re.I)
    try:
        return fetched.body.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        return fetched.body.decode("utf-8", errors="replace")


def fetch(url: str, opener: Opener = http_get, lookup: Resolver = resolve) -> JobText:
    """The job at a public web address, or a JobSourceError that says what to do instead."""
    current = public_address(url, lookup)
    for _ in range(MAX_HOPS + 1):
        got = opener(current)
        if got.status in (301, 302, 303, 307, 308) and got.location:
            current = public_address(urljoin(current, got.location), lookup)  # every hop is checked: a redirect is how a public page points at a private one
            continue
        break
    else:
        raise JobSourceError("The address sent the browser round in circles. Paste the job text instead.")
    kind = got.content_type.split(";")[0].strip().lower()
    if got.status < 400 and kind and kind not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise JobSourceError("That address is not a web page (it is a file or a download). Paste the job text instead.")
    job = from_html(_decode(got), current) if kind != "text/plain" else JobText(tidy(_decode(got)), url=current, source="page")
    why = blocked_reason(got.status, job.text, job.source == "structured")
    if why:
        raise JobSourceError(f"{why} Paste the job text, or use \"Read the job open in my browser\" (it is signed in as you).")
    return job._replace(url=current)


def from_pasted(text: object) -> JobText:
    if not isinstance(text, str) or not text.strip():
        raise JobSourceError("Paste the job description, or give the job's web address.")
    return JobText(tidy(text), source="pasted")
