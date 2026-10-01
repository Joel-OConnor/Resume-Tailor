"""Low-level ``python-docx`` helpers shared by both layouts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from resume_tailor.documents.blocks import title_of

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph as DocxParagraph

    from resume_tailor.documents.blocks import Document, Span

# The ``w:pPr`` child order from ECMA-376. python-docx builds its accessors from the same list
# and then deletes it, so it is restated here: an element inserted out of sequence yields a
# document Word reports as corrupt.
_PPR_SEQUENCE = (
    "w:pStyle",
    "w:keepNext",
    "w:keepLines",
    "w:pageBreakBefore",
    "w:framePr",
    "w:widowControl",
    "w:numPr",
    "w:suppressLineNumbers",
    "w:pBdr",
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)


def _successors(tag: str) -> tuple[str, ...]:
    """Every ``w:pPr`` child that must follow ``tag``."""
    return _PPR_SEQUENCE[_PPR_SEQUENCE.index(tag) + 1 :]


__all__ = [
    "add_spans",
    "set_cell_border",
    "set_cell_margins",
    "set_indent",
    "set_properties",
    "set_spacing",
]


def set_properties(docx: DocxDocument, document: Document) -> None:
    """Replace the template's file properties with this document's own.

    python-docx starts every file from a blank template whose properties say it was written by
    "python-docx" in December 2013 and has no title. Word's File > Info, Finder's Get Info and
    anything that indexes the file read those, so each export names the candidate as its author,
    says what it is ("Ada Lovelace Resume", "Ada Lovelace Cover Letter"), and is dated now.
    """
    now = datetime.now(UTC).replace(microsecond=0)  # the file format records whole seconds
    properties = docx.core_properties
    properties.title = title_of(document)
    properties.author = document.name
    properties.last_modified_by = document.name
    properties.comments = ""
    properties.created = now
    properties.modified = now


def add_spans(  # noqa: PLR0913 - every argument is one independent text attribute
    paragraph: DocxParagraph,
    spans: tuple[Span, ...],
    *,
    font: str,
    size: float,
    bold: bool = False,
    italic: bool = False,
) -> None:
    """Append ``spans`` to ``paragraph``, layering each span's emphasis over the defaults."""
    for span in spans:
        if not span.text:
            continue
        run = paragraph.add_run(span.text)
        run.bold = bold or span.bold
        run.italic = italic or span.italic
        run.font.name = font
        run.font.size = Pt(size)


def set_cell_border(cell: _Cell, edge: str) -> None:
    """Draw a thin black border edge (``left``/``right``/``top``/``bottom``) on a table cell."""
    properties = cell._tc.get_or_add_tcPr()  # noqa: SLF001
    borders = properties.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        properties.append(borders)
    element = OxmlElement(f"w:{edge}")
    element.set(qn("w:val"), "single")
    element.set(qn("w:sz"), "8")  # eighths of a point: a 1pt rule
    element.set(qn("w:space"), "0")
    element.set(qn("w:color"), "000000")
    borders.append(element)


def set_indent(
    paragraph: DocxParagraph, *, left: float, right: float, hanging: float = 0.0
) -> None:
    """Set left/right indents (in inches), optionally with a hanging first line."""
    fmt = paragraph.paragraph_format
    fmt.left_indent = Pt(left * 72)
    fmt.right_indent = Pt(right * 72)
    if hanging:
        fmt.first_line_indent = Pt(-hanging * 72)


def set_spacing(paragraph: DocxParagraph, *, before: float, line: float) -> None:
    """Set the gap above a paragraph and its line height, both in absolute points.

    Absolute on purpose. CSS ``line-height: 1.15`` means 1.15x the *font size*, while Word's
    "multiple" means 1.15x the font's *natural line box* — so the same number renders ~15%
    looser in Word than in the PDF printed from the HTML. Points mean the same thing to both.

    The gap likewise lives only in ``space_before``, with ``space_after`` pinned to zero: Word
    sums adjacent spacing while CSS collapses it, so splitting the gap across the two properties
    makes the .docx and the PDF disagree wherever two blocks meet.
    """
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
    fmt.line_spacing = Pt(line)
    _clear_contextual_spacing(paragraph)


def _clear_contextual_spacing(paragraph: DocxParagraph) -> None:
    """Stop a list style from suppressing the gap between consecutive items.

    ``List Bullet`` carries ``<w:contextualSpacing/>``, which zeroes spacing between same-style
    paragraphs. The browser has no such rule, so leaving it on makes .docx bullets tighter than
    the PDF's.
    """
    properties = paragraph._p.get_or_add_pPr()  # noqa: SLF001
    element = properties.find(qn("w:contextualSpacing"))
    if element is None:
        element = OxmlElement("w:contextualSpacing")
        properties.insert_element_before(element, *_successors("w:contextualSpacing"))
    element.set(qn("w:val"), "0")


def set_cell_margins(table: Table, inches: float) -> None:
    """Set every cell's inner margin on a table.

    Word's default table style adds 0.075in of padding on the left and right of every cell. The
    HTML has no such padding, so leaving it makes the .docx columns narrower than the PDF's and
    every paragraph in them wrap somewhere else.
    """
    margins = OxmlElement("w:tblCellMar")
    for edge in ("top", "left", "bottom", "right"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:w"), str(int(inches * 1440)))
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    table._tbl.tblPr.append(margins)  # noqa: SLF001
