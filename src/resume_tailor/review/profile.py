"""Audit the master profile: what is recorded twice, what does not add up, what would print badly.

The profile is the user's own record, so nothing here is applied. The refine pass reads these
findings alongside the draft it is cleaning up, and whatever survives refinement is shown to the
user afterwards:

* ADVISE is something to fix: one employer split across two entries, a highlight recorded twice,
  roles out of order or overlapping, a highlight that mentions a year after its role ended, a
  technology claiming more years than the career has, a role's stack naming a technology the
  profile never records, a highlight with no label or one that runs to a paragraph.
* ASK is a fact only the candidate has: every open ``notes`` entry, and a role with nothing
  recorded under it.

Every rule is deliberately narrow. The refine pass brings judgement to the whole file; this list
is only what can be checked mechanically, so a finding here is worth reading rather than noise.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, date, datetime
from itertools import combinations
from typing import TYPE_CHECKING

from resume_tailor.match import build_lexicon
from resume_tailor.match.tokens import normalise, stem
from resume_tailor.profile import format_date
from resume_tailor.review.models import Finding, Level, Review
from resume_tailor.verify.dates import PRESENT, Point, earlier, parse_point
from resume_tailor.verify.skills import is_known

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resume_tailor.profile.models import Highlight, Profile, Role

__all__ = ["review_profile"]

_LONG_HIGHLIGHT_WORDS = 45
_LONG_SUMMARY_WORDS = 90
_SHOWN = 5
_MONTHS_IN_YEAR = 12
_SAME_WORDS = 0.75
"""Share of the shorter highlight's words the longer one repeats before the two read as one."""

_MIN_WORDS = 4
_SHORTEST_STEM = 3
_PRESENT = "present"
_YEAR = re.compile(r"(?<![0-9])(?:19[5-9][0-9]|20[0-9]{2})(?![0-9])")
_WORD = re.compile(r"[a-z0-9$%]+")
_LEGAL = frozenset({"co", "company", "corp", "corporation", "inc", "llc", "ltd", "plc"})
_STOPWORDS = frozenset(
    {"a", "an", "and", "across", "as", "at", "by", "for", "from", "in", "into", "its", "of"}
    | {"on", "or", "that", "the", "their", "this", "to", "with", "while", "was", "were"}
)


def review_profile(profile: Profile, *, today: date | None = None) -> Review:
    """Audit ``profile`` and return every finding, with each open note as a question."""
    today = today or datetime.now(tz=UTC).date()
    findings = [
        *_summary(profile),
        *_employers(profile),
        *_roles(profile),
        *_highlights(profile),
        *_duplicates(profile),
        *_technologies(profile),
        *_technology_years(profile, today),
        *_stacks(profile),
        *_notes(profile),
    ]
    return Review(tuple(findings))


# --- the career's shape ---------------------------------------------------------------------------
def _summary(profile: Profile) -> list[Finding]:
    words = len(profile.summary.split())
    if words > _LONG_SUMMARY_WORDS:
        message = f"{words} words; every resume writes its own summary, so keep this one short"
        return [Finding("long-summary", Level.ADVISE, 0, "summary", message)]
    return []


def _employers(profile: Profile) -> list[Finding]:
    """One entry per employer, most recent first."""
    found: list[Finding] = []
    first: dict[str, int] = {}
    for index, tenure in enumerate(profile.experience):
        key = _company(tenure.company)
        if key in first:
            message = (
                f"{tenure.company} is recorded twice (experience[{first[key]}] and "
                f"experience[{index}]); merge them into one employer, each title a role"
            )
            found.append(
                Finding("duplicate-employer", Level.ADVISE, 0, f"experience[{index}]", message)
            )
        first.setdefault(key, index)
    for index in range(len(profile.experience) - 1):
        current, following = profile.experience[index], profile.experience[index + 1]
        if earlier(_latest(current.roles), _latest(following.roles)):
            message = (
                f"{following.company} ran later than {current.company} but is listed after it; "
                "list employers most recent first"
            )
            found.append(
                Finding("employer-order", Level.ADVISE, 0, f"experience[{index + 1}]", message)
            )
    return found


def _roles(profile: Profile) -> list[Finding]:
    """Titles at one employer: most recent first, and not two at once."""
    found: list[Finding] = []
    for tenure_index, tenure in enumerate(profile.experience):
        roles = tenure.roles
        for index in range(len(roles) - 1):
            if earlier(parse_point(roles[index].start), parse_point(roles[index + 1].start)):
                where = f"experience[{tenure_index}].roles[{index + 1}]"
                message = (
                    f"{roles[index + 1].title} started after {roles[index].title} but is listed "
                    "below it; list roles most recent first"
                )
                found.append(Finding("role-order", Level.ADVISE, 0, where, message))
        for (first, one), (second, other) in combinations(enumerate(roles), 2):
            if _overlap(one, other):
                where = f"experience[{tenure_index}].roles[{second}]"
                message = (
                    f"{other.title} overlaps {one.title} (roles[{first}]) at {tenure.company}; "
                    "if one job was recorded twice, merge them, otherwise confirm the dates"
                )
                found.append(Finding("overlapping-roles", Level.ADVISE, 0, where, message))
    return found


def _latest(roles: tuple[Role, ...]) -> Point:
    """Return the last point an employer's roles reach; a current role beats every date."""
    ends = [parse_point(role.end) for role in roles]
    return PRESENT if PRESENT in ends else max(ends, key=lambda point: (point.year, point.month))


def _overlap(one: Role, other: Role) -> bool:
    """Report whether two roles were held at the same time, beyond a shared boundary month."""
    return _before(parse_point(one.start), parse_point(other.end)) and _before(
        parse_point(other.start), parse_point(one.end)
    )


def _before(start: Point, end: Point) -> bool:
    """Report whether a period starting at ``start`` began clearly before another ended at ``end``.

    A promotion is usually recorded as one role ending the month the next begins, and dates copied
    from two documents drift by a month, so a single shared month is not an overlap.
    """
    if start.month and end.month and end != PRESENT:
        gap = (end.year - start.year) * _MONTHS_IN_YEAR + end.month - start.month
        return gap > 1
    return earlier(start, end)


# --- accomplishments ------------------------------------------------------------------------------
def _highlights(profile: Profile) -> list[Finding]:
    found: list[Finding] = []
    for where, role, tenure_company in _role_paths(profile):
        if not role.highlights:
            message = (
                f"What did you accomplish as {role.title} at {tenure_company}? No highlights "
                "are recorded."
            )
            found.append(Finding("no-highlights", Level.ASK, 0, "", message))
        for index, highlight in enumerate(role.highlights):
            path = f"{where}.highlights[{index}]"
            if not highlight.label:
                message = "no label; the label becomes the bold lead-in a skim reads"
                found.append(Finding("no-label", Level.ADVISE, 0, path, message))
            words = len(highlight.text.split())
            if words > _LONG_HIGHLIGHT_WORDS:
                message = (
                    f"{words} words; a highlight prints as one bullet, so split it or cut to "
                    "the outcome"
                )
                found.append(Finding("long-highlight", Level.ADVISE, 0, path, message))
            found += _after_role(highlight, role, path)
    return found


def _after_role(highlight: Highlight, role: Role, path: str) -> list[Finding]:
    """Flag a highlight that mentions a year after its role ended: it belongs to a later one."""
    if role.end == _PRESENT:
        return []
    ended = parse_point(role.end).year
    later = sorted({int(year) for year in _YEAR.findall(highlight.text) if int(year) > ended})
    if not later:
        return []
    message = (
        f"mentions {later[0]}, after this role ended ({format_date(role.end)}); it probably "
        "belongs under a later role"
    )
    return [Finding("highlight-after-role", Level.ADVISE, 0, path, message)]


def _duplicates(profile: Profile) -> list[Finding]:
    """Flag a highlight that says what an earlier one already says."""
    recorded = [
        (path, _content(highlight.text))
        for path, highlight in _highlight_paths(profile)
        if highlight.text
    ]
    found: list[Finding] = []
    for (first, words), (second, other) in combinations(recorded, 2):
        if _same(words, other):
            message = f"says what {first} already says; keep one, with every figure from both"
            found.append(Finding("duplicate-highlight", Level.ADVISE, 0, second, message))
    return found


def _content(text: str) -> frozenset[str]:
    """Return a highlight's distinctive words, stemmed, without the glue every one shares."""
    words = _WORD.findall(normalise(text).casefold())
    return frozenset(_undouble(stem(word)) for word in words if word not in _STOPWORDS)


def _undouble(word: str) -> str:
    """Finish a stem the suffix-stripper leaves doubled: "cutting" gives "cutt", meaning "cut"."""
    if len(word) > _SHORTEST_STEM and word[-1] == word[-2] and word[-1] not in "aeiousl":
        return word[:-1]
    return word


def _same(words: frozenset[str], other: frozenset[str]) -> bool:
    """Report whether two highlights say one thing: most words shared, or one inside the other."""
    shorter = min(len(words), len(other))
    if shorter < _MIN_WORDS:
        return shorter > 1 and (words <= other or other <= words)
    return len(words & other) / shorter >= _SAME_WORDS


# --- technologies ---------------------------------------------------------------------------------
def _technologies(profile: Profile) -> list[Finding]:
    found: list[Finding] = []
    names = Counter(_fold(item.name) for group in profile.technologies for item in group.items)
    for name, count in sorted(names.items()):
        if count > 1:
            message = f"'{name}' appears {count} times; keep it in one group"
            found.append(Finding("duplicate-technology", Level.ADVISE, 0, "technologies", message))
    owners: dict[str, set[str]] = {}
    for group in profile.technologies:
        for item in group.items:
            for form in (item.name, *item.aliases):
                owners.setdefault(_fold(form), set()).add(_fold(item.name))
    for form, items in sorted(owners.items()):
        if len(items) > 1:
            listed = " and ".join(sorted(items))
            message = f"'{form}' names both {listed}; record it once, other spellings as aliases"
            found.append(Finding("duplicate-technology", Level.ADVISE, 0, "technologies", message))
    unrated = [
        item.name for group in profile.technologies for item in group.items if not item.level
    ]
    if unrated:
        shown = ", ".join(unrated[:_SHOWN]) + (", …" if len(unrated) > _SHOWN else "")
        message = (
            f"{len(unrated)} technologies have no level ({shown}); tailoring leads only with "
            "proficient or expert"
        )
        found.append(Finding("no-level", Level.ADVISE, 0, "technologies", message))
    return found


def _technology_years(profile: Profile, today: date) -> list[Finding]:
    """Flag a technology used for longer than the recorded career has lasted."""
    first = min(
        parse_point(role.start).year for tenure in profile.experience for role in tenure.roles
    )
    span = today.year - first + 1
    return [
        Finding(
            "technology-years",
            Level.ADVISE,
            0,
            "technologies",
            f"{item.name}: {item.years:g} years, but the earliest role recorded starts in {first}",
        )
        for group in profile.technologies
        for item in group.items
        if item.years > span
    ]


def _stacks(profile: Profile) -> list[Finding]:
    """Flag a role's stack naming a technology the Skills section could never print."""
    lexicon = build_lexicon(profile)
    found: list[Finding] = []
    for where, role, _ in _role_paths(profile):
        missing = [item for item in role.stack if not is_known(item, lexicon)]
        if missing:
            message = (
                f"stack names {', '.join(missing)}, which technologies does not record; add "
                "them there or drop them from the stack"
            )
            found.append(Finding("stack-unrecorded", Level.ADVISE, 0, where, message))
    return found


def _notes(profile: Profile) -> list[Finding]:
    return [Finding("note", Level.ASK, 0, "", note) for note in profile.notes]


# --- walking the profile --------------------------------------------------------------------------
def _role_paths(profile: Profile) -> Iterator[tuple[str, Role, str]]:
    for tenure_index, tenure in enumerate(profile.experience):
        for index, role in enumerate(tenure.roles):
            yield f"experience[{tenure_index}].roles[{index}]", role, tenure.company


def _highlight_paths(profile: Profile) -> Iterator[tuple[str, Highlight]]:
    for where, role, _ in _role_paths(profile):
        for index, highlight in enumerate(role.highlights):
            yield f"{where}.highlights[{index}]", highlight


def _company(text: str) -> str:
    words = _WORD.findall(normalise(text).casefold())
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    return " ".join(words)


def _fold(text: str) -> str:
    return " ".join(normalise(text).casefold().split())
