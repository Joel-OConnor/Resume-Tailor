"""The command-line interface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from resume_tailor import __version__, cli
from resume_tailor.render import exporter
from tests.conftest import REPO_ROOT, RESUME_MD

if TYPE_CHECKING:
    from pathlib import Path

EXAMPLE_PROFILE = str(REPO_ROOT / "templates" / "master-profile.example.yaml")


@pytest.fixture(autouse=True)
def _pdf_always_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_: str, out: Path) -> bool:
        out.write_bytes(b"%PDF-1.4\n")
        return True

    monkeypatch.setattr(exporter, "html_to_pdf", fake)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "resume.md"
    path.write_text(RESUME_MD, encoding="utf-8")
    return path


# --- argument parsing -----------------------------------------------------------------------------
def test_no_command_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2
    assert "required" in capsys.readouterr().err


def test_profile_with_no_action_is_an_error() -> None:
    with pytest.raises(SystemExit):
        cli.main(["profile"])


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_an_unknown_layout_is_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.main(["build", "x.md", "--layout", "fancy"])


# --- build ----------------------------------------------------------------------------------------
def test_build_writes_both_layouts(source: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["build", str(source)]) == 0
    out = capsys.readouterr().out
    assert str(source) in out
    assert out.count("✓") == 4
    assert (source.parent / "resume-polished.docx").is_file()


def test_build_honours_the_layout_flag(source: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["build", str(source), "--layout", "ats"]) == 0
    assert capsys.readouterr().out.count("✓") == 2
    assert not (source.parent / "resume-polished.docx").exists()


def test_build_honours_no_pdf(source: Path) -> None:
    assert cli.main(["build", str(source), "--no-pdf"]) == 0
    assert not list(source.parent.glob("*.pdf"))


def test_build_honours_out_dir(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "exports"
    assert cli.main(["build", str(source), "--out-dir", str(out)]) == 0
    assert (out / "resume.docx").is_file()


def test_build_honours_the_sidebar_flag(source: Path) -> None:
    from docx import Document as read_docx

    assert cli.main(["build", str(source), "--layout", "polished", "--sidebar", " Summary , "]) == 0
    table = read_docx(str(source.parent / "resume-polished.docx")).tables[0]
    rail = [p.text.strip() for p in table.rows[0].cells[0].paragraphs if p.text.strip()]
    assert "Summary" in rail
    assert "Skills" not in rail


def test_build_accepts_several_files(source: Path, tmp_path: Path) -> None:
    other = tmp_path / "cover-letter.md"
    other.write_text(RESUME_MD, encoding="utf-8")
    assert cli.main(["build", str(source), str(other), "--no-pdf"]) == 0
    assert (tmp_path / "cover-letter.docx").is_file()


def test_a_missing_file_fails_but_the_others_still_build(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["build", str(tmp_path / "ghost.md"), str(source), "--no-pdf"]) == 1
    captured = capsys.readouterr()
    assert "not found: " in captured.err
    assert (source.parent / "resume.docx").is_file()


def test_a_malformed_markdown_file_reports_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "resume.md"
    bad.write_text("## No name here\n", encoding="utf-8")
    assert cli.main(["build", str(bad)]) == 1
    assert "error: no '# Name' line" in capsys.readouterr().err


def test_a_pdf_fallback_is_flagged_in_the_output(
    source: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fails(html: str, out: Path) -> bool:
        out.with_suffix(".html").write_text(html, encoding="utf-8")
        return False

    monkeypatch.setattr(exporter, "html_to_pdf", fails)
    assert cli.main(["build", str(source), "--layout", "ats"]) == 0
    assert "no Chrome found" in capsys.readouterr().out


# --- profile --------------------------------------------------------------------------------------
def test_profile_validate_summarises_the_profile(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["profile", "validate", EXAMPLE_PROFILE]) == 0
    out = capsys.readouterr().out
    assert "is valid — 2 employers, 2 roles," in out
    assert "· note: Confirm the exact settlement latency" in out


def test_profile_validate_reports_an_invalid_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "profile.yaml"
    bad.write_text("summary: s\n", encoding="utf-8")
    assert cli.main(["profile", "validate", str(bad)]) == 1
    assert "error: contact: required key is missing" in capsys.readouterr().err


def test_profile_validate_reports_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["profile", "validate", str(tmp_path / "ghost.yaml")]) == 1
    assert "error: cannot read" in capsys.readouterr().err


def test_profile_render_writes_markdown(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "MASTER_PROFILE.md"
    assert cli.main(["profile", "render", EXAMPLE_PROFILE, "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Master Profile — Jordan Rivera")


def test_profile_schema_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "schema.json"
    assert cli.main(["profile", "schema", "-o", str(out)]) == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["title"] == "Master profile"
    assert out.read_text(encoding="utf-8").endswith("\n")


def test_the_profile_commands_default_to_the_repo_paths() -> None:
    args = cli.build_parser().parse_args(["profile", "validate"])
    assert args.path.as_posix() == "profile/master-profile.yaml"
    args = cli.build_parser().parse_args(["profile", "schema"])
    assert args.out.as_posix() == "schema/master-profile.schema.json"


def test_out_dir_refuses_sources_that_would_overwrite_each_other(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two `resume.md` files under one --out-dir would silently clobber one another."""
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    out = tmp_path / "exports"
    argv = ["build", str(tmp_path / "a" / "resume.md"), str(tmp_path / "b" / "resume.md")]
    assert cli.main([*argv, "--out-dir", str(out), "--no-pdf"]) == 1
    assert "would be written twice" in capsys.readouterr().err
    assert not out.exists()


def test_the_same_stems_are_fine_without_an_out_dir(tmp_path: Path) -> None:
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "a" / "resume.md"), str(tmp_path / "b" / "resume.md")]
    assert cli.main([*argv, "--no-pdf"]) == 0
    assert (tmp_path / "a" / "resume.docx").is_file()
    assert (tmp_path / "b" / "resume.docx").is_file()
