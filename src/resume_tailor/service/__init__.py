"""Orchestration shared by every entry point.

The CLI is a thin adapter over this package: anything that decides *what happens* lives here,
anything that decides *how it is said* lives in the CLI. Three runs are exposed, one per thing the
project makes:

* :func:`build_master_profile`: the profile, drafted from the user's documents and refined;
* :func:`general_application`: the general resume and the LinkedIn profile;
* :func:`tailor_application`: a resume and cover letter for one job posting.

Each is synchronous and blocks until its files are on disk. Questions for the candidate go through
an ``ask`` callback, so the same run works at a terminal, in a test, or with nobody there to ask.
"""

from __future__ import annotations

from resume_tailor.service.applications import (
    COVER_LETTER_FILE,
    DEFAULT_OUTPUT_DIR,
    GENERAL_SLUG,
    JOB_DESCRIPTION_FILE,
    LINKEDIN_FILE,
    RESUME_FILE,
    Application,
    general_application,
    slugify,
    tailor_application,
)
from resume_tailor.service.profile import (
    DEFAULT_ANSWERS_PATH,
    DEFAULT_CAREER_DIR,
    Asker,
    ProfileBuild,
    ProfileUpdate,
    Progress,
    RawDocuments,
    apply_answers,
    build_master_profile,
    read_raw_documents,
    record_answers,
    write_profile,
)

__all__ = [
    "COVER_LETTER_FILE",
    "DEFAULT_ANSWERS_PATH",
    "DEFAULT_CAREER_DIR",
    "DEFAULT_OUTPUT_DIR",
    "GENERAL_SLUG",
    "JOB_DESCRIPTION_FILE",
    "LINKEDIN_FILE",
    "RESUME_FILE",
    "Application",
    "Asker",
    "ProfileBuild",
    "ProfileUpdate",
    "Progress",
    "RawDocuments",
    "apply_answers",
    "build_master_profile",
    "general_application",
    "read_raw_documents",
    "record_answers",
    "slugify",
    "tailor_application",
    "write_profile",
]
