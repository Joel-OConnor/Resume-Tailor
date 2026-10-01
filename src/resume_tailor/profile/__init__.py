"""The structured master profile: models, loader, JSON Schema, and the views rendered from it."""

from __future__ import annotations

from resume_tailor.profile.loader import DEFAULT_PROFILE_PATH, LEVELS, load, load_mapping, loads
from resume_tailor.profile.markdown_view import format_date, format_period, render_markdown
from resume_tailor.profile.models import (
    Contact,
    Credential,
    Doc,
    Education,
    Highlight,
    Link,
    Profile,
    Project,
    Role,
    Technology,
    TechnologyGroup,
    Tenure,
)
from resume_tailor.profile.schema import build_schema

__all__ = [
    "DEFAULT_PROFILE_PATH",
    "LEVELS",
    "Contact",
    "Credential",
    "Doc",
    "Education",
    "Highlight",
    "Link",
    "Profile",
    "Project",
    "Role",
    "Technology",
    "TechnologyGroup",
    "Tenure",
    "build_schema",
    "format_date",
    "format_period",
    "load",
    "load_mapping",
    "loads",
    "render_markdown",
]
