"""The second read: what gets fixed unattended, what gets flagged, and what gets asked."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from resume_tailor.profile import loader
from resume_tailor.review import (
    MAX_QUESTIONS,
    Answer,
    Finding,
    Level,
    Question,
    Review,
    apply_fixes,
    check_linkedin,
    format_review,
    from_findings,
    gather,
    review_profile,
    review_resume,
    said,
)

CLEAN = """\
# Ada Lovelace
Principal Engineer
ada@example.com | London, UK

## Summary
Engineer who writes programs for engines that do not exist yet.

## Skills
**Languages:** Analytical Notation, Mathematics

## Experience

### Analytical Engine Programme – Principal Engineer
Jan 1843 – Present | London, UK
- **Algorithm Design:** Published the first algorithm intended for a machine, cutting hand work 90%.
- **Correspondence:** Cut the engine's error rate 40% by reviewing Babbage's semantics.
"""


def rules(markdown: str) -> list[str]:
    return [finding.rule for finding in review_resume(markdown).findings]


def bulleted(*bullets: str) -> str:
    """Return the clean resume with the current role's bullets replaced."""
    head = CLEAN.split("- **Algorithm Design:**", maxsplit=1)[0]
    return head + "\n".join(bullets) + "\n"


# --- a clean document -----------------------------------------------------------------------------
def test_a_clean_resume_has_nothing_to_say() -> None:
    assert review_resume(CLEAN).findings == ()
    assert apply_fixes(CLEAN) == (CLEAN, ())


# --- FIX ------------------------------------------------------------------------------------------
def test_doubled_and_trailing_spaces_are_fixed() -> None:
    text = CLEAN.replace("Published the", "Published  the").replace("Mathematics", "Mathematics  ")
    fixed, applied = apply_fixes(text)
    assert fixed == CLEAN
    assert [finding.rule for finding in applied] == ["whitespace", "whitespace"]


def test_comment_alignment_is_left_alone() -> None:
    text = "<!--\n  # Name      the name\n  aligned  -->\n" + CLEAN
    assert "whitespace" not in rules(text)
    assert apply_fixes(text)[0] == text


def test_a_lead_in_gets_its_space_and_its_capital() -> None:
    text = CLEAN.replace("**Algorithm Design:** Published", "**Algorithm Design:**published")
    fixed, applied = apply_fixes(text)
    assert fixed == CLEAN
    assert [finding.rule for finding in applied] == ["lead-in"]


def test_a_mixed_case_product_name_after_the_lead_in_is_not_capitalised() -> None:
    text = bulleted("- **Mobile:** iOS work cut crashes 50%.", "- **Web:** Cut load time 30%.")
    assert "lead-in" not in rules(text)


def test_a_lowercase_tool_name_after_the_lead_in_keeps_its_spelling() -> None:
    text = bulleted(
        "- **Tooling:** npm workspaces cut install time 40%.",
        "- **Data:**pandas pipelines cut report time 30%.",
        "- **Web:** cut load time 20%.",
    )
    fixed, applied = apply_fixes(text)
    assert "- **Tooling:** npm workspaces cut install time 40%." in fixed
    assert "- **Data:** pandas pipelines cut report time 30%." in fixed, "the space is still fixed"
    assert "- **Web:** Cut load time 20%." in fixed, "an ordinary word is still capitalised"
    assert [finding.rule for finding in applied] == ["lead-in", "lead-in"]


def test_a_tool_after_the_lead_in_is_spelled_the_way_the_skills_section_spells_it() -> None:
    text = bulleted(
        "- **Version control:** git branching cut merge conflicts 40%.",
        "- **Frontend:** yarn workspaces cut install time 25%.",
        "- **Modelling:** dbt models cut report time 30%.",
        "- **Proxy:** nginx caching cut latency 20%.",
        "- **Maths:** numpy vectorising cut run time 50%.",
        "- **Web:** cut load time 20%.",
    ).replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Tools:** Git, Yarn, nginx\n**Data:** dbt; Python (pandas, NumPy)",
    )
    fixed, _ = apply_fixes(text)
    assert "- **Version control:** Git branching cut merge conflicts 40%." in fixed
    assert "- **Frontend:** Yarn workspaces cut install time 25%." in fixed
    assert "- **Modelling:** dbt models cut report time 30%." in fixed
    assert "- **Proxy:** nginx caching cut latency 20%." in fixed
    assert "- **Maths:** NumPy vectorising cut run time 50%." in fixed, "from inside parentheses"
    assert "- **Web:** Cut load time 20%." in fixed, "a word Skills lacks is capitalised"


def test_a_tool_that_takes_a_capital_gets_one_when_the_skills_section_is_silent() -> None:
    text = bulleted(
        "- **Version control:** git branching cut merge conflicts 40%.",
        "- **Frontend:** yarn workspaces cut install time 25%.",
    )
    fixed, _ = apply_fixes(text)
    assert "- **Version control:** Git branching cut merge conflicts 40%." in fixed
    assert "- **Frontend:** Yarn workspaces cut install time 25%." in fixed


def test_a_skills_line_written_as_a_bullet_keeps_its_own_spelling() -> None:
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "- **Data:** dbt, Snowflake\n- **Tools:** git, Make",
    )
    fixed, _ = apply_fixes(text)
    assert "- **Data:** dbt, Snowflake\n- **Tools:** git, Make" in fixed


def test_a_missing_full_stop_follows_the_majority() -> None:
    text = bulleted(
        "- **A:** Cut costs 10%.",
        "- **B:** Cut latency 20%.",
        "- **C:** Cut errors 30%",
    )
    fixed, applied = apply_fixes(text)
    assert "- **C:** Cut errors 30%." in fixed
    assert [finding.rule for finding in applied] == ["full-stop"]


def test_no_full_stops_are_added_when_the_bullets_do_not_use_them() -> None:
    text = bulleted("- **A:** Cut costs 10%", "- **B:** Cut latency 20%")
    assert "full-stop" not in rules(text)


def test_a_bullet_ending_in_a_colon_is_left_open() -> None:
    text = bulleted(
        "- **A:** Cut costs 10%.", "- **B:** Cut latency 20%.", "- **C:** Cut errors 30%:"
    )
    assert "full-stop" not in rules(text)


def test_doubled_punctuation_and_a_space_before_a_mark_are_collapsed() -> None:
    text = CLEAN.replace("semantics.", "semantics ..").replace("machine,", "machine ,")
    fixed, applied = apply_fixes(text)
    assert fixed == CLEAN
    assert {finding.rule for finding in applied} == {"punctuation"}


def test_date_ranges_take_an_en_dash_and_present_is_capitalised() -> None:
    text = CLEAN.replace("Jan 1843 – Present", "Jan 1843 - present")
    fixed, applied = apply_fixes(text)
    assert fixed == CLEAN
    assert [finding.rule for finding in applied] == ["dates"]


def test_a_skill_listed_twice_is_dropped_from_the_later_group() -> None:
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Languages:** Analytical Notation, Mathematics\n**Theory:** mathematics, Logic (A, B)",
    )
    fixed, applied = apply_fixes(text)
    assert "**Theory:** Logic (A, B)" in fixed
    assert applied[0].text == "mathematics"


def test_a_skill_listed_twice_in_one_group_is_dropped_too() -> None:
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Languages:** Analytical Notation, Mathematics, analytical notation\n"
        "**Theory:** Logic, Mathematics",
    )
    fixed, applied = apply_fixes(text)
    assert "**Languages:** Analytical Notation, Mathematics\n" in fixed
    assert "**Theory:** Logic\n" in fixed
    assert [(finding.rule, finding.text) for finding in applied] == [
        ("duplicate-skill", "analytical notation"),
        ("duplicate-skill", "Mathematics"),
    ]


def test_a_skills_line_with_the_colon_after_the_bold_is_fixed_in_its_own_form() -> None:
    """``**Label**: items`` is a skills line too; a fix keeps the colon where the writer put it."""
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Languages**: Analytical Notation, Mathematics, Mathematics\n**Theory**: Mathematics",
    )
    fixed, applied = apply_fixes(text)
    assert "**Languages**: Analytical Notation, Mathematics\n**Theory**:\n" in fixed
    assert [finding.rule for finding in applied] == ["duplicate-skill", "duplicate-skill"]


def test_too_many_skills_counts_lines_with_the_colon_after_the_bold() -> None:
    items = ", ".join(f"Skill{index}" for index in range(45))
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics", f"**Languages**: {items}"
    )
    found = [finding for finding in review_resume(text).findings if finding.rule == "many-skills"]
    assert [finding.text for finding in found] == [items]


def test_a_group_left_with_nothing_keeps_its_label() -> None:
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Languages:** Analytical Notation, Mathematics\n**Again:** Mathematics",
    )
    assert "**Again:**\n" in apply_fixes(text)[0]


def test_two_fixes_on_one_line_take_two_rounds_and_then_settle() -> None:
    text = CLEAN.replace(
        "**Algorithm Design:** Published the", "**Algorithm Design:**published  the"
    )
    fixed, applied = apply_fixes(text)
    assert fixed == CLEAN
    assert sorted(finding.rule for finding in applied) == ["lead-in", "whitespace"]
    assert apply_fixes(fixed) == (fixed, ())


def test_fixes_settle_within_the_round_limit() -> None:
    """Four rules on one line take four rounds, one fix each; the loop then stops on its own."""
    text = bulleted(
        "- **A:** Cut costs 10%.",
        "- **B:** Cut latency 20%.",
        "- **C:**cut errors  30% , done",
    )
    fixed, applied = apply_fixes(text)
    assert "- **C:** Cut errors 30%, done." in fixed
    assert [finding.rule for finding in applied] == [
        "full-stop",
        "lead-in",
        "punctuation",
        "whitespace",
    ]


def test_a_fix_does_not_add_a_trailing_newline_that_was_not_there() -> None:
    text = CLEAN.rstrip("\n").replace("Mathematics", "Mathematics  ")
    fixed, _ = apply_fixes(text)
    assert not fixed.endswith("\n")


# --- ADVISE ---------------------------------------------------------------------------------------
def test_a_long_bullet_is_flagged() -> None:
    long = "- **A:** Cut costs 10% " + "by doing a great many careful things " * 6 + "in the end."
    assert "long-bullet" in rules(bulleted(long, "- **B:** Cut latency 20%."))


def test_a_long_summary_is_flagged() -> None:
    text = CLEAN.replace(
        "Engineer who writes programs for engines that do not exist yet.",
        "Engineer who writes programs. " * 20,
    )
    assert "long-summary" in rules(text)


def test_too_many_bullets_under_one_role() -> None:
    text = bulleted(*(f"- **B{index}:** Cut something {index}0%." for index in range(1, 8)))
    assert "many-bullets" in rules(text)


def test_too_many_skills() -> None:
    items = ", ".join(f"Skill{index}" for index in range(45))
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics", f"**Languages:** {items}"
    )
    assert "many-skills" in rules(text)


def test_semicolon_chains() -> None:
    text = bulleted("- **A:** Cut costs 10%; cut latency 20%; cut errors 30%; cut churn 40%.")
    assert "semicolons" in rules(text)


def test_tense_drift_within_a_role() -> None:
    drifting = bulleted(
        "- **A:** Architecting the engine, 50% faster.", "- **B:** Led the 3-person team."
    )
    assert "tense" in rules(drifting)
    steady = bulleted(
        "- **A:** Architected the engine, 50% faster.", "- **B:** Led the 3-person team."
    )
    assert "tense" not in rules(steady)


def test_weak_openers() -> None:
    text = bulleted("- **A:** Responsible for cutting costs 10%.")
    assert "weak-opener" in rules(text)


def test_filler_words() -> None:
    text = bulleted("- **A:** Leveraged a robust, seamless pipeline to cut costs 10%.")
    finding = next(f for f in review_resume(text).findings if f.rule == "filler")
    assert "leveraged" in finding.message
    assert "robust" in finding.message


def test_repeated_phrases_are_flagged_once_per_pair() -> None:
    text = bulleted(
        "- **A:** Cut the cost of the nightly batch run 10%.",
        "- **B:** Cut the cost of the nightly batch run again, 5%.",
    )
    repeats = [f for f in review_resume(text).findings if f.rule == "repetition"]
    assert len(repeats) == 1
    assert "from line" in repeats[0].message


def test_stopword_only_phrases_are_not_repetition() -> None:
    text = bulleted(
        "- **A:** Cut costs 10% for the one and the other.",
        "- **B:** Cut errors 20% for the one and the rest.",
    )
    assert "repetition" not in rules(text)


# --- ASK ------------------------------------------------------------------------------------------
def test_a_bullet_without_an_outcome_is_a_question() -> None:
    text = bulleted(
        "- **A:** Corresponded with Babbage on engine semantics.", "- **B:** Cut costs 10%."
    )
    findings = review_resume(text).findings
    asked = [f for f in findings if f.rule == "no-outcome"]
    assert [f.level for f in asked] == [Level.ASK]
    assert asked[0].text.startswith("Corresponded")
    with_verb = bulleted("- **A:** Shipped the engine's scheduler.", "- **B:** Cut costs 10%.")
    assert "no-outcome" not in rules(with_verb)


def test_missing_summary_contact_dates_and_bullets_are_questions() -> None:
    text = "# Ada\n\n## Experience\n\n### Acme – Engineer\n\n### Beta – Engineer\n2020 – 2021\n"
    found = {f.rule: f for f in review_resume(text).findings}
    assert {"no-summary", "no-contact", "no-dates", "no-bullets"} <= set(found)
    assert found["no-dates"].text == "Acme – Engineer"
    assert all(f.level is Level.ASK for f in found.values())


def test_a_current_role_with_no_numbers_is_a_question() -> None:
    text = bulleted("- **A:** Shipped the scheduler.", "- **B:** Launched the engine.")
    assert "no-numbers" in rules(text)


def test_a_document_with_no_headings_still_reviews() -> None:
    findings = review_resume("# Ada\n\nJust prose.\n").findings
    assert {f.rule for f in findings} == {"no-summary", "no-contact"}


# --- reports --------------------------------------------------------------------------------------
def test_format_review_lists_what_was_fixed_and_what_is_still_advised() -> None:
    review = Review(
        (
            Finding("tense", Level.ADVISE, 12, "Acme – Engineer", "bullets switch tense"),
            Finding("no-outcome", Level.ASK, 14, "Did a thing", "What did this achieve?"),
        ),
        applied=(Finding("dates", Level.FIX, 9, "2020 - now", "an en dash", "2020 – now"),),
    )
    text = format_review(review, title="Review")
    assert text == (
        "Review: 1 fixed · 1 suggestion\n"
        "  ✓ dates: an en dash\n"
        '      "2020 - now"\n'
        "  ~ line 12  tense: bullets switch tense\n"
        '      "Acme – Engineer"\n'
    ), "each fix says what it changed; questions are asked, not listed here"


def test_a_fix_that_removed_a_skill_names_the_skill() -> None:
    """The fix that drops content is the one the candidate most needs to see."""
    text = CLEAN.replace(
        "**Languages:** Analytical Notation, Mathematics",
        "**Languages:** Analytical Notation, Mathematics\n**Theory:** Mathematics, Logic",
    )
    fixed, applied = apply_fixes(text)
    assert format_review(Review(review_resume(fixed).findings, applied)) == (
        "Review: 1 fixed · 0 suggestions\n"
        "  ✓ duplicate-skill: listed twice in Skills, so the repeat was removed\n"
        '      "Mathematics"\n'
    )


def test_fixes_of_one_kind_are_listed_once_with_the_first_few_quoted() -> None:
    long = "Cut the cost of the nightly batch run by rewriting the scheduler from scratch"
    applied = (
        *(
            Finding("full-stop", Level.FIX, line, f"{long} {line}", "added a full stop", "")
            for line in range(10, 15)
        ),
        Finding("whitespace", Level.FIX, 3, "", "removed doubled or trailing spaces", ""),
    )

    text = format_review(Review(applied=applied))

    assert text == (
        "Review: 6 fixed · 0 suggestions\n"
        "  ✓ full-stop: added a full stop (5 lines)\n"
        '      "Cut the cost of the nightly batch run by rewriting the sche…"\n'
        '      "Cut the cost of the nightly batch run by rewriting the sche…"\n'
        '      "Cut the cost of the nightly batch run by rewriting the sche…"\n'
        "      … and 2 more\n"
        "  ✓ whitespace: removed doubled or trailing spaces\n"
    )


def test_a_finding_without_a_line_or_quote_prints_without_them() -> None:
    review = Review((Finding("no-level", Level.ADVISE, 0, "", "2 technologies have no level"),))
    assert (
        format_review(review)
        == "Review: 1 suggestion\n  ~ no-level: 2 technologies have no level\n"
    )


def test_nothing_to_say_still_says_so() -> None:
    assert format_review(Review()) == "Review: 0 suggestions\n"


# --- the profile ----------------------------------------------------------------------------------
TODAY = date(2026, 9, 25)

MINIMAL: dict[str, Any] = {
    "contact": {"name": "Ada", "headline": "Engineer", "email": "ada@example.com"},
    "summary": "Writes programs for engines.",
    "experience": [
        {
            "id": "engine",
            "company": "Analytical Engine Programme",
            "roles": [
                {
                    "title": "Principal Engineer",
                    "start": "2019-01",
                    "end": "present",
                    "highlights": [{"label": "Scheduler", "text": "Cut runtime 38%."}],
                }
            ],
        }
    ],
}


def audit(data: dict[str, Any]) -> Review:
    return review_profile(loader.load_mapping(data), today=TODAY)


def advised(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(f.rule, f.text, f.message) for f in audit(data).advice]


def test_a_tidy_profile_reviews_clean() -> None:
    assert audit(MINIMAL) == Review()


def test_the_audit_defaults_to_today() -> None:
    assert review_profile(loader.load_mapping(MINIMAL)) == Review()


def test_profile_review_turns_notes_into_questions() -> None:
    questions = audit({**MINIMAL, "notes": ["Confirm the phone number."]}).questions
    assert [(f.rule, f.message) for f in questions] == [("note", "Confirm the phone number.")]


def test_notes_come_before_roles_with_no_highlights() -> None:
    """The notes are ordered most consequential first; a list of early jobs must not bury them."""
    data = {
        **MINIMAL,
        "experience": [
            *MINIMAL["experience"],
            _employer("Shop", {"title": "Developer", "start": "2010", "end": "2012"}),
        ],
        "notes": ["Was it 38% or 45%?"],
    }
    assert [f.rule for f in audit(data).questions] == ["note", "no-highlights"]


def test_profile_review_flags_what_would_print_badly() -> None:
    data = {
        **MINIMAL,
        "summary": " ".join(["word"] * 91),
        "technologies": [
            {"group": "A", "items": [{"name": "Python", "level": "expert"}, {"name": "Go"}]},
            {"group": "B", "items": [{"name": "python"}]},
        ],
        "experience": [
            {
                "id": "engine",
                "company": "Analytical Engine Programme",
                "roles": [
                    {
                        "title": "Principal Engineer",
                        "start": "2019-01",
                        "end": "present",
                        "highlights": [
                            {"text": "Cut runtime 38%."},
                            {"label": "Long", "text": " ".join(f"w{n}" for n in range(46))},
                        ],
                    },
                    {"title": "Translator", "start": "2017", "end": "2018"},
                ],
            }
        ],
    }
    review = audit(data)
    assert [f.rule for f in review.advice] == [
        "long-summary",
        "no-label",
        "long-highlight",
        "duplicate-technology",
        "no-level",
    ]
    assert [f.text for f in review.advice][1:3] == [
        "experience[0].roles[0].highlights[0]",
        "experience[0].roles[0].highlights[1]",
    ]
    assert "'python' appears 2 times" in review.advice[3].message
    assert "2 technologies have no level (Go, python)" in review.advice[-1].message
    assert "add a level by hand (expert, proficient, working or exposure) to each one you know" in (
        review.advice[-1].message
    ), "only the candidate can settle it, so the advice says how"
    assert [f.rule for f in review.questions] == ["no-highlights"]
    assert "Translator at Analytical Engine Programme" in review.questions[0].message


def test_profile_review_abbreviates_a_long_list_of_unrated_technologies() -> None:
    items = [{"name": f"T{index}"} for index in range(7)]
    message = audit({**MINIMAL, "technologies": [{"group": "A", "items": items}]}).advice[0].message
    assert "T0, T1, T2, T3, T4, …" in message


def _employer(company: str, *roles: dict[str, Any], ident: str = "") -> dict[str, Any]:
    return {
        "id": ident or company.lower().replace(" ", "-"),
        "company": company,
        "roles": list(roles),
    }


def _held(title: str, start: str, end: str, *texts: str) -> dict[str, Any]:
    return {
        "title": title,
        "start": start,
        "end": end,
        "highlights": [{"label": f"L{n}", "text": text} for n, text in enumerate(texts)],
    }


def test_one_employer_recorded_twice_is_flagged() -> None:
    data = {
        **MINIMAL,
        "experience": [
            _employer("Acme, Inc.", _held("Lead", "2022", "present", "Led it."), ident="acme"),
            _employer("Acme", _held("Engineer", "2019", "2022", "Built it."), ident="acme-2"),
        ],
    }
    assert advised(data) == [
        (
            "duplicate-employer",
            "experience[1]",
            (
                "Acme is recorded twice (experience[0] and experience[1]); merge them into one "
                "employer, each title a role"
            ),
        )
    ]


def test_employers_and_roles_out_of_order_are_flagged() -> None:
    data = {
        **MINIMAL,
        "experience": [
            _employer("Old Co", _held("Engineer", "2015", "2017", "Built it.")),
            _employer(
                "New Co",
                _held("Engineer", "2018", "2020", "Built more."),
                _held("Lead", "2020", "present", "Led it."),
            ),
        ],
    }
    assert [(rule, where) for rule, where, _ in advised(data)] == [
        ("employer-order", "experience[1]"),
        ("role-order", "experience[1].roles[1]"),
    ]


def test_roles_held_at_once_are_flagged_but_a_shared_boundary_month_is_not() -> None:
    def roles(second_start: str) -> dict[str, Any]:
        return {
            **MINIMAL,
            "experience": [
                _employer(
                    "Acme",
                    _held("Lead", second_start, "present", "Led it."),
                    _held("Engineer", "2019-01", "2022-06", "Built it."),
                )
            ],
        }

    assert advised(roles("2022-06")) == []
    assert advised(roles("2022-05")) == [], "one month of drift is how dates copy"
    assert [rule for rule, _, _ in advised(roles("2022-03"))] == ["overlapping-roles"]


def test_a_year_only_overlap_is_judged_by_the_year() -> None:
    data = {
        **MINIMAL,
        "experience": [
            _employer(
                "Acme",
                _held("Lead", "2021", "present", "Led it."),
                _held("Engineer", "2019", "2022", "Built it."),
            )
        ],
    }
    assert [rule for rule, _, _ in advised(data)] == ["overlapping-roles"]


def test_a_highlight_mentioning_a_year_after_its_role_ended_is_flagged() -> None:
    data = {
        **MINIMAL,
        "experience": [
            _employer(
                "Acme",
                _held("Lead", "2022-06", "present", "Led it."),
                _held(
                    "Engineer",
                    "2019-01",
                    "2022-06",
                    "Since 2024, built the assistant.",
                    "In 2020, shipped it.",
                ),
            )
        ],
    }
    assert advised(data) == [
        (
            "highlight-after-role",
            "experience[0].roles[1].highlights[0]",
            (
                "mentions 2024, after this role ended (June 2022); it probably belongs under a "
                "later role"
            ),
        )
    ]


def test_a_number_that_only_looks_like_a_year_is_not_read_as_one() -> None:
    """2048-bit keys under a role that ended in 2022 belong exactly where they are."""
    data = {
        **MINIMAL,
        "experience": [
            _employer(
                "Acme",
                _held("Lead", "2022-06", "present", "Led it."),
                _held(
                    "Engineer",
                    "2019-01",
                    "2022-06",
                    "Rotated the pipeline's 2048-bit signing keys with no downtime.",
                    "Held p99 under 2000ms and saved $2050 a month.",
                    "Grew traffic 2030% in a year.",
                    "Set the roadmap through 2031.",
                ),
            )
        ],
    }
    assert advised(data) == [], "a unit, an amount, a percentage and a year still to come"


def test_a_highlight_recorded_twice_is_flagged_even_when_reworded() -> None:
    data = {
        **MINIMAL,
        "experience": [
            _employer(
                "Acme",
                _held(
                    "Lead",
                    "2019-01",
                    "present",
                    "Cut batch runtime 38% by rewriting the scheduler in Python.",
                    "Rewrote the scheduler in Python, cutting batch runtime 38%.",
                    "Mentored junior developers.",
                    "Mentored and developed junior developers across two teams.",
                    "Shipped the billing export.",
                ),
            )
        ],
    }
    assert [(rule, where) for rule, where, _ in advised(data)] == [
        ("duplicate-highlight", "experience[0].roles[0].highlights[1]"),
        ("duplicate-highlight", "experience[0].roles[0].highlights[3]"),
    ]


def test_a_spelling_that_names_two_technologies_is_flagged() -> None:
    data = {
        **MINIMAL,
        "technologies": [
            {
                "group": "Cloud",
                "items": [
                    {"name": "Amazon Web Services", "aliases": ["AWS"], "level": "expert"},
                    {"name": "AWS", "level": "expert"},
                ],
            }
        ],
    }
    assert advised(data) == [
        (
            "duplicate-technology",
            "technologies",
            (
                "'aws' names both amazon web services and aws; record it once, other spellings "
                "as aliases"
            ),
        )
    ]


def test_more_years_than_the_career_is_flagged() -> None:
    data = {
        **MINIMAL,
        "technologies": [
            {"group": "L", "items": [{"name": "Python", "level": "expert", "years": 12}]}
        ],
    }
    assert advised(data) == [
        (
            "technology-years",
            "technologies",
            "Python: 12 years, but the earliest role recorded starts in 2019",
        )
    ]


def test_a_stack_naming_an_unrecorded_technology_is_flagged() -> None:
    data = {
        **MINIMAL,
        "technologies": [
            {"group": "L", "items": [{"name": "Amazon Web Services (AWS)", "level": "expert"}]}
        ],
        "experience": [
            {
                **MINIMAL["experience"][0],
                "roles": [{**MINIMAL["experience"][0]["roles"][0], "stack": ["AWS", "Go"]}],
            }
        ],
    }
    assert advised(data) == [
        (
            "stack-unrecorded",
            "experience[0].roles[0]",
            (
                "stack names Go, which technologies does not record; add them there or drop "
                "them from the stack"
            ),
        )
    ]


# --- questions ------------------------------------------------------------------------------------
def test_questions_merge_in_priority_order_without_repeats_and_are_capped() -> None:
    first = (Question("Have you used Kafka?"),)
    second = (Question("Have you used  kafka?"), Question("How big was the team?"))
    many = tuple(Question(f"Question {n}?") for n in range(10))

    merged = gather(first, second, many)

    assert [q.text for q in merged[:2]] == ["Have you used Kafka?", "How big was the team?"]
    assert len(merged) == MAX_QUESTIONS
    assert gather(first, many, limit=2) == (first[0], many[0])
    assert gather((Question("?!"),)) == (), "a question with no words is no question"


def test_ask_findings_become_questions_and_the_rest_are_left_out() -> None:
    findings = (
        Finding("no-outcome", Level.ASK, 3, "Did a thing", "What did this achieve?"),
        Finding("no-dates", Level.ASK, 5, "Acme – Engineer", "When was this?"),
        Finding("tense", Level.ADVISE, 7, "", "bullets switch tense"),
    )
    assert from_findings(findings, skip=("no-outcome",)) == (
        Question("When was this?", "Acme – Engineer"),
    )


def test_an_answer_that_declines_gives_the_profile_nothing() -> None:
    question = Question("Have you used Kafka?")
    assert Answer(question, "Yes, for 2 years at Acme.").substantive
    for declined in ("no", "No.", "  nope ", "Not sure", "", "n/a", "I haven't"):
        assert not Answer(question, declined).substantive, declined


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Have you done on-call?", "Nope, never done on-call."),
        ("Have you used Kafka?", "No, I have not."),
        ("Have you used Apache Spark?", "I'm not sure."),
        ("Have you used Apache Spark?", "Probably not."),
        ("What did this achieve?", "I’m not sure, I don’t remember the numbers."),
        ("Have you used Kafka?", "I'm afraid not, sorry."),
        ("Have you used Kafka?", "Not that I know of."),
        ("Have you used Kafka?", "Nothing comes to mind."),
    ],
)
def test_a_decline_or_a_hedge_worded_as_a_sentence_gives_nothing(
    question: str, answer: str
) -> None:
    assert not Answer(Question(question), answer).substantive


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Have you led a migration?", "No, but I led the migration in 2021"),
        ("Have you led a migration?", "No, but I led the payments migration."),
        ("Was it RabbitMQ?", "No, it was Kafka."),
        ("Did you use Kafka or Kinesis?", "Not Kafka, Kinesis."),
        ("Did you use Kafka or Kinesis?", "Not Kafka but Kinesis."),
        ("What did the rewrite achieve?", "Never had an outage after the rewrite."),
        ("What did the rewrite achieve?", "None of the 12 services went down."),
        ("Have you used Terraform?", "Notably, yes: two years."),
    ],
)
def test_an_answer_that_opens_with_a_no_but_says_more_is_a_fact(question: str, answer: str) -> None:
    assert Answer(Question(question), answer).substantive


def test_what_an_answer_establishes_includes_the_question_it_accepts() -> None:
    """A yes to "Have you used Kafka?" establishes Kafka; a no establishes nothing."""
    answers = (
        Answer(Question("Have you used Kafka?"), "No."),
        Answer(Question("Have you used Rust?"), "Not really, only a tutorial."),
        Answer(Question("Have you used Go?"), "I haven't."),
        Answer(Question("How big was the team?"), "Twelve."),
        Answer(Question("Have you used Terraform?"), "Notably, yes: two years."),
    )
    assert said(answers) == (
        "No.\nNot really, only a tutorial.\nI haven't.\nHow big was the team?\nTwelve.\n"
        "Have you used Terraform?\nNotably, yes: two years."
    )


def test_an_unsure_answer_never_licenses_what_it_was_asked() -> None:
    """An "I'm not sure" to "Have you used Apache Spark?" must not let an update add Spark."""
    answers = (
        Answer(Question("Have you used Apache Spark?"), "I’m not sure, maybe at Cedar."),
        Answer(Question("Which year did it ship?"), "Probably 2019."),
    )
    assert said(answers) == "I’m not sure, maybe at Cedar.\nProbably 2019."


# --- LinkedIn -------------------------------------------------------------------------------------
LINKEDIN = """\
# Ada Lovelace

## Headline
Principal Engineer | Python

## About
I write programs for engines.

## Top Skills
**Top Skills:** Python, Go

## Experience

### **Principal Engineer** – Analytical Engine Programme
January 2021 – Present | London, UK
I lead the programming.
- Cut batch runtime 38%.
**Skills:** Python

## Skills
**Skills:** Python, Go
- Rust
"""


def test_a_linkedin_profile_within_the_limits_passes() -> None:
    assert check_linkedin(LINKEDIN) == ()


def test_a_missing_linkedin_section_is_named() -> None:
    assert check_linkedin("# Ada\n<!-- ## About -->\n## Headline\nEngineer\n") == (
        "the ## About section is missing",
        "the ## Experience section is missing",
        "the ## Skills section is missing",
    )


def test_top_skills_written_without_a_label_are_still_counted() -> None:
    unlabelled = LINKEDIN.replace(
        "**Top Skills:** Python, Go", "Python, Go, Rust, Haskell, Scala, Elixir, Zig"
    )
    assert check_linkedin(unlabelled) == ("7 top skills; LinkedIn pins at most 5",)
    bulleted = LINKEDIN.replace(
        "**Top Skills:** Python, Go", "- Python, Go, Rust\n- Zig · OCaml · Elm"
    )
    assert check_linkedin(bulleted) == ("6 top skills; LinkedIn pins at most 5",)


def test_a_label_with_the_colon_after_the_bold_is_read_like_any_other() -> None:
    """``**Skills**: a`` is a skills line, not a sentence, and not part of a role's description."""
    one = LINKEDIN.replace(
        "**Top Skills:** Python, Go", "**Top Skills**: Python, Go, Rust, Zig, Elm"
    )
    assert check_linkedin(one.replace("Elm", "Elm, OCaml")) == (
        "6 top skills; LinkedIn pins at most 5",
    )
    assert check_linkedin(one) == ()
    long_skills = "**Skills**: " + ", ".join(["Python"] * 700)
    described = LINKEDIN.replace("**Skills:** Python\n\n## Skills", f"{long_skills}\n\n## Skills")
    assert check_linkedin(described) == (), "a role's skills line is not its description"


def test_a_plain_sentence_in_a_skills_section_is_not_counted_as_skills() -> None:
    introduced = LINKEDIN.replace(
        "**Top Skills:** Python, Go", "The five I am known for:\n**Top Skills:** A, B, C, D, E"
    )
    assert check_linkedin(introduced) == ()


def test_every_linkedin_limit_is_enforced() -> None:
    too_long = LINKEDIN.replace("Principal Engineer | Python", "x" * 221)
    too_long = too_long.replace("I write programs for engines.", "y" * 2601)
    too_long = too_long.replace("I lead the programming.", "z" * 2001)
    too_long = too_long.replace("Python, Go\n\n## Experience", "A, B, C, D, E, F\n\n## Experience")
    too_long = too_long.replace("- Rust", "\n".join(f"- S{n}" for n in range(100)))

    assert check_linkedin(too_long) == (
        "the headline is 221 characters; LinkedIn stops at 220",
        "the About section is 2601 characters; LinkedIn stops at 2600",
        # The outcomes beneath it are part of the description LinkedIn counts.
        (
            "the description for **Principal Engineer** – Analytical Engine Programme is 2026 "
            "characters; LinkedIn stops at 2000"
        ),
        "6 top skills; LinkedIn pins at most 5",
        "102 skills; LinkedIn takes at most 100",
    )
