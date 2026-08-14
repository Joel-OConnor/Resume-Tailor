"""Carry what a check found, without dragging the package's entry point in behind it.

Every checker builds :class:`Violation` values, and :mod:`resume_tailor.verify` collects them.
Keeping the two types here is what lets that happen in one direction instead of a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Verdict", "Violation"]


@dataclass(frozen=True, slots=True)
class Violation:
    """One claim in a generated document that the profile does not support."""

    kind: str
    """One of: technology, employer, title, metric, education, date."""

    text: str
    """The offending span, quoted back to the user."""

    line: int
    """1-based line in the generated Markdown."""

    reason: str
    """Why it is unsupported, phrased so a model can act on it without more context."""

    @property
    def sort_key(self) -> tuple[int, str, str]:
        """Order violations the way the document reads: top to bottom."""
        return (self.line, self.kind, self.text)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The result of verifying one generated document."""

    violations: tuple[Violation, ...] = ()

    @property
    def ok(self) -> bool:
        """True when nothing in the document claimed more than the profile does."""
        return not self.violations
