"use strict";
/* The Profile tab's dashboard: how many jobs each site has sent, skipped and failed, and the list of jobs behind each number.
   Drawn as SVG shapes and text only (the panel's security policy allows no inline styles, and nothing here is ever HTML).
   The group names and what each means come from the server, so there is one list of them.

   Every number can be pressed: the five tiles (all sites), and the numbers under each bar (one site). The ring's slices and the
   bars' stripes do the same for a mouse; they add nothing a keyboard cannot already do with the buttons. */
(() => {
  const { $, api, make } = window.PanelKit;
  const SVG = "http://www.w3.org/2000/svg";
  const CENTRE = 21, OUTER = 19, INNER = 13;  // the ring, in its own 42 x 42 drawing
  let data = null;  // the last numbers the panel sent
  let drawn = "";
  let chosen = null;  // { group, site } of the open list, or null
  let ticket = 0;  // which list request is the latest: a slow answer to an older press is ignored

  const shape = (tag, attributes, text) => {
    const element = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const sentence = (row, groups) =>  // "Submitted 2, Errors 1": a label and a number, so no plurals to get wrong
    groups.filter((g) => row[g.id]).map((g) => `${g.label} ${row[g.id]}`).join(", ") || "no jobs yet";
  const aim = (group, site) => ({ "data-group": group, "data-site": site });  // what a press on this control lists
  const same = (a, b) => !!a && !!b && a.group === b.group && a.site === b.site;
  const controlFor = (pick) => document.querySelector(`#dashboard button[data-group="${pick.group}"][data-site="${pick.site}"]`);

  // -- the picture ----------------------------------------------------------------------------
  function renderKpis(totals, groups) {
    $("dash-kpis").replaceChildren(...groups.map((g) => {
      const tile = make("button", `kpi seg-${g.id}`);
      tile.type = "button";
      tile.dataset.group = g.id; tile.dataset.site = "";
      tile.setAttribute("aria-controls", "dash-list");
      tile.title = g.about;
      tile.append(make("span", "kpi-name", g.label), make("span", "kpi-num", String(totals[g.id])));
      return tile;
    }));
  }

  const point = (radius, turns) => {  // a place on the ring: `turns` is 0 to 1 round, from the top, clockwise
    const angle = 2 * Math.PI * turns - Math.PI / 2;
    return [CENTRE + radius * Math.cos(angle), CENTRE + radius * Math.sin(angle)].map((n) => n.toFixed(3));
  };
  function slicePath(from, to) {
    if (to - from > 0.9999) {  // everything in one group: a whole ring is two circles, not an arc that ends where it began
      const circle = (r, sweep) => `M${CENTRE - r} ${CENTRE} a${r} ${r} 0 1 ${sweep} ${2 * r} 0 a${r} ${r} 0 1 ${sweep} ${-2 * r} 0Z`;
      return circle(OUTER, 0) + circle(INNER, 1);
    }
    const big = to - from > 0.5 ? 1 : 0;
    const [x1, y1] = point(OUTER, from), [x2, y2] = point(OUTER, to), [x3, y3] = point(INNER, to), [x4, y4] = point(INNER, from);
    return `M${x1} ${y1}A${OUTER} ${OUTER} 0 ${big} 1 ${x2} ${y2}L${x3} ${y3}A${INNER} ${INNER} 0 ${big} 0 ${x4} ${y4}Z`;
  }

  function renderDonut(totals, groups) {  // the ring adds up to everything: each slice is that group's share of every job
    const donut = $("dash-donut");
    donut.replaceChildren();
    let before = 0;
    for (const g of groups) {
      const share = totals.total ? totals[g.id] / totals.total : 0;
      if (share > 0) {
        const slice = shape("path", { d: slicePath(before, before + share), "fill-rule": "evenodd", class: `seg seg-${g.id} pick`, ...aim(g.id, "") });
        slice.append(shape("title", {}, `${g.label} ${totals[g.id]} of ${totals.total}. Press to list them.`));
        donut.append(slice);
      }
      before += share;
    }
    donut.append(shape("text", { x: CENTRE, y: 21.6, "text-anchor": "middle", class: "donut-number" }, String(totals.total)),
                 shape("text", { x: CENTRE, y: 26.4, "text-anchor": "middle", class: "donut-unit" }, totals.total === 1 ? "job" : "jobs"));
    donut.setAttribute("aria-label", `All sites, ${totals.total} ${totals.total === 1 ? "job" : "jobs"}: ${sentence(totals, groups)}`);
  }

  function renderRow(row, groups, widest) {  // the bar's length is the site's share of the busiest site, so busy sites look busy
    const item = make("li", "dash-row");
    const bar = shape("svg", { class: "bar", viewBox: "0 0 100 10", preserveAspectRatio: "none", role: "img",
                               "aria-label": `${row.label}: ${sentence(row, groups)}` });
    bar.append(shape("rect", { x: 0, y: 0, width: 100, height: 10, class: "bar-track" }));
    let at = 0;
    for (const g of groups) {
      const width = widest ? (100 * row[g.id]) / widest : 0;
      if (width > 0) {
        const stripe = shape("rect", { x: at, y: 0, width, height: 10, class: `seg seg-${g.id} pick`, ...aim(g.id, row.id) });
        stripe.append(shape("title", {}, `${row.label}: ${g.label} ${row[g.id]}. Press to list them.`));
        bar.append(stripe);
      }
      at += width;
    }
    const facts = make("div", "dash-facts");
    if (!row.total) facts.textContent = "No jobs yet";
    for (const g of groups.filter((group) => row[group.id])) {  // the same numbers as buttons: the keyboard's way to the list
      const chip = make("button", `chip seg-${g.id}`, `${g.label} ${row[g.id]}`);
      chip.type = "button";
      chip.dataset.group = g.id; chip.dataset.site = row.id;
      chip.setAttribute("aria-label", `${g.label} ${row[g.id]}, ${row.label}: list them`);
      chip.setAttribute("aria-controls", "dash-list");
      facts.append(chip);
    }
    item.append(make("span", "dash-name", row.label), bar, make("span", "dash-total", String(row.total)), facts);
    return item;
  }

  function renderTable({ groups, portals, totals }) {  // the same numbers in words, for anyone who cannot read the picture
    const line = (cells) => {  // each cell: [tag, text, scope]
      const row = make("tr");
      for (const [tag, text, scope] of cells) {
        const cell = make(tag, "", String(text));
        if (scope) cell.setAttribute("scope", scope);
        row.append(cell);
      }
      return row;
    };
    const figures = (row) => [...groups.map((g) => ["td", row[g.id]]), ["td", row.total]];
    const head = make("thead"), body = make("tbody"), foot = make("tfoot");
    head.append(line([["th", "Site", "col"], ...groups.map((g) => ["th", g.label, "col"]), ["th", "All", "col"]]));
    portals.forEach((row) => body.append(line([["th", row.label, "row"], ...figures(row)])));
    foot.append(line([["th", "All sites", "row"], ...figures(totals)]));
    $("dash-table").replaceChildren(make("caption", "", "Jobs by site"), head, body, foot);
  }

  // -- the list behind a number ---------------------------------------------------------------
  const renderList = (listing, showSite) => window.JobTable.render($("dash-list-table"), `${listing.label} applications`, listing.jobs, showSite);

  function markChosen() {  // the pressed tile, number or stripe says so, in shape (a heavier outline) and for screen readers
    for (const control of document.querySelectorAll("#dashboard [data-group]")) {
      const on = same(chosen, { group: control.dataset.group, site: control.dataset.site });
      if (control.tagName === "BUTTON") control.setAttribute("aria-pressed", String(on));
      control.toggleAttribute("data-chosen", on);
    }
  }

  async function showList({ quiet = false } = {}) {
    const mine = ++ticket, pick = chosen;
    const groups = data.groups, site = data.portals.find((row) => row.id === pick.site);
    const where = site ? site.label : "All sites";
    const group = groups.find((g) => g.id === pick.group);
    const heading = $("h-dash-list"), note = $("dash-list-note");
    $("dash-list").hidden = false;
    heading.textContent = `${group.label}: ${where}`;
    if (!quiet) { note.textContent = "Loading the list..."; $("dash-list-wrap").hidden = true; }
    try {
      const listing = await api(`/api/jobs?group=${encodeURIComponent(pick.group)}&site=${encodeURIComponent(pick.site)}`);
      if (mine !== ticket) return;
      heading.textContent = `${group.label}: ${where} (${listing.total})`;
      const shown = listing.jobs.length;
      note.textContent = !listing.total ? "Nothing here yet."
        : shown < listing.total ? `Showing the latest ${shown} of ${listing.total}, newest first.` : `${listing.total} ${listing.total === 1 ? "application" : "applications"}, newest first.`;
      $("dash-list-wrap").hidden = !shown;
      if (shown) renderList(listing, !pick.site);
    } catch (error) {
      if (mine !== ticket) return;
      note.textContent = `The list could not be loaded: ${error.message}`;
      $("dash-list-wrap").hidden = true;
    }
  }

  function choose(pick) {
    if (same(chosen, pick)) return closeList(false);  // pressing the same number again puts the list away
    chosen = pick;
    markChosen();
    showList();
    $("h-dash-list").focus({ preventScroll: true });  // the list opens below the bars: move there, so it is read...
    $("dash-list").scrollIntoView({ block: "start" });  // ...and seen: all of its box, not only its heading (focus alone scrolls just enough for that)
  }

  function closeList(giveFocusBack = true) {
    const was = chosen;
    chosen = null; ticket += 1;
    $("dash-list").hidden = true;
    markChosen();
    if (was && giveFocusBack) (controlFor(was) || controlFor({ group: was.group, site: "" }))?.focus();
  }

  // -- keeping up with the panel ----------------------------------------------------------------
  function render(next) {
    const signature = JSON.stringify(next);
    if (signature === drawn) return;  // the panel asks every few seconds: redraw only when something changed
    drawn = signature;
    data = next;
    const { groups, portals, totals } = next;
    $("dash-empty").hidden = totals.total > 0;
    $("dash-body").hidden = totals.total === 0;
    if (!totals.total) return;
    const held = document.activeElement?.closest("#dashboard [data-group]");  // a redraw must not drop the key the keyboard is on
    const keep = held && { group: held.dataset.group, site: held.dataset.site };
    renderKpis(totals, groups);
    renderDonut(totals, groups);
    const widest = Math.max(...portals.map((row) => row.total));
    $("dash-rows").replaceChildren(...portals.map((row) => renderRow(row, groups, widest)));
    renderTable(next);
    markChosen();
    if (keep) controlFor(keep)?.focus();
    if (chosen) showList({ quiet: true });  // an open list follows the numbers
  }

  $("dashboard").addEventListener("click", (event) => {
    const control = event.target.closest("[data-group]");
    if (control) choose({ group: control.dataset.group, site: control.dataset.site });
  });
  $("dash-list-close").addEventListener("click", () => closeList());
  document.addEventListener("panel:state", (event) => render(event.detail.setup.dashboard));
  if (window.PanelKit.state.last) render(window.PanelKit.state.last.setup.dashboard);
})();
