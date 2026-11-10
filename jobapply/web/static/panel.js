"use strict";
/* The control panel's behaviour. Everything from the server or the program's output is shown as TEXT, never
   as HTML: job titles in the output come from the internet. */
(() => {
  const token = document.querySelector('meta[name="panel-token"]').content;
  const $ = (id) => document.getElementById(id);
  const POLL_BUSY_MS = 1000, POLL_IDLE_MS = 4000, MAX_CHUNKS = 400;
  const RUN_WORDS = {
    idle: "Nothing is running", running: "Running", stopping: "Stopping",
    finished: "Finished", failed: "Stopped with a problem", stopped: "Stopped",
  };
  const READ_KEY = "jobapply.readReports", PORTAL_KEY = "jobapply.portal", MAX_READ = 200, SURE_FOR_MS = 4000;
  const app = {
    since: 0, runId: 0, setup: null, os: null, runState: "idle", failures: 0, quitting: false, quitTimer: null,
    reports: null, labels: {}, sites: {}, read: loadRead(), armed: null, erasable: [], eraseSeen: "",
  };

  // -- talking to the server ---------------------------------------------------------------
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options, cache: "no-store", headers: { "X-Token": token, "Content-Type": "application/json" },
    });
    let data = {};
    try { data = await response.json(); } catch (_) { /* an empty answer */ }
    if (!response.ok) throw new Error(data.error || `Something went wrong (${response.status}).`);
    return data;
  }
  const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });

  // -- small helpers -----------------------------------------------------------------------
  function announce(text) { $("announce").textContent = text; }
  function notice(text, kind = "info") {
    const box = $("notice");
    box.textContent = text; box.dataset.kind = kind; box.hidden = !text;
    if (text) announce(text);
  }
  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  // -- which site the buttons work on: remembered in this browser ---------------------------
  const siteRadios = () => [...document.querySelectorAll('input[name="portal"]')];
  function selectedSite() {
    const radio = siteRadios().find((box) => box.checked) || siteRadios()[0];
    return { id: radio.value, label: radio.dataset.label, note: radio.dataset.note || "" };
  }
  function chooseSite() {
    try { localStorage.setItem(PORTAL_KEY, selectedSite().id); } catch (_) { /* blocked: fine */ }
    if (app.setup) renderSetup(app.setup);  // the pills and the next step are about this site, so redraw them now
  }
  function restoreSite() {
    let saved = "";
    try { saved = localStorage.getItem(PORTAL_KEY) || ""; } catch (_) { /* blocked: fine */ }
    const match = siteRadios().find((box) => box.value === saved);
    if (match) match.checked = true;
  }

  // -- the status pills and "what next" ---------------------------------------------------
  function pillsFor(s) {
    const site = selectedSite(), info = (s.sites || {})[site.id] || { check: null, queue: {} };
    const queue = info.queue || {}, total = Object.values(queue).reduce((a, b) => a + b, 0);
    const profile = s.profile.saved
      ? ["ok", `Profile saved${s.profile.name ? ": " + s.profile.name : ""}${s.profile.resume ? ", resume " + s.profile.resume : ""}`]
      : ["warn", "Profile not set up yet"];
    const browser = !s.browser.found ? ["warn", "No Chrome or BrowserOS found"]
      : s.browser.running ? ["ok", "Browser window is open"] : ["off", "Browser window is closed"];
    const login = {
      ok: ["ok", `Logged in to ${site.label}`], logged_out: ["warn", `Not logged in to ${site.label}`],
      needs_setup: ["warn", `${site.label} needs your profile finished first`],
    }[info.check] || ["off", `${site.label} login not checked yet`];
    const ai = s.ai.configured ? ["ok", `AI helper: ${s.ai.label}`] : ["off", "AI helper is off"];
    const jobs = total ? ["ok", `Jobs: ${queue.applied || 0} applied, ${queue.needs_answer || 0} waiting for you, ${total} seen`]
      : ["off", "No jobs seen yet"];
    const asking = s.questions
      ? [["warn", `${s.questions} question${s.questions === 1 ? "" : "s"} waiting for you: answer ${s.questions === 1 ? "it" : "them"} on the Questions page (step 1)`]]
      : [];
    return [profile, browser, login, ai, jobs, ...asking];
  }

  function nextStep(s) {
    const site = selectedSite(), check = ((s.sites || {})[site.id] || {}).check;
    if (!s.profile.saved) return [1, "Start with step 1: add your profile and resume."];
    if (!s.browser.found) return [2, "No Chrome was found. Use Install Chrome under Tools, then open the browser."];
    if (!s.browser.running) {
      return [2, s.browser.windowless ? "The browser is running but its window was closed. Press Open the browser (step 2) to bring one back."
        : `Next: open the browser (step 2) and log in to ${site.label} in it.`];
    }
    if (check === "needs_setup") {  // only the person can do this, on the site itself
      return [3, `${site.label} is asking you to finish setting up your profile first. Do that yourself in the browser window, then check ${site.label} again (step 3).`];
    }
    if (check !== "ok") return [3, `Next: check ${site.label} (step 3).`];
    return [4, "Ready. Rehearse first (step 4), then apply with a small number (step 5)."];
  }

  function renderSetup(s) {
    const list = $("pills");
    list.replaceChildren(...pillsFor(s).map(([kind, text]) => {
      const item = make("li", "pill");
      item.dataset.state = kind;
      item.append(make("span", "mark", kind === "ok" ? "\u2713" : kind === "warn" ? "!" : "\u2013"), make("span", "", text));
      return item;
    }));
    const [step, words] = nextStep(s);
    $("next-up").textContent = words;
    document.querySelectorAll(".step").forEach((card) => {
      if (Number(card.dataset.step) === step) card.setAttribute("aria-current", "step");
      else card.removeAttribute("aria-current");
    });
    $("install-browser").hidden = s.browser.found;
    const site = selectedSite();
    document.querySelector('[data-action="check"]').textContent = `Check ${site.label}`;
    $("site-note").textContent = site.note; $("site-note").hidden = !site.note;
    renderReports(s.reports, s.report_labels, s.report_sites || {});
    renderErase(s.privacy);
    const note = $("apply-ai-note"), box = $("apply-ai");
    box.disabled = !s.ai.configured;
    if (!s.ai.configured) box.checked = false;
    note.dataset.configured = String(s.ai.configured);
    renderRecheck(s);
    renderQuestionsButton(s);
  }

  // Questions a run is waiting on: the button says how many and glows (see .btn[data-waiting]), because it kept being missed.
  function renderQuestionsButton(s) {
    const waiting = s.questions || 0, link = $("questions-link");
    link.textContent = waiting ? `Questions (${waiting} waiting)` : "Questions";
    link.toggleAttribute("data-waiting", waiting > 0);
  }

  // The jobs a run could look at again: the ones it turned away itself (not the ones you already applied to).
  function renderRecheck(s) {
    const info = (s.sites || {})[selectedSite().id] || {}, queue = info.queue || {};
    const skipped = (queue.skipped_match || 0) + (queue.skipped_external || 0);
    for (const id of ["rehearse", "apply"]) {
      const box = $(`${id}-recheck`);
      box.disabled = skipped === 0;
      if (!skipped) box.checked = false;
      $(`${id}-recheck-text`).textContent = skipped
        ? `Also re-check the ${skipped} job${skipped === 1 ? "" : "s"} skipped earlier`
        : "Also re-check jobs skipped earlier (none yet)";
    }
  }

  function renderReports(names, labels, sites) {
    const known = app.reports;
    // Rebuilding the buttons every few seconds would throw a keyboard user's focus away: only rebuild when the list changed.
    if (known && known.length === names.length && known.every((name, i) => name === names[i])) return;
    // A report is NEW when it sorts after the newest one already known (names start with the date and time). One that
    // only shows up because a newer report was deleted is an old report coming back into view: it must not pop open.
    const newest = known && known.length ? known[0] : "";
    const fresh = known === null ? [] : names.filter((name) => name > newest);  // the first look only learns what is there
    app.reports = names; app.labels = labels; app.sites = sites;
    $("reports-empty").hidden = names.length > 0;
    $("reports").replaceChildren(...names.map(reportRow));
    syncReportButtons();
    if (fresh.length) showReport(names[0], { toggle: false }).then((shown) => {
      if (!shown) return;
      $("report-view").scrollIntoView({ block: "nearest" });
      announce(`A new report is ready: ${labels[names[0]] || names[0]}`);
    });
  }

  const reportLabel = (name) => app.labels[name] || name;

  function reportRow(name) {  // the report's own button, and a Delete button right beside it
    const item = make("li"), open = make("button", "btn btn-small", reportLabel(name)), remove = make("button", "btn btn-small btn-danger");
    const site = app.sites[name];  // which site it was made for, told beside the name (the name itself keeps its format)
    open.type = "button"; open.dataset.report = name; open.title = name;  // the file name, on hover
    open.setAttribute("aria-controls", "report-view");
    remove.type = "button"; remove.dataset.deleteReport = name;
    labelDelete(remove, false);
    item.append(open);
    if (site) item.append(make("span", "chip tag", site));
    item.append(remove);
    return item;
  }

  // Reports that have been read look different from those that have not. Remembered in this browser; if it will not keep
  // them, they are remembered until the page is closed.
  function loadRead() {
    try { return new Set(JSON.parse(localStorage.getItem(READ_KEY)) || []); } catch (_) { return new Set(); }
  }
  function saveRead() {
    try { localStorage.setItem(READ_KEY, JSON.stringify([...app.read].slice(-MAX_READ))); } catch (_) { /* blocked: fine */ }
  }

  function syncReportButtons() {  // which report is open (for assistive technology), and which have not been read yet
    const view = $("report-view");
    document.querySelectorAll("[data-report]").forEach((button) => {
      const name = button.dataset.report, unread = !app.read.has(name);
      button.setAttribute("aria-expanded", String(!view.hidden && name === view.dataset.name));
      button.dataset.read = String(!unread);
      const words = [button.textContent, app.sites[name], unread ? "unread" : ""].filter(Boolean);  // not told by colour alone
      if (words.length > 1) button.setAttribute("aria-label", words.join(", "));
      else button.removeAttribute("aria-label");
    });
  }

  // Deleting a report takes two presses: the first only asks "Sure?", and goes back to "Delete" after a few seconds.
  function labelDelete(button, sure) {
    button.textContent = sure ? "Sure?" : "Delete";
    button.setAttribute("aria-label", `${sure ? "Sure? Delete" : "Delete"} report ${reportLabel(button.dataset.deleteReport)}`);
  }
  function disarmDelete() {
    if (!app.armed) return;
    clearTimeout(app.armed.timer);
    if (app.armed.button.isConnected) labelDelete(app.armed.button, false);
    app.armed = null;
  }
  async function deleteReport(button) {
    const name = button.dataset.deleteReport, shown = reportLabel(name);
    if (!app.armed || app.armed.button !== button) {
      disarmDelete();
      labelDelete(button, true);
      app.armed = { button, timer: setTimeout(disarmDelete, SURE_FOR_MS) };
      announce(`Press again to delete report ${shown}.`);
      return;
    }
    disarmDelete();
    try {
      await post("/api/report/delete", { name });
      app.read.delete(name); saveRead();
      const view = $("report-view");
      if (view.dataset.name === name) { view.hidden = true; view.replaceChildren(); delete view.dataset.name; }
      await refresh();
    } catch (error) { notice(error.message, "error"); return; }
    announce(`Report ${shown} deleted.`);
    (document.querySelector("[data-report]") || $("h-reports")).focus();  // the button that had focus is gone
  }

  // -- the output --------------------------------------------------------------------------
  function clearLog() { $("log").replaceChildren(); }
  function appendLines(lines, dropped) {
    if (!lines.length && !dropped) return;
    const log = $("log"), atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 48;
    if (dropped) log.append(document.createTextNode("[older output is not shown]\n"));
    if (lines.length) log.append(document.createTextNode(lines.join("\n") + "\n"));
    while (log.childNodes.length > MAX_CHUNKS) log.removeChild(log.firstChild);
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  function renderRun(run) {
    const status = $("run-status"), busy = run.state === "running" || run.state === "stopping";
    let words = RUN_WORDS[run.state] || run.state;
    if (run.label && run.state !== "idle") words += `: ${run.label}`;
    if (run.state === "failed" && run.exit_code !== null) words += ` (code ${run.exit_code})`;
    if (status.textContent !== words) announce(words);
    status.textContent = words; status.dataset.state = run.state;
    document.querySelectorAll("[data-action], #apply-open").forEach((button) => { button.disabled = busy; });
    $("stop").disabled = run.state !== "running";
    app.runState = run.state;
    updateEraseButtons();  // nothing can be deleted while a run is going
  }

  // -- polling -----------------------------------------------------------------------------
  async function refresh() {
    let data = await api(`/api/state?since=${app.since}`);
    if (data.run.run_id !== app.runId) {  // a different run: its output starts from the beginning
      app.runId = data.run.run_id; app.since = 0; clearLog();
      if (data.run.next > 0) data = await api("/api/state?since=0");
    }
    $("os-chip").textContent = data.os.label;
    app.os = data.os; app.setup = data.setup;
    $("open-data").textContent = `Show the data folder in ${data.os.file_manager}`;
    $("open-reports").textContent = `Show the reports folder in ${data.os.file_manager}`;
    appendLines(data.run.lines, data.run.dropped);
    app.since = data.run.next;
    renderRun(data.run);
    renderSetup(data.setup);
    app.failures = 0;
  }

  async function tick() {
    if (app.quitting) return;
    try {
      await refresh();
    } catch (error) {
      app.failures += 1;
      if (app.failures >= 3) { notice("The panel has stopped. You can close this tab.", "error"); return; }
    }
    setTimeout(tick, app.runState === "running" || app.runState === "stopping" ? POLL_BUSY_MS : POLL_IDLE_MS);
  }

  // -- the buttons -------------------------------------------------------------------------
  async function start(action, options = {}) {
    notice("");
    try {
      await post("/api/run", { action, ...options });
      await refresh();
      $("console").scrollIntoView({ behavior: "smooth", block: "nearest" });
      return true;
    } catch (error) {
      notice(error.message, "error");
      return false;
    }
  }

  function optionsFor(action) {
    const portal = selectedSite().id;
    if (action === "rehearse") {
      return { portal, minutes: $("rehearse-minutes").value, ai: $("rehearse-ai").checked, recheck: $("rehearse-recheck").checked,
        suggested: $("rehearse-suggested").checked };
    }
    return action === "check" ? { portal } : {};
  }

  // -- a report, shown as a page. Built from text pieces only: the titles in it come from the internet ------------
  function fill(parent, pieces) {
    for (const [kind, value] of pieces) {
      if (kind === "bold") parent.append(make("strong", "", value));
      else if (kind === "code") parent.append(make("code", "", value));
      else if (kind === "link" && /^https?:\/\//i.test(value)) {
        const link = make("a", "", "open \u2197");  // the address is in the tooltip: every row shows the same host
        link.href = value; link.title = value; link.target = "_blank"; link.rel = "noopener noreferrer";
        parent.append(link);
      } else parent.append(document.createTextNode(value));
    }
    return parent;
  }
  function renderBlock(block) {
    if (block.type === "heading") return fill(make(`h${block.level + 2}`), block.spans);
    if (block.type === "paragraph") return fill(make("p"), block.spans);
    if (block.type === "list") {
      const list = make("ul");
      block.items.forEach((pieces) => list.append(fill(make("li"), pieces)));
      return list;
    }
    const table = make("table"), wrap = make("div", "table-wrap");
    if (block.head.length) {
      const row = make("tr");
      block.head.forEach((pieces) => { const cell = fill(make("th"), pieces); cell.scope = "col"; row.append(cell); });
      table.append(make("thead")); table.tHead.append(row);
    }
    const body = make("tbody");
    block.rows.forEach((cells) => { const row = make("tr"); cells.forEach((pieces) => row.append(fill(make("td"), pieces))); body.append(row); });
    table.append(body); wrap.append(table);
    return wrap;
  }

  // Returns true when the report is now on show.
  async function showReport(name, { toggle = true } = {}) {
    const view = $("report-view");
    if (toggle && !view.hidden && view.dataset.name === name) { view.hidden = true; syncReportButtons(); return false; }
    try {
      const data = await api(`/api/report?name=${encodeURIComponent(name)}`);
      view.replaceChildren(...data.blocks.map(renderBlock)); view.dataset.name = name; view.hidden = false;
      app.read.add(name); saveRead();  // whatever opened it, it has now been shown
      syncReportButtons();
      return true;
    } catch (error) { notice(error.message, "error"); return false; }
  }

  function openApplyDialog() {
    const site = selectedSite();
    document.querySelectorAll(".site-name").forEach((name) => { name.textContent = site.label; });
    $("apply-site-note").textContent = site.note; $("apply-site-note").hidden = !site.note;
    $("apply-count").value = site.note ? "1" : "3";  // a site not yet proven live starts with a single application
    $("apply-error").hidden = true; $("apply-confirm").value = "";
    $("apply-dialog").showModal();
  }

  async function submitApply(event) {
    event.preventDefault();
    const error = $("apply-error");
    if ($("apply-confirm").value !== "YES") {
      error.textContent = "Type YES in capital letters to confirm."; error.hidden = false; $("apply-confirm").focus(); return;
    }
    const started = await start("apply", {
      portal: selectedSite().id, count: $("apply-count").value, minutes: $("apply-minutes").value, ai: $("apply-ai").checked,
      recheck: $("apply-recheck").checked, suggested: $("apply-suggested").checked, confirm: "YES",
    });
    if (started) $("apply-dialog").close();
    else { error.textContent = $("notice").textContent || "That did not start."; error.hidden = false; }
  }

  // -- deleting personal information: tick what to delete, then confirm by typing DELETE (the server checks that too) ----
  const eraseBoxes = () => [...document.querySelectorAll("#erase-list input")];
  const tickedBoxes = () => eraseBoxes().filter((box) => box.checked);
  const kindLabel = (id) => (app.erasable.find((item) => item.id === id) || {}).label || id;

  function renderErase(items) {
    const signature = JSON.stringify(items);
    if (signature === app.eraseSeen) return;  // only rebuilt when something changed, so ticks and focus stay where they are
    app.eraseSeen = signature; app.erasable = items;
    const keep = new Set(tickedBoxes().map((box) => box.value));
    $("erase-list").replaceChildren(...items.map((item) => {
      const row = make("li"), label = make("label", "check"), box = make("input"), text = make("span");
      box.type = "checkbox"; box.value = item.id; box.disabled = !item.present; box.checked = item.present && keep.has(item.id);
      text.append(make("span", "erase-name", item.label), make("span", "hint", item.present ? item.what : "Nothing saved."));
      label.append(box, text); row.append(label);
      return row;
    }));
    updateEraseButtons();
  }

  function updateEraseButtons() {
    const usable = eraseBoxes().filter((box) => !box.disabled), chosen = tickedBoxes().length;
    $("erase-open").disabled = chosen === 0 || app.runState === "running" || app.runState === "stopping";
    $("erase-all").disabled = usable.length === 0;
    $("erase-all").textContent = usable.length && chosen === usable.length ? "Clear selection" : "Select all";
  }

  function toggleAllErase() {
    const usable = eraseBoxes().filter((box) => !box.disabled), all = usable.every((box) => box.checked);
    usable.forEach((box) => { box.checked = !all; });
    updateEraseButtons();
  }

  function openEraseDialog() {
    $("erase-summary").replaceChildren(...tickedBoxes().map((box) => {
      const item = app.erasable.find((entry) => entry.id === box.value), row = make("li");
      row.append(make("strong", "", item.label), document.createTextNode(`: ${item.what}`));
      return row;
    }));
    $("erase-error").hidden = true; $("erase-confirm").value = "";
    $("erase-dialog").showModal();
  }

  function showErased({ deleted, failed }) {
    const names = (ids) => ids.map(kindLabel).join(", "), box = $("erase-result");
    const problems = failed.map((item) => `${kindLabel(item.id)} (${item.reason})`).join(", ");
    box.textContent = failed.length
      ? `Could not delete: ${problems}.${deleted.length ? ` Deleted: ${names(deleted)}.` : ""}`
      : `Deleted: ${names(deleted)}.`;
    box.dataset.kind = failed.length ? "error" : "info"; box.hidden = false;
    announce(box.textContent);
  }

  async function submitErase(event) {
    event.preventDefault();
    const error = $("erase-error"), typed = $("erase-confirm").value;
    if (typed !== "DELETE") {
      error.textContent = "Type DELETE in capital letters to confirm."; error.hidden = false; $("erase-confirm").focus(); return;
    }
    try {
      const result = await post("/api/erase", { items: tickedBoxes().map((box) => box.value), confirm: typed });
      $("erase-dialog").close();
      if (result.deleted.includes("logs")) clearLog();  // the output shown here is a log too
      await refresh();
      showErased(result);
      $("h-privacy").focus();
    } catch (problem) { error.textContent = problem.message; error.hidden = false; }
  }

  // -- saying goodbye: every component falls off the bottom of the window, then a thank-you appears -----------------
  const FALL_MS = 850, STAGGER_MS = 70, MAX_STAGGER_MS = 700;
  const FALL_EASING = "cubic-bezier(0.55, 0.06, 0.68, 0.19)";  // slow to start, then faster and faster: it is falling

  function fallingParts() {  // the visible components, from the top of the window down
    const top = (part) => part.getBoundingClientRect();
    return [...document.querySelectorAll("body > header, .left > section, .left > fieldset, .grid > article, .right > section")]
      .filter((part) => part.getClientRects().length)
      .sort((a, b) => top(a).top - top(b).top || top(a).left - top(b).left);
  }

  async function sayGoodbye() {
    const root = document.documentElement;
    document.title = "Goodbye";
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {  // people who asked for less motion skip the fall
      root.classList.add("leaving");
      try { await Promise.all(dropAll()); } catch (_) { /* a fall that cannot play must not keep the goodbye away */ }
    }
    root.classList.add("leaving", "gone");
    const goodbye = $("goodbye");
    goodbye.hidden = false; goodbye.focus();
    announce(goodbye.textContent.replace(/\s+/g, " ").trim());  // what is on screen, so the two can never differ
  }

  function dropAll() {  // starts every component falling; the promises settle when they have all landed below the window
    return fallingParts().map((part, i) => {
      const distance = innerHeight - part.getBoundingClientRect().top + 80;  // far enough to be fully below the window
      const tilt = (i % 2 ? 1 : -1) * (2 + (i % 3) * 2);
      return part.animate(
        [{ transform: "none" }, { transform: `translateY(${distance}px) rotate(${tilt}deg)` }],
        { duration: FALL_MS, delay: Math.min(i * STAGGER_MS, MAX_STAGGER_MS), easing: FALL_EASING, fill: "forwards" },
      ).finished;
    });
  }

  async function quit() {
    if (app.quitting) return;
    const button = $("quit");
    if (!app.quitTimer) {
      button.textContent = "Click again to quit";
      app.quitTimer = setTimeout(() => { button.textContent = "Quit"; app.quitTimer = null; }, 4000);
      return;
    }
    try {
      await post("/api/quit");  // only once the program agrees to stop does anything fall (it refuses while a run is going)
      app.quitting = true;
      await sayGoodbye();
    } catch (error) { notice(error.message, "error"); }
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (app.armed && target !== app.armed.button) disarmDelete();  // pressing anything else cancels a "Sure?"
    if (!target) return;
    if (target.dataset.deleteReport) deleteReport(target);
    else if (target.dataset.action) start(target.dataset.action, optionsFor(target.dataset.action));
    else if (target.dataset.report) showReport(target.dataset.report);
    else if (target.dataset.open) post("/api/open", { target: target.dataset.open }).catch((e) => notice(e.message, "error"));
  });
  $("site-choice").addEventListener("change", chooseSite);
  $("apply-open").addEventListener("click", openApplyDialog);
  $("apply-cancel").addEventListener("click", () => $("apply-dialog").close());
  $("apply-form").addEventListener("submit", submitApply);
  $("stop").addEventListener("click", () => post("/api/stop").then(refresh).catch((e) => notice(e.message, "error")));
  $("quit").addEventListener("click", quit);
  $("erase-list").addEventListener("change", updateEraseButtons);
  $("erase-all").addEventListener("click", toggleAllErase);
  $("erase-open").addEventListener("click", openEraseDialog);
  $("erase-cancel").addEventListener("click", () => $("erase-dialog").close());
  $("erase-form").addEventListener("submit", submitErase);

  restoreSite();
  tick();
})();
