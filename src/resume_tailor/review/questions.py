"""The questions a review ends with, and what the candidate answered.

A review finishes with the gaps only the candidate can fill: a must-have the posting asks for that
the profile never mentions, an accomplishment with no outcome, a role with no dates. They come from
several readers (the writer, the editor, the mechanical review, the profile's own notes), so they
are merged here in priority order with repeats dropped, and capped: a review is meant to be
answered in a couple of minutes, not to become a questionnaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.review.models import Level

if TYPE_CHECKING:
    from collections.abc import Iterable

    from resume_tailor.review.models import Finding

__all__ = ["MAX_QUESTIONS", "Answer", "Question", "from_findings", "gather", "said"]

MAX_QUESTIONS = 8
"""The most questions one review asks: enough to fill the real gaps, few enough to answer now."""

_WORDS = re.compile(r"[a-z0-9]+")
_NOTHING = frozenset(
    {"no", "n", "nope", "none", "never", "not really", "n/a", "na", "skip", "pass", "idk"}
    | {"don't know", "dont know", "no idea", "not sure", "nothing", "i haven't", "i have not"}
)
"""Answers that decline: kept in the record, but they give the profile nothing to add."""

_APOSTROPHES = str.maketrans("‘’ʼ`", "''''")
"""Typographic apostrophes, folded so "I’m not sure" reads like "I'm not sure"."""

_REFUSAL = (
    r"no|nope|nah|never|none|nothing|not|n/a|idk|dunno|unsure|skip|pass"
    r"|maybe|perhaps|possibly|probably"
    r"|i'?m not|i am not"
    r"|(?:i )?(?:have|had|did|do|does|was|were|is|are|could|would)(?:n'?t| not)"
    r"|(?:i )?(?:can'?t|cannot|can not|won'?t|will not)"
)
"""The ways an answer opens when it turns its question down, or is unsure of the answer."""

_DECLINE = re.compile(rf"^\s*(?:{_REFUSAL})\b")
"""The opening of an answer that turns its question down, however it goes on."""

_CLAUSES = re.compile(
    r"[,;:.!?()]+|\s[-\u2013\u2014]+\s|\s(?=(?:but|though|although|however|except|instead|only)\b)"
)
"""Where one clause of an answer ends: punctuation, a spaced dash, or a turn like "but"."""

_TURN = re.compile(r"^(?:but|though|although|however|except|instead|only)\s+")
_TOKENS = re.compile(r"[a-z0-9]+(?:['/][a-z0-9]+)*")
_REFUSING = frozenset(
    {"no", "nope", "nah", "never", "none", "nothing", "not", "n/a", "idk", "dunno", "unsure"}
    | {"maybe", "perhaps", "possibly", "probably", "cannot", "dont", "didnt", "havent", "cant"}
)
"""Words that decline or hedge wherever they stand, besides every word ending in "n't"."""

_FILLER = frozenset(
    {"i", "i'm", "im", "i've", "i'd", "me", "my", "myself", "we", "our", "you", "it", "it's"}
    | {"that", "this", "those", "them", "there", "one", "any", "anything", "something", "thing"}
    | {"a", "an", "the", "of", "in", "on", "at", "to", "for", "about", "with", "as", "so", "far"}
    | {"am", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did"}
    | {"done", "used", "use", "using", "worked", "work", "working", "can", "could", "would"}
    | {"say", "tell", "share", "recall", "remember", "know", "think", "idea", "clue", "mind"}
    | {"sure", "certain", "aware", "afraid", "sorry", "unfortunately", "sadly", "honestly"}
    | {"really", "all", "much", "yet", "ever", "before", "either", "personally", "comes", "come"}
    | {"exact", "exactly", "number", "numbers", "figure", "figures", "detail", "details"}
    | {"specifics", "offhand", "experience", "thanks", "thank", "well", "too", "very"}
)
"""Words that carry no fact of their own in an answer that declines: "I'm afraid not, sorry"."""


@dataclass(frozen=True, slots=True)
class Question:
    """One thing to ask the candidate."""

    text: str
    """The question, worded for the candidate."""

    about: str = ""
    """What it concerns, quoted: the bullet with no outcome, the note being confirmed."""


@dataclass(frozen=True, slots=True)
class Answer:
    """What the candidate said to one question."""

    question: Question
    text: str

    @property
    def substantive(self) -> bool:
        """True when the answer gives a fact, rather than declining or saying it is unsure.

        An answer declines when all of it does: "Nope, never done on-call." and "I'm not sure, I
        don't remember the numbers." give the profile nothing to record. One clause that says
        something more is enough to make it a fact: "No, but I led the migration in 2021".
        """
        folded = _fold(self.text).rstrip(".!")
        if not folded or folded in _NOTHING:
            return False
        return not _declines(folded, self.question.text)


def gather(*groups: Iterable[Question], limit: int = MAX_QUESTIONS) -> tuple[Question, ...]:
    """Merge question lists, most important first, dropping repeats, up to ``limit``."""
    seen: set[str] = set()
    merged: list[Question] = []
    for group in groups:
        for question in group:
            key = " ".join(_WORDS.findall(question.text.casefold()))
            if key and key not in seen:
                seen.add(key)
                merged.append(question)
    return tuple(merged[:limit])


def from_findings(findings: Iterable[Finding], *, skip: Iterable[str] = ()) -> tuple[Question, ...]:
    """Turn a review's ASK findings into questions, leaving out the rules named in ``skip``."""
    skipped = frozenset(skip)
    return tuple(
        Question(finding.message, finding.text)
        for finding in findings
        if finding.level is Level.ASK and finding.rule not in skipped
    )


def said(answers: Iterable[Answer]) -> str:
    """Return what ``answers`` establish: the text a profile update may draw new facts from.

    The candidate's own words always count. The question counts too when the answer accepts it,
    because "Yes, two years at Acme" to "Have you used Kafka?" establishes Kafka without naming it.
    It never counts when the answer declines or hedges, so neither a "Not really" nor an "I'm not
    sure" can license what it was asked.
    """
    return "\n".join(
        answer.text
        if _DECLINE.match(_fold(answer.text))
        else f"{answer.question.text}\n{answer.text}"
        for answer in answers
    )


def _fold(text: str) -> str:
    """Lowercase ``text``, straighten its apostrophes, and collapse its whitespace."""
    return " ".join(text.translate(_APOSTROPHES).casefold().split())


def _declines(folded: str, question: str) -> bool:
    """Report whether every clause of a folded answer declines or hedges, and one at least does.

    A clause that opens by turning the question down may go on to repeat the question's own words
    ("never done on-call"); any other word of substance, or any digit, is a fact.
    """
    asked = frozenset(_TOKENS.findall(_fold(question)))
    refused = False
    for part in _CLAUSES.split(folded):
        clause = _TURN.sub("", part.strip())
        words = _TOKENS.findall(clause)
        if not words:
            continue
        if any(char.isdigit() for char in clause):
            return False
        if opener := _DECLINE.match(clause):
            rest = _TOKENS.findall(clause[opener.end() :])
            if not all(_empty(word) or word in asked for word in rest):
                return False
            refused = True
        elif all(_empty(word) for word in words):
            refused = refused or any(_refusing(word) for word in words)
        else:
            return False
    return refused


def _empty(word: str) -> bool:
    """Report whether ``word`` carries no fact in a declining answer."""
    return word in _FILLER or _refusing(word)


def _refusing(word: str) -> bool:
    """Report whether ``word`` declines or hedges on its own: "never", "probably", "haven't"."""
    return word in _REFUSING or word.endswith("n't")
