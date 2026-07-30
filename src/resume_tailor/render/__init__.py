"""Render a parsed document to ``.docx``, HTML, and PDF in either layout.

The module is named ``exporter`` rather than ``build`` so it never shadows the :func:`build`
function re-exported here.
"""

from __future__ import annotations

from resume_tailor.render.exporter import Artifact, Layout, build

__all__ = ["Artifact", "Layout", "build"]
