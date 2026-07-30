"""Turn the constrained resume/cover-letter Markdown into a :class:`Document`.

The grammar is intentionally small, and the whole reason it is small is the ATS: every construct
here maps to something a resume parser reliably understands. See ``templates/resume.md`` for the
contract as the user sees it.
"""

from __future__ import annotations

import re

from resume_tailor.documents.blocks import (
    Block,
    Bullet,
    Document,
    Entry,
    HeaderLine,
    Meta,
    Name,
    Paragraph,
    Section,
    SkillLine,
)
from resume_tailor.documents.inline import parse_spans
from resume_tailor.errors import DocumentError

__all__ = ["parse"]

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_NAME = re.compile(r"^#\s+(?P<title>\S.*)$")
_SECTION = re.compile(r"^##\s+(?P<title>\S.*)$")
_ENTRY = re.compile(r"^###\s+(?P<title>\S.*)$")
_BULLET = re.compile(r"^[-*]\s+(?P<text>.*)$")
_SKILL = re.compile(r"^\*\*(?P<label>[^*]+?):\*\*\s*(?P<items>.*)$")
_RULE = re.compile(r"^(?:-{3,}|_{3,}|\*{3,})$")


def parse(markdown: str) -> Document:
    """Parse ``markdown`` into a :class:`Document`.

    Raises:
        DocumentError: if the source has no ``# Name`` line, which every renderer relies on.
    """
    lines = _COMMENT.sub("", markdown).splitlines()
    blocks: list[Block] = []

    index, name = _find_name(lines)
    blocks.append(Name(parse_spans(name)))
    index += 1

    # Header lines: everything up to the first blank line or section heading.
    while index < len(lines) and (text := lines[index].strip()) and not _SECTION.match(text):
        blocks.append(HeaderLine(parse_spans(text)))
        index += 1

    _parse_body(lines[index:], blocks)
    return Document(tuple(blocks))


def _find_name(lines: list[str]) -> tuple[int, str]:
    """Return the index of the ``# Name`` line and the name text on it."""
    for index, line in enumerate(lines):
        if match := _NAME.match(line.strip()):
            return index, match["title"].strip()
    msg = "no '# Name' line found — start the file with '# Full Name'"
    raise DocumentError(msg)


def _parse_body(lines: list[str], blocks: list[Block]) -> None:  # noqa: C901 - line-kind dispatch
    """Append every block after the header region to ``blocks``."""
    pending: list[str] = []
    # A plain line directly beneath a '### Entry' is that entry's dates/location line.
    expect_meta = False

    def flush() -> None:
        if pending:
            blocks.append(Paragraph(parse_spans(" ".join(pending))))
            pending.clear()

    for raw in lines:
        line = raw.strip()

        if not line or _RULE.match(line):
            flush()
            expect_meta = False
        elif match := _SECTION.match(line):
            flush()
            blocks.append(Section(match["title"].strip()))
            expect_meta = False
        elif match := _ENTRY.match(line):
            flush()
            blocks.append(Entry(parse_spans(match["title"].strip())))
            expect_meta = True
        elif match := _BULLET.match(line):
            flush()
            blocks.append(Bullet(parse_spans(match["text"].strip())))
            expect_meta = False
        elif match := _SKILL.match(line):
            flush()
            blocks.append(SkillLine(match["label"].strip(), parse_spans(match["items"].strip())))
            expect_meta = False
        elif expect_meta:
            blocks.append(Meta(parse_spans(line, italic=True)))
            expect_meta = False
        elif line.endswith("\\"):
            # A trailing backslash is a hard line break: the sign-off "Sincerely,\" then a name
            # has to render on two lines, and prose lines are otherwise joined into one paragraph.
            pending.append(line[:-1].rstrip())
            flush()
        else:
            pending.append(line)

    flush()
