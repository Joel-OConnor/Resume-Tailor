"""Low-level ``python-docx`` helpers shared by both layouts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

if TYPE_CHECKING:
    from docx.table import _Cell
    from docx.text.paragraph import Paragraph as DocxParagraph

    from resume_tailor.documents.blocks import Span

__all__ = [
    "add_spans",
    "set_bottom_border",
    "set_cell_border",
    "set_indent",
    "set_line_spacing",
]


def add_spans(  # noqa: PLR0913 - every argument is one independent text attribute
    paragraph: DocxParagraph,
    spans: tuple[Span, ...],
    *,
    font: str,
    size: float,
    bold: bool = False,
    italic: bool = False,
    color: str | None = None,
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
        if color is not None:
            run.font.color.rgb = RGBColor.from_string(color)


def set_bottom_border(paragraph: DocxParagraph, *, color: str = "999999", size: int = 6) -> None:
    """Draw a thin rule under a heading.

    A paragraph border, not a table — parsers read the text either way.
    """
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)  # noqa: SLF001


def set_cell_border(cell: _Cell, edge: str, *, color: str = "000000", size: int = 8) -> None:
    """Draw a single border edge (``left``/``right``/``top``/``bottom``) on a table cell."""
    properties = cell._tc.get_or_add_tcPr()  # noqa: SLF001
    borders = properties.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        properties.append(borders)
    element = OxmlElement(f"w:{edge}")
    element.set(qn("w:val"), "single")
    element.set(qn("w:sz"), str(size))
    element.set(qn("w:space"), "0")
    element.set(qn("w:color"), color)
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


def set_line_spacing(paragraph: DocxParagraph, multiple: float) -> None:
    """Set line spacing as a multiple of single spacing (1.15, 1.5, …)."""
    paragraph.paragraph_format.line_spacing = multiple
