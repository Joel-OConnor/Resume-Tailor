"""The anti-fabrication check.

Half of these tests are named after a way a resume lies, and half after a way a checker cries
wolf. Both halves are load-bearing: a missed fabrication ships a resume that collapses in the
first five minutes of a screen, and a false violation blocks a correct resume and burns a retry.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.match import build_lexicon
from resume_tailor.profile import load_mapping
from resume_tailor.verify import (
    Verdict,
    Violation,
    format_violations,
    supported_metrics,
    verify_resume,
)
from resume_tailor.verify.history import _within
from resume_tailor.verify.source import Area, Kind, scan

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

_TECHNOLOGIES: list[dict[str, Any]] = [
    {
        "group": "Languages",
        "items": [
            {"name": "Python", "years": 8},
            {"name": "Go", "aliases": ["Golang"]},
            {"name": "SQL"},
        ],
    },
    {
        "group": "Cloud & Infra",
        "items": [
            {"name": "AWS", "aliases": ["Amazon Web Services"]},
            {"name": "ECS"},
            {"name": "Lambda"},
            {"name": "RDS"},
            {"name": "Amazon S3", "aliases": ["S3"]},
            {"name": "Kubernetes", "aliases": ["K8s"]},
            {"name": "CI/CD"},
            {"name": "Test-Driven Development", "aliases": ["TDD"]},
            {"name": "OAuth 2.0"},
            {"name": "SOC 2"},
            {"name": "Environments"},
        ],
    },
]


def _mapping(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "contact": {
            "name": "Jordan Rivera",
            "headline": "Senior Backend Engineer",
            "email": "jordan@example.com",
            "phone": "(415) 555-0132",
            "location": "Austin, TX",
            "links": [{"label": "GitHub", "url": "github.com/jrivera"}],
        },
        "summary": "Senior backend engineer with 8 years on payment systems.",
        "target_roles": ["Staff Backend Engineer"],
        "technologies": _TECHNOLOGIES,
        "experience": [
            {
                "id": "northwind",
                "company": "Northwind Payments",
                "location": "Austin, TX",
                "industry": "Payments",
                "summary": "Settlement infrastructure.",
                "roles": [
                    {
                        "title": "Senior Backend Engineer",
                        "start": "2021-03",
                        "end": "present",
                        "scope": "Team of 6.",
                        "stack": ["Go", "Python"],
                        "highlights": [
                            {
                                "label": "Settlement Throughput",
                                "text": (
                                    "Redesigned settlement to process 4M daily transactions, "
                                    "cutting latency 38% (820ms to 510ms)."
                                ),
                                "tags": ["throughput"],
                            },
                            {"label": "Mentorship", "text": "Mentored 4 engineers."},
                        ],
                    },
                    {"title": "Backend Engineer", "start": "2019-01", "end": "2021-02"},
                ],
            },
            {
                "id": "cedar",
                "company": "Cedar Analytics",
                "roles": [
                    {
                        "title": "Backend Engineer",
                        "start": "2016",
                        "end": "2018",
                        "highlights": [{"text": "Cut spend 22% (~$14k/mo) and grew ARR $55.1B."}],
                    }
                ],
            },
        ],
        "education": [
            {
                "credential": "B.S. Computer Science",
                "institution": "University of Texas at Austin",
                "completed": "2016",
                "notes": "GPA 3.9",
            }
        ],
        "certifications": [
            {"name": "AWS Certified Solutions Architect", "issuer": "Amazon", "year": "2022"}
        ],
        "awards": [{"name": "Engineering Excellence Award", "year": "2020"}],
        "projects": [{"name": "Ledgerize", "description": "A ledger.", "stack": ["Go"]}],
        "notes": ["Confirm the 99.98% delivery figure before printing it"],
    }
    return {**data, **overrides}


@pytest.fixture
def profile() -> Profile:
    return load_mapping(_mapping())


CLEAN = """\
# Jordan Rivera
Senior Backend Engineer
jordan@example.com | (415) 555-0132 | Austin, TX | github.com/jrivera

## Summary
Senior backend engineer with 8 years on payment systems.

## Skills
**Languages:** Python, Go, SQL
**Cloud & Infra:** AWS (ECS, Lambda, RDS), Kubernetes, CI/CD
**Practices:** Test-Driven Development

## Experience

### Northwind Payments — Senior Backend Engineer
Austin, TX | Mar 2021 – Present
- **Settlement Throughput:** Redesigned settlement to process 4M+ daily transactions.
- **Latency:** Cut end-to-end latency 38% (820ms → 510ms).
- **Mentorship:** Mentored 4 engineers.

### Cedar Analytics — Backend Engineer
2016 – 2018
- Cut spend 22% (~$14k/mo) and grew ARR $55.1B.

## Education

### B.S. Computer Science
University of Texas at Austin, 2016

## Certifications
- AWS Certified Solutions Architect — Amazon — 2022

## Projects

### Ledgerize
A double-entry ledger written in Go.
"""


def _verify(markdown: str, profile: Profile) -> Verdict:
    return verify_resume(textwrap.dedent(markdown), profile)


def _kinds(verdict: Verdict) -> list[str]:
    return [violation.kind for violation in verdict.violations]


def _texts(verdict: Verdict) -> list[str]:
    return [violation.text for violation in verdict.violations]


# --- the honest resume ------------------------------------------------------------------------
def test_a_resume_built_only_from_the_profile_passes_clean(profile: Profile) -> None:
    verdict = verify_resume(CLEAN, profile)
    assert verdict.ok, format_violations(verdict)
    assert verdict.violations == ()


def test_an_empty_verdict_is_ok_and_formats_to_nothing() -> None:
    assert Verdict().ok
    assert format_violations(Verdict()) == ""


def test_a_verdict_with_a_violation_is_not_ok() -> None:
    verdict = Verdict((Violation("metric", "40%", 3, "why"),))
    assert not verdict.ok
    assert verdict.violations[0].sort_key == (3, "metric", "40%")


# --- employers --------------------------------------------------------------------------------
def test_an_invented_employer_is_caught(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Globex Corporation — Senior Backend Engineer
        Austin, TX | Mar 2021 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["employer"]
    assert _texts(verdict) == ["Globex Corporation"]
    assert "Northwind Payments, Cedar Analytics" in verdict.violations[0].reason


def test_shortening_a_real_employer_is_not_an_invention(profile: Profile) -> None:
    """A resume writing "Northwind" for "Northwind Payments" is abbreviating, not fabricating."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind — Senior Backend Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_the_employer_may_be_written_after_the_title(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Employment History

        ### Senior Backend Engineer — Northwind Payments
        Mar 2021 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_an_entry_naming_only_a_title_is_reported_against_the_whole_heading(
    profile: Profile,
) -> None:
    """With no employer anywhere in the heading, no one part is to blame — so quote it all."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Senior Backend Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["employer"]
    assert _texts(verdict) == ["Senior Backend Engineer"]


# --- titles -----------------------------------------------------------------------------------
def test_an_inflated_title_is_caught(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Staff Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["title"]
    assert _texts(verdict) == ["Staff Engineer"]
    assert "Senior Backend Engineer, Backend Engineer" in verdict.violations[0].reason


def test_dropping_seniority_from_a_real_title_is_allowed(profile: Profile) -> None:
    """Writing "Backend Engineer" for "Senior Backend Engineer" understates; it cannot mislead."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Backend Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_promotion_entry_may_name_both_titles_held(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments | Senior Backend Engineer | Backend Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


# --- dates ------------------------------------------------------------------------------------
def test_a_widened_start_date_is_caught(profile: Profile) -> None:
    """Reference checks read start dates off an HR system, so an early start is a checkable lie."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Austin, TX | Jan 2020 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["Jan 2020 – Present"]
    assert "March 2021 – Present" in verdict.violations[0].reason


def test_a_role_still_running_cannot_be_claimed_for_a_role_that_ended(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Cedar Analytics — Backend Engineer
        2016 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["date"]


def test_a_narrower_range_than_the_profile_records_is_fine(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        06/2021 – 2023-05
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_year_only_range_is_compared_at_year_precision(profile: Profile) -> None:
    """The profile says 2021-03 and the resume says 2021; a resume year does not claim January."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Remote 2021 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_an_entry_with_no_dates_reports_no_date_violation(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Austin, TX
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_an_unmatched_title_still_has_its_dates_checked_against_the_whole_tenure(
    profile: Profile,
) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Staff Engineer
        Jan 2015 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["title", "date"]
    assert "January 2019 – Present" in verdict.violations[1].reason


# --- education --------------------------------------------------------------------------------
def test_an_invented_degree_and_school_are_both_caught(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Education

        ### M.B.A.
        Harvard Business School, 2019
        """,
        profile,
    )
    assert _kinds(verdict) == ["education", "education"]
    assert _texts(verdict) == ["M.B.A.", "Harvard Business School"]


def test_a_real_degree_with_its_year_and_notes_passes(profile: Profile) -> None:
    """The year is a date, not an unsupported phrase — and GPA 3.9 is in the profile's notes."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Education

        ### B.S. Computer Science
        University of Texas at Austin, Austin, TX, 2016, GPA 3.9
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_certification_under_an_education_heading_is_not_a_fabrication(profile: Profile) -> None:
    """Most resumes merge the two under one heading, so both feed the same pool of phrases."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Education & Certifications

        ### AWS Certified Solutions Architect
        Amazon, 2022

        ### Engineering Excellence Award
        2020
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


# --- technologies -----------------------------------------------------------------------------
def test_a_skill_the_profile_never_records_is_caught(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Languages:** Python, Rust, Go
        """,
        profile,
    )
    assert _kinds(verdict) == ["technology"]
    assert _texts(verdict) == ["Rust"]


def test_an_alias_a_stem_and_a_recased_form_all_count_as_known(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Technical Skills
        **Languages:** Golang, python
        **Practices:** Environment, TDD
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_service_smuggled_into_a_parenthesis_is_still_checked(profile: Profile) -> None:
    """A service listed inside a parenthesis is claimed as loudly as a separate item is."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Cloud:** AWS (ECS, Redshift), Kubernetes
        """,
        profile,
    )
    assert _texts(verdict) == ["Redshift"]


def test_a_slash_joined_name_is_tried_whole_before_it_is_split(profile: Profile) -> None:
    """CI/CD is one technology; Python/Rust is two claims, one of which is untrue."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Practices:** CI/CD, Python/Go, Python/Rust
        """,
        profile,
    )
    assert _texts(verdict) == ["Python/Rust"]


def test_skills_may_be_written_as_bullets_or_with_stray_punctuation(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        - Python; Go, +
        - AWS (ECS
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_ordinary_prose_outside_the_skills_section_is_never_read_as_a_technology(
    profile: Profile,
) -> None:
    """Bullets are full of words a technology matcher would happily mistake for products."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Summary
        Pragmatic engineer who values clarity, ownership and momentum.

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Partnered with Product, Design and Compliance on the settlement rewrite.
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_prose_line_inside_the_skills_section_is_left_alone(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        Comfortable across the stack and happy in ambiguity.
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


# --- metrics ----------------------------------------------------------------------------------
def test_an_invented_percentage_is_caught_and_quoted_with_its_word(profile: Profile) -> None:
    """The invented "40% faster" is the failure this whole module exists to stop."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Made the settlement pipeline 40% faster.
        """,
        profile,
    )
    assert _kinds(verdict) == ["metric"]
    assert _texts(verdict) == ["40% faster"]
    assert format_violations(verdict) == (
        "1. line 7: '40% faster' does not appear anywhere in the profile; remove it or replace "
        "it with a figure the profile states"
    )


def test_the_same_invented_figure_twice_on_one_line_is_reported_once(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Improved 44%, then improved 44%.
        """,
        profile,
    )
    assert _texts(verdict) == ["44%"]


@pytest.mark.parametrize(
    "bullet",
    [
        "Grew revenue to $55.1B across the book.",
        "Grew revenue to 55.1B across the book.",
        "Cut spend 22% on infrastructure.",
        "Cut spend 22 points on infrastructure.",
        "Processed 4M+ transactions a day.",
        "Processed 4,000,000 transactions a day.",
        "Cut latency 38% from 820ms to 510ms.",
        "Saved ~$14k a month.",
        "Saved $14,000 a month.",
        "Mentored 4 engineers.",
    ],
)
def test_a_figure_the_profile_states_survives_every_way_of_writing_it(
    profile: Profile, bullet: str
) -> None:
    """A currency symbol, a comma, a plus and a magnitude suffix never change the claim."""
    verdict = _verify(
        f"""\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - {bullet}
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_number_inside_a_technology_name_is_not_a_metric(profile: Profile) -> None:
    """S3, K8s, OAuth 2.0, SOC 2 and Python 3 are names; none of them claims an outcome."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Ran Python 3 services on K8s with S3 storage, OAuth 2.0 auth and SOC 2 controls.
        - Shipped an ES6 client against an x86 fleet.
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_version_number_after_a_product_name_is_not_a_metric(profile: Profile) -> None:
    """The profile has no Java, but "Java 17" is still a version and not a claimed result."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Migrated the fleet to Java 17 and PCI DSS 3.2 scope.
        - Upgraded every service to python 3.12 in one quarter.
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_quantity_after_a_product_name_is_still_a_metric(profile: Profile) -> None:
    """A currency symbol, a percent sign or a magnitude suffix is never part of a version."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Cut Kubernetes spend $900k and Lambda cold starts 71%.
        """,
        profile,
    )
    assert _texts(verdict) == ["$900k", "71%"]


def test_the_dates_line_is_not_read_a_second_time_as_a_metric(profile: Profile) -> None:
    """Nothing on a dates line is an outcome, and the date check has already vouched for it."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Austin, TX 78701 | 2021-03 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_list_marker_is_not_a_claimed_figure(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Summary
        7. Led the settlement rewrite.
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_the_contact_line_is_supported_by_the_profile_contact_details(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera
        jordan@example.com | (415) 555-0132 | Austin, TX | github.com/jrivera
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_figure_that_lives_only_in_the_profile_notes_is_not_supported(profile: Profile) -> None:
    """CLAUDE.md calls notes unconfirmed, so a note's number is exactly what must not be printed."""
    assert "9998" not in supported_metrics(load_mapping(_mapping()))
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Delivered 99.98% of events on time.
        """,
        profile,
    )
    assert _kinds(verdict) == ["metric"]


def test_supported_metrics_normalises_every_figure_the_profile_states(profile: Profile) -> None:
    supported = supported_metrics(profile)
    assert {"55100000000", "14000", "4000000", "38", "22", "820", "510", "8"} <= supported
    assert "0" not in supported


def test_supported_metrics_reads_projects_and_credentials() -> None:
    extra = load_mapping(
        _mapping(
            projects=[
                {
                    "name": "Ledgerize",
                    "description": "Ledger used by 12 teams.",
                    "stack": ["Go 2"],
                    "outcome": "700 stars",
                }
            ],
            certifications=[{"name": "CKA 2024", "issuer": "CNCF", "notes": "id 4471"}],
        )
    )
    assert {"12", "700", "4471", "2024"} <= supported_metrics(extra)


# --- the scanner ------------------------------------------------------------------------------
def test_a_stripped_comment_does_not_shift_the_lines_below_it(profile: Profile) -> None:
    """Comments are blanked rather than deleted; a shifted line number is an unfixable report."""
    verdict = _verify(
        """\
        <!--
          the resume format contract, several lines long
        -->
        # Jordan Rivera

        ## Skills
        **Languages:** Rust
        """,
        profile,
    )
    assert verdict.violations[0].line == 7


def test_the_scanner_classifies_every_line_kind_and_section() -> None:
    source = scan(
        "# Jordan Rivera\nAustin, TX\n\n## Skills\n**Languages:** Go\n\n"
        "## Experience\n\n---\n### Acme — Engineer\n2020 – 2021\n- Did work.\n\n"
        "## Certifications\n- AWS\n"
    )
    assert [(line.number, line.kind) for line in source.lines] == [
        (1, Kind.PROSE),
        (2, Kind.PROSE),
        (4, Kind.HEADING),
        (5, Kind.SKILL),
        (7, Kind.HEADING),
        (10, Kind.ENTRY),
        (11, Kind.META),
        (12, Kind.BULLET),
        (14, Kind.HEADING),
        (15, Kind.BULLET),
    ]
    assert [line.area for line in source.lines[:3]] == [Area.HEADER, Area.HEADER, Area.SKILLS]
    assert source.lines[-1].area is Area.OTHER
    assert source.entries[0] == source.entries[0].__class__(
        area=Area.EXPERIENCE, title="Acme — Engineer", line=10, meta="2020 – 2021", meta_line=11
    )


def test_an_empty_claim_never_counts_as_contained() -> None:
    """An empty word tuple is a slice of every phrase, so it would match every employer alive."""
    assert not _within((), ("acme", "corp"))
    assert not _within(("acme", "corp", "limited"), ("acme", "corp"))
    assert _within(("acme",), ("acme", "corp"))


def test_a_lexicon_is_built_from_the_profile_alone(profile: Profile) -> None:
    """Guards the contract the technology check leans on: no vocabulary beyond the profile."""
    assert ("rust",) not in build_lexicon(profile).by_tokens


def test_a_promotion_matches_the_exact_title_not_the_longer_one() -> None:
    """Progressive titles overlap: "Software Engineer" sits inside "Lead Software Engineer"."""
    profile = load_mapping(
        {
            "contact": {"name": "Ada", "headline": "E", "email": "a@b.c"},
            "summary": "s",
            "experience": [
                {
                    "id": "charter",
                    "company": "Charter Communications",
                    "roles": [
                        {"title": "Lead Software Engineer", "start": "2022-06", "end": "present"},
                        {"title": "Senior Software Engineer", "start": "2021-06", "end": "2022-06"},
                        {"title": "Software Engineer", "start": "2020-03", "end": "2021-06"},
                    ],
                }
            ],
        }
    )
    resume = (
        "# Ada\n\n## Experience\n\n"
        "### Charter Communications — Software Engineer\nMarch 2020 – June 2021\n"
    )
    assert verify_resume(resume, profile).ok
