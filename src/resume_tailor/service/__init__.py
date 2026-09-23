"""Orchestration shared by every entry point.

The CLI and the HTTP API are both thin adapters over this module, so the two cannot drift: a
behaviour change lands here once and both surfaces get it. Anything that decides *what happens*
belongs in this file; anything that decides *how a caller says it* belongs in the adapter.

Tailoring is **synchronous** — one call blocks until the folder is on disk, and either the whole
application is there or none of it is. That is right for a CLI and for a single-user API. When a
UI needs progress reporting, a job queue slots in at this layer (the API returns a job id and
polls it) without touching the agent or the verification code underneath.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor.agent import refine_resume, tailor
from resume_tailor.errors import RenderError
from resume_tailor.match import match_posting, render_markdown
from resume_tailor.profile import DEFAULT_SHAPE, ResumeShape, load, render_general_resume
from resume_tailor.render import Layout, build
from resume_tailor.review import Finding, Level, Review, apply_fixes, review_and_fix, review_resume
from resume_tailor.review import render_markdown as render_review

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile import Profile

__all__ = [
    "DEFAULT_APPLICATIONS_DIR",
    "GENERAL_SLUG",
    "Application",
    "RawDocuments",
    "check_profile",
    "general_resume",
    "list_applications",
    "match_only",
    "read_raw_documents",
    "slugify",
    "tailor_application",
]

DEFAULT_APPLICATIONS_DIR = Path("applications")

GENERAL_SLUG = "general"
"""The one application folder that is not a job: the untailored resume of the whole profile."""

JOB_DESCRIPTION_FILE = "job-description.md"
RESUME_FILE = "resume.md"
FIT_REPORT_FILE = "fit-report.md"
COVER_LETTER_FILE = "cover-letter.md"
LINKEDIN_FILE = "linkedin.md"

_RAW_GUIDE = "README.md"
"""The project's own instructions in profile/raw/ — not the user's career history."""

_FALLBACK_SLUG = "application"
_MAX_SLUG = 80
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RawDocuments:
    """What a profile build found to read, and what it could not."""

    documents: dict[str, str]
    """Filename to extracted text, for every file that yielded any."""

    skipped: tuple[str, ...] = ()
    """Files that produced no text — an unsupported format, or a PDF that is only a scan."""


@dataclass(frozen=True, slots=True)
class Application:
    """One application folder: where it is, what it holds, and what a second read of it found."""

    slug: str
    directory: Path
    files: tuple[Path, ...]
    company: str = ""
    role: str = ""
    review: Review = field(default_factory=Review)
    """The readability review of the resume as written: fixes made, advice, open questions."""


def slugify(company: str, role: str) -> str:
    """Build the ``company-role`` folder name for an application.

    The result is always exactly one safe path segment: accents fold to ASCII, every other
    character becomes a hyphen, and runs collapse. That is what stops a company of ``..`` or a
    role of ``/etc/passwd`` from steering a write outside the applications directory — a slug can
    contain no separator and can never be a relative reference, so joining it onto a trusted
    parent stays inside that parent.
    """
    folded = unicodedata.normalize("NFKD", f"{company} {role}").casefold()
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _NOT_SLUG.sub("-", ascii_only).strip("-")
    # Long enough to stay readable, short enough that the renderers' own suffixes still fit
    # inside a 255-byte filename. Truncation can expose a hyphen, so strip again after it.
    return slug[:_MAX_SLUG].rstrip("-") or _FALLBACK_SLUG


def tailor_application(  # noqa: PLR0913 - one run; every argument is a distinct input
    posting: str,
    *,
    profile_path: Path,
    applications_dir: Path,
    model: LanguageModel,
    export: bool = True,
    refine: bool = True,
) -> Application:
    """Tailor ``posting`` into a complete application folder and report what was written.

    The draft gets a second read before it is written: the mechanical fixes are applied, the
    model edits it for readability under the same verifier that guarded the draft (skipped with
    ``refine=False``), and what remains — advice, and questions only the candidate can answer —
    goes into the fit report and comes back on the :class:`Application`.

    Nothing appears at ``applications_dir/<slug>`` until every document is written and every
    export has succeeded: the run builds into a hidden sibling directory and swaps it in at the
    end. So a model failure, a fabricated claim, or a broken render leaves an earlier version of
    the folder exactly as it was, instead of a half-written one the user might send to a
    recruiter.

    Raises:
        ProfileError: the profile is missing or does not validate.
        ModelError: the model could not be reached or returned nothing usable.
        FabricationError: the draft claimed something the profile does not support.
        DocumentError: the draft does not follow the resume format contract.
        RenderError: a document could not be written or exported.
    """
    profile = load(profile_path)
    draft = tailor(posting, profile, model)
    resume, review = _polish(draft.resume, profile, model if refine else None)
    slug = slugify(draft.company, draft.role)
    documents = {
        JOB_DESCRIPTION_FILE: posting,
        RESUME_FILE: resume,
        FIT_REPORT_FILE: _fit_report(draft.fit_report, posting, profile, draft.company, review),
        COVER_LETTER_FILE: draft.cover_letter,
        LINKEDIN_FILE: draft.linkedin,
    }
    directory = _publish(applications_dir, slug, documents, export=_export if export else None)
    return Application(
        slug=slug,
        directory=directory,
        files=_files(directory),
        company=draft.company,
        role=draft.role,
        review=review,
    )


def _polish(markdown: str, profile: Profile, model: LanguageModel | None) -> tuple[str, Review]:
    """Give a resume its second read: fix, edit if a model is on hand, then review what is left.

    The editor's own questions join the review's as ``ASK`` findings, so a caller sees one list
    of what the candidate still has to answer whichever reader raised it.
    """
    fixed, applied = apply_fixes(markdown)
    asked: tuple[Finding, ...] = ()
    if model is not None:
        edited = refine_resume(fixed, profile, review_resume(fixed), model)
        fixed, more = apply_fixes(edited.resume)
        applied += more
        asked = tuple(
            Finding("editor", Level.ASK, 0, "", question) for question in edited.questions
        )
    return fixed, Review(review_resume(fixed).findings + asked, applied)


def general_resume(
    *,
    profile_path: Path,
    applications_dir: Path,
    shape: ResumeShape = DEFAULT_SHAPE,
    export: bool = True,
) -> Application:
    """Render the whole profile as one untailored resume and report the folder written.

    Deterministic and key-free: :func:`resume_tailor.profile.render_general_resume` prints the
    profile's own words in the profile's own order, so there is no model to consult and nothing
    a verifier could reject. The folder is always ``applications_dir / GENERAL_SLUG``, replaced
    whole on every run, with the same all-or-nothing guarantee as :func:`tailor_application`.

    Raises:
        ProfileError: the profile is missing or does not validate.
        RenderError: the resume could not be written or exported.
    """
    markdown, review = review_and_fix(render_general_resume(load(profile_path), shape))
    directory = _publish(
        applications_dir,
        GENERAL_SLUG,
        {RESUME_FILE: markdown},
        export=_export_resume if export else None,
    )
    return Application(GENERAL_SLUG, directory, _files(directory), review=review)


def list_applications(applications_dir: Path) -> tuple[Application, ...]:
    """List every application folder already on disk, in slug order.

    ``company`` and ``role`` come back empty: only the run that generated a folder knows them,
    and a slug cannot be split back into the two of them unambiguously. A directory whose name
    starts with a dot is skipped — that is a run in flight, not an application.
    """
    if not applications_dir.is_dir():
        return ()
    return tuple(
        Application(slug=child.name, directory=child, files=_files(child))
        for child in sorted(applications_dir.iterdir())
        if child.is_dir() and not child.name.startswith(".")
    )


def check_profile(profile_path: Path) -> dict[str, object]:
    """Summarise the profile for a UI: what it contains, and what it still has to confirm.

    ``notes`` is the important key. Everything in it is unconfirmed by definition, so a surface
    that shows this summary must show those too — they are the claims a resume must not print.
    """
    profile = load(profile_path)
    return {
        "path": str(profile_path),
        "name": profile.contact.name,
        "headline": profile.contact.headline,
        "target_roles": list(profile.target_roles),
        "employers": len(profile.experience),
        "roles": sum(len(tenure.roles) for tenure in profile.experience),
        "highlights": sum(
            len(role.highlights) for tenure in profile.experience for role in tenure.roles
        ),
        "technologies": len(
            {item.name.casefold() for group in profile.technologies for item in group.items}
        ),
        "education": len(profile.education),
        "certifications": len(profile.certifications),
        "awards": len(profile.awards),
        "projects": len(profile.projects),
        "notes": list(profile.notes),
    }


def match_only(posting: str, profile_path: Path) -> str:
    """Return the deterministic keyword coverage for ``posting`` as Markdown.

    No model and no API key: this is the half of the product that works on any machine, and the
    honest answer to "am I even close?" before spending a generation on it.
    """
    return render_markdown(match_posting(posting, load(profile_path)))


def _fit_report(
    narrative: str, posting: str, profile: Profile, company: str, review: Review
) -> str:
    """Append the computed coverage table and the readability review beneath the narrative.

    The halves are deliberately separated by a rule. Above it is prose a model wrote; below it
    is arithmetic over the profile and the resume, so a reader can check every claim in the
    prose without having to trust the prose.
    """
    coverage = render_markdown(match_posting(posting, profile, company))
    return f"{narrative.rstrip()}\n\n---\n\n{coverage.rstrip()}\n\n{render_review(review)}"


def _publish(
    applications_dir: Path,
    slug: str,
    documents: Mapping[str, str],
    *,
    export: Callable[[Path], None] | None,
) -> Path:
    """Write ``documents`` into ``applications_dir / slug`` — all of them, or none.

    The run builds into a hidden sibling directory and swaps it in at the end, so a failure
    anywhere below — a write, a render — leaves whatever was there before exactly as it was.
    """
    staging = _staging_dir(applications_dir, slug)
    with contextlib.ExitStack() as unwind:
        # Registered before the first write and cancelled only once everything is on disk, so
        # every failure path below discards the partial folder without an except clause of its
        # own — including the ones raised by code this module does not own.
        unwind.callback(shutil.rmtree, staging, ignore_errors=True)
        for name, text in documents.items():
            _write(staging / name, text)
        if export is not None:
            export(staging)
        unwind.pop_all()

    directory = applications_dir / slug
    _swap(staging, directory)
    return directory


def _staging_dir(applications_dir: Path, slug: str) -> Path:
    """Create the hidden sibling directory this run builds into."""
    try:
        applications_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=applications_dir))
    except OSError as exc:
        msg = f"cannot write to {applications_dir}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def _write(path: Path, text: str) -> None:
    """Write one generated document, reporting a filesystem problem as one clean line."""
    try:
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write {path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def _export(directory: Path) -> None:
    """Render the resume and the cover letter, each single-column."""
    _export_resume(directory)
    build(directory / COVER_LETTER_FILE, layout=Layout.ATS)


def _export_resume(directory: Path) -> None:
    """Render the resume alone, in the single-column layout that serves parsers and people."""
    build(directory / RESUME_FILE, layout=Layout.ATS)


def _swap(staging: Path, directory: Path) -> None:
    """Put the finished ``staging`` directory in place of ``directory``.

    A rename cannot land on a non-empty target, so re-tailoring the same job removes the old
    folder first. The window that opens is microseconds wide, and ``staging`` is a sibling on the
    same filesystem, so the rename that follows it does not fail for the reasons a cross-device
    move would.
    """
    try:
        if directory.exists():
            shutil.rmtree(directory)
        staging.replace(directory)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        msg = f"cannot write {directory}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def _files(directory: Path) -> tuple[Path, ...]:
    """Every file in an application folder, in a stable order."""
    return tuple(sorted(path for path in directory.iterdir() if path.is_file()))


def read_raw_documents(raw_dir: Path) -> RawDocuments:
    """Extract text from every readable file in ``raw_dir``.

    Old resumes arrive as ``.pdf`` or ``.docx``, exports and notes as ``.md`` or ``.txt``.
    Anything that yields no text is *reported* rather than dropped: a scanned PDF with no text
    layer and an unsupported format both look identical to a user who was told to drop in
    "anything", and silently building a profile from half their career is the worst outcome
    this function can produce.

    The folder's own ``README.md`` — the instructions that ship with the project — is skipped.
    It is not career history, and feeding it to a model invites the model to write from it.
    """
    documents: dict[str, str] = {}
    skipped: list[str] = []
    if not raw_dir.is_dir():
        return RawDocuments({}, ())
    for path in sorted(raw_dir.iterdir()):
        if not path.is_file() or path.name.startswith(".") or path.name == _RAW_GUIDE:
            continue
        text = _extract(path)
        if text.strip():
            documents[path.name] = text
        else:
            skipped.append(path.name)
    return RawDocuments(documents, tuple(skipped))


def _extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in {".md", ".txt", ".markdown", ".text"}:
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return ""
    return ""


def _extract_pdf(path: Path) -> str:
    """Pull the text layer out of a PDF.

    A PDF that is a scan carries no text layer, so this returns nothing and the caller reports
    the file as unread — which is the truth, and far better than a profile quietly missing the
    resume the user cared most about.
    """
    from pypdf import PdfReader  # noqa: PLC0415 - only needed for this branch
    from pypdf.errors import PyPdfError  # noqa: PLC0415

    # An encrypted, truncated or malformed PDF raises from anywhere in this block, including
    # lazily while pages are read. All of it means the same thing: no text came out.
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (OSError, ValueError, KeyError, PyPdfError):
        return ""
    return "\n".join(page.strip() for page in pages if page.strip())


def _extract_docx(path: Path) -> str:
    # python-docx raises PackageNotFoundError (a ValueError subclass in some versions, an
    # OSError in others) for anything that is not a real .docx — including a renamed PDF.
    from docx import Document as read_docx  # noqa: PLC0415 - only needed for this branch
    from docx.opc.exceptions import PackageNotFoundError  # noqa: PLC0415

    try:
        document = read_docx(str(path))
    except (OSError, ValueError, KeyError, PackageNotFoundError):
        return ""
    parts = [p.text for p in document.paragraphs]
    parts += [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(part.strip() for part in parts if part.strip())
