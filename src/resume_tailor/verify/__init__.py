"""Refuse to ship a claim the profile cannot defend.

This is where "never fabricates" stops being an instruction in a prompt and becomes a check that
runs. Generated Markdown goes in; every employer, title, date, credential, technology, and figure
is traced back to ``profile/master-profile.yaml``, and whatever does not trace back comes out as a
:class:`Violation` worded so the writer can fix it on its next attempt.

Precision matters in both directions. A missed fabrication ships a resume that collapses in the
first five minutes of a screen; a false alarm blocks a correct resume and burns a retry. So every
check here is deliberately narrow, and the traps it must not fall into — a number inside a
technology name, a year that is really a date, a resume that honestly shortens a real title — are
pinned by name in ``tests/test_verify.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resume_tailor.match import build_lexicon
from resume_tailor.verify.history import check_history
from resume_tailor.verify.metrics import check_metrics, supported_metrics
from resume_tailor.verify.models import Verdict, Violation
from resume_tailor.verify.skills import check_skills
from resume_tailor.verify.source import scan

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

__all__ = ["Verdict", "Violation", "format_violations", "supported_metrics", "verify_resume"]


def verify_resume(markdown: str, profile: Profile) -> Verdict:
    """Verify generated resume ``markdown`` against everything ``profile`` supports."""
    source = scan(markdown)
    lexicon = build_lexicon(profile)
    found = [
        *check_history(source, profile),
        *check_skills(source, lexicon),
        *check_metrics(source, profile, lexicon),
    ]
    unique = {violation.sort_key: violation for violation in found}
    return Verdict(tuple(sorted(unique.values(), key=lambda violation: violation.sort_key)))


def format_violations(verdict: Verdict) -> str:
    """Render a verdict as the numbered fix list a retry prompt hands back to the writer.

    Each line names the exact offending text and what to do about it, because the reader is a
    model with one more attempt and no other context about what it got wrong.
    """
    return "\n".join(
        f"{index}. line {violation.line}: {violation.text!r} {violation.reason}"
        for index, violation in enumerate(verdict.violations, start=1)
    )
