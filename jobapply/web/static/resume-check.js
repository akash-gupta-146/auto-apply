"use strict";
/* Check it: how an applicant tracking system would read the resume you are editing, with the reason for every point lost and a button
   that takes you to the box to fix it. With a job description pasted, also which of the skills it asks for your resume lacks.
   A missing skill is only ever reported: "I have this" is a press by you, for a skill that is true. Everything is shown as TEXT. */
(() => {
  const { $, make, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  const SEVERITY = { error: "Fix this", warn: "Should fix", info: "Could improve" };
  const grade = (score) => (score >= 85 ? "Good" : score >= 65 ? "Fair" : "Needs work");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function words(text) { return text.split(",").map((word) => word.trim()).filter(Boolean); }

  async function check() {
    $("resume-check").disabled = true; $("resume-check-status").textContent = "Checking...";
    try {
      await kit.saveNow();
      const report = await post("/api/resume/check", { resume: state.doc, job: $("resume-job").value, extra: words($("resume-extra").value) });
      kit.emphasise = report.keywords ? report.keywords.required.matched : [];
      render(report);
      $("resume-check-status").textContent = "";
      $("resume-score").focus();
    } catch (error) { $("resume-check-status").textContent = error.message; } finally { $("resume-check").disabled = false; }
  }

  function render(report) {
    $("resume-report").hidden = false;
    $("resume-score").textContent = `${grade(report.score)}: ${report.score} out of 100`;
    announce($("resume-score").textContent);
    $("resume-cats").replaceChildren(...Object.values(report.categories).map(({ label, score }) => {
      const row = make("li", "resume-cat"), bar = make("progress"); bar.max = 100; bar.value = score; bar.setAttribute("aria-label", `${label}: ${score} out of 100`);
      row.append(make("span", "", `${label}: ${score} out of 100`), bar);
      return row;
    }));
    $("resume-fixes").replaceChildren(...(report.checks.length ? report.checks.map(fix) : [make("li", "", "Nothing to fix.")]));
    $("resume-good").replaceChildren(...report.passed.map((text) => make("li", "", text)));
    keywords(report.keywords);
  }

  function fix(check) {
    const row = make("li", "resume-fix");
    row.append(make("strong", "", `${SEVERITY[check.severity]}: `), document.createTextNode(`${check.message} `), make("span", "hint", check.fix));
    const go = make("button", "btn btn-small", "Go to it"); go.type = "button"; go.setAttribute("aria-label", `Go to the place to fix this: ${check.message}`);
    go.addEventListener("click", () => { if (!kit.jump(check.pointer)) $("resume-check-status").textContent = "That place could not be found: it may have been removed."; });
    row.append(" ", go);
    return row;
  }

  function keywords(found) {
    $("resume-keywords").hidden = !found;
    if (!found) return;
    const { required, nice, coverage } = found, total = required.matched.length + required.missing.length;
    $("resume-coverage").textContent = coverage === null ? "The job names no skills this check knows. Add the names of its tools in \"Other words to look for\"."
      : `${required.matched.length} of the ${plural(total, "skill", "skills")} it asks for ${required.matched.length === 1 ? "is" : "are"} in your resume.`;
    $("resume-kw-missing").replaceChildren(...required.missing.map((name) => {
      const row = make("li", "resume-kw", `Not in your resume: ${name} `), have = make("button", "btn btn-small", "I have this");
      have.type = "button"; have.setAttribute("aria-label", `I have this skill: ${name}. Add ${name} to my resume's skills`);
      have.addEventListener("click", () => addSkill(name));
      row.append(have);
      return row;
    }));
    $("resume-kw-have").textContent = [required.matched.length && `In your resume: ${required.matched.join(", ")}.`,
      nice.missing.length && `Preferred, not in your resume (costs you nothing): ${nice.missing.join(", ")}.`].filter(Boolean).join(" ");
    const lines = $("resume-job").value.split("\n").map((line) => line.replace(/^[-*\u2022\s]+/, "").trim());  // a name from the first line that is not a label like "Requirements:"
    const first = lines.find((line) => line && !line.endsWith(":")) || "";
    if (!$("resume-copy-name").value) $("resume-copy-name").value = `Resume for ${first.slice(0, 50)}`.trim();
  }

  async function addSkill(name) {
    try {
      const added = await post("/api/resume/skill", { resume: state.doc, name });
      state.doc.skills = added.skills;
      kit.renderForm(); kit.changed(); announce(`${name} added to your skills.`);
      await check();
    } catch (error) { $("resume-check-status").textContent = error.message; }
  }

  async function copy() {
    const title = $("resume-copy-name").value.trim();
    try {
      await kit.saveNow();
      const made = await post("/api/resume/duplicate", { id: state.id, title });
      $("resume-check-status").textContent = `Saved a copy called "${made.resume.title}". You will find it under all your resumes.`;
      announce($("resume-check-status").textContent);
    } catch (error) { $("resume-check-status").textContent = error.message; }
  }

  $("resume-check").addEventListener("click", check);
  $("resume-copy").addEventListener("click", copy);
  document.addEventListener("resume:opened", () => { kit.emphasise = []; $("resume-copy-name").value = ""; });
})();
