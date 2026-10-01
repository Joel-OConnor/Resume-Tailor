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
# XML 1.0 forbids the C0 controls, and python-docx passes run text through untouched — a
# paste from Word or a PDF carries \x0b and friends and would crash the export.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NAME = re.compile(r"^#\s+(?P<title>\S.*)$")
_SECTION = re.compile(r"^##\s+(?P<title>\S.*)$")
_ENTRY = re.compile(r"^###\s+(?P<title>\S.*)$")
_BULLET = re.compile(r"^[-*]\s+(?P<text>.*)$")
# The colon inside the bold (``**Languages:** Go``) is the documented form; outside it
# (``**Languages**: Go``) is just as common a habit, and read as prose it ran every skills line
# into one paragraph.
_SKILL = re.compile(r"^\*\*(?P<label>[^*]+?)(?::\*\*|\*\*:)\s*(?P<items>.*)$")
_RULE = re.compile(r"^(?:-{3,}|_{3,}|\*{3,})$")


def parse(markdown: str) -> Document:
    """Parse ``markdown`` into a :class:`Document`.

    Raises:
        DocumentError: if the source has no ``# Name`` line, which every renderer relies on.
    """
    lines = _CONTROL.sub("", _COMMENT.sub("", markdown).expandtabs(4)).splitlines()
    blocks: list[Block] = []

    index, name = _find_name(lines)
    blocks.append(Name(parse_spans(_strip_hard_break(name)[0])))
    index += 1

    # Header lines: everything up to the first blank line or section heading.
    while index < len(lines) and (text := lines[index].strip()) and not _SECTION.match(text):
        blocks.append(HeaderLine(parse_spans(_strip_hard_break(text)[0])))
        index += 1

    _parse_body(lines[index:], blocks)
    return Document(tuple(blocks))


def _find_name(lines: list[str]) -> tuple[int, str]:
    """Return the index of the ``# Name`` line and the name text on it.

    Anything before it is an error rather than something to skip: silently dropping content
    from a document the user is about to submit is the worst outcome available.
    """
    for index, line in enumerate(lines):
        if match := _NAME.match(line.strip()):
            if stray := [text for text in lines[:index] if text.strip()]:
                msg = f"content above the '# Name' line would be dropped: {stray[0].strip()!r}"
                raise DocumentError(msg)
            return index, match["title"].strip()
    msg = "no '# Name' line found: start the file with '# Full Name'"
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
        line, hard_break = _strip_hard_break(raw.strip())

        if hard_break and not line:
            # A line holding only the marker ends the paragraph without acting as a blank line,
            # which would otherwise cancel a pending dates/location line.
            flush()
        elif not line or _RULE.match(line):
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
        else:
            pending.append(line)
            if hard_break:
                flush()

    flush()


def _strip_hard_break(line: str) -> tuple[str, bool]:
    r"""Split a trailing hard-break marker off a line.

    A line ending in an odd number of backslashes ends with an unescaped one: that is the hard
    line break (the cover-letter sign-off needs "Sincerely,\" and the name on separate lines,
    because prose lines are otherwise joined into one paragraph). An even number is an escaped
    literal backslash, which :func:`parse_spans` handles.

    The marker is stripped here rather than in the prose branch alone, so a stray backslash on a
    bullet, meta, or skill line can never survive into the exported document.
    """
    trailing = len(line) - len(line.rstrip("\\"))
    if trailing % 2 == 0:
        return line, False
    return line[:-1].rstrip(), True
