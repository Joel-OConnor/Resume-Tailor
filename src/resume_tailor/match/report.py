"""Render a coverage result as the keyword analysis a tailoring prompt carries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.match.coverage import Coverage, Match
    from resume_tailor.match.gaps import Gap
    from resume_tailor.match.posting import Posting

__all__ = ["Report", "render_markdown"]


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
    """Cite a confirmed match: where it was used, and the accomplishment that shows it.

    Only confirmed matches are cited, and a match is confirmed only with evidence behind it, so
    the accomplishment is always there; the employers are not, when ``used_at`` was left empty.
    """
    where = ", ".join(match.employers)
    return f"{where} — {match.evidence[0]}" if where else match.evidence[0]


def render_markdown(report: Report) -> str:
    """Render the coverage as Markdown: what to lead with, what to qualify, and the gaps."""
    out: list[str] = ["## Keyword coverage", ""]
    out.append(
        f"Matched **{len(report.confirmed)} confirmed** and **{len(report.qualified)} qualified** "
        f"requirements; **{len(report.gaps)}** asked-for items are not supported by the profile."
    )

    out += ["", "### Confirmed — lead with these", ""]
    if report.confirmed:
        out.append("| Technology | Evidence |")
        out.append("|---|---|")
        out += [f"| {m.technology} | {_evidence_line(m)} |" for m in report.confirmed]
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
