"""Attach to a real, logged-in browser over CDP (never launches a throwaway one).

Preferred browser: BrowserOS neo, then Chrome, then (Windows only) Microsoft Edge. JOBAPPLY_BROWSER_EXE overrides all three.

Verified on macOS (neo 151): neo launched by `jobapply browser` with a dedicated
--user-data-dir and --remote-debugging-port gives full CDP, and Playwright attaches fine.
Do NOT point --cdp at neo's own managed port (9110): it is a restricted CDP that rejects
Playwright's first call ("Browser context management is not supported").
Chromium 136+ also ignores the debug port on the default profile, hence the dedicated one:
log in to each portal once in that profile; sessions persist.
"""
from __future__ import annotations

import contextlib
import glob
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterator, List, Optional
from urllib.parse import quote, urlparse

import httpx

from .config import ConfigError

DEFAULT_CDP = "http://127.0.0.1:9222"
AGENT_URL_ENV = "JOBAPPLY_AGENT_URL"  # how the control panel hands the agent a job page address: never on the command line
READY, WINDOWLESS, DOWN = "ready", "windowless", "down"  # what cdp_state() can say about a browser
WINDOWS_BASES = ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")
NOT_BROWSER_EXES = ("unins", "update", "crash", "setup", "install", "elevation", "notification")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")  # a job is never on this computer: such a tab is this program's own control panel
MAX_ADDRESS_CHARS = 2048
MAX_TABS_LOOKED_AT = 6  # tabs read to find the one that is about a job; more than this is not someone applying for a job
TAB_APPEARS_S, LOAD_MS = 15, 20_000


def _first_existing(candidates: List[str]) -> Optional[str]:
    return next((c for c in candidates if Path(c).exists()), None)


def find_neo() -> Optional[str]:
    """BrowserOS neo. macOS path is verified; the Windows search is a best guess (see --exe)."""
    if sys.platform == "darwin":
        return _first_existing(["/Applications/BrowserOS neo.app/Contents/MacOS/BrowserOS neo"])
    if sys.platform == "win32":
        found: List[str] = []
        for var in WINDOWS_BASES:
            base = os.environ.get(var)
            if base:
                for pattern in ("BrowserOS*/*.exe", "BrowserOS*/Application/*.exe"):
                    found += glob.glob(str(Path(base) / pattern))
        exes = [p for p in found if not any(bad in Path(p).name.lower() for bad in NOT_BROWSER_EXES)]
        exes.sort(key=lambda p: ("neo" not in Path(p).name.lower(), p))  # names containing "neo" first
        return exes[0] if exes else None
    return None


def find_chrome() -> Optional[str]:
    candidates: List[str] = []
    if sys.platform == "win32":
        for var in WINDOWS_BASES:
            base = os.environ.get(var)
            if base:
                candidates.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        candidates += [p for p in (_which(n) for n in ("google-chrome", "chrome", "chromium")) if p]
    return _first_existing(candidates)


def find_edge() -> Optional[str]:
    """Microsoft Edge is on every Windows 10 and 11 PC and is built on Chromium, so it takes the same debugging flags.
    The last resort, so that a PC with neither BrowserOS neo nor Chrome still works. Windows only."""
    if sys.platform != "win32":
        return None
    candidates = [str(Path(base) / "Microsoft/Edge/Application/msedge.exe")
                  for base in (os.environ.get(var) for var in WINDOWS_BASES) if base]
    return _first_existing(candidates)


def _which(name: str) -> Optional[str]:
    import shutil

    return shutil.which(name)


def find_browser() -> Optional[str]:
    """JOBAPPLY_BROWSER_EXE, else BrowserOS neo, else Chrome, else (Windows) Edge."""
    return os.environ.get("JOBAPPLY_BROWSER_EXE") or find_neo() or find_chrome() or find_edge()


def launch_browser(exe: str, profile_dir: Path, port: int = 9222) -> subprocess.Popen:
    """Start the browser fully detached: closing the window that started it (or a pipe on its output)
    must neither kill it nor make the caller wait for it."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    detach: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        detach["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        detach["start_new_session"] = True
    return subprocess.Popen(
        [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        **detach,
    )


def cdp_alive(cdp_url: str = DEFAULT_CDP) -> bool:
    try:
        return httpx.get(f"{cdp_url}/json/version", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def cdp_state(cdp_url: str = DEFAULT_CDP) -> str:
    """Whether the browser on this debug port can actually be driven.

    READY: it has a tab to work in. DOWN: nothing answers. WINDOWLESS: it answers but has no window. On a Mac, closing a
    browser's last window leaves the app (and its debug port) running, and Playwright cannot attach to it: so "the port
    answers" is not the same as "the browser is open".
    """
    if not cdp_alive(cdp_url):
        return DOWN
    try:
        tabs = httpx.get(f"{cdp_url}/json/list", timeout=3).json()
    except (httpx.HTTPError, ValueError):
        return DOWN
    if not isinstance(tabs, list):
        return DOWN
    return READY if any(isinstance(tab, dict) and tab.get("type") == "page" for tab in tabs) else WINDOWLESS


def explain_no_window(cdp_url: str) -> str:
    return (f"The browser on {cdp_url} is running but has no window open (its last window was closed, and on a Mac the app "
            "keeps running). Run `jobapply browser` to open a window, then try again.")


def _connect(pw, cdp_url: str):
    """The running browser's first window context, or a clear message about why it cannot be driven."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
    except PlaywrightError as exc:
        if "context management is not supported" in str(exc):
            if cdp_state(cdp_url) == WINDOWLESS:  # the common cause: a closed window, not a restricted port
                raise ConfigError(explain_no_window(cdp_url)) from exc
            raise ConfigError(
                f"{cdp_url} is a restricted debug port (BrowserOS's managed one). "
                "Use the engine's own browser instead: run `jobapply browser` and keep the default --cdp."
            ) from exc
        raise
    return browser.contexts[0] if browser.contexts else browser.new_context()


@contextlib.contextmanager
def open_page(cdp_url: str = DEFAULT_CDP) -> Iterator:
    """Yield our own tab in the running browser; leave the browser itself open."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        page = _connect(pw, cdp_url).new_page()
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                page.close()


BLANK_TABS = ("about:blank", "chrome://", "chrome-search://", "edge://", "browseros://")  # a new-tab page is not what the person is working on


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def _is_visible(tab) -> bool:
    try:
        return bool(tab.evaluate("document.visibilityState === 'visible'"))
    except Exception:  # a tab in the middle of loading: simply not the one we can use yet
        return False


def foreground_tab(pages: List, about_a_job: Optional[Callable[[object], bool]] = None) -> Optional[object]:
    """The tab to work on. A browser calls a tab visible only while its window is in front, and the person pressing Start in a control
    panel has just put another window in front: so "visible" is a hint, not an answer. A tab that is about a job beats one that is
    only in front; then the one in front; then the newest. A blank new-tab page and this program's own control panel are never chosen."""
    open_tabs = [p for p in pages if not p.is_closed()]
    real = [p for p in open_tabs if not p.url.startswith(BLANK_TABS) and not _is_local(p.url)]
    in_front = [p for p in real if _is_visible(p)]
    if about_a_job is not None:
        for tab in (in_front + [p for p in reversed(real) if p not in in_front])[:MAX_TABS_LOOKED_AT]:
            if about_a_job(tab):
                return tab
    return (in_front or real or open_tabs or [None])[0 if in_front else -1]


def check_address(url: str) -> str:
    """The address of a job page you were given, or a plain complaint. Web pages only: never a file, a script or a browser page."""
    url = (url or "").strip()
    parts = urlparse(url)
    if (not url or len(url) > MAX_ADDRESS_CHARS or any(c.isspace() or ord(c) < 32 for c in url)
            or parts.scheme not in ("http", "https") or not parts.hostname):
        raise ConfigError("That is not a web address. Paste the job page's full address, starting with https://")
    if parts.hostname in LOCAL_HOSTS:
        raise ConfigError("That address is on this computer, not on a job site. Paste the job page's address.")
    return url


def _same_page(a: str, b: str) -> bool:
    return a.split("#")[0].rstrip("/") == b.split("#")[0].rstrip("/")


def open_address(cdp_url: str, url: str) -> None:
    """Have the job page open in the browser: use the tab that already has it, or open one. Chrome's own debug address can open a tab
    (and so a window) in a browser that has none, which Playwright cannot: so this works however the browser was left."""
    try:
        tabs = httpx.get(f"{cdp_url}/json/list", timeout=3).json()
        if any(isinstance(t, dict) and t.get("type") == "page" and _same_page(str(t.get("url", "")), url) for t in tabs):
            return
        # "&", "#" and "%" must all be encoded: Chrome cuts a bare address at the first "&" or "#", and unescapes it once, so a bare "%26"
        # inside a value would arrive as "&" and open a different page
        opened = httpx.put(f"{cdp_url}/json/new?{quote(url, safe=':/?=@+,;~!$()*')}", timeout=10)
        opened.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise ConfigError(f"The browser would not open {urlparse(url).hostname}: {exc}") from exc
    deadline = time.monotonic() + TAB_APPEARS_S
    while cdp_state(cdp_url) != READY:  # a window takes a moment to appear
        if time.monotonic() > deadline:
            raise ConfigError("The browser did not open a window for that page. Run `jobapply browser`, then try again.")
        time.sleep(0.3)


@contextlib.contextmanager
def active_page(cdp_url: str = DEFAULT_CDP, url: str = "", about_a_job: Optional[Callable[[object], bool]] = None) -> Iterator:
    """Yield the tab to work on, and leave it open afterwards: it is theirs. With a job page address, that page (opened if need be);
    without, the tab they have open: one that is about a job, else the one in front."""
    from playwright.sync_api import sync_playwright

    if url:
        open_address(cdp_url, check_address(url))
    with sync_playwright() as pw:
        pages = _connect(pw, cdp_url).pages
        tab = _tab_at(pages, url) if url else foreground_tab(pages, about_a_job)
        if tab is None:
            raise ConfigError("The browser has no tab open. Open the job page you want to apply for, then run this again.")
        yield tab


def _tab_at(pages: List, url: str):
    """The tab showing this address; else the newest real one (the page may already have moved on, to a sign-in or a redirect)."""
    real = [p for p in pages if not p.is_closed() and not p.url.startswith(BLANK_TABS) and not _is_local(p.url)]
    tab = next((p for p in reversed(real) if _same_page(p.url, url)), None) or (real[-1] if real else None)
    if tab is not None:
        with contextlib.suppress(Exception):
            tab.bring_to_front()
            tab.wait_for_load_state("domcontentloaded", timeout=LOAD_MS)
    return tab
