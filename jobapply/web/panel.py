"""What the panel's buttons do. No HTTP in here: the server calls these and sends back what they return.

Before anything starts, the panel checks what that step needs (a saved profile, an open browser, an AI helper) and
says so in plain words, instead of letting the program fail with a stack trace in the log.
"""
from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import yaml

from .. import __version__
from ..ai_settings import load_ai_settings
from ..browser import AGENT_URL_ENV, DEFAULT_CDP, DOWN, READY, WINDOWLESS, cdp_state, find_browser
from ..config import Criteria, Paths, Profile, load_answers, load_criteria, load_profile
from ..review import APPROVE, REJECT
from ..report_names import report_label, report_portal
from ..db import sent_today_counts
from . import applications, auto, dashboard, hostos, privacy, questions
from .freshness import Freshness
from .assistant import Assistant
from .actions import ACTIONS, DEFAULT_PORTAL, PORTALS, ActionError, Options, build_command, describe, parse_options
from .hostos import HostOS
from .resumes import ResumeTab
from .runner import FAILED, FINISHED, STOPPED, Busy, JobRunner

NEEDS_BROWSER = {"check", "rehearse", "apply", "agent", "auto"}
NEEDS_PROFILE = {"rehearse", "apply", "agent", "auto"}
FOLDERS = ("data", "reports")
RECENT_REPORTS = 8
MAX_REPORT_BYTES = 200_000
READ_ERRORS = (OSError, ValueError, TypeError, yaml.YAMLError)  # a damaged file must not take the panel down


def display_command(command: List[str]) -> str:
    """What to show in the log: `jobapply run ...` rather than the long path of this computer's Python."""
    if command[1:3] == ["-m", "jobapply"]:
        return shlex.join(["jobapply"] + command[3:])
    return shlex.join(command)


class Panel:
    def __init__(
        self,
        paths: Paths,
        root: Path,
        runner: Optional[JobRunner] = None,
        host: Optional[HostOS] = None,
        command_for: Callable[..., List[str]] = build_command,
        browser_state: Callable[[], str] = lambda: cdp_state(DEFAULT_CDP),
        popen: Callable[..., object] = subprocess.Popen,
        freshness: Optional[Freshness] = None,
    ):
        self.paths, self.root = paths, root
        self.runner = runner or JobRunner()
        self.host = host or hostos.detect()
        self.command_for, self.browser_state, self.popen = command_for, browser_state, popen
        self.checked: Dict[str, str] = {}  # what the last "Check" saw on each site: ok, logged_out or needs_setup
        self._action, self._portal = "", DEFAULT_PORTAL
        self._login_read_for = 0
        self.assistant = Assistant(paths, PORTALS, DEFAULT_PORTAL)  # "Ask the AI" on the Auto fill form tab
        self.resumes = ResumeTab(paths, self._profile)  # the Create Resume tab: build, check, tailor and export a resume
        self.freshness = freshness or Freshness()  # taken now: what this panel started with

    # -- what is true right now ----------------------------------------------------------------
    def state(self, since: int = 0) -> Dict[str, Any]:
        run = self.runner.snapshot(since)
        self._learn_check(run)
        return {"os": self.host.as_dict(), "version": __version__, "stale": self.freshness.stale(), "setup": self.setup(), "run": run,
                "agent": applications.live(self.paths), "auto": self.auto()}

    def auto(self) -> Dict[str, Any]:
        """The Auto-apply v2 tab's part of every look: the job being asked about, today's count against the limit, the latest outcomes."""
        return auto.live(self.paths, self._read(load_criteria, self.paths) or Criteria(), self._read_db, PORTALS)

    def setup(self) -> Dict[str, Any]:
        profile, criteria = self._profile(), self._read(load_criteria, self.paths)
        ai = self._read(load_ai_settings, self.paths)
        reports, browser, queues = self.report_names(), self.browser_state(), self._queue_counts()
        return {
            "profile": {"saved": bool(profile), "name": profile.name if profile else "",
                        "resume": Path(profile.resume_path).name if profile and profile.resume_path else ""},
            "roles": len(criteria.target_roles) if criteria else 0,
            "questions": len(questions.waiting(self.paths)),  # asked by runs, not yet answered by you
            "browser": {"found": bool(find_browser()), "running": browser == READY, "windowless": browser == WINDOWLESS},
            "sites": {portal: {"check": self.checked.get(portal), "queue": queues.get(portal, {})} for portal in PORTALS},
            "ai": {"configured": bool(ai and ai.configured),
                   "label": ai.summary if ai and ai.configured else ""},
            "reports": reports,
            "report_labels": {name: report_label(name) for name in reports},  # what to show on each button
            "report_sites": {name: PORTALS[site] for name in reports if (site := report_portal(name)) in PORTALS},
            "privacy": self.privacy_items(),
            "dashboard": dashboard.summarize(queues, PORTALS),  # the Profile tab's picture of every job each site has been through
        }

    @staticmethod
    def _read(loader: Callable, paths: Paths):
        try:
            return loader(paths)
        except READ_ERRORS:
            return None

    def _profile(self) -> Optional[Profile]:
        return self._read(load_profile, self.paths) if self.paths.profile.exists() else None

    def _read_db(self, work: Callable[[sqlite3.Connection], Any], default: Any) -> Any:
        """Read the jobs file without disturbing a run that is writing to it. `default` when there is no file or it cannot be read."""
        if not self.paths.db.exists():
            return default
        try:
            connection = sqlite3.connect(f"{self.paths.db.as_uri()}?mode=ro", uri=True, timeout=2)
            try:
                return work(connection)
            finally:
                connection.close()
        except sqlite3.Error:
            return default

    def _queue_counts(self) -> Dict[str, Dict[str, int]]:
        """Each site's queue."""
        return self._read_db(dashboard.counts, {})

    def ask(self, body: Mapping[str, Any]) -> Dict[str, str]:
        """A question about your job search, answered by the AI helper from your details and applications (see assistant.py)."""
        return self.assistant.ask(body, profile=self._profile(), criteria=self._read(load_criteria, self.paths),
                                  answers=self._read(load_answers, self.paths.answers) or {}, read_db=self._read_db)

    def jobs(self, group: object, site: object) -> Dict[str, Any]:
        """The jobs behind one number on the Profile tab's dashboard (`site` empty: all sites)."""
        group, site = str(group or ""), str(site or "")
        try:
            dashboard.check(group, site, PORTALS)  # even with no jobs file yet, a wrong question gets a clear answer
        except ValueError as exc:
            raise ActionError(str(exc)) from None
        return self._read_db(lambda connection: dashboard.listing(connection, group, site, PORTALS), dashboard.packed(group, site, 0, []))

    def _learn_check(self, run: Mapping[str, Any]) -> None:
        """After a "Check" run, remember what its own output said about the site it looked at."""
        done = run["state"] in (FINISHED, FAILED, STOPPED)
        if self._action != "check" or not done or self._login_read_for == run["run_id"]:
            return
        self._login_read_for = run["run_id"]
        text = "\n".join(self.runner.snapshot(0)["lines"])
        if "setup needed:" in text:  # the probe prints this after "logged in: True", so it is read first
            self.checked[self._portal] = "needs_setup"
        elif "logged in: True" in text:
            self.checked[self._portal] = "ok"
        elif "logged in: False" in text:
            self.checked[self._portal] = "logged_out"

    # -- doing things --------------------------------------------------------------------------
    def run(self, raw: Mapping[str, object]) -> Dict[str, str]:
        """Start one action. Raises ActionError (fixable) or Busy (something is already running)."""
        self.runner.ensure_idle()
        action_id = raw.get("action")
        if not isinstance(action_id, str) or action_id not in ACTIONS:
            raise ActionError("I do not know that action.")
        options = parse_options(raw)
        self._require(action_id, options)
        command = self.command_for(action_id, options, str(raw.get("confirm") or ""), self.host, self.root)
        self._action, self._portal = action_id, options.portal
        label = describe(action_id, options)
        self.runner.start(label, command, self._environment(options if action_id == "agent" else None), str(self.root), f"$ {display_command(command)}")
        return {"started": label}

    def _require(self, action_id: str, options: Options) -> None:
        if action_id in NEEDS_PROFILE:
            profile = self._profile()
            if not profile or not profile.resume_path:
                raise ActionError("Set up your profile and resume first (the Profile and resume button).")
        opens_its_own_window = action_id == "agent" and bool(options.url) and not options.again  # a job page address brings a lost window back
        if action_id in NEEDS_BROWSER and self.browser_state() != READY and not (opens_its_own_window and self.browser_state() == WINDOWLESS):
            site = "the site" if action_id == "agent" else PORTALS[options.portal]  # the agent works on whatever site you have open
            raise ActionError("The browser has no window open. Press Open the browser (step 2) to bring one back."
                              if self.browser_state() == WINDOWLESS
                              else f"Open the browser first (step 2) and log in to {site} in it.")
        if action_id == "agent" and options.again and not applications.unfinished(self.paths):
            raise ActionError("There is no unfinished application to continue. Open a job page and start the agent instead.")
        if action_id == "auto":
            self._require_room(options.portal)
        ai = self._read(load_ai_settings, self.paths)
        if options.ai and not (ai and ai.configured):
            raise ActionError("The AI helper is not set up yet. Use the AI helper button, or turn the switch off.")

    def _require_room(self, portal: str) -> None:
        """Today's limit has room: otherwise the run would open a browser only to stop at once."""
        cap = (self._read(load_criteria, self.paths) or Criteria()).daily_cap
        sent = self._read_db(sent_today_counts, {}).get(portal, 0)
        if 0 < cap <= sent:
            raise ActionError(f"You have already sent {sent} of today's {cap} on {PORTALS[portal]}. Raise the daily limit on this tab, or come back tomorrow.")

    def _environment(self, agent_options: Optional[Options] = None) -> Dict[str, str]:
        env = dict(os.environ)
        env.update(JOBAPPLY_HOME=str(self.paths.home), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        env.pop(AGENT_URL_ENV, None)  # whatever this was started with is not this run's job page
        if agent_options is not None and agent_options.url and not agent_options.again:  # continuing carries on where it was
            env[AGENT_URL_ENV] = agent_options.url
        return env

    def agent_decide(self, body: Mapping[str, object]) -> Dict[str, bool]:
        """Your answer to 'may I send this?'. Only counts for the application that asked."""
        session, decision = body.get("session"), body.get("decision")
        if not isinstance(session, str) or not isinstance(decision, str):
            raise ActionError("That answer was not understood.")
        return {"recorded": applications.decide(self.paths, session, decision)}

    def auto_decide(self, body: Mapping[str, object]) -> Dict[str, bool]:
        """Your answer to 'apply to this one?'. Only counts for the job that asked."""
        token, decision = body.get("token"), body.get("decision")
        if not isinstance(token, str) or decision not in (APPROVE, REJECT):
            raise ActionError("That answer was not understood.")
        return {"recorded": auto.decide(self.paths, token, decision)}

    def auto_limit(self, body: Mapping[str, object]) -> Dict[str, int]:
        try:
            return {"cap": auto.set_cap(self.paths, body.get("cap"))}
        except ValueError as exc:
            raise ActionError(str(exc)) from None

    def auto_pause(self, body: Mapping[str, object]) -> Dict[str, bool]:
        if not isinstance(body.get("paused"), bool):
            raise ActionError("Say whether to pause or resume.")
        auto.pause(self.paths, body["paused"])
        return {"paused": body["paused"]}

    def auto_history(self, group: object, text: object, days: object) -> Dict[str, Any]:
        """The tracker table: what runs acted on, narrowed the way the person chose."""
        return auto.history(self._read_db, PORTALS, **self._narrowed(group, text, days))

    def export_csv(self, group: object = "", text: object = "", days: object = 0) -> str:
        return auto.export(self._read_db, PORTALS, **self._narrowed(group, text, days))

    @staticmethod
    def _narrowed(group: object, text: object, days: object) -> Dict[str, Any]:
        try:
            return auto.narrowed(group, text, days)
        except ValueError as exc:
            raise ActionError(str(exc)) from None

    def agent_pause(self, body: Mapping[str, object]) -> Dict[str, bool]:
        if not isinstance(body.get("paused"), bool):
            raise ActionError("Say whether to pause or resume.")
        applications.pause(self.paths, body["paused"])
        return {"paused": body["paused"]}

    def stop(self) -> bool:
        return self.runner.stop()

    def open_folder(self, target: object) -> Dict[str, str]:
        if target not in FOLDERS:
            raise ActionError("I can only open the data folder or the reports folder.")
        folder = self.paths.home if target == "data" else self.paths.reports
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.popen(hostos.open_folder_command(self.host, folder))
        except OSError as exc:
            raise ActionError(f"I could not open {self.host.file_manager}: {exc}") from exc
        return {"opened": str(folder)}

    def report_names(self) -> List[str]:
        if not self.paths.reports.exists():
            return []
        return [path.name for path in sorted(self.paths.reports.glob("*.md"), reverse=True)[:RECENT_REPORTS]]

    def _report_path(self, name: object) -> Path:
        """Only names this panel itself listed can be asked for: nothing typed can point at another file."""
        if name not in self.report_names():
            raise ActionError("That report is not there.")
        return self.paths.reports / str(name)

    def report(self, name: object) -> str:
        data = self._report_path(name).read_bytes()[:MAX_REPORT_BYTES]
        return data.decode("utf-8", errors="replace")

    def delete_report(self, name: object) -> Dict[str, Any]:
        self._report_path(name).unlink(missing_ok=True)
        return {"deleted": name}

    # -- deleting personal information ----------------------------------------------------------
    def privacy_items(self) -> List[Dict[str, Any]]:
        return [{"id": kind.id, "label": kind.label, "what": kind.what, "present": privacy.present(self.paths, kind)}
                for kind in privacy.KINDS]

    def erase(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        wanted = body.get("items")
        if not isinstance(wanted, list) or not wanted:
            raise ActionError("Choose what to delete first.")
        if not all(isinstance(item, str) and item in privacy.BY_ID for item in wanted):
            raise ActionError("That is not something I can delete.")
        if body.get("confirm") != "DELETE":
            raise ActionError("Type DELETE in capital letters to confirm.")
        if self.runner.busy:
            raise Busy("A run is in progress.")
        if "login" in wanted and self.browser_state() != DOWN:  # running, even with no window, it still holds the login
            raise ActionError("The browser this program opened is still using your saved logins. Quit it completely "
                              "(on a Mac: BrowserOS neo > Quit; closing its window is not enough), then try again.")
        deleted, failed = privacy.erase(self.paths, wanted)
        if "login" in deleted:
            self.checked.clear()  # the sessions are gone, so what the last checks saw is no longer true
        if "logs" in deleted:
            self.runner.forget_output()
        return {"deleted": deleted, "failed": [{"id": kind, "reason": reason} for kind, reason in failed.items()]}
