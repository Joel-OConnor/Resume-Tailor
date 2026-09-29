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


def test_an_invented_employer_under_an_employment_heading_is_caught(profile: Profile) -> None:
    """An "Employment History" heading is the experience section by another name, so it counts."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Employment History

        ### Globex — Senior Backend Engineer
        Mar 2021 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["employer"]
    assert _texts(verdict) == ["Globex"]


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


def test_a_promotion_entry_may_print_the_span_of_both_titles(profile: Profile) -> None:
    """Jan 2019 – Present is exactly Backend Engineer's start to Senior Backend Engineer's end."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments | Senior Backend Engineer | Backend Engineer
        Jan 2019 – Present
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_promotion_entry_may_not_start_before_its_earliest_role(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments | Senior Backend Engineer | Backend Engineer
        Jan 2018 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["Jan 2018 – Present"]
    assert (
        "Senior Backend Engineer and Backend Engineer at Northwind Payments as "
        "January 2019 – Present"
    ) in verdict.violations[0].reason


def _returned() -> Profile:
    """Northwind, left in mid-2015 and rejoined in 2019; Cedar, year-only roles back to back."""
    data = _mapping()
    data["experience"][0]["roles"].append(
        {"title": "Associate Engineer", "start": "2014-01", "end": "2015-06"}
    )
    data["experience"][1]["roles"].append(
        {"title": "Data Engineer", "start": "2014", "end": "2015"}
    )
    return load_mapping(data)


@pytest.mark.parametrize(
    "entry",
    [
        "### Northwind Payments | Senior Backend Engineer | Associate Engineer\nJan 2014 – Present",
        "### Northwind Payments\nJan 2014 – Present",
    ],
)
def test_one_range_may_not_run_across_the_years_between_two_stints(entry: str) -> None:
    """Rejoining an employer is two stretches; one range over both claims the years away."""
    verdict = verify_resume(f"# Jordan Rivera\n\n## Experience\n\n{entry}\n", _returned())
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["Jan 2014 – Present"]
    reason = verdict.violations[0].reason
    assert "Associate Engineer at Northwind Payments as January 2014 – June 2015" in reason
    assert "one of those ranges" in reason


@pytest.mark.parametrize(
    "entry",
    [
        "### Northwind Payments — Associate Engineer\nJan 2014 – Jun 2015",
        "### Northwind Payments\nJan 2019 – Present",
        "### Northwind Payments | Senior Backend Engineer | Backend Engineer\nJan 2019 – Present",
        "### Cedar Analytics | Backend Engineer | Data Engineer\n2014 – 2018",
    ],
)
def test_each_unbroken_stretch_may_print_its_own_range(entry: str) -> None:
    """A role, a promotion, or year-only roles a year apart each print as one range."""
    verdict = verify_resume(f"# Jordan Rivera\n\n## Experience\n\n{entry}\n", _returned())
    assert verdict.ok, format_violations(verdict)


def test_a_role_ending_in_december_runs_into_one_starting_in_january() -> None:
    data = _mapping()
    data["experience"][0]["roles"].append(
        {"title": "Associate Engineer", "start": "2017-06", "end": "2018-12"}
    )
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Experience\n\n### Northwind Payments\nJun 2017 – Present\n",
        load_mapping(data),
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


@pytest.mark.parametrize("dates", ["Feb 2021 – Present", "02/2021 – Present", "2021-02 – Present"])
def test_a_start_one_month_early_is_caught_in_every_date_format(
    profile: Profile, dates: str
) -> None:
    """A numeric date keeps its month, so 02/2021 is as early as Feb 2021 for a 2021-03 start."""
    verdict = _verify(
        f"""\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Austin, TX | {dates}
        """,
        profile,
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == [dates]


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
    assert [v.text for v in verdict.violations if v.kind == "education"] == [
        "M.B.A.",
        "Harvard Business School",
    ]
    assert [v.text for v in verdict.violations if v.kind == "date"] == ["2019"]
    assert "any degree, certification or award" in verdict.violations[1].reason


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


@pytest.mark.parametrize(
    "section",
    [
        "## Certifications\n- Certified Kubernetes Administrator (CKA) — CNCF",
        "## Certifications\n\n### Google Professional Cloud Architect\nGoogle",
        "## Licenses & Certifications\n\n### **Google Professional Cloud Architect** – Google",
        "## Honors & Awards\n- Staff Engineer of the Year — Globex",
        "## Certifications\n**Cloud:** AWS Certified Solutions Architect, Google Cloud Architect",
        "## Credentials\n- Certified Kubernetes Administrator (CKA) — CNCF — 2023",
        "## Professional Development\n- Certified Kubernetes Administrator (CKA) — CNCF — 2023",
        "## Certifications\nCertified Kubernetes Administrator (CKA) — CNCF — 2023",
        "## Certifications\n**Google Professional Cloud Architect:** 2022",
        "## Education\n**M.S. Computer Science:** University of Texas at Austin, 2016",
    ],
)
def test_an_invented_certification_in_its_own_section_is_caught(
    profile: Profile, section: str
) -> None:
    """The prompts put credentials under their own heading, so that heading has to be checked.

    The invented name is always reported; a year printed for it is one no record has, too.
    """
    verdict = verify_resume(f"# Jordan Rivera\n\n{section}\n", profile)
    assert "education" in _kinds(verdict)
    assert set(_kinds(verdict)) <= {"education", "date"}


@pytest.mark.parametrize(
    "entry",
    [
        "### B.S. Computer Science\nUniversity of Texas at Austin, 2012",
        "### **B.S. Computer Science** – University of Texas at Austin\nAustin, TX | 2013",
    ],
)
def test_a_graduation_year_the_profile_does_not_record_is_caught(
    profile: Profile, entry: str
) -> None:
    """The profile records the degree as completed in 2016; any other year is a checkable lie."""
    verdict = verify_resume(f"# Jordan Rivera\n\n## Education\n\n{entry}\n", profile)
    assert _kinds(verdict)
    assert set(_kinds(verdict)) <= {"date", "education"}


@pytest.mark.parametrize(
    "section",
    [
        "## Licenses & Certifications\n\n### **AWS Certified Solutions Architect** – Amazon\n2022",
        "## Certifications\n- Amazon AWS Certified Solutions Architect, 2022",
        "## Certifications\n- **AWS Certified Solutions Architect**, Amazon: 2022",
        "## Honors & Awards\n- Engineering Excellence Award — 2020",
        "## Honours\n- Engineering Excellence Award",
        "## Certifications\n- AWS Certified Solutions Architect (Amazon, 2022)",
        "## Certifications\n- AWS Certified Solutions Architect (Amazon), 2022",
        "## Education\n- B.S. Computer Science (University of Texas at Austin), 2016",
        "## Honors & Awards\n- Winner — Engineering Excellence Award, 2020",
        "## Honors & Awards\n- Recipient, Engineering Excellence Award, 2020",
        "## Licenses & Certifications\n\n### AWS Certified Solutions Architect\nIssued 2022",
        "## Certifications\n- Solutions Architect, AWS Certified, 2022",
        "## Certifications\nAWS Certified Solutions Architect — Amazon — 2022",
        "## Certifications\n1. AWS Certified Solutions Architect — Amazon — 2022",
        "## Credentials\n- AWS Certified Solutions Architect — Amazon — 2022",
        "## Certifications\n**Cloud:** AWS Certified Solutions Architect, 2022",
        "## Certifications\n**AWS Certified Solutions Architect:** Amazon, 2022",
        "## Education\n**B.S. Computer Science:** University of Texas at Austin, 2016",
    ],
)
def test_a_real_credential_in_its_own_section_passes(profile: Profile, section: str) -> None:
    """However the line is punctuated, a credential the profile records is the profile's record.

    The issuer may lead the name, follow a colon or sit in parentheses; the year may sit with it;
    a word like "Issued" or "Winner" says how it was come by; a short name may reorder its words;
    and a ``**Label:**`` before a named credential is a category, not a claim.
    """
    verdict = verify_resume(f"# Jordan Rivera\n\n{section}\n", profile)
    assert verdict.ok, format_violations(verdict)


_GRADES = [
    {
        "name": "Grade 4 (Coastal Pilot)",
        "issuer": "Harbor Pilots Guild",
        "notes": "Lapsed; 2011-2013.",
    },
    {
        "name": "Grade 9 (Deep Water Pilot)",
        "issuer": "Harbor Pilots Guild",
        "notes": "Lapsed; 2011-2013.",
    },
]


@pytest.mark.parametrize(
    ("line", "invented"),
    [
        ("- Harbor Pilots Guild Grade 4 and Grade 9 (lapsed, 2011 – 2013)", []),
        ("- Harbor Pilots Guild Grade 4 & 9, lapsed", []),
        ("- Grade 4 and 9 (Harbor Pilots Guild), 2011 – 2013", []),
        ("- Harbor Pilots Guild Grade 4 and Grade 7", ["Harbor Pilots Guild Grade 4 and Grade 7"]),
        ("- Grade 4 & Master Pilot (Harbor Pilots Guild)", ["Grade 4 & Master Pilot"]),
    ],
)
def test_credentials_joined_by_and_are_each_held_to_the_record(
    line: str, invented: list[str]
) -> None:
    """Listing "Grade 4 and 9" names two records, as a comma would; each must be recorded."""
    profile = load_mapping(_mapping(certifications=_GRADES))
    verdict = verify_resume(f"# Jordan Rivera\n\n## Certifications\n{line}\n", profile)
    assert _texts(verdict) == invented, format_violations(verdict)


def test_a_degree_joined_to_an_invented_field_by_and_is_caught(profile: Profile) -> None:
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Education\n- B.S. Computer Science and Economics, 2016\n", profile
    )
    assert _texts(verdict) == ["B.S. Computer Science and Economics"]


@pytest.mark.parametrize(
    ("heading", "area"),
    [
        ("Licenses & Certifications", Area.EDUCATION),
        ("Honors & Awards", Area.EDUCATION),
        ("Honours", Area.EDUCATION),
        ("Credentials", Area.EDUCATION),
        ("Accreditations", Area.EDUCATION),
        ("Professional Development", Area.EDUCATION),
        ("Projects", Area.OTHER),
        ("Projects & Awards", Area.OTHER),
    ],
)
def test_a_credentials_heading_is_read_as_education(heading: str, area: Area) -> None:
    """A section that mixes in projects is left alone: a project could never match a credential."""
    assert scan(f"## {heading}\n- item\n").lines[-1].area is area


@pytest.mark.parametrize(
    ("section", "flagged"),
    [
        ("## Certifications\n**2013:** AWS Certified Solutions Architect", ("date", "2013")),
        ("## Certifications\n- AWS Certified Solutions Architect (Amazon, 2013)", ("date", "2013")),
        ("## Certifications\n- 2013: AWS Certified Solutions Architect, Amazon", ("date", "2013")),
        ("## Education\n- B.S. Computer Science (Honors)", ("education", "Honors")),
    ],
)
def test_a_label_or_a_parenthesis_hides_nothing(
    profile: Profile, section: str, flagged: tuple[str, str]
) -> None:
    """A year in a bold label is still a year, and "(Honors)" standing alone is still a claim."""
    verdict = verify_resume(f"# Jordan Rivera\n\n{section}\n", profile)
    assert [(v.kind, v.text) for v in verdict.violations] == [flagged]


def test_a_wrong_year_on_a_listed_certification_is_one_date_violation(profile: Profile) -> None:
    """History owns the dates in a credentials list, so a year is not reported again as a metric."""
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Certifications\n"
        "- AWS Certified Solutions Architect — Amazon — 2013\n",
        profile,
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["2013"]
    assert "it has 2022" in verdict.violations[0].reason


@pytest.mark.parametrize(
    ("dates", "wrong"),
    [
        ("May 2016", []),
        ("2016", []),
        ("Dec 2016", ["Dec 2016"]),
        ("Aug 2012 – May 2016", ["Aug 2012"]),
    ],
)
def test_a_graduation_date_is_compared_at_the_precision_both_sides_state(
    dates: str, wrong: list[str]
) -> None:
    """A month is checked only when both sides state one; a start year is not what was completed."""
    data = _mapping()
    data["education"][0]["completed"] = "2016-05"
    verdict = verify_resume(
        f"# Jordan Rivera\n\n## Education\n\n### B.S. Computer Science\n{dates}\n",
        load_mapping(data),
    )
    assert _texts(verdict) == wrong
    assert set(_kinds(verdict)) <= {"date"}


def test_a_year_for_a_credential_the_profile_leaves_undated_is_caught() -> None:
    profile = load_mapping(_mapping(awards=[{"name": "Engineering Excellence Award"}]))
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Honors & Awards\n- Engineering Excellence Award, 2020\n", profile
    )
    assert _kinds(verdict) == ["date"]
    assert "print no date for it" in verdict.violations[0].reason


@pytest.mark.parametrize(
    "school", ["University of Texas at Austin", "Georgia Institute of Technology"]
)
def test_a_second_degree_is_held_to_its_own_year(school: str) -> None:
    """The credential outranks a school, so the M.S. cannot borrow the B.S. year."""
    ut = "University of Texas at Austin"
    data = _mapping()
    data["education"].insert(
        0, {"credential": "M.S. Computer Science", "institution": school, "completed": "2018"}
    )
    profile = load_mapping(data)

    def dates_flagged(markdown: str) -> list[str]:
        verdict = verify_resume(f"# Jordan Rivera\n\n## Education\n\n{markdown}\n", profile)
        assert set(_kinds(verdict)) <= {"date"}, format_violations(verdict)
        return _texts(verdict)

    assert dates_flagged(f"### M.S. Computer Science\n{ut}, 2016") == ["2016"]
    assert dates_flagged(f"### M.S. Computer Science\n{school}, 2018") == []
    assert dates_flagged("- Computer Science, 2016") == [], "the field alone could be either"
    verdict = verify_resume("# J\n\n## Education\n- Computer Science, 2012\n", profile)
    assert "M.S. Computer Science or B.S. Computer Science" in verdict.violations[0].reason
    assert "it has 2018 or 2016" in verdict.violations[0].reason


def _honors() -> Profile:
    data = _mapping()
    data["education"][0]["notes"] = (
        "Magna cum laude; GPA 3.9; Dean's list; Relevant coursework: Distributed Systems"
    )
    return load_mapping(data)


_DEGREE = "## Education\n\n### B.S. Computer Science\nUniversity of Texas at Austin, 2016\n"


@pytest.mark.parametrize(
    "detail",
    [
        "- 3.9 GPA",
        "- GPA: 3.9",
        "- Honors: Magna Cum Laude",
        "- Graduated magna cum laude",
        "**Honors:** Magna Cum Laude",
        "- Relevant coursework: Distributed Systems",
        "- Tech Stack: Python, SQL",
    ],
)
def test_a_detail_the_profile_records_passes_however_it_is_introduced(detail: str) -> None:
    """A label or a word like "Graduated" frames a recorded fact; it does not invent one."""
    verdict = verify_resume(f"# Jordan Rivera\n\n{_DEGREE}{detail}\n", _honors())
    assert verdict.ok, format_violations(verdict)


@pytest.mark.parametrize(
    ("detail", "flagged"),
    [
        ("- Summa Cum Laude", [("education", "Summa Cum Laude")]),
        ("- Honors: Summa Cum Laude", [("education", "Summa Cum Laude")]),
        ("- Phi Beta Kappa", [("education", "Phi Beta Kappa")]),
        ("**Honors:** Phi Beta Kappa", [("education", "Phi Beta Kappa")]),
        ("- Dean's List, 2014", [("date", "2014")]),
        ("- Tech Stack: Python, Rust", [("technology", "Rust")]),
    ],
)
def test_an_honor_the_profile_does_not_record_is_caught_under_its_degree(
    detail: str, flagged: list[tuple[str, str]]
) -> None:
    """An invented honor goes exactly where a real one would, under the degree it decorates."""
    verdict = verify_resume(f"# Jordan Rivera\n\n{_DEGREE}{detail}\n", _honors())
    assert [(v.kind, v.text) for v in verdict.violations] == flagged


def test_a_plain_line_under_a_credential_describes_it_and_only_its_dates_are_checked() -> None:
    """A description may paraphrase freely, but the year it gives has to be the award's own.

    History owns that year, so it is reported once, as a date, and not again as a metric.
    """
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Honors & Awards\n\n### Engineering Excellence Award\n2020\n"
        "Given for the settlement redesign; first presented in 2011.\n",
        load_mapping(_mapping()),
    )
    assert [(v.kind, v.text) for v in verdict.violations] == [("date", "2011")]
    assert "it has 2020" in verdict.violations[0].reason


def test_each_year_is_held_to_the_credential_printed_beside_it() -> None:
    """Two credentials on one line cannot trade years, whatever separates them."""
    data = _mapping()
    data["education"].insert(
        0,
        {
            "credential": "M.S. Computer Science",
            "institution": "University of Texas at Austin",
            "completed": "2018-12",
        },
    )
    data["certifications"].append(
        {"name": "Certified Kubernetes Administrator", "issuer": "CNCF", "year": "2024"}
    )
    profile = load_mapping(data)

    def dates_flagged(section: str) -> list[str]:
        verdict = verify_resume(f"# Jordan Rivera\n\n{section}\n", profile)
        assert set(_kinds(verdict)) <= {"date"}, format_violations(verdict)
        return _texts(verdict)

    ms, bs = "M.S. Computer Science", "B.S. Computer Science"
    aws, cka = "AWS Certified Solutions Architect", "Certified Kubernetes Administrator"
    swapped = [
        f"## Education\n\n### University of Texas at Austin\n{ms}, 2016; {bs}, 2018",
        f"## Education\n- {ms}, 2016, {bs}, 2018",
        f"## Certifications\n- {aws}, 2024 | {cka}, 2022",
        f"## Certifications\n**Cloud:** {aws}, 2024; {cka}, 2022",
    ]
    for section in swapped:
        assert sorted(dates_flagged(section)) == sorted(
            ["2016", "2018"] if "Education" in section else ["2022", "2024"]
        ), section
    for section in swapped:
        right = section.replace("2016", "X").replace("2018", "2016").replace("X", "2018")
        right = right.replace("2022", "X").replace("2024", "2022").replace("X", "2024")
        assert dates_flagged(right) == [], right


_LAPSED = {
    "name": "Series 7 (General Securities Representative)",
    "issuer": "FINRA",
    "notes": 'Lapsed; held as a broker, 2016-2018. Print it as "formerly licensed".',
}


@pytest.mark.parametrize(
    "section",
    [
        "### FINRA Series 7 — General Securities Representative\nFINRA | Held 2016 - 2018; lapsed",
        "- **Series 7** (General Securities Representative), FINRA: formerly licensed, 2016 – 2018",
    ],
)
def test_a_lapsed_license_may_print_the_years_its_notes_record(section: str) -> None:
    """The issuer may lead the name, and a date may qualify a phrase, as long as both are true."""
    profile = load_mapping(_mapping(certifications=[_LAPSED]))
    verdict = verify_resume(f"# Jordan Rivera\n\n## Certifications\n\n{section}\n", profile)
    assert verdict.ok, format_violations(verdict)


def test_a_date_qualifying_a_real_phrase_is_still_checked() -> None:
    profile = load_mapping(_mapping(certifications=[_LAPSED]))
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Certifications\n- FINRA Series 7, held 2012 – 2018\n", profile
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["2012"]


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


def test_a_name_that_opens_with_a_dot_keeps_it() -> None:
    """.NET is the profile's own spelling; only a dot that ends a sentence is punctuation."""
    languages = {"name": ".NET", "aliases": ["dotnet"]}
    technologies = [{"group": "Languages", "items": [{"name": "Go"}, languages]}]
    profile = load_mapping(_mapping(technologies=technologies))
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Languages:** .NET, Go.
        **Platforms:** dotnet (.NET), ASP.NET
        """,
        profile,
    )
    assert _texts(verdict) == ["ASP.NET"]


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


def test_a_skill_written_as_a_bullet_is_checked_like_a_labelled_one(profile: Profile) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        - Python, Rust
        """,
        profile,
    )
    assert _kinds(verdict) == ["technology"]
    assert _texts(verdict) == ["Rust"]


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


def test_a_product_written_without_its_vendor_is_still_the_recorded_one() -> None:
    """Inside "AWS (…)", "Aurora Serverless" is the profile's own "AWS Aurora Serverless"."""
    technologies = [
        {
            "group": "Cloud",
            "items": [{"name": "AWS Aurora Serverless"}, {"name": "Apache Kafka"}, {"name": "AWS"}],
        }
    ]
    profile = load_mapping(_mapping(technologies=technologies))
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Cloud:** AWS (Aurora Serverless), Kafka, Serverless
        """,
        profile,
    )
    assert _texts(verdict) == ["Serverless"], "a bare fragment is not a product"


def test_a_skills_line_under_a_role_is_a_claim_too(profile: Profile) -> None:
    """A LinkedIn position lists its skills under the role; each one must be real."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Rebuilt the settlement pipeline.
        **Skills:** Go, Python, Rust
        """,
        profile,
    )
    assert _texts(verdict) == ["Rust"]


def test_a_tech_stack_line_under_a_role_is_a_claim_too(profile: Profile) -> None:
    """The template puts a Tech Stack note under every role; each item on it must be real."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Rebuilt the settlement pipeline.
        *Tech Stack — Go, Rust*
        """,
        profile,
    )
    assert _kinds(verdict) == ["technology"]
    assert _texts(verdict) == ["Rust"]


@pytest.mark.parametrize(
    "note",
    [
        "*Tech Stack — Go, Rust*",
        "**Tech Stack:** Go, Rust",
        "*Technologies: Go, Rust*",
        "_Stack – Go, Rust_",
        "- Tech Stack: Go, Rust",
        "**Tech Stack**: Go, Rust",
        "*Tech Stack* — Go, Rust",
        "*Tech Stack — Go · Rust*",
        "*Tech Stack — Go | Rust*",
    ],
)
def test_a_tech_stack_note_under_a_project_is_a_claim_too(profile: Profile, note: str) -> None:
    """However the note is dressed, and wherever it sits, each item on it is claimed."""
    verdict = verify_resume(
        f"# Jordan Rivera\n\n## Projects\n\n### Ledgerize\nA ledger.\n{note}\n", profile
    )
    assert _kinds(verdict) == ["technology"]
    assert _texts(verdict) == ["Rust"]


@pytest.mark.parametrize(
    "line",
    [
        "*Tech Stack — Go · Python · SQL*",
        "*Tech Stack — Go | Python | SQL*",
        "*Tech Stack — Go, Python and SQL*",
        "- Stack-ranked 6 Go services by deploy time.",
    ],
)
def test_a_stack_note_splits_on_any_list_separator_and_a_verb_is_not_a_note(
    profile: Profile, line: str
) -> None:
    """Every item here is recorded, and "Stack-ranked" opens a bullet rather than a list."""
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Experience\n\n### Northwind Payments — Senior Backend Engineer\n"
        f"Mar 2021 – Present\n{line}\n\n## Skills\n**Languages:** Go · Python | SQL\n",
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_name_joined_with_and_is_two_claims_unless_it_is_one_name() -> None:
    """A list's last "Python and Rust" claims Rust; a recorded name with "and" is tried whole."""
    data = _mapping()
    data["technologies"][0]["items"].append({"name": "Identity and Access Management"})
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Practices:** Identity and Access Management, Go and Python, Python and Rust
        """,
        load_mapping(data),
    )
    assert _texts(verdict) == ["Python and Rust"]


def test_a_tech_stack_note_may_name_what_a_role_or_project_stack_records() -> None:
    """The profile says Terraform was used in that role, so saying so under it is true.

    The Skills section claims a technology outright, so it still answers to technologies alone.
    """
    data = _mapping()
    data["experience"][0]["roles"][0]["stack"] = ["Go", "Terraform"]
    data["projects"][0]["stack"] = ["Go", "SQLite"]
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Cloud:** Terraform

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Rebuilt the settlement pipeline.
        *Tech Stack — Go, Terraform, Go/Terraform*

        ## Projects

        ### Ledgerize
        A ledger.
        *Tech Stack: Go, SQLite*
        """,
        load_mapping(data),
    )
    assert [(v.line, v.text) for v in verdict.violations] == [(4, "Terraform")]


def test_a_labelled_line_outside_skills_and_experience_is_not_a_skills_claim(
    profile: Profile,
) -> None:
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Open to Work
        **Job titles:** Staff Backend Engineer, Platform Lead
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_figures_in_reads_claims_the_way_the_check_does() -> None:
    from resume_tailor.verify.metrics import figures_in

    lexicon = build_lexicon(load_mapping(_mapping()))
    found = figures_in(
        "Cut costs $200k and latency 38% on EC2 with Python 3 for 4M users.", lexicon
    )
    assert found == {"200000": "$200k", "38": "38%", "4000000": "4M"}
    assert figures_in("- Hired 25 in the first year.", lexicon) == {"25": "25"}
    assert figures_in("Cut MTTR 60 percent and grew ARR 5x.", lexicon) == {"60": "60", "5": "5x"}


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
        "**Latency** — Cut latency 38% from 820ms to 510ms.",
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
        - Scoped ISO 27001 certification and RFC 7519 tokens.
        - Python 3 powers every settlement service.
        - **Upgrade** — Moved every service to Python 3 in one quarter.
        - Typed every module with Python 3's hints.
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


@pytest.mark.parametrize(
    "bullet",
    [
        "Cut MTTR 60 percent.",
        "Improved NPS 20 points.",
        "Grew ARR 5x in two years.",
        "Achieved MTTR 45 minutes.",
        "Reached NPS 72.",
    ],
)
def test_a_quantity_after_a_metric_acronym_is_still_a_metric(profile: Profile, bullet: str) -> None:
    """MTTR, NPS and ARR are what a result is measured in, not products with versions."""
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
    assert _kinds(verdict) == ["metric"]


@pytest.mark.parametrize(
    "bullet",
    [
        "Lifted CTR 12 percent.",
        "Scaled PostgreSQL 3x in a year.",
        "Cut TTFB 400 ms across the checkout flow.",
        "Cut P95 400 ms across the checkout flow.",
        "Cut TTFB 400ms across the checkout flow.",
        "Cut CI 12 minutes per build.",
        "Lowered LCP 1.2 seconds on mobile.",
        "Used Go 12 years in production.",
    ],
)
def test_a_unit_or_a_multiplier_marks_a_quantity_after_any_name(
    profile: Profile, bullet: str
) -> None:
    """A version is never "12 percent", "3x" or "400 ms", whatever name comes before it."""
    verdict = verify_resume(
        "# Jordan Rivera\n\n## Experience\n\n### Northwind Payments — Senior Backend Engineer\n"
        f"Mar 2021 – Present\n- {bullet}\n",
        profile,
    )
    assert _kinds(verdict) == ["metric"]


@pytest.mark.parametrize(
    "bullet", ["Cut MTTR 60%.", "Cut MTTR 60 percent.", "Grew ARR 5x.", "Grew ARR 5 times over."]
)
def test_a_figure_the_profile_states_after_an_acronym_is_still_supported(bullet: str) -> None:
    """Profile prose supports every figure in it, so a true result may be restated freely."""
    data = _mapping()
    data["experience"][0]["roles"][0]["highlights"] = [
        {"text": "Cut MTTR 60 percent and grew ARR 5x."}
    ]
    verdict = _verify(
        f"""\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - {bullet}
        """,
        load_mapping(data),
    )
    assert verdict.ok, format_violations(verdict)


def test_the_dates_line_is_not_read_a_second_time_as_a_metric(profile: Profile) -> None:
    """The date check owns a dates line: a wrong year there is one date violation, not a metric.

    The zip code must not be read as a date either, or its last four digits would become the
    start of the range and hide the widened one printed after it.
    """
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Austin, TX 78701 | Jan 2015 – Present
        """,
        profile,
    )
    assert _kinds(verdict) == ["date"]
    assert _texts(verdict) == ["Jan 2015 – Present"]


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
    assert "99.98" not in supported_metrics(load_mapping(_mapping()))
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


def test_a_role_month_or_a_technology_name_is_not_a_supported_figure() -> None:
    """A role starting 2019-11 states a year, not 11 of anything; EC2 is a name, not a 2."""
    data = _mapping(
        technologies=[{"group": "Cloud", "items": [{"name": "Amazon EC2", "aliases": ["EC2"]}]}]
    )
    data["experience"][0]["roles"][1]["start"] = "2019-11"
    data["experience"][0]["roles"][0]["stack"] = ["Go", "S3"]
    data["experience"][0]["roles"][0]["highlights"][0]["tags"] = ["throughput", "EC2"]
    profile = load_mapping(data)
    supported = supported_metrics(profile)
    assert "2019" in supported
    assert supported.isdisjoint({"11", "2", "3"})
    assert supported == supported_metrics(profile, build_lexicon(profile))


@pytest.mark.parametrize(
    "bullet", ["Led a team of 3 engineers.", "Mentored 2 new hires.", "Held 99% uptime."]
)
def test_a_digit_glued_to_letters_in_profile_prose_supports_nothing(bullet: str) -> None:
    """EC2, S3, P99 and Q3 in a highlight name things; none states 2, 3 or 99 of anything."""
    data = _mapping()
    data["experience"][0]["roles"][0]["highlights"].append(
        {"text": "Moved the archive from EC2 to S3 in Q3, cutting P99 latency 45% on 12 services."}
    )
    profile = load_mapping(data)
    gained = supported_metrics(profile) - supported_metrics(load_mapping(_mapping()))
    assert gained == {"45", "12"}
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
    assert _kinds(verdict) == ["metric"]


def test_a_figure_the_profile_spells_out_supports_its_digits() -> None:
    """The profile's "seven years" is a resume's "7 years"; "one of" and "dozens" state none."""
    data = _mapping()
    data["experience"][1]["roles"][0]["highlights"].append(
        {"text": "Ran billing for seven years as one of twenty-one engineers in dozens of teams."}
    )
    profile = load_mapping(data)
    gained = supported_metrics(profile) - supported_metrics(load_mapping(_mapping()))
    assert gained == {"7", "21"}
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Cedar Analytics — Backend Engineer
        2016 – 2018
        - Ran billing for 7 years with 21+ engineers.
        - Led 12 teams and 1 guild.
        """,
        profile,
    )
    assert sorted(_texts(verdict)) == ["1 guild", "12 teams"]


def test_a_version_in_a_technology_name_is_not_a_supported_figure(profile: Profile) -> None:
    """The fixture's only 2s are in SOC 2, OAuth 2.0 and the month of 2021-02."""
    assert "2" not in supported_metrics(profile)
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Mentored 2 engineers.
        - Joined the settlement team in 2019 and shipped OAuth 2.0 in 2021.
        """,
        profile,
    )
    assert _texts(verdict) == ["2 engineers"], "a year the profile records is still printable"


def test_a_headcount_that_matches_only_a_role_month_is_caught(profile: Profile) -> None:
    """The fixture's only 3 is the month in 2021-03 (and the name S3); neither is a headcount."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Mentored 3 engineers.
        """,
        profile,
    )
    assert _kinds(verdict) == ["metric"]


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
    assert (source.lines[3].label, source.lines[3].body) == ("Languages", "Go")
    assert source.lines[5].label == ""
    assert source.lines[-1].area is Area.EDUCATION
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


def test_a_capitalised_verb_does_not_exempt_an_inflated_headcount(profile: Profile) -> None:
    """A bullet opens with a capitalised verb; that alone cannot mean "version"."""
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        - Mentored 30 junior engineers across three squads.
        """,
        profile,
    )
    assert not verdict.ok
    assert "30" in verdict.violations[0].text


@pytest.mark.parametrize(
    "bullet",
    [
        "- Hired 25 in the first year.",
        "- Mentored 30 across three squads.",
        "- **Hiring:** Hired 25 in the first year.",
        "- **Hiring** — Hired 25 in the first year.",
        "- **Hiring** - Hired 25 in the first year.",
        "- **Hiring** | Hired 25 in the first year.",
        "- **Hiring** Hired 25 in the first year.",
        "- __Hiring:__ Hired 25 in the first year.",
        "- *Hiring* — Hired 25 in the first year.",
    ],
)
def test_a_bullet_opening_verb_does_not_exempt_the_figure_after_it(
    profile: Profile, bullet: str
) -> None:
    """The same words as a Summary line are flagged; a list marker or lead-in cannot change that.

    A lead-in ends a phrase however it is closed, with a colon, a dash, a pipe or nothing at all.
    """
    verdict = _verify(
        f"""\
        # Jordan Rivera

        ## Experience

        ### Northwind Payments — Senior Backend Engineer
        Mar 2021 – Present
        {bullet}
        """,
        profile,
    )
    assert _kinds(verdict) == ["metric"]


# --- the profile's own acronym convention ------------------------------------------------------
@pytest.mark.parametrize(
    "spelling",
    ["Artificial Intelligence (AI)", "Artificial Intelligence", "AI"],
)
def test_either_half_of_an_acronym_name_is_the_same_claim(spelling: str) -> None:
    """The profile writes "Name (ACRONYM)"; a resume prints either half, and both are true."""
    profile = load_mapping(
        _mapping(
            technologies=[{"group": "AI", "items": [{"name": "Artificial Intelligence (AI)"}]}]
        )
    )
    verdict = _verify(
        f"""\
        # Jordan Rivera

        ## Skills
        **AI:** {spelling}
        """,
        profile,
    )
    assert verdict.ok, format_violations(verdict)


def test_a_parenthetical_list_still_claims_each_product_separately() -> None:
    """A bracketed list names other products, not other spellings of the one before it."""
    profile = load_mapping(
        _mapping(
            technologies=[{"group": "Cloud", "items": [{"name": "Amazon Web Services (AWS)"}]}]
        )
    )
    verdict = _verify(
        """\
        # Jordan Rivera

        ## Skills
        **Cloud:** AWS (ECS, Lambda)
        """,
        profile,
    )
    assert _texts(verdict) == ["ECS", "Lambda"], "the services still have to be real"
