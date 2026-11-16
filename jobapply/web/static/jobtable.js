"use strict";
/* A table of jobs, drawn the same way wherever the panel lists them (the Profile tab's dashboard, the Auto-apply v2 tab's history).
   Everything comes from the server as data and goes in as TEXT, never as HTML: titles and reasons come from the internet.
   A job's link is only ever a web address (the server checks), and opens in its own tab and says so. */
(() => {
  const { make } = window.PanelKit;

  const when = (iso) => {  // "13 Nov, 10:11": short enough for one line, and the year only when it is not this one
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const year = date.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" };
    return date.toLocaleString(undefined, { day: "numeric", month: "short", ...year, hour: "numeric", minute: "2-digit" });
  };

  // `jobs`: [{title, company, location, site, result, reason, when, url}]. `showSite`: add the Site column (a list over every site).
  function render(table, caption, jobs, showSite) {
    const columns = ["Job", "Company", ...(showSite ? ["Site"] : []), "Result", "When"];
    const head = make("thead"), body = make("tbody");
    const headRow = make("tr");
    columns.forEach((name) => { const cell = make("th", "", name); cell.setAttribute("scope", "col"); headRow.append(cell); });
    head.append(headRow);
    for (const job of jobs) {
      const row = make("tr");
      const title = job.title || "(no title)";
      const jobCell = make("th");
      jobCell.setAttribute("scope", "row");
      if (job.url) {
        const link = make("a", "", title);
        link.href = job.url; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.append(make("span", "sr-only", " (opens in a new tab)"));
        jobCell.append(link);
      } else {
        jobCell.textContent = title;
      }
      if (job.location) jobCell.append(make("small", "dash-sub", job.location));
      const result = make("td", "", job.result);
      if (job.reason) result.append(make("small", "dash-sub", job.reason));
      const stamp = make("td", "short"), text = when(job.when);
      if (text) { const time = make("time", "", text); time.dateTime = job.when; stamp.append(time); }
      row.append(jobCell, make("td", "", job.company || "-"), ...(showSite ? [make("td", "short", job.site)] : []), result, stamp);
      body.append(row);
    }
    table.replaceChildren(make("caption", "sr-only", caption), head, body);
  }

  window.JobTable = Object.freeze({ render });
})();
