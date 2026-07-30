"""The typed block model every renderer consumes.

A parsed document is a flat, ordered tuple of blocks. Renderers walk it top to bottom, so the
model stays deliberately shallow: the only structure layered on top is :meth:`Document.groups`,
which slices the same blocks into sections for the two-column polished layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
]


@dataclass(frozen=True, slots=True)
class Span:
    """A run of text with inline emphasis applied."""

    text: str
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True, slots=True)
class Name:
    """The candidate's name — the ``# Name`` line that opens every document."""

    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class HeaderLine:
    """A line between the name and the first section: a target title or the contact line."""

    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class Section:
    """A ``## Heading``: Summary, Skills, Experience, Education, and so on."""

    title: str


@dataclass(frozen=True, slots=True)
class Entry:
    """A ``### Heading`` — one role, degree, project, or certification."""

    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class Meta:
    """The dates/location line that immediately follows an :class:`Entry`."""

    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class SkillLine:
    """A ``**Category:** item, item`` line inside a skills section."""

    label: str
    items: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class Bullet:
    """A ``- `` list item."""

    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class Paragraph:
    """Body prose — the summary, or a cover-letter paragraph."""

    spans: tuple[Span, ...]


GroupBlock = Name | HeaderLine | Entry | Meta | SkillLine | Bullet | Paragraph
"""Every block that can appear *inside* a section — that is, everything but the heading."""

Block = Section | GroupBlock
"""Every block kind a parsed document can contain."""


@dataclass(frozen=True, slots=True)
class SectionGroup:
    """One ``## Section`` plus the blocks beneath it.

    The preamble (name and header lines) is returned as a group whose ``title`` is empty.
    """

    title: str
    blocks: tuple[GroupBlock, ...]

    @property
    def key(self) -> str:
        """The title normalised for case-insensitive matching (e.g. sidebar selection)."""
        return self.title.strip().casefold()


@dataclass(frozen=True, slots=True)
class Document:
    """A fully parsed resume or cover letter."""

    blocks: tuple[Block, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """The plain-text name, or an empty string if the document has no name block."""
        for block in self.blocks:
            if isinstance(block, Name):
                return "".join(span.text for span in block.spans)
        return ""

    def groups(self) -> tuple[SectionGroup, ...]:
        """Slice the flat block list into the preamble plus one group per ``## Section``."""
        groups: list[SectionGroup] = []
        title = ""
        current: list[GroupBlock] = []
        for block in self.blocks:
            if isinstance(block, Section):
                groups.append(SectionGroup(title, tuple(current)))
                title, current = block.title, []
            else:
                current.append(block)
        groups.append(SectionGroup(title, tuple(current)))
        return tuple(groups)
