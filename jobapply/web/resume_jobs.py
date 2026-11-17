"""Where the Create Resume tab gets a job from: pasted text, a web address, or the job page open in the browser the engine uses (signed in as you).

The first two are in builder/job_source.py. This is the third, and the glue: one `read` for all of them. Reading a page in your own browser is done only when
you press the button, for the one tab (or the one address) you named, and it changes nothing on the page. What it brings back goes into the job box for
you to read and trim, like everything else here.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from ..agent.tabs import about_a_job
from ..browser import DEFAULT_CDP, DOWN, WINDOWLESS, active_page, cdp_state, explain_no_window
from ..builder import job_source as source
from ..config import ConfigError
from .actions import ActionError

# What holds a job's description on the sites this program applies on, then the usual places: the first that has a real amount of text wins.
DESCRIPTION_SELECTORS = ("#jobDescriptionText", ".jobs-description__content", ".show-more-less-html__markup", "[class*='job-desc' i]", "[class*='JDC' i]",
                         "[class*='description' i]", "main", "article", "body")
SELECTOR_WAIT_MS = 1500


def read_in_browser(url: str = "", cdp: str = DEFAULT_CDP, state: Callable[[str], str] = cdp_state, active: Callable = active_page) -> source.JobText:
    """The job on a page in the engine's browser: the tab you have open about a job (or the address you gave, opened for you). Its job data if it has
    any, else the text of the part of the page that holds the description."""
    browser = state(cdp)
    if browser == DOWN:
        raise source.JobSourceError("The browser the engine uses is not open. Open it from the Auto-apply tab (or run `jobapply browser`), sign in, "
                                    "open the job page, then try again.")
    if browser == WINDOWLESS:
        raise source.JobSourceError(explain_no_window(cdp))
    try:
        job = _read_tab(url, cdp, active)
    except (source.JobSourceError, ConfigError):
        raise
    except Exception:  # a page that is still loading or has moved on under us: said in words, with what to do
        raise source.JobSourceError("The page open in your browser could not be read just now (it may still be loading). Wait a moment and try again, or paste the text.") from None
    if job.note == source.STRUCTURED_NOTE:
        return job
    why = source.blocked_reason(200, job.text)
    if why:
        raise source.JobSourceError(f"{why} Open the job itself in that browser (signed in), then try again, or paste the text.")
    return job._replace(note="Read from the page open in your browser: check it is the whole description, and trim anything that is not.")


def _read_tab(url: str, cdp: str, active: Callable) -> source.JobText:
    """The job on the tab to work on: its job data if it has any, else the text of the part of the page that holds the description."""
    with active(cdp, url, about_a_job) as tab:
        job = source.from_html(tab.content(), tab.url, "browser")
        if job.note == source.STRUCTURED_NOTE:
            return job
        text = ""
        for selector in DESCRIPTION_SELECTORS:
            try:
                places = tab.locator(selector)
                if places.count() == 0:  # does not wait: only a place that is there is worth waiting for
                    continue
                text = source.tidy(places.first.inner_text(timeout=SELECTOR_WAIT_MS))
            except Exception:  # the page moved on while we read it: try the next place
                continue
            if len(text) >= source.MIN_USEFUL:
                break
        try:
            title = " ".join(tab.title().split())[:120]
        except Exception:
            title = job.title
        return job._replace(text=text or job.text, title=job.title or title, url=tab.url, source="browser")


class JobReader:
    """One door for all three: pasted text, an address, or the browser. What each needs is injected, so none of it needs a network in a test."""

    def __init__(self, fetch: Callable[[str], source.JobText] = source.fetch, browse: Callable[[str], source.JobText] = read_in_browser):
        self._fetch, self._browse = fetch, browse

    def read(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        how = body.get("how")
        address = body.get("url") if isinstance(body.get("url"), str) else ""
        if how == "paste":
            job = source.from_pasted(body.get("text"))
        elif how == "link":
            job = self._fetch(address)
        elif how == "browser":
            job = self._browse(address.strip())
        else:
            raise ActionError("Choose how to give the job: paste it, give its web address, or read the one open in your browser.")
        return job.as_dict()
