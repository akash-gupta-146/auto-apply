# User guide: how to use the control panel

This is the walk-through. It tells you what each part of the panel is for and what to press, in the order you will need it.
The [README](README.md) is the reference: it has every rule, every option and every error message. This guide links to it
wherever you want more.

**Contents:** [Before you start](#before-you-start) · [Quick start](#quick-start-your-first-15-minutes) · [The panel at a glance](#the-panel-at-a-glance) ·
[Apply on a site](#tab-1-apply-on-a-site) · [Auto-apply v2](#tab-2-auto-apply-v2) · [Auto fill form](#tab-3-auto-fill-form) · [Create Resume](#tab-4-create-resume) · [Profile](#tab-5-profile) ·
[The other pages](#the-other-pages) · [Recipes](#recipes-i-want-to) · [Keyboard and screen readers](#keyboard-and-screen-readers) ·
[Where your files are](#where-your-files-are) · [Getting updates](#getting-updates) · [When something goes wrong](#when-something-goes-wrong) · [Words used](#words-used)

---

## Before you start

- **It is a program on your own computer.** The panel is a web page that opens in your browser, but it only answers *your* computer. Nothing is
  uploaded to a server. (Details: [The panel is a local program](README.md#the-panel-is-a-local-program-not-a-website).)
- **Rehearse before you apply.** A *rehearsal* does everything except send. Run one first, and again whenever you change your rules.
- **Not everything is proven.** Naukri's login check, job search and one-click *Quick apply* were tested on the live site. Naukri's screening-question
  side bar, LinkedIn, Indeed, Instahyre, Wellfound, Windows and the AI features were not (or only against stand-in pages). The table at
  [What is proven and what is not](README.md#read-this-first-what-is-proven-and-what-is-not) is the truth; read it once.
- **Job sites can forbid automation.** LinkedIn and Indeed say so in their rules and can restrict an account. It is your account and your decision.
  The program works slowly on purpose (20 to 90 seconds between jobs) and **never solves a captcha**: it waits for you.
- **You never need an AI account.** The matching and form-filling are plain rules. The AI helper is optional and only answers *new* questions.

## Quick start: your first 15 minutes

1. **Start it.** Unzip, then double-click `Start.bat` (Windows) or `Start.command` (Mac). The first time it installs itself (a few minutes);
   after that it just opens the panel. Keep its window open while you work. The Mac needs two one-time steps first: see
   [Start](README.md#start).
2. **Profile and resume** (Apply tab, step 1). Choose your resume (PDF, DOCX or TXT). Its boxes fill from what it says; anything it does not say
   stays blank. Add your skills, each with its years. Save.
3. **Job rules.** On the same form: *Job titles to apply for*, *Locations*, *Titles to skip*, *Companies to never apply to*, *Minimum skill match, in %*
   and *Most applications in one run*. (A few more rules live in `data/criteria.yaml`: see
   [Changing things later](README.md#changing-things-later).)
4. **Open the browser** (step 2). A separate browser window opens. **Log in to each site you use, in that window, once**, and leave it open.
5. **Check the site** (step 3). A read-only test: are you logged in, and can it see jobs? It applies to nothing.
6. **Rehearse** (step 4). Watch the **Output** on the right. Read the report it opens.
7. **Apply for real** (step 5), with **3** applications. You must type `YES`. Check the report and the site's own "Applied jobs" page.
8. Happy? Raise the number, or switch to **Auto-apply v2**, which shows you each job first.

Then, if you want to: set up the [AI helper](#the-ai-helper-optional), build a resume in the [Create Resume tab](#tab-4-create-resume), and read
[Recipes](#recipes-i-want-to).

## The panel at a glance

The header has the program's name, your computer type and a **Quit** button (press it twice; it will not quit while a run is going, so press
**Stop** first). Under it:

- **Which site?** Naukri, Instahyre, LinkedIn, Indeed or Wellfound. Each site keeps its own login check and its own counts, and the page remembers
  your choice.
- **Five tabs:** [Apply on a site](#tab-1-apply-on-a-site), [Auto-apply v2](#tab-2-auto-apply-v2), [Auto fill form](#tab-3-auto-fill-form), [Create Resume](#tab-4-create-resume) and
  [Profile](#tab-5-profile). The first three have the **Output** beside them. The Create Resume and Profile tabs use the whole width.
- **Output:** what the current run is doing, live. **Stop** ends it politely: it finishes the page it is on and writes its report. Only one thing
  runs at a time.
- **Reports:** every run writes one. The newest opens by itself when a run ends. Unread ones are **bold, blue, with a dot**. **Delete** takes two presses.

Short explanations hide behind small **?** buttons: rest the mouse on one, or Tab to it. Anything you must see before deciding is always in view.

---

## Tab 1: Apply on a site

The five steps, top to bottom. Use them in order the first time.

| Step | What it does | Press it when |
|---|---|---|
| **1. Your details** | Opens the profile form (see [The profile form](#the-profile-form)). | First time, and whenever your details change. |
| **2. Open the browser** | Opens the separate browser the program controls. You log in there. | First time; again if you closed its last window. |
| **3. Check the site** | Read-only: logged in? can it see jobs? | Before a run, or when something looks wrong. |
| **4. Rehearse** | Walks through jobs and fills forms, **never submits**. | Always before a real run, and after changing rules. |
| **5. Apply for real** | Sends real applications. Asks how many and for how long, and you type `YES`. | After a rehearsal looks right. Start with 3 (1 on LinkedIn, Indeed, Instahyre). |

**Also re-check jobs skipped earlier.** A normal run leaves alone jobs it already turned away. After you change your rules, tick this box (in Rehearse or
Apply for real) to give them another look. Jobs you already applied to are never sent twice.

**The daily limit.** Real runs stop at **25 applications per site per day** (counted across every run). You can change it under *Daily limit* on the
Auto-apply v2 tab. A rehearsal sends nothing and has no limit.

**What the report statuses mean.** `applied` (the site itself shows it as applied afterwards; **Instahyre confirms nothing, so there an Apply press that raised no error counts as applied**, and the reason says so), `dry_run_ok` (a rehearsal would have applied),
`skipped_match` (your rules said no, with the reason), `skipped_external` (it needs you, or applies on the company's own site), `needs_answer`
(a form asked something your profile could not answer) and `failed` (it breaks and is tried again). Full list:
[What the report statuses mean](README.md#what-the-report-statuses-mean).

## Tab 2: Auto-apply v2

The easy way to do steps 1 to 5 together, **with you in charge of every job.**

1. **Is everything ready?** A checklist (profile and resume, roles, browser, login) with *Ready*, *To do* or *Optional*, and a button to the place
   that fixes each one.
2. Choose the site and the most jobs, then press **Start auto-apply**.
3. **Now:** the job it is about to apply to appears with its title, company, place, what it asks for and *why it fits*. Press **Apply to it** or
   **Skip it** (a skipped job is remembered as turned away). A badge says *your turn* if you are on another tab. If you ignore it for **two jobs in a
   row** the run stops and nothing more is sent. **Pause** holds the run between applications; **Stop** ends it.
4. **What happened:** every job a run acted on, newest first. Filter by outcome, date, company or words, and **Download as a spreadsheet (CSV)**.

**Apply by itself** skips the asking (you type `YES` first). Details and the limits: [Auto-apply](README.md#auto-apply-let-it-work-through-jobs-asking-you-first).

## Tab 3: Auto fill form

This tab runs **the AI agent**, for a job page the site-specific code does not know. It reads whatever page is open in the automation browser, works out what kind of page it is, and
fills it in. It is **experimental** and has only been tried against stand-in sites.

1. Open the job in the browser from step 2 (or paste its address into *Job page address*).
2. Set the minutes. Tick *Use the AI helper* if you want it to answer new questions and read pages the rules cannot.
3. Press **Start the agent**. With *Let it send applications* **off** it is a rehearsal: it fills everything and stops before the last button.
4. To really send, turn that on and type `YES`. The agent then stops before **each** application and shows you exactly what it will send. It goes only
   when you press **Approve and send** (or **Do not send**).
5. The card shows what it is doing, any questions waiting for you, a **Pause** button and a log. **Continue the unfinished application** picks up where
   it stopped.

If *Guess answers I have not saved* is on, the AI makes a best guess instead of stopping to ask. Every guess is listed before you approve, marked as a
guess, and kept apart from your own answers. More: [The AI agent](README.md#the-ai-agent-any-job-site).

## Tab 4: Create Resume

Build a resume, find out how a computer will read it, and choose whether your applications use it. Everything stays on your computer. An **ATS** (applicant tracking
system) is the software that reads a resume before a person does; "ATS-friendly" below means that software can read it.

- **Start** with **New blank resume**, **New from my details** or **New from my uploaded resume**. A resume read from a file is a **draft**: a box lists
  what to check, and anything unreadable (a month, say) is left empty, never guessed.
- **Write.** Boxes on the left, the finished page on the right (shown whole, shrunk to fit). It saves a moment after you stop typing. Dates are
  year-month, like `2021-03`, or the word `present`. Empty sections are folded away; open one to use it.
- **Look.** Choose a template, font, size, accent colour, spacing and paper (A4 or Letter). **Show, hide and reorder** the sections. The plain
  one-column templates are labelled *ATS-friendly*; the two-column one is labelled *not ATS-friendly*.
- **Move and remove.** Every job, school, project and bullet has Up, Down and Remove buttons. Focus stays where you were.
- **Find your way.** An open resume has five **tabs**: *Edit*, *ATS check*, *ATS match*, *Tailor* and *Use*. Only the one you choose is on the page. The arrow keys,
  Home and End move between the tabs, a resume always opens on *Edit*, and what a tab was showing (a verdict, a job you pasted) is still there when you come back.
  Above the tabs, whatever tab you are on, are **Back to all resumes**, whether it is saved, and its **ATS status**. In the
  list, each resume shows its last ATS status (or *Not ATS-checked yet*, or *out of date* if you edited it since) and a **Check ATS** button.
- **ATS check.** Press **Run the full ATS check**. It prints the PDF you would send, reads it back the way a parser does, checks what you wrote, and gives **one
  answer**: *ATS-friendly*, *Mostly ATS-friendly* or *Not ATS-friendly yet*, with the first things to fix. **Go to it** puts the cursor in the right box. Underneath,
  **Check what I wrote** and **Check the PDF only** show each check on its own, with a score out of 100 and the reason for every lost point. "ATS-friendly" means
  these checks found nothing that software commonly trips on. It is **not a promise** about any employer's system and not a prediction of being hired.
- **ATS match.** Paste a **job description** and press **Run the ATS match** to see which skills it asks for that your resume lacks. **I have this** adds a skill to
  your Skills, only when you press it, for a skill that is true of you. A skill the job only *prefers* costs nothing. **Save a copy for this job** keeps one resume per job.
- **Check a resume you already have.** On the list, **Check the resume my runs send** checks that file as it is, or choose any PDF or Word (.docx) file to check.
  A PDF is read the way a PDF made here is. A Word file is checked for text boxes, tables, contact details in the header or footer, and pictures, plus the same
  reading of its text; what a Word file looks like when printed is not guessed. The file is read on your computer and **not kept**.
- **AI suggestions (optional).** *Improve with AI* (a bullet) and *Suggest a summary with AI* use the AI helper you set up and count against its daily
  limit. A suggestion appears as the difference from your text (struck-through words come out, underlined words go in) and **nothing changes until you
  press Use this**. A suggestion that adds a number, tool or name your resume does not contain is thrown away. A blank like `[X%]` is for you to fill in
  with the real figure; the check reminds you until you do.
- **Download as a PDF** for a file you can send anywhere.
- **Use it for my applications.** Tick *Yes, use this resume from now on*, then press **Use this resume**. It prints the PDF, reads it back to make sure it
  is sound, **then** replaces the resume your runs send, and tells you which skills it added to your profile (with no years: you set those). Until you do
  this, building a resume changes nothing about your applications.

Your resumes are the files in `data/resumes`. More: [The Create Resume tab](README.md#the-create-resume-tab-build-check-and-use-a-resume).

## Tab 5: Profile

Five things, all about you and your data:

- **Your applications at a glance.** A ring of every job and one bar per site. Tiles: **Submitted** (sent), **Rehearsed** (filled in, not sent),
  **Skipped** (turned away for any reason), **Errors** (tried again next run) and **Waiting** (found, or waiting for your answer). Press a tile or a
  number under a bar to list the jobs behind it, with the reason for each. There is a table view too (*Show these numbers as a table*), so nothing relies
  on colour.
- **Ask the AI.** Under the dashboard. It answers questions about your own applications ("Why were jobs skipped?"). It only reads what the panel already has,
  cannot do anything, saves nothing, and sends your name, email and phone only if you tick the box. Press **Ask**, or Ctrl+Enter (Command+Enter on a Mac). It is
  about the site chosen on the Apply tab, and needs the AI helper set up. See [Ask the AI about your applications](README.md#ask-the-ai-about-your-applications).
- **Your details.** Links to the [profile form](#the-profile-form), the [AI helper](#the-ai-helper-optional) and the [Questions](#questions) page.
- **Tools.** *Check my setup*, *Repair the install*, *Install Chrome* (shown only if no browser is found), *Applications (AI agent)*, and shortcuts to
  your data and reports folders.
- **Your personal information.** Delete what the program keeps. Tick what to delete (your details; your resume and documents; **resumes you built**; AI key
  and logs; saved site logins; jobs, applications and reports; logs and screenshots), press *Delete selected*, read the list, and type `DELETE`. A choice
  with nothing saved is greyed out. Files you put in `data` yourself are never touched, and applications already sent stay sent.

---

## The other pages

These open from links in the panel.

### The profile form
**Profile and resume** (`/profile`). Choose your resume and the boxes fill from it. **AI Fill** (optional) suggests values for the *empty* boxes, each
checked against your resume, and never saves for you.
- **About you:** full name, email, mobile number, current city, current job title and company, total years of experience, notice period, current and
  expected CTC, highest education, and optional LinkedIn, GitHub and portfolio links. Two tick boxes say whether you are willing to relocate and whether
  hybrid or work-from-office jobs are fine. Notice period and the two CTCs are answered by built-in rules in every wording, so fill them in once.
- **What you are looking for:** *Job titles to apply for*, optional *Keywords*, *Titles to skip*, *Locations*, *Companies to never apply to*, *Minimum skill
  match, in %*, optional *Minimum salary in LPA*, and *Most applications in one run*.
- **Skills,** each with its years (*Add another skill*). The match score is the share of a job's skills that are yours.
**Naukri applies with the resume saved on your Naukri profile**, so upload a new resume there too.

### The AI helper (optional)
**AI helper** (`/ai`). Choose Claude, ChatGPT, Gemini, OpenRouter, or **Ollama** on your own computer (free, nothing leaves your machine). Cloud AIs need a
**developer key**: a ChatGPT Plus or Claude Pro subscription does not include one. Press **Test the connection**. You can add a **backup AI**, asked
automatically when the main one errors, extra documents about you, and a box called *Anything else the AI should know about you*.
How it stays honest: your saved answers come first; an answer from your documents must **quote the exact sentence** and every number must be in them; a
personal question (gender, race, disability, veteran status) is never guessed. Everything it did is in the run report. Full rules:
[The AI helper](README.md#the-ai-helper-optional).

### Questions
**Questions** (`/questions`). When a form asks something your profile cannot answer, the job waits up to 5 minutes. Answer it **in the site's own form**
or here; either way it is saved as a normal answer, reused for the same question later, and shown to the AI for rephrasings. You can also use
**Add a question and answer yourself** before a job asks, and edit or remove anything under **Your saved answers**. For a yes/no question write `Yes`
or `No`; for choices, write one of the choices or a number. On **Naukri**, the question *side bar* is handled the same way, but
**that part is not yet checked on the live site** (Naukri's question script is blocked on some networks, so its selectors are unverified; if they miss, the bar is found by the text of its questions instead). If it does not
open, the job is parked with its questions listed here. See
[Answering a question right in the site's own form](README.md#answering-a-question-right-in-the-sites-own-form) and
[Adding a question and answer yourself](README.md#adding-a-question-and-answer-yourself).

### Applications
**Applications (AI agent)** (`/applications`), under Tools on the Profile tab: what the AI agent is doing now, what it needs from you, and every
application it has handled.

---

## Recipes: I want to…

**…send a few applications safely.** Quick start steps 1 to 7. Use **Rehearse** first. Then **Apply for real** with 3.

**…approve every job myself.** Use **Auto-apply v2**. You see each job and press Apply to it or Skip it.

**…apply on a site the panel does not list.** Open the job in the automation browser (step 2) and use the **Auto fill form** tab. Rehearse first.

**…tailor my resume to one job.** Create Resume tab → open your resume → *ATS match* tab → paste the job description → **Run the ATS match**, then the *ATS check* tab → **Run the full ATS check**. Press **I have this** only for skills that
are true. Fix what the check lists. **Save a copy for this job**, then **Download as a PDF**. To make runs use it, tick *Yes, use this resume from now on* and press
**Use this resume**.

**…stop answering the same question again and again.** Answer it once on the **Questions** page, or type it into the site's own form when a job waits. It is
saved. Use *Add a question and answer yourself* to add the ones you know are coming.

**…change my rules, then try the skipped jobs again.** Edit the profile form or `data/criteria.yaml`, then tick **Also re-check jobs skipped earlier** on a
**Rehearse**. Jobs your new rules approve are applied to by the next real run.

**…pause, or stop, a run.** *Auto-apply v2* has **Pause** (between applications) and **Stop**. The Output's **Stop** works for every run. Stopping is polite:
it finishes the page it is on and writes its report.

**…see what happened.** The dashboard on the Profile tab; the **Reports** list; the *What happened* table on Auto-apply v2 (with CSV download).

**…delete everything about me.** Profile tab → *Your personal information* → tick → *Delete selected* → type `DELETE`. Quit the automation browser
completely first if you tick the saved logins.

**…move the folder.** Delete the `.venv` folder inside it first, then start again: the install is tied to its folder.

## Keyboard and screen readers

- A **skip link** at the top of the page jumps straight to the Output.
- **Tabs:** Tab moves to the tab row; the **arrow keys** move between tabs; Tab then goes into the page.
- Every button has a text name, every box a label, and changes are announced (saved, deleted, moved). Moving an item keeps focus on it. Nothing relies on
  colour alone: scores and counts are written as words and numbers.
- **Delete** (reports, resumes) takes two presses so a slip cannot destroy anything.
- **Ask the AI:** Ctrl+Enter (Command+Enter on a Mac) sends.
- The panel follows your computer's *reduce motion* setting.

## Where your files are

All in the `data` folder next to the program. **Never share it.**

| File or folder | What is in it |
|---|---|
| `profile.yaml`, `criteria.yaml` | Your details and your job rules |
| `answers.yaml`, `answer_aliases.yaml`, `guessed_answers.yaml` | Your saved answers, other wordings of them, and answers the AI only guessed |
| `resume/`, `about/` | Your uploaded resume and extra documents for the AI |
| `resumes/` | The resumes you built in the Create Resume tab |
| `ai.yaml` | Which AI and its key |
| `ai_*.jsonl` | Records of what the AI was asked and decided |
| `browser-profile/` | The logins of the automation browser |
| `jobs.db` | Every job seen and what happened |
| `reports/` | One report per run |
| `run.log`, `failures/` | Logs, and screenshots of problems (they can show your name) |

## Getting updates

New versions are published on GitHub: <https://github.com/akash-gupta-146/auto-apply>. **An update never touches your own files.** Your profile,
answers, resumes, AI key and logins all live in the `data/` folder, and the program ignores that folder when it updates.

**If you got the program with `git clone`,** you already have what you need. Each time you want the latest:

1. In the panel press **Quit**.
2. Open a terminal in the program's folder. On a Mac: type `cd ` (with a space after it), drag the folder onto the Terminal window, press Enter.
   On Windows: open the folder in File Explorer, click its address bar, type `cmd`, press Enter.
3. Run `git pull`.
4. Start the panel again (`Start.command` on a Mac, `Start.bat` on Windows). If you forget, a banner tells you the panel is running an older version.

**If you downloaded the zip,** your folder is not connected to GitHub yet, so `git pull` has nothing to pull from. Connect it **once**, then use the steps above
from then on. You need Git: a Mac offers to install it the first time you type `git` in Terminal; on Windows install it from <https://git-scm.com>
and open a new window afterwards. In the program's folder (step 2 above) run these four lines:

```
git init
git remote add origin https://github.com/akash-gupta-146/auto-apply.git
git fetch origin
git checkout -f -B main origin/main
```

This brings your program files up to date and leaves `data/` and `.venv/` exactly as they were. It overwrites the program's own files, so it is not for
someone who has edited them. (No Git, and not wanting it? Download the zip again and unzip it over your old folder: the zip has no `data/` folder, so yours
stays. Files that a newer version removed will be left behind, which does no harm.)

**If git says it would overwrite your changes,** you have edited a program file; your `data/` folder is never the cause. Keep a copy of the file
somewhere else, then run `git checkout -- .` and `git pull` again.

## When something goes wrong

| You see | Try |
|---|---|
| "Open the browser first" | Step 2, and leave that window open |
| "login not checked yet" / `logged in: False` | Log in inside the window step 2 opened (not your usual browser), then step 3 |
| A captcha or security check | Solve it yourself in the automation window. It waits 5 minutes, then skips that job |
| "found 0 jobs" | Look at the newest picture in `data/failures/` and at `data/run.log` |
| "nothing to process … already handled" | Tick **Also re-check jobs skipped earlier** |
| Many `skipped_external` | Those jobs ask questions or apply on another site: apply by hand from the report |
| "The AI helper is not set up yet" | Open **AI helper** and fill it in, or turn the AI off for that run |
| AI error 401 / 404 / 429 | Wrong key / wrong model name / out of credit (add a backup AI) |
| "could not connect to http://127.0.0.1:11434" | Ollama is not running: open it and test again |
| The AI buttons in the Create Resume tab are off | The AI helper is not set up; the rest of the tab works without it |
| A banner says the panel is "running an older version" | Press **Quit** (top of the page), then start it again |

The full table, with every site's own messages, is [Something went wrong](README.md#something-went-wrong).

## Words used

- **Rehearsal / dry run:** a run that does everything except send.
- **Report:** the file a run writes about what it did, and why for each job.
- **Skill match / `min_score`:** the share of the skills a job names that are also yours. Below your minimum, the job is skipped, with the number shown.
- **Automation browser:** the separate browser window the program controls. You log in there.
- **AI helper:** the optional AI that answers *new* questions from your own documents. The rules and your saved answers always come first.
- **ATS (applicant tracking system):** the software many employers use to read resumes before a person does.
- **Draft:** a resume read from a file; check it before you rely on it.
- **CTC / LPA:** cost to company, in lakhs per annum (Indian salary figures).

## Command line

The panel does everything below for you. For a terminal: `jobapply panel`, `doctor`, `browser`, `probe`, `triage`, `run`, `agent`, `answers`, `ai-test`
and `status`. The list, with examples, is [The same thing with commands](README.md#the-same-thing-with-commands).
