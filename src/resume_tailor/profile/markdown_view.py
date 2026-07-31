"""Render a :class:`Profile` as Markdown for humans to read and proofread.

The YAML is the source of truth; this is a generated view. Editing the Markdown does nothing —
which is exactly why it is gitignored and regenerated on demand.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile, Role, Tenure

__all__ = ["format_period", "render_markdown"]

_WHITESPACE = re.compile(r"\s+")


def _line(text: str) -> str:
    """Flatten a value onto one line.

    Profile values are folded YAML scalars, so any of them can carry a newline. A blank line
    inside a list item ends the list; a leading ``#`` or ``-`` starts a heading or a sibling item.
    Every profile value interpolated below goes through here — a partial application is what let
    the first version of this fix through.
    """
    return _WHITESPACE.sub(" ", text).strip()


def _joined(values: tuple[str, ...], separator: str = ", ") -> str:
    """Flatten and join a tuple of profile values."""
    return separator.join(_line(value) for value in values)


_BLOCK_LEADER = re.compile(r"^(#{1,6}\s|>|[-+*]\s|[0-9]{1,9}[.)]\s|```|~~~|---|===)")


def _block(text: str) -> str:
    """Flatten a value that occupies a whole output line, and defuse any block marker.

    A value of ``` would otherwise open a fence that swallows the rest of the document, and a
    leading ``#`` would inject a heading into the middle of it.
    """
    flat = _line(text)
    return "\\" + flat if _BLOCK_LEADER.match(flat) else flat


_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _month_name(value: str) -> str:
    """Turn ``2022-06`` into ``June 2022``; leave ``2022`` and ``present`` alone."""
    if value == "present":
        return "Present"
    year, _, month = value.partition("-")
    if not month:
        return year
    return f"{_MONTHS[int(month) - 1]} {year}"


def format_period(start: str, end: str) -> str:
    """Render a date range the way a resume prints it."""
    return f"{_month_name(start)} – {_month_name(end)}"


def render_markdown(profile: Profile) -> str:
    """Render the whole profile as Markdown."""
    out: list[str] = [
        f"# Master Profile — {_line(profile.contact.name)}",
        "",
        "> Generated from `profile/master-profile.yaml`. Edit the YAML, not this file.",
        "",
    ]
    _contact(profile, out)
    _target_roles(profile, out)
    _section(out, "Professional summary", [_block(profile.summary)])
    _technologies(profile, out)
    _experience(profile, out)
    _education(profile, out)
    _credentials(profile, out)
    _projects(profile, out)
    _notes(profile, out)
    return "\n".join(out).rstrip() + "\n"


def _section(out: list[str], title: str, body: list[str]) -> None:
    out += [f"## {title}", "", *body, ""]


def _contact(profile: Profile, out: list[str]) -> None:
    contact = profile.contact
    lines = [f"- **Name:** {_line(contact.name)}", f"- **Headline:** {_line(contact.headline)}"]
    for label, value in (
        ("Location", contact.location),
        ("Email", contact.email),
        ("Phone", contact.phone),
        ("Work authorization", contact.work_authorization),
    ):
        if value:
            lines.append(f"- **{label}:** {_line(value)}")
    lines += [f"- **{_line(link.label)}:** {_line(link.url)}" for link in contact.links]
    _section(out, "Contact & links", lines)


def _target_roles(profile: Profile, out: list[str]) -> None:
    if profile.target_roles:
        _section(out, "Target roles", [f"- {_line(role)}" for role in profile.target_roles])


def _technologies(profile: Profile, out: list[str]) -> None:
    if not profile.technologies:
        return
    lines: list[str] = []
    for group in profile.technologies:
        lines += [f"### {_line(group.group)}", ""]
        for item in group.items:
            detail = ", ".join(
                part
                for part in (
                    f"aka {_joined(item.aliases, '/')}" if item.aliases else "",
                    _line(item.level),
                    f"{item.years:g} yr{'' if item.years == 1 else 's'}" if item.years else "",
                    f"at {_joined(item.used_at)}" if item.used_at else "",
                )
                if part
            )
            lines.append(f"- **{_line(item.name)}**" + (f" — {detail}" if detail else ""))
        lines.append("")
    _section(out, "Technologies", lines[:-1])


def _experience(profile: Profile, out: list[str]) -> None:
    lines: list[str] = []
    for tenure in profile.experience:
        lines += _tenure_lines(tenure)
    _section(out, "Work experience", lines[:-1] if lines else lines)


def _tenure_lines(tenure: Tenure) -> list[str]:
    header = _line(tenure.company)
    if tenure.location:
        header += f" — {_line(tenure.location)}"
    lines = [f"### {header}", ""]
    if tenure.industry:
        lines += [f"*Industry:* {_line(tenure.industry)}", ""]
    if tenure.summary:
        lines += [_block(tenure.summary), ""]
    for role in tenure.roles:
        lines += _role_lines(role)
    return lines


def _role_lines(role: Role) -> list[str]:
    lines = [f"#### {_line(role.title)}", "", f"*{format_period(role.start, role.end)}*", ""]
    if role.scope:
        lines += [f"**Scope:** {_line(role.scope)}", ""]
    if role.stack:
        lines += [f"**Stack:** {_joined(role.stack)}", ""]
    for highlight in role.highlights:
        prefix = f"**{_line(highlight.label)}:** " if highlight.label else ""
        suffix = f" *(tags: {_joined(highlight.tags)})*" if highlight.tags else ""
        lines.append(f"- {prefix}{_line(highlight.text)}{suffix}")
    if lines[-1]:
        lines.append("")
    return lines


def _education(profile: Profile, out: list[str]) -> None:
    if not profile.education:
        return
    lines: list[str] = []
    for entry in profile.education:
        lines.append(f"### {_line(entry.credential)} — {_line(entry.institution)}")
        details = [
            part
            for part in (
                _month_name(entry.completed) if entry.completed else "",
                _line(entry.location),
                _line(entry.notes),
            )
            if part
        ]
        lines += ["", " · ".join(details), ""] if details else [""]
    _section(out, "Education", lines[:-1])


def _credentials(profile: Profile, out: list[str]) -> None:
    for title, entries in (
        ("Certifications & licenses", profile.certifications),
        ("Awards, publications & talks", profile.awards),
    ):
        if not entries:
            continue
        lines = []
        for entry in entries:
            detail = " — ".join(
                _line(part) for part in (entry.issuer, entry.year, entry.notes) if part
            )
            lines.append(f"- {_line(entry.name)}" + (f" — {_line(detail)}" if detail else ""))
        _section(out, title, lines)


def _projects(profile: Profile, out: list[str]) -> None:
    if not profile.projects:
        return
    lines: list[str] = []
    for project in profile.projects:
        lines += [f"### {_line(project.name)}", "", _block(project.description), ""]
        if project.stack:
            lines += [f"**Stack:** {_joined(project.stack)}", ""]
        if project.outcome:
            lines += [f"**Outcome:** {_line(project.outcome)}", ""]
    _section(out, "Projects", lines[:-1])


def _notes(profile: Profile, out: list[str]) -> None:
    if profile.notes:
        _section(
            out,
            "Notes — confirm before using on a resume",
            [f"- {_line(note)}" for note in profile.notes],
        )
