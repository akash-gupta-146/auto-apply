"""The control panel page: the markup only. panel.js fills in the live parts, always as text, never as HTML,
because job titles in the output come from the internet.
"""
from __future__ import annotations

from html import escape

from ..credit import AUTHOR
from .actions import PORTALS, listed
from .help import help_button

AI_DISCLOSURE = (
    "With the AI helper on, the text of your resume and documents, and the answers you saved on the Questions page "
    "(consent questions left out), is sent to the AI company you chose, with email addresses and phone numbers removed, "
    "together with the public description of each job it reads. "
    "If you chose Ollama, nothing leaves your computer."
)

FIRST_SITE = next(iter(PORTALS.values()))  # what the page shows until the script has read which site was chosen
SUGGESTED_LABEL = "Apply to every job the site suggests"
# The risk is always on the page, where the choice is made; how it works is behind a "?".
SUGGESTED_RISK = "Applies without matching your roles, skills or salary, so it can apply to jobs unrelated to your resume."
SUGGESTED_MORE = (
    "Opens the site's own picks for you (LinkedIn: its Easy Apply picks; Naukri: recommended jobs; Instahyre: opportunities) and "
    "applies to each one. Indeed suggests nothing, so there it uses your role searches. A company you blocked is still skipped. "
    "Tick the AI helper to fill in forms; a question it cannot answer from your documents still stops and asks you.")
PRIVACY_RISK = "Tick what you want to delete. This cannot be undone, and applications you already sent stay sent."
PRIVACY_MORE = ("Everything this program keeps about you is stored on this computer, in the data folder. Deleting is not available "
                "while a run is going, and it only removes what this program keeps.")
RECHECK_NONE = "Also re-check jobs skipped earlier (none yet)"  # the script rewrites it with the real number for the chosen site
# What to tell the person about a site before they use it. A site with no entry here has been proven on the live site.
SITE_NOTES = {
    "instahyre": "Instahyre support is new and has not been proven on the live site yet. Rehearse first, and when you "
                 "apply for real, start with 1 application.",
    "linkedin": "LinkedIn forbids automation and can restrict accounts that use it: this is your professional account, so "
                "think before you use it. This only does Easy Apply jobs, and works slowly on purpose. A real application "
                "has been confirmed once on the live site (LinkedIn showed \"Application submitted\"), but that is one "
                "job, not a track record. Rehearse first, then apply for real with 1, and keep numbers small.",
    "indeed": "Indeed forbids automation and often stops it with a human check, so expect to be asked to help and for "
              "jobs to be skipped. This only fills in Indeed's own application form: a job that sends you to the "
              "company's website is skipped. Reading jobs has worked on the live site, but Indeed's own application "
              "form has not been proven yet. Rehearse first, then apply for real with 1.",
}


def _suggested_hint(where: str) -> str:
    """The risk, always visible and read with the checkbox, and a "?" for how it works. `where` keeps the ids apart."""
    return (f'<p class="hint"><span id="{where}-suggested-hint">{SUGGESTED_RISK}</span>'
            + help_button(f"suggested-{where}", "applying to the site's suggestions", SUGGESTED_MORE) + "</p>")


def _site_choice() -> str:
    options = "".join(
        f'<label class="check"><input type="radio" name="portal" value="{key}" data-label="{escape(label, quote=True)}"'
        f' data-note="{escape(SITE_NOTES.get(key, ""), quote=True)}"{" checked" if n == 0 else ""}> {escape(label)}</label>'
        for n, (key, label) in enumerate(PORTALS.items())
    )
    return f"""
    <fieldset class="card sites" id="site-choice">
      <legend>Which site?</legend>
      <div class="site-options">{options}</div>
      <p class="hint">Steps 3 to 5 work on the site you choose here. Log in to each site once, in the browser from step 2.</p>
      <p class="hint" id="site-note" role="status" hidden></p>
    </fieldset>"""


def _step(number: int, title: str, text: str, controls: str) -> str:
    return f"""
<article class="card step" data-step="{number}" aria-labelledby="step-{number}">
  <span class="num" aria-hidden="true">{number}</span>
  <h3 id="step-{number}">{title}</h3>
  <p>{text}</p>
  <div class="controls">{controls}</div>
</article>"""


def _button(label: str, action: str, style: str = "") -> str:
    return f'<button class="btn {style}" type="button" data-action="{action}">{label}</button>'


def render(token: str) -> str:
    steps = "".join((
        _step(1, "Your details", "Add your resume, what you are looking for, and (if you like) an AI helper.",
              '<a class="btn" href="/profile">Profile and resume</a><a class="btn" href="/ai">AI helper</a><a class="btn" id="questions-link" href="/questions">Questions</a>'),
        _step(2, "Open the browser", f"Opens a separate window that this program controls. Log in to {listed(PORTALS.values(), 'and')} in it, once each.",
              _button("Open the browser", "browser", "btn-primary")),
        _step(3, "Check the site", "A read-only test: are you logged in, and can it see jobs? It applies to nothing.",
              _button(f"Check {FIRST_SITE}", "check", "btn-primary")),
        _step(4, "Rehearse", "Walks through jobs on the chosen site and fills forms but never submits. Safe to run as often as you like.", f"""
<div class="field"><label for="rehearse-minutes">Minutes, at most</label>
<input id="rehearse-minutes" type="number" min="1" max="720" value="10" inputmode="numeric"></div>
<label class="check" for="rehearse-ai"><input id="rehearse-ai" type="checkbox"> Use the AI helper</label>
<label class="check" for="rehearse-recheck"><input id="rehearse-recheck" type="checkbox"> <span id="rehearse-recheck-text">{RECHECK_NONE}</span></label>
<label class="check" for="rehearse-suggested"><input id="rehearse-suggested" type="checkbox" aria-describedby="rehearse-suggested-hint"> {SUGGESTED_LABEL}</label>
{_suggested_hint("rehearse")}"""
              + _button("Start the rehearsal", "rehearse", "btn-primary")),
        _step(5, "Apply for real", f"Sends real applications on the chosen site. You will be asked how many, and to confirm. Start with 3 (with {listed([PORTALS[key] for key in SITE_NOTES])}, start with 1).",
              '<button class="btn btn-danger" type="button" id="apply-open">Apply for real</button>'),
    ))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="panel-token" content="{escape(token, quote=True)}">
<title>Job Apply: control panel</title>
<link rel="stylesheet" href="/static/theme.css">
<script src="/static/panel.js" defer></script>
</head>
<body>
<a class="skip" href="#console">Skip to the output</a>
<header class="top">
  <div>
    <h1>Job Apply</h1>
    <p class="sub">Your control panel. Click a step; what happens appears in the output.</p>
  </div>
  <div class="top-right">
    <span class="chip" id="os-chip">Looking at your computer&hellip;</span>
    <button class="btn btn-small" id="quit" type="button">Quit</button>
  </div>
</header>
<noscript><p class="banner">The buttons on this page need JavaScript. You can still use
<a href="/profile">Profile and resume</a> and the <a href="/ai">AI helper</a>.</p></noscript>
<main class="layout">
  <div class="left">
    <section class="card" aria-labelledby="h-status">
      <h2 id="h-status">Where things stand</h2>
      <ul class="pills" id="pills"></ul>
      <p class="next" id="next-up"></p>
    </section>
    <h2 class="sr-only">Steps</h2>
    {_site_choice()}
    <div class="grid">{steps}</div>
    <section class="card" aria-labelledby="h-tools">
      <h2 id="h-tools">Tools</h2>
      <div class="controls">
        {_button("Check my setup", "doctor")}
        {_button("Repair the install", "repair")}
        <button class="btn" type="button" data-action="install_browser" id="install-browser" hidden>Install Chrome</button>
        <button class="btn" type="button" data-open="data" id="open-data">Show the data folder</button>
        <button class="btn" type="button" data-open="reports" id="open-reports">Show the reports folder</button>
      </div>
    </section>
    <section class="card" aria-labelledby="h-reports">
      <h2 id="h-reports" tabindex="-1">Reports</h2>
      <p class="hint" id="reports-empty">Reports appear here after a run.</p>
      <ul class="reports" id="reports"></ul>
      <article class="well report" id="report-view" tabindex="0" aria-label="Report preview" hidden></article>
    </section>
    <section class="card" aria-labelledby="h-privacy">
      <h2 id="h-privacy" tabindex="-1">Your personal information</h2>
      <p class="hint">{PRIVACY_RISK}{help_button("privacy", "where your information is kept", PRIVACY_MORE)}</p>
      <ul class="erase-list" id="erase-list"></ul>
      <div class="controls">
        <button class="btn" type="button" id="erase-all">Select all</button>
        <button class="btn btn-danger" type="button" id="erase-open" disabled>Delete selected&hellip;</button>
      </div>
      <p class="notice" id="erase-result" role="status" hidden></p>
    </section>
  </div>
  <aside class="right">
    <section class="card console-card" id="console" aria-labelledby="h-out">
      <div class="console-head">
        <h2 id="h-out">Output</h2>
        <span class="status" id="run-status" data-state="idle">Nothing is running</span>
        <button class="btn btn-small btn-danger" id="stop" type="button" disabled>Stop</button>
      </div>
      <p class="notice" id="notice" hidden></p>
      <pre class="well log" id="log" role="log" aria-live="off" tabindex="0"></pre>
    </section>
  </aside>
</main>

<dialog id="apply-dialog" aria-labelledby="apply-title">
  <form id="apply-form" novalidate>
    <h2 id="apply-title">Apply for real</h2>
    <p>This sends <strong>real applications</strong> on <strong class="site-name">{escape(FIRST_SITE)}</strong>.
    It stops by itself at the limits below. Start with a small number and check the result on
    <span class="site-name">{escape(FIRST_SITE)}</span>.</p>
    <p class="hint" id="apply-site-note" hidden></p>
    <div class="field"><label for="apply-count">How many applications, at most</label>
    <input id="apply-count" type="number" min="1" max="500" value="3" inputmode="numeric"></div>
    <div class="field"><label for="apply-minutes">How many minutes, at most</label>
    <input id="apply-minutes" type="number" min="1" max="720" value="30" inputmode="numeric"></div>
    <label class="check" for="apply-ai"><input id="apply-ai" type="checkbox">
      Let the AI helper answer questions and judge jobs by their description</label>
    <p class="hint" id="apply-ai-note">{escape(AI_DISCLOSURE)}</p>
    <label class="check" for="apply-recheck"><input id="apply-recheck" type="checkbox" aria-describedby="apply-recheck-hint">
      <span id="apply-recheck-text">{RECHECK_NONE}</span></label>
    <p class="hint" id="apply-recheck-hint">Jobs it turned away earlier (they did not match, or showed no Easy Apply button) get another look, for
    example after you lower your minimum skill match. Jobs you already applied to are never re-sent.</p>
    <label class="check" for="apply-suggested"><input id="apply-suggested" type="checkbox" aria-describedby="apply-suggested-hint">
      {SUGGESTED_LABEL}</label>
    {_suggested_hint("apply")}
    <div class="field"><label for="apply-confirm">Type YES to confirm</label>
    <input id="apply-confirm" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
    <p class="error" id="apply-error" role="alert" hidden></p>
    <div class="controls">
      <button class="btn" type="button" id="apply-cancel">Cancel</button>
      <button class="btn btn-danger" type="submit">Start applying</button>
    </div>
  </form>
</dialog>
<dialog id="erase-dialog" aria-labelledby="erase-title">
  <form id="erase-form" novalidate>
    <h2 id="erase-title">Delete personal information</h2>
    <p>This will permanently delete, from this computer:</p>
    <ul id="erase-summary"></ul>
    <div class="field"><label for="erase-confirm">Type DELETE to confirm</label>
    <input id="erase-confirm" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
    <p class="error" id="erase-error" role="alert" hidden></p>
    <div class="controls">
      <button class="btn" type="button" id="erase-cancel">Cancel</button>
      <button class="btn btn-danger" type="submit">Delete for good</button>
    </div>
  </form>
</dialog>
<div class="goodbye" id="goodbye" tabindex="-1" hidden>
  <div class="goodbye-text">
    <p class="thanks">Thanks for using my application,</p>
    <p class="sign">- {escape(AUTHOR)} ❤️</p>
  </div>
</div>
<div class="sr-only" id="announce" role="status" aria-live="polite"></div>
</body>
</html>"""
