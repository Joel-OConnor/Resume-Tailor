"""Lexicon compilation, posting parsing, coverage and gaps.

Most of these tests are named after a real way a keyword matcher lies on a resume. They exist
because an adversarial review produced each case against this exact profile.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.match import match_posting, render_markdown
from resume_tailor.match.coverage import Confidence, find_coverage
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


def _acme(*highlights: dict[str, Any]) -> list[dict[str, Any]]:
    """Return an experience list of one Acme role holding exactly ``highlights``."""
    role = {"title": "Engineer", "start": "2020", "end": "present", "highlights": list(highlights)}
    return [{"id": "acme", "company": "Acme", "roles": [role]}]


def _profile(**overrides: Any) -> Profile:
    data: dict[str, Any] = {
        "contact": {"name": "Ada", "headline": "Engineer", "email": "a@b.c"},
        "summary": "s",
        "technologies": _TECHNOLOGIES,
        "experience": _acme(
            {"label": "Data Work", "text": "Tuned PostgreSQL and Caching.", "tags": ["postgresql"]},
            {"label": "People", "text": "Mentorship of four engineers."},
        ),
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


def _provenance_of(name: str, alias: str) -> Provenance:
    """Return the provenance the lexicon gives ``alias`` as a spelling of ``name``."""
    technologies = [
        {"group": "G", "items": [{"name": name, "aliases": [alias], "used_at": ["acme"]}]}
    ]
    forms = build_lexicon(_profile(technologies=technologies)).forms
    return next(form for form in forms if form.surface == alias).provenance


@pytest.mark.parametrize(
    ("name", "alias"),
    [
        ("Kubernetes", "K8s"),
        ("Test-driven development", "TDD"),
        ("JavaScript", "JS"),
        ("CI/CD", "Continuous Integration"),
        ("CI/CD", "Continuous Delivery"),
        ("Infrastructure as Code", "IaC"),
        ("Internationalization", "i18n"),
        # Either side may be the short one.
        ("K8s", "Kubernetes"),
        ("TDD", "Test-driven development"),
        ("JS", "JavaScript"),
    ],
)
def test_an_abbreviation_of_the_name_is_a_variant(name: str, alias: str) -> None:
    """Initials and numeronyms respell the name; calling them categories made K8s a vendor."""
    assert _provenance_of(name, alias) is Provenance.VARIANT


@pytest.mark.parametrize(
    ("name", "alias"),
    [
        ("BMC Remedy", "ITSM"),
        ("Salesforce", "CRM"),
        ("Terraform", "IaC"),
        ("Terraform", "infrastructure as code"),
        ("Docker", "containers"),
        # K9s is a different tool: a numeronym has to count the letters it stands for.
        ("Kubernetes", "K9s"),
        # The platform a product runs on is broader than the product, whatever its initials.
        ("AWS Lambda", "Amazon Web Services"),
    ],
)
def test_an_alias_that_abbreviates_nothing_is_still_a_category(name: str, alias: str) -> None:
    assert _provenance_of(name, alias) is Provenance.CATEGORY


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


@pytest.mark.parametrize(("tag", "technology"), [("docker", "Docker"), ("go", "Go")])
def test_a_tag_alone_makes_a_highlight_evidence(tag: str, technology: str) -> None:
    """Tags declare what a highlight is evidence for, even when its prose never says so.

    A tag is a declaration, not prose, so it matches in any case: "go" alone would be the verb
    in a sentence, but as a tag it can only mean the language.
    """
    profile = _profile(
        experience=_acme(
            {"label": "Scheduler", "text": "Moved the fleet to a new scheduler.", "tags": [tag]}
        )
    )
    assert build_lexicon(profile).evidence[technology] == ("Scheduler",)


def test_a_highlight_without_a_label_is_cited_by_its_opening_words() -> None:
    text = (
        "Tuned PostgreSQL until the nightly batch finished in forty minutes instead of four hours."
    )
    profile = _profile(experience=_acme({"text": text}))
    assert build_lexicon(profile).evidence["PostgreSQL"] == (text[:60],)


@pytest.mark.parametrize(
    ("technology", "text"),
    [("Java", "Built the settlement engine in Java."), ("Go", "Wrote the billing service in Go.")],
)
def test_a_highlight_naming_the_technology_as_a_word_is_evidence(
    technology: str, text: str
) -> None:
    technologies = [{"group": "Languages", "items": [{"name": technology, "used_at": ["acme"]}]}]
    profile = _profile(technologies=technologies, experience=_acme({"label": "Work", "text": text}))
    assert build_lexicon(profile).has_evidence(technology)


@pytest.mark.parametrize(
    ("technology", "text"),
    [
        ("Java", "Built a JavaScript dashboard for ops."),
        ("Go", "Migrated billing to Google Cloud."),
        ("Go", "Helped the team go faster on releases."),
    ],
)
def test_a_word_merely_containing_the_name_is_not_evidence(technology: str, text: str) -> None:
    """A JavaScript dashboard says nothing about Java; Google Cloud and "go" say nothing of Go."""
    technologies = [{"group": "Languages", "items": [{"name": technology, "used_at": ["acme"]}]}]
    profile = _profile(technologies=technologies, experience=_acme({"label": "Work", "text": text}))
    assert not build_lexicon(profile).has_evidence(technology)


def _evidenced(item: dict[str, Any], text: str, label: str = "Work") -> bool:
    """Report whether a highlight reading ``text`` is evidence for the one technology ``item``."""
    technologies = [{"group": "G", "items": [{**item, "used_at": ["acme"]}]}]
    profile = _profile(technologies=technologies, experience=_acme({"label": label, "text": text}))
    return build_lexicon(profile).has_evidence(item["name"])


@pytest.mark.parametrize(
    ("item", "text"),
    [
        # A respelling the profile records is the same technology.
        ({"name": "PostgreSQL", "aliases": ["Postgres"]}, "Tuned Postgres."),
        # So is either half of the profile's "Name (ACRONYM)" convention.
        ({"name": "Amazon Web Services (AWS)"}, "Cut AWS spend 22%."),
        # A stack list names each of its parts, and a joined name is still whole.
        ({"name": "React"}, "Shipped it on NestJS/React/PostgreSQL."),
        ({"name": "CI/CD"}, "Owned CI/CD for the team."),
        ({"name": "REST"}, "Designed REST APIs for partners."),
        # Prose glues a name to the word beside it, the way resumes are written.
        ({"name": "Python"}, "Built a Python-based ETL framework."),
        ({"name": "Kafka"}, "Designed a Kafka-backed event bus."),
        ({"name": "Terraform"}, "Moved 60 AWS accounts to Terraform-managed infrastructure."),
        ({"name": "C#"}, "Rewrote billing on C#/.NET."),
        ({"name": "SQL"}, "Built the reports in SQL/Python."),
        ({"name": "SQL"}, "Wrote T-SQL stored procedures."),
        ({"name": "React"}, "Shipped a React.js admin dashboard."),
        ({"name": "Express", "aliases": ["Express.js"]}, "Served it from Node.js/Express.js."),
        ({"name": "Express"}, "Served it from Express.js."),
        # A lone letter counts when a tool frame sits on its natural side.
        ({"name": "C"}, "Wrote the firmware in C."),
        ({"name": "C"}, "Built a C library for parsing."),
        # An abbreviation the profile records is a spelling, not a category.
        ({"name": "Kubernetes", "aliases": ["K8s"]}, "Moved 40 services onto K8s."),
        ({"name": "Test-driven development", "aliases": ["TDD"]}, "Brought TDD to the team."),
        ({"name": "CI/CD", "aliases": ["Continuous Integration"]}, "Ran Continuous Integration."),
    ],
)
def test_a_highlight_naming_a_spelling_of_the_technology_is_evidence(
    item: dict[str, Any], text: str
) -> None:
    assert _evidenced(item, text)


@pytest.mark.parametrize(
    ("item", "text"),
    [
        # A category alias is not: running containers is not running Docker, even in a list.
        ({"name": "Docker", "aliases": ["containers"]}, "Ran containers at scale."),
        ({"name": "Docker", "aliases": ["containers"]}, "Ran containers/VMs."),
        # An acronym that is also a word needs its capitals.
        ({"name": "REST"}, "Moved the rest of the fleet."),
        ({"name": "SQL"}, "Wrote sql-backed reports."),
        # A part of a joined word has no frame, so an ordinary word never counts.
        ({"name": "Go"}, "Owned the go-live for the payments launch."),
        ({"name": "Go"}, "Ran the Go/No-Go review before launch."),
        ({"name": "Node.js", "aliases": ["Node"]}, "Ran the Node-based batch workers."),
        # A lone letter is capitalised whatever it means.
        ({"name": "C"}, "Presented the roadmap to the C-suite."),
        ({"name": "C"}, "Prepared the Series C data room."),
        ({"name": "C"}, "Closed the Series C in March."),
    ],
)
def test_a_highlight_naming_something_broader_or_different_is_not_evidence(
    item: dict[str, Any], text: str
) -> None:
    assert not _evidenced(item, text)


@pytest.mark.parametrize(
    ("item", "label"),
    [
        ({"name": "Node.js", "aliases": ["Node"]}, "Worker Node Autoscaling"),
        ({"name": "Express.js", "aliases": ["Express"]}, "Same-Day Express Checkout"),
        ({"name": "C"}, "Series C Data Room"),
        ({"name": "Vue"}, "Vue Migration"),
    ],
)
def test_a_capital_in_a_title_case_label_is_not_evidence(item: dict[str, Any], label: str) -> None:
    """Every word of a label is capitalised, so a capital there cannot mark a product name."""
    assert not _evidenced(item, "Cut the queue time in half.", label=label)


def test_a_label_can_still_name_an_acronym_or_a_distinctive_name() -> None:
    assert _evidenced({"name": "REST"}, "Moved partners to v2.", label="REST API Redesign")
    assert _evidenced({"name": "Kafka"}, "Cut consumer lag.", label="Kafka Migration")


def test_a_common_word_label_does_not_confirm_the_technology_it_resembles() -> None:
    """The report must not tell the model to lead with Node.js on a Kubernetes story."""
    technologies = [
        {
            "group": "Runtimes",
            "items": [
                {"name": "Node.js", "aliases": ["Node"], "level": "proficient", "used_at": ["acme"]}
            ],
        }
    ]
    profile = _profile(
        technologies=technologies,
        experience=_acme(
            {"label": "Worker Node Autoscaling", "text": "Scaled the Kubernetes worker pools."}
        ),
    )
    result = _match("## Requirements\n- Experience with Node.\n", profile)
    assert "Node.js" in result["qualified"]
    assert "Node.js" not in result["confirmed"]


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


def test_a_category_alias_only_ever_reaches_partial() -> None:
    """Remedy is evidenced here, so only the ITSM category keeps ServiceNow from confirming it."""
    profile = _profile(
        experience=_acme(
            {"label": "Service Desk", "text": "Administered BMC Remedy for 4,000 users."}
        )
    )
    assert build_lexicon(profile).has_evidence("BMC Remedy")
    result = _match("## Requirements\n- ServiceNow (ITSM) integration experience.\n", profile)
    assert "BMC Remedy" in result["qualified"]
    assert "BMC Remedy" not in result["confirmed"]
    match = next(m for m in result["report"].qualified if m.technology == "BMC Remedy")
    assert match.confidence is Confidence.PARTIAL
    assert "different vendor" in match.caveat
    assert not match.satisfies_must_have


def test_a_postings_abbreviation_of_a_technology_is_not_called_another_vendor() -> None:
    """K8s is Kubernetes: the posting asks for exactly what the profile records."""
    profile = _profile(
        technologies=[
            {
                "group": "Ops",
                "items": [
                    {
                        "name": "Kubernetes",
                        "aliases": ["K8s"],
                        "level": "proficient",
                        "used_at": ["acme"],
                    }
                ],
            }
        ],
        experience=_acme({"label": "Clusters", "text": "Ran Kubernetes clusters for 40 services."}),
    )
    report = match_posting("## Requirements\n- Experience with K8s.\n", profile)
    match = next(m for m in report.coverage.matches if m.technology == "Kubernetes")
    assert "vendor" not in match.caveat
    assert match in report.confirmed


def _listed_profile() -> Profile:
    """Return a profile that evidences every technology the list postings below name."""
    names = ["Amazon Web Services (AWS)", "Kubernetes", "Terraform", "Go", "Kafka", "PostgreSQL"]
    items = [{"name": name, "level": "proficient", "used_at": ["acme"]} for name in names]
    return _profile(
        technologies=[{"group": "Stack", "items": items}],
        experience=_acme(
            {
                "label": "Platform",
                "text": "Ran Go services on AWS and Kubernetes, provisioned with Terraform.",
            },
            {"label": "Events", "text": "Moved the ledger from PostgreSQL to Kafka."},
        ),
    )


@pytest.mark.parametrize(
    "line",
    [
        "Hands-on with AWS, Kubernetes, and Terraform.",
        "Experience with Go, Kubernetes and AWS.",
        "Kafka, Go and PostgreSQL in production.",
        "Strong Go (Kafka a plus).",
    ],
)
def test_punctuation_ends_a_product_name(line: str) -> None:
    """The next item of a list is not the rest of a longer product's name.

    Read that way, every item of "AWS, Kubernetes, and Terraform" but the last was qualified as
    naming "a more specific product", and the tailoring prompt is bound by that caveat.
    """
    report = match_posting(f"## Requirements\n- {line}\n", _listed_profile())
    assert len(report.coverage.matches) >= 2
    assert not [m.technology for m in report.coverage.matches if m.caveat]
    assert report.confirmed == report.coverage.matches


@pytest.mark.parametrize(
    "line", ["Experience with AWS Lambda.", "Hands-on with AWS Lambda, Kubernetes, and Terraform."]
)
def test_a_name_followed_by_a_space_and_a_product_still_names_a_more_specific_one(
    line: str,
) -> None:
    report = match_posting(f"## Requirements\n- {line}\n", _listed_profile())
    aws = next(m for m in report.coverage.matches if m.technology == "Amazon Web Services (AWS)")
    assert aws.confidence is Confidence.PARTIAL
    assert aws.caveat == "the posting names a more specific product than the profile records"


def test_products_bracketed_after_a_name_are_gaps_rather_than_a_caveat_on_it() -> None:
    """Nothing is overstated: AWS is what the profile records, and the rest is reported missing."""
    report = match_posting(
        "## Requirements\n- AWS (Lambda, ECS) in production.\n", _listed_profile()
    )
    assert "Amazon Web Services (AWS)" in {m.technology for m in report.confirmed}
    assert {"Lambda", "ECS"} <= {gap.term for gap in report.gaps}


def test_a_technology_without_evidence_only_reaches_partial(profile: Profile) -> None:
    result = _match("## Requirements\n- Strong Docker experience.\n", profile)
    match = next(m for m in result["report"].qualified if m.technology == "Docker")
    assert "no accomplishment" in match.caveat


def test_an_unconfirmed_technology_cannot_satisfy_a_must_have() -> None:
    """Every other gate passes here, so only the note keeps Kubernetes out of "lead with these"."""
    profile = _profile(
        technologies=[
            {
                "group": "Ops",
                "items": [{"name": "Kubernetes", "level": "proficient", "used_at": ["acme"]}],
            }
        ],
        experience=_acme({"label": "Clusters", "text": "Ran Kubernetes clusters."}),
        notes=["Kubernetes: hands-on, or only alongside the platform team?"],
    )
    report = match_posting("## Requirements\n- Kubernetes at scale.\n", profile)
    match = next(m for m in report.coverage.matches if m.technology == "Kubernetes")
    assert match.confidence is Confidence.COVERED
    assert not match.is_shallow
    assert match.unconfirmed
    assert not match.satisfies_must_have
    assert match in report.qualified
    assert match not in report.confirmed
    out = render_markdown(report)
    assert "**unconfirmed**" in out
    assert "| Kubernetes |" not in out, "an open question must not be cited as a confirmed match"


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


def test_a_technology_in_the_postings_title_still_matches_in_the_body() -> None:
    """A "Senior Python Engineer" posting is asking for Python; masking the title hid it.

    The company half of the same heading is still masked, so Granite Telecom's posting does not
    confirm the profile's Granite.
    """
    profile = _profile(
        technologies=[
            {
                "group": "Languages",
                "items": [
                    {"name": "Python", "level": "proficient", "used_at": ["acme"]},
                    {"name": "Granite", "level": "proficient", "used_at": ["acme"]},
                ],
            }
        ],
        experience=_acme(
            {"label": "ETL", "text": "Rewrote the ETL in Python."},
            {"label": "Inventory", "text": "Built the inventory on Granite."},
        ),
    )
    text = (
        "# Senior Python Engineer - Granite Telecom\n\n## Requirements\n"
        "- Python in production.\n- Work on Granite systems.\n"
    )
    result = _match(text, profile)
    assert result["report"].posting.title == "Senior Python Engineer"
    assert "Python" in result["confirmed"]
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


def test_a_cased_form_is_not_matched_by_the_lowercase_word() -> None:
    """REST is an architecture; "the rest of the platform" is not asking for it."""
    profile = _profile(
        technologies=[{"group": "APIs", "items": [{"name": "REST", "used_at": ["acme"]}]}],
        experience=_acme({"label": "Partner API", "text": "Designed REST APIs for partners."}),
    )
    assert next(f for f in build_lexicon(profile).forms if f.surface == "REST").tier is Tier.CASED
    prose = _match("## Requirements\n- Own the rest of the platform.\n", profile)
    assert "REST" not in prose["confirmed"] | prose["qualified"]
    named = _match("## Requirements\n- Design REST APIs.\n", profile)
    assert "REST" in named["confirmed"] | named["qualified"]


def test_a_short_cased_form_proves_nothing_at_the_start_of_a_sentence() -> None:
    """Every clause opens with a capital, so a leading "Vue" says nothing about its casing."""
    profile = _profile(
        technologies=[{"group": "UI", "items": [{"name": "Vue", "used_at": ["acme"]}]}]
    )
    assert next(f for f in build_lexicon(profile).forms if f.surface == "Vue").tier is Tier.CASED
    opening = _match("## Requirements\n- Vue at scale.\n", profile)
    assert "Vue" not in opening["confirmed"] | opening["qualified"]
    inside = _match("## Requirements\n- Deep Vue work.\n", profile)
    assert "Vue" in inside["confirmed"] | inside["qualified"]


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


@pytest.mark.parametrize(
    "line",
    [
        "- Senior Staff Engineer with 8 years experience.",
        # The title is no longer masked out of the body, so its restatement must read as noise.
        "- We're hiring a Staff Software Engineer.",
        "- 8+ years backend experience, with time at the Staff/Lead level.",
    ],
)
def test_posting_furniture_is_not_reported_as_a_gap(profile: Profile, line: str) -> None:
    assert not _match(f"## Requirements\n{line}\n", profile)["gaps"]


def test_gaps_are_not_mined_from_non_requirements(profile: Profile) -> None:
    assert not _match("## Life at Acme\n- We love Kafka and Rust.\n", profile)["gaps"]


def test_a_gap_records_every_line_it_appeared_on() -> None:
    text = "## Requirements\n- Kafka streaming.\n- Deep Kafka work.\n"
    report = match_posting(text, _profile())
    assert next(g for g in report.gaps if g.term == "Kafka").lines == (2, 3)


def test_a_capitalised_opener_does_not_turn_a_matched_name_into_a_gap() -> None:
    """The "Advanced SQL" case: a gap there forbids the skill the report just confirmed."""
    profile = _profile(
        technologies=[
            {
                "group": "Languages",
                "items": [
                    {"name": "SQL", "used_at": ["acme"]},
                    {"name": "Python", "used_at": ["acme"]},
                ],
            }
        ],
        experience=_acme(
            {"label": "Reports", "text": "Wrote SQL reports."},
            {"label": "ETL", "text": "Rewrote the ETL in Python."},
        ),
    )
    result = _match(
        "## Requirements\n- Advanced SQL for analytics.\n- Modern Python tooling.\n", profile
    )
    assert {"SQL", "Python"} <= result["confirmed"]
    assert not {"Advanced SQL", "Modern Python"} & result["gaps"]


@pytest.mark.parametrize(
    "line", ["Apache Kafka at scale.", "Expert-level SQL.", "Production Apache Kafka."]
)
def test_a_qualifier_in_front_of_a_known_name_is_not_a_gap(line: str) -> None:
    """Apache Kafka is the profile's Kafka, and the lead word of "Expert-level" is a qualifier."""
    technologies = [
        {
            "group": "Data",
            "items": [
                {"name": "SQL", "used_at": ["acme"]},
                {"name": "Kafka", "used_at": ["acme"]},
            ],
        }
    ]
    assert (
        _match(f"## Requirements\n- {line}\n", _profile(technologies=technologies))["gaps"] == set()
    )


def test_a_known_name_inside_a_longer_product_name_is_still_a_gap() -> None:
    """Only a known qualifier is dropped in front of a known name; a product built on it stays.

    Spark SQL and Kafka Streams are not SQL and Kafka, and Microsoft SQL Server is not SQL.
    """
    profile = _profile(
        technologies=[
            {
                "group": "Data",
                "items": [
                    {"name": "SQL", "used_at": ["acme"]},
                    {"name": "Kafka", "used_at": ["acme"]},
                ],
            }
        ],
        experience=_acme({"label": "Reports", "text": "Wrote SQL reports fed from Kafka."}),
    )
    text = (
        "## Requirements\n- Spark SQL pipelines.\n- Kafka Streams in production.\n"
        "- Microsoft SQL Server administration.\n"
    )
    assert {"Spark SQL", "Kafka Streams", "Microsoft SQL Server"} <= _match(text, profile)["gaps"]


@pytest.mark.parametrize(
    ("line", "gap"),
    [
        # The profile knows "development", "continuous", "integration", "web" and "services"
        # only as fragments of longer names, which is no reason to drop the word before them.
        ("Java Development (5+ years).", "Java Development"),
        ("Rust Development experience.", "Rust Development"),
        ("Jenkins Continuous Integration pipelines.", "Jenkins Continuous Integration"),
        ("Ansible Infrastructure automation.", "Ansible Infrastructure"),
        ("Experience with Azure Web Services.", "Azure Web Services"),
        # A product in front of a known name is not a qualifier of it.
        ("Snowflake SQL and dbt.", "Snowflake SQL"),
        ("Azure Postgres at scale.", "Azure Postgres"),
    ],
)
def test_a_missing_technology_in_front_of_a_known_word_is_still_a_gap(line: str, gap: str) -> None:
    """Hiding a gap is the unsafe direction: the model is never told not to claim it."""
    technologies = [
        {
            "group": "Practice",
            "items": [
                {"name": "SQL", "used_at": ["acme"]},
                {"name": "PostgreSQL", "aliases": ["Postgres"], "used_at": ["acme"]},
                {"name": "Test-driven development", "used_at": ["acme"]},
                {"name": "Amazon Web Services (AWS)", "used_at": ["acme"]},
                {
                    "name": "CI/CD",
                    "aliases": ["Continuous Integration", "Continuous Delivery"],
                    "used_at": ["acme"],
                },
                {"name": "Terraform", "aliases": ["infrastructure as code"], "used_at": ["acme"]},
            ],
        }
    ]
    assert (
        gap in _match(f"## Requirements\n- {line}\n", _profile(technologies=technologies))["gaps"]
    )


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


@pytest.mark.parametrize(
    ("heading", "title", "company"),
    [
        ("Rust SRE - Contoso", "Rust SRE", "Contoso"),
        ("Contoso - Platform DevOps", "Platform DevOps", "Contoso"),
        ("Acme — Senior Backend Dev", "Senior Backend Dev", "Acme"),
    ],
)
def test_a_short_role_word_places_the_title(heading: str, title: str, company: str) -> None:
    posting = parse_posting(f"# {heading}\n\nBody.\n")
    assert (posting.title, posting.company) == (title, company)


@pytest.mark.parametrize(
    "heading",
    ["Northwind Freight - Widgets Division", "Senior Python Developer - Data Engineering"],
)
def test_a_heading_whose_halves_cannot_be_told_apart_names_no_company(heading: str) -> None:
    """Neither half, or both, reads as the role, so which one is the company is a guess."""
    posting = parse_posting(f"# {heading}\n\nBody.\n")
    assert (posting.title, posting.company) == (heading, "")


def test_a_guessed_company_never_masks_the_title_out_of_the_body() -> None:
    """Masking the title as if it were the company erased the posting's main requirement."""
    technologies = [
        {
            "group": "Languages",
            "items": [
                {"name": "Python", "level": "proficient", "used_at": ["acme"]},
                {"name": "Kubernetes", "level": "proficient", "used_at": ["acme"]},
            ],
        }
    ]
    profile = _profile(
        technologies=technologies,
        experience=_acme(
            {"label": "ETL", "text": "Rewrote the ETL in Python."},
            {"label": "Clusters", "text": "Ran Kubernetes clusters."},
        ),
    )
    body = "\n\n## Requirements\n- Python in production.\n- Kubernetes in production.\n"
    for heading in (
        "# Senior Python Developer - Data Engineering",
        "# Python and Kubernetes Wrangler - Contoso",
    ):
        assert {"Python", "Kubernetes"} <= _match(heading + body, profile)["confirmed"], heading
    rust = _match("# Rust SRE - Contoso\n\n## Requirements\n- Rust in production.\n", profile)
    assert "Rust" in rust["gaps"]


def test_generic_prose_is_not_reported_as_a_missing_technology() -> None:
    """Generic prose must not be reported as a technology the profile lacks."""
    text = (
        "# Staff Engineer — Acme\n\n## Requirements\n"
        "- Production experience with Apache Kafka at scale.\n"
        "- Strong ownership and a quality mindset across the platform.\n"
    )
    gaps = {gap.term.casefold() for gap in match_posting(text, _profile()).gaps}
    for noise in ("production", "ownership", "quality", "platform", "scale"):
        assert noise not in gaps, f"{noise} reported as a missing technology"


def test_a_bare_name_and_its_fuller_form_are_one_gap() -> None:
    """A posting naming both "Apache Kafka" and "Kafka" is missing one thing, not two."""
    text = (
        "# Staff Engineer — Acme\n\n## Requirements\n"
        "- Production experience with Apache Kafka.\n"
        "- Kafka tuning at scale.\n"
    )
    gaps = match_posting(text, _profile()).gaps
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
