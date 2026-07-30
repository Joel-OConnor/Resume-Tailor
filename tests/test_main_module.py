"""``python -m resume_tailor`` must behave exactly like the console script."""

from __future__ import annotations

import runpy
import sys

import pytest

import resume_tailor.__main__
from resume_tailor import __version__


def test_importing_the_module_does_not_run_the_cli() -> None:
    assert resume_tailor.__main__.__name__ == "resume_tailor.__main__"


def test_running_the_package_as_a_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["resume-tailor", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(resume_tailor.__main__.__file__, run_name="__main__")
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out
