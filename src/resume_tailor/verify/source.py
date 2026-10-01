"""Split generated Markdown into numbered, classified lines.

Verification cannot reuse :mod:`resume_tailor.documents`: that parser throws positions away, and a
violation the writer cannot locate is a violation it cannot fix. So the line grammar of
``templates/resume.md`` is walked again here, keeping the line number and — because the checks
apply to different regions — which section each line landed in.

HTML comments are blanked rather than deleted, so a stripped comment never shifts every line
number below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

__all__ = ["Area", "Entry", "Kind", "Line", "Source", "scan"]

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SKIP = re.compile(r"^$|^(?:-{3,}|_{3,}|\*{3,})$")
_SECTION = re.compile(r"^##\s+(?P<title>\S.*)$")
_ENTRY = re.compile(r"^###\s+(?P<title>\S.*)$")
_BULLET = re.compile(r"^[-*]\s+(?P<text>.*)$")
# The colon inside the bold ("**Languages:** Go") is the format's; outside it ("**Languages**: Go")
# is as common a habit, and the renderer reads both as a skills line, so both are checked as one.
_SKILL = re.compile(r"^\*\*(?P<label>[^*]+?)(?::\*\*|\*\*:)\s*(?P<items>.*)$")
_ORDINAL = re.compile(r"^[0-9]{1,2}[.)]\s+")


class Area(StrEnum):
    """The region of the resume a line belongs to, which decides what is checked on it."""

    HEADER = "header"
    SKILLS = "skills"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    OTHER = "other"


class Kind(StrEnum):
    """What a line is, in the grammar ``templates/resume.md`` defines."""

    HEADING = "heading"
    ENTRY = "entry"
    META = "meta"
    """The plain line directly under an entry: its dates and location."""

    BULLET = "bullet"
    SKILL = "skill"
    PROSE = "prose"


# Section titles are written by a model, so they are matched by keyword rather than by equality:
# "Professional Experience" and "Technical Skills" have to land in the same place as the bare word.
# Certifications, licenses, awards and any other heading a credential list goes under are checked
# exactly as a degree is, against the one pool of credentials, so they share its area. A section
# mixing projects in with them stays unchecked, since a project is not a credential and could
# never match that pool.
_AREAS: tuple[tuple[str, Area], ...] = (
    ("skill", Area.SKILLS),
    ("experience", Area.EXPERIENCE),
    ("employment", Area.EXPERIENCE),
    ("education", Area.EDUCATION),
    ("project", Area.OTHER),
    ("certif", Area.EDUCATION),
    ("licen", Area.EDUCATION),
    ("award", Area.EDUCATION),
    ("honor", Area.EDUCATION),
    ("honour", Area.EDUCATION),
    ("credential", Area.EDUCATION),
    ("accredit", Area.EDUCATION),
    ("professional development", Area.EDUCATION),
)


@dataclass(frozen=True, slots=True)
class Line:
    """One non-blank line of the document, with where and what it is."""

    number: int
    text: str
    area: Area
    kind: Kind
    body: str = ""
    """The content without its marker: an entry title, a bullet's text, a skill line's items."""

    label: str = ""
    """A skill line's bold label, without its colon; empty on every other kind of line."""


@dataclass(frozen=True, slots=True)
class Entry:
    """A ``### `` heading and the dates line beneath it, checked together."""

    area: Area
    title: str
    line: int
    meta: str = ""
    meta_line: int = 0


@dataclass(frozen=True, slots=True)
class Source:
    """A scanned document."""

    lines: tuple[Line, ...] = ()
    entries: tuple[Entry, ...] = ()


def scan(markdown: str) -> Source:
    """Split ``markdown`` into classified lines and the entries they build."""
    lines: list[Line] = []
    entries: list[Entry] = []
    area = Area.HEADER
    expect_meta = False

    for number, raw in enumerate(_uncomment(markdown).splitlines(), start=1):
        text = raw.strip()
        if _SKIP.match(text):
            expect_meta = False
        elif match := _SECTION.match(text):
            area = _area(match["title"])
            lines.append(Line(number, text, area, Kind.HEADING))
            expect_meta = False
        elif match := _ENTRY.match(text):
            title = match["title"].strip()
            entries.append(Entry(area=area, title=title, line=number))
            lines.append(Line(number, text, area, Kind.ENTRY, title))
            expect_meta = True
        elif match := _BULLET.match(text):
            lines.append(Line(number, text, area, Kind.BULLET, match["text"].strip()))
            expect_meta = False
        elif match := _SKILL.match(text):
            body, label = match["items"].strip(), match["label"].strip()
            lines.append(Line(number, text, area, Kind.SKILL, body, label))
            expect_meta = False
        elif expect_meta:
            entries[-1] = replace(entries[-1], meta=text, meta_line=number)
            lines.append(Line(number, text, area, Kind.META, text))
            expect_meta = False
        else:
            lines.append(Line(number, _blank_ordinal(text), area, Kind.PROSE, text))

    return Source(tuple(lines), tuple(entries))


def _uncomment(markdown: str) -> str:
    """Blank out HTML comments, preserving the line count so numbers stay honest."""
    return _COMMENT.sub(lambda match: "\n" * match.group().count("\n"), markdown)


def _area(title: str) -> Area:
    folded = title.casefold()
    for needle, area in _AREAS:
        if needle in folded:
            return area
    return Area.OTHER


def _blank_ordinal(text: str) -> str:
    """Blank an ordered-list marker so its number is never read as a claimed figure."""
    match = _ORDINAL.match(text)
    return " " * match.end() + text[match.end() :] if match else text
