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

_DECLINE = re.compile(
    r"^\s*(?:no|nope|not|never|none|nothing|n/a|i (?:have|had|did|do)(?:n'?t| not)|"
    r"(?:have|had|did|do)n'?t)\b",
    re.IGNORECASE,
)
"""The opening of an answer that turns its question down, however it goes on."""


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
        """True when the answer gives a fact, rather than declining."""
        folded = " ".join(self.text.casefold().split()).rstrip(".!")
        return bool(folded) and folded not in _NOTHING


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
    It never counts when the answer declines, so a "Not really" cannot license what it was asked.
    """
    return "\n".join(
        answer.text if _DECLINE.match(answer.text) else f"{answer.question.text}\n{answer.text}"
        for answer in answers
    )
