"""Allow ``python -m resume_tailor``."""

from __future__ import annotations

import sys

from resume_tailor.cli import main

if __name__ == "__main__":
    sys.exit(main())
