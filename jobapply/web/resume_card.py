"""The Create Resume tab: the markup only. resume.js, resume-form.js, resume-ai.js, resume-job.js, resume-enrich.js, resume-tailor.js, resume-check.js, resume-tabs.js and resume-ats.js fill in the live parts, always as text.

Reading order is the order of doing it: pick or start a resume, edit it beside a preview of the real page, match it to a job and tailor it, check it, and use it for
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
      <p>Build a clean resume that applicant tracking systems can read, check it, match it to a job, and use it for your applications. An <strong>ATS</strong>
      (applicant tracking system) is the software that reads a resume before a person does. Everything stays on this computer. Nothing is sent anywhere until you apply.</p>
      <p id="resume-status" role="status"></p>
      <div class="controls">
        <button class="btn btn-primary" type="button" id="resume-new-blank">New blank resume</button>
        <button class="btn" type="button" id="resume-new-profile">New from my details</button>
        <button class="btn" type="button" id="resume-new-upload" aria-describedby="resume-upload-hint">New from my uploaded resume</button>
        <button class="btn" type="button" id="resume-new-job" aria-describedby="resume-job-start-hint">Start a resume for a job</button>
      </div>
      <p class="hint" id="resume-upload-hint"></p>
      <p class="hint" id="resume-job-start-hint">"Start a resume for a job" makes a draft from your saved details and takes you to the job box, to see how it lines up and tailor it.</p>
      <ul class="resume-cards" id="resume-list" aria-labelledby="h-resume"></ul>
      <p class="hint" id="resume-empty" hidden>You have no resumes here yet. Start one above.</p>
      <section id="resume-file-card" aria-labelledby="h-resume-file">
        <h3 id="h-resume-file" tabindex="-1">ATS check for a resume you already have</h3>
        <p>Is the resume you send now ATS-friendly? Check it, or any PDF or Word (.docx) file. It is read on this computer and not kept.</p>
        <div class="controls">
          <button class="btn btn-primary" type="button" id="resume-file-current" aria-describedby="resume-file-hint" disabled>Check the resume my runs send</button>
        </div>
        <p class="hint" id="resume-file-hint"></p>
        <div class="field"><label for="resume-file-pick">Or choose a PDF or Word file to check</label>
        <input id="resume-file-pick" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"></div>
        <div class="controls"><button class="btn" type="button" id="resume-file-go" disabled>Check this file</button></div>
        <p id="resume-file-status" role="status"></p>
        <div id="resume-file-out" hidden></div>
      </section>
    </section>
    <div id="resume-open" hidden>
      <section class="card" id="resume-head" aria-label="This resume">
        <div class="resume-bar">
          <button class="btn btn-small" type="button" id="resume-back">Back to all resumes</button>
          <p id="resume-saved" role="status"></p>
        </div>
        <p class="hint" id="resume-ats-line">ATS status of this resume: <span id="resume-ats-chip"></span></p>
        <div class="notice" data-kind="error" id="resume-conflict" role="alert" hidden>
          <p id="resume-conflict-text"></p>
          <button class="btn" type="button" id="resume-reload">Load the latest version</button>
        </div>
        <div class="resume-subtabs" id="resume-subtabs" role="tablist" aria-label="Parts of this resume">
          <button class="resume-subtab" type="button" role="tab" id="rtab-edit" aria-controls="resume-editor" aria-selected="true">Edit</button>
          <button class="resume-subtab" type="button" role="tab" id="rtab-check" aria-controls="resume-check-card" aria-selected="false" tabindex="-1">ATS check</button>
          <button class="resume-subtab" type="button" role="tab" id="rtab-job" aria-controls="resume-job-card" aria-selected="false" tabindex="-1">ATS match</button>
          <button class="resume-subtab" type="button" role="tab" id="rtab-tailor" aria-controls="resume-tailor-card" aria-selected="false" tabindex="-1">Tailor</button>
          <button class="resume-subtab" type="button" role="tab" id="rtab-use" aria-controls="resume-use-card" aria-selected="false" tabindex="-1">Use</button>
        </div>
      </section>
      <section class="card" id="resume-editor" role="tabpanel" aria-labelledby="rtab-edit">
        <h2 id="h-resume-edit" tabindex="-1">Edit your resume</h2>
        <div class="notice" id="resume-notes" role="group" aria-labelledby="resume-notes-title" hidden>
          <h3 id="resume-notes-title">Check what was read from your file</h3>
          <ul id="resume-notes-list"></ul>
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
      <section class="card" id="resume-job-card" role="tabpanel" aria-labelledby="rtab-job" hidden>
        <h2 id="h-resume-job" tabindex="-1">ATS match: how well it fits a job</h2>
        <p>Give the job, and see how your resume lines up with it: what it asks for, and where your resume shows it. This compares words. It does not predict
        whether you would be shortlisted.</p>
        <div class="field"><label for="resume-job-url">Web address of the job (optional)</label>
        <input id="resume-job-url" type="url" inputmode="url" autocomplete="off" spellcheck="false" aria-describedby="resume-job-how"></div>
        <div class="controls">
          <button class="btn" type="button" id="resume-job-fetch">Read the job from this address</button>
          <button class="btn" type="button" id="resume-job-browser">Read the job open in my browser</button>
        </div>
        <p class="hint" id="resume-job-how">A public job page can be read from its address. A page that asks you to sign in cannot: open the job in the browser this program uses
        (signed in as you) and press the second button, or paste the text. Nothing is read until you press a button, and nothing on the page is changed.</p>
        <p id="resume-job-status" role="status"></p>
        <div class="field"><label for="resume-job-title">Job title (optional)</label>
        <input id="resume-job-title" type="text" maxlength="80" autocomplete="off"></div>
        <div class="field"><label for="resume-job">The job description</label>
        <textarea id="resume-job" rows="8" maxlength="20000" spellcheck="false" aria-describedby="resume-job-hint"></textarea></div>
        <p class="hint" id="resume-job-hint">Paste it here, or read it with a button above and then trim what is not the description. Skills it only prefers (\"nice to have\") cost you
        nothing. Nothing is added to your resume for you: you decide what is true.</p>
        <div class="field"><label for="resume-extra">Other words to look for (optional, separated by commas)</label>
        <input id="resume-extra" type="text" autocomplete="off" spellcheck="false" aria-describedby="resume-extra-hint"></div>
        <p class="hint" id="resume-extra-hint">The check knows the common skills and the ones in your profile. Add the name of a tool it does not know.</p>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-match">Run the ATS match</button></div>
        <p id="resume-match-status" role="status"></p>
        <div id="resume-match-out" hidden>
          <h3 id="resume-match-band" tabindex="-1"></h3>
          <p class="hint" id="resume-match-job"></p>
          <p class="notice" id="resume-match-notice"></p>
          <ul class="resume-cats" id="resume-match-factors" aria-label="What the match is made of"></ul>
          <p id="resume-match-skills"></p>
          <div id="resume-enrich" hidden>
            <h3 id="h-resume-enrich">Done it, but it is not on your resume?</h3>
            <p class="hint">If you have really used one of these, say what you did in your own words. Nothing is added until you press a button. The AI helper, if you
            ask it, can only word what you said: it cannot add to it.</p>
            <ul id="resume-enrich-list" aria-labelledby="h-resume-enrich"></ul>
          </div>
          <h3 id="h-resume-evidence">What the job asks for, and where your resume shows it</h3>
          <ul class="resume-fixes" id="resume-match-evidence" aria-labelledby="h-resume-evidence"></ul>
          <details class="resume-block"><summary>Words the job repeats</summary><ul id="resume-match-terms"></ul></details>
        </div>
      </section>
      <section class="card" id="resume-tailor-card" role="tabpanel" aria-labelledby="rtab-tailor" hidden>
        <h2 id="h-resume-tailor" tabindex="-1">Tailor it to the job</h2>
        <p>You get a short list of small changes, each shown as before and after with the reason. Accept the ones that are true of you. They go into a new copy named for
        the job: the resume you are editing does not change, and nothing is added that your resume does not already say.</p>
        <div class="field"><label for="resume-strength">How much to change</label><select id="resume-strength" aria-describedby="resume-strength-note"></select></div>
        <p class="hint" id="resume-strength-note"></p>
        <label class="check" for="resume-tailor-ai"><input type="checkbox" id="resume-tailor-ai" checked> Ask the AI helper too</label>
        <p class="hint" id="resume-tailor-ai-note">Sends the text of your bullets (no name, contact details or employer names) and the job description to the AI you chose. Without
        it, the only change offered is putting the skills the job asks for first.</p>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-tailor-go">Suggest changes</button></div>
        <p id="resume-tailor-status" role="status"></p>
        <div id="resume-tailor-out" hidden>
          <h3 id="resume-tailor-title" tabindex="-1"></h3>
          <p class="hint" id="resume-tailor-notes"></p>
          <div class="controls">
            <button class="btn btn-small" type="button" id="resume-tailor-all">Accept all</button>
            <button class="btn btn-small" type="button" id="resume-tailor-none">Accept none</button>
          </div>
          <ul class="resume-changes" id="resume-tailor-list" aria-label="Suggested changes"></ul>
          <p class="hint" id="resume-tailor-refused"></p>
          <div class="field"><label for="resume-tailor-name">Name of the new copy</label>
          <input id="resume-tailor-name" type="text" maxlength="80" autocomplete="off"></div>
          <div class="controls"><button class="btn btn-primary" type="button" id="resume-tailor-apply" disabled>Make a copy with the accepted changes</button></div>
          <p id="resume-tailor-done" role="status"></p>
        </div>
      </section>
      <section class="card" id="resume-check-card" role="tabpanel" aria-labelledby="rtab-check" hidden>
        <h2 id="h-resume-check" tabindex="-1">ATS check: can software read it?</h2>
        <p>Is this resume ATS-friendly? One press prints the PDF you would send, reads it back the way a parser does, checks what you wrote, and gives one answer with the
        first things to fix. The two checks underneath are the details.</p>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-ats-run">Run the full ATS check</button></div>
        <div id="resume-ats-verdict" hidden></div>
        <div class="controls">
          <button class="btn" type="button" id="resume-check" aria-describedby="resume-check-hint">Check what I wrote</button>
          <button class="btn" type="button" id="resume-pdfcheck" aria-describedby="resume-check-hint">Check the PDF only</button>
        </div>
        <p class="hint" id="resume-check-hint">"Check what I wrote" reads your details and bullets (and, if you gave a job in the ATS match tab, the skills it asks for). "Check the PDF only" prints the PDF
        and reads it back: it catches columns, lost text and a wrong order that the first cannot see.</p>
        <p id="resume-check-status" role="status"></p>
        <div id="resume-pdf" hidden>
          <p class="resume-caption">Details: the PDF file</p>
          <h3 id="resume-pdf-score" tabindex="-1"></h3>
          <ul class="resume-cats" id="resume-pdf-cats" aria-label="The PDF check, by part"></ul>
          <ul class="resume-fixes" id="resume-pdf-fixes" aria-label="What the PDF check found"></ul>
          <h3 id="h-resume-pdf-fields">What came through the PDF</h3>
          <ul id="resume-pdf-fields" aria-labelledby="h-resume-pdf-fields"></ul>
          <details class="resume-block"><summary>The text a parser reads from your PDF</summary>
          <pre id="resume-pdf-text" tabindex="0" aria-label="The text read from your PDF"></pre></details>
        </div>
        <div id="resume-report" hidden>
          <p class="resume-caption">Details: what you wrote</p>
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
      <section class="card" id="resume-use-card" role="tabpanel" aria-labelledby="rtab-use" hidden>
        <h2 id="h-resume-use" tabindex="-1">Use it for my applications</h2>
        <p id="resume-use-now"></p>
        <p>This prints the resume as a PDF and makes it the resume your runs send (the one on the Profile tab). Skills it mentions that are not in your profile are
        added there with no years, never with numbers made up for you. Your earlier resume file stays in the data folder.</p>
        <label class="check" for="resume-use-sure"><input type="checkbox" id="resume-use-sure"> Yes, use this resume from now on</label>
        <div class="controls"><button class="btn btn-primary" type="button" id="resume-use" disabled>Use this resume</button></div>
        <p id="resume-use-status" role="status"></p>
      </section>
    </div>"""
