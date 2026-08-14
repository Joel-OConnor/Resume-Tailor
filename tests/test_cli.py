"""The command-line interface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from resume_tailor import __version__, cli
from resume_tailor.render import exporter
from resume_tailor.render.pdf import NO_BROWSER, PdfResult
from tests.conftest import REPO_ROOT, RESUME_MD

if TYPE_CHECKING:
    from pathlib import Path

EXAMPLE_PROFILE = str(REPO_ROOT / "templates" / "master-profile.example.yaml")


@pytest.fixture(autouse=True)
def _pdf_always_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_: str, out: Path) -> PdfResult:
        out.write_bytes(b"%PDF-1.4\n")
        return PdfResult(ok=True)

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
    captured = capsys.readouterr().err
    assert "no '# Name' line" in captured
    assert str(bad) in captured


def test_a_pdf_fallback_is_flagged_in_the_output(
    source: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fails(html: str, out: Path) -> PdfResult:
        out.with_suffix(".html").write_text(html, encoding="utf-8")
        return PdfResult(ok=False, reason=NO_BROWSER)

    monkeypatch.setattr(exporter, "html_to_pdf", fails)
    # A failed PDF is a failed build, so `make export` and CI can see it.
    assert cli.main(["build", str(source), "--layout", "ats"]) == 1
    assert NO_BROWSER in capsys.readouterr().out


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


def test_a_source_named_like_another_s_polished_output_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`resume.md` renders `resume-polished.docx`, which `resume-polished.md` also claims."""
    (tmp_path / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    (tmp_path / "resume-polished.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "resume.md"), str(tmp_path / "resume-polished.md")]
    assert cli.main([*argv, "--no-pdf"]) == 1
    assert "resume-polished would be written twice" in capsys.readouterr().err
    assert not (tmp_path / "resume-polished.docx").exists()


def test_that_pair_is_fine_when_only_the_ats_layout_is_built(tmp_path: Path) -> None:
    (tmp_path / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    (tmp_path / "resume-polished.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "resume.md"), str(tmp_path / "resume-polished.md")]
    assert cli.main([*argv, "--layout", "ats", "--no-pdf"]) == 0


def test_the_same_file_listed_twice_is_not_a_clash(tmp_path: Path) -> None:
    source = tmp_path / "resume.md"
    source.write_text(RESUME_MD, encoding="utf-8")
    assert cli.main(["build", str(source), str(source), "--no-pdf"]) == 0


def test_a_directory_is_reported_as_such_not_as_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "adir").mkdir()
    assert cli.main(["build", str(tmp_path / "adir")]) == 1
    assert "not a file:" in capsys.readouterr().err


def test_one_unparseable_file_does_not_abandon_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "bad.md").write_text("no name line\n", encoding="utf-8")
    (tmp_path / "good.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "bad.md"), str(tmp_path / "good.md"), "--no-pdf"]
    assert cli.main(argv) == 1
    assert "no '# Name' line" in capsys.readouterr().err
    assert (tmp_path / "good.docx").is_file()


def test_an_unmatched_sidebar_name_is_flagged(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo like --sidebar Skils would otherwise silently produce the wrong design."""
    assert cli.main(["build", str(source), "--sidebar", "Skills,Skils", "--no-pdf"]) == 0
    assert "--sidebar Skils matched no section" in capsys.readouterr().err


def test_no_sidebar_warning_for_the_ats_layout(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["build", str(source), "--layout", "ats", "--sidebar", "Nope", "--no-pdf"]) == 0
    assert "matched no section" not in capsys.readouterr().err


def test_the_same_file_named_two_ways_is_not_a_clash(tmp_path: Path) -> None:
    source = tmp_path / "resume.md"
    source.write_text(RESUME_MD, encoding="utf-8")
    out = tmp_path / "out"
    argv = ["build", str(source), str(source.absolute()), "--out-dir", str(out), "--no-pdf"]
    assert cli.main(argv) == 0


def test_two_cover_letters_are_not_refused_for_an_impossible_clash(tmp_path: Path) -> None:
    """`build` downgrades a section-less document to ATS, so no -polished file is ever written."""
    letter = "# Ada\nada@example.com\n\nDear Hiring Manager,\n"
    for name in ("letter.md", "letter-polished.md"):
        folder = tmp_path / name.removesuffix(".md")
        folder.mkdir()
        (folder / name).write_text(letter, encoding="utf-8")
    argv = [
        "build",
        str(tmp_path / "letter" / "letter.md"),
        str(tmp_path / "letter-polished" / "letter-polished.md"),
        "--out-dir",
        str(tmp_path / "out"),
        "--no-pdf",
    ]
    assert cli.main(argv) == 0


def test_a_clash_is_caught_regardless_of_letter_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On macOS and Windows `Resume.docx` and `resume.docx` are the same file."""
    for name in ("alice", "bob"):
        folder = tmp_path / name
        folder.mkdir()
    (tmp_path / "alice" / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    (tmp_path / "bob" / "Resume.md").write_text(RESUME_MD, encoding="utf-8")
    out = tmp_path / "out"
    argv = [
        "build",
        str(tmp_path / "alice" / "resume.md"),
        str(tmp_path / "bob" / "Resume.md"),
        "--out-dir",
        str(out),
        "--no-pdf",
    ]
    assert cli.main(argv) == 1
    assert "would be written twice" in capsys.readouterr().err


def test_profile_render_reports_an_unwritable_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "adir").mkdir()
    argv = ["profile", "render", EXAMPLE_PROFILE, "-o", str(tmp_path / "adir")]
    assert cli.main(argv) == 1
    assert "error: cannot write" in capsys.readouterr().err


def test_the_sidebar_warning_fires_for_the_polished_layout_too(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["build", str(source), "--layout", "polished", "--sidebar", "Skils", "--no-pdf"]
    assert cli.main(argv) == 0
    assert "--sidebar Skils matched no section" in capsys.readouterr().err


def test_the_clash_check_survives_an_unreadable_argument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It runs over every argument, including one that turns out to be a directory."""
    (tmp_path / "resume.md").mkdir()
    (tmp_path / "other.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "resume.md"), str(tmp_path / "other.md"), "--no-pdf"]
    assert cli.main(argv) == 1
    assert "not a file:" in capsys.readouterr().err
    assert (tmp_path / "other.docx").is_file()


def test_the_clash_guard_reads_sections_the_way_the_parser_does(tmp_path: Path) -> None:
    """A `## ` inside the template's leading comment is not a section to either of them."""
    from resume_tailor.cli import _has_sections

    commented = tmp_path / "letter.md"
    commented.write_text("<!--\n## Not a section\n-->\n# Ada\n\nDear sir,\n", encoding="utf-8")
    assert _has_sections(commented) is False

    indented = tmp_path / "resume.md"
    indented.write_text("# Ada\n\n  ## Skills\n- x\n", encoding="utf-8")
    assert _has_sections(indented) is True


def test_validate_counts_technologies_not_aliases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`technology_names()` includes aliases by design; a headcount must not use it."""
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "contact: {name: Ada, headline: E, email: a@b.c}\n"
        "summary: s\n"
        "technologies:\n"
        "  - group: G\n"
        "    items:\n"
        "      - {name: Kubernetes, aliases: [K8s, k8s, kube]}\n"
        "      - {name: Go, aliases: [Golang]}\n"
        "experience:\n"
        "  - id: e\n"
        "    company: E\n"
        "    roles: [{title: T, start: '2020', end: '2021'}]\n",
        encoding="utf-8",
    )
    assert cli.main(["profile", "validate", str(profile)]) == 0
    assert "2 technologies" in capsys.readouterr().out


# --- the standalone path ---------------------------------------------------------------------
class _StubModel:
    """Stands in for a language model; the agent layer only ever calls .complete()."""

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, system: str, prompt: str) -> object:
        from resume_tailor.llm import Reply

        assert system and prompt
        return Reply(self.text, 1, 2, "end_turn")


def _profile_file(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(
        "contact: {name: Ada Lovelace, headline: Engineer, email: a@b.c}\n"
        "summary: An engineer.\n"
        "experience:\n"
        "  - id: acme\n"
        "    company: Acme\n"
        "    roles: [{title: Engineer, start: '2020', end: present}]\n",
        encoding="utf-8",
    )
    return path


def test_tailor_writes_an_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    posting = tmp_path / "jd.md"
    posting.write_text("# Acme — Engineer\n\n## Requirements\n- Work.\n", encoding="utf-8")

    called: dict[str, object] = {}

    def fake_tailor(_posting: str, **kwargs: object) -> object:
        from resume_tailor.service import Application

        called.update(kwargs)
        directory = tmp_path / "applications" / "acme-engineer"
        directory.mkdir(parents=True)
        written = directory / "resume.md"
        written.write_text("# Ada\n", encoding="utf-8")
        return Application("acme-engineer", directory, (written,), "Acme", "Engineer")

    monkeypatch.setattr(cli, "tailor_application", fake_tailor)
    monkeypatch.setattr(cli, "build_model", lambda _: _StubModel("x"))
    monkeypatch.setattr(cli, "load_settings", lambda: None)

    argv = [
        "tailor",
        str(posting),
        "--profile",
        str(_profile_file(tmp_path)),
        "--applications",
        str(tmp_path / "applications"),
        "--no-export",
    ]
    assert cli.main(argv) == 0
    assert called["export"] is False
    assert "resume.md" in capsys.readouterr().out


def test_tailor_reports_a_missing_posting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["tailor", str(tmp_path / "absent.md")]) == 1
    assert "not a file" in capsys.readouterr().err


def test_tailor_surfaces_a_missing_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The commonest first-run failure must name the fix, not raise."""
    from resume_tailor.errors import ConfigError

    posting = tmp_path / "jd.md"
    posting.write_text("# Acme — Engineer\n\n- Work.\n", encoding="utf-8")

    def no_key() -> None:
        msg = "no ANTHROPIC_API_KEY found. Copy .env.example to .env"
        raise ConfigError(msg)

    monkeypatch.setattr(cli, "load_settings", no_key)
    assert cli.main(["tailor", str(posting)]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_profile_build_writes_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "old.md").write_text("An old resume.\n", encoding="utf-8")
    out = tmp_path / "master-profile.yaml"

    from resume_tailor.agent import Usage

    monkeypatch.setattr(cli, "build_profile", lambda *_, **__: ("summary: s\n", Usage(1, 2, 1)))
    monkeypatch.setattr(cli, "build_model", lambda _: _StubModel("x"))
    monkeypatch.setattr(cli, "load_settings", lambda: None)

    assert cli.main(["profile", "build", "--raw", str(raw), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "summary: s\n"
    assert "1 document(s)" in capsys.readouterr().out


def test_profile_build_reports_an_empty_raw_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["profile", "build", "--raw", str(tmp_path / "empty")]) == 1
    assert "no readable documents" in capsys.readouterr().err


def test_serve_starts_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: dict[str, object] = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: started.update(kw, app=app))
    assert cli.main(["serve", "--port", "9999", "--profile", str(_profile_file(tmp_path))]) == 0
    assert started["port"] == 9999
    assert "http://127.0.0.1:9999/docs" in capsys.readouterr().out
