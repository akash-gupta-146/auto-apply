"""The "Ask the AI" card, under Output on the AI agent tab: the markup only. ask.js fills in the conversation, always as text.

What the AI is shown, and what it is told, is in assistant.py; the card says the same in words, because the person asking is
the one whose details are sent.
"""
from __future__ import annotations

RISK = "Each question sends your details and applications to the AI company you chose, without email addresses and phone numbers."
DISCLOSURE = (  # the short line above is always on the page; this is how it works, behind a disclosure
    "Each question sends the AI company you chose: your profile details, what you are looking for, the text of your resume (which may "
    "contain your name), the answers you saved (consent questions left out) and your applications (job, company, result and reason), "
    "with email addresses and phone numbers removed. Your name, email and phone are sent too only if you tick the box. "
    "Nothing you ask or it answers is saved. Each question uses one of the AI helper's daily requests. "
    "If you chose Ollama, nothing leaves your computer."
)
STARTERS = (
    "How are my applications going here?",
    "Why were jobs skipped here?",
    "Which applications had errors, and why?",
    "What should I do next?",
)


def render() -> str:
    starters = "".join(f'<button class="btn btn-small" type="button" data-ask="{text}">{text}</button>' for text in STARTERS)
    return f"""
    <section class="card ask-card" id="ask-card" data-only-on="tab-agent" aria-labelledby="h-ask" hidden>
      <h2 id="h-ask">Ask the AI</h2>
      <p class="ask-about">About <strong id="ask-site"></strong> (change it on the Apply tab). <span id="ask-provider"></span></p>
      <p class="hint" id="ask-hint">{RISK}</p>
      <p class="notice" id="ask-setup" data-kind="info" hidden>The AI helper is not set up yet. <a href="/ai">Set it up</a>, then ask here.</p>
      <div class="ask-scroll">
        <ol class="ask-log" id="ask-log" role="log" aria-live="polite" aria-label="Conversation with the AI"></ol>
        <div id="ask-starters">
          <p class="hint">It knows your details and every application. For example:</p>
          <div class="controls">{starters}</div>
        </div>
      </div>
      <form class="ask-form" id="ask-form">
        <label class="sr-only" for="ask-question">Your question</label>
        <textarea id="ask-question" rows="2" maxlength="1000" placeholder="Ask about your applications, your details or what to do next"
                  aria-describedby="ask-hint ask-tip"></textarea>
        <label class="check" for="ask-identity"><input id="ask-identity" type="checkbox"> Include my name, email and phone</label>
        <div class="controls">
          <button class="btn btn-primary" id="ask-send" type="submit">Ask</button>
          <button class="btn" id="ask-clear" type="button" hidden>Clear the conversation</button>
          <span class="ask-status" id="ask-status" role="status"></span>
        </div>
        <div class="ask-foot">
          <p class="hint" id="ask-tip">Ctrl+Enter (Command+Enter on a Mac) asks too.</p>
          <details class="ask-more"><summary>What exactly is sent?</summary><p class="hint" id="ask-sent-detail">{DISCLOSURE}</p></details>
        </div>
      </form>
    </section>"""
