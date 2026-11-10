# agent-to-apply

Applies to jobs on **Naukri** (and, experimentally, **Instahyre**, **LinkedIn** and **Indeed**) for you. It reads your resume, finds jobs that match the titles, locations and skills
you choose, applies to them one by one, waits up to 5 minutes if a captcha needs you, then skips that job and carries
on. When it stops it writes a report of what it did.

You run it from a **control panel**: a page of buttons that opens in your browser. There are no commands to type,
and the same panel works on Windows and on a Mac.

You do not need an AI account, an API key or any coding to use it.

## Read this first: what is proven and what is not

| | Status |
|---|---|
| Naukri: login check, finding jobs, reading jobs, one-click "Quick apply" | **Tested on the live site, on a Mac.** An application was sent and Naukri's own "Applied jobs" counter went up. |
| Naukri jobs that ask **screening questions** after Quick apply | **Not applied automatically.** Naukri's page does not show those questions to the program. They are listed in your report as "needs a human", with the questions, so you can apply by hand. |
| The control panel | **Tested on a Mac, in a real browser:** the page, the buttons, live output, the confirmation, and a rehearsal that was stopped part-way (the program wrote its report). |
| **Windows** (`Start.bat`, `setup.ps1`, and the panel's Windows parts: opening File Explorer, `winget`, the Stop button) | **Checked as far as a Mac allows. Never run on a Windows PC.** `setup.ps1` is parsed and *run for real under PowerShell* (on a Mac, with a pretend Windows around it) for a normal install, a failed install, no internet (including pasting a mirror address), no Python and a broken Python; this found and fixed a real bug (a failed install used to print "[ok]"). The panel's Windows-specific commands, the browser search, line endings and file names are covered by tests that pretend to be Windows. **Not checked:** `Start.bat` itself (`cmd.exe` cannot run on a Mac: it is 21 short lines, read by eye), BrowserOS neo's install location on Windows (a best guess; Chrome and Edge are found by their standard paths), and a real run of the panel and a browser on Windows. Tell me what breaks. |
| The AI helper | Built and tested with **simulated AI replies only**. It has never talked to the real Claude, ChatGPT, Gemini, OpenRouter or Ollama, and has never answered a real Naukri question. |
| **Instahyre** (in the panel: choose it under *Which site?*) | **Experimental.** Checked against a real account: the login check, and recognising Instahyre's profile-setup screen (the program stops and tells you, instead of finding nothing). Also checked live: reading the opportunity cards (each is headed "Company - Role"), opening a job's details (a pop-up with the full description and the Apply button) and finding Apply there; the program only ever presses the button whose text is exactly "Apply", never the "Not interested" beside it. **Not checked yet:** what Instahyre does after a real Apply press. Instahyre shows 30 of your opportunities per page, and the program does not yet page on to the rest. Rehearse first, then apply for real with **1**. |
| Wellfound | Written but **never tested on the live site**, and **not in the panel** (command line only). Treat as experimental. |
| **Indeed** (in the panel: choose it under *Which site?*) | **Experimental.** Indeed forbids automation and its Cloudflare checks often ask for a human (the program waits 5 minutes, then skips that job). It only fills in **Indeed's own application form**: a job whose Apply button leads to a company's website is skipped, and the program never types into a page that is not on indeed.com. Works with or without the AI helper (see *Indeed, with and without the AI helper*). Checked live, read-only: the login check, reading search results and a job page, and skipping a hidden decoy card that real visitors never see. **Not yet seen live: Indeed's own application form** (every job looked at said "Apply on company site"), so that part is checked only against pages built to look like Indeed's: rehearse first. |
| **LinkedIn** (in the panel: choose it under *Which site?*) | **Experimental, and the riskiest site to automate.** LinkedIn forbids automation and can restrict accounts that use it; this is your professional account, so decide for yourself. Only **Easy Apply** jobs are touched: the search always asks for Easy Apply, the program checks that filter really is switched on before it reads anything, and a job is skipped unless its own card and page say Easy Apply. It waits **45 to 120 seconds** between jobs, never presses *Follow company*, and leaves no half-finished application behind. Checked against a real account: the login check, the Easy Apply filter, reading job cards and their ids, and a **rehearsal all the way to the Submit button** (contact, resume, screening questions answered from your profile, Review, then stop and discard; it also unticks LinkedIn's pre-ticked *Follow company* box). **Not checked:** pressing *Submit application*, the "Application sent" message, other question types (dropdowns, long text), and any real application. Rehearse first, then apply for real with **1**. |

Using automation on a job site can go against its rules. Your account, your decision. The program works slowly on
purpose (20 to 90 seconds between jobs).

---

## What you need

- Windows 10 or 11, or a Mac, and an internet connection
- A Naukri, Instahyre, LinkedIn and/or Indeed account you can log in to
- Your resume as a **PDF, DOCX or TXT** file
- About 15 minutes the first time

A browser called **BrowserOS neo** is preferred; **Google Chrome** is used automatically if neo is not installed (and on
Windows, **Microsoft Edge**, which every Windows PC has, if neither is). Python 3.9 or newer is needed too: the first start installs it for you if it can, and tells you what to do if not.

---

## Start

Unzip it, then double-click **one** file:

| Your computer | Double-click |
|---|---|
| Windows | `Start.bat` |
| Mac | `Start.command` |

The first time it installs everything (a few minutes). Every time after that it just opens the control panel in your
browser. **Leave the window it opens in the background while you use the panel.** Closing it, or the **Quit** button,
shuts the panel down. Quit asks you to press it twice; the page then drops away off the bottom of the window and says
goodbye. (It will not quit while a run is going: press Stop first. If your computer is set to reduce motion, the page skips
the fall and shows the goodbye at once.)

**Windows:** extract to a short path with no spaces, for example `C:\agent-to-apply`, and not into a cloud-synced
folder. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**. If it says `winget not
found`, install Python from python.org (tick **Add python.exe to PATH**) and double-click `Start.bat` again.

**Mac, once, before the first start:**

1. Drag the unzipped `agent-to-apply` folder to your home folder, so it lives at `~/agent-to-apply`. Do this first:
   the install builds a private environment inside the folder that stops working if you move the folder later.
   Avoid Desktop and Documents if iCloud syncs them.
2. macOS blocks files that came from the internet. Open **Terminal** (Command+Space, type `Terminal`, Return) and paste:

   ```bash
   cd ~/agent-to-apply
   xattr -dr com.apple.quarantine .
   chmod +x Start.command setup.sh
   ```

   Only do this if you got the ZIP from someone you trust. If you skip it, the first double-click says it "cannot be
   opened because Apple cannot check it": open **System Settings, Privacy & Security**, scroll down and click **Open
   Anyway** next to the file.

---

## The control panel

The top of the page shows where things stand and which step is next. **Which site?** (Naukri, Instahyre, LinkedIn or Indeed) sits just below it:
steps 3 to 5, the status lines and the next-step hint all follow your choice, and the page remembers it. Each site keeps
its own login check and its own job counts. The five steps:

| Step | What it does |
|---|---|
| **1. Your details** | **Profile and resume** opens a form: choose your resume and its boxes are filled from what it says (name, contact, city, current job and company, education, links, years of experience; **anything the resume does not say stays blank**). Press **AI Fill** to have your AI helper suggest the rest from your resume: job titles, keywords and skills too. It only fills *empty* boxes, only with things your resume backs up, and never saves for you. Then add the skills you can stand behind, each with its years, with **Add another skill**. **AI helper** itself is optional (see below). |
| **2. Open the browser** | Opens a separate browser window that the program controls. **Log in to Naukri (and Instahyre, LinkedIn and Indeed, if you use them) in that window, once**, and leave it open. Your login is kept for next time. |
| **3. Check the site** | A read-only test of the chosen site: are you logged in, and can it see jobs? It applies to nothing. |
| **4. Rehearse** | Walks through jobs and fills forms but **never submits**. Safe to run as often as you like. Run it first, and again whenever you change your rules. |
| **5. Apply for real** | Sends real applications on the chosen site. It asks how many and for how long (start with **3**, or **1** on Instahyre, LinkedIn and Indeed), and you must type **YES** to start. |

While something runs, the **Output** panel shows what it is doing, and **Stop** ends it politely: it finishes the page it
is on and writes its report. Only one thing runs at a time. **Tools** has *Check my setup*, *Repair the install*,
*Install Chrome* (only shown if no browser is found) and shortcuts to your data and reports folders. **Reports** lists
the latest run reports and shows one right in the page as a formatted page (headings, a table, lists, links), not as raw
text. When a run ends, its new report opens by itself. A report that was already there when you opened the panel stays
closed until you click it. Each report is named by when it ran and what kind it was, like
`11-08-26--003000--live` (month-day-year, then hour-minute-second, then `live` or `dry-run`); a small tag beside it says
which site it was for, and hovering shows the file name.

Beside each report is a **Delete** button. It takes two presses: the first only asks "Sure?" (and goes back to "Delete" after
a few seconds, or if you press anything else). Reports you have not opened yet are **bold, blue, with a dot**; once you have
opened one (or it opened by itself) it turns grey. That is remembered in your browser, so it survives a reload.

**Your personal information** (a section at the bottom of the left column) deletes what the program keeps about you. Tick
what to delete, press *Delete selected*, read the list of what will go, and type `DELETE` to confirm. It is not available
while a run is going. The choices, and exactly what each one removes (all inside the `data` folder, nothing outside it):

| Choice | What goes |
|---|---|
| Your details and job preferences | `profile.yaml`, `criteria.yaml`, `answers.yaml` |
| Your resume and extra documents | `resume/` and `about/`. Your profile stays but forgets its resume |
| AI helper key and its logs | `ai.yaml`, `ai_answers.jsonl`, `ai_fit.jsonl` (this turns the AI helper off) |
| Your saved site logins (Naukri, Instahyre, LinkedIn, Indeed) | `browser-profile/`, which holds the logins for every site. Quit the automation browser completely first (closing its window is not enough); you will log in again next time |
| Jobs seen, applications and reports | `jobs.db` and `reports/` |
| Logs and screenshots of problems | `run.log` and `failures/`, and the output shown in the panel |

A choice with nothing saved is greyed out. Other files you may have put in the `data` folder yourself are never touched.
Applications already sent stay sent: this only removes what this program keeps.

### The panel is a local program, not a website
It only answers your own computer. Every button press must carry a secret that is new each time the panel starts, and
the panel can only run a short fixed list of things (the buttons). Nothing you type, and nothing a web page sends, can
become a command.

---

## The AI helper (optional)

Use it when many jobs stop at questions about *you* that your profile cannot answer ("Have you led a team?"). An AI you
choose (**Claude, ChatGPT, Gemini, OpenRouter, or Ollama on your own computer**) answers using only your own documents.

**How it stays honest**
- Your saved answers and the built-in rules always come first. The AI gets what is left.
- **It learns from the questions you answered yourself.** The answers you give on the Questions page are saved, shown there
  (with a Remove button), and shown to the AI as one line each with an id ("[A3] When asked ... the candidate answered: ...").
  When a question comes back in other words ("Do you have the legal right to work in India?" after you answered "Are you
  legally authorized to work in the country...?"), it may answer as you did by **naming that line's id**; the run report shows
  which line. The program checks that the id exists and that the answer is that saved answer, so nothing has to be copied
  perfectly. It is told to do this only for exactly the same fact. If two of your saved answers disagree about an ordinary
  fact, it chooses the **most reliable** (see below), and may only choose one of *your* answers. When you have more saved
  answers than fit, it is shown the ones **most like the question**, not just the first ones. An answer you give while a run is
  going is known to the AI for the next job.
  **Consent questions** ("I certify...", "I consent...", "I acknowledge...", agree, privacy, terms) are never shown to it:
  your answer to one is reused only when the very same words come up again.
- **Answers from your documents must be proved.** The AI must **quote the exact sentence** it used. The program checks that the
  quote really is in your documents and that every number in the answer is in them too (no sums, no estimates). Anything that
  fails is thrown away and the job waits for you, exactly as it would without the AI.
- **One entry per fact.** When you answer a question (on the Questions page, on the site's own form, or with
  `jobapply answers --set`), the AI looks at your other saved and *waiting* questions and folds the ones that ask **the same
  fact** into the answer you just gave. The Questions page then shows one entry, the other wordings stop waiting, and a form
  that words it that way later is answered from a file, with no AI at all (`data/answer_aliases.yaml`). It is told to doubt:
  *current vs expected* salary, *lakhs vs rupees*, *notice period vs last working day*, one skill vs another are **different**
  facts. Code, not the AI, also refuses to fold two single figures that differ by 50 times or more, or any consent wording.
  If the AI is not set up or cannot be reached, your answer is simply saved as typed. **When folded answers disagree, the one
  you just typed wins** (your own correction outranks everything); the one it replaced is kept in `data/ai_facts.jsonl`.
- **Tidy the answers you already have.** `jobapply answers --tidy` shows a plan and changes nothing; add `--apply` to do it
  (a dated backup `answers.yaml.bak-...` is made first; copy it back to undo). Identical answers are merged without any AI.
  Answers that disagree are settled by the AI's choice of the **most reliable** of your own answers, in this order (the
  priority hierarchy of the proficiently skills): it agrees with your documents, then it was given for more of the wordings,
  then it states its figure with a unit. It may not invent, average or convert. **Only you settle** a personal question
  (gender, race, disability, veteran status...), figures that look like different units, and anything the AI cannot tell:
  they are listed as *NEEDS YOU* and left exactly as they are.
- **Personal questions are never guessed.** If two saved answers about gender, race, disability, veteran status and the like
  disagree, the AI gives no answer (code checks this, not the model). If you have saved nothing and the form offers a
  *"Prefer not to say"* choice, that is chosen (the proficiently skills' default for voluntary questions) instead of stopping the job.
- **Fill in your profile once.** *Notice period*, *current CTC* and *expected CTC* in your profile are answered by built-in
  rules in **every wording**, with no AI. If they are empty, each new wording becomes a new question on the Questions page.
- Every answer it wrote is listed in the run report, so you can check what was said in your name.
- **It also reads job descriptions.** For a job the rules would skip *only because of its title* (for example "Software
  Developer - SDE II" that is really React work), the AI reads the description against your documents and decides whether
  you fit. It must quote two real lines from your documents as proof; anything else stays skipped. It never overrides a
  company you blocked, a role you skip or your salary minimum. Approved jobs say `AI fit: ...` as their reason in the report, and
  every verdict is in `data/ai_fit.jsonl`. Jobs skipped in earlier runs are not re-read by a live run: a **Rehearse** (with
  the AI switch on) gives them a second look, and the ones the AI approves are applied to by the next real run.
- Naukri jobs that show a separate screening-questions form are still left for you: neither the program nor the AI can
  see those questions.
- **AI Fill** (the button on the details form) is the same idea applied to the form itself: the AI reads your resume and
  suggests values for the *empty* boxes, and every suggestion is checked against your resume before it appears. A
  value may only use words and numbers the resume contains; an address must appear exactly; a job title needs a quote
  showing that kind of work. **A skill's years are filled only when the resume itself states them** ("5+ years of
  React"), never worked out from job dates. Anything that fails is left out, and the page tells you how many. It sends
  only your resume text (email and phone number removed), only when you press the button, and it counts against the
  AI helper's daily limit.

**The ? buttons.** On the home page and the AI helper page, the longer explanations sit behind a small **?** button: rest the
mouse on it, or press Tab to reach it, and the text appears (it hides again when you move away). It is plain text on the
page, so a screen reader reads it too. Anything you should see before you decide stays in view: the warning that these are
developer keys and not your chat subscription, that a backup AI may receive your text, what "apply to every job the site
suggests" risks, that deleting your information cannot be undone, and each site's own warning.

**Set it up once (about 10 minutes)**
1. **Get a developer key.** This is *not* your ChatGPT or Claude chat subscription: a ChatGPT Plus or Claude Pro plan does
   not include one. Each company has a developer page where you create a key and bills it separately, usually a small
   amount for this use. OpenRouter has free models. On OpenRouter, also switch off anything in **Settings, Privacy** that
   lets providers train on your data.

   **Or use Ollama: free, no key, and nothing leaves your computer.** Install it from ollama.com/download, run
   `ollama pull llama3.1:8b` (about 5 GB), and keep Ollama running. On the AI helper page choose **Ollama** and type
   `llama3.1:8b` as the model; leave the key blank. A model this size wants roughly 8 GB of free memory and is slow without
   a graphics card. Small local models are less reliable than Claude or ChatGPT, so expect more questions to be declined
   and left for you. That is the safe direction: the checks above still apply to every answer.
2. **Get your LinkedIn profile as a file.** On your own LinkedIn profile choose **More**, then **Save to PDF**. The program
   never reads LinkedIn itself: the AI helper only uses the file you give it.
3. In the panel click **AI helper**. Choose the AI, paste the **model name** and the **key**, add the LinkedIn PDF (and any
   other document: a project write-up, a performance review; one file per save) and type any notes in your own words. Press
   **Save**, then **Test the connection**. You should see **It works**.
4. In **Rehearse** or **Apply for real**, switch on the AI helper. The confirmation tells you what will be sent.
5. Open the newest report and read the AI answers. If one is wrong, add your own with
   `jobapply answers --set "Exact question text" "Your honest answer"`: your own answers always beat the AI.

**What the AI company receives:** the text of your resume, documents and notes and the answers you saved on the Questions
page (email addresses and phone numbers removed; consent questions left out)
and your profile facts (never your name, email or phone), at most the first 40,000 characters, once per new question, and
once per job it reads (plus that job's public description, up to 8,000 characters). **With Ollama, none of it leaves your
computer.** Nothing is sent unless you switch the AI helper on for a run or press **Test the connection** (which sends
only the word "OK"). Each company's own data policy applies to what it receives.

**Cost control:** a daily limit on requests (default 60, you can change it). Every question is remembered in
`data/ai_answers.jsonl`, so the same question is never paid for twice; that file is also the full audit trail. Reading job
descriptions never uses the last 10 requests of the day (kept for form questions), and each judged job is remembered in
`data/ai_fit.jsonl`.

---

**If your AI fails: backups, and AIs that are not in the list**

Free keys run out (a full daily quota is *HTTP 429*), keys expire and services go down. So the AI helper page has three
**backup** rows: the AIs to ask, in order, when the main one errors.
- **What counts as an error:** a full quota or rate limit, a wrong or expired key, an unknown model, a server error, no
  connection, a timeout, a reply that is not a reply, or an empty answer. The next AI is asked at once, with the same request.
- **A failed AI rests, so it is not asked on every question.** Every attempt, even a failed one, counts against your daily
  limit, so asking a dead AI first each time would waste it. It rests **10 minutes** after a full quota, **an hour** after a wrong
  key or model (waiting cannot fix that), **a minute** after anything else, and then goes back to being asked first by itself. If
  all of them are resting, all are tried anyway.
- **One daily limit covers all of them** (the *Most AI requests per day* box). Reaching it stops the AI helper; it is not treated as
  an AI's fault, because switching would not help.
- **Another model of the same company is a real backup.** Free tiers often limit each model separately. Leave the backup's key
  blank to use the main AI's key when it is the same company. A blank key never borrows a key from a *different* company.
- **Your documents may go to a different company.** Whatever would be sent to the main AI is sent to the backup that answers
  (the page and the profile page's AI Fill say so). Add only companies you are happy to share it with, or use Ollama, which stays
  on your computer. **The run report lists every switch** under *Problems noticed* (`AI switch: ... failed (...); asking ... instead`),
  and `data/ai_answers.jsonl` still records each answer.
- **Test the connection** tests the main AI and every backup on its own and says which one fails. `jobapply ai-test` does the same.

**An AI that is not in the list?** Under *An AI that is not in the list?* on the same page give it a name and its address, and say
which format it speaks, then choose it as the main AI or as a backup. Most services speak the *OpenAI-compatible* format (Groq,
Together, Mistral, DeepSeek, LM Studio, vLLM and many more): the address is the one *up to* `/chat/completions`, for example
`https://api.groq.com/openai/v1`. The others are *Claude-compatible* and *Ollama-compatible* (a server on your own network).
- The address must start with `https://`, because your key is sent to it. Plain `http://` is accepted only for a computer on
  your own network (`localhost`, `192.168...`, `10...`, `...local`). No login, `?` or `#` part is allowed in the address.
- Nothing is sent to an added AI until you choose it, and it is asked without a temperature setting (some servers refuse one).
- You can add up to 10. Removing one also removes it from your backups; you cannot remove the AI you are currently using as main.
- Everything is saved in `data/ai.yaml` (readable only by you), including each backup's key. Erasing your data removes it.

## Indeed, with and without the AI helper

Indeed works the same way with the AI helper off or on; the only difference is who answers a question the program has no
fact for.

| | AI helper **off** | AI helper **on** |
|---|---|---|
| Name, phone, city, years of a skill, notice period, relocation, your saved answers | Answered from your profile | Answered from your profile (the AI is never asked these) |
| A question only your documents can answer (for example *Years of experience with Rust*) | The job is **parked** as *needs an answer*, nothing is sent, and the question is listed in the report | The AI answers **only if it can quote your documents word for word**; otherwise the job is parked exactly as if it were off |
| A question marked *(optional)* | Skipped | Skipped (never worth an AI request) |

Indeed marks the optional questions rather than the required ones, so on Indeed a bare question counts as required.

**Kinds of form it handles:** text and long-text boxes, number boxes (an answer like "5 years" types `5`), dropdowns, radio
buttons, single tick boxes (ticked only when the answer is Yes), groups of tick boxes (the one that matches), date boxes
(only a real date like `2026-12-01` is typed), and the resume step (it uses a resume your Indeed account already has; it
never uploads or invents one). A tick box nobody asked for, such as "send me job alerts", is left alone.

**What it will not do:** fill in a company's own website (*Apply on company site*). Those need accounts, per-site steps and
often a captcha, so the job is skipped (`skipped_external`) and you can apply to it yourself. It also never types into any
page that is not on indeed.com, even if Indeed sends it there half way through.

## During a run

| What happens | What the program does |
|---|---|
| The time limit or the application limit is reached | Finishes the current job, writes a report in `data/reports/`, beeps |
| A captcha or "are you a robot" page | Beeps, waits up to **5 minutes** for you in the browser window, then skips that job and continues |
| 3 captchas in a row | Backs off for 30 minutes, then continues |
| A job asks screening questions | Not applied. Marked **needs a human** in the report, with the questions |
| A question your profile cannot honestly answer | The job **waits up to 5 minutes** (`answer_wait_s`) for you to answer it on the panel's **Questions** page (the panel says how many are waiting), then applies with your answer. No answer in time: the job is skipped as `needs_answer` and the run moves on. A question that already went unanswered in this run does not make later jobs wait again. Answers are saved and reused. From a terminal: `jobapply answers` |
| ...and the AI helper is on | The AI answers only if it can quote your documents for it. Otherwise the job waits, as above |
| A tick box the site **requires** (for example "I acknowledge...", marked with `*`) and your saved answer is **No** | The program never ticks it against your answer, and ticking is the only way on, so the job is **skipped before anything is sent** (it shows as `skipped_match` with the question, and does not use up one of your applications). Change the saved answer to Yes (`data/answers.yaml`), then tick **Also re-check jobs skipped earlier** to try it again |
| LinkedIn will not accept a step, or the window never opens | Reported as **failed** with LinkedIn's own words, but because nothing was sent it does **not** use up one of your applications. A send that might have gone out still counts |
| Naukri logs you out | The run **stops** and tells you to log in again in the browser window; re-run and it continues where it stopped |
| 5 failures in a row | Stops (the site probably changed). Look in `data/failures/` |
| You press **Stop**, or close the panel | Finishes the page it is on, writes the report. Everything is saved in `data/jobs.db`; the next run continues the queue |

Your computer is kept awake while a run is going, but closing a laptop lid still sleeps it. Keep it plugged in, lid open,
and the automation browser window open.

### What the report statuses mean
Every job a run touched is listed in the report, one line each, ending in **why:** and the reason it was applied to, skipped,
held back or failed. A job that was applied to says which of your roles its title fit (or the looser way it got in), how many
of the skills it names are yours, and how the site confirmed the send. A skipped job says what it fell short on, for example
`skill match 14% is below your minimum of 30%`. A failed job gives the error in the site's own words. The sections are, in order:
Applied (or *Would apply* after a rehearsal), Failed, Needs an answer from you, then three kinds of Skipped (did not fit your
rules, nothing to press, already applied) and Skipped by a challenge. Reports written before this was added show
"recorded as applied; no more detail was saved" for old applications, because nothing more was kept.

- **applied**: sent, and Naukri itself shows the job as applied afterwards (the program reloads the job to check; it does
  not trust a "success" message).
- **dry_run_ok**: would have been applied (rehearsal only).
- **skipped_match**: the title, skills, salary or location did not fit your rules.
- **skipped_external**: needs you (screening questions, or it applies on the company's own site).
- **needs_answer**: a form asked something your profile could not honestly answer, and nobody answered it within 5 minutes. It is tried again on the next run, now with any answer you have since given.
- **failed**: something broke; it is retried on the next run.

### Answering a question right in the site's own form
When a form asks something your profile cannot answer, the program leaves the form **open** for up to 5 minutes (the same wait as
before) and says so in the live output. You can then either type or tick the answer **in the site's own form**, or answer it on the
panel's Questions page. Either way it is saved as an ordinary saved answer, so the next application that asks it is answered from it
(and the AI helper learns from it too, see above). The program notices within a couple of seconds, waits until a box has stopped
changing so it never saves half a sentence, then carries on with what you entered. You will see "Saved your answer to: ...".

| Site | Answering in its own form |
|---|---|
| LinkedIn (Easy Apply window) | Yes. Text boxes, dropdowns, radio buttons and tick boxes |
| Indeed (its application form) | Yes. The same |
| Wellfound | Yes (the program only works there on request; its page layout has not been checked on the live site) |
| Naukri | No. Naukri's own questions are asked in its chat box and in a questions form the program does not fill; both are marked unverified in the code, so nothing is read back from them. Answer on the Questions page instead |
| Instahyre | Nothing to answer: it has no questions form, only an Apply button |

Only a question the program was stuck on is saved this way. An optional box you fill in, or something the site pre-filled for
you, is left alone. If you press Next yourself before the program has noticed, that answer is not saved (the form has moved on):
leave the box filled and wait for "Saved your answer", or save it from the Questions page. A question nobody answered in time is
not waited for again by later jobs in the same run.

### Pop-ups, adverts and sign-up offers
Sites put things in the way: LinkedIn's "Turn your resume into a profile that recruiters notice" after an application is sent,
Indeed's "Be the first to see new jobs" email sign-up in the middle of the results. On every portal, the program looks for such a
pop-up after each page load (and before Indeed's Next and Apply clicks) and closes it by pressing its **no**: "Not now",
"No thanks", "Maybe later", Close, or the close icon. Each one it closed is listed in the run report.

- **It never presses a yes.** "Update profile", "Activate", "Subscribe", "Join", "Accept", "Save", "Continue" and the like are refused,
  whoever suggested them. A pop-up with only yes buttons and no way to close it is left alone.
- **It never touches the application itself**: LinkedIn's Easy Apply window and its own "save this application?" question are skipped,
  and nothing is pressed while a captcha or check is showing (that is for you).
- **With the AI helper on**, a pop-up the rules do not recognise is shown to the AI (its wording and button labels, with emails and
  long numbers removed; none of your documents): is it safe to close, and which button is the no? Its answer must be one of the
  pop-up's real buttons (or its close icon), and passes the same never-a-yes check. Something that must be dealt with (a login, a
  question about the application, a confirmation of what you asked for) is left alone. Each kind of pop-up is asked about once: the
  verdict is remembered, and every one is in `data/ai_prompts.jsonl` (which "Erase my data" removes with the other AI logs).

### Apply to every job the site suggests
Tick **Apply to every job the site suggests** (in *Rehearse*, and in the *Apply for real* box), or run with `--suggested`.
The program then ignores your roles, skills and salary, opens the site's own picks for you and applies to each one in turn.
It can therefore apply to jobs that have nothing to do with your resume, in any city, so rehearse first.

| Site | What counts as "suggested" |
|---|---|
| LinkedIn | Its **Easy Apply** collection (`/jobs/collections/easy-apply/`): the jobs LinkedIn picks for you that can be sent from LinkedIn. (The plain "Top job picks" feed is not used: most of it applies on the company's own site, so nearly every job would be opened only to be turned away.) |
| Naukri | Its recommended jobs |
| Instahyre | Its opportunities |
| Indeed | Nothing: its home page only lists your recent searches. It uses your role and location searches instead |

What stays the same: a company on your blocked list is still skipped; a job you already applied to is never sent again; the
application and minute limits and the YES confirmation still apply; and a question your documents cannot answer still stops
and asks you on the Questions page (then skips the job after the wait). Tick the AI helper as well if you want it to fill in
forms from your documents. It only ever uses what your documents say.

Only what the site shows *during that run* is opened. Jobs an earlier search left in the queue are not touched, and jobs an
earlier run turned away for not matching are taken if the site suggests them now. The report says, for each one, that it was
applied to because the site suggested it, and still shows how many of its skills are yours "for information".

It works in batches: it reads about ten of the site's picks (a few seconds), applies to them, then reads ten more. Applying
starts almost at once instead of after scrolling through the whole list, and the live output shows each page as it is read.
A job still waiting for your answer from an earlier run is tried after the fresh ones, so nothing queues behind a question.

---

## Changing things later

- **New resume or new details:** use **Profile and resume** again. Naukri applies with the resume saved on your *Naukri
  profile*, not the file on this computer: upload the new one on Naukri too.
- **Job rules:** open `data/criteria.yaml` in any text editor. The ones you will use:
  - `target_roles`, `skip_roles`, `locations`, `blocked_companies`
  - `keywords` (also in the profile form, under the job titles): your own words for a good job, e.g. `react, design systems,
    accessibility`. A job whose **title, experience or description** uses at least two of them (all of them, if you gave
    fewer than two) is applied to even when its title is not in `target_roles`. Spelling variants count as the same word
    ("Front End" is "frontend"), and a phrase like `design systems` must appear with its words together. It is an
    *extra way in*, never a way around your rules: a blocked company, a `skip_roles` title, your salary minimum and the
    skills check (at least 50% of the skills the job names must be yours) still apply. Each job it lets in is marked
    `keyword fit: react (title), design systems (description)` as the reason in the report, so you can see why. Leave it empty to turn
    it off. The experience a job asks for (for example `5-8 Yrs`) comes from Naukri's own search results; it is read
    when the job is found, so jobs found before this version get it the next time a run finds them again.
    **After changing keywords, tick "Also re-check jobs skipped earlier"** (in Rehearse or Apply for real; see below), or rehearse once:
    a plain real run does not re-read jobs it already rejected, a rehearsal does,
    and the ones your keywords now approve are applied to by the next real run.
  - `similar_roles` (`true` by default): also apply to a title that is not one of your roles when the job is still plausibly yours.
    Two ways in, each marked in the report with its evidence: a generic title such as "Software Developer - SDE II" whose own
    text is about your roles (your role words at least 3 times), or an engineering title (engineer, developer, SDE) whose text
    names any skill you have (`skills in common`). Managers, architects and designers never count. Either way the job must
    still reach `min_score`. Set it to `false` for your exact titles only.
  - `min_score` (0 to 100, default 10; **"Minimum skill match, in %" on the profile page**). A job names some skills
    (React, Java, Kafka...); the score is the share of them that you also have, so a job naming 5 skills where you have 2
    scores 40. A job scoring below your minimum is skipped, with the reason `skill match 40% is below your minimum of 50%`.
    One bar for every way in. Raise it to apply to fewer, closer jobs; `0` switches the check off for jobs whose title is
    one of yours. A job that names no skill you have scores 0.
  - **Applying again to jobs that were skipped:** a plain run leaves alone the jobs it turned away. To give them another
    look (for example after you lowered your minimum skill match), tick **Also re-check the N jobs skipped earlier** in
    step 4 (Rehearse) or in the Apply for real window. It shows how many are waiting on the chosen site. It re-opens the
    jobs that did not match and the ones that showed no Easy Apply button; jobs you already applied to are never re-sent.
    The command-line way is `jobapply run <site> --reevaluate`. The usual limits (applications, minutes) still apply.
  - `min_salary_lpa` (only applied when a job shows its salary)
  - **The decision ladder** (from the proficiently job-search skill: *dealbreakers, then must-haves, then nice-to-haves*). All
    off until you set them, so jobs are judged exactly as before:
    - `dealbreakers`: words that make a job a "never" (for example `unpaid`, `clearance`). Whole words or phrases, in the title
      or description. Honoured by every run, including "apply to every suggested job"; no AI can overturn one.
    - `max_years_below` / `max_years_above`: skip a job whose **highest** experience ask is more than this many years under
      yours, or whose **lowest** is more than this many over. A portal's own "5-8 Yrs" is trusted; in a description only one
      clear statement in a sentence about *experience* counts (a second figure is usually about one skill), so an unclear job is
      never turned away for its years.
    - `min_fit`: `Low` (default: anything that passed), `Medium` (at least one nice-to-have) or `High` (at least two).
      Nice-to-haves: at least 60% of its skills are yours, it uses your keywords, its salary is over your minimum, it is in one
      of your locations (or remote), it asks for your level of experience. The report says the rating and which it found.
  - `max_applications_per_run`
  - `pacing_min_s`, `pacing_max_s` (seconds between jobs; do not make these very small)
- **"Remote":** this version does not search Naukri's "Remote" as a location, so leave it out of `locations`.
- **Moving the folder:** if you move `agent-to-apply` after installing, delete the `.venv` folder inside it and start again.

---

## Your privacy

- Everything is kept in the `data` folder on your computer: your profile, a copy of your resume, the browser's saved
  logins (`data/browser-profile`), your job history and, after a failure, screenshots of the page (which can show your name
  or photo). **Never share the `data` folder.** To reset everything, use *Your personal information* in the panel (or delete the
  folder). To log out, use its *Your saved site logins* choice (after quitting the automation browser).
- The panel only listens on your own computer, and its pages load nothing from anywhere else.
- If you set up the AI helper: your key is in `data/ai.yaml`, your extra documents are in `data/about`, and every question
  and answer is in `data/ai_answers.jsonl`. All stay on your computer. Never share them. Deleting `data/ai.yaml` turns the
  helper off.
- The program only talks to the job site you run it on (and, with the AI helper, to the AI company you chose, unless that
  is Ollama).

---

## Something went wrong

| You see | Do this |
|---|---|
| Mac: "cannot be opened because Apple cannot check it" | Run the `xattr` line in Terminal (see **Start**), or use **Open Anyway** in System Settings, Privacy & Security |
| Mac: "You do not have permission to open the application", or the file opens in a text editor | In Terminal: `cd ~/agent-to-apply && chmod +x Start.command setup.sh` |
| "This Mac cannot reach pypi.org" (first start) | The install downloads the program's parts from pypi.org. No internet: connect and retry. A work or school network blocking it: ask IT for the "PyPI mirror" web address; the installer asks you to paste it, then retries (remembered inside this folder). Starting again on an already-installed program is safe, even offline |
| The panel says **Open the browser first** | Use step 2 and leave that window open |
| Instahyre says it **needs your profile finished first** (the output says `setup needed:`) | Instahyre shows no opportunities until its 4-step profile setup (Add skills, Job preferences, Upload resume, Privacy settings) is done. Do it yourself in the browser window: this program never fills those steps in. Then check Instahyre again |
| LinkedIn shows a **security check** or asks you to sign in | Solve it yourself in the automation browser window. The program waits 5 minutes, then skips that job and carries on; after several in a row it backs off for 30 minutes. If it keeps happening, stop for the day: that is LinkedIn telling you it has noticed. |
| On LinkedIn the run stops with **"Easy Apply filter is not on"** | LinkedIn changed its search page, so nothing was read and nothing was applied (it refuses to browse unfiltered results). Run **Check LinkedIn** and tell whoever maintains the program. |
| On LinkedIn a job fails with **"did not accept this step"** | LinkedIn would not move past a step (a required answer was missing, or not in the form LinkedIn wants). Nothing was sent and the draft was discarded. Look at the screenshot saved in `failures/`; if it is a question about you, add the answer with `jobapply answers --set` and run again. |
| Indeed shows **"Additional Verification Required"** or a security check | Solve it yourself in the automation browser window. The program waits 5 minutes, then skips that job and carries on; after several in a row it backs off for 30 minutes. Indeed does this often. |
| On Indeed a job fails with **"Indeed did not accept this step"** | Indeed would not move past a step and the message after the colon is Indeed's own. Nothing was sent. Look at the screenshot saved in `failures/`, and add your own answer with `jobapply answers --set` if it was a question. |
| On Indeed many jobs are **skipped_external** | Those jobs send you to the company's own website, which this program does not fill in. Apply to them yourself. |
| **"<site> login not checked yet"**, or `logged in: False` | Log in inside the window that step 2 opened (not your usual browser), then use step 3 |
| "... is running but has no window open" (older versions said "... is a restricted debug port"), or the panel says the browser window was closed | You closed the automation browser's last window. On a Mac the app keeps running with no window, and nothing can use it. Run `jobapply browser` (or press **Open the browser**, step 2): it opens a window again, and your Naukri login is kept |
| "... is a restricted debug port" and you chose your own `--cdp` | That port belongs to BrowserOS itself. Leave `--cdp` alone and use the browser that `jobapply browser` opens |
| **No Chrome or BrowserOS found** | Use **Install Chrome** under Tools, or install Google Chrome yourself |
| The report says "found 0 jobs" | Look at the newest picture in `data/failures/` (login page? captcha?) and `data/run.log`; then use step 3 |
| The report says "nothing to process ... already handled" | Earlier runs dealt with them. After editing your rules, tick **Also re-check jobs skipped earlier** (in Rehearse or Apply for real) |
| "5 failures in a row" | The site changed. Keep `data/failures/` and `data/run.log` and ask for help |
| Many jobs say `skipped_external` | Those jobs ask screening questions or apply elsewhere. Apply by hand from the report |
| "The AI helper is not set up yet" | Click **AI helper** and fill it in, or switch the AI helper off for that run |
| "The AI did not accept the request: HTTP 401" | The key is wrong, expired, or from another company. Create a new key and save it again |
| "... HTTP 404" or "model not found" | The model name is wrong or retired. Copy a current one from the company's model list. For Ollama run `ollama pull <model name>` |
| "... HTTP 429" or "quota" | You ran out of credit or hit the company's free limit. Check your account, or wait. Better: add a **backup AI** on the AI helper page, which is asked automatically when this one errors |
| The report says "AI switch: ... failed ...; asking ... instead" | The main AI errored during the run and a backup answered. Look at the reason in the line; **Test the connection** shows which AI is broken |
| "every AI failed: ..." | Every AI you set up errored, one after another. The message names each one and its reason |
| "could not connect to http://127.0.0.1:11434" | Ollama is not running. Open the Ollama app, wait a few seconds, and press **Test the connection** again |
| The report lists "Questions the AI could not answer" | Your documents do not say. Add the facts to your notes on the AI page, or use `jobapply answers --set` |

---

## Optional: Claude Code with a free OpenRouter key (Windows installer only)

Not needed to apply to jobs, and separate from the AI helper: this is a chat assistant in a terminal, for starting runs by
typing a sentence and for asking an AI to help fix the program if a site changes. Free OpenRouter models allow only about 50
requests a day, so the program itself is built to need none. Running the full installer instead of `Start.bat` sets it up
(it installs Git, Node and Claude Code, and asks for the key):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The key is stored only on your own PC (in your `.claude\settings.json`), never in this folder.

---

## The same thing with commands

The panel runs these for you; you never need them. From the program's folder, with its private environment
(`.venv\Scripts\jobapply.exe` on Windows, `.venv/bin/jobapply` on a Mac):

```
jobapply panel                           # open the control panel (plain `jobapply` does the same)
jobapply doctor                          # check the setup
jobapply browser                         # open the automation browser
jobapply probe naukri                    # read-only check (the same for: probe instahyre, probe linkedin, probe indeed)
jobapply run naukri --dry-run --minutes 10          # rehearsal, applies to nothing
jobapply run naukri --minutes 30 --attempts 3       # real: at most 3 applications, 30 minutes
jobapply run naukri --dry-run --ai --minutes 10     # rehearsal with the AI helper
jobapply answers                         # questions the program could not answer
jobapply answers --set "Question" "Answer"
jobapply answers --tidy                  # plan to fold the questions that ask the same fact into one (changes nothing)
jobapply answers --tidy --apply          # do it, after making a backup
jobapply ai-test                         # tests the main AI and each backup; changes nothing
jobapply status                          # queue counts, AI usage, latest report
```

## For developers

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

- `jobapply/engine.py`: the run loop (time budget, pacing, captcha wait, stop rules)
- `jobapply/adapters/`: one file per portal; `naukri_api.py` reads Naukri's own job data (JSON), not its page layout
- `jobapply/matching.py`, `answers.py`, `resume.py`: deciding which jobs fit, and answering forms honestly
- `jobapply/ai_answers.py`, `ai_fit.py`: the AI helper (quote and number checks, redaction, cache, audit log);
  `ai_settings.py`: providers, key storage, the documents it may read; `llm.py`: the HTTP client for all five providers
- `jobapply/answer_book.py`: your saved answers as one entry per fact (aliases, folding, the guards that are code, not AI);
  `ai_facts.py`: the AI that says whether questions are the same fact and which conflicting answer to trust (ids only, checked);
  `answer_tidy.py`: `jobapply answers --tidy`; `ai_ledger.py`: the file of AI decisions, and their memory; `similarity.py`: how
  alike two questions are, with no AI
- `jobapply/matching.py`: whether a job is worth applying to, including the dealbreaker / must-have / nice-to-have ladder;
  `experience.py`: the years a posting asks for, read cautiously
- **Testing note:** when mutation-testing (breaking the code on purpose to see a test fail), run with
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=$(mktemp -d)`. Python reuses compiled bytecode when a file's size and its
  modification time (in whole seconds) match, so a mutant restored within the same second can keep running after the source is
  back to normal.
- `jobapply/web/`: the control panel and the profile and AI forms
  - `help.py`: the **?** button (no JavaScript: the text is in the page next to it; the stylesheet shows it on hover or focus)
  - `server.py`: HTTP, and all of the security checks (token, Host, Origin, CSP, a two-file static allowlist)
  - `actions.py`: the **only** commands the panel can run, built from fixed words and checked numbers
  - `hostos.py`: the few things that differ between Windows and Mac, as plain data so every system is testable
  - `runner.py`: runs one program at a time, keeps its output, stops it politely (Ctrl+C, then a hard kill after 20 s)
  - `panel.py` (what the buttons do and the status they report), `panel_page.py` (the markup), `static/` (theme and script)
  - `app.py`, `forms.py`, `ai_form.py`, `pages.py`: the profile and AI forms
- `scripts/build_release.py`: builds the one ZIP for both systems, after scanning it for your personal details. Run
  `python scripts/build_release.py` from a checkout whose changes are committed. It zips **only the files git tracks**, so your
  `data/` folder (profile, resume, AI key, logins, history), `.venv`, `.git` and any stray file can never travel, and it lists
  what it left out. It writes Windows scripts with Windows line endings and Mac scripts with Mac ones, whichever computer builds
  it, and it refuses to build if your name, email, phone, company, an API key or a home-folder path appears anywhere.
  It also leaves out `tests/`, `docs/`, `scripts/` and `PLAN.md`: they are for a developer's checkout, and are where traces of real
  sessions (the companies of jobs looked at live, real run results) end up. The person who unzips it starts from nothing: their own
  resume, details and AI key go into the panel and stay in *their* `data/` folder.
- Tests that need a browser are skipped when Chrome is not installed.

## Credits

The decision ladder (dealbreakers, then must-haves, then nice-to-haves, rated High / Medium / Low / Skip), the "accuracy first,
never fabricate; your own corrections outrank generated content" priority order used to choose between conflicting answers, and
the "prefer not to say" default for voluntary questions are adapted from the MIT-licensed
[proficiently-claude-skills](https://github.com/proficientlyjobs/proficiently-claude-skills) by Proficiently. Only the ideas were
taken; the code here is this project's own.
