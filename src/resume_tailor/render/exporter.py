"""Turn one Markdown file into its exported documents."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from resume_tailor.documents import parse
from resume_tailor.documents.blocks import Section
from resume_tailor.errors import RenderError
from resume_tailor.render import ats, polished
from resume_tailor.render.pdf import html_to_pdf

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from resume_tailor.documents.blocks import Document

__all__ = ["Artifact", "Layout", "build", "is_sectioned", "output_names", "read_source"]


class Layout(StrEnum):
    """Which visual treatment to export."""

    ATS = "ats"
    """Single column in the design's typography, parser-safe. The default, and the one to send."""

    POLISHED = "polished"
    """The two-column arrangement of the same design. Opt-in, for a human reader only."""

    BOTH = "both"
    """Export both, side by side."""


@dataclass(frozen=True, slots=True)
class Artifact:
    """One file produced by a build."""

    path: Path
    layout: Layout
    ok: bool = True
    """``False`` for a PDF that fell back to HTML."""

    reason: str = ""
    """Why the PDF could not be produced, when ``ok`` is ``False``."""


def read_source(source: Path) -> Document:
    r"""Read and parse a Markdown source, reporting file problems as :class:`RenderError`.

    ``utf-8-sig`` because editors on Windows write a BOM, and a leading ``﻿`` is not
    whitespace — it would stop ``# Name`` matching and produce an error blaming the user for
    omitting a line that is plainly there.
    """
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        msg = f"cannot read {source}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{source} is not UTF-8 text — re-save it as UTF-8"
        raise RenderError(msg) from exc
    return parse(text)


def build(
    source: Path,
    *,
    out_dir: Path | None = None,
    layout: Layout = Layout.ATS,
    sidebar_sections: tuple[str, ...] = polished.DEFAULT_SIDEBAR_SECTIONS,
    pdf: bool = True,
) -> list[Artifact]:
    """Render ``source`` into ``.docx`` (and optionally ``.pdf``) for each requested layout.

    The default is the single-column layout alone, which keeps the source's stem
    (``resume.docx``); the opt-in polished one is suffixed (``resume-polished.docx``) so both can
    sit in the same application folder when both are asked for.

    ``Layout.BOTH`` skips the polished pass for a cover letter — a letter is prose with no
    sections, so the two-column rail would come out empty and the docs promise letters are always
    single-column. Asking for ``Layout.POLISHED`` explicitly still renders one.
    """
    document = read_source(source)
    directory = out_dir or source.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"cannot write to {directory}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    if layout is Layout.BOTH and not is_sectioned(document):
        # The tool — not the user — decided against the polished pass, so an earlier run's
        # polished files would otherwise sit in the folder the user sends from, holding the
        # previous version of the document. An explicitly chosen layout is left alone.
        layout = Layout.ATS
        _discard(output_names(directory, f"{source.stem}-polished"))

    artifacts: list[Artifact] = []
    if layout in (Layout.ATS, Layout.BOTH):
        artifacts += _one(
            document,
            directory,
            source.stem,
            Layout.ATS,
            ats.render_docx,
            ats.render_html,
            pdf=pdf,
        )
    if layout in (Layout.POLISHED, Layout.BOTH):
        artifacts += _one(
            document,
            directory,
            f"{source.stem}-polished",
            Layout.POLISHED,
            lambda doc, out: polished.render_docx(doc, out, sidebar_sections),
            lambda doc: polished.render_html(doc, sidebar_sections),
            pdf=pdf,
        )
    return artifacts


def _discard(paths: tuple[Path, ...]) -> None:
    """Remove artifacts of a layout this build is not producing."""
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _one(  # noqa: PLR0913, PLR0917 - one renderer pass; each argument is a distinct input
    document: Document,
    directory: Path,
    stem: str,
    layout: Layout,
    render_docx: Callable[[Document, Path], None],
    render_html: Callable[[Document], str],
    *,
    pdf: bool,
) -> list[Artifact]:
    """Render one layout, turning any filesystem failure into a :class:`RenderError`."""
    docx_path, pdf_path, html_path = output_names(directory, stem)
    try:
        render_docx(document, docx_path)
    except OSError as exc:
        msg = f"cannot write {docx_path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc

    artifacts = [Artifact(docx_path, layout)]
    if not pdf:
        return artifacts
    try:
        result = html_to_pdf(render_html(document), pdf_path)
    except OSError as exc:
        msg = f"cannot write {pdf_path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    artifacts.append(
        Artifact(pdf_path if result.ok else html_path, layout, result.ok, result.reason)
    )
    return artifacts


def output_names(directory: Path, stem: str) -> tuple[Path, Path, Path]:
    """Return the ``.docx``, ``.pdf`` and ``.html`` paths for one layout of one source.

    Built by concatenation rather than ``Path.with_suffix``: ``with_suffix`` *replaces* whatever
    follows the last dot, so a source named ``resume.v2.md`` would collapse to ``resume.docx``
    and the polished pass would silently overwrite the ATS file the user submits.
    """
    return (
        directory / f"{stem}.docx",
        directory / f"{stem}.pdf",
        directory / f"{stem}.html",
    )


def is_sectioned(document: Document) -> bool:
    """Report whether this is a resume (it has ``## `` sections) rather than a cover letter."""
    return any(isinstance(block, Section) for block in document.blocks)
