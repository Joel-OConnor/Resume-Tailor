"""Parse the constrained resume/cover-letter Markdown into a typed block model."""

from __future__ import annotations

from resume_tailor.documents.blocks import (
    Block,
    Bullet,
    Document,
    Entry,
    GroupBlock,
    HeaderLine,
    Meta,
    Name,
    Paragraph,
    Section,
    SectionGroup,
    SkillLine,
    Span,
)
from resume_tailor.documents.inline import parse_spans
from resume_tailor.documents.parser import parse

__all__ = [
    "Block",
    "Bullet",
    "Document",
    "Entry",
    "GroupBlock",
    "HeaderLine",
    "Meta",
    "Name",
    "Paragraph",
    "Section",
    "SectionGroup",
    "SkillLine",
    "Span",
    "parse",
    "parse_spans",
]
