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
            lambda d: d.update(projects=[{"name": "Loom", "description": "A loom controller."}]),
            "added 'Loom', which the draft does not have",
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
        (
            lambda d: d["experience"][0]["roles"].pop(1),
            "dropped the role Engineer at Analytical Engine Programme, Inc. (June 2018 – January",
        ),
        (
            lambda d: d["certifications"][0].update(year="2012"),
            "changed the date of 'Fellow of the Analytical Society' from 2019 to 2012",
        ),
        (
            lambda d: d["education"][0].update(completed="2010"),
            "gave 'Private tuition (De Morgan)' the date 2010, which the draft does not record",
        ),
        (
            lambda d: d["certifications"][0].update(year=""),
            "dropped the date 2019 from 'Fellow of the Analytical Society'",
        ),
        (
            lambda d: d["contact"].update(location="London (open to relocation)"),
            "changed contact.location from '' to 'London (open to relocation)'; refining never",
        ),
        (
            lambda d: d["contact"].update(work_authorization="Holds active security clearance"),
            "changed contact.work_authorization from ''",
        ),
        (
            lambda d: d["contact"].update(headline="Distinguished Engineer"),
            "changed contact.headline to 'Distinguished Engineer', which the draft's titles",
        ),
        (
            lambda d: _role(d).update(stack=["Python", "Rust"]),
            (
                "added 'Rust' to the stack of Principal Engineer at Analytical Engine Programme, "
                "Inc. (January 2021 – Present), which the draft does not record anywhere"
            ),
        ),
        (
            lambda d: d.update(projects=[{"name": "Loom", "description": "x", "stack": ["Rust"]}]),
            "added 'Rust' to the stack of Loom",
        ),
        (
            lambda d: _role(d)["highlights"].append(
                {"label": "Fraud", "text": "Designed the fraud-detection platform."}
            ),
            "added the highlight Fraud, which nothing the draft records at that employer supports",
        ),
        (
            lambda d: d.update(summary="Engineer whose programs serve millions of users."),
            "claimed 'millions', a size larger than any figure the draft states",
        ),
        (
            lambda d: _role(d)["highlights"][1].update(text="Led a team of fifteen from 2021."),
            "introduced the figure 'fifteen', which the draft does not state",
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


@pytest.mark.parametrize(
    "duplicate",
    [
        {"title": "Software Engineer", "start": "2018", "end": "2021"},
        {"title": "Developer", "start": "2019-03", "end": "2020-11"},
        {"title": "Engineer II", "start": "2018-06", "end": "2021-01"},
    ],
)
def test_a_duplicate_under_another_title_may_be_merged_into_the_role_that_covers_it(
    duplicate: dict[str, str],
) -> None:
    """An old resume's "Software Engineer, 2018 to 2021" is the same job as "Engineer" then."""

    def recorded_twice(data: dict[str, Any]) -> None:
        data["experience"][0]["roles"].append(duplicate)

    assert check_refinement(profile(recorded_twice), profile()) == ()


def test_a_duplicate_known_only_by_its_year_may_merge_into_the_months_inside_it() -> None:
    """A clerk's 2014 covers March to November 2014, though no month of it is sure to overlap."""

    def recorded_twice(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] += [
            {"title": "Junior Clerk", "start": "2014-03", "end": "2014-11"},
            {"title": "Clerk", "start": "2014", "end": "2014"},
        ]

    def merged(data: dict[str, Any]) -> None:
        recorded_twice(data)
        data["experience"][1]["roles"].pop()

    assert check_refinement(profile(recorded_twice), profile(merged)) == ()


def test_a_role_that_ends_the_year_the_next_starts_is_not_a_duplicate_of_it() -> None:
    """A promotion recorded to the year touches the next role without sharing any time with it."""

    def promoted(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"].insert(
            0, {"title": "Senior Analyst", "start": "2018", "end": "2020"}
        )

    def merged(data: dict[str, Any]) -> None:
        promoted(data)
        data["experience"][1]["roles"].pop(1)

    assert check_refinement(profile(promoted), profile(merged)) == (
        (
            "dropped the role Analyst at Babbage Mill (2015 – 2018); keep every role, unless "
            "another role at the same employer records the same job"
        ),
    )


@pytest.mark.parametrize(("end", "month"), [("2021-02", "February"), ("2021-03", "March")])
def test_a_role_that_overlaps_the_next_by_a_month_is_not_a_duplicate_of_it(
    end: str, month: str
) -> None:
    """LinkedIn often ends the old title a month after the new one starts."""

    def overlapping(data: dict[str, Any]) -> None:
        _role(data, 0, 1)["end"] = end

    def dropped(data: dict[str, Any]) -> None:
        overlapping(data)
        data["experience"][0]["roles"].pop(1)

    assert check_refinement(profile(overlapping), profile(dropped)) == (
        (
            f"dropped the role Engineer at Analytical Engine Programme, Inc. (June 2018 – {month} "
            f"2021); keep every role, unless another role at the same employer records the same job"
        ),
    )


@pytest.mark.parametrize(
    ("kept", "gone", "label"),
    [
        (
            {"title": "Engineer", "start": "2017-09", "end": "2019"},
            {"title": "Engineering Intern", "start": "2017", "end": "2017"},
            "Engineering Intern at Babbage Mill (2017 – 2017)",
        ),
        (
            {"title": "Engineer", "start": "2017", "end": "2019"},
            {"title": "Engineering Intern", "start": "2017-05", "end": "2017-08"},
            "Engineering Intern at Babbage Mill (May 2017 – August 2017)",
        ),
        (
            {"title": "Software Engineer", "start": "2018", "end": "2021"},
            {"title": "Engineer", "start": "2018-06", "end": "2021-01"},
            "Engineer at Babbage Mill (June 2018 – January 2021)",
        ),
    ],
    ids=["intern-year-before-a-september-start", "intern-months-in-a-bare-year", "months-lost"],
)
def test_a_year_given_alone_is_not_taken_to_cover_the_months_around_it(
    kept: dict[str, str], gone: dict[str, str], label: str
) -> None:
    """A 2017 internship can be the months before a job that starts in September 2017."""

    def recorded(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [kept, gone]

    def dropped(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [kept]

    assert check_refinement(profile(recorded), profile(dropped)) == (
        (
            f"dropped the role {label}; keep every role, unless another role at the same "
            f"employer records the same job"
        ),
    )


@pytest.mark.parametrize(
    ("kept", "gone"),
    [
        (
            {"title": "Analyst", "start": "2015", "end": "2018"},
            {"title": "Data Analyst", "start": "2015", "end": "2018"},
        ),
        (
            {"title": "Principal Engineer", "start": "2021-01", "end": "present"},
            {"title": "Staff Engineer", "start": "2022", "end": "present"},
        ),
    ],
    ids=["same-years", "inside-the-current-role"],
)
def test_a_duplicate_under_another_title_may_merge_when_its_years_are_covered(
    kept: dict[str, str], gone: dict[str, str]
) -> None:
    def recorded(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [kept, gone]

    def merged(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [kept]

    assert check_refinement(profile(recorded), profile(merged)) == ()


def test_a_credential_recorded_twice_may_keep_the_entry_with_the_date() -> None:
    def twice(data: dict[str, Any]) -> None:
        data["certifications"].append({"name": "Fellow of the Analytical Society"})

    assert check_refinement(profile(twice), profile()) == ()
    undated = profile(lambda d: d["certifications"][0].update(year=""))
    assert check_refinement(profile(twice), undated) == (
        (
            "dropped the date 2019 from 'Fellow of the Analytical Society'; keep every date the "
            "draft records"
        ),
    )


def _won_twice(data: dict[str, Any]) -> None:
    data["awards"] = [
        {"name": "Employee of the Year", "year": "2019"},
        {"name": "Employee of the Year", "year": "2021"},
    ]


def _won_once(data: dict[str, Any]) -> None:
    _won_twice(data)
    data["awards"].pop()


def test_a_credential_held_twice_keeps_both_its_years() -> None:
    """An award won twice, or a certification renewed, loses a fact when one year goes."""
    assert check_refinement(profile(_won_twice), profile(_won_once)) == (
        "dropped the date 2021 from 'Employee of the Year'; keep every date the draft records",
    )


@pytest.mark.parametrize("kept", ["2010", "2010-06"])
def test_a_duplicate_credential_may_merge_into_its_twin_with_the_same_year(kept: str) -> None:
    def twice(data: dict[str, Any]) -> None:
        data["education"] = [
            {"credential": "Private tuition", "institution": "De Morgan", "completed": "2010-06"},
            {"credential": "Private tuition", "institution": "De Morgan", "completed": "2010"},
        ]

    merged = profile(lambda d: d["education"][0].update(completed=kept))
    assert check_refinement(profile(twice), merged) == ()


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


def test_refining_may_reword_merge_and_move_highlights() -> None:
    """Each keeps the draft's words for that employer, which is what a new highlight lacks."""

    def recorded_twice(data: dict[str, Any]) -> None:
        _role(data)["highlights"].append(
            {"text": "Rewrote the scheduler, cutting nightly batch runtime 38%."}
        )

    def refined(data: dict[str, Any]) -> None:
        highlights = _role(data)["highlights"]
        highlights[0]["text"] = (
            "Rewrote the scheduler on AWS EC2, cutting nightly batch runtime 38%."
        )
        highlights[1]["text"] = "Led a twelve-person team from 2021."
        _role(data, 0, 1)["highlights"] = [highlights.pop(1)]

    assert check_refinement(profile(recorded_twice), profile(refined)) == ()


def test_refining_may_turn_a_technology_that_was_an_accomplishment_into_a_highlight() -> None:
    def refined(data: dict[str, Any]) -> None:
        _items(data).pop()  # "Scheduler rewrite"
        _role(data)["highlights"].append(
            {"label": "Scheduler", "text": "Led the scheduler rewrite."}
        )

    assert check_refinement(profile(), profile(refined)) == ()


def test_refining_may_respell_contact_details_and_align_the_headline_and_stacks() -> None:
    """Punctuation is no change, and a title the draft holds is no promotion.

    A stack may name any technology the draft records: in its list, in another stack, or in its
    text.
    """

    def draft(data: dict[str, Any]) -> None:
        data["contact"].update(location="London UK - open to remote", headline="Engineer")
        _role(data, 0, 1)["stack"] = ["K8s"]
        data["summary"] = "Engineer who writes programs in Ada for the Difference Engine."
        notes = {
            "name": "Engine notes",
            "description": "Notes on the engine.",
            "stack": ["Fortran"],
        }
        data["projects"] = [notes]

    def refined(data: dict[str, Any]) -> None:
        draft(data)
        data["contact"].update(location="London, UK — open to remote")
        data["contact"].update(headline="Principal Engineer")
        _role(data)["stack"] = ["Python", "Kubernetes", "Ada", "Fortran"]

    assert check_refinement(profile(draft), profile(refined)) == ()


def test_a_size_the_draft_states_may_be_restated_in_words() -> None:
    def large(data: dict[str, Any]) -> None:
        _role(data)["highlights"][0]["text"] = "Cut batch runtime 38% for 4M jobs on AWS EC2."

    def restated(data: dict[str, Any]) -> None:
        large(data)
        data["summary"] = "Engineer whose programs run millions of jobs."

    assert check_refinement(profile(large), profile(restated)) == ()


@pytest.mark.parametrize(
    ("name", "alias"), [("PostgreSQL", "Postgres"), ("Postgres", "PostgreSQL")]
)
def test_merging_two_spellings_of_one_technology_keeps_the_depth_either_recorded(
    name: str, alias: str
) -> None:
    """The draft's "PostgreSQL" (no level) and "Postgres" (expert) are one database."""

    def recorded_twice(data: dict[str, Any]) -> None:
        _items(data).extend(
            [{"name": "PostgreSQL"}, {"name": "Postgres", "level": "expert", "years": 8}]
        )

    def merged(years: float) -> Callable[[dict[str, Any]], None]:
        def merge(data: dict[str, Any]) -> None:
            entry = {"name": name, "aliases": [alias], "level": "expert", "years": years}
            _items(data).append(entry)

        return merge

    assert check_refinement(profile(recorded_twice), profile(merged(8))) == ()
    assert check_refinement(profile(recorded_twice), profile(merged(9))) == (
        f"raised {name} from 8 to 9 years; refining never raises it",
    )


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
        (
            lambda d: d["experience"][0]["roles"].pop(1),
            "dropped the role Engineer at Analytical Engine Programme, Inc.",
        ),
        (
            lambda d: _role(d).update(start="2018-06"),
            "recorded the role Principal Engineer at Analytical Engine Programme, Inc. (June 2018",
        ),
        (
            lambda d: d["certifications"][0].update(year="2012"),
            "recorded 2012 as the date of 'Fellow of the Analytical Society', which none of",
        ),
        (
            lambda d: d["education"][0].update(completed="2010-06"),
            "recorded 2010-06 as the date of 'Private tuition (De Morgan)'",
        ),
        (
            lambda d: d["certifications"][0].update(year=""),
            "dropped the date 2019 from 'Fellow of the Analytical Society', which none of",
        ),
    ],
)
def test_an_update_may_not_record_what_nobody_said(
    edit: Callable[[dict[str, Any]], None], expected: str
) -> None:
    problems = check_update(profile(), profile(edit), "The team was 12 engineers.")
    assert any(expected in problem for problem in problems), problems


def test_an_update_may_correct_a_role_the_answer_names() -> None:
    def corrected(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"][0].update(title="Senior Analyst", end="2017")

    said = "My title at Babbage Mill was Senior Analyst, and I left in 2017."
    assert check_update(profile(), profile(corrected), said) == ()


def test_an_update_may_split_a_role_at_the_promotion_the_answer_gives() -> None:
    def split(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [
            {"title": "Senior Analyst", "start": "2017", "end": "2018"},
            {"title": "Analyst", "start": "2015", "end": "2017"},
        ]

    said = "I was promoted to Senior Analyst in 2017."
    assert check_update(profile(), profile(split), said) == ()


def test_a_role_moves_to_another_role_s_date_only_when_the_answer_gives_it() -> None:
    """The date "Engineer" started is not a date "Principal Engineer" may take on its own."""
    backdated = profile(lambda d: _role(d).update(start="2018-06"))

    assert check_update(profile(), backdated, "I've been Principal Engineer since June 2018.") == ()
    assert check_update(profile(), backdated, "I led the team as Principal Engineer.")


def test_merging_into_a_current_role_needs_the_date_even_when_the_answer_says_now() -> None:
    """A "now" gives Principal Engineer its end, never the start it would take from Engineer."""

    def merged(data: dict[str, Any]) -> None:
        data["experience"][0]["roles"].pop(1)
        _role(data)["start"] = "2018-06"

    assert check_update(profile(), profile(merged), "I now mentor every new engineer.") == (
        (
            "recorded the role Principal Engineer at Analytical Engine Programme, Inc. (June 2018 "
            "– Present), which none of the answers mentions"
        ),
    )


def _unsaid(what: str) -> str:
    return f"{what}, which none of the answers mentions"


def _boomerang(data: dict[str, Any]) -> None:
    data["experience"][1]["roles"] = [
        {"title": "Analyst", "start": "2019", "end": "2021"},
        {"title": "Analyst", "start": "2012", "end": "2014"},
    ]


def test_two_stints_with_one_title_join_only_when_the_answer_gives_the_dates() -> None:
    """Pooling both stints' dates would invent the five years between them."""

    def joined(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [{"title": "Analyst", "start": "2012", "end": "2021"}]

    assert check_update(profile(_boomerang), profile(joined), "The team was 12 engineers.") == (
        _unsaid("recorded the role Analyst at Babbage Mill (2012 – 2021)"),
        _unsaid("dropped the role Analyst at Babbage Mill (2012 – 2014)"),
    )
    said = "I was an Analyst at Babbage Mill from 2012 to 2021 without a break."
    assert check_update(profile(_boomerang), profile(joined), said) == ()


def test_a_stint_that_goes_beside_another_with_its_title_is_still_a_removal() -> None:
    def one_stint(data: dict[str, Any]) -> None:
        _boomerang(data)
        data["experience"][1]["roles"].pop()

    assert check_update(profile(_boomerang), profile(one_stint), "The team was 12 engineers.") == (
        _unsaid("dropped the role Analyst at Babbage Mill (2012 – 2014)"),
    )
    said = "Drop the first Analyst stint, that was a contract through an agency."
    assert check_update(profile(_boomerang), profile(one_stint), said) == ()


def test_a_title_corrected_to_one_held_elsewhere_there_keeps_its_own_dates() -> None:
    """Correcting the title alone keeps the role's dates, even when the title is already there."""

    def boomerang(data: dict[str, Any]) -> None:
        data["experience"][1]["roles"] = [
            {"title": "Analyst", "start": "2019", "end": "2021"},
            {"title": "Senior Analyst", "start": "2013", "end": "2015"},
            {"title": "Analyst", "start": "2011", "end": "2013"},
        ]

    def retitled(data: dict[str, Any]) -> None:
        boomerang(data)
        data["experience"][1]["roles"][0]["title"] = "Senior Analyst"

    said = "When I came back to Babbage Mill I was Senior Analyst again, not Analyst."
    assert check_update(profile(boomerang), profile(retitled), said) == ()
    assert check_update(profile(boomerang), profile(retitled), "The team was 12 engineers.") == (
        (
            "recorded the role Senior Analyst at Babbage Mill (2019 – 2021), which none of the "
            "answers mentions"
        ),
    )


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


def test_a_credential_date_must_be_given_in_the_answer() -> None:
    redated = profile(lambda d: d["certifications"][0].update(year="2012"))
    assert (
        check_update(profile(), redated, "The Analytical Society made me a fellow in 2012.") == ()
    )

    completed = profile(lambda d: d["education"][0].update(completed="2010-06"))
    assert check_update(profile(), completed, "I finished with De Morgan in June 2010.") == ()

    undated = profile(lambda d: d["certifications"][0].update(year=""))
    said = "I don't remember when I became a Fellow of the Analytical Society."
    assert check_update(profile(), undated, said) == ()


def test_a_new_credential_keeps_only_the_date_the_answer_gives() -> None:
    def added(data: dict[str, Any]) -> None:
        data["certifications"].append({"name": "Certified Loom Operator", "year": "2016"})

    assert check_update(profile(), profile(added), "I'm a Certified Loom Operator.") == (
        (
            "recorded 2016 as the date of 'Certified Loom Operator', which none of the answers "
            "mentions"
        ),
    )
    said = "I became a Certified Loom Operator in 2016."
    assert check_update(profile(), profile(added), said) == ()


def test_a_renamed_credential_keeps_the_date_it_had() -> None:
    def renamed(year: str) -> Profile:
        name = "Fellow of the Royal Analytical Society"
        return profile(lambda d: d.update(certifications=[{"name": name, "year": year}]))

    said = "It's Fellow of the Royal Analytical Society, not Fellow of the Analytical Society."
    assert check_update(profile(), renamed("2019"), said) == ()
    assert check_update(profile(), renamed("2012"), said) == (
        (
            "recorded 2012 as the date of 'Fellow of the Royal Analytical Society', which none of "
            "the answers mentions"
        ),
    )


def test_a_new_credential_does_not_take_the_date_of_an_unrelated_one_dropped() -> None:
    swapped = profile(
        lambda d: d.update(certifications=[{"name": "Certified Loom Operator", "year": "2019"}])
    )
    said = (
        "My Fellow of the Analytical Society membership lapsed, please remove it. I am also a "
        "Certified Loom Operator."
    )
    assert check_update(profile(), swapped, said) == (
        (
            "recorded 2019 as the date of 'Certified Loom Operator', which none of the answers "
            "mentions"
        ),
    )


def test_a_rename_is_one_for_one() -> None:
    """Two new names that each keep the old one's words cannot both inherit its year."""

    def split(data: dict[str, Any]) -> None:
        data["certifications"] = [
            {"name": "Fellow of the Royal Analytical Society", "year": "2019"},
            {"name": "Honorary Fellow of the Analytical Society", "year": "2019"},
        ]

    said = (
        "I'm a Fellow of the Royal Analytical Society and an Honorary Fellow of the Analytical "
        "Society, not a Fellow of the Analytical Society."
    )
    problems = check_update(profile(), profile(split), said)
    assert len(problems) == 2
    assert all(problem.startswith("recorded 2019 as the date of") for problem in problems)


def test_an_update_may_drop_one_year_of_a_credential_held_twice_only_when_it_names_it() -> None:
    assert check_update(profile(_won_twice), profile(_won_once), "The team was 12 engineers.") == (
        "dropped the date 2021 from 'Employee of the Year', which none of the answers mentions",
    )
    said = "I was Employee of the Year once, in 2019."
    assert check_update(profile(_won_twice), profile(_won_once), said) == ()


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


# --- an update: every figure from the answers, or from the field it was already in ----------------
_DOWNTIME = "How much did the loom work cut downtime?\nIt cut loom downtime 45% in 2022."


def _highlight(text: str, label: str = "") -> Callable[[dict[str, Any]], None]:
    def add(data: dict[str, Any]) -> None:
        _role(data)["highlights"].append({"label": label, "text": text})

    return add


@pytest.mark.parametrize(
    ("text", "borrowed"),
    [
        ("Cut loom downtime 38% in 2022.", "38%"),
        ("Cut loom downtime 45% in 2021.", "2021"),
        ("Cut loom downtime 45% in 2019.", "2019"),
        ("Cut loom downtime 45% in 2022 for twelve looms.", "twelve"),
    ],
    ids=["another-highlight-s-figure", "a-role-s-start-year", "a-certification-year", "in-words"],
)
def test_a_new_highlight_may_not_borrow_a_figure_or_a_year_the_answer_did_not_give(
    text: str, borrowed: str
) -> None:
    """38% and 12 are the profile's, for other accomplishments; the answer said 45% and 2022."""
    problems = check_update(profile(), profile(_highlight(text, "Downtime")), _DOWNTIME)
    assert problems == (_unsaid(f"introduced the figure {borrowed!r} in the highlight Downtime"),)


def test_a_new_highlight_carrying_the_answer_s_own_figures_passes() -> None:
    updated = profile(_highlight("Cut loom downtime 45% in 2022.", "Downtime"))
    assert check_update(profile(), updated, _DOWNTIME) == ()


def test_a_rewritten_highlight_keeps_its_own_figures_and_takes_only_the_answer_s() -> None:
    def figured(text: str) -> Profile:
        return profile(lambda d: _role(d)["highlights"][0].update(text=text))

    said = "How long did the batch take after the rewrite?\nIt saved 4 hours a night."
    assert (
        check_update(
            profile(), figured("Cut batch runtime 38% (4 hours a night) on AWS EC2."), said
        )
        == ()
    )
    assert check_update(
        profile(), figured("Cut batch runtime 38% for 12 teams on AWS EC2."), said
    ) == (_unsaid("introduced the figure '12' in the highlight Scheduler"),)


def test_a_scope_takes_a_figure_only_from_the_answers_or_its_own_text() -> None:
    def scoped(scope: str) -> Profile:
        return profile(lambda d: _role(d).update(scope=scope))

    said = "How big is the team you lead?\nNine engineers."
    assert check_update(profile(), scoped("Leads a team of nine."), said) == ()
    assert check_update(profile(), scoped("Leads a team of 9."), said) == ()
    assert check_update(profile(), scoped("Leads a team of 12."), said) == (
        _unsaid(
            "introduced the figure '12' in the scope of Principal Engineer at Analytical Engine "
            "Programme, Inc."
        ),
    )


def test_a_corrected_role_keeps_its_scope_s_figures() -> None:
    def scoped(data: dict[str, Any]) -> None:
        _role(data).update(scope="Leads a team of 12.")

    def retitled(data: dict[str, Any]) -> None:
        scoped(data)
        _role(data).update(title="Chief Engineer")

    said = "My title is Chief Engineer, not Principal Engineer."
    assert check_update(profile(scoped), profile(retitled), said) == ()


def test_a_role_corrected_in_title_and_dates_keeps_its_scope_but_another_may_not_copy_it() -> None:
    def scoped(data: dict[str, Any]) -> None:
        _role(data).update(scope="Leads a team of 12.")

    def corrected(data: dict[str, Any]) -> None:
        scoped(data)
        _role(data).update(title="Chief Engineer", start="2020-06")

    said = "I was Chief Engineer from June 2020, not Principal Engineer."
    assert check_update(profile(scoped), profile(corrected), said) == ()

    def copied(data: dict[str, Any]) -> None:
        scoped(data)
        _role(data, 0, 1).update(scope="Leads a team of 12.")

    assert check_update(profile(scoped), profile(copied), "I was an Engineer before that.") == (
        _unsaid(
            "introduced the figure '12' in the scope of Engineer at Analytical Engine "
            "Programme, Inc."
        ),
    )


def test_a_renamed_credential_keeps_the_figures_in_its_notes() -> None:
    def fellow(name: str) -> Profile:
        entry = {"name": name, "year": "2019", "notes": "Member 4471."}
        return profile(lambda d: d.update(certifications=[entry]))

    said = "It's Fellow of the Royal Analytical Society, not Fellow of the Analytical Society."
    renamed = fellow("Fellow of the Royal Analytical Society")
    assert check_update(fellow("Fellow of the Analytical Society"), renamed, said) == ()


def test_the_summary_and_a_project_take_figures_only_from_the_answers_or_themselves() -> None:
    def project(outcome: str) -> Callable[[dict[str, Any]], None]:
        def add(data: dict[str, Any]) -> None:
            data["projects"] = [
                {"name": "Loom", "description": "A loom controller.", "outcome": outcome}
            ]

        return add

    said = "How many mills use the loom controller?\nThree mills run it."
    assert check_update(profile(project("")), profile(project("Runs in 3 mills.")), said) == ()
    assert check_update(profile(project("")), profile(project("Runs in 12 mills.")), said) == (
        _unsaid("introduced the figure '12' in the project 'Loom'"),
    )
    summarised = profile(lambda d: d.update(summary="Engineer who led 12 engineers."))
    assert check_update(profile(), summarised, said) == (
        _unsaid("introduced the figure '12' in the summary"),
    )


def test_a_figure_from_a_note_needs_the_note_s_question_to_be_answered() -> None:
    """Notes are unconfirmed; their figure counts once the answer accepts the question."""

    def peak(data: dict[str, Any]) -> None:
        _role(data)["highlights"][1]["text"] = "Led a team of 14 engineers from 2021."

    assert check_update(profile(), profile(peak), "I led the team from 2021.") == (
        _unsaid("introduced the figure '14' in the highlight \"Led a team of 14 engineers…\""),
    )
    accepted = "Was the team 12 or 14 engineers?\nIt was 14 at its peak."
    assert check_update(profile(), profile(peak), accepted) == ()


def test_a_size_in_words_needs_an_answer_that_large() -> None:
    updated = profile(_highlight("Ran the loom controller for millions of users.", "Scale"))
    small = "How many people used the loom controller?\nAbout 3,000 users."
    assert check_update(profile(), updated, small) == (
        "claimed 'millions' in the highlight Scale, a size larger than anything the answers state",
    )
    large = "How many people used the loom controller?\nAbout 3 million users."
    assert check_update(profile(), updated, large) == ()


# --- an update: contact details, stacks and new highlights in the answers' words -----------------
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("location", "London (open to relocation)"),
        ("work_authorization", "Holds active security clearance"),
        ("headline", "Distinguished Engineer"),
    ],
)
def test_an_update_may_not_write_a_contact_detail_nobody_gave(field: str, value: str) -> None:
    changed = profile(lambda d: d["contact"].update({field: value}))
    assert check_update(profile(), changed, "About $9k a month.") == (
        _unsaid(f"changed contact.{field} to {value!r}"),
    )


@pytest.mark.parametrize(
    ("field", "value", "said"),
    [
        (
            "location",
            "London, UK (open to remote)",
            "I moved to London and I'm open to remote work.",
        ),
        ("location", "Denver, CO", "I live in Denver now."),
        ("work_authorization", "Green card holder", "I have a green card."),
        ("headline", "Principal Engineer, Scheduling", "Yes, scheduling is my focus."),
    ],
)
def test_an_update_may_word_a_contact_detail_the_answer_gives(
    field: str, value: str, said: str
) -> None:
    """The answer's words, put the way a profile writes them: "Denver" may gain its state."""
    changed = profile(lambda d: d["contact"].update({field: value}))
    assert check_update(profile(), changed, said) == ()


def test_an_update_may_add_to_a_stack_only_what_the_answers_name() -> None:
    """A stack says the technology was used in that role, which a resume then prints there."""
    stacked = profile(lambda d: _role(d).update(stack=["Python", "Kubernetes"]))
    role = "Principal Engineer at Analytical Engine Programme, Inc."
    assert check_update(profile(), stacked, "About $9k a month.") == (
        _unsaid(f"added 'Python' to the stack of {role}"),
        _unsaid(f"added 'Kubernetes' to the stack of {role}"),
    )
    assert check_update(profile(), stacked, "I used Python and K8s on the scheduler.") == ()
    accepted = "Did you use Python and Kubernetes on the scheduler?\nYes, both of them."
    assert check_update(profile(), stacked, accepted) == ()


def test_respelling_a_stack_item_adds_nothing() -> None:
    before = profile(lambda d: _role(d).update(stack=["Kubernetes"]))
    after = profile(lambda d: _role(d).update(stack=["K8s"]))
    assert check_update(before, after, "The team was 12 engineers.") == ()


def test_an_update_may_add_to_a_project_s_stack_only_what_the_answers_name() -> None:
    def project(*stack: str) -> Profile:
        loom = {"name": "Loom", "description": "A loom controller.", "stack": list(stack)}
        return profile(lambda d: d.update(projects=[loom]))

    assert check_update(project("Python"), project("Python", "Go"), "It ran on looms.") == (
        _unsaid("added 'Go' to the stack of Loom"),
    )
    assert check_update(project("Python"), project("Python", "Go"), "I rewrote it in Go.") == ()


def test_a_new_highlight_must_be_told_in_the_answers_words() -> None:
    """An answer about a salary cannot become an accomplishment about incident command."""
    invented = profile(_highlight("Served as incident commander for every outage.", "Incident"))
    assert check_update(profile(), invented, "About $9k a month.") == (
        _unsaid("added the highlight Incident"),
    )
    paraphrased = profile(
        _highlight("Established the team's on-call rotation and authored its runbooks.", "On-call")
    )
    said = "Did you run on-call?\nYes, I set up the team's on-call rotation and wrote the runbooks."
    assert check_update(profile(), paraphrased, said) == ()


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


def test_an_answer_that_changes_a_highlight_says_which_one() -> None:
    """The commonest answer puts a figure into a highlight the profile already has."""

    def figured(data: dict[str, Any]) -> None:
        _role(data)["highlights"][0]["text"] = "Cut batch runtime 38% (4 hours a night) on AWS EC2."
        _role(data)["highlights"][1]["text"] = "Led a team of 12 engineers from 2021; 3 promoted."

    assert describe_changes(profile(), profile(figured)) == (
        'highlights edited: Scheduler, "Led a team of 12 engineers…"',
    )


def test_a_highlight_added_moved_or_respelled_is_not_an_edit() -> None:
    def rearranged(data: dict[str, Any]) -> None:
        highlights = _role(data)["highlights"]
        _role(data, 0, 1)["highlights"] = [highlights.pop(1)]
        highlights[0]["text"] = "Cut batch runtime 38%, on AWS EC2!"
        highlights.append({"text": "Shipped the loom controller."})

    assert describe_changes(profile(), profile(rearranged)) == (
        "highlights: 2 → 3",
        'highlights added: "Shipped the loom controller."',
    )


def test_an_edited_highlight_is_paired_by_its_label_before_its_place() -> None:
    def edited(data: dict[str, Any]) -> None:
        highlights = _role(data)["highlights"]
        highlights[0]["text"] = "Cut batch runtime 38% on AWS EC2 and Batch."
        highlights.insert(0, {"text": "Shipped the loom controller."})

    lines = describe_changes(profile(), profile(edited))
    assert lines == (
        "highlights: 2 → 3",
        'highlights added: "Shipped the loom controller."',
        "highlights edited: Scheduler",
    )


def test_an_unlabelled_highlight_is_paired_only_with_one_that_shares_its_words() -> None:
    """A highlight added ahead of the one edited is not the edit, whatever its place."""

    def edited(data: dict[str, Any]) -> None:
        highlights = _role(data)["highlights"]
        highlights[1]["text"] = "Led a team of 12 engineers from 2021; 3 promoted."
        highlights.insert(0, {"text": "Shipped the loom controller."})

    assert describe_changes(profile(), profile(edited)) == (
        "highlights: 2 → 3",
        'highlights added: "Shipped the loom controller."',
        'highlights edited: "Led a team of 12 engineers…"',
    )


def test_a_highlight_deleted_beside_one_added_is_not_an_edit() -> None:
    """The summary is what tells the candidate a highlight, and its 38%, went."""

    def replaced(data: dict[str, Any]) -> None:
        _role(data)["highlights"].pop(0)
        _role(data, 0, 1)["highlights"] = [
            {"label": "Mentoring", "text": "Mentored 3 engineers to promotion."}
        ]

    assert describe_changes(profile(), profile(replaced)) == (
        "highlights removed: Scheduler",
        "highlights added: Mentoring",
    )


def test_a_changed_credential_date_is_named() -> None:
    def redated(data: dict[str, Any]) -> None:
        data["certifications"][0]["year"] = "2012"
        data["education"][0]["completed"] = "2010"

    assert describe_changes(profile(), profile(redated)) == (
        "Private tuition (De Morgan): no date → 2010",
        "Fellow of the Analytical Society: 2019 → 2012",
    )


def test_nothing_changed_says_nothing() -> None:
    assert describe_changes(profile(), profile()) == ()


_PRINCIPAL = "Principal Engineer at Analytical Engine Programme, Inc."


def test_the_summary_of_changes_names_stacks_scopes_and_contact_details() -> None:
    """What an answer adds outside the highlights is still something the candidate should see."""

    def before(data: dict[str, Any]) -> None:
        _role(data).update(stack=["Python", "Terraform"])
        data["projects"] = [{"name": "Loom", "description": "A loom.", "stack": ["Python"]}]

    def after(data: dict[str, Any]) -> None:
        _role(data).update(stack=["Python", "K8s"], scope="Leads a team of nine.")
        shuttle = {"name": "Shuttle", "description": "A shuttle.", "stack": ["Go"]}
        data["projects"] = [{"name": "Loom", "description": "A loom.", "stack": ["Go"]}, shuttle]
        data["contact"].update(location="Denver, CO", phone="(555) 010-0199")
        data["contact"]["links"].append({"label": "Site", "url": "https://ada.example"})
        data["target_roles"] = ["Staff Engineer"]
        _items(data)[0].update(years=6, used_at=["engine", "mill"])

    lines = describe_changes(profile(before), profile(after))

    assert f"{_PRINCIPAL}: stack + K8s" in lines
    assert f"{_PRINCIPAL}: stack - Terraform" in lines
    assert f"{_PRINCIPAL}: scope: Leads a team of nine." in lines
    assert "Loom: stack + Go" in lines
    assert "Loom: stack - Python" in lines
    assert "+ Shuttle" in lines
    assert not any(line.startswith("Shuttle:") for line in lines), "a new project is one line"
    assert "location: Denver, CO" in lines
    assert "phone: (555) 010-0199" in lines
    assert "+ link: https://ada.example" in lines
    assert "target roles: Staff Engineer" in lines
    assert "  Python: 5 → 6 years" in lines
    assert "  Python: used at + mill" in lines


def test_the_summary_of_changes_names_what_was_taken_away() -> None:
    def before(data: dict[str, Any]) -> None:
        _role(data).update(scope="Leads a team of 12.")
        data["contact"].update(work_authorization="US citizen")
        data["target_roles"] = ["Staff Engineer"]

    def after(data: dict[str, Any]) -> None:
        _role(data).update(title="Chief Engineer")
        data["contact"]["links"] = []
        _items(data)[0].update(used_at=[])

    lines = describe_changes(profile(before), profile(after))

    assert "Chief Engineer at Analytical Engine Programme, Inc.: scope: removed" in lines
    assert "work authorization: removed" in lines
    assert "- link: https://github.com/ada" in lines
    assert "target roles: none" in lines
    assert "  Python: used at - engine" in lines


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
