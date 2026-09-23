"""What a review says: findings at three levels, anchored to the line they are about."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Finding", "Level", "Review"]


class Level(StrEnum):
    """How a finding is acted on."""

    FIX = "fix"
    """Mechanical and safe: applied automatically, and named so the change stays visible."""

    ADVISE = "advise"
    """A readability call for an editor to make — the model pass, or the user."""

    ASK = "ask"
    """Needs a fact only the candidate has. Becomes a question in the prompt cycle."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing the review noticed."""

    rule: str
    level: Level
    line: int
    """1-based line in the document; 0 when the finding has no line, e.g. a profile field."""

    text: str
    """The offending line or fragment, quoted so the reader can find it."""

    message: str
    replacement: str = ""
    """For a FIX: the whole corrected line."""


@dataclass(frozen=True, slots=True)
class Review:
    """Every finding for one document, in line order, plus the fixes already applied to it."""

    findings: tuple[Finding, ...] = ()
    applied: tuple[Finding, ...] = ()
    """The FIX findings that were acted on before ``findings`` were computed."""

    def at(self, level: Level) -> tuple[Finding, ...]:
        """Return the findings at one level."""
        return tuple(finding for finding in self.findings if finding.level is level)

    @property
    def fixes(self) -> tuple[Finding, ...]:
        """Findings that can be applied mechanically."""
        return self.at(Level.FIX)

    @property
    def advice(self) -> tuple[Finding, ...]:
        """Findings an editor should act on."""
        return self.at(Level.ADVISE)

    @property
    def questions(self) -> tuple[Finding, ...]:
        """Findings only the candidate can resolve."""
        return self.at(Level.ASK)
