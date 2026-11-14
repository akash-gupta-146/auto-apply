"""The Profile tab: a dashboard of what every site has done with your jobs, then your details, the tools and your personal information.

Markup only. dashboard.js draws the live parts (as SVG shapes and text, never as HTML) from the numbers the panel sends, and fills
the list of applications that opens when you press a tile, a number or a stripe of a bar.
"""
from __future__ import annotations


def _dashboard() -> str:
    return """
<section class="card" id="dashboard" aria-labelledby="h-dash">
  <h2 id="h-dash">Your applications at a glance</h2>
  <p class="hint" id="dash-empty">Nothing to show yet. After a rehearsal or a real run, every site's jobs appear here: sent, skipped and
  failed.</p>
  <div id="dash-body" hidden>
    <div class="dash-top">
      <svg class="donut" id="dash-donut" viewBox="0 0 42 42" role="img" aria-label=""></svg>
      <div class="kpis" id="dash-kpis" role="group" aria-label="All sites: choose one to list its applications"></div>
    </div>
    <h3 id="h-dash-sites">By site</h3>
    <p class="hint" id="dash-scale">Each bar is as long as that site is busy, next to the busiest site. The colours are the tiles above.
    Press a tile or a number to list those applications.</p>
    <ul class="dash-rows" id="dash-rows" aria-labelledby="h-dash-sites"></ul>
    <section class="dash-list" id="dash-list" aria-labelledby="h-dash-list" hidden>
      <div class="dash-list-head">
        <h3 id="h-dash-list" tabindex="-1"></h3>
        <button class="btn btn-small" type="button" id="dash-list-close">Close the list</button>
      </div>
      <p class="hint" id="dash-list-note" role="status"></p>
      <div class="table-wrap" id="dash-list-wrap" role="region" aria-labelledby="h-dash-list" tabindex="0"><table id="dash-list-table"></table></div>
    </section>
    <details class="dash-table">
      <summary>Show these numbers as a table</summary>
      <div class="table-wrap"><table id="dash-table"></table></div>
    </details>
  </div>
</section>"""


def render(details_card: str, tools_card: str, privacy_card: str) -> str:
    """The destructive section goes last, so it is never what you reach for by accident."""
    return _dashboard() + details_card + tools_card + privacy_card
