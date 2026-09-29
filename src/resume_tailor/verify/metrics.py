"""Hold every number the resume prints to a number the profile itself states.

An invented figure is the classic way a generated resume fails. "Cut latency 40%" reads well,
survives the recruiter, and collapses the moment somebody asks how it was measured — so every
figure in the document has to normalise onto a figure the profile carries. Normalising is what
makes that comparison usable rather than pedantic: ``$55.1B`` and ``55.1B`` are the same claim,
``5900%`` and ``5900`` are the same claim, ``30+`` and ``30`` are the same claim, and ``$200k``
and ``200,000`` are the same claim.

``notes`` is deliberately left out of the supporting text. CLAUDE.md treats it as unconfirmed, so
a figure that lives only there is precisely the figure that must not reach a resume.

The other half of the job is not crying wolf. Digits appear inside technology names (``S3``,
``K8s``, ``ES6``), version numbers (``Python 3``, ``OAuth 2.0``), dates, and list markers, and
none of those is a claim about an outcome. Each gets an explicit exemption below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import Token, stem, tokenise
from resume_tailor.verify.dates import find_points
from resume_tailor.verify.models import Violation
from resume_tailor.verify.source import Area, Kind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.profile.models import Profile
    from resume_tailor.verify.source import Line, Source

__all__ = ["check_metrics", "figures_in", "supported_metrics"]

_SCALES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_DATED_AREAS = frozenset({Area.EXPERIENCE, Area.EDUCATION})

# The scale suffix stops at any further letter, so "820ms" is 820 milliseconds and not 820 million.
_FIGURE = re.compile(
    r"(?P<currency>[$€£¥])?\s?"
    r"(?P<number>[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
    r"(?P<scale>[KkMmBb](?![A-Za-z0-9]))?"
    r"(?P<percent>%)?"
    r"(?P<plus>\+)?"
)
# Four letters and up: "40% faster" locates the claim, while "$200k in" just quotes a preposition.
_TRAILING_WORD = re.compile(r" [A-Za-z]{4,12}(?![A-Za-z])")

_REASON = (
    "does not appear anywhere in the profile; remove it or replace it with a figure the profile "
    "states"
)


@dataclass(frozen=True, slots=True)
class _Figure:
    raw: str
    value: str
    start: int
    end: int
    plain: bool
    """True when nothing marks this as a quantity — the shape a version number has."""


def supported_metrics(profile: Profile) -> frozenset[str]:
    """Return every figure the profile itself states, normalised for comparison."""
    return frozenset(figure.value for text in _profile_text(profile) for figure in _figures(text))


def figures_in(text: str, lexicon: Lexicon) -> dict[str, str]:
    """Return every figure ``text`` claims, as normalised value to the text that wrote it.

    The same reading :func:`check_metrics` applies to a resume line, exemptions included, so a
    technology name (``EC2``) or a version (``Python 3``) is never mistaken for a claimed number.
    """
    tokens = tokenise(text)
    return {
        figure.value: figure.raw
        for figure in _figures(text)
        if not _explained(figure, tokens, (), lexicon)
    }


def check_metrics(source: Source, profile: Profile, lexicon: Lexicon) -> list[Violation]:
    """Check every figure the document prints against the figures the profile supports."""
    supported = supported_metrics(profile)
    found: list[Violation] = []
    for line in source.lines:
        tokens = tokenise(line.text)
        dated = _dated_spans(line)
        found += [
            Violation("metric", _quote(line.text, figure), line.number, _REASON)
            for figure in _figures(line.text)
            if figure.value not in supported and not _explained(figure, tokens, dated, lexicon)
        ]
    return found


# --- what the profile supports --------------------------------------------------------------------
def _profile_text(profile: Profile) -> Iterator[str]:
    """Yield every string the user wrote about themselves, except the unconfirmed notes."""
    contact = profile.contact
    yield from (contact.name, contact.headline, contact.email, contact.location, contact.phone)
    yield contact.work_authorization
    for link in contact.links:
        yield from (link.label, link.url)
    yield profile.summary
    yield from profile.target_roles
    yield from _technology_text(profile)
    yield from _experience_text(profile)
    yield from _credential_text(profile)


def _technology_text(profile: Profile) -> Iterator[str]:
    for group in profile.technologies:
        yield group.group
        for item in group.items:
            yield item.name
            yield from item.aliases
            # An unrecorded duration is 0.0, and supporting a bare "0" would wave through
            # "reduced incidents to 0" for every profile ever written.
            if item.years:
                yield f"{item.years:g}"


def _experience_text(profile: Profile) -> Iterator[str]:
    for tenure in profile.experience:
        yield from (tenure.company, tenure.location, tenure.industry, tenure.summary)
        for role in tenure.roles:
            yield from (role.title, role.start, role.end, role.scope)
            yield from role.stack
            for highlight in role.highlights:
                yield from (highlight.label, highlight.text)
                yield from highlight.tags


def _credential_text(profile: Profile) -> Iterator[str]:
    for education in profile.education:
        yield from (education.credential, education.institution, education.completed)
        yield from (education.location, education.notes)
    for credential in (*profile.certifications, *profile.awards):
        yield from (credential.name, credential.issuer, credential.year, credential.notes)
    for project in profile.projects:
        yield from (project.name, project.description, project.outcome)
        yield from project.stack


# --- reading figures ------------------------------------------------------------------------------
def _figures(text: str) -> list[_Figure]:
    figures: list[_Figure] = []
    for match in _FIGURE.finditer(text):
        scale = match["scale"] or ""
        amount = Decimal(match["number"].replace(",", "")) * _SCALES.get(scale.casefold(), 1)
        figures.append(
            _Figure(
                raw=match.group().strip(),
                value=format(amount.normalize(), "f"),
                start=match.start("number"),
                end=match.end(),
                plain=not any((match["currency"], scale, match["percent"], match["plus"])),
            )
        )
    return figures


def _quote(text: str, figure: _Figure) -> str:
    """Quote the figure with the word it qualifies, so the writer can find it in its own draft."""
    match = _TRAILING_WORD.match(text, figure.end)
    return figure.raw + (match.group() if match else "")


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


# --- exemptions -----------------------------------------------------------------------------------
def _dated_spans(line: Line) -> tuple[tuple[int, int], ...]:
    """Return the characters the date check already owns, so no figure is read from them twice."""
    if line.kind is not Kind.META or line.area not in _DATED_AREAS:
        return ()
    return tuple((span.start, span.end) for span in find_points(line.text))


def _explained(
    figure: _Figure, tokens: list[Token], dated: tuple[tuple[int, int], ...], lexicon: Lexicon
) -> bool:
    """Report whether this figure is something other than a claim about an outcome."""
    if any(start <= figure.start < end for start, end in dated):
        return True
    # Every digit lies inside a token: tokenise() keeps digits and only trims edge punctuation.
    index = max((i for i, token in enumerate(tokens) if token.start <= figure.start), default=0)
    if _letter_led(tokens[index].surface):
        return True
    return _version_position(figure, tokens, index, lexicon)


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

    A version never carries a currency symbol, a percent sign, a magnitude suffix, or a trailing
    "+", which is what keeps "$200k" and "40%" out of this exemption no matter what precedes them.
    """
    if not figure.plain or not index:
        return False
    previous = tokens[index - 1]
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
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    return following is not None and following.lower not in _FUNCTION_WORDS
