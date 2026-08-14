"""Rendering a coverage report, and the ``resume-tailor match`` command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor import cli
from resume_tailor.match import (
    build_lexicon,
    find_coverage,
    match_posting,
    parse_posting,
    read_posting,
    render_json,
    render_markdown,
    render_text,
)
from resume_tailor.profile import load_mapping

if TYPE_CHECKING:
    from pathlib import Path

    from resume_tailor.profile.models import Profile

POSTING = """\
# Acme Corp — Staff Engineer

## Requirements
- Deep PostgreSQL expertise and query tuning.
- Strong Docker skills in production.
- Kafka streaming experience is required.

## Life at Acme
- No Terraform experience is required for this role.
"""


def _profile(**overrides: Any) -> Profile:
    data: dict[str, Any] = {
        "contact": {"name": "Ada", "headline": "Engineer", "email": "a@b.c"},
        "summary": "s",
        "technologies": [
            {
                "group": "Data",
                "items": [
                    {"name": "PostgreSQL", "used_at": ["acme"]},
                    {"name": "Docker", "level": "working", "used_at": ["acme"]},
                    {"name": "Terraform", "level": "exposure", "used_at": ["acme"]},
                ],
            }
        ],
        "experience": [
            {
                "id": "acme",
                "company": "Acme",
                "roles": [
                    {
                        "title": "Engineer",
                        "start": "2020",
                        "end": "present",
                        "highlights": [{"label": "Tuning", "text": "Tuned PostgreSQL heavily."}],
                    }
                ],
            }
        ],
        "notes": ["Confirm Terraform depth before claiming it."],
    }
    return load_mapping({**data, **overrides})


@pytest.fixture
def report() -> Any:
    return match_posting(POSTING, _profile())


def test_text_names_every_section(report: Any) -> None:
    out = render_text(report)
    assert "Coverage for Staff Engineer" in out
    assert "company: Acme Corp" in out
    assert "LEAD WITH THESE" in out
    assert "PostgreSQL" in out
    assert "USE WITH CARE" in out
    assert "ASKED FOR, NOT IN YOUR PROFILE" in out
    assert "Kafka" in out
    assert "IGNORED (not requirements)" in out


def test_text_spells_out_why_a_match_is_qualified(report: Any) -> None:
    out = render_text(report)
    assert "no accomplishment in the profile describes this" in out
    assert "depth: recorded as working" in out


def test_an_unconfirmed_match_is_shouted_about() -> None:
    text = "## Requirements\n- Strong Terraform skills.\n"
    assert "UNCONFIRMED" in render_text(match_posting(text, _profile()))


def test_markdown_is_a_fit_report_section(report: Any) -> None:
    out = render_markdown(report)
    assert out.startswith("## Keyword coverage")
    assert "| Technology | Evidence |" in out
    assert "### Qualified — true, but read the caveat" in out
    assert "### Gaps — asked for, not supported" in out
    assert "Do not add any of these to the resume unless they are true." in out
    assert "### Ignored" in out


def test_markdown_says_so_when_nothing_is_confirmed() -> None:
    out = render_markdown(match_posting("## Requirements\n- Rust and Elixir.\n", _profile()))
    assert "_Nothing in this posting is matched" in out


def test_json_round_trips(report: Any) -> None:
    payload = json.loads(render_json(report))
    assert payload["posting"] == {"title": "Staff Engineer", "company": "Acme Corp"}
    assert {m["technology"] for m in payload["confirmed"]} == {"PostgreSQL"}
    assert payload["confirmed"][0]["confidence"] == "covered"
    assert {g["term"] for g in payload["gaps"]} >= {"Kafka"}
    assert payload["ignored"][0]["reason"] == "company/benefits section"


def test_a_posting_with_no_gaps_or_ignored_lines_renders() -> None:
    minimal = match_posting("## Requirements\n- PostgreSQL.\n", _profile())
    assert "ASKED FOR" not in render_text(minimal)
    assert "### Gaps" not in render_markdown(minimal)


def test_a_posting_matching_nothing_still_renders() -> None:
    empty = match_posting("Some prose with nothing in it at all.\n", _profile())
    assert "this posting" in render_text(empty)
    assert render_markdown(empty)
    assert json.loads(render_json(empty))["confirmed"] == []


def test_evidence_falls_back_to_employers_alone() -> None:
    """A technology with a used_at link but no highlight still cites where it was used."""
    out = render_text(match_posting("## Requirements\n- Strong Docker skills.\n", _profile()))
    assert "[acme]" in out


def test_a_technology_with_neither_employer_nor_highlight_still_renders() -> None:
    profile = _profile(
        technologies=[{"group": "Data", "items": [{"name": "PostgreSQL"}]}], notes=[]
    )
    assert "PostgreSQL" in render_text(match_posting("## Requirements\n- PostgreSQL.\n", profile))


def test_a_negation_outside_a_context_section_is_reported_as_such() -> None:
    text = "## Requirements\n- No Docker experience is required.\n"
    payload = json.loads(render_json(match_posting(text, _profile())))
    assert payload["ignored"][0]["reason"] == "stated as not required"


def test_a_more_specific_product_downgrades_the_match() -> None:
    """The 'Docker Swarm' case: is more specific than the profile's "Docker"."""
    profile = _profile(
        technologies=[{"group": "Ops", "items": [{"name": "Docker", "used_at": ["acme"]}]}],
        notes=[],
    )
    report = match_posting("## Requirements\n- Run Docker Swarm in production.\n", profile)
    match = report.qualified[0]
    assert "more specific product" in match.caveat


def test_ignored_lines_are_only_listed_when_they_mention_something() -> None:
    quiet = match_posting("## Life at Acme\n- We drink coffee.\n", _profile())
    assert not quiet.coverage.ignored


def test_coverage_of_an_empty_posting() -> None:
    coverage = find_coverage(parse_posting(""), build_lexicon(_profile()))
    assert coverage.matches == ()


# --- the CLI command ---------------------------------------------------------------------------
@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    posting = tmp_path / "jd.md"
    posting.write_text(POSTING, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "contact: {name: Ada, headline: E, email: a@b.c}\n"
        "summary: s\n"
        "technologies:\n"
        "  - group: Data\n"
        "    items: [{name: PostgreSQL, used_at: [acme]}]\n"
        "experience:\n"
        "  - id: acme\n"
        "    company: Acme\n"
        "    roles: [{title: T, start: '2020', end: present}]\n",
        encoding="utf-8",
    )
    return posting, profile


@pytest.mark.parametrize("fmt", ["text", "markdown", "json"])
def test_match_command_renders_each_format(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    posting, profile = files
    argv = ["match", str(posting), "--profile", str(profile), "--format", fmt]
    assert cli.main(argv) == 0
    assert "PostgreSQL" in capsys.readouterr().out


def test_match_command_accepts_an_explicit_company(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    posting, profile = files
    argv = ["match", str(posting), "--profile", str(profile), "--company", "Acme Corp"]
    assert cli.main(argv) == 0
    assert "Acme Corp" in capsys.readouterr().out


def test_match_command_reports_a_missing_posting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["match", str(tmp_path / "nope.md")]) == 1
    assert "not a file" in capsys.readouterr().err


def test_match_command_reports_an_invalid_profile(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    posting, _ = files
    broken = tmp_path / "broken.yaml"
    broken.write_text("summary: s\n", encoding="utf-8")
    assert cli.main(["match", str(posting), "--profile", str(broken)]) == 1
    assert "error:" in capsys.readouterr().err


def test_read_posting_strips_a_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "jd.md"
    path.write_bytes(b"\xef\xbb\xbf## Requirements\n- PostgreSQL.\n")
    assert read_posting(path).startswith("## Requirements")


def test_markdown_marks_an_unconfirmed_match() -> None:
    out = render_markdown(match_posting("## Requirements\n- Terraform.\n", _profile()))
    assert "**unconfirmed**" in out


def test_a_qualified_match_can_carry_no_caveat_at_all() -> None:
    """Shallow depth alone qualifies a match without adding a caveat sentence."""
    profile = _profile(
        technologies=[
            {"group": "Ops", "items": [{"name": "Docker", "level": "working", "used_at": ["acme"]}]}
        ],
        experience=[
            {
                "id": "acme",
                "company": "Acme",
                "roles": [
                    {
                        "title": "E",
                        "start": "2020",
                        "end": "present",
                        "highlights": [{"label": "Ship", "text": "Ran Docker in production."}],
                    }
                ],
            }
        ],
        notes=[],
    )
    out = render_text(match_posting("## Requirements\n- Deep Docker skills.\n", profile))
    assert "depth: recorded as working" in out
