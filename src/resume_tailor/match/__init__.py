"""Match a job posting against the master profile, without ever overstating coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from resume_tailor.match.coverage import Confidence, Coverage, Match, find_coverage
from resume_tailor.match.gaps import Gap, find_gaps
from resume_tailor.match.lexicon import Lexicon, Provenance, Tier, build_lexicon
from resume_tailor.match.posting import Posting, PostingError, Section, parse_posting, read_posting
from resume_tailor.match.report import Report, render_markdown

if TYPE_CHECKING:
    from resume_tailor.profile.models import Profile

__all__ = [
    "Confidence",
    "Coverage",
    "Gap",
    "Lexicon",
    "Match",
    "Posting",
    "PostingError",
    "Provenance",
    "Report",
    "Section",
    "Tier",
    "build_lexicon",
    "find_coverage",
    "find_gaps",
    "match_posting",
    "parse_posting",
    "read_posting",
    "render_markdown",
]


def match_posting(text: str, profile: Profile, company: str = "") -> Report:
    """Match posting ``text`` against ``profile`` and return a renderable report."""
    lexicon = build_lexicon(profile)
    posting = parse_posting(text, company)
    return Report(posting, find_coverage(posting, lexicon), find_gaps(posting, lexicon))
