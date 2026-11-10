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
from pathlib import Path
from typing import Iterator, List, Optional

import httpx

from .config import ConfigError

DEFAULT_CDP = "http://127.0.0.1:9222"
READY, WINDOWLESS, DOWN = "ready", "windowless", "down"  # what cdp_state() can say about a browser
WINDOWS_BASES = ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")
NOT_BROWSER_EXES = ("unins", "update", "crash", "setup", "install", "elevation", "notification")


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


@contextlib.contextmanager
def open_page(cdp_url: str = DEFAULT_CDP) -> Iterator:
    """Yield our own tab in the running browser; leave the browser itself open."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
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
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                page.close()
