"""LinkedIn's own picks for you: its Easy Apply collection, the jobs it suggests that this program can actually send.

It is drawn with LinkedIn's older page markup (a list of `li[data-occludable-job-id]`), not the `componentkey` cards of a
search, so it has a reader of its own. The ordinary "Top job picks" feed is not used: its jobs mostly apply on the company's
own site, so almost every one would be opened only to be turned away.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ..models import JobCard

log = logging.getLogger("jobapply")

PICKS = "https://www.linkedin.com/jobs/collections/easy-apply/"
PAGE_SIZE = 25
MAX_PAGES = 10  # LinkedIn listed 249 picks (ten pages) when this was written
ITEM = "li[data-occludable-job-id]"
LIST_WAIT_MS = 20_000

# A card is only drawn while it is near the screen, and jumping to the end of the list leaves the middle empty (read live:
# 12 of 25). So walk the list one card at a time, read each where it is drawn, and give it up to two seconds to appear.
WALK_JS = """async () => {
  const out = [];
  for (const li of document.querySelectorAll('li[data-occludable-job-id]')) {
    li.scrollIntoView({block: 'center'});
    let title = '';
    for (let waited = 0; waited < 2000 && !title; waited += 100) {
      await new Promise(done => setTimeout(done, 100));
      const link = li.querySelector('a[href*="/jobs/view/"]');
      title = link ? (link.querySelector('strong') || link).innerText.trim().split('\\n')[0].trim() : '';
    }
    const text = selector => { const e = li.querySelector(selector); return e ? e.innerText.trim().split('\\n')[0].trim() : ''; };
    // a job you already applied to keeps its card, marked "Applied" (or "Applied 2 days ago"): never a title such as "Applied Scientist"
    const applied = [...li.querySelectorAll('span, p')].some(e => !e.children.length && /^applied(\\s+\\d.*)?$/i.test((e.innerText || '').trim()));
    out.push({id: li.getAttribute('data-occludable-job-id'), title, company: text('.artdeco-entity-lockup__subtitle'),
              location: text('.artdeco-entity-lockup__caption'), applied});
  }
  return out;
}"""


def discover_picks(adapter, query: str) -> Iterator[JobCard]:
    """The picks, page by page, as the same job addresses a search gives (so a job found both ways is one job)."""
    seen = set()
    for page_no in range(MAX_PAGES):
        adapter.goto(query if page_no == 0 else f"{query}?start={page_no * PAGE_SIZE}")
        try:
            adapter.active.wait_for_selector(ITEM, timeout=LIST_WAIT_MS)
        except Exception:
            return  # no cards: the end of the picks, or a broken page (the engine saves the page as evidence)
        cards = [c for c in adapter.active.evaluate(WALK_JS) if c["title"] and c["id"] not in seen]
        if not cards:
            return
        log.info("LinkedIn's Easy Apply picks, page %d: %d jobs", page_no + 1, len(cards))  # so the live output shows it is working
        for card in cards:
            seen.add(card["id"])
            if not card["applied"]:  # nothing to do for a job already applied to, and no reason to open it
                yield JobCard(adapter.name, f"https://www.linkedin.com/jobs/view/{card['id']}/", card["title"], card["company"], card["location"])
