"""The AI agent's card on the control panel: the markup only. panel.js fills in the live parts, always as text."""
from __future__ import annotations



def render(ai_disclosure: str) -> str:
    return f"""
    <section class="card" id="agent-card" aria-labelledby="h-agent">
      <h2 id="h-agent" tabindex="-1">Auto fill form: any site</h2>
      <p>Paste a job page's address below, or open the job page in the browser from step 2, then press Start. The agent works on any
      site: it finds the way to apply, fills in what it can, and asks you for the rest. It never types a password or gets past a
      captcha: you do those. The same agent also takes over, during a run on the Apply tab, the jobs a site cannot apply to itself.</p>
      <div class="field"><label for="agent-url">Job page address (optional)</label>
      <input id="agent-url" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://" aria-describedby="agent-url-hint"></div>
      <p class="hint" id="agent-url-hint">The agent opens it in its own browser, whichever browser you found the job in, and opens a window if it has none.
      Empty: it uses the job page already open in the agent's browser (the one that looks like a job, if you have several tabs open).</p>
      <div class="field"><label for="agent-minutes">Minutes, at most</label>
      <input id="agent-minutes" type="number" min="1" max="720" value="30" inputmode="numeric"></div>
      <label class="check" for="agent-ai"><input class="filled-in" id="agent-ai" type="checkbox" aria-describedby="agent-ai-hint"><span>Use the AI helper</span></label>
      <p class="hint" id="agent-ai-hint">It answers questions your saved answers cannot, and reads pages the rules are unsure about.
      {ai_disclosure}</p>
      <label class="check" for="agent-guess"><input class="filled-in" id="agent-guess" type="checkbox" checked aria-describedby="agent-guess-hint agent-guess-why"><span>Guess answers I have not saved</span></label>
      <p class="hint" id="agent-guess-hint">When no saved answer or rule fits, the AI helper makes its best guess and says so, and lists every guess first when it asks
      to send, so you can check it. Guesses are kept on the <a href="/questions">Questions page</a>, where you can keep one as your own answer or forget it. It never
      guesses an agreement, a legal or personal question, or what only you know (pay, notice period, dates, links). It asks you instead when it is not sure,
      or when the form does not accept its guess.</p>
      <p class="hint" id="agent-guess-why" hidden></p>
      <label class="check" for="agent-send"><input class="filled-in" id="agent-send" type="checkbox" aria-describedby="agent-send-hint"><span>Let it send applications</span></label>
      <p class="hint" id="agent-send-hint">Off: a rehearsal that stops before the final button. On: it can really send.</p>
      <div id="agent-send-options" hidden>
        <label class="check" for="agent-wait"><input class="filled-in" id="agent-wait" type="checkbox" checked aria-describedby="agent-wait-hint"><span>Wait for my approval before each
        application is sent</span></label>
        <p class="hint" id="agent-wait-hint">On (recommended): it shows you what it is about to send, here, and sends only after you press
        Approve. Off: it sends as soon as the form is filled in, without asking.</p>
        <div class="field"><label for="agent-confirm">Type YES to allow sending</label>
        <input id="agent-confirm" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
      </div>
      <div class="controls">
        <button class="btn btn-primary" type="button" data-action="agent">Start the agent</button>
        <button class="btn" type="button" id="agent-continue" data-action="agent" data-again="1">Continue the unfinished application</button>
      </div>
      <div class="agent-live" id="agent-live" aria-labelledby="h-agent-live">
        <h3 id="h-agent-live">What the agent is doing</h3>
        <p id="agent-state" role="status">The agent is: Idle</p>
        <p id="agent-job" hidden></p>
        <p id="agent-detail" hidden></p>
        <div id="agent-asking" hidden>
          <p>It is waiting for you:</p>
          <ul id="agent-questions"></ul>
          <p><a href="/questions">Answer questions</a>, or type the answer into the form in the browser.</p>
        </div>
        <div class="notice" id="agent-approval" role="group" aria-labelledby="agent-approval-title" hidden>
          <h4 id="agent-approval-title">Waiting for your approval to send</h4>
          <ul id="agent-summary"></ul>
          <div class="controls">
            <button class="btn btn-danger" type="button" id="agent-approve">Approve and send</button>
            <button class="btn" type="button" id="agent-reject">Do not send</button>
          </div>
        </div>
        <div class="controls">
          <button class="btn" type="button" id="agent-pause">Pause the agent</button>
          <a class="btn" href="/applications">All applications</a>
        </div>
        <ul class="feed" id="agent-feed" aria-label="What the agent has been doing, newest first" hidden></ul>
      </div>
    </section>"""
