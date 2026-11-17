"""One plain answer to "is this resume ATS-friendly?", from checks that already exist.

An ATS is an applicant tracking system: the software that reads a resume before a person does. This module does not read anything itself. It takes the PDF
check (builder/pdfcheck.py: what a parser gets out of the file) and, when there is one, the data check (builder/ats.py: what you wrote) and says:

  * "ATS-friendly"            no blocker and no warning in what makes a resume hard to read;
  * "Mostly ATS-friendly"     warnings only: something could be missed or misread;
  * "Not ATS-friendly yet"    a blocker: no text to read, no email, two columns, no Experience heading, a missing name, ...

Only the data check's `contact` and `format` findings count: they are about whether software can read the resume. Its `content` and `keywords` findings
(weak verbs, no numbers, missing skills) are advice about writing it well and about one particular job, and do not make a resume unreadable.

"ATS-friendly" is a claim about these checks, and the notice says so: it is not a promise about any employer's system. No HTTP and no HTML in here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

COUNTED = ("contact", "format")  # the data check's categories that are about readability
MOST_REASONS = 3
LABELS = {"compatible": "ATS-friendly", "mostly": "Mostly ATS-friendly", "not": "Not ATS-friendly yet"}
SUMMARIES = {
    "compatible": "These checks found nothing that an applicant tracking system is likely to trip on.",
    "mostly": "A few things could make an applicant tracking system miss or misread part of your resume. Fix the ones below.",
    "not": "Something here would stop an applicant tracking system from reading your resume properly.",
}
NOTICE = ("This is our own set of checks for what applicant tracking systems commonly trip on. \"ATS-friendly\" means these checks found no problem: it does not "
          "mean that any one employer's system will accept or rank your resume, and it says nothing about whether you would be hired.")


def _reasons(data: Optional[Mapping], pdf: Mapping) -> List[Dict[str, str]]:
    """Every blocker and warning that makes a resume hard to read, blockers first, each once however many checks found it."""
    found = [{"source": "pdf", "severity": f["severity"], "message": f["message"], "fix": f["fix"], "pointer": f.get("pointer", "")} for f in pdf["findings"]]
    for check in (data or {}).get("checks", []):
        if check["category"] in COUNTED and check["severity"] in ("error", "warn"):
            found.append({"source": "data", "severity": "blocker" if check["severity"] == "error" else "warning", "message": check["message"], "fix": check["fix"],
                          "pointer": check["pointer"]})
    unique: Dict[str, Dict[str, str]] = {}
    for reason in found:
        unique.setdefault(reason["message"], reason)
    return sorted(unique.values(), key=lambda reason: reason["severity"] != "blocker")  # a stable sort: the PDF's findings stay ahead of the data's


def decide(pdf: Mapping, data: Optional[Mapping] = None) -> Dict[str, Any]:
    """The verdict on a file (`pdf`, from pdfcheck.analyze) and, if the resume is one made here, on what was written (`data`, from ats.analyze)."""
    reasons = _reasons(data, pdf)
    blockers = sum(reason["severity"] == "blocker" for reason in reasons)
    warnings = len(reasons) - blockers
    if blockers or pdf["verdict"] == "hard":
        key = "not"
    elif warnings or pdf["score"] < 80:
        key = "mostly"
    else:
        key = "compatible"
    # a resume made here is printed to a PDF, so "the PDF file"; a file you brought is whatever it is (a PDF or a Word file): "the file"
    parts = [{"id": "pdf", "label": "The PDF file" if data is not None else "The file", "score": pdf["score"]}]
    if data is not None:
        parts.insert(0, {"id": "data", "label": "What you wrote", "score": data["score"]})
    return {"key": key, "label": LABELS[key], "summary": SUMMARIES[key], "reasons": reasons[:MOST_REASONS], "blockers": blockers, "warnings": warnings,
            "more": max(0, len(reasons) - MOST_REASONS), "parts": parts, "notice": NOTICE}
