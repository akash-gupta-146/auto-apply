"""File names every computer will accept. macOS and Linux take whatever Windows takes, so there is one rule, not one per system."""
from __future__ import annotations

DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


def windows_safe(file_name: str) -> str:
    """Windows reads CON, NUL, COM1 and the rest, followed by anything (CON.pdf, nul.Smith.docx), as a device and not a file, and cannot make it.

    A name that starts that way gets an underscore in front; any other name is returned as it was.
    """
    return f"_{file_name}" if file_name.split(".")[0].upper() in DEVICE_NAMES else file_name
