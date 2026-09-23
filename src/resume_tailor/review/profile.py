"""Review the master profile the way the resume review reads a resume.

The profile is the user's own record, so nothing here is applied automatically: an ADVISE
finding names a highlight that would print badly, and every open ``notes`` entry — the builder's
own unanswered questions — comes back as an ASK, which is what the prompt cycle walks through.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from resume_tailor.review.models import Finding, Level, Review

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

__all__ = ["review_profile"]

_LONG_HIGHLIGHT_WORDS = 45
_LONG_SUMMARY_WORDS = 90


def review_profile(profile: Profile) -> Review:
    """Review ``profile`` and return the findings, with every open note as a question."""
    findings = [
        *_summary(profile),
        *_highlights(profile),
        *_technologies(profile),
        *_notes(profile),
    ]
    return Review(tuple(findings))


def _summary(profile: Profile) -> list[Finding]:
    words = len(profile.summary.split())
    if words > _LONG_SUMMARY_WORDS:
        message = f"{words} words; tailoring rewrites it per job, so keep the generic one short"
        return [Finding("long-summary", Level.ADVISE, 0, "summary", message)]
    return []


def _highlights(profile: Profile) -> list[Finding]:
    found: list[Finding] = []
    for tenure_index, tenure in enumerate(profile.experience):
        for role_index, role in enumerate(tenure.roles):
            where = f"experience[{tenure_index}].roles[{role_index}]"
            if not role.highlights:
                message = (
                    f"What did you accomplish as {role.title} at {tenure.company}? No highlights "
                    "are recorded."
                )
                found.append(Finding("no-highlights", Level.ASK, 0, where, message))
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
    return found


def _technologies(profile: Profile) -> list[Finding]:
    found: list[Finding] = []
    names = Counter(item.name.casefold() for group in profile.technologies for item in group.items)
    for name, count in sorted(names.items()):
        if count > 1:
            message = f"'{name}' appears in {count} groups; keep it in one"
            found.append(Finding("duplicate-technology", Level.ADVISE, 0, "technologies", message))
    unrated = [
        item.name for group in profile.technologies for item in group.items if not item.level
    ]
    if unrated:
        shown = ", ".join(unrated[:5]) + (", …" if len(unrated) > 5 else "")  # noqa: PLR2004
        message = (
            f"{len(unrated)} technologies have no level ({shown}); tailoring leads only with "
            "proficient or expert"
        )
        found.append(Finding("no-level", Level.ADVISE, 0, "technologies", message))
    return found


def _notes(profile: Profile) -> list[Finding]:
    return [Finding("note", Level.ASK, 0, "notes", note) for note in profile.notes]
