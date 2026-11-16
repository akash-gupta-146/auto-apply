"""The only things the panel can run.

Every command is built here from fixed words plus whole numbers that are checked first. Nothing typed
into the page, and nothing a web page sends, ever becomes part of a command, and no shell is involved. (The one thing typed that a run
needs, the address of a job page, is checked to be a web address and travels in the environment, never on the command line.)
Sending real applications also needs the person to type the confirmation word.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional
from urllib.parse import urlparse

from ..browser import check_address
from ..config import ConfigError
from .hostos import HostOS, install_browser_command

CONFIRM_WORD = "YES"
MAX_COUNT, MAX_MINUTES = 500, 720
DEFAULT_REHEARSAL_MINUTES = 10
DEFAULT_AGENT_MINUTES = 30
DEFAULT_AUTO_MINUTES = 120  # the longest an Auto-apply run goes on; the number of applications usually ends it first
AGENT_HANDOFF = ("rehearse", "apply")  # the portal runs that can hand a company-site job to the agent
PORTALS = {"naukri": "Naukri", "instahyre": "Instahyre", "linkedin": "LinkedIn", "indeed": "Indeed", "wellfound": "Wellfound"}  # the sites the panel can work on, in the order shown
DEFAULT_PORTAL = "naukri"


def listed(words, joiner: str = "or") -> str:
    """"A", "A or B", "A, B or C": the way a person lists things."""
    words = list(words)
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} {joiner} {words[-1]}"


class ActionError(ValueError):
    """A request the person can fix. The message is written for them."""


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    real_apply: bool = False  # sends real applications: needs the confirmation word and a count
    uses_ai: bool = False  # may carry the AI helper switch


@dataclass(frozen=True)
class Options:
    count: Optional[int] = None  # applications, at most
    minutes: Optional[int] = None  # minutes, at most
    ai: bool = False
    portal: str = DEFAULT_PORTAL
    recheck: bool = False  # also re-open the jobs skipped earlier (--reevaluate); last, so Options(3, 30, True) still means what it did
    suggested: bool = False  # apply to every job the site suggests, matching nothing (--suggested)
    send: bool = False  # the AI agent may really send (--submit), after you approve each application
    again: bool = False  # the AI agent carries on with the application left unfinished (--continue)
    agent: bool = False  # a job the site cannot apply to itself goes to the AI agent instead of being skipped (--agent)
    approval: bool = True  # the agent waits for your approval before it sends; False lets it send without asking (--no-approval)
    guess: bool = True  # the agent may guess a question nothing else can answer, and says so (False: --no-guess)
    url: str = ""  # the agent's job page address, opened in its browser: for a job found in some other browser, or in no browser yet
    review: bool = True  # Auto-apply shows you each job and applies only after you say so (--review); False sends by itself

    def __post_init__(self):  # whoever builds an Options, a site that is not on the list can never become part of a command
        if not isinstance(self.portal, str) or self.portal not in PORTALS:
            raise ActionError(f"Choose {listed(PORTALS.values())}.")


ACTIONS: Dict[str, Action] = {
    action.id: action
    for action in (
        Action("doctor", "Check my setup"),
        Action("browser", "Open the browser"),
        Action("check", "Check the site"),
        Action("rehearse", "Rehearsal (nothing is sent)", uses_ai=True),
        Action("apply", "Apply for real", real_apply=True, uses_ai=True),
        Action("auto", "Auto-apply", uses_ai=True),  # real applications too, but it asks for the confirmation word only when it will not ask you first
        Action("agent", "AI agent on the open page", uses_ai=True),
        Action("repair", "Repair the install"),
        Action("install_browser", "Install Chrome"),
    )
}


def _whole(raw: Mapping[str, object], key: str, label: str, high: int) -> Optional[int]:
    value = raw.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ActionError(f"{label} must be a whole number.")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ActionError(f"{label} must be a whole number.") from None
    if not 1 <= number <= high:
        raise ActionError(f"{label} must be between 1 and {high}.")
    return number


def _switch(raw: Mapping[str, object], key: str, label: str, default: bool = False) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ActionError(f"{label} must be on or off.")
    return value


def _address(raw: Mapping[str, object]) -> str:
    """A job page address, if one was given: a web address and nothing else, since it becomes part of a command."""
    value = raw.get("url", "")
    if not isinstance(value, str):
        raise ActionError("The job page address must be text.")
    try:
        return check_address(value) if value.strip() else ""
    except ConfigError as exc:
        raise ActionError(str(exc)) from None


def parse_options(raw: Mapping[str, object]) -> Options:
    return Options(
        count=_whole(raw, "count", "The number of applications", MAX_COUNT),
        minutes=_whole(raw, "minutes", "The number of minutes", MAX_MINUTES),
        ai=_switch(raw, "ai", "The AI helper switch"),
        portal=raw.get("portal", DEFAULT_PORTAL),  # the site is checked by Options itself
        recheck=_switch(raw, "recheck", "The re-check switch"),
        suggested=_switch(raw, "suggested", "The every-suggested-job switch"),
        send=_switch(raw, "send", "The sending switch"),
        again=_switch(raw, "again", "The continue switch"),
        agent=_switch(raw, "agent", "The AI agent switch"),
        approval=_switch(raw, "approval", "The wait-for-approval switch", default=True),
        guess=_switch(raw, "guess", "The guess switch", default=True),
        url=_address(raw),
        review=_switch(raw, "review", "The ask-me-first switch", default=True),
    )


def where_agent_works(options: Options) -> str:
    return (urlparse(options.url).hostname or "the page you gave") if options.url and not options.again else "the open page"


def describe(action_id: str, options: Options) -> str:
    """What to call this run on screen: the action and, for the ones that work on a site, which site."""
    site = PORTALS[options.portal]
    return {
        "check": f"Check {site}",
        "rehearse": f"Rehearsal on {site} (nothing is sent)",
        "apply": f"Apply for real on {site}",
        "auto": f"Auto-apply on {site} (asks you before each one)" if options.review else f"Auto-apply on {site} (sends by itself)",
        "agent": f"AI agent on {where_agent_works(options)} (it may send, after you approve)" if options.send
        else f"AI agent on {where_agent_works(options)} (nothing is sent)",
    }.get(action_id, ACTIONS[action_id].label)


def build_command(
    action_id: str,
    options: Options,
    confirm: str,
    host: HostOS,
    root: Path,
    python: str = sys.executable,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> List[str]:
    """The exact command for one action, or an ActionError saying what is missing."""
    action = ACTIONS.get(action_id)
    if action is None:
        raise ActionError("I do not know that action.")
    program = [python, "-m", "jobapply"]
    ai = ["--ai"] if action.uses_ai and options.ai else []
    switches = ["--reevaluate"] if options.recheck else []  # each switch is only ever one fixed word
    switches += ["--suggested"] if options.suggested else []
    switches += ["--agent"] if options.agent and action_id in AGENT_HANDOFF else []
    unattended = ["--no-approval"] if not options.approval else []  # only ever added next to the switch that makes it mean something
    # A guess is acceptable because you see it before anything is sent, so it is off whenever sending needs no approval; and it only
    # means something next to the AI helper. Either way the command says so in one fixed word.
    sends_unasked = not options.approval and (options.send or action.real_apply)  # a rehearsal sends nothing, so it has nothing to approve
    no_guess = ["--no-guess"] if ai and (not options.guess or sends_unasked) else []

    if action.real_apply:
        if confirm != CONFIRM_WORD:
            raise ActionError(f"Type {CONFIRM_WORD} to confirm: this sends real applications.")
        if options.count is None or options.minutes is None:
            raise ActionError("Say how many applications and how many minutes, at most.")
        return program + ["run", options.portal, "--minutes", str(options.minutes), "--attempts", str(options.count)] + ai + switches + (unattended + no_guess if options.agent else [])
    if action_id == "auto":
        if options.count is None:
            raise ActionError("Say how many applications, at most.")
        if not options.review and confirm != CONFIRM_WORD:
            raise ActionError(f"Type {CONFIRM_WORD} to confirm: this sends real applications without asking you first.")
        return program + ["run", options.portal, "--minutes", str(options.minutes or DEFAULT_AUTO_MINUTES), "--attempts", str(options.count)] + ai \
            + (["--review"] if options.review else [])
    if action_id == "rehearse":
        minutes = options.minutes or DEFAULT_REHEARSAL_MINUTES
        return program + ["run", options.portal, "--dry-run", "--minutes", str(minutes)] + ai + switches
    if action_id == "agent":
        if options.send and confirm != CONFIRM_WORD:
            raise ActionError(f"Type {CONFIRM_WORD} to confirm: the agent may send real applications (you still approve each one).")
        flags = (["--submit"] + unattended if options.send else []) + (["--continue"] if options.again else [])
        return program + ["agent", "--minutes", str(options.minutes or DEFAULT_AGENT_MINUTES)] + flags + ai + no_guess
    if action_id == "repair":
        if not (root / "pyproject.toml").exists():
            raise ActionError("This copy of the program is not installed from a folder, so there is nothing to repair here.")
        return [python, "-m", "pip", "install", "--quiet", "-e", str(root)]
    if action_id == "install_browser":
        command = install_browser_command(host, which)
        if command is None:
            raise ActionError("I cannot install Chrome for you on this computer. Download it from google.com/chrome.")
        return command
    return program + {"doctor": ["doctor"], "browser": ["browser"], "check": ["probe", options.portal]}[action_id]
