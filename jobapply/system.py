"""OS-level helpers: audible alerts and keeping the machine awake during a run."""
from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys

log = logging.getLogger("jobapply")


def beep() -> None:
    try:
        if sys.platform == "win32":
            import winsound

            winsound.Beep(1000, 500)
        elif sys.platform == "darwin":
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
        else:
            print("\a", end="", flush=True)
    except Exception:  # an alert must never crash a run
        pass


def announce(message: str) -> None:
    """Log loudly and beep: used when a human is needed or a run ends."""
    log.warning("*** %s", message)
    beep()


@contextlib.contextmanager
def keep_awake():
    """Stop the OS from sleeping while a run is in progress."""
    helper = None
    try:
        if sys.platform == "win32":
            import ctypes

            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x1 | 0x2)
        elif sys.platform == "darwin":
            helper = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    except Exception:
        log.warning("could not enable keep-awake; disable sleep manually for long runs")
    try:
        yield
    finally:
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        if helper:
            helper.terminate()
