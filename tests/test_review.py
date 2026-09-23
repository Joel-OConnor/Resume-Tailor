"""The second read: what gets fixed unattended, what gets flagged, and what gets asked."""

from __future__ import annotations

from typing import Any

from resume_tailor.profile import loader
from resume_tailor.review import (
    Finding,
    Level,
    Review,
    apply_fixes,
    format_review,
    render_markdown,
    review_and_fix,
    review_profile,
    review_resume,
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
    fixed, review = review_and_fix(CLEAN)
    assert fixed == CLEAN
    assert review == Review()


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


def test_a_lowercase_product_name_after_the_lead_in_is_not_capitalised() -> None:
    text = bulleted("- **Mobile:** iOS work cut crashes 50%.", "- **Web:** Cut load time 30%.")
    assert "lead-in" not in rules(text)


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
def test_format_review_lists_fixes_advice_and_questions() -> None:
    review = Review(
        (
            Finding("tense", Level.ADVISE, 12, "Acme – Engineer", "bullets switch tense"),
            Finding("no-outcome", Level.ASK, 14, "Did a thing", "What did this achieve?"),
        ),
        applied=(Finding("dates", Level.FIX, 9, "2020 - now", "an en dash", "2020 – now"),),
    )
    text = format_review(review)
    assert text.startswith("Readability: 1 fixed · 1 suggestions · 1 questions\n")
    assert "  ✓ line 9  dates: an en dash" in text
    assert '  ~ line 12  tense: bullets switch tense\n      "Acme – Engineer"' in text
    assert "  ? line 14  no-outcome: What did this achieve?" in text


def test_a_pending_fix_is_listed_and_marked() -> None:
    review = Review((Finding("dates", Level.FIX, 9, "2020 - now", "an en dash", "2020 – now"),))
    text = format_review(review)
    assert text.startswith("Readability: 0 fixed · 1 to fix · 0 suggestions · 0 questions\n")
    assert "  ✓ line 9  dates: an en dash (not applied)" in text


def test_a_finding_without_a_line_prints_without_one() -> None:
    review = Review((Finding("note", Level.ASK, 0, "notes", "Confirm the phone number."),))
    assert "  ? note: Confirm the phone number." in format_review(review)


def test_render_markdown_says_so_when_there_is_nothing_to_flag() -> None:
    assert render_markdown(Review()) == "## Readability review\n\nNothing to flag.\n"


def test_render_markdown_groups_findings_by_kind() -> None:
    review = Review(
        (Finding("no-outcome", Level.ASK, 14, "Did a thing", "What did this achieve?"),),
        applied=(Finding("dates", Level.FIX, 9, "2020 - now", "an en dash", "2020 – now"),),
    )
    text = render_markdown(review)
    assert "**Fixed automatically**\n\n- line 9 dates: an en dash\n" in text
    assert (
        '**Questions for you**\n\n- line 14 no-outcome: What did this achieve? ("Did a thing")'
        in text
    )
    assert "**Suggestions**" not in text


# --- the profile ----------------------------------------------------------------------------------
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
                    "start": "1843-01",
                    "end": "present",
                    "highlights": [{"label": "Scheduler", "text": "Cut runtime 38%."}],
                }
            ],
        }
    ],
}


def test_a_tidy_profile_reviews_clean() -> None:
    assert review_profile(loader.load_mapping(MINIMAL)) == Review()


def test_profile_review_turns_notes_into_questions() -> None:
    profile = loader.load_mapping({**MINIMAL, "notes": ["Confirm the phone number."]})
    questions = review_profile(profile).questions
    assert [(f.rule, f.message) for f in questions] == [("note", "Confirm the phone number.")]


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
                        "start": "1843-01",
                        "end": "present",
                        "highlights": [
                            {"text": "Cut runtime 38%."},
                            {"label": "Long", "text": " ".join(["word"] * 46)},
                        ],
                    },
                    {"title": "Translator", "start": "1842", "end": "1843"},
                ],
            }
        ],
    }
    review = review_profile(loader.load_mapping(data))
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
    assert "2 technologies have no level (Go, python)" in review.advice[-1].message
    assert [f.rule for f in review.questions] == ["no-highlights"]
    assert "Translator at Analytical Engine Programme" in review.questions[0].message


def test_profile_review_abbreviates_a_long_list_of_unrated_technologies() -> None:
    items = [{"name": f"T{index}"} for index in range(7)]
    profile = loader.load_mapping({**MINIMAL, "technologies": [{"group": "A", "items": items}]})
    message = review_profile(profile).advice[0].message
    assert "T0, T1, T2, T3, T4, …" in message
