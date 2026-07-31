"""Pin the typography and geometry of both layouts to literal values.

Every other render test compares output against the module constant that produced it, so it moves
in lockstep with any change to that constant and can never catch one. These assertions spell the
numbers out. Changing a constant is then a deliberate two-place edit, and the diff says what the
document will look like afterwards.

The polished figures come from the user's own "2026 Polished Resume.docx"; the ATS figures are the
parser-safe layout documented in ``reference/ATS-PLAYBOOK.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from docx import Document as read_docx
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Inches, Pt

from resume_tailor.render import ats, polished
from resume_tailor.render.html_common import FONT_STACK

if TYPE_CHECKING:
    from pathlib import Path

    from resume_tailor.documents.blocks import Document

_TWIP = 635  # EMU


# --- the numbers themselves -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("FONT", "Calibri"),
        ("BODY_PT", 10.0),
        ("PROSE_PT", 10.5),
        ("NAME_PT", 20.0),
        ("SECTION_PT", 12.0),
        ("ENTRY_PT", 11.0),
        ("LINE_PT", 13.5),
        ("MUTED", "444444"),
        ("BULLET_INDENT_IN", 0.25),
        ("BULLET_HANGING_IN", 0.15),
    ],
)
def test_ats_constants(name: str, expected: object) -> None:
    assert getattr(ats, name) == expected


def test_ats_gaps() -> None:
    assert ats.GAP_PT == {
        "name": 0.0,
        "header": 1.0,
        "section": 12.0,
        "entry": 8.0,
        "meta": 1.0,
        "skill": 1.0,
        "bullet": 1.0,
        "para": 5.0,
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("FONT", "Roboto"),
        ("FONT_LIGHT", "Roboto ExtraLight"),
        ("FONT_SEMIBOLD", "Roboto SemiBold"),
        ("BODY_PT", 10.0),
        ("CONTACT_PT", 9.0),
        ("SECTION_PT", 15.0),
        ("SUBTITLE_PT", 12.0),
        ("NAME_PT", 35.0),
        ("LINE_PT", 11.5),
        ("NAME_LINE_PT", 36.75),
        ("PAGE_MARGIN_IN", 0.45),
        ("SIDEBAR_WIDTH_IN", 2.42),
        ("MAIN_WIDTH_IN", 6.08),
        ("SIDEBAR_INDENT", (0.45, 0.25)),
        ("MAIN_INDENT", (0.30, 0.50)),
        ("BULLET_HANGING_IN", 0.18),
    ],
)
def test_polished_constants(name: str, expected: object) -> None:
    assert getattr(polished, name) == expected


def test_polished_gaps() -> None:
    assert polished.GAP_PT == {
        "name": 0.0,
        "contact": 2.0,
        "subtitle": 2.0,
        "section": 12.0,
        "entry": 6.0,
        "meta": 0.0,
        "lead": 3.0,
        "bullet": 2.0,
        "para": 4.0,
        "skill-group": 6.0,
        "skill-item": 0.0,
        "skill-inline": 2.0,
    }


def test_the_columns_fill_the_page() -> None:
    """Full bleed is the whole point of the design; the rule sits where the split falls."""
    assert polished.SIDEBAR_WIDTH_IN + polished.MAIN_WIDTH_IN == 8.5


def test_the_font_stack_leads_with_the_design_face() -> None:
    assert FONT_STACK.startswith("Roboto,")
    assert "Helvetica" in FONT_STACK
    assert FONT_STACK.endswith("sans-serif")


# --- the numbers as they reach the .docx ----------------------------------------------------------
def test_ats_page_geometry(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume.docx"
    ats.render_docx(resume, out)
    section = read_docx(str(out)).sections[0]
    assert section.top_margin == Pt(0.6 * 72)
    assert section.bottom_margin == Pt(0.6 * 72)
    assert section.left_margin == Pt(0.7 * 72)
    assert section.right_margin == Pt(0.7 * 72)


def test_ats_typography_reaches_the_docx(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume.docx"
    ats.render_docx(resume, out)
    document = read_docx(str(out))
    sizes = {
        p.text.strip(): p.runs[0].font.size.pt
        for p in document.paragraphs
        if p.runs and p.runs[0].font.size is not None
    }
    assert sizes["Ada Lovelace"] == 20
    assert sizes["SUMMARY"] == 12
    assert sizes["Analytical Engine Programme — Principal Engineer"] == 11

    name = next(p for p in document.paragraphs if p.text.strip() == "Ada Lovelace")
    assert name.paragraph_format.line_spacing == Pt(13.5)
    section = next(p for p in document.paragraphs if p.text.strip() == "SUMMARY")
    assert section.paragraph_format.space_before == Pt(12)
    assert section.paragraph_format.space_after == Pt(0)


def test_polished_page_geometry(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    document = read_docx(str(out))
    section = document.sections[0]
    assert section.top_margin == Inches(0.45)
    assert section.left_margin == Inches(0)
    columns = document.tables[0].columns
    assert abs(columns[0].width - Inches(2.42)) <= _TWIP
    assert abs(columns[1].width - Inches(6.08)) <= _TWIP


def test_polished_typography_reaches_the_docx(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    table = read_docx(str(out)).tables[0]
    rail, main = table.rows[0].cells

    name = main.paragraphs[0]
    assert name.runs[0].font.size.pt == 35
    assert name.runs[0].font.name == "Roboto ExtraLight"
    assert name.paragraph_format.line_spacing == Pt(36.75)

    contact = rail.paragraphs[0]
    assert contact.runs[0].font.size.pt == 9
    assert contact.runs[0].font.name == "Roboto SemiBold"

    heading = next(p for p in main.paragraphs if p.text.strip() == "Summary")
    assert heading.runs[0].font.size.pt == 15
    assert heading.runs[0].bold is False, "the design's section headings are regular weight"
    assert heading.paragraph_format.space_before == Pt(12)


def test_polished_role_headings_are_semibold_not_bold(resume: Document, tmp_path: Path) -> None:
    """SemiBold family plus a bold flag resolves to the bold companion — heavier than designed."""
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    table = read_docx(str(out)).tables[0]
    entries = [
        run
        for p in table.rows[0].cells[1].paragraphs
        for run in p.runs
        if "Analytical Engine Programme" in run.text
    ]
    assert entries
    assert all(run.font.name == "Roboto SemiBold" for run in entries)
    assert all(run.bold is False for run in entries)


def test_polished_zeroes_the_table_cell_margins(resume: Document, tmp_path: Path) -> None:
    """Word's default 0.075in cell padding would narrow the .docx columns against the PDF."""
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    xml = read_docx(str(out)).tables[0]._tbl.xml
    assert "w:tblCellMar" in xml
    assert xml.count('w:w="0" w:type="dxa"') >= 4


def test_the_divider_is_one_point(resume: Document, tmp_path: Path) -> None:
    """w:sz is in eighths of a point, so 8 is 1pt — and the CSS must say the same."""
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    rail = read_docx(str(out)).tables[0].rows[0].cells[0]
    assert 'w:sz="8"' in rail._tc.xml
    assert "border-right: 1pt solid #000" in polished.render_html(resume)


def test_the_ats_heading_rule_is_three_quarter_point(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume.docx"
    ats.render_docx(resume, out)
    heading = next(p for p in read_docx(str(out)).paragraphs if p.text.strip() == "SUMMARY")
    assert 'w:sz="6"' in heading._p.xml
    assert "border-bottom: 0.75pt solid #999" in ats.render_html(resume)


def test_line_spacing_is_at_least_never_exact(resume: Document, tmp_path: Path) -> None:
    """EXACTLY clips any glyph taller than the line box — Word would silently truncate text."""
    out = tmp_path / "resume.docx"
    ats.render_docx(resume, out)
    rules = {p.paragraph_format.line_spacing_rule for p in read_docx(str(out)).paragraphs}
    assert rules == {WD_LINE_SPACING.AT_LEAST}
