"use strict";
/* The Auto fill form tab: what the agent is doing, what it needs, and your say before anything is sent.
   Everything from the server or the agent is shown as TEXT, never as HTML: job titles come from the internet. */
(() => {
  const { $, post, notice, announce, make, refresh, optionsFor, state } = window.PanelKit;
  const ACTIVE_OFF = ["Idle", "Completed", "Failed"];
  let approvalSeen = "";

  const fillList = (list, lines) => { list.replaceChildren(...lines.map((line) => make("li", "", line))); list.hidden = !lines.length; };
  const sentence = (text) => (text ? text[0].toUpperCase() + text.slice(1) : "");

  function badgeFor(agent, active) {  // seen from the other tab too: it says when the agent needs you
    if (agent.approval) return "approval needed";
    if ((agent.questions || []).length) return "needs an answer";
    return active ? "working" : "";
  }

  function renderAgent(agent) {
    const paused = agent.paused && agent.state !== "Paused";
    $("agent-state").textContent = `The agent is: ${agent.state}${paused ? " (paused)" : ""}`;
    for (const [id, text] of [["agent-job", agent.job ? `Job: ${agent.job}` : ""], ["agent-detail", sentence(agent.detail)]]) {
      $(id).textContent = text; $(id).hidden = !text;
    }
    fillList($("agent-questions"), agent.questions || []);
    $("agent-asking").hidden = !(agent.questions || []).length;
    const ask = agent.approval;
    $("agent-approval").hidden = !ask;
    if (ask) {
      fillList($("agent-summary"), ask.summary || []);
      $("agent-approval").dataset.session = ask.session;
      if (approvalSeen !== ask.session) {  // said once, not on every poll
        approvalSeen = ask.session;
        announce("The agent is waiting for your approval to send an application.");
      }
    }
    $("agent-pause").textContent = agent.paused ? "Resume the agent" : "Pause the agent";
    $("agent-pause").dataset.paused = agent.paused ? "1" : "";
    fillList($("agent-feed"), (agent.feed || []).map((entry) => `${entry.at.slice(11)} ${entry.text}`).reverse());
    state.agentActive = !ACTIVE_OFF.includes(agent.state);  // watch it closely while it works
    const badge = $("agent-badge"), words = badgeFor(agent, state.agentActive);
    badge.textContent = words; badge.hidden = !words; badge.dataset.kind = ask ? "urgent" : "";
  }

  async function decide(decision) {
    try {
      await post("/api/agent/decide", { session: $("agent-approval").dataset.session, decision });
      await refresh();
    } catch (error) { notice(error.message, "error"); }
  }

  optionsFor.agent = (button) => ({
    minutes: $("agent-minutes").value, url: $("agent-url").value.trim(), ai: $("agent-ai").checked, send: $("agent-send").checked, approval: $("agent-wait").checked,
    guess: $("agent-guess").checked,
    again: Boolean(button && button.dataset.again), confirm: $("agent-confirm").value,
  });

  // Guessing needs the AI helper, and a guess is only safe if you see it before anything is sent: so it is off, and says why, when the
  // AI helper is off or the agent may send without waiting for your approval. (The program enforces the same; this only tells you.)
  function syncGuess() {
    const noAi = !$("agent-ai").checked, unasked = $("agent-send").checked && !$("agent-wait").checked;
    const why = $("agent-guess-why");
    $("agent-guess").disabled = noAi || unasked;
    why.textContent = noAi ? "Off while the AI helper is off."
      : unasked ? "Off while it may send without waiting for your approval: a guess is only safe if you can check it first." : "";
    why.hidden = !why.textContent;
  }
  for (const id of ["agent-ai", "agent-send", "agent-wait"]) $(id).addEventListener("change", syncGuess);
  syncGuess();

  $("agent-send").addEventListener("change", () => {  // sending is a choice that asks for the word, and for how much to ask you
    $("agent-send-options").hidden = !$("agent-send").checked;
  });
  $("agent-approve").addEventListener("click", () => decide("approve"));
  $("agent-reject").addEventListener("click", () => decide("reject"));
  $("agent-pause").addEventListener("click", () =>
    post("/api/agent/pause", { paused: !$("agent-pause").dataset.paused }).then(refresh).catch((e) => notice(e.message, "error")));

  document.addEventListener("panel:state", (event) => renderAgent(event.detail.agent));
  if (state.last) renderAgent(state.last.agent);  // the first look can arrive before this script has started listening
})();
