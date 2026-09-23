"""Render a review for the terminal, and as a section of a fit report."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.review.models import Finding, Review

__all__ = ["format_review", "render_markdown"]

_MARK = {"fix": "✓", "advise": "~", "ask": "?"}


def format_review(review: Review) -> str:
    """Render a review as terminal lines: the fixes made, the advice, then the questions.

    A fix that is still pending — a review run with ``--no-fix`` — is listed too, marked so.
    """
    counts = [f"{len(review.applied)} fixed"]
    if review.fixes:
        counts.append(f"{len(review.fixes)} to fix")
    counts += [f"{len(review.advice)} suggestions", f"{len(review.questions)} questions"]
    out = ["Readability: " + " · ".join(counts)]
    for finding in (*review.applied, *review.fixes, *review.advice, *review.questions):
        pending = " (not applied)" if finding in review.fixes else ""
        out.append(
            f"  {_MARK[finding.level]} {_where(finding)}{finding.rule}: {finding.message}{pending}"
        )
        if finding.text and finding.level is not finding.level.FIX:
            out.append(f'      "{finding.text}"')
    return "\n".join(out) + "\n"


def render_markdown(review: Review) -> str:
    """Render a review as the ``## Readability review`` section of a fit report."""
    out = ["## Readability review", ""]
    if not (review.applied or review.advice or review.questions):
        out.append("Nothing to flag.")
        return "\n".join(out) + "\n"
    for title, findings in (
        ("Fixed automatically", review.applied),
        ("Suggestions", review.advice),
        ("Questions for you", review.questions),
    ):
        if not findings:
            continue
        out += [f"**{title}**", ""]
        out += [_item(finding) for finding in findings]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _where(finding: Finding) -> str:
    return f"line {finding.line}  " if finding.line else ""


def _item(finding: Finding) -> str:
    show = finding.text and finding.level is not finding.level.FIX
    quoted = f' ("{finding.text}")' if show else ""
    where = f"line {finding.line} " if finding.line else ""
    return f"- {where}{finding.rule}: {finding.message}{quoted}"
