"""Hold every number the resume prints to a number the profile itself states.

An invented figure is the classic way a generated resume fails. "Cut latency 40%" reads well,
survives the recruiter, and collapses the moment somebody asks how it was measured — so every
figure in the document has to normalise onto a figure the profile carries. Normalising is what
makes that comparison usable rather than pedantic: ``$55.1B`` and ``55.1B`` are the same claim,
``5900%`` and ``5900`` are the same claim, ``30+`` and ``30`` are the same claim, and ``$200k``
and ``200,000`` are the same claim.

``notes`` is deliberately left out of the supporting text. CLAUDE.md treats it as unconfirmed, so
a figure that lives only there is precisely the figure that must not reach a resume.

The same care runs the other way on the profile's side. A role that started ``2019-11`` states a
year, not eleven of anything, and ``EC2`` names a service, not two of something, wherever the
profile writes it. So a date supports only its year, a technology name supports only a figure the
resume check itself would read as one, and a digit glued behind letters supports nothing.

The other half of the job is not crying wolf. Digits appear inside technology names (``S3``,
``K8s``, ``ES6``), version numbers (``Python 3``, ``OAuth 2.0``), dates, and list markers, and
none of those is a claim about an outcome. Each gets an explicit exemption below.

A figure spelled out is the same claim as its digits: "nine years" is held to the profile exactly
as "9 years" is, and "4 million" is the "4M" it says. A size written as a word ("thousands of
users", "tens of millions") states no figure, but it does state a size, so it may claim no more
than the largest quantity the profile states. :mod:`resume_tailor.verify.numbers` does that reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from resume_tailor.match.lexicon import build_lexicon
from resume_tailor.match.tokens import Token, stem, tokenise
from resume_tailor.verify.dates import find_points
from resume_tailor.verify.models import Violation
from resume_tailor.verify.numbers import SCALES, Shape, numbers_anywhere, read_numbers
from resume_tailor.verify.source import Area, Kind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.profile.models import Profile
    from resume_tailor.verify.numbers import Spelled
    from resume_tailor.verify.source import Line, Source

__all__ = [
    "check_metrics",
    "figures_in",
    "largest_stated",
    "magnitudes_in",
    "prose_of",
    "supported_metrics",
]

_SCALES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_YEAR = re.compile(r"^[0-9]{4}")
# A plain four-digit number in this range is a year; it dates a claim and measures nothing.
_DATE_LIKE = re.compile(r"^(?:19|20)[0-9]{2}$")

# The scale and multiplier suffixes stop at any further letter, so "820ms" is 820 milliseconds and
# not 820 million, and "x86" or "4xx" is never a multiple.
_FIGURE = re.compile(
    r"(?P<currency>[$€£¥])?\s?"
    r"(?P<number>[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
    r"(?P<scale>[KkMmBb](?![A-Za-z0-9]))?"
    r"(?P<times>[xX×](?![A-Za-z0-9]))?"
    r"(?P<percent>%)?"
    r"(?P<plus>\+)?"
)
# A scale written as a word after the digits: "4 million", "$1.5 billion", "2 dozen".
_WORD_SCALE = re.compile(
    rf"[ \t]+(?P<word>{'|'.join(SCALES)})(?![A-Za-z])",
    re.IGNORECASE,
)
# Markdown a reader never sees: a bullet's list marker and every emphasis asterisk. It is blanked
# rather than deleted, so a figure read from the raw line still sits at the same position, and so
# the verb opening a bullet or following a bold "**Lead-in:**" reads as the start of a sentence.
_MARKUP = re.compile(r"^[ \t]*-(?=\s)|\*", re.MULTILINE)
# A lead-in ends a phrase however it is closed: "**Hiring:**", "**Hiring** —", "__Hiring__ |".
_LEAD_IN = re.compile(
    r"^(?P<marker>[ \t]*(?:[-*][ \t]+)?)(?P<open>\*\*|__|\*|_)(?P<label>[^*_]+?)(?P=open)"
    r"(?P<gap>[ \t]*)(?P<separator>[-–—|:.]?)"
)
# Four letters and up: "40% faster" locates the claim, while "$200k in" just quotes a preposition.
_TRAILING_WORD = re.compile(r" [A-Za-z]{4,12}(?![A-Za-z])")
# What a size counts: "thousands of users", "tens of millions of events".
_COUNTING = re.compile(r" of [A-Za-z]{2,12}(?![A-Za-z])")
_DURATION = re.compile(r"\+?(?:[ \t]+|-)(?:years?|yrs?)(?![A-Za-z])", re.IGNORECASE)
"""What follows a figure written as a duration: "8 years", "8+ yrs", "an 8-year career"."""
_YEARS_INSIDE = re.compile(r"[- ](?:years?|yrs?)$", re.IGNORECASE)
"""A figure read together with its unit, as a number in words is: "five-year"."""

_REASON = (
    "does not appear anywhere in the profile; remove it or replace it with a figure the profile "
    "states"
)
_LARGER = (
    "claims a size larger than any figure the profile states; remove it or replace it with a "
    "figure the profile states"
)


@dataclass(frozen=True, slots=True)
class _Figure:
    raw: str
    value: str
    start: int
    end: int
    plain: bool
    """True when nothing marks this as a quantity — the shape a version number has."""

    amount: Decimal = Decimal(0)
    """The value as a number, for comparing sizes."""

    ratio: bool = False
    """True for a percentage or a multiple, which measure a change rather than a quantity."""


def supported_metrics(profile: Profile, lexicon: Lexicon | None = None) -> frozenset[str]:
    """Return every figure the profile itself states, normalised for comparison.

    Prose supports every figure in it, even one after an acronym ("MTTR 60 percent") or one
    written in words ("six years", "a dozen", "doubled"), because a resume may restate a true
    figure in other words: "six years" prints as "6 years" and "doubled" as "2x". Only a digit
    glued behind letters (``EC2``, ``P99``, ``Q3``) is left out, as the resume check never reads
    one as a claim either. A date supports only its year, and a technology name only what
    :func:`figures_in` reads from it, so neither the month of ``2019-11`` nor the digit in ``EC2``
    becomes a figure a resume may print. A technology's years of use are not here at all: they
    back a figure only where it is written as a duration (:func:`check_metrics`), since a "5" that
    means five years of Kafka must not support "mentored 5 engineers".
    """
    if lexicon is None:
        lexicon = build_lexicon(profile)
    prose = {
        value for text in _profile_text(profile) for value in (*_stated(text), *_spelled(text))
    }
    names = {value for text in _profile_names(profile) for value in figures_in(text, lexicon)}
    return frozenset(prose | names | set(_profile_years(profile)))


def figures_in(text: str, lexicon: Lexicon) -> dict[str, str]:
    """Return every figure ``text`` claims, as normalised value to the text that wrote it.

    The same reading :func:`check_metrics` applies to a resume line, exemptions included, so a
    technology name (``EC2``) or a version (``Python 3``) is never mistaken for a claimed number.
    A figure written in words is read too, as the figure it states: "twelve" is 12, "a dozen" is
    12 and "doubled" is 2. A size with no figure ("thousands") is :func:`magnitudes_in`'s.
    """
    reading = _reading(text)
    tokens = tokenise(reading)
    found = {
        figure.value: figure.raw
        for figure in _figures(text)
        if not _explained(figure, tokens, (), lexicon)
    }
    for spelled in _spelled_claims(reading, tokens, (), lexicon):
        if spelled.shape is not Shape.MAGNITUDE:
            found.setdefault(spelled.values[0], spelled.raw)
    return found


def magnitudes_in(text: str, lexicon: Lexicon) -> dict[str, Decimal]:
    """Return every size ``text`` claims in words, as the words to the least they can mean.

    "Tens of millions of users" claims at least 10,000,000 of them; "dozens" at least 24.
    """
    reading = _reading(text)
    return {
        spelled.raw: spelled.least
        for spelled in _spelled_claims(reading, tokenise(reading), (), lexicon)
        if spelled.shape is Shape.MAGNITUDE
    }


def largest_stated(texts: Iterable[str]) -> Decimal:
    """Return the largest quantity ``texts`` state, which bounds every size a document may claim.

    A count, an amount or a size counts, in digits ("4M+", "$14k") or in words ("a million",
    "hundreds of millions"). A percentage or a multiple measures a change, not a quantity, and a
    bare year dates a claim, so none of them makes "thousands of users" true.
    """
    largest = Decimal(0)
    for text in texts:
        tokens = tokenise(text)
        for figure in _figures(text):
            if figure.ratio or (figure.plain and _DATE_LIKE.match(figure.raw)):
                continue
            if not _letter_led(tokens[_token_at(figure, tokens)].surface):
                largest = max(largest, figure.amount)
        for spelled in read_numbers(text, tokens):
            largest = max(largest, spelled.least)
    return largest


def prose_of(profile: Profile) -> Iterator[str]:
    """Yield every field a resume prints as a claim, rather than as a name, a title or a date.

    Contact details, names and dates are left out: a zip code, a phone number or "3M" as an
    employer states no size the resume could claim. So are ``notes``, which are unconfirmed.
    """
    yield from (profile.contact.headline, profile.summary, *profile.target_roles)
    for tenure in profile.experience:
        yield from (tenure.summary, tenure.industry)
        for role in tenure.roles:
            yield role.scope
            for highlight in role.highlights:
                yield from (highlight.label, highlight.text, *highlight.tags)
    yield from (entry.notes for entry in profile.education)
    yield from (item.notes for item in (*profile.certifications, *profile.awards))
    for project in profile.projects:
        yield from (project.description, project.outcome)


def check_metrics(source: Source, profile: Profile, lexicon: Lexicon) -> list[Violation]:
    """Check every figure the document prints against the figures the profile supports.

    A figure in digits or in words has to be one the profile states. A size in words
    ("thousands of users") may claim no more than the largest quantity the profile states.
    """
    supported = supported_metrics(profile, lexicon)
    durations = _durations(profile)
    largest = largest_stated(prose_of(profile))
    found: list[Violation] = []
    for line in source.lines:
        reading = _reading(line.text)
        tokens = tokenise(reading)
        dated = _dated_spans(line)
        found += [
            Violation("metric", _quote(line.text, figure.raw, figure.end), line.number, _REASON)
            for figure in _figures(line.text)
            if figure.value not in supported
            and not _a_recorded_duration(
                (figure.value,), figure.raw, figure.end, reading, durations
            )
            and not _explained(figure, tokens, dated, lexicon)
        ]
        for spelled in _spelled_claims(reading, tokens, dated, lexicon):
            if spelled.shape is Shape.MAGNITUDE:
                if spelled.least > largest:
                    quoted = _quote(line.text, spelled.raw, spelled.end, _COUNTING)
                    found.append(Violation("metric", quoted, line.number, _LARGER))
            elif supported.isdisjoint(spelled.values) and not _a_recorded_duration(
                spelled.values, spelled.raw, spelled.end, reading, durations
            ):
                quoted = _quote(line.text, spelled.raw, spelled.end)
                found.append(Violation("metric", quoted, line.number, _REASON))
    return found


def _spelled_claims(
    reading: str, tokens: list[Token], dated: tuple[tuple[int, int], ...], lexicon: Lexicon
) -> Iterator[Spelled]:
    """Yield every number ``reading`` writes in words as a claim: not a name, idiom or date."""
    for spelled in read_numbers(
        reading, tokens, technology=lambda index: _form_spanning(tokens, index, lexicon)
    ):
        if not spelled.named and not any(start <= spelled.start < end for start, end in dated):
            yield spelled


# --- what the profile supports --------------------------------------------------------------------
def _profile_text(profile: Profile) -> Iterator[str]:
    """Yield every free-text field the user wrote about themselves, except the unconfirmed notes.

    Technology names, stacks, tags and dates are read separately, by :func:`_profile_names` and
    :func:`_profile_years`.
    """
    contact = profile.contact
    yield from (contact.name, contact.headline, contact.email, contact.location, contact.phone)
    yield contact.work_authorization
    for link in contact.links:
        yield from (link.label, link.url)
    yield profile.summary
    yield from profile.target_roles
    yield from _experience_text(profile)
    yield from _credential_text(profile)


def _durations(profile: Profile) -> frozenset[str]:
    """Return the years of use the profile records for its technologies, normalised as figures are.

    An unrecorded duration is 0.0 and is left out: supporting a bare "0" would wave through
    "reduced incidents to 0" for every profile ever written.
    """
    return frozenset(
        value
        for group in profile.technologies
        for item in group.items
        if item.years
        for value in _stated(f"{item.years:g}")
    )


def _a_recorded_duration(
    values: tuple[str, ...], raw: str, end: int, reading: str, durations: frozenset[str]
) -> bool:
    """Report whether a figure is written as a duration the profile's technologies record.

    "8 years of Python" may rest on Python's recorded 8 years; "8 engineers" may not.
    """
    if durations.isdisjoint(values):
        return False
    return _YEARS_INSIDE.search(raw) is not None or _DURATION.match(reading, end) is not None


def _experience_text(profile: Profile) -> Iterator[str]:
    for tenure in profile.experience:
        yield from (tenure.company, tenure.location, tenure.industry, tenure.summary)
        for role in tenure.roles:
            yield from (role.title, role.scope)
            for highlight in role.highlights:
                yield from (highlight.label, highlight.text)


def _credential_text(profile: Profile) -> Iterator[str]:
    for education in profile.education:
        yield from (education.credential, education.institution)
        yield from (education.location, education.notes)
    for credential in (*profile.certifications, *profile.awards):
        yield from (credential.name, credential.issuer, credential.notes)
    for project in profile.projects:
        yield from (project.name, project.description, project.outcome)


def _profile_names(profile: Profile) -> Iterator[str]:
    """Yield every technology name the profile records: its list, each stack, each tag."""
    for group in profile.technologies:
        yield group.group
        for item in group.items:
            yield item.name
            yield from item.aliases
    for tenure in profile.experience:
        for role in tenure.roles:
            yield from role.stack
            for highlight in role.highlights:
                yield from highlight.tags
    for project in profile.projects:
        yield from project.stack


def _profile_years(profile: Profile) -> Iterator[str]:
    """Yield the year of every date the profile records, which is all a date states as a figure."""
    dates = [
        value
        for tenure in profile.experience
        for role in tenure.roles
        for value in (role.start, role.end)
    ]
    dates += [education.completed for education in profile.education]
    dates += [credential.year for credential in (*profile.certifications, *profile.awards)]
    for value in dates:
        if match := _YEAR.match(value):
            yield match.group()


def _stated(text: str) -> Iterator[str]:
    """Yield every figure in a line of profile prose, except a digit that is part of a name."""
    tokens = tokenise(text)
    for figure in _figures(text):
        if not _letter_led(tokens[_token_at(figure, tokens)].surface):
            yield figure.value


def _spelled(text: str) -> Iterator[str]:
    """Yield every number a line of profile prose writes in words: "six", "a dozen", "halved".

    Read as generously as it can be, names and idioms included, since this side only supports: a
    profile's "Six Sigma" or "two-factor" lets a resume print the same words wherever it puts them.
    """
    yield from numbers_anywhere(text)
    for spelled in read_numbers(text):
        yield from spelled.values


# --- reading figures ------------------------------------------------------------------------------
def _figures(text: str) -> list[_Figure]:
    """Read every figure written in digits, with the scale word after it if it has one.

    "4 million" is the "4M" it states, not a 4: read without its scale, it would be supported by
    any 4 the profile states, and would never match the profile's own "4M".
    """
    figures: list[_Figure] = []
    for match in _FIGURE.finditer(text):
        scale = match["scale"] or ""
        amount = Decimal(match["number"].replace(",", "")) * _SCALES.get(scale.casefold(), 1)
        end, worded = match.end(), None
        if not (scale or match["times"] or match["percent"]):
            worded = _WORD_SCALE.match(text, end)
        if worded is not None:
            amount *= SCALES[worded["word"].casefold()]
            end = worded.end()
        figures.append(
            _Figure(
                raw=text[match.start() : end].strip(),
                value=format(amount.normalize(), "f"),
                start=match.start("number"),
                end=end,
                plain=worded is None
                and not any(
                    (match["currency"], scale, match["times"], match["percent"], match["plus"])
                ),
                amount=amount,
                ratio=bool(match["times"] or match["percent"]),
            )
        )
    return figures


def _reading(text: str) -> str:
    """Blank the Markdown a reader never sees, keeping every other character where it was.

    A leading lead-in is closed with a colon, whatever separator the writer used after it, so the
    word following it reads as the start of a sentence, as it does to a reader.
    """
    text = _LEAD_IN.sub(_closed, text, count=1)
    return _MARKUP.sub(lambda match: " " * len(match.group()), text)


def _closed(match: re.Match[str]) -> str:
    """Rewrite a lead-in as its bare label and a colon, at exactly the same length."""
    size = len(match["open"])
    return "".join(
        (
            match["marker"],
            " " * size,
            match["label"],
            " " * (size - 1) + ":",
            match["gap"],
            " " * len(match["separator"]),
        )
    )


def _quote(text: str, raw: str, end: int, follower: re.Pattern[str] = _TRAILING_WORD) -> str:
    """Quote a figure with the word it qualifies, so the writer can find it in its own draft."""
    match = follower.match(text, end)
    return raw + (match.group() if match else "")


#: Words that follow a version rather than a quantity — "Java 17 and", "SOC 2 in scope".
_FUNCTION_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "across",
        "under",
        "over",
        "via",
    ]
)


#: Words that say the figure before them is an amount: "60 percent", "400 ms", "12 minutes".
#: A version is never followed by one, so they hold after any acronym, not only a known measure.
#: A bare "s" is left out: "Python 3's" tokenises to "3" and "s".
_UNITS = frozenset(
    [
        "percent",
        "percentage",
        "pct",
        "points",
        "pts",
        "bps",
        "basis",
        "ms",
        "msec",
        "sec",
        "secs",
        "second",
        "seconds",
        "min",
        "mins",
        "minute",
        "minutes",
        "hr",
        "hrs",
        "hour",
        "hours",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "yrs",
        "kb",
        "mb",
        "gb",
        "tb",
        "pb",
        "rps",
        "qps",
        "tps",
    ]
)
_LEADING_NUMBER = re.compile(r"^[0-9.,]+")

#: Acronyms a result is measured in. A number after one is a reading of it, never a version.
_MEASURES = frozenset(
    [
        "aov",
        "arr",
        "aum",
        "cac",
        "csat",
        "dau",
        "gmv",
        "kpi",
        "ltv",
        "mau",
        "mrr",
        "mtbf",
        "mtta",
        "mttd",
        "mttr",
        "nps",
        "qps",
        "roi",
        "rpo",
        "rps",
        "rto",
        "sla",
        "slo",
        "tco",
        "tps",
        "wau",
    ]
)


# --- exemptions -----------------------------------------------------------------------------------
def _dated_spans(line: Line) -> tuple[tuple[int, int], ...]:
    """Return the characters the date check already owns, so no figure is read from them twice.

    History reads the dates on a role's dates line, and on every line under a credentials heading.
    """
    owned = (line.kind is Kind.META and line.area is Area.EXPERIENCE) or (
        line.kind is not Kind.HEADING and line.area is Area.EDUCATION
    )
    if not owned:
        return ()
    return tuple((span.start, span.end) for span in find_points(line.text))


def _explained(
    figure: _Figure, tokens: list[Token], dated: tuple[tuple[int, int], ...], lexicon: Lexicon
) -> bool:
    """Report whether this figure is something other than a claim about an outcome."""
    if any(start <= figure.start < end for start, end in dated):
        return True
    index = _token_at(figure, tokens)
    if _letter_led(tokens[index].surface):
        return True
    return _version_position(figure, tokens, index, lexicon)


def _token_at(figure: _Figure, tokens: list[Token]) -> int:
    """Return the index of the token holding the figure's first digit.

    Every digit lies inside a token: tokenise() keeps digits and only trims edge punctuation.
    """
    return max((i for i, token in enumerate(tokens) if token.start <= figure.start), default=0)


def _letter_led(surface: str) -> bool:
    """Report whether digits are glued behind letters, as in S3, EC2, K8s, ES6, x86.

    A quantity is written digits-first — 4M, 200k, 820ms, 99.98% — so the two never collide.
    """
    return surface[:1].isalpha() and any(character.isdigit() for character in surface)


def _form_spanning(tokens: list[Token], index: int, lexicon: Lexicon) -> bool:
    """Report whether a known technology name covers the token at ``index``."""
    for size in range(min(lexicon.max_length, len(tokens)), 0, -1):
        first = max(index - size + 1, 0)
        for start in range(first, min(index + 1, len(tokens) - size + 1)):
            keys = tuple(token.lower for token in tokens[start : start + size])
            if keys in lexicon.by_tokens or tuple(stem(key) for key in keys) in lexicon.by_stems:
                return True
    return False


def _version_position(figure: _Figure, tokens: list[Token], index: int, lexicon: Lexicon) -> bool:
    """Report whether the figure is a version hanging off a product name: SOC 2, Python 3.

    A version never carries a currency symbol, a percent sign, a magnitude or multiplier suffix,
    or a trailing "+", which is what keeps "$200k", "40%" and "5x" out of this exemption no matter
    what precedes them. Nor is it followed by a unit, spaced or glued ("60 percent", "400ms"), or
    preceded by what a result is measured in ("MTTR 45"), which is what keeps "Cut MTTR 60
    percent" and "Cut TTFB 400 ms" claims.
    """
    if not figure.plain or not index:
        return False
    previous = tokens[index - 1]
    glued = _LEADING_NUMBER.sub("", tokens[index].lower)
    if previous.lower in _MEASURES or _UNITS & {glued, _following(tokens, index)}:
        return False
    if (
        _form_spanning(tokens, index - 1, lexicon)
        or previous.all_caps
        or previous.has_inner_capital
    ):
        return True
    # Ordinary capitalisation alone is not enough: a resume bullet opens with a capitalised verb,
    # so "Mentored 30 junior engineers" would exempt itself from the one check that stops an
    # inflated headcount. What separates it from "Java 17" is what comes after — a quantity is
    # followed by the thing it counts, a version is followed by punctuation or a function word.
    capitalised = previous.surface[:1].isupper() and not previous.sentence_initial
    return capitalised and not _counts_something(tokens, index)


def _counts_something(tokens: list[Token], index: int) -> bool:
    """Report whether a word the figure could be quantifying follows it."""
    following = _following(tokens, index)
    return bool(following) and following not in _FUNCTION_WORDS


def _following(tokens: list[Token], index: int) -> str:
    """Return the word after the figure, casefolded, or nothing at the end of the text."""
    return tokens[index + 1].lower if index + 1 < len(tokens) else ""
