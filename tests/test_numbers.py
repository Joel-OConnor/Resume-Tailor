"""Reading numbers written in words: what counts as a claim, and what is a name or an idiom."""

from __future__ import annotations

from decimal import Decimal

import pytest

from resume_tailor.match.tokens import tokenise
from resume_tailor.verify.numbers import Shape, numbers_anywhere, read_numbers


def _claims(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Return the words read as a claim, with the figures each may be printed as."""
    return [(spelled.raw, spelled.values) for spelled in read_numbers(text) if not spelled.named]


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("Mentored twelve engineers.", [("twelve", ("12",))]),
        ("Twelve engineers joined.", [("Twelve", ("12",))]),
        ("Grew to twenty-five engineers.", [("twenty-five", ("25",))]),
        ("Grew to twenty five engineers.", [("twenty five", ("25",))]),
        ("Led a dozen services.", [("a dozen", ("12",))]),
        ("Led half a dozen services.", [("half a dozen", ("6",))]),
        ("Led two dozen services.", [("two dozen", ("24",))]),
        ("Over a decade of payments work.", [("a decade", ("10",))]),
        ("Two decades of payments work.", [("Two decades", ("20",))]),
        ("Served a million users.", [("a million", ("1000000",))]),
        ("Served one million users.", [("one million", ("1000000",))]),
        ("Served two hundred thousand users.", [("two hundred thousand", ("200000",))]),
        ("Kept five nines of availability.", [("five nines", ("99.999",))]),
        (
            "Ran a five-person team for twenty-plus weeks.",
            [("five-person", ("5",)), ("twenty-plus", ("20",))],
        ),
    ],
)
def test_a_number_in_words_is_read_as_the_figure_it_states(
    text: str, claims: list[tuple[str, tuple[str, ...]]]
) -> None:
    assert _claims(text) == claims


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("Doubled throughput.", [("Doubled", ("2", "100"))]),
        ("Tripling throughput.", [("Tripling", ("3", "200"))]),
        ("Quadrupled throughput.", [("Quadrupled", ("4", "300"))]),
        ("Halved monthly spend.", [("Halved", ("50",))]),
        ("Cut deploy time in half.", [("in half", ("50",))]),
        ("Cut spend by half.", [("by half", ("50",))]),
        ("Delivered in half the time.", [("in half", ("50",))]),
        ("Grew revenue tenfold.", [("tenfold", ("10",))]),
        ("Grew revenue ten-fold.", [("ten-fold", ("10",))]),
        ("Grew revenue a hundredfold.", [("hundredfold", ("100",))]),
    ],
)
def test_a_multiple_in_words_is_read_as_every_figure_it_can_be_printed_as(
    text: str, claims: list[tuple[str, tuple[str, ...]]]
) -> None:
    assert _claims(text) == claims
    assert {spelled.shape for spelled in read_numbers(text)} == {Shape.MULTIPLE}


@pytest.mark.parametrize(
    ("text", "raw", "least"),
    [
        ("Served thousands of users.", "thousands", 1_000),
        ("Thousands of users rely on it.", "Thousands", 1_000),
        ("Served millions of monthly users.", "millions", 1_000_000),
        ("Served tens of millions of users.", "tens of millions", 10_000_000),
        ("Handled hundreds of millions of requests.", "hundreds of millions", 100_000_000),
        ("Served hundreds of thousands of accounts.", "hundreds of thousands", 100_000),
        ("Saved dozens of hours.", "dozens", 24),
        ("Onboarded several hundred merchants.", "several hundred", 100),
        ("Onboarded a few thousand merchants.", "few thousand", 1_000),
        ("Closed a multi-million-dollar deal.", "multi-million-dollar", 1_000_000),
        ("Closed a multibillion deal.", "multibillion", 1_000_000_000),
        ("Drove seven-figure savings.", "seven-figure", 1_000_000),
    ],
)
def test_a_size_in_words_is_read_as_the_least_it_can_mean(text: str, raw: str, least: int) -> None:
    (spelled,) = read_numbers(text)
    assert (spelled.raw, spelled.shape, spelled.least, spelled.named) == (
        raw,
        Shape.MAGNITUDE,
        Decimal(least),
        False,
    )


def test_a_range_of_sizes_is_read_as_each_size() -> None:
    found = read_numbers("Dozens to hundreds of thousands of accounts.")
    assert [(spelled.raw, spelled.least) for spelled in found] == [
        ("Dozens", Decimal(24)),
        ("hundreds of thousands", Decimal(100_000)),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "One of the first engineers on the team.",
        "Migrated with zero downtime.",
        "Ran one-on-one mentoring and zero-downtime deploys.",
        "Became the single owner of the third-party integrations.",
        "Shipped it in the twenty-first sprint.",
        "Both teams shipped twice a year.",
        "Our goal was twofold.",
        "Hired a scaffold team, a manifold of tools.",
        "Saw a hundred-year storm in the logs.",
        "Read tens of logs.",
        "Spoke to several teams.",
        "Shipped the fix in half an hour.",
        "Saw it in the second half, by, half the team agreed.",
        "Used a multi-cloud setup.",
    ],
)
def test_one_ordinals_and_words_that_only_look_like_numbers_state_nothing(text: str) -> None:
    assert _claims(text) == []


def test_a_scale_ending_the_text_is_still_read() -> None:
    assert _claims("Served a million") == [("a million", ("1000000",))]


@pytest.mark.parametrize(
    "text",
    [
        "Joined Two Sigma in 2021.",
        "Two Sigma's research platform.",
        "Audited by the Big Four.",
        "Holds a Six Sigma Green Belt.",
        "Shipped two-factor authentication.",
        "Ran a three-tier architecture.",
        "Worked nine-to-five.",
        "A Dozen Engineers",
        "The service doubled as a cache.",
        "We doubled down on testing.",
        "Then Doubled throughput.",
    ],
)
def test_a_number_in_a_name_or_an_idiom_is_not_a_claim(text: str) -> None:
    found = read_numbers(text)
    assert found
    assert all(spelled.named for spelled in found)


def test_a_capitalised_number_before_a_recorded_technology_counts_it() -> None:
    """A capital before a recorded technology counts it, and one before a name names it."""
    tokens = tokenise("Twelve Kafka topics.")
    found = read_numbers("Twelve Kafka topics.", tokens, technology=lambda index: index == 1)
    assert [(spelled.raw, spelled.named) for spelled in found] == [("Twelve", False)]
    assert [spelled.named for spelled in read_numbers("Twelve Labs builds models.")] == [True]


def test_a_number_inside_a_recorded_technology_names_it() -> None:
    found = read_numbers("Applied Six Sigma.", technology=lambda index: index in {1, 2})
    assert [(spelled.raw, spelled.named) for spelled in found] == [("Six", True)]


def test_a_number_followed_by_punctuation_or_a_pronoun_still_counts() -> None:
    assert _claims("Six, I think.") == [("Six", ("6",))]
    assert _claims("Twelve I think.") == [("Twelve", ("12",))]
    assert _claims("Twelve.") == [("Twelve", ("12",))]
    assert _claims("Twelve AWS accounts.") == [("Twelve", ("12",))]


def test_numbers_anywhere_reads_every_cardinal_word_however_it_is_glued() -> None:
    assert list(numbers_anywhere("three.js nine-to-five twenty-five one zero dozens")) == [
        "3",
        "9",
        "5",
        "25",
    ]
