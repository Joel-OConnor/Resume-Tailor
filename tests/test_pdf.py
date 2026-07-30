"""Print-to-PDF, with Chrome stubbed out."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from resume_tailor.render import pdf

HTML = "<!doctype html><html><body>hi</body></html>"


@pytest.fixture(autouse=True)
def _no_real_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never shell out to a real browser from the test suite."""
    monkeypatch.setattr(pdf, "CHROME_CANDIDATES", ())
    monkeypatch.setattr("shutil.which", lambda _: None)


def _fake_chrome(
    monkeypatch: pytest.MonkeyPatch, effect: Any, *, path: str = "/fake/chrome"
) -> list[list[str]]:
    """Point ``find_chrome`` at ``path`` and record every command ``effect`` receives."""
    calls: list[list[str]] = []
    monkeypatch.setattr(pdf, "find_chrome", lambda: path)

    def run(command: list[str], **_: object) -> object:
        calls.append(command)
        return effect(command)

    monkeypatch.setattr("subprocess.run", run)
    return calls


def _writes_pdf(command: list[str]) -> None:
    for argument in command:
        if argument.startswith("--print-to-pdf="):
            Path(argument.removeprefix("--print-to-pdf=")).write_bytes(b"%PDF-1.4\n")


# --- find_chrome ----------------------------------------------------------------------------------
def test_find_chrome_returns_none_when_nothing_is_installed() -> None:
    assert pdf.find_chrome() is None


def test_find_chrome_prefers_an_installed_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "Chrome"
    app.write_text("")
    monkeypatch.setattr(pdf, "CHROME_CANDIDATES", (str(tmp_path / "missing"), str(app)))
    assert pdf.find_chrome() == str(app)


def test_find_chrome_falls_back_to_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def which(name: str) -> str | None:
        return "/usr/bin/x" if name == "chromium" else None

    monkeypatch.setattr("shutil.which", which)
    assert pdf.find_chrome() == "/usr/bin/x"


# --- html_to_pdf ----------------------------------------------------------------------------------
def test_without_chrome_the_html_is_written_instead(tmp_path: Path) -> None:
    out = tmp_path / "resume.pdf"
    assert pdf.html_to_pdf(HTML, out) is False
    assert not out.exists()
    assert out.with_suffix(".html").read_text(encoding="utf-8") == HTML


def test_a_successful_run_produces_the_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _fake_chrome(monkeypatch, _writes_pdf)
    out = tmp_path / "resume.pdf"
    assert pdf.html_to_pdf(HTML, out) is True
    assert out.read_bytes().startswith(b"%PDF")
    assert not out.with_suffix(".html").exists()
    assert len(calls) == 1
    assert calls[0][1] == "--headless=new"
    assert calls[0][-1].startswith("file://")


def test_the_legacy_headless_flag_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def only_old_headless(command: list[str]) -> None:
        if "--headless" in command:
            _writes_pdf(command)

    calls = _fake_chrome(monkeypatch, only_old_headless)
    assert pdf.html_to_pdf(HTML, tmp_path / "resume.pdf") is True
    assert [call[1] for call in calls] == ["--headless=new", "--headless"]


def test_an_empty_pdf_counts_as_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def empty_file(command: list[str]) -> None:
        for argument in command:
            if argument.startswith("--print-to-pdf="):
                Path(argument.removeprefix("--print-to-pdf=")).write_bytes(b"")

    _fake_chrome(monkeypatch, empty_file)
    out = tmp_path / "resume.pdf"
    assert pdf.html_to_pdf(HTML, out) is False
    assert out.with_suffix(".html").read_text(encoding="utf-8") == HTML


@pytest.mark.parametrize(
    "error",
    [OSError("no such binary"), subprocess.TimeoutExpired("chrome", 90)],
)
def test_a_crashing_or_hanging_chrome_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    def raises(_: list[str]) -> None:
        raise error

    _fake_chrome(monkeypatch, raises)
    out = tmp_path / "resume.pdf"
    assert pdf.html_to_pdf(HTML, out) is False
    assert out.with_suffix(".html").exists()


def test_the_temporary_html_is_cleaned_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Path] = []

    def record(command: list[str]) -> None:
        seen.append(Path(command[-1].removeprefix("file://")))
        _writes_pdf(command)

    _fake_chrome(monkeypatch, record)
    pdf.html_to_pdf(HTML, tmp_path / "resume.pdf")
    assert seen and not seen[0].exists()


def test_chrome_is_never_invoked_through_a_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A path with spaces must not be re-split; that is why ``shell=`` is never set."""
    calls = _fake_chrome(monkeypatch, _writes_pdf, path="/Applications/Google Chrome/chrome")
    pdf.html_to_pdf(HTML, tmp_path / "resume.pdf")
    assert calls[0][0] == "/Applications/Google Chrome/chrome"
