"""The Auto-apply v2 tab: the markup only. auto.js fills in the live parts, always as text.

Reading order is the order of doing it: is everything ready, choose what to do and press Start, watch it and answer when it asks, look back at what
happened. Nothing is sent without you unless you choose that, and the page says so in the place where the choice is made.
"""
from __future__ import annotations

from html import escape
from typing import Mapping

from . import auto, dashboard

DEFAULT_COUNT = 10
WARNING = ("Some job sites forbid automated applications and can restrict an account that uses them: you decide whether to use this, and you are "
           "responsible for what is sent. It works slowly on purpose, it never solves a captcha or a check (it stops and waits for you), and it stops "
           "by itself at your daily limit.")


def _sites(sites: Mapping[str, str], notes: Mapping[str, str]) -> str:
    options = "".join(
        f'<label class="check"><input class="with-gap" type="radio" name="auto-portal" value="{key}" data-label="{escape(label, quote=True)}"'
        f' data-note="{escape(notes.get(key, ""), quote=True)}"{" checked" if n == 0 else ""}><span>{escape(label)}</span></label>'
        for n, (key, label) in enumerate(sites.items()))
    return f'<fieldset class="field auto-sites"><legend>Which site?</legend><div class="site-options">{options}</div></fieldset>'


def _outcomes() -> str:
    return '<option value="">All outcomes</option>' + "".join(
        f'<option value="{group}">{escape(dashboard.LABELS[group][0])}</option>' for group in dashboard.GROUPS)


def render(sites: Mapping[str, str], notes: Mapping[str, str], ai_disclosure: str) -> str:
    return f"""
    <section class="card" id="auto-card" aria-labelledby="h-auto">
      <h2 id="h-auto" tabindex="-1">Auto-apply v2</h2>
      <p>Let the program work through jobs for you. It applies only to jobs that fit the roles and skills you saved, fills each form in from your saved
      answers, and <strong>by default shows you every job first</strong>: you press Apply or Skip.</p>
      <h3 id="h-auto-ready">Is everything ready?</h3>
      <p id="auto-ready-summary" role="status"></p>
      <ul class="auto-ready" id="auto-ready" aria-labelledby="h-auto-ready"></ul>
      {_sites(sites, notes)}
      <p class="hint" id="auto-site-note" hidden></p>
      <div class="field"><label for="auto-count">Apply to how many jobs, at most?</label>
      <input id="auto-count" type="number" min="1" max="500" value="{DEFAULT_COUNT}" inputmode="numeric" aria-describedby="auto-count-hint"></div>
      <p class="hint" id="auto-count-hint"></p>
      <fieldset class="field"><legend>How should it work?</legend>
        <label class="check"><input class="with-gap" type="radio" name="auto-mode" id="auto-ask" value="ask" checked aria-describedby="auto-ask-hint"><span>Ask me before each application (recommended)</span></label>
        <p class="hint" id="auto-ask-hint">It shows you the job and why it fits, here. It applies only after you press Apply; Skip moves on and remembers.
        If nobody answers two jobs in a row, it stops.</p>
        <label class="check"><input class="with-gap" type="radio" name="auto-mode" id="auto-direct" value="direct" aria-describedby="auto-direct-hint"><span>Apply by itself</span></label>
        <p class="hint" id="auto-direct-hint">It sends every application that fits, without asking. You can still Pause or Stop.</p>
      </fieldset>
      <div id="auto-direct-options" hidden>
        <div class="field"><label for="auto-confirm">Type YES to allow sending without asking</label>
        <input id="auto-confirm" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
      </div>
      <label class="check" for="auto-ai"><input class="filled-in" id="auto-ai" type="checkbox" aria-describedby="auto-ai-hint"><span>Use the AI helper for questions I have not answered</span></label>
      <p class="hint" id="auto-ai-hint">Answers only from your own documents, and says so when it cannot. {ai_disclosure}</p>
      <p class="hint">{escape(WARNING)}</p>
      <div class="controls">
        <button class="btn btn-primary" type="button" data-action="auto" id="auto-start" aria-describedby="auto-ready-summary">Start auto-apply</button>
      </div>
    </section>
    <section class="card" id="auto-live" aria-labelledby="h-auto-live">
      <h2 id="h-auto-live" tabindex="-1">Now</h2>
      <p id="auto-state" role="status">Nothing is running.</p>
      <div class="auto-meter"><progress id="auto-meter" max="1" value="0" aria-labelledby="auto-today"></progress>
      <span id="auto-today"></span></div>
      <div class="notice" id="auto-asking" role="group" aria-labelledby="auto-asking-title" hidden>
        <h3 id="auto-asking-title">A form is waiting for your answer</h3>
        <p id="auto-asking-text"></p>
        <p><a href="/questions">Answer questions</a>, or type the answer into the form in the browser.</p>
      </div>
      <div class="notice" id="auto-review-card" role="group" aria-labelledby="auto-review-title" hidden>
        <h3 id="auto-review-title">Apply to this job?</h3>
        <p><strong id="auto-job-title"></strong></p>
        <p id="auto-job-facts"></p>
        <p id="auto-job-why"></p>
        <div class="controls">
          <button class="btn btn-primary" type="button" id="auto-approve">Apply to it</button>
          <button class="btn" type="button" id="auto-skip">Skip it</button>
        </div>
      </div>
      <div class="controls">
        <button class="btn" type="button" id="auto-pause">Pause</button>
        <button class="btn btn-danger" type="button" id="auto-stop" disabled>Stop</button>
      </div>
      <details class="auto-cap">
        <summary>Daily limit</summary>
        <div class="field"><label for="auto-cap">Most applications to send in a day, on each site</label>
        <input id="auto-cap" type="number" min="1" max="{auto.MAX_DAILY_CAP}" inputmode="numeric" aria-describedby="auto-cap-hint"></div>
        <p class="hint" id="auto-cap-hint">A safety: it stops by itself when today's number is reached, and starts again tomorrow. Raise it only on purpose.</p>
        <div class="controls"><button class="btn" type="button" id="auto-cap-save">Save the limit</button></div>
      </details>
    </section>
    <section class="card" id="auto-history" aria-labelledby="h-auto-history">
      <h2 id="h-auto-history" tabindex="-1">What happened</h2>
      <div class="auto-filters" role="search" aria-label="Narrow the list">
        <div class="field"><label for="auto-f-group">Outcome</label><select class="browser-default" id="auto-f-group">{_outcomes()}</select></div>
        <div class="field"><label for="auto-f-days">When</label><select class="browser-default" id="auto-f-days">
          <option value="0">Any time</option><option value="1">Today</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select></div>
        <div class="field"><label for="auto-f-text">Company or job</label><input id="auto-f-text" type="search" autocomplete="off" spellcheck="false"></div>
      </div>
      <p class="hint" id="auto-history-note" role="status"></p>
      <div class="table-wrap" id="auto-table-wrap" role="region" aria-labelledby="h-auto-history" tabindex="0"><table id="auto-table"></table></div>
      <div class="controls"><a class="btn" id="auto-export" href="/export/applications.csv" download>Download as a spreadsheet (CSV)</a></div>
    </section>"""
