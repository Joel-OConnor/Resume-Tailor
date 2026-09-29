"""Check the factual spine of the resume: who, what title, when, and what was studied.

These are the claims a reference check verifies word for word, so they get the strictest rule in
the package: a resume may *shorten* a name the profile carries — "Charter" for "Charter
Communications", "Backend Engineer" for "Senior Backend Engineer" — but it may never introduce a
word the profile does not have. Shortening is how people write; adding words is how a title gets
inflated and an employer gets invented.

Dates are checked the same way round. Narrowing a tenure is the candidate's business; widening one
is a claim a former employer's HR system will contradict.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import normalise
from resume_tailor.profile import format_period
from resume_tailor.verify.dates import earlier, find_points, parse_point, read_range
from resume_tailor.verify.models import Violation
from resume_tailor.verify.source import Area

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile, Role, Tenure
    from resume_tailor.verify.source import Entry, Source

__all__ = ["check_history"]

# " — Title" and " | Location" are the separators templates/resume.md prescribes; normalise() has
# already folded every dash variant to "-". Spaces are required around "-" so that a hyphenated
# name ("Full-Stack Engineer", "Hewlett-Packard") is never torn in half.
_SPLIT = re.compile(r"\s*\|\s*|\s+-\s+")
_SEGMENT = re.compile(r"\s*[,;·|]\s*|\s+-\s+")
_EMPHASIS = re.compile(r"[*`]+")

_EDUCATION_REASON = (
    "is not in the profile's record of any degree, certification or award; print only what the "
    "profile records for this entry (its credential, institution, location and year) and remove "
    "the rest, such as a city or state the profile does not give"
)


def check_history(source: Source, profile: Profile) -> list[Violation]:
    """Check every experience and education entry in ``source`` against ``profile``."""
    found: list[Violation] = []
    for entry in source.entries:
        if entry.area is Area.EXPERIENCE:
            found += _check_role(entry, profile)
        elif entry.area is Area.EDUCATION:
            found += _check_education(entry, profile)
    return found


# --- experience -----------------------------------------------------------------------------------
def _check_role(entry: Entry, profile: Profile) -> list[Violation]:
    """Check one ``### `` entry's employer, title, and dates.

    The employer may be written on either side of the separator — "Acme — Engineer" and
    "Engineer — Acme" are both common — so every part is tried as the company before anything is
    reported.
    """
    parts = _parts(entry.title)
    for index, part in enumerate(parts):
        tenure = _tenure_named(part, profile)
        if tenure is None:
            continue
        role, unknown = _role_named(parts[:index] + parts[index + 1 :], tenure, entry)
        titles = [_title_violation(entry, text, tenure) for text in unknown]
        return titles + _check_period(entry, tenure, role)
    return [_employer_violation(entry, parts, profile)]


def _tenure_named(part: str, profile: Profile) -> Tenure | None:
    claim = _words(part)
    return next((t for t in profile.experience if _within(claim, _words(t.company))), None)


def _role_named(parts: list[str], tenure: Tenure, entry: Entry) -> tuple[Role | None, list[str]]:
    """Return the role the entry names, plus the parts no role at this employer accounts for."""
    matched: Role | None = None
    unknown: list[str] = []
    for part in parts:
        claim = _words(part)
        role = _best_role(claim, tenure, entry)
        if role is None:
            unknown.append(part)
        elif matched is None:
            matched = role
    return matched, unknown


def _best_role(claim: tuple[str, ...], tenure: Tenure, entry: Entry) -> Role | None:
    """Find the role a title claim names.

    Progressive titles at one employer overlap: "Software Engineer" is a word run inside both
    "Senior Software Engineer" and "Lead Software Engineer", so several roles can match the same
    claim. The entry's own dates are the tie-breaker — they say which of the overlapping roles is
    actually being described. Without that, a promotion gets pinned to the wrong role and a
    correct resume is reported as claiming a period it never claimed.
    """
    candidates = [role for role in tenure.roles if _within(claim, _words(role.title))]
    if not candidates:
        return None
    printed = read_range(entry.meta)
    if printed is not None:
        consistent = [role for role in candidates if not _check_period(entry, tenure, role)]
        if consistent:
            candidates = consistent
    return next((role for role in candidates if _words(role.title) == claim), candidates[0])


def _check_period(entry: Entry, tenure: Tenure, role: Role | None) -> list[Violation]:
    printed = read_range(entry.meta)
    if printed is None:
        return []
    start, end, label = _recorded(tenure, role)
    began_earlier = earlier(printed.start, parse_point(start))
    ran_later = earlier(parse_point(end), printed.end)
    if not began_earlier and not ran_later:
        return []
    reason = (
        f"claims a period the profile does not record: it has {label} as "
        f"{format_period(start, end)}. Print dates inside that range"
    )
    return [Violation("date", printed.text, entry.meta_line, reason)]


def _recorded(tenure: Tenure, role: Role | None) -> tuple[str, str, str]:
    """Return the profile's own start, end, and a label for whatever the entry named.

    ``YYYY``, ``YYYY-MM`` and ``present`` sort correctly as plain strings: a bare year precedes
    its own months, and ``present`` follows every digit.
    """
    if role is not None:
        return role.start, role.end, f"{role.title} at {tenure.company}"
    return (
        min(held.start for held in tenure.roles),
        max(held.end for held in tenure.roles),
        tenure.company,
    )


def _employer_violation(entry: Entry, parts: list[str], profile: Profile) -> Violation:
    """Report the part of the entry that named an employer the profile has never had."""
    titles = [role.title for tenure in profile.experience for role in tenure.roles]
    unknown = [p for p in parts if not any(_within(_words(p), _words(t)) for t in titles)]
    companies = ", ".join(tenure.company for tenure in profile.experience)
    reason = (
        f"is not an employer in the profile, which lists {companies}; "
        f"use one of those or delete the entry"
    )
    return Violation("employer", unknown[0] if unknown else entry.title, entry.line, reason)


def _title_violation(entry: Entry, text: str, tenure: Tenure) -> Violation:
    held = ", ".join(role.title for role in tenure.roles)
    reason = (
        f"is not a title held at {tenure.company}, where the profile records {held}; "
        f"use one of those"
    )
    return Violation("title", text, entry.line, reason)


# --- education ------------------------------------------------------------------------------------
def _check_education(entry: Entry, profile: Profile) -> list[Violation]:
    """Check that every phrase in an education entry comes from the profile's own credentials."""
    known = _credential_phrases(profile)
    found: list[Violation] = []
    for text, number in ((entry.title, entry.line), (entry.meta, entry.meta_line)):
        found += [
            Violation("education", segment, number, _EDUCATION_REASON)
            for segment in _segments(text)
            if not _is_date(segment) and not any(_within(_words(segment), p) for p in known)
        ]
    return found


def _credential_phrases(profile: Profile) -> tuple[tuple[str, ...], ...]:
    """Return every phrase an education entry may draw on.

    Certifications and awards are in the pool because one heading routinely carries all three:
    "Education & Certifications" is a section, not three sections.
    """
    texts = [profile.contact.location]
    for education in profile.education:
        texts += [education.credential, education.institution, education.location, education.notes]
    for credential in (*profile.certifications, *profile.awards):
        texts += [credential.name, credential.issuer, credential.notes]
    return tuple(_words(text) for text in texts if text)


def _is_date(segment: str) -> bool:
    """Report whether a segment is nothing but dates, which the date check already owns."""
    remainder = segment
    for span in reversed(find_points(segment)):
        remainder = remainder[: span.start] + remainder[span.end :]
    return not any(character.isalnum() for character in remainder)


# --- comparison -----------------------------------------------------------------------------------
def _parts(title: str) -> list[str]:
    return [part for raw in _SPLIT.split(normalise(title)) if (part := _clean(raw))]


def _segments(text: str) -> list[str]:
    return [part for raw in _SEGMENT.split(normalise(text)) if (part := _clean(raw))]


def _clean(text: str) -> str:
    return _EMPHASIS.sub("", text).strip()


def _words(text: str) -> tuple[str, ...]:
    """Reduce text to comparable words, dropping case, punctuation, and spacing."""
    folded = normalise(text).casefold()
    return tuple("".join(c if c.isalnum() else " " for c in folded).split())


def _within(claim: tuple[str, ...], known: tuple[str, ...]) -> bool:
    """Report whether every word of ``claim`` appears, in order and unbroken, inside ``known``."""
    size = len(claim)
    if not size or size > len(known):
        return False
    return any(known[index : index + size] == claim for index in range(len(known) - size + 1))
