"""Which words of an entry heading are bold: one rule for both layouts and both renderers.

A role heading bolds the job title or the company, never both, so each role has one anchor for
the eye. The Markdown says which by bolding the title itself:
``### **Senior Backend Engineer** – Northwind Payments``. Deciding it here, once, keeps each
layout's ``.docx`` and the PDF printed from its HTML from disagreeing about the weight.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.documents.blocks import Span

__all__ = ["entry_spans"]


def entry_spans(spans: tuple[Span, ...]) -> tuple[Span, ...]:
    """Return a ``### `` heading's spans with the weight each is set in, on a regular base.

    A heading that bolds any of its text is set as written: the bold part (the title, degree, or
    certification) bold and the rest (the company or institution) regular. A heading that bolds
    nothing was written before the convention, and is set bold throughout as headings used to be.
    """
    if any(span.bold for span in spans):
        return spans
    return tuple(replace(span, bold=True) for span in spans)
