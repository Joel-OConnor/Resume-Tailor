"""Find what the posting wants that the profile does not support.

Gaps are mined by **shape**, not vocabulary: there is no list of the world's technologies here
either. A token that looks like a technology name — an acronym, an internal capital, technology
punctuation, or a capitalised word that is not merely starting a sentence — becomes a candidate,
and any candidate the profile did not cover is reported.

Over-generating here is safe by construction: this channel can only ever add a gap, never a
coverage claim. The worst case is an advisory line the user dismisses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import Token, stem

if TYPE_CHECKING:
    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.match.posting import Posting

__all__ = ["Gap", "find_gaps"]

_ACRONYM_MIN, _ACRONYM_MAX = 2, 6

# Words a posting bullet actually opens with. Everything else that is capitalised at the start of
# a line is far more likely to be a technology — "Kafka expertise is required" is how bullets read.
_SENTENCE_STARTERS = frozenset(
    {
        "architect",
        "build",
        "collaborate",
        "create",
        "define",
        "deliver",
        "deep",
        "design",
        "develop",
        "drive",
        "ensure",
        "establish",
        "experience",
        "familiarity",
        "help",
        "identify",
        "implement",
        "improve",
        "lead",
        "maintain",
        "manage",
        "mentor",
        "operate",
        "own",
        "partner",
        "proven",
        "provide",
        "scale",
        "ship",
        "solid",
        "strong",
        "support",
        "the",
        "this",
        "understand",
        "we",
        "work",
        "write",
        "you",
        "your",
        "our",
        "a",
        "an",
        "as",
        "at",
        "in",
        "it",
        "on",
        "to",
        "excellent",
        "extensive",
        "hands",
        "knowledge",
        "prior",
        "significant",
        "track",
        "demonstrated",
    }
)
_NEAR_MISS_PREFIX = 4

# Posting furniture, not skills. Not a taxonomy — just the words every job ad contains.
_NOISE = frozenset(
    {
        "a",
        "about",
        "additional",
        "an",
        "and",
        "architect",
        "backend",
        "basic",
        "benefits",
        "bonus",
        "candidate",
        "company",
        "day",
        "deep",
        "design",
        "desirable",
        "develop",
        "developer",
        "engineer",
        "engineering",
        "equal",
        "even",
        "experience",
        "expertise",
        "familiarity",
        "frontend",
        "full",
        "have",
        "impact",
        "join",
        "ju",
        "knowledge",
        "lead",
        "level",
        "life",
        "manager",
        "meaningful",
        "minimum",
        "mission",
        "must",
        "need",
        "nice",
        "opportunity",
        "own",
        "perks",
        "plus",
        "preferred",
        "principal",
        "proficiency",
        "qualification",
        "qualifications",
        "record",
        "requirement",
        "requirements",
        "responsibilities",
        "role",
        "salary",
        "senior",
        "skills",
        "stack",
        "staff",
        "strong",
        "team",
        "teams",
        "track",
        "we",
        "what",
        "who",
        "why",
        "will",
        "work",
        "working",
        "years",
        "you",
        "your",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "bs",
        "ms",
        "ba",
        "phd",
        "pto",
        "eeo",
        "us",
        "usa",
        "i",
        "ii",
        "iii",
        "iv",
        "the",
        "our",
        "their",
        "its",
        "this",
        "that",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "as",
        "is",
        "are",
        "be",
        "by",
        "from",
        "across",
    }
)

# All-lowercase infrastructure nouns no shape rule can reach. Gap channel only.
_ALWAYS_TERM = frozenset(
    {
        "kubectl",
        "etcd",
        "npm",
        "pnpm",
        "yarn",
        "nginx",
        "envoy",
        "redis",
        "kafka",
        "grafana",
        "prometheus",
        "airflow",
        "dbt",
        "spark",
        "hadoop",
        "elasticsearch",
        "rabbitmq",
        "celery",
        "postgres",
        "mysql",
        "mongodb",
        "graphql",
        "webpack",
        "vite",
        "eslint",
    }
)

# Requirements that are prose, never a proper noun — and therefore invisible to a shape test.
_PROSE_REQUIREMENTS: tuple[tuple[str, ...], ...] = (
    ("on", "call"),
    ("oncall",),
    ("incident", "response"),
    ("postmortem",),
    ("post", "mortem"),
    ("pager",),
    ("code", "review"),
    ("design", "review"),
    ("technical", "writing"),
    ("trunk", "based", "development"),
    ("feature", "flags"),
    ("progressive", "rollout"),
    ("a", "b", "testing"),
    ("pci", "dss"),
    ("soc", "2"),
    ("hipaa",),
    ("gdpr",),
    ("disaster", "recovery"),
    ("capacity", "planning"),
    ("chaos", "engineering"),
)


@dataclass(frozen=True, slots=True)
class Gap:
    """Something the posting asks for that the profile does not support."""

    term: str
    lines: tuple[int, ...]
    near_miss: str = ""
    """A profile technology this looks like — a prompt to add an alias rather than a real gap."""


def find_gaps(posting: Posting, lexicon: Lexicon, covered: frozenset[str]) -> tuple[Gap, ...]:
    """Return the posting's apparent requirements that ``covered`` does not account for."""
    known = _known_tokens(lexicon)
    seen: dict[str, set[int]] = {}

    for clause in posting.requirement_clauses:
        tokens = list(clause.tokens)
        for term in _candidates(tokens) + _prose(tokens):
            if not _is_gap(term, known, covered):
                continue
            seen.setdefault(term, set()).add(clause.line)

    gaps = [
        Gap(term=term, lines=tuple(sorted(lines)), near_miss=_near_miss(term, lexicon))
        for term, lines in seen.items()
    ]
    gaps.sort(key=lambda gap: (-len(gap.lines), gap.term.casefold()))
    return tuple(gaps)


def _is_gap(term: str, known: frozenset[str], covered: frozenset[str]) -> bool:
    """Report whether a term is a gap: neither it nor an alternation branch is accounted for."""
    key = term.casefold()
    if key in known or key in covered:
        return False
    # "PostgreSQL/MySQL" is not a gap when PostgreSQL is covered — the posting offered a choice.
    return not any(part in known or part in covered for part in key.split("/") if part)


def _known_tokens(lexicon: Lexicon) -> frozenset[str]:
    """Every single-token spelling the profile already knows, so it is never called a gap."""
    known = {form.surface.casefold() for form in lexicon.forms}
    known |= {token for form in lexicon.forms for token in form.tokens}
    return frozenset(known)


def _candidates(tokens: list[Token]) -> list[str]:
    """Merge runs of technology-shaped tokens into candidate terms."""
    terms: list[str] = []
    run: list[str] = []
    for token in tokens:
        if _is_term_shaped(token):
            run.append(token.surface)
        else:
            terms += _flush(run)
            run = []
    return terms + _flush(run)


def _flush(run: list[str]) -> list[str]:
    return [" ".join(run)] if run else []


def _is_term_shaped(token: Token) -> bool:
    surface = token.surface
    if token.lower in _NOISE:
        return False
    acronym = token.all_caps and _ACRONYM_MIN <= len(surface) <= _ACRONYM_MAX
    punctuated = any(c in surface for c in "+#./") and any(c.isalpha() for c in surface)
    if token.lower in _ALWAYS_TERM or acronym or token.has_inner_capital or punctuated:
        return True
    # A capitalised word proves less at the start of a sentence, but suppressing all of them
    # loses every bullet that opens with its keyword — which is how requirement bullets are
    # written. So suppress only the words postings actually open sentences with.
    if not surface[:1].isupper():
        return False
    return not (token.sentence_initial and surface.isalpha() and token.lower in _SENTENCE_STARTERS)


def _prose(tokens: list[Token]) -> list[str]:
    """Match the closed list of requirements that never appear as proper nouns."""
    lowered = [token.lower for token in tokens]
    found: list[str] = []
    for phrase in _PROSE_REQUIREMENTS:
        size = len(phrase)
        if any(tuple(lowered[i : i + size]) == phrase for i in range(len(lowered) - size + 1)):
            found.append(" ".join(phrase))
    return found


def _near_miss(term: str, lexicon: Lexicon) -> str:
    """Flag a gap that is probably a missing alias rather than missing experience.

    One must be a prefix of the other — "cache"/"caching", "Nest"/"NestJS". A shared opening
    four letters is not a resemblance: "postmortem" is not a kind of "PostgreSQL".
    """
    if len(term.split()) > 1:
        return ""
    root = stem(term.casefold())
    if len(root) < _NEAR_MISS_PREFIX:
        return ""
    for form in lexicon.forms:
        if form.length != 1:
            continue
        other = form.stems[0]
        if len(other) >= _NEAR_MISS_PREFIX and (root.startswith(other) or other.startswith(root)):
            return form.technology
    return ""
