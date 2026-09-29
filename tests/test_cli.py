"""The command-line interface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from resume_tailor import __version__, cli
from resume_tailor.render import exporter
from resume_tailor.render.pdf import NO_BROWSER, PdfResult
from tests.conftest import REPO_ROOT, RESUME_MD, pdf_bytes

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

EXAMPLE_PROFILE = str(REPO_ROOT / "examples" / "master-profile.yaml")


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
def test_build_writes_the_one_layout_by_default(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["build", str(source)]) == 0
    out = capsys.readouterr().out
    assert str(source) in out
    assert out.count("✓") == 2
    assert (source.parent / "resume.docx").is_file()
    assert not (source.parent / "resume-polished.docx").exists()


def test_build_honours_the_layout_flag(source: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["build", str(source), "--layout", "both"]) == 0
    assert capsys.readouterr().out.count("✓") == 4
    assert (source.parent / "resume-polished.docx").is_file()


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
def test_profile_validate_summarises_and_audits_the_profile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["profile", "validate", EXAMPLE_PROFILE]) == 0
    out = capsys.readouterr().out
    assert "is valid — 2 employers, 2 roles," in out
    assert "  ? Confirm the exact settlement latency" in out


def test_profile_validate_prints_what_the_audit_still_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "contact: {name: Ada, headline: E, email: a@b.c}\n"
        "summary: s\n"
        "technologies: [{group: G, items: [{name: Go}]}]\n"
        "experience:\n"
        "  - id: e\n"
        "    company: E\n"
        "    roles: [{title: T, start: '2020', end: '2021', highlights: [{text: Did it.}]}]\n",
        encoding="utf-8",
    )
    assert cli.main(["profile", "validate", str(profile)]) == 0
    out = capsys.readouterr().out
    assert "Still worth a look: 2 suggestions" in out
    assert "~ no-level: 1 technologies have no level (Go)" in out


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


def test_every_command_defaults_to_the_documented_folders() -> None:
    """The README promises these folders; a default drifting from them strands the user's files."""
    parse = cli.build_parser().parse_args
    build = parse(["profile", "build"])
    assert build.documents.as_posix() == "my-documents/career-history"
    assert build.out.as_posix() == "output/master-profile.yaml"
    assert build.answers.as_posix() == "my-documents/career-history/answers.md"
    assert parse(["profile", "validate"]).path.as_posix() == "output/master-profile.yaml"
    assert parse(["profile", "render"]).out.as_posix() == "output/master-profile.md"
    assert parse(["profile", "schema"]).out.as_posix() == "schema/master-profile.schema.json"
    for command in (["resume"], ["tailor", "posting.md"]):
        args = parse(command)
        assert (args.profile.as_posix(), args.output.as_posix()) == (
            "output/master-profile.yaml",
            "output",
        )


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
    """With both layouts, `resume.md` renders `resume-polished.docx`, a name a sibling claims."""
    (tmp_path / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    (tmp_path / "resume-polished.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "resume.md"), str(tmp_path / "resume-polished.md")]
    assert cli.main([*argv, "--layout", "both", "--no-pdf"]) == 1
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
    argv = ["build", str(source), "--layout", "both", "--sidebar", "Skills,Skils", "--no-pdf"]
    assert cli.main(argv) == 0
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
    """It runs over every argument, including one that turns out to be a directory.

    With both layouts asked for, the guard has to read each source to know whether a polished
    file will be written, so the directory is where that read fails.
    """
    (tmp_path / "resume.md").mkdir()
    (tmp_path / "other.md").write_text(RESUME_MD, encoding="utf-8")
    argv = ["build", str(tmp_path / "resume.md"), str(tmp_path / "other.md")]
    assert cli.main([*argv, "--layout", "both", "--no-pdf"]) == 1
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
    """Aliases are spellings, not technologies; a headcount must not include them."""
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


# --- the three runs -------------------------------------------------------------------------------
from resume_tailor.review import Answer, Finding, Level, Question, Review  # noqa: E402
from resume_tailor.service import Application, ProfileBuild, ProfileUpdate  # noqa: E402


def _flat(text: str) -> str:
    """Undo the terminal's line wrapping, so an assertion reads the sentence that was printed."""
    return " ".join(text.split())


class _Recorder:
    """Stands in for a service run: records its arguments and returns a canned result."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.args: tuple[object, ...] = ()
        self.kwargs: dict[str, object] = {}

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.args, self.kwargs = args, kwargs
        return self.result


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Pretend an API key is configured, and record how each run asks for its model.

    The model it hands out is never consulted: the runs it is passed to are recorders too.
    """
    monkeypatch.setattr(cli, "load_settings", lambda: None)
    model = _Recorder(object())
    monkeypatch.setattr(cli, "build_model", model)
    return model


def _application(tmp_path: Path, **fields: object) -> Application:
    directory = tmp_path / "output" / "general"
    directory.mkdir(parents=True, exist_ok=True)
    resume = directory / "resume.md"
    resume.write_text(RESUME_MD, encoding="utf-8")
    return Application("general", directory, (resume,), **fields)  # type: ignore[arg-type]


_REVIEWED = Review(
    (Finding("long-bullet", Level.ADVISE, 12, "Built the thing", "44 words; split it"),),
    applied=(Finding("dates", Level.FIX, 9, "2020 - now", "an en dash", "2020 – now"),),
)


def test_resume_runs_the_general_application_and_reports_it(
    tmp_path: Path,
    keyed: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = _Recorder(_application(tmp_path, review=_REVIEWED))
    monkeypatch.setattr(cli, "general_application", run)
    profile, answers = tmp_path / "p.yaml", tmp_path / "a.md"

    argv = ["resume", "--output", str(tmp_path / "output"), "--no-export"]
    argv += ["--profile", str(profile), "--answers", str(answers)]
    assert cli.main([*argv, "--no-interactive"]) == 0

    assert keyed.kwargs.get("announce") is cli._progress, "a relay run says what it waits for"
    assert run.kwargs["model"] is keyed.result
    assert (run.kwargs["profile_path"], run.kwargs["answers_path"]) == (profile, answers)
    assert run.kwargs["output_dir"] == tmp_path / "output"
    assert run.kwargs["export"] is False
    assert run.kwargs["ask"] is None
    out = capsys.readouterr().out
    assert "→ " in out and "✓ resume.md" in out
    assert "Review: 1 fixed · 1 suggestion" in out
    assert "~ line 12  long-bullet: 44 words; split it" in out


@pytest.mark.usefixtures("keyed")
def test_unasked_questions_are_listed_with_how_to_answer_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    questions = (Question("How many users?", "Built the thing"),)
    monkeypatch.setattr(
        cli, "general_application", _Recorder(_application(tmp_path, questions=questions))
    )

    assert cli.main(["resume", "--no-interactive"]) == 0

    out = _flat(capsys.readouterr().out)
    assert "Open questions" in out
    assert "? How many users?" in out
    assert '"Built the thing"' in out
    assert "Run it again at a terminal" in out
    assert "add the facts to output/master-profile.yaml" in out


@pytest.mark.usefixtures("keyed")
def test_asked_questions_are_not_listed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    update = ProfileUpdate(
        (Answer(Question("How many users?"), "About 4,000."),), changes=("highlights: 3 → 4",)
    )
    result = _application(
        tmp_path, questions=(Question("How many users?"),), asked=True, update=update
    )
    monkeypatch.setattr(cli, "general_application", _Recorder(result))

    assert cli.main(["resume", "--interactive"]) == 0

    out = capsys.readouterr().out
    assert "Open questions" not in out
    assert "✓ recorded 1 answer in output/master-profile.yaml" in out
    assert "highlights: 3 → 4" in out


@pytest.mark.usefixtures("keyed")
def test_problems_that_did_not_stop_the_run_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    update = ProfileUpdate((Answer(Question("Q?"), "A."),), error="rate limited")
    result = _application(
        tmp_path, asked=True, update=update, problems=("the documents do not use them yet",)
    )
    monkeypatch.setattr(cli, "general_application", _Recorder(result))

    assert cli.main(["resume"]) == 0

    err = _flat(capsys.readouterr().err)
    assert "could not be recorded in output/master-profile.yaml automatically: rate limited" in err
    assert "! the documents do not use them yet" in err


def test_tailor_runs_on_the_one_posting_named_and_shows_the_fit(
    tmp_path: Path,
    keyed: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    posting = tmp_path / "jd.md"
    posting.write_text("# Acme — Engineer\n\n## Requirements\n- Work.\n", encoding="utf-8")
    run = _Recorder(_application(tmp_path, company="Acme", role="Engineer", fit="Strong on Go."))
    monkeypatch.setattr(cli, "tailor_application", run)
    profile, answers = tmp_path / "p.yaml", tmp_path / "a.md"

    argv = ["tailor", str(posting), "--profile", str(profile), "--answers", str(answers)]
    assert cli.main([*argv, "--no-interactive"]) == 0

    assert keyed.kwargs.get("announce") is cli._progress, "a relay run says what it waits for"
    assert run.kwargs["model"] is keyed.result
    assert (run.kwargs["profile_path"], run.kwargs["answers_path"]) == (profile, answers)
    assert run.args == ("# Acme — Engineer\n\n## Requirements\n- Work.\n",)
    assert run.kwargs["export"] is True
    assert "Fit: Strong on Go." in capsys.readouterr().out


@pytest.mark.usefixtures("keyed")
def test_tailor_finds_a_posting_named_without_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make tailor JOB=acme.md`` works for a posting saved where the README says to save it."""
    monkeypatch.chdir(tmp_path)
    saved = tmp_path / "my-documents" / "job-postings" / "acme.md"
    saved.parent.mkdir(parents=True)
    saved.write_text("# Acme, Engineer\n\n- Work.\n", encoding="utf-8")
    run = _Recorder(_application(tmp_path))
    monkeypatch.setattr(cli, "tailor_application", run)

    assert cli.main(["tailor", "acme.md", "--no-interactive"]) == 0
    assert run.args == ("# Acme, Engineer\n\n- Work.\n",)


@pytest.mark.usefixtures("keyed")
def test_a_posting_path_that_exists_wins_over_one_in_the_postings_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "acme.md").write_text("# Here\n\n- The one named.\n", encoding="utf-8")
    saved = tmp_path / "my-documents" / "job-postings" / "acme.md"
    saved.parent.mkdir(parents=True)
    saved.write_text("# There\n\n- The saved one.\n", encoding="utf-8")
    run = _Recorder(_application(tmp_path))
    monkeypatch.setattr(cli, "tailor_application", run)

    assert cli.main(["tailor", "acme.md", "--no-interactive"]) == 0
    assert run.args == ("# Here\n\n- The one named.\n",)


def test_a_posting_in_neither_place_is_reported_by_the_name_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["tailor", "ghost.md"]) == 1
    assert "not found: ghost.md" in capsys.readouterr().err


def test_tailor_needs_a_posting(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["tailor"])
    assert "posting" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda tmp: tmp / "absent.md", "not found"),
        (lambda tmp: tmp, "not a file"),
    ],
)
def test_tailor_reports_a_posting_it_cannot_use(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make: Callable[[Path], Path],
    expected: str,
) -> None:
    assert cli.main(["tailor", str(make(tmp_path))]) == 1
    assert expected in capsys.readouterr().err


def test_tailor_reports_an_empty_or_unreadable_posting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("  \n", encoding="utf-8")
    assert cli.main(["tailor", str(empty)]) == 1
    assert "is empty" in capsys.readouterr().err

    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00\x80")
    assert cli.main(["tailor", str(binary)]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_a_missing_api_key_is_reported_with_the_fix(
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
    assert cli.main(["resume"]) == 1


# --- asking at the terminal -----------------------------------------------------------------------
def _typed(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    """Feed ``lines`` to input(), then end of input."""
    pending = list(lines)

    def fake_input(_: str = "") -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


def test_the_terminal_asks_each_question_and_keeps_every_reply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _typed(monkeypatch, "About 4,000.", "")
    questions = (Question("How many users?", "Built the thing"), Question("Which year?"))

    answers = cli._ask_in_terminal(questions)

    assert [(a.question, a.text) for a in answers] == [
        (questions[0], "About 4,000."),
        (questions[1], ""),
    ]
    out = capsys.readouterr().out
    assert "2 questions before the final version" in out
    assert "[1/2] How many users?" in out
    assert '"Built the thing"' in out


def test_done_or_end_of_input_stops_the_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = (Question("One?"), Question("Two?"), Question("Three?"))
    _typed(monkeypatch, "yes", "done")
    assert [a.text for a in cli._ask_in_terminal(questions)] == ["yes"]
    _typed(monkeypatch, "yes")
    assert [a.text for a in cli._ask_in_terminal(questions[:2])] == ["yes"]


def test_questions_are_asked_by_default_only_at_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    args = cli.build_parser().parse_args(["resume"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli._asker(args) is cli._ask_in_terminal
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli._asker(args) is None
    assert cli._asker(cli.build_parser().parse_args(["resume", "--interactive"])) is not None


# --- building the profile -------------------------------------------------------------------------
@pytest.fixture
def raw(tmp_path: Path) -> Path:
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / "old.md").write_text("An old resume.\n", encoding="utf-8")
    return folder


def test_profile_build_reads_the_documents_and_reports_what_it_did(
    tmp_path: Path,
    raw: Path,
    keyed: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "master-profile.yaml"
    built = ProfileBuild(
        path=out,
        backup=tmp_path / "backups" / "master-profile.20260925.yaml",
        changes=("Merged two highlights about the migration.",),
        difference=("highlights: 12 → 11",),
        review=Review(
            (
                Finding("overlapping-roles", Level.ADVISE, 0, "experience[0].roles[1]", "overlaps"),
                Finding("note", Level.ASK, 0, "", "Was it 12 or 14?"),
            )
        ),
        questions=(Question("Was it 12 or 14?"),),
    )
    run = _Recorder(built)
    monkeypatch.setattr(cli, "build_master_profile", run)
    answers = tmp_path / "a.md"

    argv = ["profile", "build", "--documents", str(raw), "-o", str(out), "--answers", str(answers)]
    assert cli.main([*argv, "--no-interactive"]) == 0

    assert keyed.kwargs.get("announce") is cli._progress, "a relay run says what it waits for"
    assert run.kwargs["model"] is keyed.result
    assert run.kwargs["answers_path"] == answers
    assert run.kwargs["out"] == out
    assert run.kwargs["force"] is False
    assert run.kwargs["ask"] is None
    printed = _flat(capsys.readouterr().out)
    assert "reading 1 document(s)" in printed
    assert "· old.md" in printed
    assert "(previous profile kept as backups/master-profile.20260925.yaml)" in printed
    assert "Merged two highlights about the migration." in printed
    assert "highlights: 12 → 11" in printed
    assert "~ overlapping-roles: overlaps" in printed
    assert "? Was it 12 or 14?" in printed
    assert "deleting its note" in printed
    assert "make resume" in printed


@pytest.mark.usefixtures("keyed")
def test_profile_build_reports_a_refinement_that_fell_back_and_an_update(
    tmp_path: Path, raw: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "master-profile.yaml"
    built = ProfileBuild(
        path=out,
        backup=None,
        refine_error="lost the figure '38%'",
        update=ProfileUpdate((Answer(Question("Q?"), "A."),), changes=("notes: 1 → 0",)),
    )
    monkeypatch.setattr(cli, "build_master_profile", _Recorder(built))

    assert cli.main(["profile", "build", "--documents", str(raw), "-o", str(out)]) == 0

    captured = capsys.readouterr()
    assert "refining did not pass its checks" in captured.err
    assert "lost the figure '38%'" in _flat(captured.err)
    assert "✓ recorded 1 answer" in captured.out
    assert "Open questions" not in captured.out


def test_profile_build_reports_an_empty_raw_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["profile", "build", "--documents", str(tmp_path / "empty")]) == 1
    assert "no readable documents" in capsys.readouterr().err


def test_profile_build_names_what_it_could_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence here is the failure that matters: a scan nobody knows was never read."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "scan.pdf").write_bytes(pdf_bytes(""))
    assert cli.main(["profile", "build", "--documents", str(raw)]) == 1
    assert "scan.pdf" in capsys.readouterr().err


def test_profile_build_refuses_to_replace_a_profile(
    tmp_path: Path, raw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Weeks of hand corrections must not vanish because a command was re-run."""
    out = tmp_path / "master-profile.yaml"
    out.write_text("summary: hand written\n", encoding="utf-8")

    assert cli.main(["profile", "build", "--documents", str(raw), "-o", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "summary: hand written\n"
    assert "--force" in capsys.readouterr().err


@pytest.mark.usefixtures("keyed")
def test_profile_build_with_force_goes_ahead(
    tmp_path: Path, raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "master-profile.yaml"
    out.write_text("summary: hand written\n", encoding="utf-8")
    run = _Recorder(ProfileBuild(path=out, backup=None))
    monkeypatch.setattr(cli, "build_master_profile", run)

    assert cli.main(["profile", "build", "--documents", str(raw), "-o", str(out), "--force"]) == 0
    assert run.kwargs["force"] is True


def test_progress_is_one_line_per_step(capsys: pytest.CaptureFixture[str]) -> None:
    cli._progress("drafting the profile")
    assert capsys.readouterr().out == "  … drafting the profile\n"


def test_a_profile_with_nothing_to_flag_validates_quietly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "contact: {name: Ada, headline: E, email: a@b.c}\n"
        "summary: s\n"
        "experience:\n"
        "  - id: e\n"
        "    company: E\n"
        "    roles:\n"
        "      - {title: T, start: '2020', end: '2021', highlights: [{label: L, text: Did it.}]}\n",
        encoding="utf-8",
    )
    assert cli.main(["profile", "validate", str(profile)]) == 0
    assert (
        capsys.readouterr().out == f"✓ {profile} is valid — 1 employers, 1 roles, 0 technologies\n"
    )


def test_only_the_first_open_notes_are_printed_with_a_count_of_the_rest(
    tmp_path: Path,
    raw: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: None)
    monkeypatch.setattr(cli, "build_model", lambda *_, **__: object())
    out = tmp_path / "master-profile.yaml"
    notes = tuple(Finding("note", Level.ASK, 0, "", f"Question {n}?") for n in range(11))
    monkeypatch.setattr(
        cli,
        "build_master_profile",
        _Recorder(ProfileBuild(path=out, backup=None, review=Review(notes))),
    )

    assert cli.main(["profile", "build", "--documents", str(raw), "-o", str(out)]) == 0

    printed = _flat(capsys.readouterr().out)
    assert "? Question 7?" in printed
    assert "? Question 8?" not in printed
    assert "3 more are in its notes; `resume-tailor profile validate` lists them." in printed
