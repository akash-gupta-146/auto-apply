"""`jobapply` command line."""
from __future__ import annotations

import argparse
import itertools
import logging
import signal
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .adapters import ADAPTERS
from .ai_answers import build_answerer
from .ai_facts import FactJudge, build_fact_judge
from .ai_fit import FitJudge
from .ai_prompts import PromptJudge
from .ai_settings import about_files, check_all, load_ai_settings
from .answer_book import AnswerBook
from .answer_tidy import apply_plan, describe, plan_tidy
from .answers import AnswerResolver, normalize
from .browser import DEFAULT_CDP, DOWN, READY, WINDOWLESS, cdp_state, explain_no_window, find_browser, launch_browser, open_page
from .config import (
    ConfigError,
    Paths,
    Profile,
    load_answers,
    load_criteria,
    load_profile,
    save_criteria,
    save_profile,
)
from .db import Database
from .engine import Engine
from .matching import evaluate
from .models import JobCard, SetupIncomplete
from .report import write_report
from .resume import guess_facts, read_text, sync_profile
from .system import announce, keep_awake
from .web.server import DEFAULT_PORT, serve

PORTAL_URLS = {
    "naukri": "https://www.naukri.com/nlogin/login",
    "instahyre": "https://www.instahyre.com/login/",
    "linkedin": "https://www.linkedin.com/login",
    "wellfound": "https://wellfound.com/login",
    "indeed": "https://secure.indeed.com/auth",
}


def setup_logging(paths: Paths) -> None:
    paths.ensure()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(paths.run_log, encoding="utf-8")],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one "HTTP Request" line per browser probe buries the useful lines


# -- prompts (init is interactive on purpose: the answers are yours, not the model's) ----------
def ask(label: str, default="") -> str:
    shown = f" [{default}]" if default not in ("", None) else ""
    return input(f"{label}{shown}: ").strip() or str(default)


def ask_bool(label: str, default: bool) -> bool:
    return ask(f"{label} (y/n)", "y" if default else "n").lower().startswith("y")


def ask_list(label: str, default: List[str]) -> List[str]:
    return [item.strip() for item in ask(f"{label} (comma separated)", ", ".join(default)).split(",") if item.strip()]


def cmd_init(args) -> None:
    if not sys.stdin.isatty():
        raise ConfigError("init is interactive: run `jobapply init --resume <path>` in your own terminal")
    paths = Paths.from_env()
    paths.ensure()
    resume = Path(args.resume).expanduser()
    facts = guess_facts(read_text(resume))
    profile = load_profile(paths) if paths.profile.exists() else Profile()
    criteria = load_criteria(paths)
    print("Answer once; these facts fill every application form. Enter keeps the [default].\n")
    profile.name = ask("Full name", profile.name or facts["name"])
    profile.email = ask("Email", profile.email or facts["email"])
    profile.phone = ask("Phone", profile.phone or facts["phone"])
    profile.city = ask("Current city", profile.city)
    profile.current_title = ask("Current job title", profile.current_title)
    profile.current_company = ask("Current company", profile.current_company)
    profile.total_experience_years = float(ask("Total years of experience", profile.total_experience_years or facts["years"]))
    profile.notice_period = ask("Notice period (e.g. 30 days)", profile.notice_period)
    profile.current_ctc = ask("Current CTC (e.g. 12 LPA)", profile.current_ctc)
    profile.expected_ctc = ask("Expected CTC (e.g. 18 LPA)", profile.expected_ctc)
    profile.willing_to_relocate = ask_bool("Willing to relocate?", profile.willing_to_relocate)
    profile.ok_with_onsite = ask_bool("OK with hybrid / work-from-office?", profile.ok_with_onsite)
    profile.education = ask("Highest education (degree, college, year)", profile.education)
    profile.linkedin = ask("LinkedIn URL (optional)", profile.linkedin)
    profile.github = ask("GitHub URL (optional)", profile.github)
    criteria.target_roles = ask_list("Target job titles (list variants: 'backend engineer, python developer')", criteria.target_roles)
    criteria.skip_roles = ask_list("Titles to skip (e.g. qa, sdet, sales)", criteria.skip_roles)
    criteria.locations = ask_list("Locations", criteria.locations or ([profile.city] if profile.city else []))
    criteria.blocked_companies = ask_list("Companies to never apply to", criteria.blocked_companies)
    added = sync_profile(profile, resume)
    save_profile(profile, paths)
    save_criteria(criteria, paths)
    print(f"\nSaved {paths.profile} and {paths.criteria}.")
    print(f"Detected {len(added)} skills in the resume: {', '.join(added) or 'none'}")
    print(f"Optional: open {paths.profile} and set years for the skills you want answered automatically.")
    print("Skills left as null are never answered (those questions are parked for you), never guessed.")


def cmd_panel(args) -> None:
    serve(Paths.from_env(), port=args.port, open_browser=not args.no_open)


def cmd_ai_test(args) -> None:
    """One tiny request to prove the AI helper's key and model work. Sends none of your documents."""
    paths = Paths.from_env()
    settings = load_ai_settings(paths)
    if not settings.configured:
        raise ConfigError("The AI helper is not set up. Run `jobapply panel` and choose AI helper.")
    key = f", key {settings.masked_key}" if settings.masked_key else ""
    print(f"AI: {settings.summary}{key}")
    results = check_all(settings)
    for position, (label, problem) in enumerate(results):
        print(f"  {'main' if position == 0 else f'backup {position}'}: {label}: {problem.splitlines()[0] if problem else 'works'}")
    failed = [problem for _, problem in results if problem]
    if failed:
        raise ConfigError(f"The AI did not accept the request: {failed[0]}" if len(results) == 1
                          else f"{len(failed)} of {len(results)} AIs did not accept the request (see above).")
    names = [p.name for p in about_files(paths)]
    print("Connection works.")
    print(f"It will read your resume plus {len(names)} extra document(s){': ' + ', '.join(names) if names else ''}.")


def cmd_doctor(args) -> None:
    paths = Paths.from_env()
    checks: List[tuple] = [("python >= 3.9", sys.version_info >= (3, 9), sys.version.split()[0])]
    checks.append(("profile.yaml", paths.profile.exists(), str(paths.profile)))
    criteria = load_criteria(paths)
    checks.append(("criteria.target_roles", bool(criteria.target_roles), str(criteria.target_roles)))
    exe = find_browser()
    checks.append(("browser executable", bool(exe), exe or "install BrowserOS neo (or Chrome), or set JOBAPPLY_BROWSER_EXE"))
    state = cdp_state(args.cdp)
    checks.append(("browser debug port", state == READY, {
        READY: args.cdp, DOWN: f"{args.cdp}  (start it: jobapply browser)",
        WINDOWLESS: f"{args.cdp} answers, but the browser has no window open (open one: jobapply browser)",
    }[state]))
    checks.append(("AI helper (optional)", load_ai_settings(paths).configured,
                   "set it up with the AI helper button in the control panel (jobapply panel)"))
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else '!!'}] {name}: {detail}")


def cmd_browser(args) -> None:
    paths = Paths.from_env()
    paths.ensure()
    state = cdp_state(args.cdp)
    if state == READY:
        print(f"Browser already open on {args.cdp}.")
        return
    exe = args.exe or find_browser()
    if not exe:
        raise ConfigError(
            "No BrowserOS neo or Chrome found. Install one, or pass --exe <path to browser exe> "
            "(or set JOBAPPLY_BROWSER_EXE)."
        )
    launch_browser(exe, paths.browser_profile, int(args.cdp.rsplit(":", 1)[1]))
    if state == WINDOWLESS:  # same profile, so the app that is still running opens a window instead of a second copy
        print("The browser was running with no window open. Opened one.")
        return
    print(f"Started {exe}\nwith a dedicated profile ({paths.browser_profile}).")
    print("Log in ONCE to each portal you want to use (a separate profile from your daily browser):")
    for portal, url in PORTAL_URLS.items():
        print(f"  {portal:10} {url}")


def _require_browser(cdp: str) -> None:
    state = cdp_state(cdp)
    if state == DOWN:
        raise ConfigError(f"No browser on {cdp}. Run `jobapply browser`, log in to the portal, then retry.")
    if state == WINDOWLESS:
        raise ConfigError(explain_no_window(cdp))


def cmd_run(args) -> None:
    paths = Paths.from_env()
    setup_logging(paths)
    profile, criteria = load_profile(paths), load_criteria(paths)
    if args.resume:
        added = sync_profile(profile, Path(args.resume).expanduser())
        save_profile(profile, paths)
        if added:
            logging.info("new skills from this resume: %s (set their years in profile.yaml)", ", ".join(added))
    if not profile.resume_path:
        raise ConfigError("Pass --resume <path-to-resume>")
    if not criteria.target_roles:
        raise ConfigError(f"No target_roles in {paths.criteria}. Run `jobapply init`.")
    _require_browser(args.cdp)
    db = Database(paths.db)
    ai = build_answerer(paths, profile, db, args.portal) if args.ai else None
    judge = FitJudge.from_answerer(ai, criteria.target_roles, paths.ai_fit_log) if ai is not None else None
    book = AnswerBook(paths, FactJudge.from_answerer(ai, paths.facts_log) if ai is not None else None)
    resolver = AnswerResolver(profile, book.wordings(), db, args.portal, ai=ai,
                              persist=lambda question, answer: book.remember(question, answer))  # an answer typed on a form folds in too
    with keep_awake(), open_page(args.cdp) as page:
        adapter = ADAPTERS[args.portal](page, profile, criteria, paths.failures)
        popups = PromptJudge.from_answerer(ai, paths.prompt_log) if ai is not None else None
        adapter.prompt_judge = popups  # with the AI helper on, a pop-up the rules do not know is asked about too
        if args.sync_resume:
            adapter.sync_resume(Path(profile.resume_path))
        engine = Engine(
            adapter, db, profile, criteria, resolver,
            minutes=args.minutes, dry_run=args.dry_run, reevaluate=args.reevaluate, suggested=args.suggested, fit_judge=judge, max_attempts=args.attempts,
            answers_loader=book.wordings,  # so an answer typed in the panel reaches a job that is waiting
        )
        try:
            summary = engine.run()
        except KeyboardInterrupt:
            summary = engine.summary
            summary.stop_reason = "interrupted by user"
    if ai is not None:
        summary.ai_answers, summary.ai_declined = dict(ai.used), list(ai.declined)
        summary.ai_fit = dict(judge.counts)
        summary.ai_popups = dict(popups.counts)
        summary.notes += [f"AI switch: {note}" for note in ai.client.switches]  # which company answered is worth knowing
    summary.dismissed = list(adapter.dismissed)
    report = write_report(summary, paths.reports)
    announce(f"{args.portal} {'dry-run ' if args.dry_run else ''}finished: {summary.done} done, stopped: {summary.stop_reason}. Report: {report}")


def cmd_probe(args) -> None:
    """Read-only smoke test of one adapter: login, search, read a job. Never applies."""
    paths = Paths.from_env()
    setup_logging(paths)
    profile, criteria = load_profile(paths), load_criteria(paths)
    _require_browser(args.cdp)
    with open_page(args.cdp) as page:
        adapter = ADAPTERS[args.portal](page, profile, criteria, paths.failures)
        try:
            logged_in = adapter.is_logged_in()
            print("logged in:", logged_in)
            if not logged_in:
                print(f"NOT logged in to {args.portal} in the automation browser. Log in there (the window opened by "
                      "`jobapply browser`), then run probe again.")
                return
            queries = list(itertools.islice(adapter.queries(), 3))
            print("queries:", *queries, sep="\n  ")
            try:
                cards = list(itertools.islice(adapter.discover(queries[0]), 5)) if queries else []
            except SetupIncomplete as exc:  # not a fault in the program: nothing to repair, so nothing is saved
                print(f"setup needed: {exc}")
                return
            print(f"first query found {len(cards)} cards:")
            for card in cards:
                print(f"  {card.title} @ {card.company} | {card.url}")
            if cards:
                job = adapter.read_job(cards[0])
                decision = evaluate(job, profile, criteria)
                print(f"read_job: desc={len(job.description)} chars, salary={job.salary!r}, applied={job.already_applied}")
                print(f"match decision: {decision}")
            elif queries:
                saved = adapter.capture_failure(JobCard(args.portal, queries[0], "probe: no cards found"))
                print(f"no cards found: page saved for repair at {saved}.*")
        except Exception:
            saved = adapter.capture_failure(JobCard(args.portal, adapter.active.url, "probe error"))
            print(f"probe failed: page saved for repair at {saved}.*")
            raise


def cmd_status(args) -> None:
    paths = Paths.from_env()
    db = Database(paths.db)
    for portal, counts in db.counts().items():
        print(portal, dict(sorted(counts.items())))
    print(f"AI requests today: {db.llm_calls_today()}")
    latest = sorted(paths.reports.glob("*.md"))[-1:] if paths.reports.exists() else []
    print("latest report:", latest[0] if latest else "none yet")


def _tidy_answers(paths: Paths, apply: bool) -> None:
    judge = build_fact_judge(paths)
    if judge is None:
        raise ConfigError("Tidying uses the AI helper to tell which questions are the same fact. Set it up in the control panel first.")
    plan = plan_tidy(load_answers(paths.answers), judge)
    print(describe(plan))
    if not plan.merges:
        return
    if not apply:
        print(f"\n{len(plan.merges)} to merge, {len(plan.needs_you)} need you. NOTHING was changed. Run again with --apply to do it (a backup is made first).")
        return
    print(f"\ndone. Your answers before this: {apply_plan(paths, plan)}  (copy it back over answers.yaml to undo)")


def cmd_answers(args) -> None:
    paths = Paths.from_env()
    if args.tidy:
        return _tidy_answers(paths, args.apply)
    db = Database(paths.db)
    if args.set:
        question, answer = args.set
        folded = AnswerBook(paths, build_fact_judge(paths)).remember(question, answer, [row["raw"] for row in db.pending_questions()])
        for wording in [question, *folded]:
            db.drop_question(normalize(wording))
        print("saved." + (f" It also answers {len(folded)} other way(s) of asking: {'; '.join(folded)}" if folded else ""))
        return
    known = {normalize(k) for k in AnswerBook(paths).wordings()}
    rows = [r for r in db.pending_questions() if r["norm"] not in known]
    for row in rows:
        print(f"- {row['raw']}" + (f"   [options: {row['options']}]" if row["options"] else ""))
    print(f"\n{len(rows)} unanswered. Answer with: jobapply answers --set \"<question>\" \"<answer>\"")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobapply", description="Apply to matching jobs with a deterministic engine.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.set_defaults(func=cmd_panel, port=DEFAULT_PORT, no_open=False)  # no command at all opens the panel
    sub = parser.add_subparsers(dest="cmd")

    def with_cdp(p):
        p.add_argument("--cdp", default=DEFAULT_CDP, help="browser debug URL (default %(default)s)")
        return p

    p = sub.add_parser("init", help="interview + resume -> profile.yaml / criteria.yaml")
    p.add_argument("--resume", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("panel", help="the control panel: buttons for every step (also what plain `jobapply` does)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="preferred port (default %(default)s; another is used if busy)")
    p.add_argument("--no-open", action="store_true", help="do not open the browser automatically")
    p.set_defaults(func=cmd_panel)

    p = with_cdp(sub.add_parser("doctor", help="check the setup"))
    p.set_defaults(func=cmd_doctor)

    p = with_cdp(sub.add_parser("browser", help="start the automation browser (BrowserOS neo, else Chrome)"))
    p.add_argument("--exe", help="path to the browser exe (default: auto-detect neo, then Chrome)")
    p.set_defaults(func=cmd_browser)

    p = with_cdp(sub.add_parser("run", help="apply on a portal"))
    p.add_argument("portal", choices=sorted(ADAPTERS))
    p.add_argument("--resume", help="resume file for this run (PDF/DOCX/TXT)")
    p.add_argument("--minutes", type=float, default=120, help="time budget for this run (default %(default)s)")
    p.add_argument("--dry-run", action="store_true", help="fill forms but never submit (also re-checks jobs skipped earlier)")
    p.add_argument("--reevaluate", action="store_true", help="live run: also re-check jobs skipped earlier: those that did not match (after you change your criteria) and those with no Easy Apply button")
    p.add_argument("--suggested", action="store_true",
                   help="apply to every job the site itself suggests (LinkedIn's Easy Apply picks, Naukri's recommended jobs, Instahyre's "
                        "opportunities), with no matching of roles, skills or salary; a company you blocked is still skipped. "
                        "Indeed suggests nothing, so it uses your role searches")
    p.add_argument("--attempts", type=int, metavar="N", help="stop after N live Apply clicks, whether they succeed or not (use N=1 to calibrate a portal)")
    p.add_argument("--sync-resume", action="store_true", help="upload the resume to the portal profile first (naukri)")
    p.add_argument("--ai", action="store_true",
                   help="let your AI helper answer form questions, only from your own documents (set up in `jobapply panel`)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ai-test", help="check that the AI helper's key and model work (sends none of your documents)")
    p.set_defaults(func=cmd_ai_test)

    p = with_cdp(sub.add_parser("probe", help="read-only adapter smoke test"))
    p.add_argument("portal", choices=sorted(ADAPTERS))
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("status", help="queue counts, AI usage, latest report")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("answers", help="review unanswered questions, or tidy the ones you have saved")
    p.add_argument("--set", nargs=2, metavar=("QUESTION", "ANSWER"))
    p.add_argument("--tidy", action="store_true", help="fold the saved questions that ask the same fact into one (shows the plan; changes nothing)")
    p.add_argument("--apply", action="store_true", help="with --tidy: really do it, after making a backup")
    p.set_defaults(func=cmd_answers)
    return parser


def _let_stop_reach_us() -> None:
    """A program started from a shell that ignores Ctrl+C would also ignore the panel's Stop button."""
    signal.signal(signal.SIGINT, signal.default_int_handler)
    if hasattr(signal, "SIGBREAK"):  # Windows: what the panel sends instead of Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


def _never_stop_on_a_character() -> None:
    """Job titles come from the internet. A Windows console, or a file the output is sent to, may not be able to show every
    character of one: show a ? in its place rather than end a run that may have 100 applications to go."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # not there when there is no console at all
            stream.reconfigure(errors="replace")


def main(argv: Optional[List[str]] = None) -> None:
    _never_stop_on_a_character()
    _let_stop_reach_us()
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
