"""Render a review for the terminal."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.review.models import Finding, Review

__all__ = ["format_review"]

_QUOTED = 3
"""How many of one kind of fix are quoted before the rest are only counted."""

_QUOTE_CHARS = 60


def format_review(review: Review, *, title: str = "Review") -> str:
    """Render a review as terminal lines: what each fix changed, then every suggestion standing.

    Fixes of one kind are listed once, with what they changed quoted as it was before, so a change
    made unattended (a skill dropped as a repeat, a full stop added) stays visible. They carry no
    line number, because most were made to a draft the editor has rewritten since. Questions are
    left out: whoever prints this either asks them or lists them in its own words.
    """
    counts = [f"{len(review.applied)} fixed"] if review.applied else []
    plural = "" if len(review.advice) == 1 else "s"
    counts.append(f"{len(review.advice)} suggestion{plural}")
    out = [f"{title}: " + " · ".join(counts)]
    for fixes in _kinds(review.applied):
        many = f" ({len(fixes)} lines)" if len(fixes) > 1 else ""
        out.append(f"  ✓ {fixes[0].rule}: {fixes[0].message}{many}")
        quoted = [fix.text for fix in fixes if fix.text]
        out += [f'      "{_clip(text)}"' for text in quoted[:_QUOTED]]
        if len(quoted) > _QUOTED:
            out.append(f"      … and {len(quoted) - _QUOTED} more")
    for finding in review.advice:
        out.append(f"  ~ {_where(finding)}{finding.rule}: {finding.message}")
        if finding.text:
            out.append(f'      "{finding.text}"')
    return "\n".join(out) + "\n"


def _kinds(fixes: tuple[Finding, ...]) -> list[list[Finding]]:
    """Group fixes that made the same change, in the order each kind was first made."""
    kinds: dict[tuple[str, str], list[Finding]] = {}
    for fix in fixes:
        kinds.setdefault((fix.rule, fix.message), []).append(fix)
    return list(kinds.values())


def _clip(text: str) -> str:
    return text if len(text) <= _QUOTE_CHARS else text[: _QUOTE_CHARS - 1].rstrip() + "…"


def _where(finding: Finding) -> str:
    return f"line {finding.line}  " if finding.line else ""
