"""The standalone path's model operations: every place a language model writes something.

Profile operations draft the master profile, refine it, and record the candidate's answers in it;
document operations write the general resume with its LinkedIn profile, tailor a resume and cover
letter to one posting, and edit any of them a second time. All of them retry until their checks
pass, and raise rather than hand back an answer that failed one.
"""

from __future__ import annotations

from resume_tailor.agent.loop import Usage
from resume_tailor.agent.profiling import ProfileEdit, build_profile, refine_profile, update_profile
from resume_tailor.agent.prompts import COVER_LETTER, LINKEDIN, RESUME
from resume_tailor.agent.writing import (
    EditResult,
    GeneralResult,
    TailorResult,
    edit_documents,
    tailor,
    write_general,
)

__all__ = [
    "COVER_LETTER",
    "LINKEDIN",
    "RESUME",
    "EditResult",
    "GeneralResult",
    "ProfileEdit",
    "TailorResult",
    "Usage",
    "build_profile",
    "edit_documents",
    "refine_profile",
    "tailor",
    "update_profile",
    "write_general",
]
