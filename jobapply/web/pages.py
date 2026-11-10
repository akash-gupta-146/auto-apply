"""HTML for the profile and AI-helper forms.

No JavaScript on purpose: nothing to break, it works in any browser, and screen readers get plain
labelled controls. Every piece of user text goes through `escape`. (The control panel's page is in panel_page.py.)
"""
from __future__ import annotations

import dataclasses
from html import escape
from typing import Callable, List, Mapping, Sequence, Tuple

from ..ai_providers import MAX_CUSTOM, STYLES
from ..ai_settings import PROVIDERS, AiSettings, Provider
from .ai_form import AI_FIELDS, MAX_BACKUPS, backup_fields
from .help import help_button, topic_list
from .forms import (ADD_SKILL, CRITERIA_FIELDS, MAX_SKILL_NAME, MAX_SKILL_YEARS, PROFILE_FIELDS, SKILL_NAME, SKILL_YEARS,
                    Field)
from .questions import MAX_ANSWER_CHARS, field_name

AUTOCOMPLETE = {"name": "name", "email": "email", "phone": "tel"}
INPUT_TYPE = {"text": "text", "list": "text", "email": "email", "tel": "tel", "number": "number", "integer": "number", "percent": "number",
              "password": "password"}
NUMBER_ATTRS = {
    "number": ' step="any" min="0" inputmode="decimal"',
    "integer": ' step="1" min="1" inputmode="numeric"',
    "percent": ' step="1" min="0" max="100" inputmode="numeric"',
}

def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title><link rel="stylesheet" href="/static/theme.css"></head><body>'
        f'<nav class="top"><a href="/">&larr; Control panel</a></nav><main class="page">{body}</main></body></html>'
    )


def _token(token: str) -> str:
    return f'<input type="hidden" name="token" value="{escape(token, quote=True)}">'


def upload_page(token: str, error: str = "", has_saved_profile: bool = False) -> str:
    alert = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    edit = '<p><a href="/form">I have already done this: edit my saved details</a></p>' if has_saved_profile else ""
    return _page("Set up your profile", f"""
<h1>Set up your profile</h1>
<section>
<h2>Step 1 of 2: your resume</h2>
<p>Choose your resume. It is copied into this program's own <code>data</code> folder and read on this
computer only; nothing is sent anywhere. I use it to pre-fill the next page.</p>
{alert}
<form method="post" action="/resume" enctype="multipart/form-data">
{_token(token)}
<label for="resume">Resume file (PDF, DOCX or TXT, up to 10 MB)</label>
<input id="resume" name="resume" type="file" accept=".pdf,.docx,.txt" required>
<button type="submit">Read my resume</button>
</form>
</section>
{edit}
<p><a href="/ai">Optional: set up the AI helper</a></p>""")


def _field(spec: Field, values: Mapping[str, str], errors: Mapping[str, str]) -> str:
    fid = f"f-{spec.name}"
    label = escape(spec.label)
    if spec.kind == "checkbox":
        checked = " checked" if values.get(spec.name) else ""
        return (f'<div class="check"><input id="{fid}" name="{spec.name}" type="checkbox"{checked}>'
                f'<label for="{fid}">{label}</label></div>')
    described = [i for i, present in ((f"{fid}-hint", spec.hint), (f"{fid}-err", spec.name in errors)) if present]
    attrs = (f' aria-describedby="{" ".join(described)}"' if described else "")
    attrs += ' aria-invalid="true"' if spec.name in errors else ""
    attrs += f' autocomplete="{AUTOCOMPLETE[spec.name]}"' if spec.name in AUTOCOMPLETE else ""
    attrs += NUMBER_ATTRS.get(spec.kind, "")
    attrs += " required" if spec.required else ""
    mark = ' <span class="req">(required)</span>' if spec.required else ""
    value = escape(values.get(spec.name, ""), quote=True)
    hint = f'<p class="hint" id="{fid}-hint">{escape(spec.hint)}</p>' if spec.hint else ""
    error = f'<p class="error" id="{fid}-err">{escape(errors[spec.name])}</p>' if spec.name in errors else ""
    if spec.kind == "textarea":
        return (f'<label for="{fid}">{label}{mark}</label>'
                f'<textarea id="{fid}" name="{spec.name}" rows="6"{attrs}>{value}</textarea>{hint}{error}')
    if spec.kind == "password":  # a saved key is never sent back to the page
        value, attrs = "", attrs + ' autocomplete="off"'
    return (f'<label for="{fid}">{label}{mark}</label>'
            f'<input id="{fid}" name="{spec.name}" type="{INPUT_TYPE[spec.kind]}" value="{value}"{attrs}>{hint}{error}')


def _skills(rows: Sequence[Tuple[str, str]], errors: Mapping[str, str], focus_last: bool = False) -> str:
    """One pair of boxes per row: the skill and the years. A person adds rows with the button (a page with no
    JavaScript cannot grow a row by itself, so the button asks the server for one more) and removes one by clearing it.
    focus_last: the row was just added, so put the cursor in it (the page has reloaded at the top)."""
    cells = []
    for n, (name, years) in enumerate(rows):
        for prefix, label, attrs, value in (
            (SKILL_NAME, f"Skill {n + 1}", f'type="text" maxlength="{MAX_SKILL_NAME}" placeholder="e.g. React"', name),
            (SKILL_YEARS, f"Years for skill {n + 1}",
             f'type="number" step="any" min="0" max="{MAX_SKILL_YEARS}" inputmode="decimal" placeholder="years"', years),
        ):
            key = f"{prefix}{n}"
            extra = ' aria-invalid="true"' if key in errors else ""
            extra += " autofocus" if focus_last and prefix == SKILL_NAME and n == len(rows) - 1 else ""
            cells.append(f'<div><label for="{key}">{label}</label>'
                         f'<input id="{key}" name="{key}" {attrs} value="{escape(value, quote=True)}"{extra} aria-describedby="skills-hint"></div>')
    return f"""<fieldset><legend>Your skills and years of experience</legend>
<p class="hint" id="skills-hint">Add the skills you can stand behind, each with the years you have used it. These are the
answers given when an application asks "years of experience in ..."; a skill you do not list is never answered, so
nothing is made up. To remove a skill, clear its name and years.</p>
<div class="skills">{"".join(cells)}</div>
<button type="submit" name="{ADD_SKILL}" value="1" formnovalidate>Add another skill</button>
</fieldset>"""


def _error_target(key: str) -> str:
    """The id of the input an error belongs to, so the summary can link straight to it."""
    return key if key.startswith((SKILL_NAME, SKILL_YEARS)) else f"f-{key}"


def _summary(errors: Mapping[str, str], target: Callable[[str], str]) -> str:
    """The box at the top listing every mistake, each one linking to the field it belongs to."""
    if not errors:
        return ""
    items = "".join(f'<li><a href="#{target(key)}">{escape(message)}</a></li>' for key, message in errors.items())
    return (f'<div class="summary" role="alert"><strong>Please fix {len(errors)} thing(s):</strong>'
            f"<ul>{items}</ul></div>")


def _banner(banner: Tuple[str, str]) -> str:
    """A message at the top of a page: ('ok', text) is good news, anything else is a problem. A new line in the text
    starts a new line on the page."""
    kind, text = banner
    if not text:
        return ""
    shown = "<br>".join(escape(line) for line in text.splitlines())
    return (f'<div class="ok" role="status">{shown}</div>' if kind == "ok"
            else f'<div class="summary" role="alert">{shown}</div>')


def _ai_fill(provider: str) -> str:
    """The AI Fill card. provider is the name of the AI that will read the resume, or empty when none is set up."""
    if not provider:
        return ('<fieldset class="aifill"><legend>Fill it in from your resume</legend>'
                '<button type="submit" name="ai_fill" value="1" formnovalidate disabled aria-describedby="aifill-hint">AI Fill</button>'
                '<p class="hint" id="aifill-hint">To use this, <a href="/ai">set up the AI helper</a> first (an AI, a model and a key).</p>'
                "</fieldset>")
    return ('<fieldset class="aifill"><legend>Fill it in from your resume</legend>'
            '<button type="submit" name="ai_fill" value="1" formnovalidate aria-describedby="aifill-hint">AI Fill</button>'
            '<p class="hint" id="aifill-hint">An AI reads your resume and fills the <strong>empty</strong> boxes below: your '
            "details, job titles, keywords and skills. It must back every suggestion with words from your resume, and it "
            "never changes what you have typed. Check what it fills before you save. This sends the text of your resume "
            f"(email and phone number removed) to {escape(provider)}, and can take up to a minute.</p></fieldset>")


def form_page(token: str, values: Mapping[str, str], errors: Mapping[str, str],
              skill_rows: Sequence[Tuple[str, str]], resume_name: str, focus_new_skill: bool = False,
              banner: Tuple[str, str] = ("", ""), ai_provider: str = "") -> str:
    summary = _summary(errors, _error_target)
    about = "".join(_field(spec, values, errors) for spec in PROFILE_FIELDS)
    wanted = "".join(_field(spec, values, errors) for spec in CRITERIA_FIELDS)
    return _page("Your details", f"""
<h1>Your details</h1>
<p>Step 2 of 2. Resume: <strong>{escape(resume_name)}</strong> (<a href="/">choose another</a>).
I filled in what I could read from it, and left blank what it does not say: please check every field.</p>
{_banner(banner)}{summary}
<form method="post" action="/save">
{_token(token)}
<!-- Enter in a box presses the FIRST submit button in the form. That must be Save, not "AI Fill" or "Add another
     skill", so Save comes first here, out of sight and out of the tab order; the visible one is at the bottom. -->
<button type="submit" class="sr-only" tabindex="-1" aria-hidden="true">Save my profile</button>
{_ai_fill(ai_provider)}
<fieldset><legend>About you</legend>{about}</fieldset>
<fieldset><legend>Which jobs to apply for</legend>{wanted}</fieldset>
{_skills(skill_rows, errors, focus_new_skill)}
<button type="submit">Save my profile</button>
</form>""")


def _example(text: str) -> str:
    """A model name looks like code; a sentence about one does not."""
    return f"for example <code>{escape(text)}</code>" if " " not in text else escape(text)


def _provider_choices(chosen: str, errors: Mapping[str, str], providers: Mapping[str, Provider]) -> str:
    rows = []
    for index, (key, provider) in enumerate(providers.items()):
        checked = " checked" if key == chosen else ""
        required = " required" if index == 0 else ""  # one 'required' covers the whole group
        if provider.key_page:
            example = (f"Copy the model name from the list, {_example(provider.model_example)}." if " " not in provider.model_example
                       else f"Copy the model name from the list. {escape(provider.model_example[0].upper() + provider.model_example[1:])}.")
            hint = (f'<a href="{escape(provider.key_page)}" rel="noopener noreferrer">{escape(provider.key_label)}</a> &middot; '
                    f'<a href="{escape(provider.models_page)}" rel="noopener noreferrer">Model names</a>'
                    + help_button(f"p-{key}", f"model names and notes for {provider.label}",
                                  example + (f"<br><br>{escape(provider.note)}" if provider.note else "")))
        else:  # one the person added: we only know its address
            hint = f"Added by you. Address: <code>{escape(provider.base_url)}</code>"
        rows.append(
            f'<div class="check"><input id="p-{key}" name="provider" type="radio" value="{key}"{checked}{required}>'
            f'<label for="p-{key}">{escape(provider.label)}</label></div><p class="hint">{hint}</p>')
    error = f'<p class="error">{escape(errors["provider"])}</p>' if "provider" in errors else ""
    warning = ('<p class="hint"><strong>These are developer keys, not your chat subscription.</strong> A ChatGPT Plus or '
               'Claude Pro plan does not include one. Each company bills its own key separately, so check its pricing '
               'page. OpenRouter has free models, and Ollama is free and runs on your own computer. '
               'Is yours not listed? <a href="#add-ai">Add it further down this page</a>.</p>')
    return f'<fieldset><legend>Which AI?</legend>{warning}{"".join(rows)}{error}</fieldset>'


def _backups(values: Mapping[str, str], errors: Mapping[str, str], saved: AiSettings) -> str:
    """Rows for the AIs to ask, in order, when the main one errors. An empty row is no backup."""
    providers = saved.providers()
    rows = []
    for slot in range(1, MAX_BACKUPS + 1):
        name_provider, name_model, name_key = backup_fields(slot)
        chosen = values.get(name_provider, "")
        options = '<option value="">No backup</option>' + "".join(
            f'<option value="{key}"{" selected" if key == chosen else ""}>{escape(provider.label)}</option>'
            for key, provider in providers.items())
        old = saved.backups[slot - 1] if slot <= len(saved.backups) and saved.backups[slot - 1].provider == chosen else None
        key_hint = (f"A key is already saved ({old.masked_key}). Leave this blank to keep it." if old and old.masked_key
                    else "Leave this blank to use the main AI's key, if this is the same company. Ollama needs no key.")
        problem = (f'<p class="error" id="f-{name_provider}-err">{escape(errors[name_provider])}</p>'
                   if name_provider in errors else "")
        rows.append(
            f'<fieldset><legend>Backup {slot}</legend><label for="f-{name_provider}">Which AI</label>'
            f'<select id="f-{name_provider}" name="{name_provider}">{options}</select>{problem}'
            f'{_field(Field(name_model, "Model name"), values, errors)}'
            f'{_field(Field(name_key, "API key", "password", hint=key_hint), values, errors)}</fieldset>')
    about = help_button("backups", "backup AIs",
                        "When the main AI errors (a full free quota, a bad key, it being down), the next one here is asked instead, "
                        "then the next. An AI that failed is left alone for a while so that it is not asked on every question. "
                        "Another model of the same company is fine too.")
    return ("<fieldset><legend>If that AI fails, ask these (optional)</legend>"
            '<p class="hint">Anything the AI would be sent may go to whichever of these answers, so add only companies you are '
            f'happy to share it with.{about}</p>{"".join(rows)}</fieldset>')


def _custom_providers(token: str, saved: AiSettings, values: Mapping[str, str], errors: Mapping[str, str]) -> str:
    """The AIs the person added (each can be removed), and a form to add one that is not in the list."""
    items = "".join(
        f'<li>{escape(custom.label)} <code>{escape(custom.base_url)}</code>'
        f'<form method="post" action="/ai/provider/remove" class="inline">{_token(token)}'
        f'<input type="hidden" name="id" value="{escape(key, quote=True)}">'
        f'<button class="small" type="submit" aria-label="Remove {escape(custom.label, quote=True)}">Remove</button></form></li>'
        for key, custom in saved.custom.items())
    chosen_style = values.get("custom_style", "openai")
    styles = "".join(f'<option value="{key}"{" selected" if key == chosen_style else ""}>{escape(text)}</option>'
                     for key, text in STYLES.items())
    style_error = f'<p class="error" id="f-custom_style-err">{escape(errors["custom_style"])}</p>' if "custom_style" in errors else ""
    needs_key = {"custom_needs_key": "1"} if values.get("custom_needs_key", "1") else {}
    about = help_button("add-ai", "adding an AI that is not in the list",
                        "Most services use the <strong>OpenAI-compatible</strong> format (Groq, Together, Mistral, DeepSeek, "
                        "LM Studio, vLLM and many more). The address is the one up to, but not including, <code>/chat/completions</code>. "
                        "It must start with <code>https://</code>, because your key is sent to it; plain <code>http://</code> is accepted "
                        "only for a computer on your own network (localhost, 192.168..., 10..., .local). "
                        f"You can add up to {MAX_CUSTOM}. You cannot remove the AI you use as your main one.")
    return ("<section id=\"add-ai\"><h2>An AI that is not in the list?" + about + "</h2>"
            '<p>Add any AI service that speaks one of the formats below, then choose it above. '
            f'{"Added so far:" if items else ""}</p>{"<ul>" + items + "</ul>" if items else ""}'
            f'<form method="post" action="/ai/provider">{_token(token)}'
            f'{_field(Field("custom_name", "Name", required=True, hint="Anything you will recognise, for example My company AI."), values, errors)}'
            f'{_field(Field("custom_url", "Address", required=True, hint="The API address, up to but not including /chat/completions. For example https://api.groq.com/openai/v1"), values, errors)}'
            f'<label for="f-custom_style">Format it speaks</label><select id="f-custom_style" name="custom_style">{styles}</select>{style_error}'
            f'{_field(Field("custom_needs_key", "It needs an API key", "checkbox"), needs_key, errors)}'
            '<button type="submit">Add this AI</button></form></section>')


def _documents(token: str, names: List[str]) -> str:
    if not names:
        return "<p>No extra documents yet. Your resume is always included.</p>"
    items = "".join(
        f'<li>{escape(name)}<form method="post" action="/ai/remove" class="inline">{_token(token)}'
        f'<input type="hidden" name="name" value="{escape(name, quote=True)}">'
        f'<button class="small" type="submit" aria-label="Remove {escape(name, quote=True)}">Remove</button></form></li>'
        for name in names)
    return f"<ul>{items}</ul>"


def _ai_target(key: str) -> str:
    return {"provider": f"p-{next(iter(PROVIDERS))}", "about_file": "f-about_file"}.get(key, f"f-{key}")


# What the AI helper does, one line each; the "?" on a line holds the rest. (key, title, the full explanation)
WHAT_IT_DOES = (
    ("only-docs", "It may only use what is written in your documents",
     "For every answer it must quote the sentence it used. If that quote is not really in your documents, or the answer contains "
     "a number that is not in them, the answer is thrown away and that job waits for you."),
    ("saved-first", "Your own saved answers and the built-in rules come first",
     "The AI gets what is left. It also reads the answers you gave on the Questions page (except ones about consent, like "
     "&ldquo;I certify&hellip;&rdquo;), so when a question comes back in other words it answers as you did before, and the run "
     "report shows which saved answer it used. A wrong one can be removed on that page."),
    ("job-descriptions", "It also reads job descriptions",
     "For a job the rules would skip only because of its title (say &ldquo;Software Developer - SDE II&rdquo; that is really React "
     "work), it reads the description against your documents and decides whether you fit. It must quote two real lines from your "
     "documents as proof, and it can never override a company you blocked, a role you skip or your salary minimum. Approved jobs "
     "are marked <em>AI fit</em> in the run report."),
    ("report", "Every answer it writes is listed in the run report so you can check it", ""),
    ("ai-fill", "AI Fill, a button on the details form",
     "It uses the same AI to suggest what goes in the empty boxes there: your details, job titles, keywords and skills. Each "
     "suggestion has to be backed by your resume, it never changes what you have typed, and nothing is saved until you press Save. "
     "It sends only your resume text, only when you press the button."),
    ("sent", "What is sent to the AI company (nothing leaves your computer if you choose Ollama)",
     "The text of your resume, documents and notes, the answers you saved on the Questions page (email addresses and phone numbers "
     "removed) and your profile facts (never your name, email or phone). Only the first 40,000 characters are used. For each job it "
     "reads, that job&rsquo;s public description is sent too. Nothing is sent unless you switch the AI helper on for a run. If you "
     "add backup AIs, whatever would go to the main AI goes to a backup when the main one errors."),
    ("linkedin", "LinkedIn",
     "The AI helper never reads LinkedIn itself. Instead, open your own LinkedIn profile, choose <em>More</em>, then "
     "<em>Save to PDF</em>, and add that file below."),
    ("naukri-forms", "Naukri jobs with a separate screening form still wait for you",
     "The AI only helps with questions the program can see."),
)


def ai_page(token: str, values: Mapping[str, str], errors: Mapping[str, str], saved: AiSettings,
            documents: List[str], banner: Tuple[str, str] = ("", "")) -> str:
    kind, text = banner
    note = _banner(banner)
    specs = [dataclasses.replace(spec, hint=f"A key is already saved ({saved.masked_key}). Leave this blank to keep it.")
             if spec.name == "api_key" and saved.masked_key else spec for spec in AI_FIELDS]
    fields = {spec.name: _field(spec, values, errors) for spec in specs}
    file_error = (f'<p class="error" id="f-about_file-err">{escape(errors["about_file"])}</p>'
                  if "about_file" in errors else "")
    return _page("The AI helper", f"""
<h1>The AI helper (optional)</h1>
<section>
<h2>What it does</h2>
<p>Some job forms ask things your profile cannot answer, like &ldquo;Have you led a team?&rdquo;. When you switch the AI helper on
in the control panel, an AI of your choice reads your resume and the documents you add here, and answers
those questions for you.</p>
{topic_list(WHAT_IT_DOES)}
</section>
{note}{_summary(errors, _ai_target)}
<section>
<h2>Documents the AI can read</h2>
{_documents(token, documents)}
</section>
<form method="post" action="/ai/save" enctype="multipart/form-data">
{_token(token)}
{_provider_choices(values.get("provider", ""), errors, saved.providers())}
<fieldset><legend>Your key</legend>{fields["model"]}{fields["api_key"]}{fields["daily_cap"]}</fieldset>
{_backups(values, errors, saved)}
<fieldset><legend>About you</legend>
<label for="f-about_file">Add a document (PDF, DOCX or TXT, up to 10 MB)</label>
<input id="f-about_file" name="about_file" type="file" accept=".pdf,.docx,.txt">
<p class="hint">For example your LinkedIn &ldquo;Save to PDF&rdquo;. To add several, save once per file.</p>{file_error}
{fields["notes"]}</fieldset>
<button type="submit">Save</button>
</form>
{_custom_providers(token, saved, values, errors)}
<section>
<h2>Check that it works</h2>
<p>Save first, then test. This sends one tiny message to each AI you set up, the main one and any backups, and says which
work. None of your documents are sent.</p>
<form method="post" action="/ai/test">{_token(token)}<button type="submit">Test the connection</button></form>
</section>
<p><a href="/">Back to the control panel</a></p>""")


def _question(item: Mapping[str, object], index: int) -> str:
    """One waiting question: a radio button per choice when the form gave choices, else a text box."""
    name = escape(field_name(str(item["norm"])), quote=True)
    where = f' <small>({escape(str(item["portal"]))})</small>' if item["portal"] else ""
    options = item["options"]
    if options:
        controls = "".join(
            f'<div class="check"><input type="radio" id="q{index}-{n}" name="{name}" value="{escape(str(option), quote=True)}">'
            f'<label for="q{index}-{n}">{escape(str(option))}</label></div>' for n, option in enumerate(options))
        return f"<fieldset><legend>{escape(str(item['raw']))}{where}</legend>{controls}</fieldset>"
    return (f'<div class="field"><label for="q{index}">{escape(str(item["raw"]))}{where}</label>'
            f'<input id="q{index}" name="{name}" type="text" maxlength="{MAX_ANSWER_CHARS}"></div>')


def _saved_row(token: str, index: int, question: str, answer: str) -> str:
    """One saved answer: the question as plain text, your answer in bold, an Edit that opens in place, and Remove."""
    asked, hidden = escape(question, quote=True), f'<input type="hidden" name="question" value="{escape(question, quote=True)}">'
    return (
        f'<li><div class="what"><span class="q">{escape(question)}</span><br><strong>{escape(answer)}</strong>'
        f'<details class="edit"><summary>Edit</summary>'
        f'<form method="post" action="/questions/edit">{_token(token)}{hidden}'
        f'<input type="text" name="answer" id="edit-{index}" value="{escape(answer, quote=True)}" maxlength="{MAX_ANSWER_CHARS}"'
        f' aria-label="Your answer to: {asked}">'
        f'<button type="submit" class="small">Save</button></form></details></div>'
        f'<form method="post" action="/questions/forget">{_token(token)}{hidden}'
        f'<button type="submit" class="small" aria-label="Remove my saved answer to: {asked}">Remove</button></form></li>')


def _saved_answers(token: str, saved: Sequence[Tuple[str, str]], opened: bool = False) -> str:
    """What you have answered so far, in a dropdown (it gets long): each can be changed or taken back, because the AI learns from them.
    It stays open after you edit or remove one, so you can carry on down the list."""
    if not saved:
        return ""
    rows = "".join(_saved_row(token, index, question, answer) for index, (question, answer) in enumerate(saved))
    return f"""
<section>
<details class="saved-list"{" open" if opened else ""}>
<summary>Your saved answers ({len(saved)})</summary>
<p class="saved-note">These stay on this computer. A job that asks the same thing in the same words is answered from them, and
with the AI helper on it reads them too (the AI company gets them, unless you chose Ollama; consent questions are never shown to
it), so it can answer the same question put in other words. The run report says which saved answer it used. If one is wrong,
edit or remove it.</p>
<ul class="saved">{rows}</ul>
</details>
</section>"""


def questions_page(token: str, items: Sequence[Mapping[str, object]], banner: Tuple[str, str] = ("", ""),
                   saved: Sequence[Tuple[str, str]] = (), saved_open: bool = False) -> str:
    """What runs could not answer for you. Answer once: the answer is used for every job that asks the same thing."""
    if items:
        body = (f'<form method="post" action="/questions/save">{_token(token)}'
                + "".join(_question(item, index) for index, item in enumerate(items))
                + '<button type="submit">Save my answers</button></form>')
    else:
        body = "<p>Nothing is waiting for you. When a job asks something your profile cannot answer, it shows up here.</p>"
    return _page("Questions waiting for you", f"""
<h1>Questions waiting for you</h1>
{_banner(banner)}
<section>
<p>While a run is going, a job that asks one of these waits up to 5 minutes for your answer here, then it is skipped and
the run moves on. Answer only what is true for you: your answer is saved on this computer and used for every later job
that asks the same thing. Leave a question blank to skip it.</p>
{body}
</section>{_saved_answers(token, saved, saved_open)}""")


def done_page(name: str, resume_name: str, profile_file: str, criteria_file: str) -> str:
    return _page("Saved", f"""
<h1>Saved, {escape(name)}</h1>
<section>
<p>Resume: <strong>{escape(resume_name)}</strong><br>
Details saved to <code>{escape(profile_file)}</code> and <code>{escape(criteria_file)}</code>.
You can change them any time.</p>
</section>
<section>
<h2>What to do next</h2>
<p>Go back to the control panel. It shows the next step for you: open the browser, log in to Naukri, check it can see
jobs, rehearse, then apply.</p>
<p><a class="button" href="/">Back to the control panel</a></p>
</section>""")
