"use strict";
/* Match it to a job: the job (pasted, read from a web address, or read from the page open in your browser) and how your resume lines up with it.
   The match is the words of your resume against the words of the job, as a band with the evidence for each part: never a percentage and never a prediction.
   What was read from a page goes into the box for you to read and trim. Everything from the server is shown as TEXT. */
(() => {
  const { $, make, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  const FACTOR = { ok: "Good", warn: "Partly", bad: "Weak", unknown: "Not enough to say" };
  const STATUS = { supported: "Shown in your resume", partly: "Partly shown", none: "Not found in your resume" };
  const KIND = { required: "Asked for", nice: "Preferred" };
  let company = "";  // of the job last read: kept for the copy that tailoring makes

  kit.extraWords = () => $("resume-extra").value.split(",").map((word) => word.trim()).filter(Boolean);
  kit.job = () => ({ text: $("resume-job").value, title: $("resume-job-title").value.trim(), company, url: $("resume-job-url").value.trim() });
  const status = (text) => { $("resume-job-status").textContent = text; if (text) announce(text); };

  async function read(how) {
    const url = $("resume-job-url").value.trim(), button = $(how === "link" ? "resume-job-fetch" : "resume-job-browser");
    if (how === "link" && !url) return status("Type the web address of the job first.");
    button.disabled = true; status(how === "link" ? "Reading the page..." : "Reading the page open in your browser...");
    try {
      const job = await post("/api/resume/job", { how, url });
      $("resume-job").value = job.text;
      if (job.title && !$("resume-job-title").value) $("resume-job-title").value = job.title;
      if (job.url && !$("resume-job-url").value) $("resume-job-url").value = job.url;  // the page open in the browser: its address
      company = job.company || company;
      status([job.note, `Read ${job.text.length} characters${company ? ` for ${company}` : ""}. Check that it is the whole description.`].filter(Boolean).join(" "));
      $("resume-job").focus();
    } catch (error) { status(error.message); } finally { button.disabled = false; }
  }

  async function match() {
    const job = kit.job();
    if (!job.text.trim()) { $("resume-match-status").textContent = "Give the job first: paste its description, or read it from its web address."; return; }
    $("resume-match").disabled = true; $("resume-match-status").textContent = "Comparing...";
    try {
      await kit.saveNow();
      const found = await post("/api/resume/match", { resume: state.doc, job: job.text, title: job.title, extra: kit.extraWords() });
      kit.emphasise = found.skills.required.matched;
      render(found);
      $("resume-match-status").textContent = "";
      $("resume-match-band").focus();
    } catch (error) { $("resume-match-status").textContent = error.message; } finally { $("resume-match").disabled = false; }
  }

  function bar(label, text, share) {
    const row = make("li", "resume-cat");
    row.append(make("span", "", text));
    if (share !== null) { const meter = make("progress"); meter.max = 100; meter.value = Math.round(share * 100); meter.setAttribute("aria-label", label); row.append(meter); }
    return row;
  }

  function evidence(item) {
    const row = make("li", "resume-fix");
    row.append(make("strong", "", `${KIND[item.kind] || item.kind}: `), document.createTextNode(`${item.text}. `), make("span", "", `${STATUS[item.status]}. `));
    if (item.quote) row.append(make("span", "hint", `Your resume says: "${item.quote}" `));
    if (item.status !== "supported") row.append(make("span", "hint", item.reason));
    if (item.pointer) {
      const go = make("button", "btn btn-small", "Go to it"); go.type = "button"; go.setAttribute("aria-label", `Go to the place in your resume that shows: ${item.text}`);
      go.addEventListener("click", () => { if (!kit.jump(item.pointer)) $("resume-match-status").textContent = "That place could not be found: it may have been removed."; });
      row.append(" ", go);
    }
    return row;
  }

  function render(found) {
    $("resume-match-out").hidden = false;
    $("resume-match-band").textContent = found.label;
    announce(found.label);
    const { job, your_years: years } = found;
    $("resume-match-job").textContent = [job.title && `The job: ${job.title}`, job.seniority && `level: ${job.seniority}`, job.years && `asks for ${job.years}+ years`,
      years && `your dated jobs add up to about ${years} years`].filter(Boolean).join(" · ");
    $("resume-match-notice").textContent = found.notice;
    const { required, nice } = found.skills;
    $("resume-match-skills").textContent = [required.matched.length && `Skills it asks for that are in your resume: ${required.matched.join(", ")}.`,
      required.missing.length && `Skills it asks for that are not: ${required.missing.join(", ")}.`,
      nice.missing.length && `Preferred, not in your resume (costs you nothing): ${nice.missing.join(", ")}.`].filter(Boolean).join(" ")
      || "The job names no skills this check knows. Add the names of its tools in \"Other words to look for\".";
    $("resume-match-factors").replaceChildren(...found.factors.map((f) => bar(`${f.label}: ${FACTOR[f.state]}`, `${f.label}: ${FACTOR[f.state]}. ${f.detail}`, f.share)));
    kit.offerEnrich(required.missing);
    $("resume-match-evidence").replaceChildren(...(found.evidence.length ? found.evidence.map(evidence) : [make("li", "", "The job lists no requirements this check could pick out. Paste the requirements section.")]));
    $("resume-match-terms").replaceChildren(...(found.terms.length ? found.terms.map((t) => make("li", "", `${t.term}: used ${t.count} times; ${t.in_resume ? "in your resume" : "not in your resume"}`))
      : [make("li", "", "No repeated words stand out.")]));
  }

  $("resume-job-fetch").addEventListener("click", () => read("link"));
  $("resume-job-browser").addEventListener("click", () => read("browser"));
  $("resume-match").addEventListener("click", match);
  document.addEventListener("resume:opened", () => {  // a copy made for a job remembers it: its title and address are put back, not its text
    const made = state.doc.job || {};
    company = made.company || "";
    $("resume-job-title").value = made.title || ""; $("resume-job-url").value = made.url || "";
    $("resume-match-out").hidden = true; $("resume-match-status").textContent = ""; status("");
  });
})();
