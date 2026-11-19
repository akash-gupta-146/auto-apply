"use strict";
/* The resume's text boxes, built from the resume itself: one routine for every section that is a list of entries (jobs, schools, projects,
   certificates, languages, skills), so they all behave alike. Typing changes `kit.state.doc` in place; adding, removing or moving something
   rebuilds the form and puts the focus back where you were. Every box knows its place in the resume (data-pointer, like "/experience/0/title"):
   that is how "Go to it" in the check finds it. */
(() => {
  const { make, announce, $ } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  const MONTH = /^(?:19|20)\d\d-(?:0[1-9]|1[0-2])$/;
  let serial = 0;
  const uid = () => `rf-${++serial}`;
  const MONTH_FIELD = (label, end) => ({ month: true, end, label });

  // Each list section: what one entry is called, its boxes [key, label, options], and where its bullets are kept.
  const SPECS = {
    experience: { noun: "Job", name: (e) => e.title || e.company, boxes: [["title", "Job title"], ["company", "Company"], ["location", "Where"],
      ["start", "Started", MONTH_FIELD("Started", false)], ["end", "Ended", MONTH_FIELD("Ended", true)]], bullets: "bullets", about: "What you did and achieved", ai: true },
    education: { noun: "School", name: (e) => e.school || e.degree, boxes: [["degree", "Degree"], ["field", "Field of study"], ["school", "School or college"],
      ["start", "Started", MONTH_FIELD("Started", false)], ["end", "Ended", MONTH_FIELD("Ended", true)]], bullets: "details", about: "Details (optional)" },
    skills: { noun: "Group of skills", name: (e) => e.group, boxes: [["group", "Group name (optional, like Languages or Tools)"]], list: ["items", "Skills, separated by commas"] },
    projects: { noun: "Project", name: (e) => e.name, boxes: [["name", "Project name"], ["url", "Web address (optional)"]], bullets: "bullets", about: "What it does and what you did" },
    certifications: { noun: "Certificate", name: (e) => e.name, boxes: [["name", "Certificate"], ["issuer", "Given by"], ["date", "Date", MONTH_FIELD("Date", false)]] },
    languages: { noun: "Language", name: (e) => e.name, boxes: [["name", "Language"], ["level", "Level (like Fluent)"]] },
  };
  const HEADINGS = { summary: "Summary", experience: "Experience", education: "Education", skills: "Skills", projects: "Projects", certifications: "Certifications", languages: "Languages" };

  // -- one box -------------------------------------------------------------------------------------
  function box(label, value, onInput, { pointer, area = false, rows = 3, month, hint, max } = {}) {
    const id = uid(), wrap = make("div", "field"), name = make("label", "", label), input = make(area ? "textarea" : "input", area ? "materialize-textarea" : "");  // a textarea needs the class: Materialize styles no bare one
    name.htmlFor = id; input.id = id; input.value = value || ""; input.autocomplete = "off"; input.spellcheck = !month;
    if (area) input.rows = rows; else input.type = "text";
    if (max) input.maxLength = max;
    if (pointer) input.dataset.pointer = pointer;
    wrap.append(name, input);
    const note = month ? make("p", "hint", `Year and month, like 2021-03${month.end ? ", or the word present" : ""}.`) : hint ? make("p", "hint", hint) : null;
    if (note) { note.id = `${id}-note`; input.setAttribute("aria-describedby", note.id); wrap.append(note); }
    input.addEventListener("input", () => {
      onInput(input.value);
      if (month) {
        const text = input.value.trim().toLowerCase(), bad = text !== "" && !MONTH.test(text) && !(month.end && text === "present");
        input.setAttribute("aria-invalid", String(bad));
        note.textContent = bad ? "That is not a date the resume can show: use year-month, like 2021-03." : `Year and month, like 2021-03${month.end ? ", or the word present" : ""}.`;
      }
      kit.changed();
    });
    return wrap;
  }

  function button(text, label, onClick, key, kind = "") {
    const element = make("button", `btn btn-small ${kind}`.trim(), text);
    element.type = "button"; element.setAttribute("aria-label", label);
    if (key) element.dataset.key = key;
    element.addEventListener("click", onClick);
    return element;
  }

  const move = (list, from, by) => { const [item] = list.splice(from, 1); list.splice(from + by, 0, item); };

  /* Rebuild the form, then put the focus on the first of these controls that is there and can be pressed (what you pressed, or where it went:
     the Up button of the top row is switched off, so its Down button is the next best place). */
  function rerender(...keys) {
    renderForm();
    const target = keys.map((key) => document.querySelector(`#resume-form [data-key="${key}"]`)).find((found) => found && !found.disabled);
    if (target) target.focus();
    kit.changed();
  }

  // -- bullets -------------------------------------------------------------------------------------
  function bullets(key, at, entry, field, spec) {
    const list = entry[field], wrap = make("div", "resume-bullets"), here = `${key}.${at}.${field}`;
    wrap.append(make("p", "resume-bullets-title", spec.about));
    list.forEach((text, j) => {
      const row = make("div", "resume-bullet"), where = `${spec.noun.toLowerCase()} ${at + 1}`;
      const input = box(`Bullet ${j + 1}`, text, (value) => { list[j] = value; }, { area: true, rows: 2, pointer: `/${key}/${at}/${field}/${j}`, max: state.overview.choices.limits.bullet });
      input.querySelector("textarea").dataset.key = `${here}.${j}.first`;
      const tools = make("div", "controls");
      if (spec.ai) tools.append(button("Improve with AI", `Improve bullet ${j + 1} of ${where} with the AI helper`, () => kit.suggestBullet(row, input.querySelector("textarea"), entry), `${here}.${j}.ai`));
      tools.append(
        button("Up", `Move bullet ${j + 1} of ${where} up`, () => { move(list, j, -1); rerender(`${here}.${j - 1}.up`, `${here}.${j - 1}.down`); }, `${here}.${j}.up`),
        button("Down", `Move bullet ${j + 1} of ${where} down`, () => { move(list, j, 1); rerender(`${here}.${j + 1}.down`, `${here}.${j + 1}.up`); }, `${here}.${j}.down`),
        button("Remove", `Remove bullet ${j + 1} of ${where}`, () => { list.splice(j, 1); rerender(`${here}.add`); announce("Bullet removed."); }, `${here}.${j}.remove`, "btn-danger"));
      tools.querySelectorAll("button").forEach((b) => { b.disabled = b.dataset.key.endsWith(".up") ? j === 0 : b.dataset.key.endsWith(".down") ? j === list.length - 1 : false; });
      row.append(input, tools);
      wrap.append(row);
    });
    if (list.length < state.overview.choices.limits.bullets) {
      wrap.append(button("Add a bullet", `Add a bullet to ${spec.noun.toLowerCase()} ${at + 1}`, () => { list.push(""); rerender(`${here}.${list.length - 1}.first`); }, `${here}.add`));
    }
    return wrap;
  }

  // -- list sections -------------------------------------------------------------------------------
  function entryBox(key, spec, entry, at, total) {
    const wrap = make("div", "resume-entry"), title = make("h4", "", `${spec.noun} ${at + 1}${spec.name(entry) ? `: ${spec.name(entry)}` : ""}`), id = uid();
    title.id = id; wrap.setAttribute("role", "group"); wrap.setAttribute("aria-labelledby", id); wrap.tabIndex = -1; wrap.dataset.pointer = `/${key}/${at}`;
    wrap.append(title);
    spec.boxes.forEach(([field, label, extra], n) => {
      const made = box(label, entry[field], (value) => { entry[field] = value; }, { pointer: `/${key}/${at}/${field}`, month: extra, max: state.overview.choices.limits.long });
      if (n === 0) made.querySelector("input").dataset.key = `${key}.${at}.first`;
      wrap.append(made);
    });
    if (spec.list) {
      const [field, label] = spec.list;
      wrap.append(box(label, entry[field].join(", "), (value) => { entry[field] = value.split(",").map((item) => item.trim()).filter(Boolean); }, { pointer: `/${key}/${at}/${field}` }));
    }
    if (spec.bullets) wrap.append(bullets(key, at, entry, spec.bullets, spec));
    const tools = make("div", "controls"), name = `${spec.noun.toLowerCase()} ${at + 1}`;
    tools.append(
      button("Move up", `Move ${name} up`, () => { move(state.doc[key], at, -1); rerender(`${key}.${at - 1}.up`, `${key}.${at - 1}.down`); }, `${key}.${at}.up`),
      button("Move down", `Move ${name} down`, () => { move(state.doc[key], at, 1); rerender(`${key}.${at + 1}.down`, `${key}.${at + 1}.up`); }, `${key}.${at}.down`),
      button(`Remove this ${spec.noun.toLowerCase()}`, `Remove ${name}`, () => { state.doc[key].splice(at, 1); rerender(`${key}.add`); announce(`${spec.noun} removed.`); }, `${key}.${at}.remove`, "btn-danger"));
    tools.children[0].disabled = at === 0; tools.children[1].disabled = at === total - 1;
    wrap.append(tools);
    return wrap;
  }

  function listSection(key) {
    const spec = SPECS[key], body = make("div"), entries = state.doc[key];
    entries.forEach((entry, at) => body.append(entryBox(key, spec, entry, at, entries.length)));
    if (entries.length < state.overview.choices.limits.entries) {
      body.append(button(`Add a ${spec.noun.toLowerCase()}`, `Add a ${spec.noun.toLowerCase()}`, () => {
        const blank = { id: "" };
        for (const [field] of spec.boxes) blank[field] = "";
        if (spec.bullets) blank[spec.bullets] = [];
        if (spec.list) blank[spec.list[0]] = [];
        entries.push(blank); rerender(`${key}.${entries.length - 1}.first`);
      }, `${key}.add`));
    }
    return body;
  }

  // -- the other two -------------------------------------------------------------------------------
  function basics() {
    const body = make("div"), b = state.doc.basics;
    for (const [field, label, hint] of [["name", "Your full name"], ["headline", "Headline (the job you want, like Backend Engineer)"], ["email", "Email"], ["phone", "Phone, with the country code"],
                                        ["location", "City and country"]]) {
      body.append(box(label, b[field], (value) => { b[field] = value; }, { pointer: `/basics/${field}`, hint }));
    }
    b.links.forEach((link, at) => {
      const row = make("div", "resume-entry"), id = uid(), title = make("h4", "", `Link ${at + 1}`);
      title.id = id; row.setAttribute("role", "group"); row.setAttribute("aria-labelledby", id);
      row.append(title, box("Name of the link (like GitHub)", link.label, (value) => { link.label = value; }, { pointer: `/basics/links/${at}/label` }),
        box("Web address (starts with https://)", link.url, (value) => { link.url = value; }, { pointer: `/basics/links/${at}/url` }),
        button("Remove this link", `Remove link ${at + 1}`, () => { b.links.splice(at, 1); rerender("basics.links.add"); }, `basics.links.${at}.remove`, "btn-danger"));
      body.append(row);
    });
    if (b.links.length < state.overview.choices.limits.links) body.append(button("Add a link", "Add a link", () => { b.links.push({ label: "", url: "" }); rerender("basics.links.add"); }, "basics.links.add"));
    return body;
  }

  function summary() {
    const body = make("div"), area = box("Two or three sentences on who you are and what you are good at", state.doc.summary, (value) => { state.doc.summary = value; },
      { area: true, rows: 4, pointer: "/summary", max: state.overview.choices.limits.summary });
    body.append(area, button("Suggest a summary with AI", "Suggest a summary with the AI helper", () => kit.suggestSummary(body, area.querySelector("textarea")), "summary.ai"));
    return body;
  }

  // -- the form ------------------------------------------------------------------------------------
  function section(key, body, open) {
    const wrap = make("details", "resume-block"), title = make("summary", "", HEADINGS[key] || "Your details");
    wrap.open = open; wrap.append(title, body);
    if (key !== "summary") wrap.dataset.pointer = `/${key}`;  // the summary's own box has that place: "Go to it" must land in the box, not on the heading above it
    return wrap;
  }

  function renderForm() {
    const parts = [section("basics", basics(), true), section("summary", summary(), true)];
    for (const key of ["experience", "education", "skills", "projects", "certifications", "languages"]) parts.push(section(key, listSection(key), state.doc[key].length > 0 || key === "experience"));
    $("resume-form").replaceChildren(...parts);
    const ai = state.overview.ai;
    $("resume-form").querySelectorAll('[data-key$=".ai"]').forEach((b) => { b.disabled = !ai; });
    $("resume-ai-off").hidden = ai; $("resume-ai-note").hidden = !ai;  // what the AI buttons send matters only when there are AI buttons
  }
  kit.renderForm = renderForm;

  /* "Go to it" in the check: the box at this place in the resume, or the nearest thing that holds it. */
  kit.jump = (pointer) => {
    let place = pointer;
    while (place) {
      const target = document.querySelector(`[data-pointer="${place}"]`);
      if (target) {
        kit.showTab("edit");  // the box is in the Edit part, which may be folded away: a box that is not shown cannot be focused
        for (let up = target.closest("details"); up; up = up.parentElement && up.parentElement.closest("details")) up.open = true;
        const focusable = target.matches("details") ? target.querySelector("summary") : target;
        focusable.focus(); focusable.scrollIntoView({ block: "center" });
        return true;
      }
      place = place.slice(0, place.lastIndexOf("/"));
    }
    return false;
  };
})();
