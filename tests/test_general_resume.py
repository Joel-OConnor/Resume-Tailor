"""The untailored, general-purpose resume rendered straight from the profile."""

from __future__ import annotations

from typing import Any

import pytest

from resume_tailor.documents import parse
from resume_tailor.profile import ResumeShape, load, loader, render_general_resume
from resume_tailor.render.exporter import is_sectioned
from resume_tailor.verify import verify_resume
from tests.conftest import REPO_ROOT

EXAMPLE_PROFILE = REPO_ROOT / "templates" / "master-profile.example.yaml"

MINIMAL: dict[str, Any] = {
    "contact": {
        "name": "Ada Lovelace",
        "headline": "Principal Engineer @ Analytical Engine | punched cards, Bernoulli numbers",
        "email": "ada@example.com",
    },
    "summary": "Writes programs for engines\nthat do not exist yet.",
    "experience": [
        {
            "id": "analytical-engine",
            "company": "Analytical Engine Programme",
            "roles": [{"title": "Principal Engineer", "start": "1843-01", "end": "present"}],
        }
    ],
}


def render(shape: ResumeShape = ResumeShape(), **overrides: Any) -> str:  # noqa: B008
    return render_general_resume(loader.load_mapping({**MINIMAL, **overrides}), shape)


def lines(shape: ResumeShape = ResumeShape(), **overrides: Any) -> list[str]:  # noqa: B008
    return render(shape, **overrides).splitlines()


# --- header ---------------------------------------------------------------------------------------
def test_the_name_title_and_contact_line_open_the_document() -> None:
    assert lines()[:3] == [
        "# Ada Lovelace",
        "Principal Engineer @ Analytical Engine",
        "ada@example.com",
    ]


def test_the_title_prefers_the_first_target_role_over_the_headline() -> None:
    assert lines(target_roles=["Staff Engineer", "Principal"])[1] == "Staff Engineer"


def test_an_explicit_title_wins_and_its_pipes_are_defused() -> None:
    """A pipe would turn the title into a contact line, so it is replaced, not printed."""
    assert lines(ResumeShape(title="Engineer | Author"))[1] == "Engineer / Author"


def test_a_headline_that_is_only_pipes_still_yields_a_title() -> None:
    assert lines(contact={**MINIMAL["contact"], "headline": "| engineer"})[1] == "/ engineer"


def test_the_contact_line_carries_every_detail_that_is_set_and_shortens_urls() -> None:
    contact = {
        **MINIMAL["contact"],
        "location": "London, UK",
        "phone": "555-0100",
        "work_authorization": "UK citizen",
        "links": [
            {"label": "LinkedIn", "url": "https://www.linkedin.com/in/ada/"},
            {"label": "Site", "url": "ada.example"},
        ],
    }
    assert lines(contact=contact)[2] == (
        "London, UK | ada@example.com | 555-0100 | linkedin.com/in/ada | ada.example | UK citizen"
    )


def test_a_link_that_is_nothing_but_scheme_is_printed_as_written() -> None:
    contact = {**MINIMAL["contact"], "links": [{"label": "Odd", "url": "https://"}]}
    assert lines(contact=contact)[2] == "ada@example.com | https://"


# --- summary and skills ---------------------------------------------------------------------------
def test_the_summary_is_flattened_onto_one_line() -> None:
    text = render()
    assert "## Summary\n\nWrites programs for engines that do not exist yet.\n" in text


def test_skills_print_one_line_per_group_and_skip_thin_depths() -> None:
    technologies = [
        {
            "group": "Languages",
            "items": [
                {"name": "Analytical Notation", "level": "expert"},
                {"name": "Latin", "level": "working"},
                {"name": "French", "level": "exposure"},
                {"name": "Mathematics"},
            ],
        },
        {"group": "Thin only", "items": [{"name": "Weaving", "level": "exposure"}]},
    ]
    text = render(technologies=technologies)
    assert "## Skills\n\n**Languages:** Analytical Notation, Mathematics\n" in text
    assert "Thin only" not in text
    assert "Latin" not in text


def test_no_skills_section_when_nothing_is_worth_claiming() -> None:
    assert "## Skills" not in render()
    thin = [{"group": "Languages", "items": [{"name": "Latin", "level": "working"}]}]
    assert "## Skills" not in render(technologies=thin)


def test_max_skills_caps_each_group_in_profile_order() -> None:
    technologies = [
        {"group": "Languages", "items": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
        {"group": "Tools", "items": [{"name": "D"}]},
    ]
    text = render(ResumeShape(max_skills=2), technologies=technologies)
    assert "**Languages:** A, B\n" in text
    assert "**Tools:** D\n" in text


# --- experience -----------------------------------------------------------------------------------
def test_each_role_is_an_entry_with_its_period_location_bullets_and_stack() -> None:
    experience = [
        {
            "id": "engine",
            "company": "Analytical Engine Programme",
            "location": "London, UK",
            "roles": [
                {
                    "title": "Principal Engineer",
                    "start": "1843-01",
                    "end": "present",
                    "stack": ["Punched cards", "Bernoulli numbers"],
                    "highlights": [
                        {"label": "Algorithm Design", "text": "Published the first algorithm."},
                        {"text": "Corresponded with Babbage\non engine semantics."},
                    ],
                },
                {"title": "Translator", "start": "1842", "end": "1843"},
            ],
        }
    ]
    text = render(experience=experience)
    assert (
        "## Experience\n\n"
        "### Analytical Engine Programme – Principal Engineer\n"
        "January 1843 – Present | London, UK\n"
        "- **Algorithm Design:** Published the first algorithm.\n"
        "- Corresponded with Babbage on engine semantics.\n"
        "*Tech Stack – Punched cards, Bernoulli numbers*\n\n"
        "### Analytical Engine Programme – Translator\n"
        "1842 – 1843 | London, UK\n"
    ) in text


def test_max_highlights_keeps_the_first_bullets_in_profile_order() -> None:
    roles = [
        {
            "title": "Principal Engineer",
            "start": "1843-01",
            "end": "present",
            "highlights": [{"text": "first"}, {"text": "second"}, {"text": "third"}],
        }
    ]
    experience = [{**MINIMAL["experience"][0], "roles": roles}]
    text = render(ResumeShape(max_highlights=2), experience=experience)
    assert "- first\n- second\n" in text
    assert "third" not in text


def test_since_drops_employers_left_before_that_year_but_never_a_current_one() -> None:
    experience = [
        {
            "id": "engine",
            "company": "Analytical Engine Programme",
            "roles": [{"title": "Principal Engineer", "start": "1843-01", "end": "present"}],
        },
        {
            "id": "salon",
            "company": "Somerville Salon",
            "roles": [{"title": "Student", "start": "1834", "end": "1840-06"}],
        },
        {
            "id": "tuition",
            "company": "Private Tuition",
            "roles": [{"title": "Pupil", "start": "1828", "end": "1833"}],
        },
    ]
    text = render(ResumeShape(since="1840"), experience=experience)
    assert "Analytical Engine Programme" in text
    assert "Somerville Salon" in text, "left during the cut-off year, so it stays"
    assert "Private Tuition" not in text


def test_since_can_leave_no_experience_at_all_and_the_document_still_parses() -> None:
    roles = [{"title": "Principal Engineer", "start": "1843-01", "end": "1852-11"}]
    experience = [{**MINIMAL["experience"][0], "roles": roles}]
    text = render(ResumeShape(since="1900"), experience=experience)
    assert "## Experience" not in text
    parse(text)


# --- education, credentials, projects -------------------------------------------------------------
def test_education_entries_carry_date_location_and_notes_when_present() -> None:
    education = [
        {
            "credential": "Private tuition in mathematics",
            "institution": "De Morgan",
            "completed": "1840-06",
            "location": "London, UK",
            "notes": "With distinction",
        },
        {"credential": "Self-taught", "institution": "Home"},
    ]
    text = render(education=education)
    assert (
        "## Education\n\n"
        "### Private tuition in mathematics – De Morgan\n"
        "June 1840 | London, UK | With distinction\n\n"
        "### Self-taught – Home\n"
    ) in text


def test_certifications_and_awards_are_entries_with_an_optional_detail_line() -> None:
    text = render(
        certifications=[
            {"name": "Fellow", "issuer": "Analytical Society", "year": "1843", "notes": "Lapsed"},
            {"name": "Honorary member"},
        ],
        awards=[{"name": "Lovelace Medal", "year": "1852"}],
    )
    assert "## Certifications\n\n### Fellow\nAnalytical Society | 1843 | Lapsed\n\n" in text
    assert "### Honorary member\n\n## Awards\n\n### Lovelace Medal\n1852\n" in text


def test_projects_print_their_description_outcome_and_stack() -> None:
    text = render(
        projects=[
            {
                "name": "Notes on the Engine",
                "description": "Annotated translation.",
                "outcome": "Still cited.",
                "stack": ["Ink"],
            },
            {"name": "Sketch", "description": "A sketch."},
        ]
    )
    assert (
        "## Projects\n\n"
        "### Notes on the Engine\n"
        "- Annotated translation.\n"
        "- Still cited.\n"
        "*Tech Stack – Ink*\n\n"
        "### Sketch\n"
        "- A sketch.\n"
    ) in text


def test_empty_optional_sections_are_omitted() -> None:
    text = render()
    for heading in ("Skills", "Education", "Certifications", "Awards", "Projects"):
        assert f"## {heading}" not in text


def test_it_ends_with_exactly_one_newline() -> None:
    text = render()
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


# --- the guarantee: it is a resume, and every word of it is the profile's ------------------------
@pytest.mark.parametrize("shape", [ResumeShape(), ResumeShape(max_highlights=1, max_skills=2)])
def test_the_example_profile_renders_a_resume_the_verifier_accepts(shape: ResumeShape) -> None:
    profile = load(EXAMPLE_PROFILE)
    text = render_general_resume(profile, shape)

    document = parse(text)
    assert is_sectioned(document)
    verdict = verify_resume(text, profile)
    assert verdict.ok, verdict


def test_the_example_profile_renders_every_part_of_the_career() -> None:
    text = render_general_resume(load(EXAMPLE_PROFILE))
    assert text.startswith("# Jordan Rivera\nStaff Backend Engineer\n")
    assert "jordan.rivera@email.com | (415) 555-0132 | linkedin.com/in/jordanrivera" in text
    assert "### Northwind Payments – Senior Backend Engineer\nMarch 2021 – Present | Austin" in text
    assert "### Cedar Analytics – Backend Engineer\nJune 2018 – February 2021 | Remote" in text
    assert "### B.S. Computer Science – University of Texas at Austin\nMay 2016 | Austin" in text
    assert "### AWS Certified Solutions Architect – Associate\nAmazon | 2022" in text
    assert "### pgbench-lite\n" in text
    assert "Confirm the exact settlement latency" not in text, "notes are never printed"
