"use strict";
/* The five parts of an open resume are tabs: Edit | ATS check | ATS match | Tailor | Use. Only the chosen part is on the page, so nothing is scrolled past. The standard
   pattern, the same as the panel's own tabs (tabs.js): arrow keys, Home and End move between the tabs, and only the chosen tab is a stop in the Tab order. What a part was
   showing (a verdict, a match) is kept while you are in another one. Every resume opens on Edit. A script that sends you to a place in another part (Go to it, Start a
   resume for a job) calls kit.showTab first. */
(() => {
  const { $ } = window.PanelKit;
  const kit = window.ResumeKit;
  const tabs = [...$("resume-subtabs").querySelectorAll('[role="tab"]')];
  const panelOf = (tab) => $(tab.getAttribute("aria-controls"));

  function select(tab, focus = false) {
    for (const each of tabs) {
      const on = each === tab;
      each.setAttribute("aria-selected", String(on));
      each.tabIndex = on ? 0 : -1;
      panelOf(each).hidden = !on;
    }
    if (focus) tab.focus();
  }

  kit.showTab = (name, focus = false) => select($(`rtab-${name}`), focus);  // name: edit, check, job, tailor or use

  tabs.forEach((tab) => tab.addEventListener("click", () => select(tab)));
  $("resume-subtabs").addEventListener("keydown", (event) => {
    const here = tabs.indexOf(document.activeElement);
    const target = { ArrowRight: here + 1, ArrowLeft: here - 1, Home: 0, End: tabs.length - 1 }[event.key];
    if (here < 0 || target === undefined) return;
    event.preventDefault();
    select(tabs[(target + tabs.length) % tabs.length], true);
  });
  document.addEventListener("resume:opened", () => select(tabs[0]));
})();
