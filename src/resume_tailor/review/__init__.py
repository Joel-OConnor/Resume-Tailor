"""A second read of what was generated: fix the easy things, flag the rest, ask about the gaps."""

from __future__ import annotations

from resume_tailor.review.linkedin import check_linkedin
from resume_tailor.review.models import Finding, Level, Review
from resume_tailor.review.profile import review_profile
from resume_tailor.review.questions import (
    MAX_QUESTIONS,
    Answer,
    Question,
    from_findings,
    gather,
    said,
)
from resume_tailor.review.report import format_review
from resume_tailor.review.resume import apply_fixes, review_and_fix, review_resume

__all__ = [
    "MAX_QUESTIONS",
    "Answer",
    "Finding",
    "Level",
    "Question",
    "Review",
    "apply_fixes",
    "check_linkedin",
    "format_review",
    "from_findings",
    "gather",
    "review_and_fix",
    "review_profile",
    "review_resume",
    "said",
]
