"""Inline emphasis parsing."""

from __future__ import annotations

import pytest

from resume_tailor.documents.blocks import Span
from resume_tailor.documents.inline import parse_spans, spans_to_text


def test_plain_text_is_one_span() -> None:
    assert parse_spans("hello world") == (Span("hello world"),)


def test_empty_string_yields_no_spans() -> None:
    assert parse_spans("") == ()


def test_bold_segment() -> None:
    assert parse_spans("a **b** c") == (Span("a "), Span("b", bold=True), Span(" c"))


@pytest.mark.parametrize("source", ["a *b* c", "a _b_ c"])
def test_italic_segment(source: str) -> None:
    assert parse_spans(source) == (Span("a "), Span("b", italic=True), Span(" c"))


def test_bold_italic_segment() -> None:
    assert parse_spans("***both***") == (Span("both", bold=True, italic=True),)


def test_baseline_emphasis_applies_to_unmarked_text() -> None:
    assert parse_spans("dates **now**", italic=True) == (
        Span("dates ", italic=True),
        Span("now", bold=True, italic=True),
    )


def test_baseline_bold_survives_an_italic_marker() -> None:
    assert parse_spans("a *b*", bold=True) == (
        Span("a ", bold=True),
        Span("b", bold=True, italic=True),
    )


def test_adjacent_identical_spans_merge() -> None:
    assert parse_spans("*a*_b_") == (Span("ab", italic=True),)


def test_underscores_inside_a_word_are_literal() -> None:
    assert parse_spans("snake_case_name") == (Span("snake_case_name"),)


def test_lone_asterisk_is_literal() -> None:
    assert parse_spans("2 * 3 = 6") == (Span("2 * 3 = 6"),)


def test_asterisk_pair_needs_non_space_edges() -> None:
    assert parse_spans("a * b * c") == (Span("a * b * c"),)


def test_single_character_italic() -> None:
    assert parse_spans("*x*") == (Span("x", italic=True),)


def test_bold_wins_over_italic_at_the_same_position() -> None:
    assert parse_spans("**bold** and *it*") == (
        Span("bold", bold=True),
        Span(" and "),
        Span("it", italic=True),
    )


def test_spans_to_text_round_trips_the_visible_text() -> None:
    assert spans_to_text(parse_spans("a **b** *c*")) == "a b c"


def test_spans_to_text_of_nothing() -> None:
    assert spans_to_text(()) == ""


# --- nesting -------------------------------------------------------------------------------------
def test_bold_nested_inside_italic() -> None:
    """The documented `*Tech Stack — …*` note may bold one item; the markers must not survive."""
    assert parse_spans("*Stack — Go, **Python**, Kafka*") == (
        Span("Stack — Go, ", italic=True),
        Span("Python", bold=True, italic=True),
        Span(", Kafka", italic=True),
    )


def test_italic_nested_inside_bold() -> None:
    assert parse_spans("**Reduced *p99* latency**") == (
        Span("Reduced ", bold=True),
        Span("p99", bold=True, italic=True),
        Span(" latency", bold=True),
    )


def test_underscore_italic_nested_inside_bold() -> None:
    assert parse_spans("**Note _really_ important**") == (
        Span("Note ", bold=True),
        Span("really", bold=True, italic=True),
        Span(" important", bold=True),
    )


# --- delimiters that must stay literal ------------------------------------------------------------
def test_space_padded_double_asterisks_are_literal() -> None:
    """`*` already required non-space edges; `**` must match, or stray text gets bolded."""
    assert parse_spans("a ** b ** c") == (Span("a ** b ** c"),)


# --- escapes -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"literal \*star\* here", "literal *star* here"),
        (r"a \_b\_ c", "a _b_ c"),
        (r"back\\slash", "back\\slash"),
    ],
)
def test_backslash_escapes_a_marker(source: str, expected: str) -> None:
    assert parse_spans(source) == (Span(expected),)


def test_an_escaped_marker_does_not_open_emphasis() -> None:
    assert parse_spans(r"\*not italic* at all") == (Span("*not italic* at all"),)
