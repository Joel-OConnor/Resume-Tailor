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
    "is_contact_line",
    "is_note",
    "is_sectioned",
    "title_of",
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
    """A ``**Category:** item, item`` line (or ``**Category**: item``) in a skills section."""

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


def is_contact_line(spans: tuple[Span, ...]) -> bool:
    """Report whether a header line is the contact line rather than a target-title subtitle.

    Any pipe counts, not just the documented ``" | "``, so a contact line written without spaces
    is still recognised. The cost is that a target title containing a pipe is misread as contact
    details — write the title without one.
    """
    return "|" in "".join(span.text for span in spans)


def is_note(spans: tuple[Span, ...]) -> bool:
    """Report whether a paragraph is set entirely in italics: a closing ``*Tech Stack*`` note."""
    written = [span for span in spans if span.text.strip()]
    return bool(written) and all(span.italic for span in written)


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


def is_sectioned(document: Document) -> bool:
    """Report whether this is a resume (it has ``## `` sections) rather than a cover letter."""
    return any(isinstance(block, Section) for block in document.blocks)


def title_of(document: Document) -> str:
    """Return what the file is, for its title: "Ada Lovelace Resume", "Ada Lovelace Cover Letter".

    The .docx properties and the PDF share it, so both files name themselves the same way.
    """
    kind = "Resume" if is_sectioned(document) else "Cover Letter"
    return f"{document.name} {kind}".strip()
