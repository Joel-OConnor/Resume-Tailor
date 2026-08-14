"""Tokenisation and stemming.

The hazard cases here are the whole reason the tokeniser exists: ordinary word splitting turns
``Node.js`` into two tokens and ``CI/CD`` into two more, and every one of those breaks a match.
"""

from __future__ import annotations

import pytest

from resume_tailor.match.tokens import normalise, stem, tokenise


def _surfaces(text: str) -> list[str]:
    return [token.surface for token in tokenise(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Node.js and NestJS", ["Node.js", "and", "NestJS"]),
        ("CI/CD pipelines", ["CI/CD", "pipelines"]),
        ("PL/pgSQL functions", ["PL/pgSQL", "functions"]),
        (".NET Core", [".NET", "Core"]),
        ("C++ and C#", ["C++", "and", "C#"]),
        ("We use Go.", ["We", "use", "Go"]),
        ("PostgreSQL, NoSQL, MySQL", ["PostgreSQL", "NoSQL", "MySQL"]),
        ("...", []),
        ("K8s at scale", ["K8s", "at", "scale"]),
    ],
)
def test_technology_punctuation_stays_inside_the_token(text: str, expected: list[str]) -> None:
    assert _surfaces(text) == expected


def test_a_leading_dot_survives_only_when_a_letter_follows() -> None:
    assert _surfaces("-- .NET -- ... --") == [".NET"]


def test_sentence_position_is_recorded() -> None:
    tokens = tokenise("Go fast. Go home")
    assert [t.sentence_initial for t in tokens] == [True, False, True, False]


def test_casing_signals() -> None:
    aws, postgres, plain = tokenise("AWS PostgreSQL kafka")
    assert aws.all_caps
    assert not postgres.all_caps
    assert postgres.has_inner_capital
    assert not plain.all_caps
    assert not plain.has_inner_capital


def test_normalise_folds_typography() -> None:
    assert normalise("“smart” — quotes’") == '"smart" - quotes\''


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("mentoring", "mentorship"),
        ("environments", "environment"),
        ("requirements", "requirement"),
        ("improvements", "improvement"),
        ("caching", "caching"),
        ("integrations", "integration"),
    ],
)
def test_stems_agree_across_inflections(left: str, right: str) -> None:
    """Single-pass stripping is not idempotent; both sides must land on the same stem."""
    assert stem(left) == stem(right)


@pytest.mark.parametrize("word", [".NET", "C++", "K8s", "CI/CD", "Go", "AWS"])
def test_punctuated_and_short_words_are_never_stemmed(word: str) -> None:
    assert stem(word) == word.casefold()


def test_stemming_never_eats_a_word_whole() -> None:
    assert stem("ceded") == "ceded"
