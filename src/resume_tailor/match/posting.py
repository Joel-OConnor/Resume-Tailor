"""Parse a job posting into requirement units.

The unit of work is a clause, not a document. A posting says very different things in different
places — "you must have Kubernetes", "no Kubernetes needed", "our sister team runs Kubernetes" —
and a scanner that reads the whole file as one bag of words reports all three identically.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.errors import ResumeTailorError
from resume_tailor.match.tokens import Token, normalise, tokenise

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["Clause", "Posting", "PostingError", "Section", "parse_posting", "read_posting"]

_HEADING = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)?(?P<title>[A-Za-z][^*\n]{2,60}?)(?:\*\*)?\s*:?\s*$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_CLAUSE_SPLIT = re.compile(r";|\s-\s|(?<=\s)(?:but|however|though|whereas|while)\s")
_TITLE_SPLIT = re.compile(r"\s[—|–-]\s")
_TITLE_PARTS = 2
_MIN_SUPPRESSED = 3
_MAX_HEADING_WORDS = 6

_NEGATIONS = frozenset({"no", "not", "n't", "never", "without", "nor", "neither", "won't", "wont"})
_NULLIFIERS = frozenset(
    {
        "required",
        "require",
        "requires",
        "necessary",
        "needed",
        "need",
        "needs",
        "expected",
        "must",
        "mandatory",
        "prerequisite",
        "experience",
        "background",
    }
)
_FUTURE = frozenset({"learn", "teach", "train", "willingness", "curious", "ramp"})
_THIRD_PARTY = frozenset({"team", "teams", "squad", "org", "department", "partner", "sister"})
_SECOND_PERSON = frozenset({"you", "your", "you'll", "youll", "yours"})
_DEPRECATED = frozenset(
    {
        "retire",
        "retiring",
        "retired",
        "sunset",
        "deprecate",
        "deprecated",
        "legacy",
        "migrating",
        "away",
    }
)

_MUST_CUES = (
    "requirement",
    "must have",
    "must-have",
    "qualification",
    "what you need",
    "what we need",
    "you have",
    "minimum",
    "basic qualification",
    "required",
)
_NICE_CUES = (
    "nice to have",
    "nice-to-have",
    "preferred",
    "bonus",
    "plus",
    "desirable",
    "additional qualification",
    "even better",
)
_DUTY_CUES = (
    "responsibilit",
    "what you'll do",
    "what you will do",
    "the role",
    "day to day",
    "day-to-day",
    "about the role",
    "your impact",
    "what you'll own",
)
_CONTEXT_CUES = (
    "about us",
    "about the company",
    "about the team",
    "who we are",
    "life at",
    "benefits",
    "perks",
    "compensation",
    "salary",
    "equal opportunity",
    "eeo",
    "diversity",
    "how to apply",
    "our culture",
    "why join",
    "what we offer",
)


class Section(StrEnum):
    """What part of a posting a line came from."""

    MUST = "must"
    NICE = "nice"
    RESPONSIBILITY = "responsibility"
    CONTEXT = "context"
    """About-us, benefits, culture, EEO. Never produces coverage — see :mod:`.coverage`."""

    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Clause:
    """One clause of one line, with the scope signals that decide whether it is a requirement."""

    text: str
    tokens: tuple[Token, ...]
    line: int
    section: Section
    negated: bool
    future: bool
    third_party: bool
    deprecated: bool

    @property
    def counts_as_requirement(self) -> bool:
        """Only a live, first-person, non-context clause states something the candidate needs."""
        return not (
            self.negated
            or self.future
            or self.third_party
            or self.deprecated
            or self.section is Section.CONTEXT
        )


@dataclass(frozen=True, slots=True)
class Posting:
    """A parsed job posting."""

    clauses: tuple[Clause, ...] = ()
    company: str = ""
    title: str = ""

    @property
    def requirement_clauses(self) -> tuple[Clause, ...]:
        """The clauses that actually state a requirement."""
        return tuple(c for c in self.clauses if c.counts_as_requirement)


class PostingError(ResumeTailorError):
    """A posting file is not plain text, so there is no job description to read from it."""


#: What a posting saved from a browser or a word processor usually is instead of text.
_DOCUMENT_KINDS = {".pdf": "a PDF", ".doc": "a Word document", ".docx": "a Word document"}
_PDF_SIGNATURE = b"%PDF-"
_UTF16_MARKS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_SAVE_AS_TEXT = "Save the job description as a .md or .txt file and point at that."


def read_posting(path: Path) -> str:
    """Read a posting file as text, in whichever encoding the editor that saved it used.

    A PDF or a Word document is refused by name, and anything else that is not text is
    refused too, each with a :class:`PostingError` that says how to fix it. Both used to
    surface as a raw codec error.
    """
    data = path.read_bytes()
    kind = _DOCUMENT_KINDS.get(path.suffix.casefold(), "")
    if not kind and data.startswith(_PDF_SIGNATURE):
        kind = "a PDF"
    if kind:
        msg = f"cannot read {path}: it is {kind}, not plain text. {_SAVE_AS_TEXT}"
        raise PostingError(msg)
    text = _decode(data)
    if text is None:
        msg = f"cannot read {path}: it is not plain text. {_SAVE_AS_TEXT}"
        raise PostingError(msg)
    return text


def _decode(data: bytes) -> str | None:
    """Decode a posting's bytes, or return ``None`` when they are not text.

    UTF-8 comes first, with or without the byte-order mark a Windows editor adds. Then UTF-16
    when a byte-order mark says so (Notepad's "Unicode", a Windows PowerShell redirect), and
    otherwise Windows-1252, the "ANSI" Notepad saves by default, whose curly apostrophe is a
    byte UTF-8 rejects. Valid UTF-8 is text unless it holds a NUL, which no text does. The
    other two are guesses: Windows-1252 turns almost any byte into some character, and any
    file can start with the two bytes of a UTF-16 mark. So a guess is kept only when it comes
    out as text this tool can read: no control codes, and Latin letters, the only ones its
    tokenizer matches.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        codec = "utf-16" if data.startswith(_UTF16_MARKS) else "cp1252"
        try:
            text = data.decode(codec)
        except UnicodeDecodeError:
            return None
        return text if _reads_as_text(text) else None
    return None if "\x00" in text else text


def _reads_as_text(text: str) -> bool:
    """Report whether a guessed decoding came out as text: no control codes, and Latin letters.

    Blank text passes, so an empty posting is reported as empty rather than as unreadable.
    """
    if _CONTROL.search(text):
        return False
    return not text.strip() or _LATIN_LETTER.search(text) is not None


def parse_posting(text: str, company: str = "") -> Posting:
    """Parse posting ``text`` into clauses, classifying each by section and scope."""
    source = normalise(text)
    lines = source.splitlines()
    title, detected = _identify(lines)
    company = company or detected
    suppress = _suppression(company)

    clauses: list[Clause] = []
    section = Section.UNKNOWN
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if (heading := _heading_section(line)) is not None:
            section = heading
            continue
        body = _BULLET.sub("", line)
        for part in _split_clauses(body):
            masked = _mask(part, suppress)
            tokens = tokenise(masked)
            if tokens:
                clauses.append(_clause(masked, tokens, number, section))
    return Posting(tuple(clauses), company, title)


#: Words marking a heading half as the role rather than the employer. Both orders are
#: published — "Acme — Staff Engineer" and "Staff Engineer — Acme" — so position alone gets
#: it wrong half the time, and a swapped header makes the whole report look untrustworthy.
_ROLE_WORDS = frozenset(
    {
        "admin",
        "administrator",
        "analyst",
        "architect",
        "consultant",
        "designer",
        "dev",
        "developer",
        "devops",
        "director",
        "engineer",
        "engineering",
        "head",
        "lead",
        "manager",
        "officer",
        "president",
        "principal",
        "programmer",
        "scientist",
        "sde",
        "specialist",
        "sre",
        "staff",
        "swe",
        "technician",
        "vp",
    }
)


def _identify(lines: list[str]) -> tuple[str, str]:
    """Take the role title and company from the first heading, if there is one.

    When exactly one half of "Title — Company" reads as a role, that half is the title. When
    neither half does, or both do ("Senior Python Developer — Data Engineering"), the order is
    a guess, so the whole heading is the title and no company is claimed. The company is masked
    out of the body, and a wrong guess there erases the posting's main requirement, while a
    missed company costs at most one gap line.
    """
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            parts = _TITLE_SPLIT.split(heading, maxsplit=1)
            if len(parts) == _TITLE_PARTS:
                first, second = parts[0].strip(), parts[1].strip()
                if _names_a_role(first) != _names_a_role(second):
                    return (first, second) if _names_a_role(first) else (second, first)
            return heading, ""
    return "", ""


def _names_a_role(text: str) -> bool:
    """Report whether this half of a heading reads as a job title."""
    return any(word.strip(",.()").casefold() in _ROLE_WORDS for word in text.split())


def _suppression(company: str) -> tuple[str, ...]:
    """Words of the company's name, blanked out before scanning.

    A posting from a company called Granite must not match the profile's Granite. The role title
    is deliberately not masked: a "Senior Python Engineer" posting is asking for Python, and the
    heading it sits in is never scanned as body text, so there is nothing to double-count.
    """
    words = {w.casefold() for w in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]*", company)}
    return tuple(sorted(w for w in words if len(w) >= _MIN_SUPPRESSED))


def _mask(text: str, suppress: tuple[str, ...]) -> str:
    if not suppress:
        return text
    pattern = "|".join(re.escape(word) for word in suppress)
    return re.sub(rf"(?<![\w.]){pattern}(?![\w.])", " ", text, flags=re.IGNORECASE)


def _heading_section(line: str) -> Section | None:
    """Classify a heading line, or return ``None`` when the line is body text."""
    if not (line.startswith("#") or (line.startswith("**") and line.endswith("**"))):
        match = _HEADING.match(line)
        if match is None or len(line.split()) > _MAX_HEADING_WORDS or line.endswith((".", ",")):
            return None
        if not line.endswith(":"):
            return None
    title = line.lstrip("#").strip().strip("*").rstrip(":").casefold()
    # Context first: "About the role" is a duty heading, "About the team" is not.
    for cues, section in (
        (_CONTEXT_CUES, Section.CONTEXT),
        (_NICE_CUES, Section.NICE),
        (_MUST_CUES, Section.MUST),
        (_DUTY_CUES, Section.RESPONSIBILITY),
    ):
        if any(cue in title for cue in cues):
            return section
    return Section.UNKNOWN


def _split_clauses(body: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(body) if part.strip()]


def _clause(text: str, tokens: list[Token], line: int, section: Section) -> Clause:
    lowered = {token.lower for token in tokens}
    negated = bool(lowered & _NEGATIONS) and bool(lowered & _NULLIFIERS)
    third_party = bool(lowered & _THIRD_PARTY) and not (lowered & _SECOND_PERSON)
    return Clause(
        text=text,
        tokens=tuple(tokens),
        line=line,
        section=section,
        negated=negated,
        future=bool(lowered & _FUTURE),
        third_party=third_party,
        deprecated=bool(lowered & _DEPRECATED),
    )
