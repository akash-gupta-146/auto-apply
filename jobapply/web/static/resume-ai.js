"use strict";
/* AI suggestions: shown beside what you wrote, as the difference between the two, and nothing changes until you press "Use this".
   The server has already thrown away any suggestion that adds a number, a tool or a name that is not in your resume; what is left can
   still be wrong about YOU, so it says so. Everything is shown as TEXT. */
(() => {
  const { make, post, announce } = window.PanelKit;
  const kit = window.ResumeKit, { state } = kit;
  kit.emphasise = [];  // the skills the job asks for that your resume already has: set by the check, offered to the AI as words it may stress

  /* The words of `before` and `after`, with what was taken out crossed out and what was put in underlined (shape as well as colour). */
  function difference(before, after) {
    const x = before.split(/\s+/).filter(Boolean), y = after.split(/\s+/).filter(Boolean);
    const table = Array.from({ length: x.length + 1 }, () => new Array(y.length + 1).fill(0));
    for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) table[i][j] = x[i] === y[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    const out = make("p", "diff");
    const put = (node) => out.append(node, " ");
    let i = 0, j = 0;
    while (i < x.length || j < y.length) {
      if (i < x.length && j < y.length && x[i] === y[j]) { put(document.createTextNode(x[i])); i++; j++; }
      else if (j < y.length && (i === x.length || table[i][j + 1] >= table[i + 1][j])) { put(make("ins", "", y[j])); j++; }
      else { put(make("del", "", x[i])); i++; }
    }
    return out;
  }

  function show(host, current, answer, apply, what) {
    host.replaceChildren();
    host.append(make("h4", "", "Suggestions from the AI helper"), make("p", "hint", "Crossed-out words come out, underlined words go in. Use one only if it is true of you."));
    if (!answer.options.length) host.append(make("p", "", "The AI gave nothing safe to use this time. Try again, or write it yourself."));
    answer.options.forEach((text, n) => {
      const item = make("div", "resume-suggestion"), use = make("button", "btn btn-small btn-primary", "Use this"), no = make("button", "btn btn-small", "Not this one");
      use.type = no.type = "button";
      use.setAttribute("aria-label", `Use suggestion ${n + 1} for ${what}`); no.setAttribute("aria-label", `Do not use suggestion ${n + 1} for ${what}`);
      use.addEventListener("click", () => { apply(text); host.replaceChildren(); announce(/\[[^\]]+\]/.test(text) ? "Used. It has a blank to fill in: put in the real figure." : "Suggestion used."); });
      no.addEventListener("click", () => { item.remove(); if (!host.querySelector(".resume-suggestion")) host.replaceChildren(); announce("Suggestion dismissed."); });
      const tools = make("div", "controls"); tools.append(use, no);
      item.append(difference(current, text), tools);
      if (/\[[^\]]+\]/.test(text)) item.append(make("p", "hint", "It has a blank like [X%]: fill in the real figure after you use it, or take the blank out. The check reminds you."));
      host.append(item);
    });
    if (answer.dropped) host.append(make("p", "hint", `${answer.dropped} other suggestion${answer.dropped === 1 ? " was" : "s were"} thrown away because ${answer.dropped === 1 ? "it" : "they"} added a number, tool or name that is not in your resume.`));
    const close = make("button", "btn btn-small", "Close the suggestions"); close.type = "button"; close.addEventListener("click", () => host.replaceChildren());
    host.append(close);
  }

  async function ask(after, kind, extra, textarea, what) {
    let host = [...after.parentElement.children].find((child) => child.classList.contains("resume-ai") && child.dataset.for === what);  // not a selector: a title may hold quotes
    if (!host) { host = make("div", "resume-ai"); host.dataset.for = what; host.setAttribute("role", "region"); host.setAttribute("aria-label", `AI suggestions for ${what}`); after.after(host); }
    host.replaceChildren(make("p", "", "Asking the AI helper..."));
    host.setAttribute("aria-busy", "true");
    try {
      await kit.saveNow();  // the suggestions are made from the resume as it is now
      const answer = await post("/api/resume/suggest", { kind, resume: state.doc, ...extra });
      show(host, textarea.value, answer, (text) => { textarea.value = text; textarea.dispatchEvent(new Event("input", { bubbles: true })); textarea.focus(); }, what);
    } catch (error) {
      host.replaceChildren(make("p", "notice", error.message));
    } finally { host.removeAttribute("aria-busy"); }
  }

  kit.showSuggestions = show;  // resume-enrich.js shows its bullets the same way
  kit.difference = difference;  // resume-tailor.js shows its changes the same way
  kit.suggestBullet = (row, textarea, entry) => ask(row, "bullet", { bullet: textarea.value, title: entry.title || "", emphasise: kit.emphasise }, textarea,
    `${textarea.labels[0].textContent.toLowerCase()} of ${entry.title || entry.company || "this job"}`);
  kit.suggestSummary = (body, textarea) => ask(body.querySelector("button"), "summary", {}, textarea, "your summary");
})();
