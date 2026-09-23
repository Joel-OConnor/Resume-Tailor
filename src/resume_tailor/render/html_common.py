"""Shared HTML helpers.

The HTML render exists to drive print-to-PDF, so it must mirror the ``.docx`` of the same layout
as closely as a browser can. Keep the two in step whenever either changes.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resume_tailor.documents.blocks import Span

__all__ = ["FONT_IMPORT_URL", "FONT_STACK", "page", "spans_to_html"]

# Roboto is what the user's own design used; the rest are ubiquitous metric-compatible fallbacks
# so the PDF still looks right on a machine without it installed and no network.
FONT_STACK = "Roboto, 'Helvetica Neue', Helvetica, Arial, sans-serif"
FONT_IMPORT_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Roboto:ital,wght@0,200;0,400;0,600;0,700;1,400&display=block"
)
"""The design face, fetched by the browser at print time: the weights the layouts use, no more."""


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
