"use strict";
/* "Ask the AI", on the Profile tab. The conversation lives in this page only: reloading it starts afresh, and nothing
   is saved anywhere. Everything the AI writes is shown as plain text (never as HTML), so an answer can neither run anything nor
   look like a link. The server decides what the AI is shown and tells us in words what was sent. */
(() => {
  const { $, post, make } = window.PanelKit;
  const KEEP = 6;  // earlier messages sent along with a question, so a follow-up makes sense
  const talk = [];  // { role: "user" | "assistant", text }
  let busy = false;
  let configured = false;

  const site = () => {
    const chosen = document.querySelector('input[name="portal"]:checked') || document.querySelector('input[name="portal"]');
    return { id: chosen.value, label: chosen.dataset.label };
  };

  /* Shows a new message by scrolling the talk, and only the talk: the card is in the page now, and a long answer must never drag the page away from where you were
     reading. A message that is too tall for the talk is shown from its beginning, any other from its end (the same as scrollIntoView with "nearest", minus the page). */
  function reveal(item) {
    const area = item.closest(".ask-scroll"), within = area.getBoundingClientRect(), at = item.getBoundingClientRect();
    if (at.top < within.top || at.height > within.height) area.scrollTop += at.top - within.top;
    else if (at.bottom > within.bottom) area.scrollTop += at.bottom - within.bottom;
  }

  function say(who, text, extra = "") {
    const item = make("li", `ask-msg ask-${who}`);
    item.append(make("strong", "ask-who", who === "user" ? "You" : "AI"), make("p", "ask-text", text));
    if (extra) item.append(make("p", "ask-sent", extra));
    $("ask-clear").hidden = false;
    $("ask-starters").hidden = true;  // before the scrolling: the sizes are then the final ones
    $("ask-log").append(item);
    reveal(item);
  }

  function sayProblem(text) {  // not part of the talk: it is never sent back to the AI
    const item = make("li", "ask-msg ask-problem");
    item.append(make("strong", "ask-who", "Problem"), make("p", "ask-text", text));
    $("ask-log").append(item);
    reveal(item);
  }

  function renderState() {
    $("ask-site").textContent = site().label;
    $("ask-setup").hidden = configured;
    for (const id of ["ask-question", "ask-identity"]) $(id).disabled = !configured;
    $("ask-send").disabled = !configured || busy;
    for (const starter of document.querySelectorAll("[data-ask]")) starter.disabled = !configured;
  }

  function setBusy(on) {
    busy = on;
    $("ask-log").setAttribute("aria-busy", String(on));
    $("ask-status").textContent = on ? "Thinking..." : "";
    renderState();
  }

  async function ask(event) {
    event.preventDefault();
    const box = $("ask-question"), question = box.value.trim();
    if (!question || busy || !configured) return;
    const earlier = talk.slice(-KEEP);
    say("user", question);
    talk.push({ role: "user", text: question });
    box.value = "";
    setBusy(true);
    try {
      const reply = await post("/api/ask", { question, site: site().id, identity: $("ask-identity").checked, history: earlier });
      talk.push({ role: "assistant", text: reply.answer });
      say("assistant", reply.answer, reply.sent);
    } catch (error) {
      talk.pop();  // the question got no answer: it is not part of the talk
      sayProblem(error.message);
    } finally {
      setBusy(false);
      box.focus({ preventScroll: true });  // back where you type; the page stays where it is, and typing brings the box into view
    }
  }

  $("ask-form").addEventListener("submit", ask);
  $("ask-question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) $("ask-form").requestSubmit();
  });
  $("ask-clear").addEventListener("click", () => {
    talk.length = 0;
    $("ask-log").replaceChildren();
    $("ask-clear").hidden = true;
    $("ask-starters").hidden = false;
    $("ask-question").focus();
  });
  for (const starter of document.querySelectorAll("[data-ask]")) {
    starter.addEventListener("click", () => { $("ask-question").value = starter.dataset.ask; $("ask-question").focus(); });
  }
  document.addEventListener("change", (event) => { if (event.target.name === "portal") renderState(); });
  document.addEventListener("panel:state", (event) => {
    const ai = event.detail.setup.ai;
    configured = !!ai.configured;
    $("ask-provider").textContent = ai.configured ? `Using ${ai.label}.` : "";
    renderState();
  });
  renderState();
})();
