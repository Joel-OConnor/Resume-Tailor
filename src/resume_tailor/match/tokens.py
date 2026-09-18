"""Resume-aware tokenisation.

Ordinary word splitting destroys the vocabulary this tool exists to match: ``C++``, ``C#``,
``Node.js``, ``CI/CD``, ``PL/pgSQL`` and ``.NET`` all carry punctuation *inside* the token. So the
scanner keeps ``+ # . / - _ &`` glued and trims only at the edges.

Everything downstream matches whole token n-grams. Substring matching is never used anywhere,
which is what stops ``SQL`` firing inside ``PostgreSQL`` and ``Go`` inside ``going``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Token", "normalise", "stem", "tokenise"]

_WORD = re.compile(r"[0-9A-Za-z+#./\-_&]+")
_SENTENCE_END = re.compile(r"[.!?:;]\s*$")
_TYPOGRAPHIC = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})

# Longest first: the set is not prefix-free, and single-pass stripping is not idempotent —
# "environments" and "environment" have to reduce to the same stem or a real match is lost.
_SUFFIXES = ("ings", "ings", "ment", "ship", "ies", "ing", "ity", "es", "ed", "s")
_MIN_STEM = 4
_MIN_STEMMABLE = 5
_STEM_PASSES = 2


@dataclass(frozen=True, slots=True)
class Token:
    """One token of source text, with the position and casing signals matching depends on."""

    surface: str
    start: int
    end: int
    sentence_initial: bool
    break_before: bool = False
    """True when punctuation, not just space, separates this token from the one before it.

    Phrase building reads this. Without it a comma, a semicolon or a parenthesis is invisible,
    and "Strong Go (Python a plus)" reads as one requirement named "Go Python" — a phantom the
    profile can never match, reported next to the real Python it contradicts.
    """

    @property
    def lower(self) -> str:
        """Casefolded surface, used for every lexicon lookup."""
        return self.surface.casefold()

    @property
    def all_caps(self) -> bool:
        """True for an acronym-shaped token like ``AWS`` or ``SQS``."""
        return self.surface.isupper() and any(c.isalpha() for c in self.surface)

    @property
    def has_inner_capital(self) -> bool:
        """True for ``PostgreSQL``, ``NestJS``, ``gRPC`` — a strong technology-name signal."""
        return any(c.isupper() for c in self.surface[1:])


def normalise(text: str) -> str:
    """Fold Unicode and typographic punctuation to ASCII, preserving length-independent content.

    Case is deliberately preserved: the ambiguity tiers and the gap miner both read capitalisation.
    """
    return unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHIC)


def tokenise(text: str) -> list[Token]:
    """Split ``text`` into tokens, keeping technology punctuation inside them."""
    tokens: list[Token] = []
    previous_end = 0
    for match in _WORD.finditer(text):
        raw = match.group()
        lead = len(raw) - len(_strip_leading(raw))
        surface = _strip_trailing(_strip_leading(raw))
        if not surface or not any(c.isalnum() for c in surface):
            continue
        start = match.start() + lead
        before = text[: match.start()]
        tokens.append(
            Token(
                surface=surface,
                start=start,
                end=start + len(surface),
                sentence_initial=not before.strip() or bool(_SENTENCE_END.search(before)),
                # Whitespace joins; anything else separates. Punctuation trimmed off the end of
                # the previous token lands in this span too, so "Node.js, React" breaks here.
                break_before=bool(tokens) and bool(text[previous_end:start].strip()),
            )
        )
        previous_end = start + len(surface)
    return tokens


def _strip_leading(raw: str) -> str:
    # A leading dot survives only when a letter follows it, which is what preserves ".NET".
    index = 0
    while index < len(raw) and raw[index] in "-/_&+#.":
        if raw[index] == "." and index + 1 < len(raw) and raw[index + 1].isalpha():
            break
        index += 1
    return raw[index:]


def _strip_trailing(raw: str) -> str:
    return raw.rstrip(".-/_&")


def stem(word: str) -> str:
    """Reduce an alphabetic word to a comparison stem.

    Applied identically to both sides of a comparison, so ``mentoring`` meets ``Mentorship`` and
    ``environments`` meets ``environment``. Never applied to tokens carrying punctuation, which
    protects ``.NET``, ``C++``, ``K8s`` and ``CI/CD``.
    """
    if not word.isalpha() or len(word) < _MIN_STEMMABLE:
        return word.casefold()
    current = word.casefold()
    for _ in range(_STEM_PASSES):
        for suffix in _SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= _MIN_STEM:
                current = current[: -len(suffix)]
                break
        else:
            break
    return current
