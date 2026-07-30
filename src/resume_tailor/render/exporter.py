"""Turn one Markdown file into its exported documents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.documents import parse
from resume_tailor.documents.blocks import Section
from resume_tailor.render import ats, polished
from resume_tailor.render.pdf import html_to_pdf

if TYPE_CHECKING:
    from pathlib import Path

    from resume_tailor.documents.blocks import Document

__all__ = ["Artifact", "Layout", "build", "is_sectioned"]


class Layout(StrEnum):
    """Which visual treatment to export."""

    ATS = "ats"
    """Single column, parser-safe. Submit this one."""

    POLISHED = "polished"
    """Two-column typographic design. Send this to a human."""

    BOTH = "both"
    """Export both, side by side."""


@dataclass(frozen=True, slots=True)
class Artifact:
    """One file produced by a build."""

    path: Path
    layout: Layout
    ok: bool = True
    """``False`` for a PDF that fell back to HTML because Chrome was unavailable."""


def build(
    source: Path,
    *,
    out_dir: Path | None = None,
    layout: Layout = Layout.BOTH,
    sidebar_sections: tuple[str, ...] = polished.DEFAULT_SIDEBAR_SECTIONS,
    pdf: bool = True,
) -> list[Artifact]:
    """Render ``source`` into ``.docx`` (and optionally ``.pdf``) for each requested layout.

    The ATS layout keeps the source's stem (``resume.docx``); the polished one is suffixed
    (``resume-polished.docx``) so both can sit in the same application folder.

    ``Layout.BOTH`` skips the polished pass for a cover letter — a letter is prose with no
    sections, so the two-column rail would come out empty and the docs promise letters are always
    single-column. Asking for ``Layout.POLISHED`` explicitly still renders one.
    """
    document = parse(source.read_text(encoding="utf-8"))
    directory = out_dir or source.parent
    directory.mkdir(parents=True, exist_ok=True)
    if layout is Layout.BOTH and not is_sectioned(document):
        layout = Layout.ATS

    artifacts: list[Artifact] = []
    if layout in (Layout.ATS, Layout.BOTH):
        base = directory / source.stem
        ats.render_docx(document, base.with_suffix(".docx"))
        artifacts.append(Artifact(base.with_suffix(".docx"), Layout.ATS))
        if pdf:
            ok = html_to_pdf(ats.render_html(document), base.with_suffix(".pdf"))
            artifacts.append(Artifact(base.with_suffix(".pdf" if ok else ".html"), Layout.ATS, ok))

    if layout in (Layout.POLISHED, Layout.BOTH):
        base = directory / f"{source.stem}-polished"
        polished.render_docx(document, base.with_suffix(".docx"), sidebar_sections)
        artifacts.append(Artifact(base.with_suffix(".docx"), Layout.POLISHED))
        if pdf:
            html = polished.render_html(document, sidebar_sections)
            ok = html_to_pdf(html, base.with_suffix(".pdf"))
            artifacts.append(
                Artifact(base.with_suffix(".pdf" if ok else ".html"), Layout.POLISHED, ok)
            )

    return artifacts


def is_sectioned(document: Document) -> bool:
    """Report whether this is a resume (it has ``## `` sections) rather than a cover letter."""
    return any(isinstance(block, Section) for block in document.blocks)
