"""The ATS-safe layout — the properties a resume parser depends on."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docx import Document as read_docx

from resume_tailor.documents import parse
from resume_tailor.render import ats
from tests.conftest import docx_lines

if TYPE_CHECKING:
    from pathlib import Path

    from docx.document import Document as DocxDocument

    from resume_tailor.documents.blocks import Document


def _render(document: Document, tmp_path: Path) -> DocxDocument:
    out = tmp_path / "resume.docx"
    ats.render_docx(document, out)
    return read_docx(str(out))


def test_docx_has_no_tables(resume: Document, tmp_path: Path) -> None:
    """Tables are the single most common cause of a scrambled parse."""
    assert not _render(resume, tmp_path).tables


def test_docx_keeps_contact_details_out_of_the_header_region(
    resume: Document, tmp_path: Path
) -> None:
    """Many parsers ignore the header/footer entirely."""
    document = _render(resume, tmp_path)
    for section in document.sections:
        assert not [p.text.strip() for p in section.header.paragraphs if p.text.strip()]
        assert not [p.text.strip() for p in section.footer.paragraphs if p.text.strip()]


def test_docx_contains_every_line_in_source_order(resume: Document, tmp_path: Path) -> None:
    lines = docx_lines(_render(resume, tmp_path))
    assert lines[0] == "Ada Lovelace"
    assert "ada@example.com | (555) 010-0100 | London, UK | github.com/ada" in lines
    assert "SUMMARY" in lines
    assert "Languages: Analytical Notation, Mathematics" in lines
    assert "Analytical Engine Programme — Principal Engineer" in lines
    assert lines.index("SUMMARY") < lines.index("EXPERIENCE")


def test_section_headings_are_uppercased(resume: Document, tmp_path: Path) -> None:
    lines = docx_lines(_render(resume, tmp_path))
    assert {"SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION", "CERTIFICATIONS"} <= set(lines)


def test_bullets_use_the_list_bullet_style(resume: Document, tmp_path: Path) -> None:
    document = _render(resume, tmp_path)
    matching = [p for p in document.paragraphs if "first algorithm" in p.text]
    styles = {p.style.name for p in matching if p.style is not None}
    assert styles == {"List Bullet"}


def test_inline_bold_becomes_a_bold_run(resume: Document, tmp_path: Path) -> None:
    document = _render(resume, tmp_path)
    runs = [r for p in document.paragraphs for r in p.runs if r.text == "programs"]
    assert runs and all(run.bold for run in runs)


def test_a_meta_line_renders_italic(resume: Document, tmp_path: Path) -> None:
    document = _render(resume, tmp_path)
    runs = [r for p in document.paragraphs for r in p.runs if "Jan 1843" in r.text]
    assert runs and all(run.italic for run in runs)


def test_every_run_uses_a_standard_font(resume: Document, tmp_path: Path) -> None:
    document = _render(resume, tmp_path)
    fonts = {r.font.name for p in document.paragraphs for r in p.runs}
    assert fonts == {ats.FONT}


def test_a_cover_letter_renders_as_prose(letter: Document, tmp_path: Path) -> None:
    lines = docx_lines(_render(letter, tmp_path))
    assert lines[0] == "Ada Lovelace"
    assert "Dear Hiring Manager," in lines
    assert "Sincerely, Ada" in lines


def test_html_mirrors_the_docx_structure(resume: Document) -> None:
    html = ats.render_html(resume)
    assert html.startswith("<!doctype html>")
    assert "<title>Ada Lovelace</title>" in html
    assert "<h1>Ada Lovelace</h1>" in html
    assert "<h2>Summary</h2>" in html
    assert "<h3>Analytical Engine Programme — Principal Engineer</h3>" in html
    assert '<div class="meta"><em>London, UK | Jan 1843 – Present</em></div>' in html
    assert "<strong>Languages: </strong>Analytical Notation, Mathematics" in html


def test_html_wraps_consecutive_bullets_in_one_list(resume: Document) -> None:
    html = ats.render_html(resume)
    assert html.count("<ul>") == html.count("</ul>") == 2  # experience + certifications
    assert "<li><strong>Algorithm Design:</strong> Published" in html


def test_html_escapes_markup_in_content() -> None:
    html = ats.render_html(parse("# A <b>& Co</b>\n\n## Summary\n5 < 6"))
    assert "&lt;b&gt;" in html
    assert "5 &lt; 6" in html
    assert "<b>" not in html


def test_html_falls_back_to_a_generic_title() -> None:
    from resume_tailor.documents.blocks import Document as Blocks

    assert "<title>Resume</title>" in ats.render_html(Blocks())


def test_a_trailing_italic_note_renders_outside_the_bullet_list(resume: Document) -> None:
    html = ats.render_html(resume)
    assert "</ul><p><em>Tech Stack — Bernoulli numbers, punched cards</em></p>" in html
