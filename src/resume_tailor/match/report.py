"""Render a coverage result for a human, for a fit report, or for another tool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resume_tailor.match.coverage import Coverage, Match
    from resume_tailor.match.gaps import Gap
    from resume_tailor.match.posting import Posting

__all__ = ["Report", "render_json", "render_markdown", "render_text"]


@dataclass(frozen=True, slots=True)
class Report:
    """Everything a fit report needs, computed once."""

    posting: Posting
    coverage: Coverage
    gaps: tuple[Gap, ...]

    @property
    def confirmed(self) -> tuple[Match, ...]:
        """Matches strong enough to lead a resume with."""
        return tuple(m for m in self.coverage.matches if m.satisfies_must_have)

    @property
    def qualified(self) -> tuple[Match, ...]:
        """Real matches carrying a caveat the user must read before using them."""
        return tuple(m for m in self.coverage.matches if not m.satisfies_must_have)


def _evidence_line(match: Match) -> str:
    parts: list[str] = []
    if match.employers:
        parts.append(", ".join(match.employers))
    if match.evidence:
        parts.append(match.evidence[0])
    return " — ".join(parts)


def render_text(report: Report) -> str:
    """Render a terminal summary."""
    out: list[str] = []
    title = report.posting.title or "this posting"
    out.append(f"Coverage for {title}")
    if report.posting.company:
        out.append(f"  company: {report.posting.company}")
    out.append(
        f"  {len(report.confirmed)} confirmed · {len(report.qualified)} qualified · "
        f"{len(report.gaps)} not supported"
    )

    if report.confirmed:
        out += ["", "LEAD WITH THESE"]
        out += [f"  ✓ {m.technology:<34} {_evidence_line(m)}" for m in report.confirmed]

    if report.qualified:
        out += ["", "USE WITH CARE"]
        for match in report.qualified:
            out += _qualified_lines(match)

    if report.gaps:
        out += ["", "ASKED FOR, NOT IN YOUR PROFILE"]
        for gap in report.gaps:
            suffix = (
                f"   (looks like {gap.near_miss} — add an alias if that is what they mean)"
                if gap.near_miss
                else ""
            )
            out.append(f"  ✗ {gap.term}{suffix}")

    if report.coverage.ignored:
        out += ["", "IGNORED (not requirements)"]
        out += [
            f"  line {line}: {reason} — {text[:60]}"
            for line, reason, text in report.coverage.ignored
        ]

    return "\n".join(out) + "\n"


def _qualified_lines(match: Match) -> list[str]:
    where = _evidence_line(match)
    lines = [f"  ~ {match.technology}" + (f"   [{where}]" if where else "")]
    if match.unconfirmed:
        lines.append("      UNCONFIRMED — your profile notes flag this; confirm before use")
    if match.is_shallow:
        lines.append(f"      depth: recorded as {match.level}")
    if match.caveat:
        lines.append(f"      {match.caveat}")
    return lines


def render_markdown(report: Report) -> str:
    """Render the body of a ``fit-report.md``."""
    out: list[str] = ["## Keyword coverage", ""]
    out.append(
        f"Matched **{len(report.confirmed)} confirmed** and **{len(report.qualified)} qualified** "
        f"requirements; **{len(report.gaps)}** asked-for items are not supported by the profile."
    )

    out += ["", "### Confirmed — lead with these", ""]
    if report.confirmed:
        out.append("| Technology | Evidence |")
        out.append("|---|---|")
        out += [f"| {m.technology} | {_evidence_line(m) or '—'} |" for m in report.confirmed]
    else:
        out.append("_Nothing in this posting is matched by a confirmed, evidenced technology._")

    if report.qualified:
        out += ["", "### Qualified — true, but read the caveat", ""]
        for match in report.qualified:
            notes = [match.caveat] if match.caveat else []
            if match.is_shallow:
                notes.append(f"profile records this as **{match.level}**")
            if match.unconfirmed:
                notes.append(f"**unconfirmed** — {match.unconfirmed}")
            out.append(f"- **{match.technology}** — {'; '.join(notes)}")

    if report.gaps:
        out += ["", "### Gaps — asked for, not supported", ""]
        for gap in report.gaps:
            hint = f" _(possibly an alias of {gap.near_miss})_" if gap.near_miss else ""
            out.append(f"- {gap.term}{hint}")
        out += ["", "Do not add any of these to the resume unless they are true."]

    if report.coverage.ignored:
        out += ["", "### Ignored", "", "Text that mentions a technology without requiring it:", ""]
        out += [
            f"- line {line}: _{reason}_ — {text[:80]}"
            for line, reason, text in report.coverage.ignored
        ]

    return "\n".join(out) + "\n"


def render_json(report: Report) -> str:
    """Machine-readable output."""
    payload: dict[str, Any] = {
        "posting": {"title": report.posting.title, "company": report.posting.company},
        "confirmed": [_as_dict(m) for m in report.confirmed],
        "qualified": [_as_dict(m) for m in report.qualified],
        "gaps": [
            {"term": g.term, "lines": list(g.lines), "near_miss": g.near_miss} for g in report.gaps
        ],
        "ignored": [
            {"line": line, "reason": reason, "text": text}
            for line, reason, text in report.coverage.ignored
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _as_dict(match: Match) -> dict[str, Any]:
    return {
        "technology": match.technology,
        "group": match.group,
        "matched_text": match.matched_text,
        "confidence": match.confidence.value,
        "provenance": match.provenance.value,
        "sections": [section.value for section in match.sections],
        "lines": list(match.lines),
        "employers": list(match.employers),
        "evidence": list(match.evidence),
        "level": match.level,
        "unconfirmed": match.unconfirmed,
        "caveat": match.caveat,
    }
