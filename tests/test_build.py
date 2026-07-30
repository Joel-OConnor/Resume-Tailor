"""Orchestration: one Markdown file in, the right set of files out."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from resume_tailor.render import exporter
from resume_tailor.render.exporter import Layout, build
from tests.conftest import RESUME_MD

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "resume.md"
    path.write_text(RESUME_MD, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _pdf_always_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_: str, out: Path) -> bool:
        out.write_bytes(b"%PDF-1.4\n")
        return True

    monkeypatch.setattr(exporter, "html_to_pdf", fake)


def _names(source: Path, **kwargs: object) -> list[str]:
    return [artifact.path.name for artifact in build(source, **kwargs)]  # type: ignore[arg-type]


def test_both_layouts_by_default(source: Path) -> None:
    assert _names(source) == [
        "resume.docx",
        "resume.pdf",
        "resume-polished.docx",
        "resume-polished.pdf",
    ]


def test_the_ats_layout_keeps_the_source_stem(source: Path) -> None:
    assert _names(source, layout=Layout.ATS) == ["resume.docx", "resume.pdf"]


def test_the_polished_layout_is_suffixed(source: Path) -> None:
    assert _names(source, layout=Layout.POLISHED) == [
        "resume-polished.docx",
        "resume-polished.pdf",
    ]


def test_no_pdf_writes_only_word_files(source: Path) -> None:
    assert _names(source, pdf=False) == ["resume.docx", "resume-polished.docx"]


def test_every_artifact_actually_exists(source: Path) -> None:
    assert all(artifact.path.is_file() for artifact in build(source))


def test_artifacts_report_their_layout(source: Path) -> None:
    assert [artifact.layout for artifact in build(source)] == [
        Layout.ATS,
        Layout.ATS,
        Layout.POLISHED,
        Layout.POLISHED,
    ]


def test_an_out_dir_is_created_and_used(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "exports"
    artifacts = build(source, out_dir=out, layout=Layout.ATS)
    assert all(artifact.path.parent == out for artifact in artifacts)
    assert (out / "resume.docx").is_file()


def test_a_failed_pdf_is_reported_as_html(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fails(html: str, out: Path) -> bool:
        out.with_suffix(".html").write_text(html, encoding="utf-8")
        return False

    monkeypatch.setattr(exporter, "html_to_pdf", fails)
    artifacts = build(source, layout=Layout.ATS)
    assert [(a.path.name, a.ok) for a in artifacts] == [
        ("resume.docx", True),
        ("resume.html", False),
    ]


def test_the_sidebar_selection_reaches_the_polished_renderer(source: Path, tmp_path: Path) -> None:
    from docx import Document as read_docx

    build(source, layout=Layout.POLISHED, sidebar_sections=("summary",))
    table = read_docx(str(tmp_path / "resume-polished.docx")).tables[0]
    rail = [p.text.strip() for p in table.rows[0].cells[0].paragraphs if p.text.strip()]
    assert "Summary" in rail
    assert "Skills" not in rail


def test_the_layout_enum_round_trips_through_strings() -> None:
    assert Layout("both") is Layout.BOTH
    assert str(Layout.ATS) == "ats"


def test_a_cover_letter_skips_the_polished_layout_by_default(tmp_path: Path) -> None:
    """A letter has no sections: the rail would be empty, and the docs promise one column."""
    letter = tmp_path / "cover-letter.md"
    letter.write_text(
        "# Ada\nada@example.com\n\nDear Hiring Manager,\n\nHello.\n", encoding="utf-8"
    )
    assert _names(letter) == ["cover-letter.docx", "cover-letter.pdf"]


def test_an_explicit_polished_layout_still_renders_a_letter(tmp_path: Path) -> None:
    letter = tmp_path / "cover-letter.md"
    letter.write_text("# Ada\nada@example.com\n\nDear Hiring Manager,\n", encoding="utf-8")
    assert _names(letter, layout=Layout.POLISHED) == [
        "cover-letter-polished.docx",
        "cover-letter-polished.pdf",
    ]


def test_is_sectioned_distinguishes_a_resume_from_a_letter() -> None:
    from resume_tailor.documents import parse

    assert exporter.is_sectioned(parse("# A\n\n## Summary\nx"))
    assert not exporter.is_sectioned(parse("# A\n\nDear sir,\n"))
