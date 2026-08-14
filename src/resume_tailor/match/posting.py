"""Parse a job posting into requirement units.

The unit of work is a clause, not a document. A posting says very different things in different
places — "you must have Kubernetes", "no Kubernetes needed", "our sister team runs Kubernetes" —
and a scanner that reads the whole file as one bag of words reports all three identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from resume_tailor.match.tokens import Token, normalise, tokenise

__all__ = ["Clause", "Posting", "Section", "parse_posting"]

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


def parse_posting(text: str, company: str = "") -> Posting:
    """Parse posting ``text`` into clauses, classifying each by section and scope."""
    source = normalise(text)
    lines = source.splitlines()
    title, detected = _identify(lines)
    company = company or detected
    suppress = _suppression(company, title)

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
        "administrator",
        "analyst",
        "architect",
        "consultant",
        "designer",
        "developer",
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
        "specialist",
        "staff",
        "technician",
        "vp",
    }
)


def _identify(lines: list[str]) -> tuple[str, str]:
    """Take the role title and company from the first heading, if there is one."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            parts = _TITLE_SPLIT.split(heading, maxsplit=1)
            if len(parts) == _TITLE_PARTS:
                first, second = parts[0].strip(), parts[1].strip()
                if _names_a_role(first) and not _names_a_role(second):
                    return first, second
                return second, first
            return heading, ""
    return "", ""


def _names_a_role(text: str) -> bool:
    """Report whether this half of a heading reads as a job title."""
    return any(word.strip(",.()").casefold() in _ROLE_WORDS for word in text.split())


def _suppression(company: str, title: str) -> tuple[str, ...]:
    """Words to blank out before scanning.

    A posting from a company called Granite must not match the profile's Granite, and a posting
    titled "Node.js Engineer" should not have its own title double-counted as body evidence.
    """
    words: set[str] = set()
    for phrase in (company, title):
        words.update(w.casefold() for w in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]*", phrase))
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
