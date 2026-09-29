"""The guard on profile rewrites: refining keeps every fact, an update adds only what was said."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest

from resume_tailor.profile import load_mapping
from resume_tailor.verify.changes import check_refinement, check_update, describe_changes

if TYPE_CHECKING:
    from collections.abc import Callable

    from resume_tailor.profile.models import Profile

_BASE: dict[str, Any] = {
    "contact": {
        "name": "Ada Lovelace",
        "headline": "Principal Engineer",
        "email": "ada@example.com",
        "phone": "(555) 010-0100",
        "links": [{"label": "GitHub", "url": "https://github.com/ada"}],
    },
    "summary": "Engineer who writes programs for engines that do not exist yet.",
    "technologies": [
        {
            "group": "Languages",
            "items": [
                {"name": "Python", "level": "proficient", "years": 5, "used_at": ["engine"]},
                {"name": "Kubernetes", "aliases": ["K8s"], "level": "working", "years": 2},
                {"name": "Scheduler rewrite"},
            ],
        }
    ],
    "experience": [
        {
            "id": "engine",
            "company": "Analytical Engine Programme, Inc.",
            "roles": [
                {
                    "title": "Principal Engineer",
                    "start": "2021-01",
                    "end": "present",
                    "highlights": [
                        {"label": "Scheduler", "text": "Cut batch runtime 38% on AWS EC2."},
                        {"text": "Led a team of 12 engineers from 2021."},
                    ],
                },
                {"title": "Engineer", "start": "2018-06", "end": "2021-01"},
            ],
        },
        {
            "id": "mill",
            "company": "Babbage Mill",
            "roles": [{"title": "Analyst", "start": "2015", "end": "2018"}],
        },
    ],
    "education": [{"credential": "Private tuition", "institution": "De Morgan"}],
    "certifications": [{"name": "Fellow of the Analytical Society", "year": "2019"}],
    "notes": ["Was the team 12 or 14 engineers?"],
}


def profile(edit: Callable[[dict[str, Any]], None] | None = None) -> Profile:
    """Return the base profile, optionally after ``edit`` changes a deep copy of its data."""
    data = copy.deepcopy(_BASE)
    if edit is not None:
        edit(data)
    return load_mapping(data)


def _role(data: dict[str, Any], tenure: int = 0, index: int = 0) -> dict[str, Any]:
    role: dict[str, Any] = data["experience"][tenure]["roles"][index]
    return role


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = data["technologies"][0]["items"]
    return items


# --- refinement: nothing added, nothing lost ------------------------------------------------------
def test_an_unchanged_profile_is_a_clean_refinement() -> None:
    assert check_refinement(profile(), profile()) == ()


def test_merging_duplicates_and_dropping_noise_is_what_refining_is_for() -> None:
    def refine(data: dict[str, Any]) -> None:
        _items(data).pop()  # "Scheduler rewrite" is an accomplishment, not a skill
        _role(data)["highlights"][1]["text"] = "Led a 12-engineer team from 2021."
        data["experience"][0]["company"] = "Analytical Engine Programme"  # legal suffix only
        data["summary"] = "Engineer who programs engines that do not exist yet."

    assert check_refinement(profile(), profile(refine)) == ()


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (
            lambda d: d["contact"].update(email="ada@other.example"),
            "changed contact.email from 'ada@example.com'",
        ),
        (
            lambda d: d["contact"]["links"].append({"label": "X", "url": "https://x.com/ada"}),
            "added the link 'https://x.com/ada'",
        ),
        (lambda d: d["contact"].update(links=[]), "dropped the link 'https://github.com/ada'"),
        (lambda d: d["experience"].pop(), "dropped the employer 'Babbage Mill'"),
        (
            lambda d: d["experience"].append(
                {
                    "id": "x",
                    "company": "Hooli",
                    "roles": [{"title": "CEO", "start": "2020", "end": "2021"}],
                }
            ),
            "added the employer 'Hooli'",
        ),
        (
            lambda d: _role(d).update(title="Chief Engineer"),
            "added the role Chief Engineer at Analytical Engine Programme, Inc.",
        ),
        (
            lambda d: d["experience"][1]["roles"][0].update(start="2014"),
            "added the role Analyst at Babbage Mill (2014 – 2018)",
        ),
        (lambda d: d.update(education=[]), "dropped 'Private tuition (De Morgan)'"),
        (
            lambda d: d.update(awards=[{"name": "Turing Award"}]),
            "added 'Turing Award', which the draft does not have",
        ),
        (
            lambda d: _items(d).append({"name": "Rust"}),
            "recorded 'Rust' as a technology, which the draft does not record",
        ),
        (
            lambda d: _items(d)[1].update(aliases=["K8s", "Nomad"]),
            "recorded 'Nomad' as a technology",
        ),
        (
            lambda d: _items(d)[1].update(level="expert"),
            "raised Kubernetes from working to expert; refining never raises it",
        ),
        (
            lambda d: _items(d)[0].update(years=9),
            "raised Python from 5 to 9 years; refining never raises it",
        ),
        (
            lambda d: _role(d)["highlights"][0].update(text="Cut batch runtime 45% on AWS EC2."),
            "introduced the figure '45%', which the draft does not state",
        ),
        (
            lambda d: _role(d)["highlights"][0].update(text="Cut batch runtime on AWS EC2."),
            "lost the figure '38%'",
        ),
    ],
)
def test_refining_may_not_add_lose_or_promote(
    edit: Callable[[dict[str, Any]], None], expected: str
) -> None:
    problems = check_refinement(profile(), profile(edit))
    assert any(expected in problem for problem in problems), problems


def test_a_duplicate_role_may_be_merged_into_the_one_that_covers_it() -> None:
    def duplicated(data: dict[str, Any]) -> None:
        _role(data, 0, 1)["title"] = "Senior Engineer"
        data["experience"][0]["roles"].insert(
            2, {"title": "Senior Engineer", "start": "2018-07", "end": "2021-01"}
        )

    def merged(data: dict[str, Any]) -> None:
        _role(data, 0, 1)["title"] = "Senior Engineer"

    assert check_refinement(profile(duplicated), profile(merged)) == ()


def test_a_figure_moved_into_a_note_is_not_lost() -> None:
    """A contradiction the documents cannot settle goes to notes, figure and all."""

    def to_note(data: dict[str, Any]) -> None:
        _role(data)["highlights"][1]["text"] = "Led the engineering team from 2021."
        data["notes"] = ["The team was 12 or 14 engineers — which?"]

    assert check_refinement(profile(), profile(to_note)) == ()


def test_a_year_that_is_already_a_date_is_not_a_new_figure() -> None:
    def dated(data: dict[str, Any]) -> None:
        _role(data)["highlights"][0]["text"] = "Cut batch runtime 38% on AWS EC2 in 2018."

    assert check_refinement(profile(), profile(dated)) == ()


def test_a_figure_promoted_out_of_the_notes_is_an_invention() -> None:
    """Notes are unconfirmed; moving one of their figures into a highlight asserts it."""

    def promoted(data: dict[str, Any]) -> None:
        _role(data)["highlights"][1]["text"] = "Led a team of 12 engineers (14 at peak) from 2021."

    problems = check_refinement(profile(), profile(promoted))
    assert problems == ("introduced the figure '14', which the draft does not state",)


# --- an update: only what the answers say ---------------------------------------------------------
def test_an_update_may_add_what_the_answer_states() -> None:
    def answered(data: dict[str, Any]) -> None:
        data["experience"].append(
            {
                "id": "jacquard",
                "company": "Jacquard Looms",
                "roles": [{"title": "Apprentice", "start": "2012", "end": "2014"}],
            }
        )
        _role(data)["highlights"].append({"text": "Shipped the loom controller to 3 mills."})
        _items(data).append({"name": "Go", "level": "working", "years": 1, "used_at": ["engine"]})
        _items(data)[1]["level"] = "proficient"
        data["notes"] = []

    said = (
        "Yes, 12 is right. I shipped a loom controller in Go to 3 mills; I'm proficient in K8s. "
        "Before that I was an Apprentice at Jacquard Looms from 2012 to 2014."
    )
    assert check_update(profile(), profile(answered), said) == ()


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda d: _items(d).append({"name": "Kafka"}), "recorded 'Kafka' as a technology"),
        (
            lambda d: _items(d)[0].update(level="expert"),
            "raised Python from proficient to expert; no answer says so",
        ),
        (
            lambda d: _role(d)["highlights"].append({"text": "Saved $2M a year."}),
            "introduced the figure '$2M'",
        ),
        (lambda d: d["experience"].pop(), "dropped the employer 'Babbage Mill'"),
        (lambda d: _items(d).pop(0), "dropped the technology 'Python'"),
        (lambda d: d["contact"].update(phone="(555) 999-0000"), "changed contact.phone"),
        (
            lambda d: d["contact"]["links"].append({"label": "X", "url": "https://x.com/ada"}),
            "added the link 'https://x.com/ada'",
        ),
        (lambda d: d["contact"].update(links=[]), "dropped the link"),
        (
            lambda d: d.update(awards=[{"name": "Turing Award"}]),
            "added 'Turing Award', which none of the answers mentions",
        ),
        (lambda d: d.update(certifications=[]), "dropped 'Fellow of the Analytical Society'"),
        (
            lambda d: d["experience"].append(
                {
                    "id": "x",
                    "company": "Hooli",
                    "roles": [{"title": "CEO", "start": "2020", "end": "2021"}],
                }
            ),
            "added the employer 'Hooli'",
        ),
        (
            lambda d: _role(d, 1).update(end="2019"),
            "recorded the role Analyst at Babbage Mill (2015 – 2019)",
        ),
        (
            lambda d: d["experience"][1]["roles"].insert(
                0, {"title": "Owner", "start": "2018", "end": "2019"}
            ),
            "recorded the role Owner at Babbage Mill",
        ),
    ],
)
def test_an_update_may_not_record_what_nobody_said(
    edit: Callable[[dict[str, Any]], None], expected: str
) -> None:
    problems = check_update(profile(), profile(edit), "The team was 12 engineers.")
    assert any(expected in problem for problem in problems), problems


def test_a_no_to_a_question_naming_a_technology_does_not_license_it() -> None:
    """The guard reads the answers alone: the question's own words are not evidence."""
    problems = check_update(
        profile(), profile(lambda d: _items(d).append({"name": "Kafka"})), "No."
    )
    assert problems


def test_an_update_may_correct_a_role_the_answer_names() -> None:
    def corrected(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"][0].update(title="Senior Analyst", end="2017")

    said = "My title at Babbage Mill was Senior Analyst, and I left in 2017."
    assert check_update(profile(), profile(corrected), said) == ()


def test_an_update_may_mark_a_role_current_when_the_answer_says_so() -> None:
    def current(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"][0]["end"] = "present"

    assert check_update(profile(), profile(current), "I still work at the mill, currently.") == ()
    assert check_update(profile(), profile(current), "I left the mill.")


def test_an_update_may_remove_what_the_answer_rules_out() -> None:
    def removed(data: dict[str, Any]) -> None:
        data["experience"].pop()
        _items(data).pop(1)

    said = "Drop Babbage Mill, it was a summer job. And I never really used Kubernetes."
    assert check_update(profile(), profile(removed), said) == ()


def test_a_phone_number_is_matched_digit_for_digit() -> None:
    changed = profile(lambda d: d["contact"].update(phone="555-222-3333"))
    assert check_update(profile(), changed, "My number is (555) 222 3333.") == ()
    assert check_update(profile(), changed, "My number changed.")


def test_a_new_email_or_link_must_be_written_out_in_the_answer() -> None:
    changed = profile(lambda d: d["contact"].update(email="ada@babbage.example"))
    assert check_update(profile(), changed, "Use ada@babbage.example now.") == ()
    linked = profile(
        lambda d: d["contact"]["links"].append({"label": "Site", "url": "https://ada.example/"})
    )
    assert check_update(profile(), linked, "My site is ada.example") == ()


# --- what changed, for the person -----------------------------------------------------------------
def test_the_summary_of_changes_counts_what_moved() -> None:
    def refine(data: dict[str, Any]) -> None:
        _items(data).pop()
        _items(data)[1]["level"] = "exposure"
        _items(data).append({"name": "Go"})
        _role(data)["highlights"].pop()
        data["summary"] = "Engineer."
        data["contact"]["headline"] = "Engine programmer"
        data["notes"] = []
        data["experience"][1]["roles"][0]["title"] = "Clerk"
        data["education"] = [{"credential": "Self-taught", "institution": "Home"}]

    lines = describe_changes(profile(), profile(refine))

    assert "+ role: Clerk at Babbage Mill (2015 – 2018)" in lines
    assert "- role: Analyst at Babbage Mill (2015 – 2018)" in lines
    assert "+ Self-taught (Home)" in lines
    assert "- Private tuition (De Morgan)" in lines
    assert "technologies: 3 → 3" in lines
    assert "  removed: Scheduler rewrite" in lines
    assert "  added: Go" in lines
    assert "  Kubernetes: working → exposure" in lines
    assert "highlights: 2 → 1" in lines
    assert "summary: rewritten" in lines
    assert "headline: Engine programmer" in lines
    assert "notes: 1 → 0" in lines


def test_a_long_list_of_removals_is_cut_short() -> None:
    def many(data: dict[str, Any]) -> None:
        _items(data).extend({"name": f"Tool {index}"} for index in range(12))

    lines = describe_changes(profile(many), profile())
    assert any(line.endswith("and 4 more") for line in lines)


def test_nothing_changed_says_nothing() -> None:
    assert describe_changes(profile(), profile()) == ()


def test_marking_a_technology_thin_narrows_what_can_be_printed_so_it_is_no_raise() -> None:
    """Writers list an unrated technology a role shows in use, never an exposure-level one."""

    def thin(data: dict[str, Any]) -> None:
        _items(data)[2]["level"] = "exposure"
        _items(data)[1]["level"] = "exposure"

    assert check_refinement(profile(), profile(thin)) == ()
    assert check_update(profile(), profile(thin), "") == ()


def test_clearing_a_thin_level_is_a_raise() -> None:
    def cleared(data: dict[str, Any]) -> None:
        del _items(data)[1]["level"]

    assert check_refinement(profile(), profile(cleared)) == (
        "raised Kubernetes from working to no level; refining never raises it",
    )
