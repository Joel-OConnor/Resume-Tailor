"""Rendering a coverage report: the keyword analysis a tailoring prompt carries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.match import (
    build_lexicon,
    find_coverage,
    match_posting,
    parse_posting,
    read_posting,
    render_markdown,
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


def test_the_report_sorts_the_posting_into_what_to_lead_with_qualify_and_leave_out(
    report: Any,
) -> None:
    assert report.posting.title == "Staff Engineer"
    assert report.posting.company == "Acme Corp"
    assert {m.technology for m in report.confirmed} == {"PostgreSQL"}
    assert report.confirmed[0].confidence.value == "covered"
    assert {g.term for g in report.gaps} >= {"Kafka"}
    assert report.coverage.ignored[0][1] == "company/benefits section"


def test_markdown_names_every_section(report: Any) -> None:
    out = render_markdown(report)
    assert out.startswith("## Keyword coverage")
    assert "| Technology | Evidence |" in out
    assert "| PostgreSQL | acme — Tuning |" in out
    assert "### Qualified — true, but read the caveat" in out
    assert "no accomplishment in the profile describes this" in out
    assert "profile records this as **working**" in out
    assert "### Gaps — asked for, not supported" in out
    assert "Do not add any of these to the resume unless they are true." in out
    assert "### Ignored" in out


def test_markdown_says_so_when_nothing_is_confirmed() -> None:
    out = render_markdown(match_posting("## Requirements\n- Rust and Elixir.\n", _profile()))
    assert "_Nothing in this posting is matched" in out


def test_markdown_marks_an_unconfirmed_match() -> None:
    out = render_markdown(match_posting("## Requirements\n- Terraform.\n", _profile()))
    assert "**unconfirmed**" in out


def test_a_posting_with_no_gaps_or_ignored_lines_renders() -> None:
    minimal = match_posting("## Requirements\n- PostgreSQL.\n", _profile())
    out = render_markdown(minimal)
    assert "### Gaps" not in out
    assert "### Ignored" not in out


def test_a_posting_matching_nothing_still_renders() -> None:
    empty = match_posting("Some prose with nothing in it at all.\n", _profile())
    assert empty.confirmed == ()
    assert render_markdown(empty).startswith("## Keyword coverage")


def test_a_confirmed_match_with_no_employer_cites_the_accomplishment_alone() -> None:
    profile = _profile(
        technologies=[{"group": "Data", "items": [{"name": "PostgreSQL"}]}], notes=[]
    )
    out = render_markdown(match_posting("## Requirements\n- PostgreSQL.\n", profile))
    assert "| PostgreSQL | Tuning |" in out


def test_a_negation_outside_a_context_section_is_reported_as_such() -> None:
    text = "## Requirements\n- No Docker experience is required.\n"
    assert match_posting(text, _profile()).coverage.ignored[0][1] == "stated as not required"


def test_a_more_specific_product_downgrades_the_match() -> None:
    """The 'Docker Swarm' case: is more specific than the profile's "Docker"."""
    profile = _profile(
        technologies=[{"group": "Ops", "items": [{"name": "Docker", "used_at": ["acme"]}]}],
        notes=[],
    )
    report = match_posting("## Requirements\n- Run Docker Swarm in production.\n", profile)
    match = report.qualified[0]
    assert "more specific product" in match.caveat
    assert "- **Docker** — the posting names a more specific product" in render_markdown(report)


def test_ignored_lines_are_only_listed_when_they_mention_something() -> None:
    quiet = match_posting("## Life at Acme\n- We drink coffee.\n", _profile())
    assert not quiet.coverage.ignored


def test_coverage_of_an_empty_posting() -> None:
    coverage = find_coverage(parse_posting(""), build_lexicon(_profile()))
    assert coverage.matches == ()


def test_read_posting_strips_a_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "jd.md"
    path.write_bytes(b"\xef\xbb\xbf## Requirements\n- PostgreSQL.\n")
    assert read_posting(path).startswith("## Requirements")


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
    out = render_markdown(match_posting("## Requirements\n- Deep Docker skills.\n", profile))
    assert "- **Docker** — profile records this as **working**" in out
