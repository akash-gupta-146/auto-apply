"use strict";
/* Done it, but it is not on your resume: for a skill the job asks for that your resume lacks, you say what you did in your own words. The AI helper (only if you
   ask it) can word that as a bullet and cannot add to it. Nothing goes into your resume until you press a button, and the skill is only added to your skills
   at the same moment. Everything from the server is shown as TEXT. */
(() => {
  const { $, make, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;

  kit.offerEnrich = (missing) => {
    $("resume-enrich").hidden = missing.length === 0;
    $("resume-enrich-list").replaceChildren(...missing.map(item));
  };

  function item(skill) {
    const row = make("li", "resume-enrich-item"), open = make("button", "btn btn-small", "I have done this");
    open.type = "button"; open.setAttribute("aria-label", `I have done this: ${skill}. Say what I did`);
    open.addEventListener("click", () => { open.disabled = true; row.append(form(skill, row, open)); });
    row.append(make("strong", "", `${skill} `), open);
    return row;
  }

  function form(skill, row, opener) {
    const box = make("div", "resume-ai"), id = `resume-enrich-${skill.replace(/[^a-z0-9]/gi, "-")}`;
    const said = make("textarea", "materialize-textarea"), label = make("label", "", `What have you done with ${skill}? Say it in your own words, one or two lines.`);
    said.id = id; said.rows = 3; said.maxLength = 400; label.htmlFor = id;
    const where = make("select", "browser-default"), whereLabel = make("label", "", "Add it as a bullet to"); where.id = `${id}-where`; whereLabel.htmlFor = where.id;
    state.doc.experience.forEach((job, n) => { const option = make("option", "", [job.title, job.company].filter(Boolean).join(", ") || `Job ${n + 1}`); option.value = String(n); where.append(option); });
    const status = make("p", "", ""); status.setAttribute("role", "status");
    const host = make("div");
    const word = make("button", "btn btn-small btn-primary", "Ask the AI helper to word it"), own = make("button", "btn btn-small", "Use my words as they are"), cancel = make("button", "btn btn-small", "Cancel");
    word.type = own.type = cancel.type = "button"; word.disabled = !state.overview.ai;
    const tools = make("div", "controls"); tools.append(word, own, cancel);
    box.append(label, said, whereLabel, where, tools, status, host);
    if (!state.doc.experience.length) { status.textContent = "Add a job in the editor first: the bullet goes under one of your jobs."; word.disabled = own.disabled = true; }
    if (!state.overview.ai) host.append(make("p", "hint", "The AI helper is not set up, so it cannot word this for you. You can still add your own words."));

    const add = async (text) => {
      const wanted = text.replace(/^\s*I\s+/i, "").trim();  // "I moved billing" is a bullet once the "I" is gone
      const bullet = wanted ? wanted[0].toUpperCase() + wanted.slice(1) : "";
      if (!bullet) { status.textContent = "Say what you did first."; return; }
      try {
        const added = await post("/api/resume/skill", { resume: state.doc, name: skill });
        state.doc.skills = added.skills;
        state.doc.experience[Number(where.value)].bullets.push(bullet);
        kit.renderForm(); kit.changed();
        box.remove(); opener.disabled = false; opener.textContent = "Added";
        row.append(make("span", "hint", `Added to your resume: ${skill}, and a bullet under ${where.selectedOptions[0].textContent}.`));
        announce(`Added ${skill} and a bullet to your resume.`);
      } catch (error) { status.textContent = error.message; }
    };
    own.addEventListener("click", () => add(said.value));
    cancel.addEventListener("click", () => { box.remove(); opener.disabled = false; opener.focus(); });
    word.addEventListener("click", async () => {
      if (!said.value.trim()) { status.textContent = "Say what you did first: the AI helper words it, it cannot know it."; return; }
      word.disabled = true; status.textContent = "Asking the AI helper...";
      try {
        const job = state.doc.experience[Number(where.value)] || {};
        const answer = await post("/api/resume/enrich", { said: said.value, skill, title: job.title || "" });
        status.textContent = "";
        kit.showSuggestions(host, said.value, answer, (text) => add(text), `the bullet about ${skill}`);
      } catch (error) { status.textContent = error.message; } finally { word.disabled = false; }
    });
    queueMicrotask(() => said.focus());
    return box;
  }

  document.addEventListener("resume:opened", () => kit.offerEnrich([]));
})();
