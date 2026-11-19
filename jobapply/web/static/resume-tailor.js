"use strict";
/* Tailor it to the job: a short list of small changes, each shown as before and after with the reason. You accept the ones that are true of you; they go
   into a NEW copy named for the job, and the resume you are editing does not change. The server checks every change again when you ask for the copy.
   Everything from the server is shown as TEXT. */
(() => {
  const { $, make, check, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  let offered = [];

  const status = (text) => { $("resume-tailor-status").textContent = text; if (text) announce(text); };
  const boxes = () => offered.map((change) => $(`resume-change-${change.id}`));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function fillStrengths() {
    const { strengths } = state.overview.choices, chosen = $("resume-strength").value || "keywords";
    $("resume-strength").replaceChildren(...strengths.map((s) => { const option = make("option", "", s.name); option.value = s.id; return option; }));
    $("resume-strength").value = chosen;
    note();
    const off = !state.overview.ai;
    $("resume-tailor-ai").disabled = off; if (off) $("resume-tailor-ai").checked = false;
    $("resume-tailor-ai-note").textContent = off ? "The AI helper is not set up, so only the rule-based change is offered: the skills the job asks for, put first. Set it up on the AI helper page."
      : "Sends the text of your bullets (no name, contact details or employer names) and the job description to the AI you chose. Without it, the only change offered is putting the skills the job asks for first.";
  }

  function note() { const chosen = state.overview.choices.strengths.find((s) => s.id === $("resume-strength").value); $("resume-strength-note").textContent = chosen ? chosen.about : ""; }

  async function suggest() {
    const job = kit.job();
    if (!job.text.trim()) return status("Give the job first, in the ATS match tab: paste its description, or read it from its web address.");
    $("resume-tailor-go").disabled = true; status("Looking for changes that suit the job...");
    try {
      await kit.saveNow();  // the changes are made to the resume as it is now
      const found = await post("/api/resume/tailor", { resume: state.doc, job: job.text, title: job.title, extra: kit.extraWords(), strength: $("resume-strength").value, ai: $("resume-tailor-ai").checked });
      render(found, job);
      status("");
      $("resume-tailor-title").focus();
    } catch (error) { status(error.message); } finally { $("resume-tailor-go").disabled = false; }
  }

  function item(change) {
    const row = make("li", "resume-change"), box = make("input"), head = make("div", "resume-change-head");
    box.type = "checkbox"; box.id = `resume-change-${change.id}`;
    box.addEventListener("change", count);
    head.append(check(box, `Accept: ${change.label}`));
    row.append(head);
    if (change.action === "replace") row.append(kit.difference(change.original, change.value));
    else if (change.action === "append") { const added = make("p", "diff"); added.append("New bullet: ", make("ins", "", change.value)); row.append(added); }
    else row.append(make("p", "hint", `Now: ${change.original.join(", ")}`), make("p", "", `After: ${change.value.join(", ")}`));
    row.append(make("p", "hint", change.reason ? `Why: ${change.reason}` : "Why: it suits the job."));
    return row;
  }

  function render(found, job) {
    offered = found.changes;
    $("resume-tailor-out").hidden = false; $("resume-tailor-done").replaceChildren();
    $("resume-tailor-title").textContent = offered.length ? `${plural(offered.length, "change", "changes")} to look at` : "Nothing to change";
    $("resume-tailor-notes").textContent = [found.notes, found.ai_note, !offered.length && "Your resume already suits this job as far as these checks can tell. You can try a fuller strength.",
      found.ai && "From the AI helper and the rules, checked against your resume. Accept only what is true of you."].filter(Boolean).join(" ");
    $("resume-tailor-list").replaceChildren(...offered.map(item));
    const n = found.refused_count;
    $("resume-tailor-refused").textContent = n ? `${plural(n, "suggestion was", "suggestions were")} thrown away because ${n === 1 ? "it" : "they"} would have added something your resume does not say, or did not fit. `
      + found.refused.map((r) => r.why).join("; ") + "." : "";
    $("resume-tailor-name").value = ""; $("resume-tailor-name").placeholder = job.title ? `Tailored: ${job.title}${job.company ? ` at ${job.company}` : ""}` : "Tailored copy";
    $("resume-tailor-all").disabled = $("resume-tailor-none").disabled = !offered.length;
    count();
  }

  function count() {
    const n = boxes().filter((box) => box.checked).length;
    $("resume-tailor-apply").disabled = n === 0;
    $("resume-tailor-apply").textContent = n ? `Make a copy with ${plural(n, "accepted change", "accepted changes")}` : "Make a copy with the accepted changes";
  }

  function acceptAll(on) { boxes().forEach((box) => { box.checked = on; }); count(); announce(on ? "All accepted." : "None accepted."); }

  async function apply() {
    const accepted = offered.filter((change) => $(`resume-change-${change.id}`).checked), job = kit.job();
    $("resume-tailor-apply").disabled = true; $("resume-tailor-done").textContent = "Making the copy...";
    try {
      await kit.saveNow();
      const made = await post("/api/resume/tailor/apply", { id: state.id, title: $("resume-tailor-name").value.trim(), job: { title: job.title, company: job.company, url: job.url },
        changes: accepted.map(({ path, action, original, value, reason }) => ({ path, action, original, value, reason })) });
      const open = make("button", "btn btn-small", "Open the new copy"); open.type = "button"; open.addEventListener("click", () => kit.open(made.resume.id));
      $("resume-tailor-done").replaceChildren(`Made "${made.resume.title}" with ${plural(made.applied, "change", "changes")}${made.skipped ? ` (${plural(made.skipped, "change", "changes")} no longer fit and ${made.skipped === 1 ? "was" : "were"} left out)` : ""}. This resume is as it was. `, open);
      announce(`Made ${made.resume.title}.`);
    } catch (error) { $("resume-tailor-done").textContent = error.message; count(); }
  }

  $("resume-strength").addEventListener("change", note);
  $("resume-tailor-go").addEventListener("click", suggest);
  $("resume-tailor-all").addEventListener("click", () => acceptAll(true));
  $("resume-tailor-none").addEventListener("click", () => acceptAll(false));
  $("resume-tailor-apply").addEventListener("click", apply);
  document.addEventListener("resume:opened", () => { offered = []; $("resume-tailor-out").hidden = true; status(""); fillStrengths(); });
})();
