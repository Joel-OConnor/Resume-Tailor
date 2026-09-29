"""Check that every skill printed is a technology the profile actually records.

The Skills block is what an automated screener reads most literally, and therefore the cheapest
place in the document to add a plausible lie. Matching is delegated whole to
:func:`resume_tailor.match.build_lexicon`, which already knows every spelling and alias the user
wrote down — there is no list of the world's technologies here either.

Only list-shaped claims are checked: every item in the Skills section, a ``**Skills:** a, b``
line under a role, which is how a LinkedIn position lists what it used, and the
``*Tech Stack – a, b*`` note the resume format closes each role with. Prose is full of ordinary
words that any technology matcher will happily mistake for products, and a false alarm on a true
bullet costs a retry.

A line under a role or project may also name what that role's or project's ``stack`` records,
since the profile states it was used there. The Skills section may not: it claims the technology
outright, so it answers to ``technologies`` alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import normalise, stem, tokenise
from resume_tailor.verify.models import Violation
from resume_tailor.verify.source import Area, Kind

if TYPE_CHECKING:
    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.profile.models import Profile
    from resume_tailor.verify.source import Line, Source

__all__ = ["check_skills", "is_known", "stack_note"]

_ITEM_LINES = frozenset({Kind.SKILL, Kind.BULLET})
# Read after normalise(), which folds every dash to "-". The note is italic in the format, but a
# writer that drops the emphasis, bolds the label, or closes the emphasis before the separator is
# making the same claim. The separator is a colon or a spaced dash, so "Stack-ranked" opening a
# bullet is a verb and not a list.
_STACK = re.compile(
    r"^[*_]*\s*(?:(?:tech(?:nology)?\s+)?stack|technologies)[*_]*"
    r"(?:\s*:|\s+-)[*_]*\s*(?P<items>.*?)[\s*_]*$",
    re.IGNORECASE,
)
# "PostgreSQL/MySQL" and "Python and Kafka" each claim two things; each half has to be real.
_BRANCHES = re.compile(r"/|\s+and\s+")
_VENDORS = ("amazon", "aws", "apache", "microsoft", "google", "azure", "oracle", "ibm")
"""Vendor words a product name drops in ordinary writing: "Kafka" for "Apache Kafka"."""
_TRIM = " .;:&/-"
# A leading dot is part of a name (".NET"); only a trailing one is the end of a sentence.
_LEADING_TRIM = _TRIM.replace(".", "")
_REASON = (
    "is not a technology the profile records under any name or alias; use the profile's own "
    "spelling, or add it to output/master-profile.yaml first if the user really has it"
)


def check_skills(source: Source, profile: Profile, lexicon: Lexicon) -> list[Violation]:
    """Check every technology the document lists against what the profile records."""
    stacks = _stack_forms(profile)
    found: list[Violation] = []
    for line in source.lines:
        items = _claimed(line)
        if items is None:
            continue
        used = frozenset() if line.area is Area.SKILLS else stacks
        found += [
            Violation("technology", term, line.number, _REASON)
            for term in _terms(items)
            if not is_known(term, lexicon, used)
        ]
    return found


def _claimed(line: Line) -> str | None:
    """Return the technologies a line lists as claims, or ``None`` when it lists none."""
    if line.area is Area.SKILLS and line.kind in _ITEM_LINES:
        return line.body
    if line.area is Area.EXPERIENCE and line.kind is Kind.SKILL:
        return line.body
    return stack_note(line)


def stack_note(line: Line) -> str | None:
    """Return the items of a ``*Tech Stack – a, b*`` note, or ``None`` when the line is not one."""
    for text in (line.text, line.body):
        if match := _STACK.match(normalise(text)):
            return match["items"].replace("*", " ")
    return None


def _stack_forms(profile: Profile) -> frozenset[tuple[str, ...]]:
    """Every technology a role's or project's stack records, keyed the way a claim is."""
    items = [item for tenure in profile.experience for role in tenure.roles for item in role.stack]
    items += [item for project in profile.projects for item in project.stack]
    return frozenset(key for item in items for term in _terms(item) if (key := _key(term)))


def _key(term: str) -> tuple[str, ...]:
    return tuple(stem(token.lower) for token in tokenise(term))


def _terms(text: str) -> list[str]:
    """Split a skills line into the individual technologies it claims.

    ``AWS (ECS, Lambda, RDS)`` claims four things, not one, so the parenthesis is opened and its
    contents checked as separate items — that is exactly where an unearned service name hides.
    """
    terms: list[str] = []
    for piece in _split(normalise(text)):
        head, _, inner = piece.partition("(")
        candidates = (head, *_split(inner.rstrip(")")))
        terms += [
            term
            for candidate in candidates
            if (term := candidate.lstrip(_LEADING_TRIM).rstrip(_TRIM).strip())
        ]
    return terms


def _split(text: str) -> list[str]:
    """Split on the separators a skills line uses, leaving anything inside parentheses alone.

    Commas and semicolons are the format's own; a middle dot, a bullet and a pipe are how a
    writer that ignores it lists the same items.
    """
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(depth - 1, 0)
        if character in ",;·•|" and not depth:
            items.append("".join(current))
            current = []
        else:
            current.append(character)
    items.append("".join(current))
    return items


def is_known(term: str, lexicon: Lexicon, stacks: frozenset[tuple[str, ...]] = frozenset()) -> bool:
    """Report whether the profile records this technology under any spelling.

    ``stacks`` adds what a role's or project's stack records, for a line that lists what one used.
    """
    if _recorded(term, lexicon, stacks):
        return True
    # "PostgreSQL/MySQL" claims both, so both have to be real; "CI/CD" and "Identity and Access
    # Management" are one name each and were already answered above, which is why the whole term
    # is tried before it is ever split.
    branches = [branch for branch in _BRANCHES.split(term) if branch.strip()]
    return len(branches) > 1 and all(_recorded(branch, lexicon, stacks) for branch in branches)


def _recorded(term: str, lexicon: Lexicon, stacks: frozenset[tuple[str, ...]]) -> bool:
    return _in_lexicon(term, lexicon) or _key(term) in stacks


def _in_lexicon(term: str, lexicon: Lexicon) -> bool:
    keys = tuple(token.lower for token in tokenise(term))
    if not keys:
        return True
    if keys in lexicon.by_tokens or tuple(stem(key) for key in keys) in lexicon.by_stems:
        return True
    # A product is routinely written without its vendor, above all inside a parenthesis:
    # "AWS (Lambda, Aurora Serverless)". It names the same recorded technology, so it is known.
    return any((vendor, *keys) in lexicon.by_tokens for vendor in _VENDORS)
