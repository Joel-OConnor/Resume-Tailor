"""Inline emphasis parsing."""

from __future__ import annotations

import pytest

from resume_tailor.documents.blocks import Span
from resume_tailor.documents.inline import parse_spans


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


def test_single_character_bold_runs_do_not_merge() -> None:
    """Greedy matching swallowed the closer, printing literal asterisks in the exported resume."""
    assert parse_spans("Scaled to **5** teams and **9** services") == (
        Span("Scaled to "),
        Span("5", bold=True),
        Span(" teams and "),
        Span("9", bold=True),
        Span(" services"),
    )


def test_single_character_bold_italic_runs_do_not_merge() -> None:
    assert parse_spans("***a*** and ***b***") == (
        Span("a", bold=True, italic=True),
        Span(" and "),
        Span("b", bold=True, italic=True),
    )


def test_many_delimiters_parse_without_blowing_up() -> None:
    """The matcher recurses; a pathological line must not hang or overflow the stack."""
    assert "".join(s.text for s in parse_spans("**a** " * 200)).strip() == ("a " * 200).strip()


def test_an_escaped_asterisk_inside_an_italic_run() -> None:
    """The closer must not land on an escaped delimiter — that is what the escape is for."""
    assert parse_spans(r"*100\* off*") == (Span("100* off", italic=True),)


def test_an_italic_flush_against_the_bold_closer() -> None:
    """Three stars in a row: the bold must close on the last two, not the first two."""
    assert parse_spans("**Cut latency by *38%***") == (
        Span("Cut latency by ", bold=True),
        Span("38%", bold=True, italic=True),
    )


def test_an_escaped_backslash_does_not_block_the_next_emphasis() -> None:
    assert parse_spans(r"a\\_x_") == (Span("a\\"), Span("x", italic=True))


def test_a_long_line_of_delimiters_parses_in_reasonable_time() -> None:
    """Unbounded backtracking made a 100KB line take over 20 seconds."""
    import time

    source = "**a " * 25000
    start = time.monotonic()
    parse_spans(source)
    assert time.monotonic() - start < 5
