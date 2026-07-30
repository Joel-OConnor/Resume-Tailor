"""Profile loading and validation."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.errors import ProfileError
from resume_tailor.profile import loader
from resume_tailor.profile.models import Profile

if TYPE_CHECKING:
    from pathlib import Path

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


def _with(**overrides: Any) -> dict[str, Any]:
    return {**MINIMAL, **overrides}


def _expect(data: object, path: str, message: str) -> None:
    with pytest.raises(ProfileError) as caught:
        loader.load_mapping(data)
    assert caught.value.path == path
    assert message in str(caught.value)


# --- happy path -----------------------------------------------------------------------------------
def test_minimal_profile_loads() -> None:
    profile = loader.load_mapping(MINIMAL)
    assert isinstance(profile, Profile)
    assert profile.contact.name == "Ada"
    assert profile.schema_version == 1
    assert profile.experience[0].roles[0].end == "present"


def test_defaults_fill_in_absent_optional_fields() -> None:
    profile = loader.load_mapping(MINIMAL)
    assert profile.technologies == ()
    assert profile.contact.links == ()
    assert profile.contact.location == ""


def test_the_shipped_example_is_valid() -> None:
    from tests.conftest import REPO_ROOT

    profile = loader.load(REPO_ROOT / "templates" / "master-profile.example.yaml")
    assert profile.contact.name == "Jordan Rivera"
    assert profile.tenure_ids() == {"northwind-payments", "cedar-analytics"}


def test_technology_names_include_aliases() -> None:
    profile = loader.load_mapping(
        _with(
            technologies=[{"group": "Data", "items": [{"name": "Kubernetes", "aliases": ["K8s"]}]}]
        )
    )
    assert profile.technology_names() == ("Kubernetes", "K8s")


def test_text_is_stripped() -> None:
    profile = loader.load_mapping(_with(summary="  spaced  "))
    assert profile.summary == "spaced"


def test_years_accepts_an_integer() -> None:
    profile = loader.load_mapping(
        _with(technologies=[{"group": "G", "items": [{"name": "Go", "years": 4}]}])
    )
    assert profile.technologies[0].items[0].years == 4.0


# --- file and YAML errors -------------------------------------------------------------------------
def test_a_missing_file_reports_the_path(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="cannot read"):
        loader.load(tmp_path / "nope.yaml")


def test_broken_yaml_is_reported() -> None:
    with pytest.raises(ProfileError, match="invalid YAML"):
        loader.loads("a:\n  - b\n c: d\n")


def test_an_empty_file_is_reported() -> None:
    with pytest.raises(ProfileError, match="the profile is empty"):
        loader.loads("# just a comment\n")


def test_loads_parses_yaml_source() -> None:
    source = textwrap.dedent("""\
        contact: {name: Ada, headline: Engineer, email: a@b.c}
        summary: s
        experience:
          - id: e
            company: E
            roles: [{title: T, start: '2020', end: '2021'}]
    """)
    assert loader.loads(source).contact.name == "Ada"


# --- structural validation ------------------------------------------------------------------------
def test_a_non_mapping_root_is_reported() -> None:
    _expect([1, 2], "<root>", "expected a mapping, got list")


def test_a_non_mapping_nested_value_is_reported() -> None:
    _expect(_with(contact="Ada"), "contact", "expected a mapping, got str")


def test_an_unknown_key_is_reported() -> None:
    _expect(_with(nickname="A"), "nickname", "unknown key 'nickname'")


def test_an_unknown_nested_key_is_reported() -> None:
    data = {**MINIMAL, "contact": {**MINIMAL["contact"], "fax": "1"}}
    _expect(data, "contact.fax", "unknown key")


def test_a_missing_required_key_is_reported() -> None:
    _expect({"summary": "s", "experience": MINIMAL["experience"]}, "contact", "required key")


def test_a_missing_nested_required_key_is_reported() -> None:
    _expect(
        {**MINIMAL, "contact": {"name": "Ada", "headline": "E"}},
        "contact.email",
        "required key",
    )


def test_a_scalar_where_a_list_belongs_is_reported() -> None:
    _expect(_with(target_roles="Engineer"), "target_roles", "expected a list, got str")


def test_a_bad_list_item_reports_its_index() -> None:
    _expect(_with(target_roles=["ok", ["nested"]]), "target_roles[1]", "expected text, got list")


def test_a_bad_deeply_nested_value_reports_the_full_path() -> None:
    data = _with(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [
                    {"title": "T", "start": "2020", "end": "2021"},
                    {"title": ["nope"], "start": "2020", "end": "2021"},
                ],
            }
        ]
    )
    _expect(data, "experience[0].roles[1].title", "expected text")


@pytest.mark.parametrize("value", [True, None, {"a": 1}])
def test_non_text_values_are_rejected(value: object) -> None:
    _expect(_with(summary=value), "summary", "expected text")


def test_a_non_integer_schema_version_is_rejected() -> None:
    _expect(_with(schema_version="1"), "schema_version", "expected a whole number")


def test_a_boolean_is_not_an_integer() -> None:
    _expect(_with(schema_version=True), "schema_version", "expected a whole number")


def test_a_non_numeric_years_value_is_rejected() -> None:
    _expect(
        _with(technologies=[{"group": "G", "items": [{"name": "Go", "years": "four"}]}]),
        "technologies[0].items[0].years",
        "expected a number",
    )


# --- semantic validation --------------------------------------------------------------------------
def test_an_unsupported_schema_version_is_rejected() -> None:
    _expect(_with(schema_version=2), "schema_version", "unsupported schema_version 2")


@pytest.mark.parametrize(
    ("field", "path"),
    [("name", "contact.name"), ("email", "contact.email")],
)
def test_required_contact_fields_must_not_be_blank(field: str, path: str) -> None:
    _expect({**MINIMAL, "contact": {**MINIMAL["contact"], field: "  "}}, path, "must not be empty")


def test_a_blank_summary_is_rejected() -> None:
    _expect(_with(summary=" "), "summary", "must not be empty")


def test_at_least_one_employer_is_required() -> None:
    _expect(_with(experience=[]), "experience", "at least one employer")


def test_at_least_one_role_is_required() -> None:
    _expect(
        _with(experience=[{"id": "e", "company": "E", "roles": []}]),
        "experience[0].roles",
        "at least one role",
    )


def test_a_blank_company_is_rejected() -> None:
    _expect(
        _with(experience=[{"id": "e", "company": "", "roles": MINIMAL["experience"][0]["roles"]}]),
        "experience[0].company",
        "must not be empty",
    )


def test_a_blank_role_title_is_rejected() -> None:
    _expect(
        _with(
            experience=[
                {
                    "id": "e",
                    "company": "E",
                    "roles": [{"title": "", "start": "2020", "end": "2021"}],
                }
            ]
        ),
        "experience[0].roles[0].title",
        "must not be empty",
    )


@pytest.mark.parametrize("bad", ["Acme Corp", "acme_corp", "-acme", "acme-", "Acme"])
def test_employer_ids_must_be_slugs(bad: str) -> None:
    data = _with(experience=[{**MINIMAL["experience"][0], "id": bad}])
    _expect(data, "experience[0].id", "lowercase slug")


def test_duplicate_employer_ids_are_rejected() -> None:
    data = _with(experience=[MINIMAL["experience"][0], MINIMAL["experience"][0]])
    _expect(data, "experience[1].id", "duplicate employer id")


@pytest.mark.parametrize("bad", ["Jan 2020", "2020-13", "2020-00", "20-01", "2020-1"])
def test_bad_start_dates_are_rejected(bad: str) -> None:
    data = _with(
        experience=[
            {"id": "e", "company": "E", "roles": [{"title": "T", "start": bad, "end": "2021"}]}
        ]
    )
    _expect(data, "experience[0].roles[0].start", "expected YYYY or YYYY-MM")


def test_present_is_only_allowed_for_an_end_date() -> None:
    data = _with(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [{"title": "T", "start": "present", "end": "2021"}],
            }
        ]
    )
    _expect(data, "experience[0].roles[0].start", "expected YYYY or YYYY-MM")


def test_a_blank_end_date_is_rejected() -> None:
    data = _with(
        experience=[
            {"id": "e", "company": "E", "roles": [{"title": "T", "start": "2020", "end": ""}]}
        ]
    )
    _expect(data, "experience[0].roles[0].end", "a date or 'present' is required")


def test_an_end_before_the_start_is_rejected() -> None:
    data = _with(
        experience=[
            {"id": "e", "company": "E", "roles": [{"title": "T", "start": "2021", "end": "2020"}]}
        ]
    )
    _expect(data, "experience[0].roles[0].end", "is before start")


@pytest.mark.parametrize(
    ("start", "end"),
    [("2020", "2020"), ("2020-01", "2020"), ("2020", "2020-01"), ("2020-01", "2020-12")],
)
def test_year_only_dates_widen_to_the_whole_year(start: str, end: str) -> None:
    data = _with(
        experience=[
            {"id": "e", "company": "E", "roles": [{"title": "T", "start": start, "end": end}]}
        ]
    )
    assert loader.load_mapping(data).experience[0].roles[0].end == end


def test_a_blank_highlight_is_rejected() -> None:
    data = _with(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [
                    {
                        "title": "T",
                        "start": "2020",
                        "end": "2021",
                        "highlights": [{"text": "ok"}, {"text": " "}],
                    }
                ],
            }
        ]
    )
    _expect(data, "experience[0].roles[0].highlights[1].text", "must not be empty")


def test_an_unknown_technology_level_is_rejected() -> None:
    _expect(
        _with(technologies=[{"group": "G", "items": [{"name": "Go", "level": "guru"}]}]),
        "technologies[0].items[0].level",
        "level must be one of",
    )


@pytest.mark.parametrize("level", loader.LEVELS)
def test_every_documented_level_is_accepted(level: str) -> None:
    data = _with(technologies=[{"group": "G", "items": [{"name": "Go", "level": level}]}])
    assert loader.load_mapping(data).technologies[0].items[0].level == level


def test_negative_years_are_rejected() -> None:
    _expect(
        _with(technologies=[{"group": "G", "items": [{"name": "Go", "years": -1}]}]),
        "technologies[0].items[0].years",
        "cannot be negative",
    )


def test_a_blank_technology_group_is_rejected() -> None:
    _expect(_with(technologies=[{"group": " ", "items": []}]), "technologies[0].group", "empty")


def test_a_blank_technology_name_is_rejected() -> None:
    _expect(
        _with(technologies=[{"group": "G", "items": [{"name": ""}]}]),
        "technologies[0].items[0].name",
        "must not be empty",
    )


def test_used_at_must_reference_a_real_employer() -> None:
    _expect(
        _with(technologies=[{"group": "G", "items": [{"name": "Go", "used_at": ["ghost"]}]}]),
        "technologies[0].items[0].used_at[0]",
        "unknown employer id 'ghost'",
    )


def test_used_at_accepts_a_real_employer() -> None:
    data = _with(
        technologies=[{"group": "G", "items": [{"name": "Go", "used_at": ["analytical-engine"]}]}]
    )
    assert loader.load_mapping(data).technologies[0].items[0].used_at == ("analytical-engine",)


@pytest.mark.parametrize("field", ["credential", "institution"])
def test_education_requires_its_core_fields(field: str) -> None:
    entry = {"credential": "BSc", "institution": "X", field: ""}
    _expect(_with(education=[entry]), f"education[0].{field}", "must not be empty")


def test_a_bad_education_date_is_rejected() -> None:
    _expect(
        _with(education=[{"credential": "BSc", "institution": "X", "completed": "spring 2016"}]),
        "education[0].completed",
        "expected YYYY or YYYY-MM",
    )


def test_an_absent_education_date_is_allowed() -> None:
    profile = loader.load_mapping(_with(education=[{"credential": "BSc", "institution": "X"}]))
    assert profile.education[0].completed == ""


@pytest.mark.parametrize("section", ["certifications", "awards"])
def test_a_bad_credential_year_is_rejected(section: str) -> None:
    _expect(
        _with(**{section: [{"name": "N", "year": "twenty-twenty"}]}),
        f"{section}[0].year",
        "expected a 4-digit year",
    )


@pytest.mark.parametrize("section", ["certifications", "awards"])
def test_a_good_credential_year_is_accepted(section: str) -> None:
    profile = loader.load_mapping(_with(**{section: [{"name": "N", "year": "2020"}]}))
    assert getattr(profile, section)[0].year == "2020"


def test_a_yaml_integer_is_rejected_with_a_hint() -> None:
    """The generated schema says "string"; silently coercing an int would make it a lie."""
    _expect(
        _with(education=[{"credential": "BSc", "institution": "X", "completed": 2016}]),
        "education[0].completed",
        "expected text, got int — quote it",
    )


def test_a_non_ascii_digit_is_not_a_date() -> None:
    r"""`\d` matches Devanagari digits; the date would then break ordering and rendering."""
    data = _with(
        experience=[
            {
                "id": "e",
                "company": "E",
                "roles": [{"title": "T", "start": "२०२०", "end": "2021"}],
            }
        ]
    )
    _expect(data, "experience[0].roles[0].start", "expected YYYY or YYYY-MM")


def test_a_non_ascii_digit_is_not_a_credential_year() -> None:
    _expect(
        _with(certifications=[{"name": "N", "year": "٢٠٢٢"}]),
        "certifications[0].year",
        "expected a 4-digit year",
    )
