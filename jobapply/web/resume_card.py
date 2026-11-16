"""The Create Resume tab: the markup only. resume.js, resume-form.js, resume-ai.js and resume-check.js fill in the live parts, always as text.

Reading order is the order of doing it: pick or start a resume, edit it beside a preview of the real page, check it (and match it to a job), and use it for
your applications. The preview is an inner page that only this panel may frame; it is the very page the PDF is printed from.
"""
from __future__ import annotations

AI_NOTE = ("The AI buttons send only the text you ask about (for a summary: your job titles, skills and a few bullets), with emails and phone numbers "
           "removed and no names of employers, to the AI you chose on the <a href=\"/ai\">AI helper page</a>. You see each suggestion next to what you wrote, "
           "and nothing changes until you press Use this.")


def render() -> str:
    return f"""
    <section class="card" id="resume-list-card" aria-labelledby="h-resume">
      <h2 id="h-resume" tabindex="-1">Create Resume</h2>
      <p>Build a clean resume that applicant tracking systems can read, check it, match it to a job, and use it for your applications.
      Everything stays on this computer. Nothing is sent anywhere until you apply.</p>
      <p id="resume-status" role="status"></p>
      <div class="controls">
        <button class="btn btn-primary" type="button" id="resume-new-blank">New blank resume</button>
        <button class="btn" type="button" id="resume-new-profile">New from my details</button>
        <button class="btn" type="button" id="resume-new-upload" aria-describedby="resume-upload-hint">New from my uploaded resume</button>
      </div>
      <p class="hint" id="resume-upload-hint"></p>
      <ul class="resume-cards" id="resume-list" aria-labelledby="h-resume"></ul>
      <p class="hint" id="resume-empty" hidden>You have no resumes here yet. Start one above.</p>
    </section>
    <div id="resume-open" hidden>
      <section class="card" id="resume-editor" aria-labelledby="h-resume-edit">
        <div class="resume-bar">
          <button class="btn btn-small" type="button" id="resume-back">Back to all resumes</button>
          <p id="resume-saved" role="status"></p>
        </div>
        <h2 id="h-resume-edit" tabindex="-1">Edit your resume</h2>
        <div class="notice" id="resume-notes" role="group" aria-labelledby="resume-notes-title" hidden>
          <h3 id="resume-notes-title">Check what was read from your file</h3>
          <ul id="resume-notes-list"></ul>
        </div>
        <div class="notice" data-kind="error" id="resume-conflict" role="alert" hidden>
          <p id="resume-conflict-text"></p>
          <button class="btn" type="button" id="resume-reload">Load the latest version</button>
        </div>
        <div class="resume-grid">
          <div class="resume-form-col">
            <div class="field"><label for="resume-title">Name of this resume (only you see it)</label>
            <input id="resume-title" type="text" maxlength="80" autocomplete="off"></div>
            <p class="hint" id="resume-ai-note">{AI_NOTE}</p>
            <p class="hint" id="resume-ai-off" hidden>The AI helper is not set up, so the AI buttons are switched off. The rest works without it.</p>
            <details class="resume-block" open><summary>Look</summary>
              <div class="field"><label for="resume-template">Template</label><select id="resume-template" data-pointer="/template"></select></div>
              <p class="hint" id="resume-template-note"></p>
              <div class="resume-look">
                <div class="field"><label for="resume-font">Font</label><select id="resume-font"></select></div>
                <div class="field"><label for="resume-size">Size (points)</label><select id="resume-size"></select></div>
                <div class="field"><label for="resume-accent">Accent colour</label><select id="resume-accent"></select></div>
                <div class="field"><label for="resume-spacing">Spacing</label><select id="resume-spacing" data-pointer="/theme/spacing"></select></div>
                <div class="field"><label for="resume-page">Paper</label><select id="resume-page"></select></div>
              </div>
            </details>
            <details class="resume-block" open><summary>Sections: show, hide and put in order</summary>
              <p class="hint">A section with nothing in it is left out of the resume. The order here is the order on the page.</p>
              <ol class="resume-sections" id="resume-sections"></ol>
            </details>
            <div id="resume-form"></div>
          </div>
          <div class="resume-preview-col">
            <div class="controls">
              <a class="btn btn-primary" id="resume-download" href="/resume/export.pdf" download>Download as a PDF</a>
            </div>
            <p class="hint" id="resume-pages" role="status"></p>
            <div class="resume-preview-wrap" id="resume-preview-wrap">
              <iframe id="resume-preview" title="Preview of your resume (read only)" sandbox="" src="about:blank"></iframe>
            </div>
          </div>
        </div>
      </section>
      <section class="card" id="resume-check-card" aria-labelledby="h-resume-check">
        <h2 id="h-resume-check" tabindex="-1">Check it</h2>
        <p>See how an applicant tracking system would read this resume, with the reasons for every point lost. Paste a job description to also see which of the
        skills it asks for your resume does not mention.</p>
        <div class="field"><label for="resume-job">A job description (optional)</label>
        <textarea id="resume-job" rows="6" maxlength="20000" spellcheck="false" aria-describedby="resume-job-hint"></textarea></div>
        <p class="hint" id="resume-job-hint">Skills it only prefers ("nice to have") cost you nothing. Nothing is added to your resume for you: you decide what is true.</p>
        <div class="field"><label for="resume-extra">Other words to look for (optional, separated by commas)</label>
        <input id="resume-extra" type="text" autocomplete="off" spellcheck="false" aria-describedby="resume-extra-hint"></div>
        <p class="hint" id="resume-extra-hint">The check knows the common skills and the ones in your profile. Add the name of a tool it does not know.</p>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-check">Check my resume</button></div>
        <p id="resume-check-status" role="status"></p>
        <div id="resume-report" hidden>
          <h3 id="resume-score" tabindex="-1"></h3>
          <ul class="resume-cats" id="resume-cats"></ul>
          <h3 id="h-resume-fixes">What to fix</h3>
          <ul class="resume-fixes" id="resume-fixes" aria-labelledby="h-resume-fixes"></ul>
          <details class="resume-block"><summary>What is already good</summary><ul id="resume-good"></ul></details>
          <div id="resume-keywords" hidden>
            <h3 id="h-resume-keywords">Skills in the job description</h3>
            <p id="resume-coverage"></p>
            <ul id="resume-kw-missing" aria-labelledby="h-resume-keywords"></ul>
            <p class="hint" id="resume-kw-hint">Press "I have this" only for a skill that is true of you. It goes in your resume's skills; your bullets are yours to word.</p>
            <p id="resume-kw-have" class="hint"></p>
            <div class="field"><label for="resume-copy-name">Keep a copy of this resume for this job</label>
            <input id="resume-copy-name" type="text" maxlength="80" autocomplete="off"></div>
            <div class="controls"><button class="btn" type="button" id="resume-copy">Save a copy for this job</button></div>
          </div>
        </div>
      </section>
      <section class="card" id="resume-use-card" aria-labelledby="h-resume-use">
        <h2 id="h-resume-use" tabindex="-1">Use it for my applications</h2>
        <p id="resume-use-now"></p>
        <p>This prints the resume as a PDF and makes it the resume your runs send (the one on the Profile tab). Skills it mentions that are not in your profile are
        added there with no years, never with numbers made up for you. Your earlier resume file stays in the data folder.</p>
        <label class="check" for="resume-use-sure"><input type="checkbox" id="resume-use-sure"> Yes, use this resume from now on</label>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-use" disabled>Use this resume</button></div>
        <p id="resume-use-status" role="status"></p>
      </section>
    </div>"""
