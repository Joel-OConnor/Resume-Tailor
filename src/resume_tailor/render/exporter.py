"""Turn one Markdown file into its exported documents."""

from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor.documents import parse
from resume_tailor.documents.blocks import is_sectioned
from resume_tailor.errors import RenderError
from resume_tailor.render import ats, polished
from resume_tailor.render.pdf import html_to_pdf

if TYPE_CHECKING:
    from collections.abc import Callable

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
        msg = f"{source} is not UTF-8 text: re-save it as UTF-8"
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

    With ``pdf=False`` an earlier build's ``.pdf`` and ``.html`` for each layout rendered here are
    removed rather than left beside the new ``.docx``, so the folder never pairs this version of
    the document with a previous one.

    ``Layout.BOTH`` skips the polished pass for a cover letter — a letter is prose with no
    sections, so the two-column rail would come out empty and the docs promise letters are always
    single-column. Asking for ``Layout.POLISHED`` explicitly still renders one.

    A source that is itself one of the files this build writes or removes (Markdown saved as
    ``resume.html``, say) is refused before anything is touched, rather than destroyed.
    """
    document = read_source(source)
    directory = out_dir or source.parent
    _refuse_to_destroy(source, directory, layout)
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


def _refuse_to_destroy(source: Path, directory: Path, layout: Layout) -> None:
    """Raise if any file this build may write or remove is the source itself.

    Each layout's ``.docx``, ``.pdf`` and ``.html`` are replaced or removed outright, so a
    Markdown source saved under one of those names would be overwritten or deleted with no
    warning. ``Layout.BOTH`` covers the polished names even for a letter, whose earlier polished
    files are removed.
    """
    stems = [
        stem
        for stem, own in ((source.stem, Layout.ATS), (f"{source.stem}-polished", Layout.POLISHED))
        if layout in (own, Layout.BOTH)
    ]
    for path in (path for stem in stems for path in output_names(directory, stem)):
        if _is_same_file(path, source):
            msg = (
                f"this source is also an output of the build ({path.name}), so building would "
                f"destroy it; rename it to {source.stem}.md"
            )
            raise RenderError(msg)


def _is_same_file(path: Path, source: Path) -> bool:
    """Report whether ``path`` is the source, however the two names are spelled.

    ``samefile`` rather than comparing the names: on macOS and Windows ``resume.HTML`` and
    ``resume.html`` are one file, so a source differing from an output only in case is still
    the file that output would replace.
    """
    try:
        return path.samefile(source)
    except OSError:  # nothing there yet, so nothing to destroy
        return False


def _discard(paths: tuple[Path, ...]) -> None:
    """Remove earlier artifacts this build is not replacing."""
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _write_atomically(target: Path, write: Callable[[Path], None]) -> None:
    """Have ``write`` produce ``target`` beside it first, then swap it into place.

    Writing in place means a write that fails partway (a full disk, a synced folder going
    offline) leaves a truncated ``resume.docx`` where the last good one was. The draft goes in a
    scratch folder in the same directory, so the swap is a rename on one filesystem; a folder
    rather than a temporary file, so the writer creates the draft with ordinary permissions
    instead of a temporary file's owner-only ones. On any failure the scratch folder and the
    partial draft in it are removed and ``target`` is left exactly as it was.
    """
    with tempfile.TemporaryDirectory(
        prefix=".resume-tailor-", dir=target.parent, ignore_cleanup_errors=True
    ) as scratch:
        draft = Path(scratch) / target.name
        write(draft)
        draft.replace(target)


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
        _write_atomically(docx_path, lambda path: render_docx(document, path))
    except OSError as exc:
        msg = f"cannot write {docx_path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc

    artifacts = [Artifact(docx_path, layout)]
    if not pdf:
        # No PDF was asked for, not the last one kept: an earlier build's PDF or printable HTML
        # would sit beside the new .docx under the same name, passing for its current twin.
        _discard((pdf_path, html_path))
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
