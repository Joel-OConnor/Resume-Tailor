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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor.agent import tailor
from resume_tailor.errors import RenderError
from resume_tailor.match import match_posting, render_markdown
from resume_tailor.profile import load
from resume_tailor.render import Layout, build

if TYPE_CHECKING:
    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile import Profile

__all__ = [
    "DEFAULT_APPLICATIONS_DIR",
    "Application",
    "check_profile",
    "list_applications",
    "match_only",
    "read_raw_documents",
    "slugify",
    "tailor_application",
]

DEFAULT_APPLICATIONS_DIR = Path("applications")

JOB_DESCRIPTION_FILE = "job-description.md"
RESUME_FILE = "resume.md"
FIT_REPORT_FILE = "fit-report.md"
COVER_LETTER_FILE = "cover-letter.md"
LINKEDIN_FILE = "linkedin.md"

_FALLBACK_SLUG = "application"
_MAX_SLUG = 80
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Application:
    """One application folder: where it is and what it holds."""

    slug: str
    directory: Path
    files: tuple[Path, ...]
    company: str = ""
    role: str = ""


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


def tailor_application(
    posting: str,
    *,
    profile_path: Path,
    applications_dir: Path,
    model: LanguageModel,
    export: bool = True,
) -> Application:
    """Tailor ``posting`` into a complete application folder and report what was written.

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
    slug = slugify(draft.company, draft.role)
    directory = applications_dir / slug
    documents = {
        JOB_DESCRIPTION_FILE: posting,
        RESUME_FILE: draft.resume,
        FIT_REPORT_FILE: _fit_report(draft.fit_report, posting, profile, draft.company),
        COVER_LETTER_FILE: draft.cover_letter,
        LINKEDIN_FILE: draft.linkedin,
    }

    staging = _staging_dir(applications_dir, slug)
    with contextlib.ExitStack() as unwind:
        # Registered before the first write and cancelled only once everything is on disk, so
        # every failure path below discards the partial folder without an except clause of its
        # own — including the ones raised by code this module does not own.
        unwind.callback(shutil.rmtree, staging, ignore_errors=True)
        for name, text in documents.items():
            _write(staging / name, text)
        if export:
            _export(staging)
        unwind.pop_all()

    _swap(staging, directory)
    return Application(
        slug=slug,
        directory=directory,
        files=_files(directory),
        company=draft.company,
        role=draft.role,
    )


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


def _fit_report(narrative: str, posting: str, profile: Profile, company: str) -> str:
    """Append the computed coverage table beneath the model's narrative.

    The two halves are deliberately separated by a rule. Above it is prose a model wrote; below
    it is arithmetic over the profile, so a reader can check every keyword claim in the prose
    without having to trust the prose.
    """
    coverage = render_markdown(match_posting(posting, profile, company))
    return f"{narrative.rstrip()}\n\n---\n\n{coverage}"


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
    """Render the resume in both layouts and the cover letter single-column."""
    build(directory / RESUME_FILE)
    build(directory / COVER_LETTER_FILE, layout=Layout.ATS)


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


def read_raw_documents(raw_dir: Path) -> dict[str, str]:
    """Extract text from every readable file in ``raw_dir``.

    Old resumes arrive as ``.docx``, exports as ``.md`` or ``.txt``. Anything unreadable is
    skipped rather than fatal — a stray ``.DS_Store`` or a PDF should not stop a profile build,
    and the caller reports how many documents were actually understood.
    """
    documents: dict[str, str] = {}
    if not raw_dir.is_dir():
        return documents
    for path in sorted(raw_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        text = _extract(path)
        if text.strip():
            documents[path.name] = text
    return documents


def _extract(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _extract_docx(path)
    if path.suffix.lower() in {".md", ".txt", ".markdown", ".text"}:
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return ""
    return ""


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
