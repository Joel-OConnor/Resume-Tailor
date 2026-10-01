"""Decide what the profile covers, and refuse to overstate it.

Every rule here exists to stop one thing: reporting coverage the person cannot defend in an
interview. A false negative costs a keyword. A false positive puts a claim on a resume that
collapses in the first five minutes of a screen, which is the failure this project was built to
avoid. Precision wins every tie.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.match.lexicon import Form, Provenance, admits, alternatives
from resume_tailor.match.posting import Section
from resume_tailor.match.tokens import Token, stem

if TYPE_CHECKING:
    from resume_tailor.match.lexicon import Lexicon
    from resume_tailor.match.posting import Clause, Posting

__all__ = ["Confidence", "Coverage", "Match", "find_coverage"]

_SHALLOW_LEVELS = frozenset({"exposure", "working"})


class Confidence(StrEnum):
    """How strongly a match may be stated."""

    COVERED = "covered"
    """Named directly, with narrative evidence behind it."""

    PARTIAL = "partial"
    """Real but qualified — a category alias, a stem match, or no evidence beyond a stack list."""


@dataclass(frozen=True, slots=True)
class Match:
    """One technology the posting asks for and the profile supports."""

    technology: str
    group: str
    matched_text: str
    confidence: Confidence
    provenance: Provenance
    sections: tuple[Section, ...]
    lines: tuple[int, ...]
    employers: tuple[str, ...]
    evidence: tuple[str, ...]
    level: str = ""
    unconfirmed: str = ""
    caveat: str = ""

    @property
    def is_shallow(self) -> bool:
        """True when the posting wants this but the profile records it as thin."""
        return self.level in _SHALLOW_LEVELS

    @property
    def satisfies_must_have(self) -> bool:
        """Only a confirmed, evidenced, directly-named match can answer a must-have."""
        return (
            self.confidence is Confidence.COVERED and not self.unconfirmed and not self.is_shallow
        )


@dataclass(frozen=True, slots=True)
class Coverage:
    """The full result of matching a posting against a profile."""

    matches: tuple[Match, ...] = ()
    ignored: tuple[tuple[int, str, str], ...] = ()
    """``(line, reason, text)`` per excluded clause, printed so suppression is auditable."""


def find_coverage(posting: Posting, lexicon: Lexicon) -> Coverage:
    """Match ``posting`` against ``lexicon``, applying every precision gate."""
    hits: dict[str, list[_Hit]] = {}
    ignored: list[tuple[int, str, str]] = []

    for clause in posting.clauses:
        if (reason := _excluded(clause)) is not None:
            if _scan(clause, lexicon):
                ignored.append((clause.line, reason, clause.text))
            continue
        for hit in _scan(clause, lexicon):
            hits.setdefault(hit.form.technology, []).append(hit)

    matches = [_match(technology, found, lexicon) for technology, found in hits.items()]
    matches.sort(
        key=lambda m: (m.confidence is not Confidence.COVERED, -len(m.lines), m.technology)
    )
    return Coverage(tuple(matches), tuple(ignored))


def _excluded(clause: Clause) -> str | None:
    if clause.section is Section.CONTEXT:
        return "company/benefits section"
    if clause.negated:
        return "stated as not required"
    if clause.future:
        return "offered as something to learn"
    if clause.third_party:
        return "attributed to another team"
    if clause.deprecated:
        return "described as being retired"
    return None


@dataclass(frozen=True, slots=True)
class _Hit:
    form: Form
    clause: Clause
    exact: bool
    sub_span: bool


def _scan(clause: Clause, lexicon: Lexicon) -> list[_Hit]:
    """Longest-match n-gram scan. Substring matching is never used."""
    tokens: list[Token] = list(clause.tokens)
    hits: list[_Hit] = []
    index = 0
    while index < len(tokens):
        for size in range(min(lexicon.max_length, len(tokens) - index), 0, -1):
            window = tokens[index : index + size]
            keys = tuple(token.lower for token in window)
            form = lexicon.by_tokens.get(keys)
            exact = form is not None
            if form is None:
                form = lexicon.by_stems.get(tuple(stem(key) for key in keys))
            if form is None and size == 1:
                # "AWS/GCP" and "Node.js/Express" are alternations, but "CI/CD" and "PL/pgSQL"
                # are single names — so only split when the whole token is not itself a form.
                form = _split_alternate(keys[0], lexicon)
                exact = form is not None
            if form is not None and admits(form, tokens, index):
                # A hit whose neighbour extends it (AWS inside "AWS Lambda") is only partial.
                following = index + size
                sub_span = following < len(tokens) and _extends(tokens[following])
                hits.append(_Hit(form, clause, exact=exact, sub_span=sub_span))
                index += size
                break
        else:
            index += 1
            continue
    return hits


def _extends(token: Token) -> bool:
    """Report whether the next token makes this a prefix of a more specific product.

    Only a space joins a name to the word after it, as in "AWS Lambda" or "Docker Swarm". A
    comma, a bracket or any other punctuation ends the name, so the next item of a list ("AWS,
    Kubernetes, and Terraform") never makes the one before it read as half of a longer product.
    """
    if token.break_before:
        return False
    return token.has_inner_capital or (token.surface[:1].isupper() and not token.sentence_initial)


def _split_alternate(key: str, lexicon: Lexicon) -> Form | None:
    """Find a lexicon form inside a slash-joined alternation."""
    return next(iter(alternatives(key, lexicon.by_tokens)), None)


def _match(technology: str, hits: list[_Hit], lexicon: Lexicon) -> Match:
    best = min(
        hits,
        key=lambda h: (
            not h.exact,
            h.form.provenance is not Provenance.NAME,
            h.form.provenance is Provenance.CATEGORY,
            -h.form.length,
        ),
    )
    caveats: list[str] = []
    confidence = Confidence.COVERED

    if best.form.provenance is Provenance.CATEGORY:
        confidence = Confidence.PARTIAL
        if any(c.isupper() for c in best.form.surface):
            caveats.append(
                f"the posting says {best.form.surface!r} — a product category, so it may mean a "
                f"different vendor than {technology}"
            )
        else:
            caveats.append(
                f"the posting says {best.form.surface!r}, which is broader than {technology!r}"
            )
    if not best.exact:
        confidence = Confidence.PARTIAL
        caveats.append(f"matched by word stem, not exactly ({best.form.surface!r})")
    if best.sub_span:
        confidence = Confidence.PARTIAL
        caveats.append("the posting names a more specific product than the profile records")
    if not lexicon.has_evidence(technology):
        confidence = Confidence.PARTIAL
        caveats.append("no accomplishment in the profile describes this — only a stack listing")

    return Match(
        technology=technology,
        group=best.form.group,
        matched_text=best.form.surface,
        confidence=confidence,
        provenance=best.form.provenance,
        sections=tuple(sorted({h.clause.section for h in hits})),
        lines=tuple(sorted({h.clause.line for h in hits})),
        employers=lexicon.employers.get(technology, ()),
        evidence=lexicon.evidence.get(technology, ()),
        level=lexicon.levels.get(technology, ""),
        unconfirmed=lexicon.unconfirmed.get(technology, ""),
        caveat="; ".join(caveats),
    )
