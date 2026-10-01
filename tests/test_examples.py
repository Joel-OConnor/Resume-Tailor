"""The shipped examples and templates are documents the tool itself would accept.

They show a user what a resume drawn from a profile looks like, so they are held to the same
checks as a generated one: every fact in them is one ``examples/master-profile.yaml`` records.
"""

from __future__ import annotations

import pytest

from resume_tailor.documents import parse
from resume_tailor.profile import load
from resume_tailor.verify import format_violations, verify_resume
from tests.conftest import REPO_ROOT

_SHIPPED = (
    "examples/tailored-application/resume.md",
    "examples/tailored-application/cover-letter.md",
    "templates/resume.md",
    "templates/cover-letter.md",
)


@pytest.mark.parametrize("path", _SHIPPED)
def test_a_shipped_example_passes_the_checks_it_demonstrates(path: str) -> None:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    parse(text)  # the format contract the renderers rely on
    verdict = verify_resume(text, load(REPO_ROOT / "examples" / "master-profile.yaml"))
    assert verdict.ok, format_violations(verdict)
