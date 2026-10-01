"""Exceptions raised across the package.

Everything user-facing derives from :class:`ResumeTailorError` so the CLI can turn any of them
into a clean one-line message instead of a traceback.
"""

from __future__ import annotations

__all__ = [
    "ConfigError",
    "DocumentError",
    "FabricationError",
    "ModelError",
    "ProfileError",
    "RenderError",
    "ResumeTailorError",
]


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


class ConfigError(ResumeTailorError):
    """The settings that choose and reach the model are missing or wrong, usually the API key."""


class ModelError(ResumeTailorError):
    """The language model could not be reached, or returned something unusable."""


class FabricationError(ResumeTailorError):
    """Generated content made a claim the profile does not support.

    Raised rather than warned: a resume with an invented claim is the one outcome this project
    exists to prevent.
    """


class RenderError(ResumeTailorError):
    """A document could not be rendered to its output format."""
