"""Shared HTML helpers.

The HTML render exists to drive print-to-PDF, so it must mirror the ``.docx`` of the same layout
as closely as a browser can. Keep the two in step whenever either changes.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.documents.blocks import Span

__all__ = ["FONT_STACK", "page", "spans_to_html"]

# Arial is installed on every Mac and Windows machine, so the browser has nothing to fetch at print
# time and Word draws the .docx in the same face. Helvetica, its metric twin, covers anywhere else.
FONT_STACK = "Arial, Helvetica, sans-serif"


def spans_to_html(spans: tuple[Span, ...]) -> str:
    """Render spans as escaped HTML with ``<strong>``/``<em>`` emphasis."""
    parts: list[str] = []
    for span in spans:
        text = html.escape(span.text)
        if span.bold:
            text = f"<strong>{text}</strong>"
        if span.italic:
            text = f"<em>{text}</em>"
        parts.append(text)
    return "".join(parts)


def page(title: str, css: str, body: str) -> str:
    """Wrap rendered body HTML in a complete, self-contained document."""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{css}</style></head>"
        f"<body>{body}</body></html>\n"
    )
