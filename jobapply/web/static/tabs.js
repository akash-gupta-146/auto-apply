"use strict";
/* The header's tabs: Apply on a site | AI agent | Profile. The standard pattern: arrow keys, Home and End move between tabs, and the
   tab you were on is remembered in this browser. Something beside the tabs (the Output column) can belong to some tabs only: it says
   so with data-only-on="<the ids of those tabs, separated by spaces>", and the page says which tab is chosen in data-tab, for the
   layout. */
(() => {
  const KEY = "jobapply.tab";
  const list = document.querySelector('[role="tablist"]');
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  const panelOf = (tab) => document.getElementById(tab.getAttribute("aria-controls"));

  function select(tab, focus = false) {
    for (const each of tabs) {
      const on = each === tab;
      each.setAttribute("aria-selected", String(on));
      each.tabIndex = on ? 0 : -1;  // only the chosen tab is a stop in the Tab order: the arrow keys move between them
      panelOf(each).hidden = !on;
    }
    document.querySelector("main.layout").dataset.tab = tab.id;
    for (const part of document.querySelectorAll("[data-only-on]")) part.hidden = !part.dataset.onlyOn.split(" ").includes(tab.id);
    try { localStorage.setItem(KEY, tab.id); } catch (_) { /* a browser that will not remember: fine */ }
    if (focus) tab.focus();
  }

  // Something is told in Output (a run started, a message): on a tab with no Output beside it (Profile), go to the first tab that has it.
  document.addEventListener("panel:output", () => {
    const column = document.getElementById("console").closest("[data-only-on]");
    if (!column.hidden) return;
    select(tabs.find((tab) => column.dataset.onlyOn.split(" ").includes(tab.id)));
    document.getElementById("h-out").focus();  // the button that was pressed is no longer on screen: focus goes to what it did
  });

  tabs.forEach((tab) => tab.addEventListener("click", () => select(tab)));
  list.addEventListener("keydown", (event) => {
    const here = tabs.indexOf(document.activeElement);
    const target = { ArrowRight: here + 1, ArrowLeft: here - 1, Home: 0, End: tabs.length - 1 }[event.key];
    if (here < 0 || target === undefined) return;
    event.preventDefault();
    select(tabs[(target + tabs.length) % tabs.length], true);
  });

  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (_) { /* as above */ }
  select(tabs.find((tab) => tab.id === saved) || tabs[0]);
})();
