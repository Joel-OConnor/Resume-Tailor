"""Where everything lives: what the user brings, and what the project makes.

Two folders hold the user's data, both gitignored:

    my-documents/
        career-history/     old resumes, a LinkedIn export, brag docs, and answers.md
        job-postings/       one file per job to apply to
    output/
        master-profile.yaml the career record every document is built from
        master-profile.md   its readable view
        backups/            earlier profiles, one per rebuild or recorded answer
        general/            the general resume and the LinkedIn profile
        applications/       one folder per tailored application

Every path is relative to the working directory, so the scripts are run from the project root
(the Makefile does this). Each command takes a flag to point anywhere else.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ANSWERS_PATH",
    "APPLICATIONS_FOLDER",
    "BACKUPS_FOLDER",
    "CAREER_HISTORY_DIR",
    "GENERAL_FOLDER",
    "JOB_POSTINGS_DIR",
    "MY_DOCUMENTS_DIR",
    "OUTPUT_DIR",
    "PROFILE_PATH",
    "PROFILE_VIEW_PATH",
    "SCHEMA_PATH",
]

MY_DOCUMENTS_DIR = Path("my-documents")
CAREER_HISTORY_DIR = MY_DOCUMENTS_DIR / "career-history"
"""The documents the master profile is built from."""
JOB_POSTINGS_DIR = MY_DOCUMENTS_DIR / "job-postings"
"""Where a posting named without a folder is looked for."""
ANSWERS_PATH = CAREER_HISTORY_DIR / "answers.md"
"""Every answer the user has given, kept with their documents as source for the next rebuild."""

OUTPUT_DIR = Path("output")
PROFILE_PATH = OUTPUT_DIR / "master-profile.yaml"
PROFILE_VIEW_PATH = OUTPUT_DIR / "master-profile.md"
BACKUPS_FOLDER = "backups"
"""Beside the profile, wherever it is: the copies kept each time it is replaced."""
GENERAL_FOLDER = "general"
"""Inside the output folder: the general resume and the LinkedIn profile."""
APPLICATIONS_FOLDER = "applications"
"""Inside the output folder: one ``<company>-<role>`` folder per tailored application."""

SCHEMA_PATH = Path("schema/master-profile.schema.json")
