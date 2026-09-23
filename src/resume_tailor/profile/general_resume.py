"""Render a profile as a general-purpose resume: the whole career, untailored.

This is the resume to have on hand when there is no posting to tailor to — a LinkedIn upload, a
recruiter's "just send me your resume", a job-board profile. It is deterministic and needs no
model and no API key: every employer, title, date, highlight and technology comes straight from
the profile, in the profile's own order and wording, so nothing here can be invented and there
is nothing to verify. The one judgement applied is the one every resume needs — a technology the
profile records as ``exposure`` or ``working`` is left out of Skills, because a Skills line is
read as a claim of competence.

The output follows ``templates/resume.md``, so it exports in both layouts like any tailored
resume. It is a starting point, not a final word: trim it with :class:`ResumeShape`, or correct
the profile and regenerate. Editing the Markdown by hand works too, until the next regeneration
replaces it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.profile.markdown_view import format_date, format_period

if TYPE_CHECKING:
    from resume_tailor.profile.models import Credential, Highlight, Profile, Role, Tenure

__all__ = ["DEFAULT_SHAPE", "ResumeShape", "render_general_resume"]

_THIN_LEVELS = frozenset({"exposure", "working"})
"""Depths a Skills line must not claim — the same threshold the matcher treats as shallow."""

_PRESENT = "present"
_WHITESPACE = re.compile(r"\s+")
_URL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)
_YEAR_LENGTH = 4


@dataclass(frozen=True, slots=True)
class ResumeShape:
    """How much of the profile the general resume prints. The defaults print all of it."""

    title: str = ""
    """The line under the name. Empty means the first target role, else the headline."""

    max_highlights: int = 0
    """Bullets per role, taken in profile order; 0 means every one."""

    max_skills: int = 0
    """Items per Skills group, taken in profile order; 0 means every one."""

    since: str = ""
    """A year, ``YYYY``. An employer left before it is omitted; empty keeps every employer."""


DEFAULT_SHAPE = ResumeShape()
"""Print everything: the shape used when a caller states no preference."""


def render_general_resume(profile: Profile, shape: ResumeShape = DEFAULT_SHAPE) -> str:
    """Render ``profile`` as resume Markdown in the ``templates/resume.md`` format."""
    out = [f"# {_line(profile.contact.name)}", _title(profile, shape), _contact_line(profile)]
    out += ["", "## Summary", "", _line(profile.summary)]
    _skills(profile, shape, out)
    _experience(profile, shape, out)
    _education(profile, out)
    _credentials("Certifications", profile.certifications, out)
    _credentials("Awards", profile.awards, out)
    _projects(profile, out)
    return "\n".join(out).rstrip() + "\n"


# --- header ---------------------------------------------------------------------------------------
def _title(profile: Profile, shape: ResumeShape) -> str:
    """Return the title line: the target role, or the headline up to its first pipe.

    A pipe is what makes a header line read as contact details, so a LinkedIn-style headline
    ("Lead Engineer @ Acme | Go, Kubernetes") is cut at the first one, and a pipe inside an
    explicit title is replaced rather than printed.
    """
    if shape.title:
        chosen = shape.title
    elif profile.target_roles:
        chosen = profile.target_roles[0]
    else:
        headline = profile.contact.headline
        chosen = headline.partition("|")[0].strip() or headline
    return _line(chosen.replace("|", "/"))


def _contact_line(profile: Profile) -> str:
    """Join every contact detail the profile has onto the one pipe-separated line."""
    contact = profile.contact
    parts = (
        contact.location,
        contact.email,
        contact.phone,
        *(_short_url(link.url) for link in contact.links),
        contact.work_authorization,
    )
    return " | ".join(_line(part) for part in parts if part)


def _short_url(url: str) -> str:
    """Print ``https://www.linkedin.com/in/x/`` as ``linkedin.com/in/x``, the way resumes do."""
    return _URL_PREFIX.sub("", url).rstrip("/") or url


# --- sections -------------------------------------------------------------------------------------
def _skills(profile: Profile, shape: ResumeShape, out: list[str]) -> None:
    lines: list[str] = []
    for group in profile.technologies:
        names = [_line(item.name) for item in group.items if item.level not in _THIN_LEVELS]
        if shape.max_skills:
            names = names[: shape.max_skills]
        if names:
            lines.append(f"**{_line(group.group)}:** {', '.join(names)}")
    if lines:
        out += ["", "## Skills", "", *lines]


def _experience(profile: Profile, shape: ResumeShape, out: list[str]) -> None:
    tenures = [tenure for tenure in profile.experience if _kept(tenure, shape.since)]
    if not tenures:
        return
    out += ["", "## Experience"]
    for tenure in tenures:
        for role in tenure.roles:
            out += _role_lines(tenure, role, shape)


def _kept(tenure: Tenure, since: str) -> bool:
    """Report whether an employer is recent enough to print under ``since``.

    Dates are ``YYYY`` or ``YYYY-MM``, so the year is the first four characters and compares as
    text; a role still held always counts.
    """
    return not since or any(
        role.end == _PRESENT or role.end[:_YEAR_LENGTH] >= since for role in tenure.roles
    )


def _role_lines(tenure: Tenure, role: Role, shape: ResumeShape) -> list[str]:
    meta = format_period(role.start, role.end)
    if tenure.location:
        meta += f" | {_line(tenure.location)}"
    lines = ["", f"### {_line(tenure.company)} – {_line(role.title)}", meta]
    highlights = role.highlights
    if shape.max_highlights:
        highlights = highlights[: shape.max_highlights]
    lines += [_bullet(highlight) for highlight in highlights]
    if role.stack:
        lines.append(_stack_line(role.stack))
    return lines


def _bullet(highlight: Highlight) -> str:
    text = _line(highlight.text)
    if highlight.label:
        return f"- **{_line(highlight.label)}:** {text}"
    return f"- {text}"


def _stack_line(stack: tuple[str, ...]) -> str:
    return f"*Tech Stack – {', '.join(_line(item) for item in stack)}*"


def _education(profile: Profile, out: list[str]) -> None:
    if not profile.education:
        return
    out += ["", "## Education"]
    for entry in profile.education:
        out += ["", f"### {_line(entry.credential)} – {_line(entry.institution)}"]
        _meta((format_date(entry.completed), entry.location, entry.notes), out)


def _credentials(title: str, entries: tuple[Credential, ...], out: list[str]) -> None:
    """Print certifications or awards, each as an entry with its issuer, year and notes."""
    if not entries:
        return
    out += ["", f"## {title}"]
    for entry in entries:
        out += ["", f"### {_line(entry.name)}"]
        _meta((entry.issuer, entry.year, entry.notes), out)


def _projects(profile: Profile, out: list[str]) -> None:
    if not profile.projects:
        return
    out += ["", "## Projects"]
    for project in profile.projects:
        out += ["", f"### {_line(project.name)}", f"- {_line(project.description)}"]
        if project.outcome:
            out.append(f"- {_line(project.outcome)}")
        if project.stack:
            out.append(_stack_line(project.stack))


def _meta(parts: tuple[str, ...], out: list[str]) -> None:
    """Append the dates/location line under an entry, or nothing when there is nothing to say."""
    if meta := " | ".join(_line(part) for part in parts if part):
        out.append(meta)


def _line(text: str) -> str:
    """Flatten a folded YAML value onto one line, since every construct here is one line."""
    return _WHITESPACE.sub(" ", text).strip()
