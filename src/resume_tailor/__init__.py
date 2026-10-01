"""Turn a structured record of a real career into resumes, a LinkedIn profile and cover letters.

A language model writes and the code checks:

* :mod:`resume_tailor.agent` asks the model, through :mod:`resume_tailor.llm`, for every
  document and every profile edit, and retries until its reply passes its check;
* :mod:`resume_tailor.verify` and :mod:`resume_tailor.review` hold each reply to the master
  profile (:mod:`resume_tailor.profile`), so nothing it cannot support is kept;
* :mod:`resume_tailor.service` runs the three jobs end to end, and :mod:`resume_tailor.render`
  turns the result into ``.docx`` and ``.pdf``.

``reference/ARCHITECTURE.md`` walks through the whole design.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
