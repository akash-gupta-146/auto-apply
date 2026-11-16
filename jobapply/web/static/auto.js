"use strict";
/* The Auto-apply v2 tab: is everything ready, what it is doing now, your say on each job, and what happened.
   Everything from the server is shown as TEXT, never as HTML: job titles come from the internet. */
(() => {
  const { $, api, post, notice, announce, make, refresh, optionsFor } = window.PanelKit;
  const PORTAL_KEY = "jobapply.portal";  // the site chosen on the Apply tab: the same one is the starting point here
  const FILTER_DELAY_MS = 300;
  let current = { auto: null, run: null };  // the last look, for what a press needs to know
  let announcedFor = "", drawnFor = "", ticket = 0, typing = null;
  let capShown = null;  // the limit the box was last filled with: it is refilled only when the saved limit changes, never over what you are typing

  const site = () => document.querySelector('input[name="auto-portal"]:checked');
  const asking = () => document.querySelector('input[name="auto-mode"]:checked').value === "ask";
  const plural = (number, one, many) => `${number} ${number === 1 ? one : many}`;

  // -- is everything ready ------------------------------------------------------------------------
  // Each: [what it is, ready?, required?, what to say, where to go]. Words ("Ready", "To do") carry the meaning, not colour.
  function readiness(setup, chosen) {
    const check = ((setup.sites || {})[chosen.value] || {}).check, name = chosen.dataset.label;
    const browser = setup.browser || {};
    return [
      ["profile", setup.profile.saved && !!setup.profile.resume, true, "Your profile and resume are saved.", "Save your profile and resume.", "tab-profile"],
      ["roles", setup.roles > 0, true, `You said which roles to look for (${setup.roles}).`, "Say which roles you are looking for.", "tab-profile"],
      ["browser", !!browser.running, true, "The browser is open.",
        browser.windowless ? "The browser has no window: bring one back (step 2)." : "Open the browser (step 2).", "tab-apply"],
      ["login", check === "ok", check === "logged_out" || check === "needs_setup", `You are logged in to ${name}.`,
        check === "logged_out" ? `Log in to ${name} in the browser, then press Check.`
          : check === "needs_setup" ? `${name} needs a step only you can do: press Check to see which.`
            : `Not checked yet: press Check for ${name} to be sure you are logged in.`, "tab-apply"],
      ["ai", !!(setup.ai || {}).configured, false, "The AI helper is on.", "The AI helper is not set up: questions you have not answered will wait for you.", ""],
    ];
  }

  function renderReady(setup) {
    const items = readiness(setup, site());
    const todo = items.filter(([, ok, required]) => !ok && required).length;
    $("auto-ready-summary").textContent = todo ? `${plural(todo, "thing", "things")} to do before it can start.` : "Everything it needs is ready.";
    $("auto-ready").replaceChildren(...items.map(([key, ok, required, done, undone, goto]) => {
      const row = make("li", "", `${ok ? "Ready" : required ? "To do" : "Optional"}: ${ok ? done : undone}`);
      row.dataset.item = key;
      if (!ok && goto) {
        const go = make("button", "btn btn-small", goto === "tab-profile" ? "Go to the Profile tab" : "Go to the Apply tab");
        go.type = "button"; go.dataset.goto = goto;
        row.append(" ", go);
      } else if (!ok && key === "ai") {
        const link = make("a", "", "AI helper"); link.href = "/ai";
        row.append(" ", link);
      }
      return row;
    }));
    $("auto-ai").disabled = !(setup.ai || {}).configured;
    if ($("auto-ai").disabled) $("auto-ai").checked = false;
  }

  // -- now ------------------------------------------------------------------------------------------
  function renderToday(auto) {
    const chosen = site(), sent = auto.sent[chosen.value] || 0, cap = auto.cap, name = chosen.dataset.label;
    $("auto-meter").max = cap > 0 ? cap : Math.max(sent, 1);
    $("auto-meter").value = sent;
    $("auto-today").textContent = cap > 0 ? `${sent} of ${cap} sent today on ${name}` : `${sent} sent today on ${name} (no daily limit)`;
    $("auto-count-hint").textContent = cap > 0 ? (sent >= cap ? `You have used today's limit on ${name}: it starts again tomorrow, or raise the limit below.`
      : `You can still send ${cap - sent} today on ${name}.`) : "";
    if (cap !== capShown) { capShown = cap; $("auto-cap").value = cap > 0 ? cap : ""; }
  }

  function stateWords(auto, run, running) {
    if (!running) return "Nothing is running.";
    if (auto.review) return "Waiting for you: apply to the job below?";
    if (auto.paused) return "Paused. It finishes the step it is on, then waits. Press Resume to go on.";
    return `Running: ${run.label || "a run"}.`;
  }

  function renderReview(review) {
    $("auto-review-card").hidden = !review;
    if (!review) return;
    const job = review.job;
    const title = job.title || "(no title)";
    if (job.url) {  // the server only sends web addresses
      const link = make("a", "", title);
      link.href = job.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.append(make("span", "sr-only", " (opens in a new tab)"));
      $("auto-job-title").replaceChildren(link);
    } else {
      $("auto-job-title").textContent = title;
    }
    $("auto-job-facts").textContent = [job.company, job.location, job.experience, job.salary].filter(Boolean).join(" \u00b7 ");
    $("auto-job-why").textContent = job.why ? `Why it fits: ${job.why}` : "";
    if (announcedFor !== review.token) {  // said once, not on every look
      announcedFor = review.token;
      announce(`A job is waiting for your decision: ${title}. Apply or skip.`);
    }
  }

  function renderBadge(auto, running) {
    const badge = $("auto-badge"), words = auto.review ? "your turn" : auto.paused && running ? "paused" : running ? "working" : "";
    badge.textContent = words; badge.hidden = !words; badge.dataset.kind = auto.review ? "urgent" : "";
  }

  function render(data) {
    const { auto, run, setup } = data, running = run.state === "running";
    current = { auto, run };
    renderReady(setup);
    renderToday(auto);
    $("auto-state").textContent = stateWords(auto, run, running);
    $("auto-asking").hidden = !(running && setup.questions > 0);
    $("auto-asking-text").textContent = `${plural(setup.questions, "question is", "questions are")} waiting. A form may be paused until you answer.`;
    renderReview(auto.review);
    $("panel-auto").toggleAttribute("data-busy", running || !!auto.review);
    $("auto-pause").textContent = auto.paused ? "Resume" : "Pause";
    $("auto-pause").disabled = !running && !auto.paused;
    $("auto-stop").disabled = !running;
    renderBadge(auto, running);
    const signature = [run.run_id, run.state, run.next, auto.paused, JSON.stringify(auto.sent), auto.review ? auto.review.token : ""].join("|");
    if (signature !== drawnFor) { drawnFor = signature; if (!$("panel-auto").hidden) loadHistory(); }  // something happened: look again
  }

  // -- what happened ----------------------------------------------------------------------------------
  const filters = () => new URLSearchParams({ group: $("auto-f-group").value, days: $("auto-f-days").value, text: $("auto-f-text").value.trim() });

  async function loadHistory() {
    const mine = ++ticket, query = filters().toString();
    $("auto-export").href = `/export/applications.csv?${query}`;  // the file holds exactly what the table shows (and all of it)
    try {
      const found = await api(`/api/auto/history?${query}`);
      if (mine !== ticket) return;  // a slower answer to an older choice
      const narrowed = [...filters().values()].some((value) => value && value !== "0");
      $("auto-table-wrap").hidden = !found.jobs.length;
      $("auto-history-note").textContent = !found.jobs.length ? (narrowed ? "Nothing fits these choices." : "Nothing yet: what a run does shows up here.")
        : `${plural(found.jobs.length, "job", "jobs")}, newest first.${found.more ? " That is the newest few hundred: the spreadsheet has all of them." : ""}`;
      if (found.jobs.length) window.JobTable.render($("auto-table"), "What the auto-apply runs did", found.jobs, true);
      else $("auto-table").replaceChildren();  // nothing fits: no old rows left behind, even out of sight
    } catch (error) {
      if (mine === ticket) $("auto-history-note").textContent = error.message;
    }
  }

  // -- pressing things ------------------------------------------------------------------------------------
  async function tell(path, body) {
    try { await post(path, body); await refresh(); } catch (error) { notice(error.message, "error"); }
  }

  function showNote() {
    const note = $("auto-site-note"), text = site().dataset.note;
    note.textContent = text; note.hidden = !text;
  }

  optionsFor.auto = () => ({ portal: site().value, count: $("auto-count").value, ai: $("auto-ai").checked, review: asking(), confirm: $("auto-confirm").value });

  $("auto-approve").addEventListener("click", () => tell("/api/auto/decide", { token: current.auto.review.token, decision: "approve" }));
  $("auto-skip").addEventListener("click", () => tell("/api/auto/decide", { token: current.auto.review.token, decision: "reject" }));
  $("auto-pause").addEventListener("click", () => tell("/api/auto/pause", { paused: !current.auto.paused }));
  $("auto-stop").addEventListener("click", () => tell("/api/stop"));
  $("auto-cap-save").addEventListener("click", async () => {
    try { const saved = await post("/api/auto/limit", { cap: $("auto-cap").value }); notice(`The daily limit is now ${saved.cap}. It applies from the next start.`); await refresh(); }
    catch (error) { notice(error.message, "error"); }
  });
  for (const radio of document.querySelectorAll('input[name="auto-portal"]')) {
    radio.addEventListener("change", () => { showNote(); if (state()) render(state()); });
  }
  for (const radio of document.querySelectorAll('input[name="auto-mode"]')) {
    radio.addEventListener("change", () => { $("auto-direct-options").hidden = asking(); });
  }
  for (const id of ["auto-f-group", "auto-f-days"]) $(id).addEventListener("change", loadHistory);
  $("auto-f-text").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(loadHistory, FILTER_DELAY_MS); });
  document.addEventListener("click", (event) => {  // "Go to the Profile tab": the tabs are the page's own buttons
    const go = event.target.closest("[data-goto]");
    if (!go) return;
    const tab = $(go.dataset.goto);
    tab.click();
    document.getElementById(tab.getAttribute("aria-controls")).querySelector("h2").focus();
  });
  new MutationObserver(() => { if (!$("panel-auto").hidden) loadHistory(); }).observe($("panel-auto"), { attributes: true, attributeFilter: ["hidden"] });

  const state = () => window.PanelKit.state.last;
  try {
    const remembered = localStorage.getItem(PORTAL_KEY), radio = document.querySelector(`input[name="auto-portal"][value="${remembered}"]`);
    if (radio) radio.checked = true;
  } catch (_) { /* a browser that will not remember: the first site */ }
  showNote();

  document.addEventListener("panel:state", (event) => render(event.detail));
  if (state()) render(state());  // the first look can arrive before this script has started listening
})();
