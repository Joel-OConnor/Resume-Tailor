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
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from resume_tailor.match.tokens import normalise
from resume_tailor.profile import format_date, format_period
from resume_tailor.verify.dates import Point, earlier, find_points, parse_point, read_range
from resume_tailor.verify.models import Violation
from resume_tailor.verify.skills import stack_note
from resume_tailor.verify.source import Area, Kind

if TYPE_CHECKING:
    from resume_tailor.profile.models import Credential, Profile, Role, Tenure
    from resume_tailor.verify.dates import Range, Span
    from resume_tailor.verify.source import Entry, Line, Source

__all__ = ["check_history"]

# " — Title" and " | Location" are the separators templates/resume.md prescribes; normalise() has
# already folded every dash variant to "-". Spaces are required around "-" so that a hyphenated
# name ("Full-Stack Engineer", "Hewlett-Packard") is never torn in half.
_SPLIT = re.compile(r"\s*\|\s*|\s+-\s+")
# A credential line is read in clauses, split at a semicolon or a pipe, and each clause in
# segments: at a comma, a middle dot, a parenthesis ("Name (Issuer, Year)"), a spaced dash, and a
# colon before a qualifier ("FINRA: formerly licensed"). A colon needs a space after it, which
# keeps a URL whole, and the separator is kept so a segment a colon follows reads as a label.
_CLAUSE = re.compile(r"\s*[;|]\s*")
_SEGMENT = re.compile(r"(\s*[,·]\s*|\s*[()]|\s*:\s+|\s+-\s+)")
_EMPHASIS = re.compile(r"[*`]+")
_AND = re.compile(r"\s+(?:and|&)\s+", re.IGNORECASE)

#: Words that say how a credential was come by rather than what it is: "Issued 2022", "Recipient".
_FRAMING = frozenset(
    {
        "awarded",
        "completed",
        "conferred",
        "coursework",
        "earned",
        "expected",
        "gpa",
        "graduated",
        "issued",
        "received",
        "recipient",
        "relevant",
        "winner",
    }
)
#: Words that only introduce what follows them ("Honors: Magna Cum Laude"). Standing alone they
#: are a claim: "B.S. Computer Science (Honors)" says something the profile has to record.
_LABELS = _FRAMING | {"activities", "honors", "honours", "thesis"}
#: A claim this short may put the profile's words in its own order: "3.9 GPA" for "GPA 3.9".
_LOOSE = 4

_EDUCATION_REASON = (
    "is not in the profile's record of any degree, certification or award; print only what the "
    "profile records for this entry (its credential, institution, location and year) and remove "
    "the rest, such as a city or state the profile does not give"
)
_UNRECORDED_DATE = (
    "is not a date the profile records for any degree, certification or award; remove it"
)


def check_history(source: Source, profile: Profile) -> list[Violation]:
    """Check every experience entry and every credential in ``source`` against ``profile``.

    Under a credentials heading, a ``### `` entry is read with the lines beneath it, and a line
    outside every entry, which is how most Certifications sections list one, is read on its own.
    """
    found: list[Violation] = []
    for entry in source.entries:
        if entry.area is Area.EXPERIENCE:
            found += _check_role(entry, profile)
    for texts in _credential_entries(source):
        found += _check_education(texts, profile)
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
        roles, unknown = _roles_named(parts[:index] + parts[index + 1 :], tenure, entry)
        titles = [_title_violation(entry, text, tenure) for text in unknown]
        return titles + _check_period(entry, tenure, roles)
    return [_employer_violation(entry, parts, profile)]


def _tenure_named(part: str, profile: Profile) -> Tenure | None:
    claim = _words(part)
    return next((t for t in profile.experience if _within(claim, _words(t.company))), None)


def _roles_named(
    parts: list[str], tenure: Tenure, entry: Entry
) -> tuple[tuple[Role, ...], list[str]]:
    """Return every role the entry names, plus the parts no role at this employer accounts for.

    A promotion entry names two titles, and its dates naturally run from the first one's start to
    the last one's end, so the period is checked against the roles together.
    """
    matched: list[Role] = []
    unknown: list[str] = []
    for part in parts:
        claim = _words(part)
        role = _best_role(claim, tenure, entry)
        if role is None:
            unknown.append(part)
        elif role not in matched:
            matched.append(role)
    return tuple(matched), unknown


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
        consistent = [role for role in candidates if not _check_period(entry, tenure, (role,))]
        if consistent:
            candidates = consistent
    return next((role for role in candidates if _words(role.title) == claim), candidates[0])


def _check_period(entry: Entry, tenure: Tenure, roles: tuple[Role, ...]) -> list[Violation]:
    """Check the printed dates against what the entry names, one unbroken stretch at a time.

    An entry naming no role is held to the whole tenure, and one naming several to the span they
    cover together, but only where they cover it without a break: a range printed across the
    years someone was away from an employer claims years they were not there.
    """
    printed = read_range(entry.meta)
    if printed is None:
        return []
    blocks = _blocks(roles or tenure.roles)
    if any(_fits(printed, block) for block in blocks):
        return []
    titled = bool(roles) or len(blocks) > 1
    periods = [f"{_label(tenure, block, titled=titled)} as {_period(block)}" for block in blocks]
    if len(periods) == 1:
        advice = f"it has {periods[0]}. Print dates inside that range"
    else:
        advice = f"it has {' and '.join(periods)}. Print dates inside one of those ranges"
    reason = f"claims a period the profile does not record: {advice}"
    return [Violation("date", printed.text, entry.meta_line, reason)]


def _blocks(roles: tuple[Role, ...]) -> list[tuple[Role, ...]]:
    """Group roles into the unbroken stretches they cover, each in the order it was given.

    A promotion starts the month the earlier role ends, or the month after, so the two make one
    stretch. ``YYYY``, ``YYYY-MM`` and ``present`` sort correctly as plain strings: a bare year
    precedes its own months, and ``present`` follows every digit.
    """
    blocks: list[list[Role]] = []
    for role in sorted(roles, key=lambda role: role.start):
        if blocks and not earlier(_month_after(_end(blocks[-1])), parse_point(role.start)):
            blocks[-1].append(role)
        else:
            blocks.append([role])
    return [tuple(sorted(block, key=roles.index)) for block in blocks]


def _end(block: list[Role] | tuple[Role, ...]) -> Point:
    return parse_point(max(role.end for role in block))


def _month_after(point: Point) -> Point:
    """Return the point just after ``point``, at the precision it states."""
    if not point.month:
        return Point(point.year + 1)
    return Point(point.year + point.month // 12, point.month % 12 + 1)


def _fits(printed: Range, block: tuple[Role, ...]) -> bool:
    start = parse_point(min(role.start for role in block))
    return not earlier(printed.start, start) and not earlier(_end(block), printed.end)


def _period(block: tuple[Role, ...]) -> str:
    return format_period(min(role.start for role in block), max(role.end for role in block))


def _label(tenure: Tenure, block: tuple[Role, ...], *, titled: bool) -> str:
    """Name what a stretch of the profile covers: its titles when they matter, else the company."""
    if not titled:
        return tenure.company
    return f"{' and '.join(role.title for role in block)} at {tenure.company}"


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
@dataclass(frozen=True, slots=True)
class _Text:
    """One line of a credentials entry, or a skill line's label, and how closely it is read."""

    text: str
    number: int
    label: bool = False
    """A ``**Label:**`` is a claim only when the items after it name no record."""

    described: bool = False
    """A plain line under an entry describes it, so only its dates are checked."""


@dataclass(frozen=True, slots=True)
class _Piece:
    """One segment of an entry: the words the profile has to record, and the dates it prints."""

    text: str
    number: int
    clause: int
    claim: tuple[str, ...]
    dates: tuple[tuple[str, Point], ...]
    label: bool


@dataclass(frozen=True, slots=True)
class _Pool:
    """Every phrase a credentials entry may draw on."""

    phrases: tuple[tuple[str, ...], ...]
    loose: tuple[frozenset[str], ...]
    """The same words as sets, for a short claim that reorders them: a name whole, a note by clause,
    so a claim never pairs words from two separate facts in one note."""

    def knows(self, claim: tuple[str, ...]) -> bool:
        """Report whether the profile records ``claim``, shortened or, when short, reordered."""
        if any(_within(claim, phrase) for phrase in self.phrases):
            return True
        return len(claim) <= _LOOSE and any(set(claim) <= words for words in self.loose)


@dataclass(frozen=True, slots=True)
class _Record:
    """One degree, certification or award, as an education entry can name it."""

    label: str
    names: tuple[tuple[str, ...], ...]
    """What identifies it: a degree's credential, a certification's or award's name."""

    issuer: tuple[str, ...]
    """Who issued it: part of one name ("FINRA Series 7"), but not a name on its own."""

    details: tuple[tuple[str, ...], ...]
    """What else an entry may print for it: a school, an issuer, its notes."""

    when: str
    """The date the profile records for it, as the profile writes it; empty when it has none."""

    dates: tuple[Point, ...]
    """Every date the profile records for it: its own, and any its notes state."""


def _credential_entries(source: Source) -> list[list[_Text]]:
    """Group the lines under every credentials heading into the entries they make up.

    A ``### `` heading opens an entry that runs to the next heading. Its dates line, bullets and
    skill lines are read as part of it, and any other plain line describes it. A line outside every
    entry stands on its own. A Tech Stack note is a technology claim, which the skills check reads.
    """
    entries: list[list[_Text]] = []
    current: list[_Text] | None = None
    for line in source.lines:
        if line.kind is Kind.HEADING:
            current = None
            continue
        if line.area is not Area.EDUCATION or stack_note(line) is not None:
            continue
        texts = _texts(line, described=current is not None and line.kind is Kind.PROSE)
        if line.kind is Kind.ENTRY:
            current = texts
            entries.append(current)
        elif current is not None:
            current += texts
        else:
            entries.append(texts)
    return entries


def _texts(line: Line, *, described: bool) -> list[_Text]:
    if line.kind is Kind.SKILL:
        return [_Text(line.label, line.number, label=True), _Text(line.body, line.number)]
    # A plain line's text has an ordered-list marker blanked; every other kind's body has none.
    text = line.text if line.kind is Kind.PROSE else line.body
    return [_Text(text, line.number, described=described)]


def _check_education(texts: list[_Text], profile: Profile) -> list[Violation]:
    """Check one credentials entry's phrases, and its dates, against the profile's own records.

    Every phrase has to be one the profile records, shortened if need be. Every date has to be one
    the profile records for the credential it is printed beside. A ``**Label:**`` is read as a
    claim only when its own line names no record, so "**Cloud:**" can head a list while
    "**M.S. Computer Science:**" before a real school is still an invented degree.
    """
    pool, records = _pool(profile), _records(profile)
    pieces = _read(texts, pool)
    named = {piece.number for piece in pieces if not piece.label and _names(piece.claim, records)}
    pieces = [
        replace(piece, claim=()) if piece.label and piece.number in named else piece
        for piece in pieces
    ]
    found = [
        Violation("education", piece.text, piece.number, _EDUCATION_REASON)
        for piece in pieces
        if piece.claim and not pool.knows(piece.claim) and not _listed(piece.text, pool)
    ]
    for index, piece in enumerate(pieces):
        for text, point in piece.dates:
            allowed, reason = _resolve(_context(pieces, index, records), records)
            if not _recorded_point(point, allowed):
                found.append(Violation("date", text, piece.number, reason))
    return found


def _read(texts: list[_Text], pool: _Pool) -> list[_Piece]:
    pieces: list[_Piece] = []
    clause = 0
    for text in texts:
        for part in _CLAUSE.split(normalise(text.text)):
            clause += 1
            for segment, colon in _segments(part):
                labelled = colon or text.label
                pieces.append(_piece(segment, text, clause, labelled=labelled, pool=pool))
    return pieces


def _piece(segment: str, text: _Text, clause: int, *, labelled: bool, pool: _Pool) -> _Piece:
    """Read one segment into the words the profile has to record and the dates it prints.

    Only a phrase the profile records whole, its own year included ("CKA 2024"), keeps its date
    as written; any other date is checked as a date.
    """
    spans = find_points(segment)
    dates = tuple((segment[span.start : span.end], span.point) for span in spans)
    claim = () if text.described else _claim(_without(segment, spans), labelled=labelled)
    if claim and pool.knows(whole := _claim(segment, labelled=labelled)):
        claim, dates = whole, ()
    return _Piece(segment, text.number, clause, claim, dates, label=text.label)


def _listed(segment: str, pool: _Pool) -> bool:
    """Report whether a segment joins recorded phrases with "and": "Series 7 and 63".

    "And" lists two records the way a comma does, so each side has to be one the profile records.
    """
    sides = [
        _claim(_without(side, find_points(side)), labelled=False) for side in _AND.split(segment)
    ]
    return len(sides) > 1 and all(pool.knows(side) for side in sides if side)


def _claim(text: str, *, labelled: bool) -> tuple[str, ...]:
    """Reduce a segment to the words the profile has to record.

    Framing words say how a credential was come by, not what it is, so they are dropped. A label
    made only of framing or label words introduces what follows it and claims nothing itself.
    """
    words = _words(text)
    if labelled and set(words) <= _LABELS:
        return ()
    return tuple(word for word in words if word not in _FRAMING)


def _context(pieces: list[_Piece], index: int, records: list[_Record]) -> list[tuple[str, ...]]:
    """Return the phrases that say which record the date in ``pieces[index]`` belongs to.

    A date belongs to the nearest credential named in its own clause, the earlier one on a tie,
    so "M.S., 2018; B.S., 2016" holds each year to its own degree. A clause naming none, such as a
    dates line under a heading, falls back to everything the entry names.
    """
    clause = pieces[index].clause
    same = [at for at, piece in enumerate(pieces) if piece.clause == clause and piece.claim]
    naming = [at for at in same if _names(pieces[at].claim, records)]
    if not naming:
        return [piece.claim for piece in pieces if piece.claim]
    nearest = min(naming, key=lambda at: (abs(at - index), at > index))
    return [pieces[nearest].claim] + [pieces[at].claim for at in same if at not in naming]


def _resolve(claims: list[tuple[str, ...]], records: list[_Record]) -> tuple[list[Point], str]:
    """Return the dates the profile records for what ``claims`` name, and why others are wrong.

    A credential or name counts for more than a school or issuer, so a second degree from the same
    school still resolves to its own year. Phrases that name nothing allow every recorded date.
    """
    scores = [_score(record, claims) for record in records]
    best = max(scores, default=0)
    if not best:
        return [point for record in records for point in record.dates], _UNRECORDED_DATE
    chosen = [record for record, score in zip(records, scores, strict=True) if score == best]
    label = " or ".join(record.label for record in chosen)
    when = " or ".join(format_date(record.when) for record in chosen if record.when)
    advice = f"it has {when}, so print that or no date" if when else "print no date for it"
    reason = f"is not a date the profile records for {label}; {advice}"
    return [point for record in chosen for point in record.dates], reason


def _records(profile: Profile) -> list[_Record]:
    records = [
        _Record(
            label=education.credential,
            names=(_words(education.credential),),
            issuer=(),
            details=(_words(education.institution), _words(education.notes)),
            when=education.completed,
            dates=_dates_in(education.completed, education.notes),
        )
        for education in profile.education
    ]
    records += [
        _Record(
            label=credential.name,
            names=(_words(credential.name), _words(_issued(credential))),
            issuer=_words(credential.issuer),
            details=(_words(credential.issuer), _words(credential.notes)),
            when=credential.year,
            dates=_dates_in(credential.year, credential.notes),
        )
        for credential in (*profile.certifications, *profile.awards)
    ]
    return records


def _dates_in(*texts: str) -> tuple[Point, ...]:
    return tuple(span.point for text in texts for span in find_points(text))


def _issued(credential: Credential) -> str:
    """Name a credential behind its issuer, the way a resume often prints it: "FINRA Series 7"."""
    return f"{credential.issuer} {credential.name}"


def _names(claim: tuple[str, ...], records: list[_Record]) -> bool:
    """Report whether ``claim`` names a record by name, not just by a school or issuer."""
    return any(_named(claim, record) for record in records)


def _named(claim: tuple[str, ...], record: _Record) -> bool:
    by_name = any(_matches(claim, name) for name in record.names)
    return by_name and not _matches(claim, record.issuer)


def _score(record: _Record, claims: list[tuple[str, ...]]) -> int:
    """Rate how surely an entry's phrases name this record: 2 for its name, 1 for a detail."""
    by_name = any(_named(claim, record) for claim in claims)
    by_detail = any(_matches(claim, detail) for claim in claims for detail in record.details)
    return 2 * by_name + by_detail


def _matches(claim: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """Report whether ``phrase`` says ``claim``, the way :meth:`_Pool.knows` accepts one."""
    if _within(claim, phrase):
        return True
    return bool(claim) and len(claim) <= _LOOSE and set(claim) <= set(phrase)


def _recorded_point(printed: Point, allowed: list[Point]) -> bool:
    """Report whether a printed date is one the profile records, at the precision both state."""
    return any(
        printed.year == point.year
        and (not printed.month or not point.month or printed.month == point.month)
        for point in allowed
    )


def _pool(profile: Profile) -> _Pool:
    """Return every phrase a credentials entry may draw on.

    Certifications and awards are in the pool with degrees because one heading routinely carries
    all three: "Education & Certifications" is a section, not three sections.
    """
    names = [profile.contact.location]
    notes: list[str] = []
    for education in profile.education:
        names += [education.credential, education.institution, education.location]
        notes.append(education.notes)
    for credential in (*profile.certifications, *profile.awards):
        names += [credential.name, credential.issuer, _issued(credential)]
        notes.append(credential.notes)
    clauses = [
        segment
        for note in notes
        for part in _CLAUSE.split(normalise(note))
        for segment, _ in _segments(part)
    ]
    return _Pool(
        phrases=tuple(_words(text) for text in (*names, *notes) if text),
        loose=tuple(frozenset(_words(text)) for text in (*names, *clauses) if text),
    )


def _without(text: str, spans: tuple[Span, ...]) -> str:
    """Blank the dates out of ``text``, leaving the words around them apart."""
    for span in reversed(spans):
        text = text[: span.start] + " " + text[span.end :]
    return text


# --- comparison -----------------------------------------------------------------------------------
def _parts(title: str) -> list[str]:
    return [part for raw in _SPLIT.split(normalise(title)) if (part := _clean(raw))]


def _segments(text: str) -> list[tuple[str, bool]]:
    """Split a clause into its segments, marking each one a colon follows, which labels the next."""
    parts = _SEGMENT.split(text)
    return [
        (segment, index + 1 < len(parts) and parts[index + 1].strip() == ":")
        for index in range(0, len(parts), 2)
        if (segment := _clean(parts[index]))
    ]


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
