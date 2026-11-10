"""Which computer this is, and the few commands that differ between Windows and Mac.

Everything the panel runs is the same Python program on both systems. Only three things are not:
opening a folder, installing a browser, and how to name them to the person. They live here, as plain
data in and out, so they can be tested for every system without owning one.
"""
from __future__ import annotations

import platform
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

WINDOWS, MAC, LINUX = "windows", "mac", "linux"
WINDOWS_11_FIRST_BUILD = 22000  # platform.release() still says "10" on Windows 11; the build number tells them apart


@dataclass(frozen=True)
class HostOS:
    family: str  # windows | mac | linux
    label: str  # shown to the person: "macOS 15.1 (Apple silicon)"
    file_manager: str  # what a folder opens in: "Finder", "File Explorer"

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


def detect(
    system: Optional[str] = None,
    release: Optional[str] = None,
    version: Optional[str] = None,
    machine: Optional[str] = None,
    mac_version: Optional[str] = None,
) -> HostOS:
    """Read the live system, or take the details as arguments (tests pass them in)."""
    system = system if system is not None else platform.system()
    release = release if release is not None else platform.release()
    version = version if version is not None else platform.version()
    machine = machine if machine is not None else platform.machine()
    if system == "Darwin":
        number = mac_version if mac_version is not None else platform.mac_ver()[0]
        chip = "Apple silicon" if machine in ("arm64", "aarch64") else "Intel"
        return HostOS(MAC, f"macOS {number} ({chip})".replace("  ", " "), "Finder")
    if system == "Windows":
        return HostOS(WINDOWS, f"Windows {_windows_name(release, version)}", "File Explorer")
    return HostOS(LINUX, f"{system or 'Linux'} {release}".strip(), "your file manager")


def _windows_name(release: str, version: str) -> str:
    build = version.rsplit(".", 1)[-1]
    if release == "10" and build.isdigit() and int(build) >= WINDOWS_11_FIRST_BUILD:
        return "11"
    return release


def open_folder_command(host: HostOS, folder: Path) -> List[str]:
    """The command that shows a folder in the system's file manager."""
    opener = {WINDOWS: "explorer", MAC: "open"}.get(host.family, "xdg-open")
    return [opener, str(folder)]


def install_browser_command(host: HostOS, which: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[str]]:
    """The package manager's command to install Chrome, or None when there is nothing to run it with."""
    if host.family == WINDOWS and which("winget"):
        return ["winget", "install", "-e", "--id", "Google.Chrome",
                "--accept-package-agreements", "--accept-source-agreements"]
    if host.family == MAC and which("brew"):
        return ["brew", "install", "--cask", "google-chrome"]
    return None
