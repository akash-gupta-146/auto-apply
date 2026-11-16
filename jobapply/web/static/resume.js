"use strict";
/* The Resume tab: your resumes, the frame of the editor (name, look, sections), saving, and the preview.
   Everything from the server is shown as TEXT, never as HTML. The resume you are editing lives in `kit.state.doc`; the text boxes
   (resume-form.js) change it in place and say so with kit.changed(), and it is saved a moment after you stop typing. */
(() => {
  const { $, api, post, make, announce } = window.PanelKit;
  const AUTOSAVE_MS = 700, SURE_FOR_MS = 4000;
  const ACCENTS = [["#1f4e8c", "Blue"], ["#1e6b46", "Green"], ["#8a2b2b", "Red"], ["#5b3a8c", "Purple"], ["#2b2b2b", "Charcoal"], ["#0f6b7a", "Teal"]];
  const state = { id: null, doc: null, pages: 0, overview: null, timer: null, saving: false, again: false, locked: false, dirty: false, armed: null };
  const kit = window.ResumeKit = { state, ACCENTS, changed, saveNow, say };  // resume-form.js adds renderForm; resume-ai.js and resume-check.js add theirs
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function say(text) { $("resume-status").textContent = text; if (text) announce(text); }
  const templateName = (id) => ((state.overview.templates.find((t) => t.id === id)) || { name: id }).name;
  const fail = (error) => say(error.message || "Something went wrong.");

  // -- the list ------------------------------------------------------------------------------------
  async function loadOverview() {
    try { state.overview = await api("/api/resume/list"); } catch (error) { return fail(error); }
    renderList();
    fillChoices();
  }

  function renderList() {
    const { resumes, uploaded, has_profile: hasProfile } = state.overview;
    $("resume-empty").hidden = resumes.length > 0;
    $("resume-list").replaceChildren(...resumes.map(card));
    $("resume-new-upload").disabled = !uploaded;
    $("resume-upload-hint").textContent = uploaded ? `Reads ${uploaded}, the resume your runs send now, into a draft for you to check.`
      : hasProfile ? "Save a resume on the Profile tab to start from it." : "Save your details and a resume on the Profile tab to start from them.";
  }

  function card(item) {
    const row = make("li", "resume-card"), when = item.updated ? new Date(item.updated).toLocaleString() : "";
    const open = make("button", "btn btn-small btn-primary", "Open");
    open.type = "button"; open.setAttribute("aria-label", `Open ${item.title}`);
    open.addEventListener("click", () => openResume(item.id));
    const copy = make("button", "btn btn-small", "Copy");
    copy.type = "button"; copy.setAttribute("aria-label", `Make a copy of ${item.title}`);
    copy.addEventListener("click", () => duplicate(item.id, ""));
    const del = make("button", "btn btn-small btn-danger", "Delete");
    del.type = "button"; del.setAttribute("aria-label", `Delete ${item.title}`);
    del.addEventListener("click", () => remove(item, del));
    const buttons = make("div", "controls"); buttons.append(open, copy, del);
    row.append(make("h3", "", item.title), make("p", "hint", [item.name || "No name yet", templateName(item.template), when && `edited ${when}`].filter(Boolean).join(" · ")), buttons);
    return row;
  }

  async function create(mode) {
    try {
      const made = await post("/api/resume/new", { mode });
      say(mode === "upload" ? "Read your resume into a draft. Check each part below." : "Started a new resume.");
      await openResume(made.resume.id, made.notes);
    } catch (error) { fail(error); }
  }

  async function duplicate(id, title) {
    try { await post("/api/resume/duplicate", { id, title }); await loadOverview(); say("Made a copy."); } catch (error) { fail(error); }
  }

  async function remove(item, button) {  // two presses, the second within a few seconds: a delete is for good
    if (!state.armed || state.armed.id !== item.id) {
      clearTimeout(state.armed && state.armed.timer);
      button.textContent = "Press again to delete";
      state.armed = { id: item.id, timer: setTimeout(() => { button.textContent = "Delete"; state.armed = null; }, SURE_FOR_MS) };
      return announce(`Press Delete again within a few seconds to delete ${item.title} for good.`);
    }
    clearTimeout(state.armed.timer); state.armed = null;
    try { await post("/api/resume/delete", { id: item.id }); await loadOverview(); say(`Deleted ${item.title}.`); } catch (error) { fail(error); }
  }

  // -- opening one ---------------------------------------------------------------------------------
  async function openResume(id, notes = []) {
    try {
      const data = await api(`/api/resume/get?id=${encodeURIComponent(id)}`);
      Object.assign(state, { id, doc: data.resume, pages: data.pages, locked: false, dirty: false });
    } catch (error) { return fail(error); }
    $("resume-list-card").hidden = true; $("resume-open").hidden = false; $("resume-conflict").hidden = true;
    $("resume-notes-list").replaceChildren(...notes.map((text) => make("li", "", text)));
    $("resume-notes").hidden = notes.length === 0;
    $("resume-job").value = ""; $("resume-extra").value = ""; $("resume-report").hidden = true; $("resume-check-status").textContent = "";
    $("resume-use-sure").checked = false; $("resume-use").disabled = true; $("resume-use-status").textContent = "";
    $("resume-use-now").textContent = state.overview.uploaded ? `Your runs now send: ${state.overview.uploaded}.` : "No resume is saved for your runs yet.";
    fillFrame(); kit.renderForm(); refreshPreview(); setSaved("Saved");
    document.dispatchEvent(new CustomEvent("resume:opened"));  // resume-check.js clears what it showed about the last one
    $("h-resume-edit").focus();
  }

  async function closeResume() {
    await saveNow();
    $("resume-open").hidden = true; $("resume-list-card").hidden = false;
    Object.assign(state, { id: null, doc: null });
    await loadOverview();
    $("h-resume").focus();
  }

  // -- the frame of the editor: name, look, sections -----------------------------------------------
  function options(select, items, chosen) {  // items: [[value, label]]
    select.replaceChildren(...items.map(([value, label]) => { const option = make("option", "", label); option.value = String(value); return option; }));
    select.value = String(chosen);
  }

  function fillChoices() {
    const { choices, templates } = state.overview;
    options($("resume-template"), templates.map((t) => [t.id, t.ats_safe ? t.name : `${t.name}: less safe for applications`]), state.doc ? state.doc.template : "classic");
    options($("resume-font"), choices.fonts.map((f) => [f, f === "sans" ? "Sans-serif (plain)" : "Serif (classic)"]), state.doc ? state.doc.theme.font : "sans");
    options($("resume-size"), choices.sizes.map((s) => [s, `${s} pt`]), state.doc ? state.doc.theme.size : 10.5);
    options($("resume-accent"), ACCENTS, state.doc ? state.doc.theme.accent : ACCENTS[0][0]);
    options($("resume-spacing"), choices.spacings.map((s) => [s, s[0].toUpperCase() + s.slice(1)]), state.doc ? state.doc.theme.spacing : "normal");
    options($("resume-page"), choices.pages.map((p) => [p, p === "A4" ? "A4 (most countries)" : "Letter (US, Canada)"]), state.doc ? state.doc.theme.page : "A4");
  }

  function fillFrame() {
    fillChoices();
    const { doc } = state;
    if (![...$("resume-accent").options].some((o) => o.value === doc.theme.accent)) {  // an accent set some other way: kept, and shown by its code
      const own = make("option", "", `Your own (${doc.theme.accent})`); own.value = doc.theme.accent; $("resume-accent").append(own);
      $("resume-accent").value = doc.theme.accent;
    }
    $("resume-title").value = doc.title;
    noteTemplate();
    renderSections();
  }

  function noteTemplate() {
    const chosen = state.overview.templates.find((t) => t.id === state.doc.template);
    $("resume-template-note").textContent = chosen.ats_safe ? chosen.about : `Less safe for applications. ${chosen.about}`;
  }

  function wireControls() {
    $("resume-title").addEventListener("input", () => { state.doc.title = $("resume-title").value; changed(); });
    $("resume-template").addEventListener("change", () => { state.doc.template = $("resume-template").value; noteTemplate(); changed(); });
    for (const [id, key, number] of [["font", "font"], ["size", "size", true], ["accent", "accent"], ["spacing", "spacing"], ["page", "page"]]) {
      $(`resume-${id}`).addEventListener("change", () => { const value = $(`resume-${id}`).value; state.doc.theme[key] = number ? Number(value) : value; fitPreview(); changed(); });
    }
  }

  function renderSections() {
    const { doc } = state, headings = Object.fromEntries(state.overview.choices.sections.map((s) => [s.id, s.heading]));
    $("resume-sections").replaceChildren(...doc.order.map((key, at) => {
      const row = make("li", "resume-section-row"), name = headings[key], shown = !doc.hidden.includes(key);
      const box = make("input"); box.type = "checkbox"; box.id = `resume-show-${key}`; box.checked = shown; box.dataset.key = `section.${key}.show`;
      const label = make("label", "", `Show ${name}`); label.htmlFor = box.id;
      box.addEventListener("change", () => {
        doc.hidden = box.checked ? doc.hidden.filter((k) => k !== key) : [...doc.hidden, key];
        changed(); announce(`${name} ${box.checked ? "will be shown" : "is hidden"}.`);
      });
      const move = (by, word) => {
        const button = make("button", "btn btn-small", word); button.type = "button"; button.dataset.key = `section.${key}.${word.toLowerCase()}`;
        button.setAttribute("aria-label", `Move ${name} ${word.toLowerCase()}`);
        button.disabled = at + by < 0 || at + by >= doc.order.length;
        button.addEventListener("click", () => {
          const order = doc.order.slice(); [order[at], order[at + by]] = [order[at + by], order[at]]; doc.order = order;
          changed(); renderSections(); announce(`${name} moved ${word.toLowerCase()}.`);
          const here = (name) => document.querySelector(`[data-key="section.${key}.${name}"]`);  // the same button again, or its other half when this one is now switched off
          [here(word.toLowerCase()), here(word === "Up" ? "down" : "up"), here("show")].find((control) => control && !control.disabled).focus();
        });
        return button;
      };
      const check = make("div", "check"); check.append(box, label);
      row.append(check, move(-1, "Up"), move(1, "Down"));
      return row;
    }));
  }

  // -- saving and the preview ----------------------------------------------------------------------
  function setSaved(text) { $("resume-saved").textContent = text; }

  function changed() {
    if (state.locked) return;
    state.dirty = true; setSaved("Changes not saved yet");
    clearTimeout(state.timer);
    state.timer = setTimeout(save, AUTOSAVE_MS);
  }

  async function save() {
    if (!state.id || !state.dirty || state.locked) return;
    if (state.saving) { state.again = true; return; }
    state.saving = true; state.dirty = false; setSaved("Saving...");
    try {
      const sent = await post("/api/resume/save", { id: state.id, version: state.doc.version, resume: state.doc });
      state.doc.version = sent.resume.version; state.doc.updated = sent.resume.updated; state.pages = sent.pages;
      setSaved(`Saved at ${new Date().toLocaleTimeString()}`); refreshPreview();
    } catch (error) {
      state.dirty = true;
      if (/changed somewhere else/.test(error.message)) {
        state.locked = true; $("resume-conflict-text").textContent = error.message; $("resume-conflict").hidden = false; setSaved("Not saved");
      } else { setSaved(`Could not save: ${error.message}`); }
    } finally {
      state.saving = false;
      if (state.again) { state.again = false; save(); }
    }
  }

  async function saveNow() {
    clearTimeout(state.timer);
    await save();
    while (state.saving) await new Promise((resolve) => setTimeout(resolve, 50));
  }

  /* The preview is the whole page, at its real width, shrunk to fit the column: a page cut off at the edge would hide what the PDF says. */
  const PAGE_PX = { A4: 794, Letter: 816 };  // 210 mm and 8.5 in, in CSS pixels
  function fitPreview() {
    const wrap = $("resume-preview-wrap"), frame = $("resume-preview");
    if (!state.doc || !wrap.clientWidth) return;
    const width = PAGE_PX[state.doc.theme.page] || PAGE_PX.A4, scale = Math.min(1, wrap.clientWidth / width);
    frame.style.width = `${width}px`;
    frame.style.height = `${wrap.clientHeight / scale}px`;
    frame.style.transform = `scale(${scale})`;
  }
  new ResizeObserver(fitPreview).observe($("resume-preview-wrap"));

  function refreshPreview() {
    fitPreview();
    const id = encodeURIComponent(state.id);
    $("resume-preview").src = `/resume/preview?id=${id}&v=${state.doc.version}`;
    $("resume-download").href = `/resume/export.pdf?id=${id}`;
    const pages = state.pages;
    $("resume-pages").textContent = `About ${plural(pages, "page", "pages")} (an estimate: the PDF has the exact count).` + (pages > 2 ? " Two pages is as much as most recruiters read." : "");
  }

  // -- using it ------------------------------------------------------------------------------------
  async function use() {
    $("resume-use").disabled = true; $("resume-use-status").textContent = "Printing your resume...";
    try {
      await saveNow();
      const done = await post("/api/resume/use", { id: state.id, confirm: true });
      const added = done.added.length ? ` Added to your profile with no years: ${done.added.join(", ")}.` : "";
      $("resume-use-status").textContent = `Done. ${done.file} (${plural(done.pages, "page", "pages")}) is now the resume your runs send.${added}`;
      announce($("resume-use-status").textContent);
      $("resume-use-sure").checked = false;
      state.overview.uploaded = done.file; $("resume-use-now").textContent = `Your runs now send: ${done.file}.`;
    } catch (error) { $("resume-use-status").textContent = error.message; $("resume-use").disabled = !$("resume-use-sure").checked; }
  }

  // -- wiring --------------------------------------------------------------------------------------
  $("resume-new-blank").addEventListener("click", () => create("blank"));
  $("resume-new-profile").addEventListener("click", () => create("profile"));
  $("resume-new-upload").addEventListener("click", () => create("upload"));
  $("resume-back").addEventListener("click", closeResume);
  $("resume-reload").addEventListener("click", () => openResume(state.id));
  $("resume-use-sure").addEventListener("change", () => { $("resume-use").disabled = !$("resume-use-sure").checked; });
  $("resume-use").addEventListener("click", use);
  wireControls();
  document.addEventListener("visibilitychange", () => { if (document.hidden) saveNow(); });  // leaving the tab or the page: nothing typed is lost
  window.addEventListener("pagehide", () => { if (state.dirty) save(); });
  new MutationObserver(() => { if (!$("panel-resume").hidden && !state.id) loadOverview(); }).observe($("panel-resume"), { attributes: true, attributeFilter: ["hidden"] });  // opening the tab shows what is there now
  loadOverview();
})();
