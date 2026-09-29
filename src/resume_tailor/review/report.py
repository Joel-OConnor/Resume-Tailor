"""Render a review for the terminal."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.review.models import Finding, Review

__all__ = ["format_review"]


def format_review(review: Review, *, title: str = "Review") -> str:
    """Render a review as terminal lines: what was fixed, then every suggestion still standing.

    Questions are left out: whoever prints this either asks them or lists them in its own words.
    """
    counts = [f"{len(review.applied)} fixed"] if review.applied else []
    plural = "" if len(review.advice) == 1 else "s"
    counts.append(f"{len(review.advice)} suggestion{plural}")
    out = [f"{title}: " + " · ".join(counts)]
    for finding in review.advice:
        out.append(f"  ~ {_where(finding)}{finding.rule}: {finding.message}")
        if finding.text:
            out.append(f'      "{finding.text}"')
    return "\n".join(out) + "\n"


def _where(finding: Finding) -> str:
    return f"line {finding.line}  " if finding.line else ""
