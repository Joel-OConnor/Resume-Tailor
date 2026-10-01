"""Read the numbers a document writes in words: "nine years", "a dozen services", "halved".

A check that reads only digits can be walked around by spelling the figure out: "Mentored twelve
engineers" claims exactly what "Mentored 12 engineers" does. So numbers written as words are read
here the way :mod:`resume_tailor.verify.metrics` reads digits, in three shapes:

* **a number**: a cardinal ("nine", "twenty-five", "twenty five"), scaled by the words after it
  ("two hundred", "a million", "a dozen", "half a dozen", "a decade"), or an availability written
  as nines ("five nines" is 99.999);
* **a multiple**: "doubled", "tripled", "halved", "cut in half", "tenfold", each of which states a
  ratio as surely as "2x" or "50%" does;
* **a magnitude**: "thousands", "tens of millions", "several hundred", "multi-million",
  "seven-figure". It states no figure, but it does state a size, so it is read as the least it
  can mean.

Precision runs the other way too, because a false alarm on a true line costs a retry. "One" and
"zero" are never read on their own ("one of the first engineers" counts nothing), and neither is
any ordinal, "single", "both" or "twice". A reading the context shows is not a count is kept but
marked :attr:`Spelled.named`: a capitalised number inside a name ("Two Sigma", "the Big Four",
"Six Sigma"), a hyphenated idiom ("two-factor", "three-tier", "nine-to-five"), a phrase inside a
technology the profile records, and "doubled as". The profile's side reads those too, since a
profile's "Six Sigma" has to support a resume that opens a sentence with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import tokenise

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from resume_tailor.match.tokens import Token

__all__ = ["SCALES", "Shape", "Spelled", "numbers_anywhere", "read_numbers"]

_UNIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_TEEN_WORDS = (
    *("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen"),
    *("seventeen", "eighteen", "nineteen"),
)
_TENS_WORDS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_UNITS = {word: value for value, word in enumerate(_UNIT_WORDS)}
_TENS = {word: 20 + 10 * index for index, word in enumerate(_TENS_WORDS)}
_CARDINALS = {word: value for word, value in _UNITS.items() if value > 1}
_CARDINALS |= {word: 10 + index for index, word in enumerate(_TEEN_WORDS)}
_CARDINALS |= _TENS
"""Every number one word states. "One" and "zero" alone state nothing a resume claims."""

SCALES: dict[str, int] = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
    "dozen": 12,
    "decade": 10,
    "decades": 10,
}
"""Words that multiply the number before them, in digits or in words: "4 million", "a dozen"."""

_ONE = frozenset({"a", "one"})
"""Words that state one of a scale and nothing alone: "a dozen", "one million", but not "one"."""

_MAGNITUDES = {
    "dozens": 24,
    "hundreds": 100,
    "thousands": 1_000,
    "millions": 1_000_000,
    "billions": 1_000_000_000,
    "trillions": 1_000_000_000_000,
}
"""Sizes in the plural, each read as the least it can mean: "dozens" is two dozen at least."""

_PREFIXES = {"tens": 10, "dozens": 24, "hundreds": 100, "thousands": 1_000}
"""A size that multiplies a larger one after "of": "tens of millions", "hundreds of thousands"."""

_LARGE = frozenset({"thousands", "millions", "billions", "trillions"})
_FEW = frozenset({"several", "few", "couple", "many"})
"""Words that say "some" of a scale: "several hundred", "a few thousand", "a couple hundred"."""

_MULTIPLES = {
    "doubled": ("2", "100"),
    "doubling": ("2", "100"),
    "tripled": ("3", "200"),
    "tripling": ("3", "200"),
    "quadrupled": ("4", "300"),
    "quadrupling": ("4", "300"),
    "halved": ("50",),
    "halving": ("50",),
}
"""A multiple, as every figure it can be printed as: "doubled" is "2x", and it is "100%" more."""

_IDIOMS = frozenset({"as", "down", "up"})
"""What follows a multiple that is not one: "doubled as the on-call lead", "doubled down"."""

_HALVING = frozenset({"in", "by"})
_ONE_OF = frozenset({"a", "an"})
"""An article after "half" makes it half of a thing ("half an hour"), not half of the result."""
_LEAST_FOLD = 3
"""Below threefold, "-fold" is an idiom: "the goal was twofold"."""

_COUNTED = frozenset(
    {
        *("year", "years", "month", "months", "week", "weeks", "day", "days"),
        *("hour", "hours", "minute", "minutes", "person", "people", "member", "members"),
        "plus",
    }
)
"""What a hyphenated number may count and still be a claim: "five-person team", "twenty-plus".

Every other word hyphenated to a number makes it part of a name or an idiom: "two-factor",
"three-tier", "two-pizza", "nine-to-five", "twenty-first".
"""

_ARTICLES = frozenset({"a", "half"})
_FIGURE = "figure"
_FOLD = "fold"
_HALF = "half"
_MULTI = "multi"
_MULTI_SCALES = frozenset({"million", "billion"})
_NINES = "nines"
_OF = "of"
_PERCENT = 100
_FIRST_TENS = 20
# A word, and the word hyphenated to it, so "twenty-five" reads as one number. Read casefolded.
_SPELLED = re.compile(r"(?<![a-z])(?P<word>[a-z]+)(?:-(?P<unit>[a-z]+))?(?![a-z])")


class Shape(StrEnum):
    """What a number written in words states."""

    NUMBER = "number"
    """An exact number: "nine", "a dozen", "two hundred"."""

    MULTIPLE = "multiple"
    """A ratio: "doubled", "halved", "tenfold"."""

    MAGNITUDE = "magnitude"
    """A size with no exact figure: "thousands", "tens of millions"."""


@dataclass(frozen=True, slots=True)
class Spelled:
    """One number a text writes in words."""

    raw: str
    """The words as written, to quote back to the writer: "a dozen", "tens of millions"."""

    start: int
    end: int
    shape: Shape
    values: tuple[str, ...] = ()
    """A number's or a multiple's figure, normalised as digits are, in every form it may take."""

    least: Decimal = Decimal(0)
    """The smallest quantity a number or a magnitude can mean; nothing for a multiple."""

    named: bool = False
    """True when the context shows a name or an idiom rather than a count."""

    first: int = 0
    last: int = 0
    """The indexes of the first and the last token the words span."""


def _unrecorded(_index: int) -> bool:
    return False


def read_numbers(
    text: str,
    tokens: list[Token] | None = None,
    *,
    technology: Callable[[int], bool] = _unrecorded,
) -> list[Spelled]:
    """Return every number ``text`` writes in words, in the order it writes them.

    ``tokens`` is ``text`` tokenised, when the caller already has it. ``technology`` reports
    whether a technology the profile records covers the token at an index: a number inside one
    ("Six Sigma", "Twelve-Factor App") names it, and a number before one counts it ("Twelve Kafka
    topics").
    """
    tokens = tokenise(text) if tokens is None else tokens
    found: list[Spelled] = []
    index = 0
    while index < len(tokens):
        spelled = _read_at(text, tokens, index, technology)
        if spelled is None:
            index += 1
            continue
        inside = any(map(technology, range(spelled.first, spelled.last + 1)))
        found.append(replace(spelled, named=spelled.named or inside))
        index = spelled.last + 1
    return found


def numbers_anywhere(text: str) -> Iterator[str]:
    """Yield every cardinal ``text`` writes as a word anywhere, glued or hyphenated or not.

    The most generous reading there is, for the side of a comparison that supports: "three.js",
    "nine-to-five" and "two-factor" each state a number here, though no claim is ever read from
    them. "Twenty-five" is one number, and "one" and "zero" alone are none.
    """
    for match in _SPELLED.finditer(text.casefold()):
        value = _CARDINALS.get(match["word"])
        if value is None:
            continue
        unit = _UNITS.get(match["unit"] or "", 0) if value >= _FIRST_TENS else 0
        yield str(value + unit)


# --- the three shapes -----------------------------------------------------------------------------
def _read_at(
    text: str, tokens: list[Token], index: int, technology: Callable[[int], bool]
) -> Spelled | None:
    """Read the number in words that starts at ``tokens[index]``, if one does."""
    word = tokens[index].lower
    if word in _MULTIPLES:
        return _multiple(text, tokens, index)
    if word == _HALF and index and _halving(tokens, index):
        return replace(_span(text, tokens, index - 1, index, Shape.MULTIPLE), values=("50",))
    if (magnitude := _magnitude(text, tokens, index)) is not None:
        return _proper(magnitude, tokens, technology)
    if (number := _number(text, tokens, index)) is not None:
        return _proper(number, tokens, technology)
    return None


def _halving(tokens: list[Token], index: int) -> bool:
    """Report whether "half" cuts something in two: "cut in half", "by half", "in half the time".

    "In half an hour" is a duration, not a ratio, so "half" before "a" or "an" is left alone.
    """
    joined = not tokens[index].break_before and tokens[index - 1].lower in _HALVING
    return joined and _joined(tokens, index + 1) not in _ONE_OF


def _multiple(text: str, tokens: list[Token], index: int) -> Spelled:
    """Read "doubled", "halving" and the like; "doubled as" and "doubled down" are idioms."""
    token = tokens[index]
    capitalised = token.surface[:1].isupper() and not token.sentence_initial
    named = capitalised or _joined(tokens, index + 1) in _IDIOMS
    spelled = _span(text, tokens, index, index, Shape.MULTIPLE)
    return replace(spelled, values=_MULTIPLES[token.lower], named=named)


def _magnitude(text: str, tokens: list[Token], index: int) -> Spelled | None:
    """Read a size: "thousands", "tens of millions", "several hundred", "multi-million"."""
    word = tokens[index].lower
    after = _joined(tokens, index + 1)
    if word in _PREFIXES and after == _OF and _joined(tokens, index + 2) in _LARGE:
        least = _PREFIXES[word] * _MAGNITUDES[tokens[index + 2].lower]
        return _sized(_span(text, tokens, index, index + 2, Shape.MAGNITUDE), least)
    if word in _MAGNITUDES:
        return _sized(_span(text, tokens, index, index, Shape.MAGNITUDE), _MAGNITUDES[word])
    if word in _FEW and after in SCALES:
        return _sized(_span(text, tokens, index, index + 1, Shape.MAGNITUDE), SCALES[after])
    if word.startswith(_MULTI):
        scale = word.removeprefix(_MULTI).removeprefix("-").partition("-")[0]
        if scale in _MULTI_SCALES:
            return _sized(_span(text, tokens, index, index, Shape.MAGNITUDE), SCALES[scale])
    return None


def _number(text: str, tokens: list[Token], index: int) -> Spelled | None:
    """Read an exact number: a cardinal or "a" with the scales after it, or a hyphenated one."""
    word = tokens[index].lower
    lead, rest = _cardinal(word)
    if lead is None and word.endswith(_FOLD):
        return _fold(_span(text, tokens, index, index, Shape.MULTIPLE), word.removesuffix(_FOLD))
    if lead is not None and rest:
        return _hyphenated(_span(text, tokens, index, index, Shape.NUMBER), lead, rest[0])
    if lead is not None:
        lead, last = _units_after(tokens, index, lead)
    elif word == _HALF and _joined(tokens, index + 1) == "a":
        lead, last = Decimal("0.5"), index + 1
    elif word in _ONE:
        lead, last = Decimal(1), index
    else:
        return None
    value, scaled = lead, last
    while (scale := _joined(tokens, scaled + 1)) in SCALES:
        value *= SCALES[scale]
        scaled += 1
    if scaled == last and lead <= 1:
        return None  # "a", "one" and "half a" state nothing without a scale after them
    if scaled == last and _joined(tokens, last + 1) == _NINES:
        nines = _PERCENT - Decimal(10) ** (2 - int(lead))
        return replace(_span(text, tokens, index, last + 1, Shape.NUMBER), values=(_normal(nines),))
    return _counted(_span(text, tokens, index, scaled, Shape.NUMBER), value)


def _units_after(tokens: list[Token], index: int, lead: Decimal) -> tuple[Decimal, int]:
    """Join "twenty five" into 25, as a writer who leaves the hyphen out still means it."""
    unit = _UNITS.get(_joined(tokens, index + 1), 0)
    if tokens[index].lower in _TENS and unit:
        return lead + unit, index + 1
    return lead, index


def _hyphenated(spelled: Spelled, lead: Decimal, suffix: str) -> Spelled | None:
    """Read "five-person", "twenty-plus", "seven-figure", "ten-fold"; "two-factor" is a name."""
    if suffix == _FIGURE:
        least = Decimal(10) ** (int(lead) - 1)
        return _sized(replace(spelled, shape=Shape.MAGNITUDE), least)
    if suffix == _FOLD:
        return _folded(replace(spelled, shape=Shape.MULTIPLE), lead)
    return replace(_counted(spelled, lead), named=suffix not in _COUNTED)


def _fold(spelled: Spelled, head: str) -> Spelled | None:
    """Read "tenfold" or "hundredfold"; anything else ending in "fold" is no number."""
    lead, rest = _cardinal(head)
    if lead is None and head in SCALES:
        lead, rest = Decimal(SCALES[head]), []
    return None if lead is None or rest else _folded(spelled, lead)


def _folded(spelled: Spelled, lead: Decimal) -> Spelled | None:
    """Return a multiple of three or more; "twofold" is too often an idiom to read as one."""
    return replace(spelled, values=(_normal(lead),)) if lead >= _LEAST_FOLD else None


def _cardinal(word: str) -> tuple[Decimal | None, list[str]]:
    """Return the number a word, or a hyphenated word, opens with, and the parts after it.

    "twenty-five-person" opens with 25 and leaves "person"; "nine" leaves nothing. "One-on-one",
    "zero-downtime", "tenfold" and "team" open with no number: one and zero are never read.
    """
    parts = word.split("-")
    if not all(part.isalpha() for part in parts):
        return None, []
    if parts[0] in _TENS and len(parts) > 1 and _UNITS.get(parts[1], 0) > 0:
        return Decimal(_TENS[parts[0]] + _UNITS[parts[1]]), parts[2:]
    if parts[0] in _CARDINALS:
        return Decimal(_CARDINALS[parts[0]]), parts[1:]
    return None, []


# --- context --------------------------------------------------------------------------------------
def _proper(spelled: Spelled, tokens: list[Token], technology: Callable[[int], bool]) -> Spelled:
    """Mark a number that a capital shows is part of a name: "Two Sigma", "the Big Four".

    A capitalised number inside a sentence names something. At the start of one, it does only
    when a title-case word follows it directly that is not a technology the profile records:
    "Two Sigma" names a firm, "Twelve Kafka topics" counts topics, "Twelve engineers" counts
    people. An article before the number ("A dozen") is only the sentence's capital.
    """
    at = spelled.first
    while at < spelled.last and tokens[at].lower in _ARTICLES:
        at += 1
    if not tokens[at].surface[:1].isupper():
        return spelled
    if at != spelled.first or not tokens[at].sentence_initial:
        return replace(spelled, named=True)
    following = spelled.last + 1
    if following >= len(tokens) or tokens[following].break_before:
        return spelled
    after = tokens[following].surface
    title_case = after[:1].isupper() and any(character.islower() for character in after[1:])
    return replace(spelled, named=True) if title_case and not technology(following) else spelled


# --- building readings ----------------------------------------------------------------------------
def _span(text: str, tokens: list[Token], first: int, last: int, shape: Shape) -> Spelled:
    start, end = tokens[first].start, tokens[last].end
    return Spelled(text[start:end], start, end, shape, first=first, last=last)


def _sized(spelled: Spelled, least: Decimal | int) -> Spelled:
    return replace(spelled, least=Decimal(least))


def _counted(spelled: Spelled, value: Decimal) -> Spelled:
    return replace(spelled, values=(_normal(value),), least=value)


def _joined(tokens: list[Token], index: int) -> str:
    """Return the word at ``index`` when nothing but space joins it to the one before it."""
    if index >= len(tokens) or tokens[index].break_before:
        return ""
    return tokens[index].lower


def _normal(value: Decimal) -> str:
    """Normalise a value exactly as a figure written in digits is normalised."""
    return format(value.normalize(), "f")
