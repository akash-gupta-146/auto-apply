"use strict";
/* The ATS check: one plain answer to "is this resume ATS-friendly?" (an ATS is the software that reads a resume before a person does). For a resume made here it
   prints the PDF, reads it back the way a parser does, checks what you wrote, and says ATS-friendly, mostly, or not yet, with the first things to fix. The same
   answer for the resume your runs send, and for any PDF or Word file you choose: those are read here and not kept. The word is always in the answer, never
   colour alone. Everything from the server is shown as TEXT. */
(() => {
  const { $, make, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  const MAX_FILE = 8 * 1024 * 1024;  // the server's limit: said here first, so a big file is not sent only to be refused
  let last = null;  // what the last ATS check of the open resume said: {key, stale}

  /* The answer as a box: the word and a mark, what to do first, how much more there is, the parts, and what the answer is not. */
  function verdictBox(found) {
    const box = make("div", "resume-verdict"), title = make("h3", "", ""), mark = make("span", "", kit.MARKS[found.key]);
    box.dataset.key = found.key; title.tabIndex = -1; mark.setAttribute("aria-hidden", "true");
    title.append(mark, ` ${found.label}`);
    box.append(title, make("p", "", found.summary));
    if (found.reasons.length) {
      const list = make("ul", "resume-fixes"); list.append(...found.reasons.map((reason) => kit.findingRow(reason)));
      box.append(make("p", "", "Fix these first:"), list);
    }
    if (found.more) box.append(make("p", "hint", `${found.more} more ${found.more === 1 ? "thing is" : "things are"} in the details.`));
    box.append(make("p", "hint", found.parts.map((part) => `${part.label}: ${part.score} out of 100`).join(" · ")), make("p", "hint", found.notice));
    return { box, title };
  }

  // -- the resume you are editing ------------------------------------------------------------------
  function setChip(ats) { last = ats; $("resume-ats-chip").replaceChildren(kit.atsChip(ats)); }

  async function runFull() {
    $("resume-ats-run").disabled = true; $("resume-check-status").textContent = "Printing the PDF and reading it back...";
    try {
      await kit.saveNow();  // the answer is about the saved resume, and so is the PDF
      const got = await post("/api/resume/ats", { id: state.id });
      kit.showDataReport(got.data); kit.showPdfReport(got.pdf);  // the details underneath
      const { box, title } = verdictBox(got.verdict);
      $("resume-ats-verdict").replaceChildren(box); $("resume-ats-verdict").hidden = false;
      setChip({ key: got.verdict.key, stale: false });
      $("resume-check-status").textContent = "";
      announce(`${got.verdict.label}. ${got.verdict.summary}`);
      title.focus();
    } catch (error) { $("resume-check-status").textContent = error.message; } finally { $("resume-ats-run").disabled = false; }
  }

  // -- the list ------------------------------------------------------------------------------------
  kit.checkOne = async (item, row, button) => {  // a resume in the list, without opening it
    button.disabled = true; kit.say(`Checking ${item.title}...`);
    try {
      const got = await post("/api/resume/ats", { id: item.id });
      row.querySelector(".resume-chip").replaceWith(kit.atsChip({ key: got.verdict.key, stale: false }));
      kit.say(`${item.title}: ${got.verdict.label}. ${got.verdict.summary}`);
    } catch (error) { kit.say(error.message); } finally { button.disabled = false; }
  };

  // -- a resume you already have -------------------------------------------------------------------
  function showFile(got) {
    const { box, title } = verdictBox(got.verdict), report = got.report;
    const details = make("details", "resume-block"), found = [...report.findings, ...report.tips], text = make("pre");
    details.append(make("summary", "", "Details: what was found, and the text a parser reads from it"), make("ul", "resume-cats"));
    details.querySelector("ul").append(...kit.bars(report.categories));
    const list = make("ul", "resume-fixes"); list.append(...(found.length ? found.map((finding) => kit.findingRow(finding)) : [make("li", "", "Nothing to fix: a parser reads this file cleanly.")]));
    text.tabIndex = 0; text.textContent = report.text; text.setAttribute("aria-label", "The text read from the file");
    details.append(list, text);
    $("resume-file-out").replaceChildren(make("p", "hint", `Checked: ${got.file} (${got.kind === "pdf" ? "a PDF" : "a Word file"}). It was read here and not kept.`), box, details);
    $("resume-file-out").hidden = false;
    announce(`${got.verdict.label}. ${got.verdict.summary}`);
    title.focus();
  }

  async function checkFile(button, status, ask) {
    button.disabled = true; status.textContent = "Reading the file...";
    try { showFile(await ask()); status.textContent = ""; } catch (error) { status.textContent = error.message; } finally { button.disabled = false; }
  }

  async function base64Of(file) {  // in pieces: one call with a whole file's characters is more than a browser will take
    const bytes = new Uint8Array(await file.arrayBuffer()), pieces = [];
    for (let at = 0; at < bytes.length; at += 0x8000) pieces.push(String.fromCharCode(...bytes.subarray(at, at + 0x8000)));
    return btoa(pieces.join(""));
  }

  $("resume-file-current").addEventListener("click", () => checkFile($("resume-file-current"), $("resume-file-status"), () => post("/api/resume/atscurrent", {})));
  $("resume-file-pick").addEventListener("change", () => { $("resume-file-go").disabled = !$("resume-file-pick").files.length; });
  $("resume-file-go").addEventListener("click", () => {
    const file = $("resume-file-pick").files[0];
    if (!file) return;
    if (file.size > MAX_FILE) { $("resume-file-status").textContent = "That file is too big to check: a resume is a few hundred kilobytes."; return; }
    checkFile($("resume-file-go"), $("resume-file-status"), async () => post("/api/resume/atsfile", { name: file.name, data: await base64Of(file) }));
  });

  $("resume-ats-run").addEventListener("click", runFull);
  document.addEventListener("resume:edited", () => { if (last && !last.stale) setChip({ ...last, stale: true }); });
  document.addEventListener("resume:opened", () => {
    const known = state.overview.resumes.find((item) => item.id === state.id);
    setChip(known && known.ats ? known.ats : null);
    $("resume-ats-verdict").hidden = true; $("resume-ats-verdict").replaceChildren();
  });
})();
