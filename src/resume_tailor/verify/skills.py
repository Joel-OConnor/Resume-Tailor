"""Check that every skill printed is a technology the profile actually records.

The Skills block is what an automated screener reads most literally, and therefore the cheapest
place in the document to add a plausible lie. Matching is delegated whole to
:func:`resume_tailor.match.build_lexicon`, which already knows every spelling and alias the user
wrote down — there is no list of the world's technologies here either.

Only list-shaped claims are checked: every item in the Skills section, and a ``**Skills:** a, b``
line under a role, which is how a LinkedIn position lists what it used. Prose is full of ordinary
words that any technology matcher will happily mistake for products, and a false alarm on a true
bullet costs a retry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resume_tailor.match.tokens import normalise, stem, tokenise
from resume_tailor.verify.models import Violation
from resume_tailor.verify.source import Area, Kind

if TYPE_CHECKING:
    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.verify.source import Line, Source

__all__ = ["check_skills", "is_known"]

_ITEM_LINES = frozenset({Kind.SKILL, Kind.BULLET})
_VENDORS = ("amazon", "aws", "apache", "microsoft", "google", "azure", "oracle", "ibm")
"""Vendor words a product name drops in ordinary writing: "Kafka" for "Apache Kafka"."""
_TRIM = " .;:&/-"
_REASON = (
    "is not a technology the profile records under any name or alias; use the profile's own "
    "spelling, or add it to profile/master-profile.yaml first if the user really has it"
)


def check_skills(source: Source, lexicon: Lexicon) -> list[Violation]:
    """Check every item in the Skills section against the profile's lexicon."""
    found: list[Violation] = []
    for line in source.lines:
        if not _claims_skills(line):
            continue
        found += [
            Violation("technology", term, line.number, _REASON)
            for term in _terms(line.body)
            if not is_known(term, lexicon)
        ]
    return found


def _claims_skills(line: Line) -> bool:
    """Report whether a line is a list of technologies the candidate claims."""
    if line.area is Area.SKILLS:
        return line.kind in _ITEM_LINES
    return line.area is Area.EXPERIENCE and line.kind is Kind.SKILL


def _terms(text: str) -> list[str]:
    """Split a skills line into the individual technologies it claims.

    ``AWS (ECS, Lambda, RDS)`` claims four things, not one, so the parenthesis is opened and its
    contents checked as separate items — that is exactly where an unearned service name hides.
    """
    terms: list[str] = []
    for piece in _split(normalise(text)):
        head, _, inner = piece.partition("(")
        candidates = (head, *_split(inner.rstrip(")")))
        terms += [term for candidate in candidates if (term := candidate.strip(_TRIM).strip())]
    return terms


def _split(text: str) -> list[str]:
    """Split on the separators a skills line uses, leaving anything inside parentheses alone."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(depth - 1, 0)
        if character in ",;" and not depth:
            items.append("".join(current))
            current = []
        else:
            current.append(character)
    items.append("".join(current))
    return items


def is_known(term: str, lexicon: Lexicon) -> bool:
    """Report whether the profile records this technology under any spelling."""
    if _in_lexicon(term, lexicon):
        return True
    # "PostgreSQL/MySQL" claims both, so both have to be real; "CI/CD" is one name and was already
    # answered above, which is why the whole term is tried before it is ever split.
    branches = [branch for branch in term.split("/") if branch.strip()]
    return len(branches) > 1 and all(_in_lexicon(branch, lexicon) for branch in branches)


def _in_lexicon(term: str, lexicon: Lexicon) -> bool:
    keys = tuple(token.lower for token in tokenise(term))
    if not keys:
        return True
    if keys in lexicon.by_tokens or tuple(stem(key) for key in keys) in lexicon.by_stems:
        return True
    # A product is routinely written without its vendor, above all inside a parenthesis:
    # "AWS (Lambda, Aurora Serverless)". It names the same recorded technology, so it is known.
    return any((vendor, *keys) in lexicon.by_tokens for vendor in _VENDORS)
