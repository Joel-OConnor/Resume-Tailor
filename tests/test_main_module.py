"""``python -m resume_tailor`` must behave exactly like the console script."""

from __future__ import annotations

import runpy
import sys

import pytest

# Importing it must not run the CLI: without its __name__ guard, collection fails right here.
import resume_tailor.__main__
from resume_tailor import __version__


def test_running_the_package_as_a_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["resume-tailor", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(resume_tailor.__main__.__file__, run_name="__main__")
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out
