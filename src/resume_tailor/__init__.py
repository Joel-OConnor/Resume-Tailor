"""Build ATS-safe and design-polished resumes from a structured career profile.

Two halves, deliberately decoupled:

* :mod:`resume_tailor.profile` reads ``profile/master-profile.yaml`` — the machine-readable
  superset of a career — and validates it into typed models.
* :mod:`resume_tailor.documents` and :mod:`resume_tailor.render` turn a *tailored* Markdown
  resume or cover letter into ``.docx``/``.pdf`` in either the ATS-safe or polished layout.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
