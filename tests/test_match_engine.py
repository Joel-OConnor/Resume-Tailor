"""Lexicon compilation, posting parsing, coverage and gaps.

Most of these tests are named after a real way a keyword matcher lies on a resume. They exist
because an adversarial review produced each case against this exact profile.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.match import match_posting
from resume_tailor.match.coverage import Confidence, find_coverage
from resume_tailor.match.gaps import find_gaps
from resume_tailor.match.lexicon import Provenance, Tier, build_lexicon
from resume_tailor.match.posting import Section, parse_posting
from resume_tailor.profile import load_mapping

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

_TECHNOLOGIES: list[dict[str, Any]] = [
    {
        "group": "Data",
        "items": [
            {"name": "PostgreSQL", "aliases": ["Postgres"], "used_at": ["acme"]},
            {"name": "Caching", "aliases": ["cache warming"], "used_at": ["acme"]},
        ],
    },
    {
        "group": "Tooling",
        "items": [
            {"name": "BMC Remedy", "aliases": ["Remedy", "ITSM"], "used_at": ["acme"]},
            {"name": "Docker", "aliases": ["containers"], "level": "working", "used_at": ["acme"]},
            {"name": "Granite", "used_at": ["acme"]},
            {"name": "Go", "used_at": ["acme"]},
            {"name": "Node.js", "aliases": ["Node"], "used_at": ["acme"]},
            {"name": "Mentorship", "aliases": ["coaching"], "used_at": ["acme"]},
        ],
    },
]


def _profile(**overrides: Any) -> Profile:
    data: dict[str, Any] = {
        "contact": {"name": "Ada", "headline": "Engineer", "email": "a@b.c"},
        "summary": "s",
        "technologies": _TECHNOLOGIES,
        "experience": [
            {
                "id": "acme",
                "company": "Acme",
                "roles": [
                    {
                        "title": "Engineer",
                        "start": "2020",
                        "end": "present",
                        "highlights": [
                            {
                                "label": "Data Work",
                                "text": "Tuned PostgreSQL and Caching.",
                                "tags": ["postgresql"],
                            },
                            {"label": "People", "text": "Mentorship of four engineers."},
                        ],
                    }
                ],
            }
        ],
    }
    return load_mapping({**data, **overrides})


@pytest.fixture
def profile() -> Profile:
    return _profile()


def _match(text: str, profile: Profile, company: str = "") -> dict[str, Any]:
    report = match_posting(text, profile, company)
    return {
        "confirmed": {m.technology for m in report.confirmed},
        "qualified": {m.technology for m in report.qualified},
        "gaps": {g.term for g in report.gaps},
        "ignored": [reason for _, reason, _ in report.coverage.ignored],
        "report": report,
    }


# --- lexicon ---------------------------------------------------------------------------------
def test_a_category_alias_is_distinguished_from_a_respelling(profile: Profile) -> None:
    """ITSM is a product class; a posting naming it may mean a competitor of BMC Remedy."""
    lexicon = build_lexicon(profile)
    by_surface = {form.surface: form for form in lexicon.forms}
    assert by_surface["Remedy"].provenance is Provenance.VARIANT
    assert by_surface["ITSM"].provenance is Provenance.CATEGORY
    assert by_surface["Postgres"].provenance is Provenance.VARIANT
    assert by_surface["containers"].provenance is Provenance.CATEGORY


@pytest.mark.parametrize(
    ("surface", "tier"),
    [
        ("PostgreSQL", Tier.SAFE),
        ("BMC Remedy", Tier.SAFE),
        ("ITSM", Tier.CASED),
        ("Go", Tier.GUARDED),
        ("Granite", Tier.GUARDED),
        ("Node", Tier.GUARDED),
    ],
)
def test_forms_are_tiered_by_how_easily_they_misfire(
    profile: Profile, surface: str, tier: Tier
) -> None:
    lexicon = build_lexicon(profile)
    assert next(f for f in lexicon.forms if f.surface == surface).tier is tier


def test_evidence_requires_a_highlight_not_just_a_stack_link(profile: Profile) -> None:
    lexicon = build_lexicon(profile)
    assert lexicon.has_evidence("PostgreSQL")
    assert not lexicon.has_evidence("Docker"), "used_at alone is not evidence"


def test_a_technology_named_in_notes_is_flagged_unconfirmed() -> None:
    profile = _profile(notes=["Confirm you are comfortable claiming Docker in an interview."])
    assert "Docker" in build_lexicon(profile).unconfirmed


# --- posting parsing -------------------------------------------------------------------------
def test_sections_are_classified_from_headings() -> None:
    posting = parse_posting(
        textwrap.dedent("""\
            ## Requirements
            - PostgreSQL
            ## Nice to have
            - Docker
            ## Life at Acme
            - We drink coffee
        """)
    )
    assert [c.section for c in posting.clauses] == [Section.MUST, Section.NICE, Section.CONTEXT]


def test_the_company_name_is_taken_from_the_title_line() -> None:
    posting = parse_posting("# Granite Telecom — Staff Engineer\n\nBody.\n")
    assert posting.company == "Granite Telecom"
    assert posting.title == "Staff Engineer"


def test_a_heading_without_a_separator_is_all_title() -> None:
    assert parse_posting("# Staff Engineer\n\nBody.\n").title == "Staff Engineer"


def test_a_posting_with_no_heading_has_no_title() -> None:
    assert parse_posting("Just prose about a job.\n").title == ""


@pytest.mark.parametrize(
    ("line", "flag"),
    [
        ("- No PostgreSQL experience is required here.", "negated"),
        ("- We will teach you PostgreSQL on the job.", "future"),
        ("- Our sister team owns the PostgreSQL clusters.", "third_party"),
        ("- We are retiring the PostgreSQL service.", "deprecated"),
    ],
)
def test_scope_signals_are_detected(line: str, flag: str) -> None:
    clause = parse_posting(f"## Requirements\n{line}\n").clauses[0]
    assert getattr(clause, flag) is True
    assert not clause.counts_as_requirement


def test_a_clause_you_own_is_not_third_party() -> None:
    clause = parse_posting("## Requirements\n- You own the team's PostgreSQL clusters.\n").clauses[
        0
    ]
    assert not clause.third_party


def test_prose_lines_that_look_like_headings_are_still_body() -> None:
    posting = parse_posting("This is an ordinary sentence about the work.\n")
    assert len(posting.clauses) == 1


# --- coverage --------------------------------------------------------------------------------
def test_a_direct_evidenced_match_is_confirmed(profile: Profile) -> None:
    result = _match("## Requirements\n- Deep PostgreSQL expertise.\n", profile)
    assert "PostgreSQL" in result["confirmed"]


def test_a_substring_can_never_match(profile: Profile) -> None:
    """SQL must not fire inside PostgreSQL, and Go must not fire inside going."""
    result = _match("## Requirements\n- We are going to Google about NoSQL.\n", profile)
    assert not result["confirmed"]
    assert not result["qualified"]


def test_a_category_alias_only_ever_reaches_partial(profile: Profile) -> None:
    result = _match("## Requirements\n- ServiceNow (ITSM) integration experience.\n", profile)
    assert "BMC Remedy" in result["qualified"]
    match = next(m for m in result["report"].qualified if m.technology == "BMC Remedy")
    assert match.confidence is Confidence.PARTIAL
    assert "different vendor" in match.caveat
    assert not match.satisfies_must_have


def test_a_technology_without_evidence_only_reaches_partial(profile: Profile) -> None:
    result = _match("## Requirements\n- Strong Docker experience.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Docker")
    assert "no accomplishment" in match.caveat


def test_an_unconfirmed_technology_cannot_satisfy_a_must_have() -> None:
    profile = _profile(notes=["Confirm Docker before claiming it."])
    result = _match("## Requirements\n- Docker at scale.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Docker")
    assert match.unconfirmed
    assert not match.satisfies_must_have


def test_a_shallow_technology_cannot_satisfy_a_must_have(profile: Profile) -> None:
    result = _match("## Requirements\n- Docker at scale.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Docker")
    assert match.is_shallow


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("- No Docker experience is required.", "stated as not required"),
        ("- We will teach you Docker.", "offered as something to learn"),
        ("- Our platform team runs Docker.", "attributed to another team"),
        ("- We are retiring Docker this year.", "described as being retired"),
    ],
)
def test_a_mentioned_technology_is_not_a_requirement(
    profile: Profile, line: str, reason: str
) -> None:
    result = _match(f"## Requirements\n{line}\n", profile)
    assert "Docker" not in result["confirmed"] | result["qualified"]
    assert reason in result["ignored"]


def test_a_culture_section_never_produces_coverage(profile: Profile) -> None:
    result = _match("## Life at Acme\n- Our Granite office runs on coffee and Go karts.\n", profile)
    assert not result["confirmed"] and not result["qualified"]


def test_the_postings_own_company_name_is_suppressed(profile: Profile) -> None:
    """A posting from a company called Granite must not match the profile's Granite."""
    text = "# Granite Telecom — Engineer\n\n## Requirements\n- Work on Granite systems.\n"
    result = _match(text, profile)
    assert "Granite" not in result["confirmed"] | result["qualified"]


def test_an_explicit_company_overrides_the_heading(profile: Profile) -> None:
    result = _match("## Requirements\n- Granite work.\n", profile, company="Granite")
    assert "Granite" not in result["confirmed"] | result["qualified"]


def test_an_alternation_still_finds_the_covered_branch(profile: Profile) -> None:
    """The 'PostgreSQL/MySQL' case: offers a choice; one branch is covered, so it is not a gap."""
    result = _match("## Requirements\n- A PostgreSQL/MySQL split behind the API.\n", profile)
    assert "PostgreSQL" in result["confirmed"]
    assert not any("MySQL" in gap for gap in result["gaps"])


def test_a_joined_name_is_not_split_apart(profile: Profile) -> None:
    """CI/CD is one name, not an alternation of CI and CD."""
    posting = parse_posting("## Requirements\n- CI/CD ownership.\n")
    coverage = find_coverage(posting, build_lexicon(profile))
    assert not coverage.matches


def test_a_stem_match_is_reported_as_partial(profile: Profile) -> None:
    result = _match("## Requirements\n- A record of mentoring senior engineers.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Mentorship")
    assert "word stem" in match.caveat


def test_a_guarded_word_needs_technology_framing(profile: Profile) -> None:
    prose = _match("## Requirements\n- A granite foundation of good judgement.\n", profile)
    assert "Granite" not in prose["confirmed"] | prose["qualified"]


def test_a_cased_form_is_not_matched_by_the_lowercase_word(profile: Profile) -> None:
    assert "Go" not in _match("## Requirements\n- You go where needed.\n", profile)["confirmed"]


# --- gaps ------------------------------------------------------------------------------------
def test_an_unmatched_technology_shaped_term_becomes_a_gap(profile: Profile) -> None:
    assert "Kafka" in _match("## Requirements\n- Kafka expertise is required.\n", profile)["gaps"]


def test_prose_requirements_are_found_even_though_they_are_lowercase(profile: Profile) -> None:
    text = "## Requirements\n- You carry the pager and run incident response.\n"
    gaps = _match(text, profile)["gaps"]
    assert {"pager", "incident response"} <= gaps


def test_a_near_miss_suggests_an_alias_rather_than_a_gap() -> None:
    """A gap that is really a missing alias should say so rather than read as missing skill."""
    profile = _profile(
        technologies=[{"group": "Data", "items": [{"name": "Caching", "used_at": ["acme"]}]}]
    )
    report = match_posting("## Requirements\n- You own Caches and invalidation.\n", profile)
    gap = next(g for g in report.gaps if g.term == "Caches")
    assert gap.near_miss == "Caching"


def test_a_shared_prefix_is_not_a_resemblance(profile: Profile) -> None:
    """The 'postmortem' case: is not a kind of "PostgreSQL"."""
    report = match_posting("## Requirements\n- Write the postmortem.\n", profile)
    assert next(g for g in report.gaps if g.term == "postmortem").near_miss == ""


def test_posting_furniture_is_not_reported_as_a_gap(profile: Profile) -> None:
    gaps = _match("## Requirements\n- Senior Staff Engineer with 8 years experience.\n", profile)[
        "gaps"
    ]
    assert not gaps


def test_gaps_are_not_mined_from_non_requirements(profile: Profile) -> None:
    assert not _match("## Life at Acme\n- We love Kafka and Rust.\n", profile)["gaps"]


def test_a_gap_records_every_line_it_appeared_on() -> None:
    text = "## Requirements\n- Kafka streaming.\n- Deep Kafka work.\n"
    report = match_posting(text, _profile())
    assert next(g for g in report.gaps if g.term == "Kafka").lines == (2, 3)


def test_find_gaps_accepts_an_empty_covered_set(profile: Profile) -> None:
    posting = parse_posting("## Requirements\n- Kafka.\n")
    assert find_gaps(posting, build_lexicon(profile), frozenset())


def test_punctuation_separates_two_requirements_instead_of_welding_them() -> None:
    """A bracket splits two requirements; welded they became a gap nothing can ever match."""
    profile = _profile(
        technologies=[{"group": "Languages", "items": [{"name": "Python", "used_at": ["acme"]}]}]
    )
    report = match_posting("## Requirements\n- Strong Go (Python a plus).\n", profile)
    terms = {gap.term for gap in report.gaps}
    assert "Go" in terms
    assert "Go Python" not in terms, "a bracket separates two requirements"
    assert "Python" not in terms, "matched elsewhere, so it cannot also be a gap"


def test_a_comma_separated_list_is_one_gap_per_item() -> None:
    text = "## Requirements\n- Hands-on with Kafka, Terraform, and Rust.\n"
    terms = {gap.term for gap in match_posting(text, _profile()).gaps}
    assert {"Kafka", "Terraform", "Rust"} <= terms
    assert not any(" " in term for term in terms), "commas must not weld names together"


def test_a_multi_word_product_name_survives_as_one_term() -> None:
    """The break is punctuation, not every space — "Amazon Web Services" is one name."""
    text = "## Requirements\n- Deep experience with Amazon Web Services.\n"
    assert "Amazon Web Services" in {gap.term for gap in match_posting(text, _profile()).gaps}


def test_a_hyphenated_sentence_opener_is_not_a_missing_skill() -> None:
    """A hyphenated opener reads like the plain one, and neither of them is a skill."""
    text = "## Requirements\n- Hands-on with Kafka.\n"
    assert "Hands-on" not in {gap.term for gap in match_posting(text, _profile()).gaps}


# --- remaining edges -----------------------------------------------------------------------
def test_a_lowercase_category_alias_says_broader_not_vendor() -> None:
    profile = _profile(
        technologies=[
            {
                "group": "Ops",
                "items": [{"name": "Docker", "aliases": ["containers"], "used_at": ["acme"]}],
            }
        ]
    )
    result = _match("## Requirements\n- Deep containers expertise.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Docker")
    assert "broader than" in match.caveat


def test_an_all_caps_acronym_is_framed_by_its_own_shape(profile: Profile) -> None:
    """ITSM needs no neighbouring frame word — being an acronym is the frame."""
    assert "BMC Remedy" in _match("## Requirements\n- ITSM, ticketing.\n", profile)["qualified"]


def test_a_bare_alternation_branch_is_still_a_gap(profile: Profile) -> None:
    gaps = _match("## Requirements\n- Rust/Elixir services.\n", profile)["gaps"]
    assert any("Rust" in gap for gap in gaps)


def test_a_colonless_short_line_is_body_not_a_heading() -> None:
    posting = parse_posting("Requirements\n- PostgreSQL.\n")
    assert len(posting.clauses) == 2


def test_a_bold_heading_is_recognised() -> None:
    posting = parse_posting("**Requirements**\n- PostgreSQL.\n")
    assert posting.clauses[0].section is Section.MUST


def test_a_plain_heading_with_a_colon_is_recognised() -> None:
    posting = parse_posting("Requirements:\n- PostgreSQL.\n")
    assert posting.clauses[0].section is Section.MUST


def test_a_non_heading_first_line_is_skipped_when_looking_for_the_title() -> None:
    posting = parse_posting("Some intro prose.\n\n# Acme — Engineer\n")
    assert posting.company == "Acme"


def test_a_tool_frame_word_admits_a_guarded_form(profile: Profile) -> None:
    """The 'built on Granite' case: frames Granite as a tool even though it is an English word."""
    assert (
        "Granite" in _match("## Requirements\n- Services built on granite.\n", profile)["qualified"]
    )


def test_an_always_term_is_mined_even_though_it_is_lowercase(profile: Profile) -> None:
    assert "kubectl" in _match("## Requirements\n- Fluent with kubectl daily.\n", profile)["gaps"]


def test_a_short_mixed_case_form_needs_matching_capitalisation() -> None:
    """The 'Vue' case: is three characters — the lowercase word must not match it."""
    profile = _profile(
        technologies=[{"group": "UI", "items": [{"name": "Vue", "used_at": ["acme"]}]}]
    )
    assert "Vue" in _match("## Requirements\n- Deep Vue work.\n", profile)["qualified"]
    assert "Vue" not in _match("## Requirements\n- With a vue of the park.\n", profile)["qualified"]


def test_a_punctuated_unknown_term_is_mined_as_a_gap(profile: Profile) -> None:
    assert "C#" in _match("## Requirements\n- Services in C# on Windows.\n", profile)["gaps"]


def test_a_clause_with_no_tokens_is_dropped() -> None:
    assert parse_posting("## Requirements\n- ... ; ...\n").clauses == ()


def test_a_lowercase_dotted_name_is_mined_as_a_gap(profile: Profile) -> None:
    """The socket.io case: no capital and no acronym shape, only punctuation."""
    assert "socket.io" in _match("## Requirements\n- Realtime with socket.io.\n", profile)["gaps"]


def test_the_role_is_found_on_either_side_of_the_separator() -> None:
    """Both orders are published; position alone gets it wrong half the time."""
    role_first = parse_posting("# Staff Data Platform Engineer — Northwind Freight\n\nBody.\n")
    assert role_first.title == "Staff Data Platform Engineer"
    assert role_first.company == "Northwind Freight"

    company_first = parse_posting("# Granite Telecom — Staff Engineer\n\nBody.\n")
    assert company_first.title == "Staff Engineer"
    assert company_first.company == "Granite Telecom"


def test_a_heading_with_no_role_word_keeps_the_company_first_reading() -> None:
    posting = parse_posting("# Northwind Freight — Widgets Division\n\nBody.\n")
    assert posting.company == "Northwind Freight"


def test_generic_prose_is_not_reported_as_a_missing_technology() -> None:
    """Generic prose must not be reported as a technology the profile lacks."""
    posting = parse_posting(
        "# Staff Engineer — Acme\n\n## Requirements\n"
        "- Production experience with Apache Kafka at scale.\n"
        "- Strong ownership and a quality mindset across the platform.\n"
    )
    lexicon = build_lexicon(_profile())
    gaps = {gap.term.casefold() for gap in find_gaps(posting, lexicon, frozenset())}
    for noise in ("production", "ownership", "quality", "platform", "scale"):
        assert noise not in gaps, f"{noise} reported as a missing technology"


def test_a_bare_name_and_its_fuller_form_are_one_gap() -> None:
    """A posting naming both "Apache Kafka" and "Kafka" is missing one thing, not two."""
    posting = parse_posting(
        "# Staff Engineer — Acme\n\n## Requirements\n"
        "- Production experience with Apache Kafka.\n"
        "- Kafka tuning at scale.\n"
    )
    gaps = find_gaps(posting, build_lexicon(_profile()), frozenset())
    terms = [gap.term for gap in gaps]
    assert "Apache Kafka" in terms
    assert "Kafka" not in terms
    kafka = next(gap for gap in gaps if gap.term == "Apache Kafka")
    assert len(kafka.lines) == 2, "the absorbed term keeps its line reference"


def test_a_posting_may_spell_out_an_acronym_the_profile_joined() -> None:
    """The profile's "Name (ACRONYM)" convention is one claim written three ways."""
    profile = _profile(
        technologies=[
            {
                "group": "AI",
                "items": [{"name": "Artificial Intelligence (AI)", "used_at": ["acme"]}],
            }
        ]
    )
    for wording in ("Artificial Intelligence", "AI", "Artificial Intelligence (AI)"):
        report = match_posting(f"## Requirements\n- Deep {wording} experience.\n", profile)
        assert not [gap for gap in report.gaps if "ntelligence" in gap.term or gap.term == "AI"], (
            f"the profile records this, however the posting spells it: {wording}"
        )
