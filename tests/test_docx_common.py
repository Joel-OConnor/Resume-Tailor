"""The low-level ``python-docx`` helpers, exercised directly."""

from __future__ import annotations

from docx import Document as new_docx
from docx.oxml.ns import qn
from docx.shared import Pt

from resume_tailor.documents.blocks import Span
from resume_tailor.render.docx_common import (
    add_spans,
    set_bottom_border,
    set_cell_border,
    set_indent,
    set_line_spacing,
)


def test_empty_spans_add_no_runs() -> None:
    paragraph = new_docx().add_paragraph()
    add_spans(paragraph, (Span(""), Span("kept"), Span("")), font="Calibri", size=10)
    assert [run.text for run in paragraph.runs] == ["kept"]


def test_defaults_layer_over_span_emphasis() -> None:
    paragraph = new_docx().add_paragraph()
    add_spans(
        paragraph,
        (Span("a"), Span("b", bold=True)),
        font="Calibri",
        size=10,
        italic=True,
        color="444444",
    )
    assert [(run.bold, run.italic) for run in paragraph.runs] == [(False, True), (True, True)]
    assert str(paragraph.runs[0].font.color.rgb) == "444444"


def test_colour_is_left_alone_when_unset() -> None:
    paragraph = new_docx().add_paragraph()
    add_spans(paragraph, (Span("a"),), font="Calibri", size=10)
    assert paragraph.runs[0].font.color.rgb is None


def test_a_bottom_border_is_a_paragraph_border() -> None:
    paragraph = new_docx().add_paragraph("Heading")
    set_bottom_border(paragraph)
    assert "w:pBdr" in paragraph._p.xml
    assert 'w:color="999999"' in paragraph._p.xml


def test_cell_borders_accumulate_rather_than_replace() -> None:
    cell = new_docx().add_table(rows=1, cols=1).rows[0].cells[0]
    set_cell_border(cell, "right")
    set_cell_border(cell, "top", color="FF0000")
    borders = cell._tc.find(qn("w:tcPr")).findall(qn("w:tcBorders"))
    assert len(borders) == 1
    assert {child.tag.split("}")[1] for child in borders[0]} == {"right", "top"}


def test_indent_without_a_hanging_first_line() -> None:
    paragraph = new_docx().add_paragraph()
    set_indent(paragraph, left=0.5, right=0.25)
    assert paragraph.paragraph_format.left_indent == Pt(36)
    assert paragraph.paragraph_format.right_indent == Pt(18)
    assert paragraph.paragraph_format.first_line_indent is None


def test_indent_with_a_hanging_first_line() -> None:
    paragraph = new_docx().add_paragraph()
    set_indent(paragraph, left=0.5, right=0.25, hanging=0.25)
    assert paragraph.paragraph_format.first_line_indent == Pt(-18)


def test_line_spacing_is_set_as_a_multiple() -> None:
    paragraph = new_docx().add_paragraph()
    set_line_spacing(paragraph, 1.15)
    assert paragraph.paragraph_format.line_spacing == 1.15
