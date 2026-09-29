"""Pin the typography and geometry of both layouts to literal values.

Every other render test compares output against the module constant that produced it, so it moves
in lockstep with any change to that constant and can never catch one. These assertions spell the
numbers out. Changing a constant is then a deliberate two-place edit, and the diff says what the
document will look like afterwards.

Both layouts take their proportions from the user's own "2026 Polished Resume" PDF, set in Arial
at the sizes resume guidance for people and parsers alike recommends (body 10-12pt, headings
14-16pt): the single-column layout carries that typography in the parser-safe shape
``reference/ATS-PLAYBOOK.md`` describes, and the polished layout carries its two-column geometry
as well.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from docx import Document as read_docx
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Inches, Pt

from resume_tailor.render import ats, polished
from resume_tailor.render.html_common import FONT_STACK

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from resume_tailor.documents.blocks import Document

_TWIP = 635  # EMU

# Arial's natural line box as a share of its size, about 1.15: (ascender + descender + line gap)
# over units per em, from its hhea table. Word's "single" line and the browser's "normal" are this.
_ARIAL_LINE = (1854 + 434 + 67) / 2048


# --- the numbers themselves -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("FONT", "Arial"),
        ("BODY_PT", 10.0),
        ("PROSE_PT", 11.0),
        ("CONTACT_PT", 10.0),
        ("SUBTITLE_PT", 12.0),
        ("SECTION_PT", 15.0),
        ("NAME_PT", 28.0),
        ("LINE_PT", 12.0),
        ("PROSE_LINE_PT", 13.5),
        ("SUBTITLE_LINE_PT", 14.25),
        ("SECTION_LINE_PT", 18.0),
        ("NAME_LINE_PT", 33.0),
        ("PAGE_MARGIN_IN", (0.6, 0.7)),
        ("BULLET_HANGING_IN", 0.25),
        ("NOTE_INDENT_IN", 0.05),
        ("BULLET_GLYPH", "\u2022"),
    ],
)
def test_ats_constants(name: str, expected: object) -> None:
    assert getattr(ats, name) == expected


def test_ats_gaps() -> None:
    assert ats.GAP_PT == {
        "name": 0.0,
        "subtitle": 2.25,
        "contact": 2.25,
        "section": 12.0,
        "section-after-name": 37.5,
        "section-after-header": 21.0,
        "entry": 5.25,
        "meta": 1.5,
        "skill": 2.25,
        "bullet": 2.25,
        "bullet-first": 6.75,
        "note": 2.25,
        "para": 5.25,
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("FONT", "Arial"),
        ("BODY_PT", 10.0),
        ("PROSE_PT", 11.0),
        ("CONTACT_PT", 10.0),
        ("SECTION_PT", 15.0),
        ("SUBTITLE_PT", 12.0),
        ("NAME_PT", 28.0),
        ("LINE_PT", 12.0),
        ("PROSE_LINE_PT", 13.5),
        ("SUBTITLE_LINE_PT", 14.25),
        ("SECTION_LINE_PT", 18.0),
        ("NAME_LINE_PT", 33.0),
        ("PAGE_MARGIN_IN", 0.2),
        ("SIDEBAR_WIDTH_IN", 2.42),
        ("MAIN_WIDTH_IN", 6.08),
        ("SIDEBAR_INDENT", (0.2, 0.2)),
        ("MAIN_INDENT", (0.2, 0.25)),
        ("BULLET_HANGING_IN", 0.25),
        ("NOTE_INDENT_IN", 0.05),
        ("BULLET_GLYPH", "\u2022"),
    ],
)
def test_polished_constants(name: str, expected: object) -> None:
    assert getattr(polished, name) == expected


def test_polished_gaps() -> None:
    assert polished.GAP_PT == {
        "name": 0.0,
        "contact": 4.5,
        "subtitle": 2.25,
        "section": 9.75,
        "section-rail": 15.75,
        "section-after-name": 37.5,
        "section-after-subtitle": 21.0,
        "entry": 5.25,
        "meta": 1.5,
        "bullet": 2.25,
        "bullet-first": 6.75,
        "note": 2.25,
        "para": 5.25,
        "skill-group": 3.75,
        "skill-item": 1.5,
        "skill-item-first": 3.75,
        "skill-inline": 2.25,
    }


@pytest.mark.parametrize("module", [ats, polished])
def test_the_pdf_fetches_nothing_at_print_time(module: ModuleType) -> None:
    """Arial is a system font on macOS and Windows, so there is no web font to wait for."""
    assert "@import" not in module.CSS
    assert "url(" not in module.CSS


@pytest.mark.parametrize("module", [ats, polished])
def test_the_css_asks_only_for_the_weights_arial_has(module: ModuleType) -> None:
    """Regular and bold, the two a .docx run can say; a 200 or a 600 would have no Word twin."""
    assert set(re.findall(r"font-weight: *(\d+)", module.CSS)) <= {"400", "700"}


_SIZED_LINES = (
    ("BODY_PT", "LINE_PT"),
    ("CONTACT_PT", "LINE_PT"),
    ("PROSE_PT", "PROSE_LINE_PT"),
    ("SUBTITLE_PT", "SUBTITLE_LINE_PT"),
    ("SECTION_PT", "SECTION_LINE_PT"),
    ("NAME_PT", "NAME_LINE_PT"),
)


@pytest.mark.parametrize("module", [ats, polished])
@pytest.mark.parametrize(("size", "line"), _SIZED_LINES)
def test_every_line_box_holds_a_line_of_arial(module: ModuleType, size: str, line: str) -> None:
    """Word's "at least" widens a box smaller than the font's own; the browser does not."""
    assert getattr(module, line) >= getattr(module, size) * _ARIAL_LINE


_LINE_CONSTANTS = (
    "LINE_PT",
    "PROSE_LINE_PT",
    "SUBTITLE_LINE_PT",
    "SECTION_LINE_PT",
    "NAME_LINE_PT",
)


def test_every_vertical_measure_is_a_whole_css_pixel() -> None:
    """The browser snaps to whole pixels (0.75pt); a value that already is one cannot drift."""
    measures = [
        *(getattr(module, name) for module in (ats, polished) for name in _LINE_CONSTANTS),
        *ats.GAP_PT.values(),
        *polished.GAP_PT.values(),
    ]
    assert all((value / 0.75).is_integer() for value in measures)


def test_the_columns_fill_the_page() -> None:
    """Full bleed is the whole point of the design; the rule sits where the split falls."""
    assert polished.SIDEBAR_WIDTH_IN + polished.MAIN_WIDTH_IN == 8.5


def test_the_font_stack_is_arial_then_its_metric_twin() -> None:
    assert FONT_STACK == "Arial, Helvetica, sans-serif"


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
    assert sizes["Ada Lovelace"] == 28
    assert sizes["ada@example.com | (555) 010-0100 | London, UK | github.com/ada"] == 10
    assert sizes["Summary"] == 15
    assert sizes["Analytical Engine Programme — Principal Engineer"] == 10

    name = next(p for p in document.paragraphs if p.text.strip() == "Ada Lovelace")
    assert name.paragraph_format.line_spacing == Pt(33)
    section = next(p for p in document.paragraphs if p.text.strip() == "Summary")
    assert section.paragraph_format.line_spacing == Pt(18)
    # The fixture's Summary follows the contact line.
    assert section.paragraph_format.space_before == Pt(21)
    assert section.paragraph_format.space_after == Pt(0)


def test_polished_page_geometry(resume: Document, tmp_path: Path) -> None:
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    document = read_docx(str(out))
    section = document.sections[0]
    assert section.top_margin == Inches(0.2)
    assert section.bottom_margin == Inches(0.2)
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
    assert name.runs[0].font.size.pt == 28
    assert name.runs[0].font.name == "Arial"
    assert name.runs[0].bold is False, "a large name reads as prominent without the weight"
    assert name.paragraph_format.line_spacing == Pt(33)

    contact = rail.paragraphs[0]
    assert contact.runs[0].font.size.pt == 10
    assert contact.runs[0].font.name == "Arial"
    assert contact.runs[0].bold is False

    heading = next(p for p in main.paragraphs if p.text.strip() == "Summary")
    assert heading.runs[0].font.size.pt == 15
    assert heading.runs[0].bold is False, "the design's section headings are regular weight"
    assert heading.paragraph_format.line_spacing == Pt(18)
    # The fixture has a target-title line under the name, so Summary follows a subtitle.
    assert heading.paragraph_format.space_before == Pt(21)


def test_every_polished_run_is_arial(resume: Document, tmp_path: Path) -> None:
    """One family in every run of both cells, so Word never substitutes a face it lacks."""
    out = tmp_path / "resume-polished.docx"
    polished.render_docx(resume, out)
    cells = read_docx(str(out)).tables[0].rows[0].cells
    assert {run.font.name for cell in cells for p in cell.paragraphs for run in p.runs} == {"Arial"}


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


def test_line_spacing_is_at_least_never_exact(resume: Document, tmp_path: Path) -> None:
    """EXACTLY clips any glyph taller than the line box — Word would silently truncate text."""
    out = tmp_path / "resume.docx"
    ats.render_docx(resume, out)
    rules = {p.paragraph_format.line_spacing_rule for p in read_docx(str(out)).paragraphs}
    assert rules == {WD_LINE_SPACING.AT_LEAST}
