r"""Inline emphasis parsing: ``**bold**``, ``*italic*``, ``_italic_``, ``***both***``.

Deliberately tiny. A resume needs bold for lead-ins and italic for dates and tech stacks; every
other Markdown inline construct (links, code, images) is either meaningless on a resume or
actively hostile to an ATS parser, so it is left as literal text.

Emphasis nests (``**Cut *p99* latency**``), and ``\\*`` escapes a literal marker — without those
two, a stray delimiter reaches the exported PDF as a visible asterisk.
"""

from __future__ import annotations

import re

from resume_tailor.documents.blocks import Span

__all__ = ["parse_spans"]

# Order matters: an escape wins over everything, then the longest delimiter — ``***`` before
# ``**`` before ``*``. Notes on the parts that are not obvious:
#
# * ``(?!\s)`` / ``(?<![\s\\])`` require non-space inner edges, so "a ** b ** c" stays literal,
#   and stop a closer landing on an escaped ``\*``.
# * ``\\.`` is listed first in each body so an escape is consumed atomically.
# * ``\*(?=\*\*(?!\*))`` lets a bold body end in a single star, so the trailing italic in
#   "**Cut latency by *38%***" closes against the last two stars rather than the first two.
# * ``{1,400}?`` is lazy and bounded: greedy swallows the closer, and unbounded backtracks
#   quadratically on a long line of ``**``.
_INLINE = re.compile(
    r"""
    \\(?P<escape>[*_\\])
  | \*\*\*(?!\s)(?P<both>(?:\\.|[^*]){1,400}?)(?<![\s\\])\*\*\*
  | \*\*(?!\s)(?P<bold>(?:\\.|\*(?!\*)|\*(?=\*\*(?!\*))|[^*]){1,400}?)(?<![\s\\])\*\*(?!\*)
  | \*(?!\*)(?!\s)(?P<star>(?:\\.|\*\*|[^*]){1,400}?)(?<![\s\\])\*(?!\*)
  | (?<!\w)_(?!\s)(?P<under>(?:\\.|[^_]){1,400}?)(?<![\s\\])_(?!\w)
    """,
    re.VERBOSE,
)


def _push(spans: list[Span], text: str, *, bold: bool = False, italic: bool = False) -> None:
    """Append a span, merging into the previous one when the emphasis is identical."""
    if not text:
        return
    if spans and spans[-1].bold == bold and spans[-1].italic == italic:
        spans[-1] = Span(spans[-1].text + text, bold=bold, italic=italic)
    else:
        spans.append(Span(text, bold=bold, italic=italic))


def _extend(spans: list[Span], more: tuple[Span, ...]) -> None:
    """Append already-parsed spans, merging at the seam."""
    for span in more:
        _push(spans, span.text, bold=span.bold, italic=span.italic)


def parse_spans(text: str, *, bold: bool = False, italic: bool = False) -> tuple[Span, ...]:
    """Split ``text`` into emphasis spans.

    ``bold``/``italic`` set the baseline emphasis for the whole string, which lets a caller render
    an already-italic line (a dates line, say) that still contains bold segments. The same
    parameters carry the outer emphasis down when a delimiter is nested inside another.
    """
    spans: list[Span] = []
    position = 0
    for match in _INLINE.finditer(text):
        _push(spans, text[position : match.start()], bold=bold, italic=italic)
        # Recursion always shrinks the input by at least two delimiters, so it terminates.
        if (inner := match.group("escape")) is not None:
            _push(spans, inner, bold=bold, italic=italic)
        elif (inner := match.group("both")) is not None:
            _extend(spans, parse_spans(inner, bold=True, italic=True))
        elif (inner := match.group("bold")) is not None:
            _extend(spans, parse_spans(inner, bold=True, italic=italic))
        else:
            inner = match.group("star")
            if inner is None:
                inner = match.group("under")
            _extend(spans, parse_spans(inner, bold=bold, italic=True))
        position = match.end()
    _push(spans, text[position:], bold=bold, italic=italic)
    return tuple(spans)
