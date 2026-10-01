"""The generated human-readable Markdown view of a profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from resume_tailor.profile import loader
from resume_tailor.profile.markdown_view import format_period, render_markdown
from tests.conftest import REPO_ROOT

MINIMAL: dict[str, Any] = {
    "contact": {"name": "Ada", "headline": "Engineer", "email": "ada@example.com"},
    "summary": "Writes programs for engines.",
    "experience": [
        {
            "id": "analytical-engine",
            "company": "Analytical Engine Programme",
            "roles": [{"title": "Principal Engineer", "start": "1843-01", "end": "present"}],
        }
    ],
}


def _render(**overrides: Any) -> str:
    return render_markdown(loader.load_mapping({**MINIMAL, **overrides}))


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2022-06", "present", "June 2022 – Present"),
        ("2020-01", "2021-12", "January 2020 – December 2021"),
        ("2016", "2018", "2016 – 2018"),
        ("2016", "2018-03", "2016 – March 2018"),
    ],
)
def test_period_formatting(start: str, end: str, expected: str) -> None:
    assert format_period(start, end) == expected


def test_the_minimal_profile_renders_the_core_sections() -> None:
    markdown = _render()
    assert markdown.startswith("# Master Profile — Ada\n")
    assert "> Generated from `output/master-profile.yaml`" in markdown
    assert "## Contact & links" in markdown
    assert "- **Name:** Ada" in markdown
    assert "## Professional summary" in markdown
    assert "## Work experience" in markdown
    assert "### Analytical Engine Programme" in markdown
    assert "#### Principal Engineer" in markdown
    assert "*January 1843 – Present*" in markdown


def test_the_header_names_the_file_the_view_was_rendered_from() -> None:
    """A view of a backup or the example must not send the reader to edit the live profile."""
    profile = loader.load_mapping(MINIMAL)
    markdown = render_markdown(profile, source=Path("examples/master-profile.yaml"))
    assert markdown.splitlines()[2] == (
        "> Generated from `examples/master-profile.yaml`. Edit the YAML, not this file."
    )
    assert "output/master-profile.yaml" not in markdown


def test_without_a_source_the_header_names_the_default_profile() -> None:
    assert _render().splitlines()[2] == (
        "> Generated from `output/master-profile.yaml`. Edit the YAML, not this file."
    )


def test_it_ends_with_exactly_one_newline() -> None:
    markdown = _render()
    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")


def test_optional_contact_fields_only_appear_when_set() -> None:
    assert "**Phone:**" not in _render()
    filled = _render(
        contact={
            **MINIMAL["contact"],
            "phone": "555",
            "location": "London",
            "work_authorization": "UK",
            "links": [{"label": "GitHub", "url": "https://gh/ada"}],
        }
    )
    assert "- **Phone:** 555" in filled
    assert "- **Location:** London" in filled
    assert "- **Work authorization:** UK" in filled
    assert "- **GitHub:** https://gh/ada" in filled


def test_empty_optional_sections_are_omitted() -> None:
    markdown = _render()
    for heading in ("Target roles", "Technologies", "Education", "Projects", "Certifications"):
        assert f"## {heading}" not in markdown


def test_target_roles_render_as_a_list() -> None:
    assert "- Staff Engineer" in _render(target_roles=["Staff Engineer"])


def test_technologies_render_with_their_detail() -> None:
    markdown = _render(
        technologies=[
            {
                "group": "Data",
                "items": [
                    {
                        "name": "Kubernetes",
                        "aliases": ["K8s"],
                        "level": "expert",
                        "years": 3,
                        "used_at": ["analytical-engine"],
                    },
                    {"name": "SQL"},
                ],
            }
        ]
    )
    assert "### Data" in markdown
    assert "- **Kubernetes** — aka K8s, expert, 3 yrs, at analytical-engine" in markdown
    assert "- **SQL**\n" in markdown


def test_a_single_year_is_not_pluralised() -> None:
    markdown = _render(technologies=[{"group": "G", "items": [{"name": "Go", "years": 1}]}])
    assert "1 yr," not in markdown
    assert "**Go** — 1 yr" in markdown


def test_role_scope_stack_and_highlights_render() -> None:
    markdown = _render(
        experience=[
            {
                "id": "e",
                "company": "E",
                "location": "Remote",
                "industry": "Fintech",
                "summary": "Pays people.",
                "roles": [
                    {
                        "title": "T",
                        "start": "2020",
                        "end": "2021",
                        "scope": "Ten engineers.",
                        "stack": ["Go", "SQL"],
                        "highlights": [
                            {"label": "Speed", "text": "Made it fast.", "tags": ["perf"]},
                            {"text": "Plain one."},
                        ],
                    }
                ],
            }
        ]
    )
    assert "### E — Remote" in markdown
    assert "*Industry:* Fintech" in markdown
    assert "Pays people." in markdown
    assert "**Scope:** Ten engineers." in markdown
    assert "**Stack:** Go, SQL" in markdown
    assert "- **Speed:** Made it fast. *(tags: perf)*" in markdown
    assert "- Plain one." in markdown


def test_education_renders_with_and_without_detail() -> None:
    markdown = _render(
        education=[
            {
                "credential": "BSc",
                "institution": "X",
                "completed": "2016-05",
                "location": "London",
                "notes": "First class",
            },
            {"credential": "MSc", "institution": "Y"},
        ]
    )
    assert "### BSc — X" in markdown
    assert "May 2016 · London · First class" in markdown
    assert "### MSc — Y" in markdown


def test_credentials_render_with_their_issuer_and_year() -> None:
    markdown = _render(
        certifications=[{"name": "AWS SAA", "issuer": "Amazon", "year": "2022"}],
        awards=[{"name": "Prize"}],
    )
    assert "## Certifications & licenses" in markdown
    assert "- AWS SAA — Amazon — 2022" in markdown
    assert "## Awards, publications & talks" in markdown
    assert "- Prize\n" in markdown


def test_projects_render() -> None:
    markdown = _render(
        projects=[
            {"name": "P", "description": "A thing.", "stack": ["Go"], "outcome": "300 stars"},
            {"name": "Q", "description": "Another."},
        ]
    )
    assert "### P" in markdown
    assert "**Stack:** Go" in markdown
    assert "**Outcome:** 300 stars" in markdown
    assert "### Q" in markdown


def test_notes_render_under_a_warning_heading() -> None:
    markdown = _render(notes=["Check the numbers."])
    assert "## Notes — confirm before using on a resume" in markdown
    assert "- Check the numbers." in markdown


def test_the_shipped_example_renders() -> None:
    profile = loader.load(REPO_ROOT / "examples" / "master-profile.yaml")
    markdown = render_markdown(profile)
    assert "# Master Profile — Jordan Rivera" in markdown
    assert "March 2021 – Present" in markdown
    assert "pgbench-lite" in markdown


def test_a_role_with_no_extras_renders_just_its_title_and_period() -> None:
    markdown = _render()
    assert "**Scope:**" not in markdown
    assert "**Stack:**" not in markdown


def test_a_multi_line_value_is_flattened_onto_one_line() -> None:
    """A blank line inside a value would terminate the surrounding Markdown list."""
    markdown = _render(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [
                    {
                        "title": "T",
                        "start": "2020",
                        "end": "2021",
                        "scope": "one\n\ntwo",
                        "highlights": [{"label": "A\nB", "text": "first\n\nsecond"}],
                    }
                ],
            }
        ]
    )
    assert "**Scope:** one two" in markdown
    assert "- **A B:** first second" in markdown
    assert "\n\nsecond" not in markdown


@pytest.mark.parametrize(
    "payload",
    ["```", "~~~", "# PWNED", "## Work experience", "---", "- item", "1. item", "> quote"],
)
def test_a_value_cannot_inject_a_markdown_block(payload: str) -> None:
    """A bare ``` in the summary used to open a fence that swallowed the rest of the document."""
    markdown = _render(summary=payload)
    body = markdown.split("## Professional summary", 1)[1]
    assert body.lstrip().startswith("\\")
    assert "## Work experience" in markdown
    assert markdown.count("## ") >= 3


def test_a_role_without_highlights_does_not_double_a_blank_line() -> None:
    markdown = _render(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [{"title": "T", "start": "2020", "end": "2021", "highlights": []}],
            }
        ]
    )
    assert "\n\n\n" not in markdown
