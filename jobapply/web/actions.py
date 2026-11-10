"""The only things the panel can run.

Every command is built here from fixed words plus whole numbers that are checked first. Nothing typed
into the page, and nothing a web page sends, ever becomes part of a command, and no shell is involved.
Sending real applications also needs the person to type the confirmation word.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from .hostos import HostOS, install_browser_command

CONFIRM_WORD = "YES"
MAX_COUNT, MAX_MINUTES = 500, 720
DEFAULT_REHEARSAL_MINUTES = 10
PORTALS = {"naukri": "Naukri", "instahyre": "Instahyre", "linkedin": "LinkedIn", "indeed": "Indeed"}  # the sites the panel can work on, in the order shown
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


def parse_options(raw: Mapping[str, object]) -> Options:
    ai = raw.get("ai", False)
    if not isinstance(ai, bool):
        raise ActionError("The AI helper switch must be on or off.")
    recheck = raw.get("recheck", False)
    if not isinstance(recheck, bool):
        raise ActionError("The re-check switch must be on or off.")
    suggested = raw.get("suggested", False)
    if not isinstance(suggested, bool):
        raise ActionError("The every-suggested-job switch must be on or off.")
    return Options(
        count=_whole(raw, "count", "The number of applications", MAX_COUNT),
        minutes=_whole(raw, "minutes", "The number of minutes", MAX_MINUTES),
        ai=ai,
        portal=raw.get("portal", DEFAULT_PORTAL),  # the site is checked by Options itself
        recheck=recheck,
        suggested=suggested,
    )


def describe(action_id: str, options: Options) -> str:
    """What to call this run on screen: the action and, for the ones that work on a site, which site."""
    site = PORTALS[options.portal]
    return {
        "check": f"Check {site}",
        "rehearse": f"Rehearsal on {site} (nothing is sent)",
        "apply": f"Apply for real on {site}",
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

    if action.real_apply:
        if confirm != CONFIRM_WORD:
            raise ActionError(f"Type {CONFIRM_WORD} to confirm: this sends real applications.")
        if options.count is None or options.minutes is None:
            raise ActionError("Say how many applications and how many minutes, at most.")
        return program + ["run", options.portal, "--minutes", str(options.minutes), "--attempts", str(options.count)] + ai + switches
    if action_id == "rehearse":
        minutes = options.minutes or DEFAULT_REHEARSAL_MINUTES
        return program + ["run", options.portal, "--dry-run", "--minutes", str(minutes)] + ai + switches
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
