"""Exceptions raised across the package.

Everything user-facing derives from :class:`ResumeTailorError` so the CLI can turn any of them
into a clean one-line message instead of a traceback.
"""

from __future__ import annotations

__all__ = ["DocumentError", "ProfileError", "RenderError", "ResumeTailorError"]


class ResumeTailorError(Exception):
    """Base class for every error this package reports to the user."""


class DocumentError(ResumeTailorError):
    """The Markdown source does not follow the resume/cover-letter contract."""


class ProfileError(ResumeTailorError):
    """The profile YAML is missing, malformed, or fails validation.

    ``path`` points at the offending location in the document (e.g. ``experience[0].start``)
    so the message tells the user exactly what to fix.
    """

    def __init__(self, message: str, path: str = "") -> None:
        """Record ``path`` and prefix it onto ``message``."""
        self.path = path
        super().__init__(f"{path}: {message}" if path else message)


class RenderError(ResumeTailorError):
    """A document could not be rendered to its output format."""
