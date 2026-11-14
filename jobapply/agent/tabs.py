"""Which open tab is the job? Asked when the person did not say, so the answer comes from what each tab shows, not from which is in front."""
from __future__ import annotations

from .models import PageKind
from .observe import observe
from .understand import classify


def about_a_job(page) -> bool:
    """Does this tab show a job, an application, or one of its steps (and not some other page)? A tab that cannot be read is not."""
    try:
        return classify(observe(page)).kind is not PageKind.UNRELATED
    except Exception:
        return False
