"""The two things this project generates once the profile exists, and the review both go through.

``general_application`` writes the general resume and the LinkedIn profile into
``applications/general/``; ``tailor_application`` writes a resume and cover letter for one posting
into ``applications/<company>-<role>/``. Between drafting and exporting, both run the same review:

1. The mechanical fixes are applied to the resume (spacing, a missing full stop, a hyphen in a
   date range, a skill listed twice).
2. An editor pass reads every document for readability, held to the same checks as the draft, and
   comes back with the questions only the candidate can answer.
3. Those questions (the writer's, the editor's and the mechanical review's, merged and capped)
   go to the candidate. Answers that give a fact are recorded in the profile, and the documents
   are revised to use them.
4. Only then is anything exported.

Nothing appears in the application folder until every document is written and every export has
succeeded: the run builds into a hidden sibling directory and swaps it in at the end, so a model
failure or a broken render leaves an earlier version of the folder exactly as it was.
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

from resume_tailor.agent import (
    COVER_LETTER,
    LINKEDIN,
    RESUME,
    edit_documents,
    tailor,
    write_general,
)
from resume_tailor.errors import RenderError, ResumeTailorError
from resume_tailor.profile import load
from resume_tailor.render import Layout, build
from resume_tailor.review import (
    Question,
    Review,
    apply_fixes,
    from_findings,
    gather,
    review_resume,
)
from resume_tailor.service.profile import DEFAULT_ANSWERS_PATH, apply_answers

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile.models import Profile
    from resume_tailor.review import Finding
    from resume_tailor.service.profile import Asker, ProfileUpdate, Progress

__all__ = [
    "COVER_LETTER_FILE",
    "DEFAULT_APPLICATIONS_DIR",
    "GENERAL_SLUG",
    "JOB_DESCRIPTION_FILE",
    "LINKEDIN_FILE",
    "RESUME_FILE",
    "Application",
    "general_application",
    "slugify",
    "tailor_application",
]

DEFAULT_APPLICATIONS_DIR = Path("applications")

GENERAL_SLUG = "general"
"""The one application folder that is not a job: the general resume and the LinkedIn profile."""

JOB_DESCRIPTION_FILE = "job-description.md"
RESUME_FILE = "resume.md"
COVER_LETTER_FILE = "cover-letter.md"
LINKEDIN_FILE = "linkedin.md"

_UNASKED = ("no-outcome",)
"""Mechanical questions left to the editor, which asks the ones worth asking in better words."""

_FALLBACK_SLUG = "application"
_MAX_SLUG = 80
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _silent(_: str) -> None:
    """Report progress nowhere: the default for a caller that does not want it."""


@dataclass(frozen=True, slots=True)
class Application:
    """One finished application folder, and what its review found and asked."""

    slug: str
    directory: Path
    files: tuple[Path, ...]
    company: str = ""
    role: str = ""
    fit: str = ""
    """For a tailored application: how strong the match is, in the writer's words."""

    review: Review = field(default_factory=Review)
    """The resume's mechanical review: the fixes applied, and the advice still standing."""

    questions: tuple[Question, ...] = ()
    """What the review asked, or would have asked with someone there to answer."""

    asked: bool = False
    """True when the questions were put to the candidate during the run."""

    update: ProfileUpdate | None = None
    """What the candidate's answers changed in their profile, when they gave any."""

    problems: tuple[str, ...] = ()
    """Steps that failed without stopping the run, e.g. answers that could not be worked in."""


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


def general_application(  # noqa: PLR0913 - one run; every argument is a distinct input
    *,
    profile_path: Path,
    applications_dir: Path,
    model: LanguageModel,
    ask: Asker | None = None,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    export: bool = True,
    progress: Progress = _silent,
) -> Application:
    """Write, review and export the general resume and the LinkedIn profile.

    The folder is always ``applications_dir / GENERAL_SLUG``, replaced whole on every run.
    Without ``ask`` the review's questions are returned unasked on the result.

    Raises:
        ProfileError: the profile is missing or does not validate.
        ModelError: the model could not be reached or returned nothing usable.
        FabricationError: a draft claimed something the profile does not support.
        RenderError: a document could not be written or exported.
    """
    profile = load(profile_path)
    progress("writing the resume and the LinkedIn profile")
    draft = write_general(profile, model, progress=progress)
    reviewed = _review(
        {RESUME: draft.resume, LINKEDIN: draft.linkedin},
        profile,
        model,
        steps=_Steps(profile_path, answers_path, ask, progress),
    )
    documents = {
        RESUME_FILE: reviewed.documents[RESUME],
        LINKEDIN_FILE: reviewed.documents[LINKEDIN],
    }
    directory = _publish(
        applications_dir, GENERAL_SLUG, documents, export=_export_resume if export else None
    )
    return reviewed.application(GENERAL_SLUG, directory)


def tailor_application(  # noqa: PLR0913 - one run; every argument is a distinct input
    posting: str,
    *,
    profile_path: Path,
    applications_dir: Path,
    model: LanguageModel,
    ask: Asker | None = None,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    export: bool = True,
    progress: Progress = _silent,
) -> Application:
    """Write, review and export a resume and cover letter tailored to ``posting``.

    The writer's own questions (chiefly the posting's must-haves the profile does not support)
    are asked first. Without ``ask`` every question is returned unasked on the result.

    Raises:
        ProfileError: the profile is missing or does not validate.
        ModelError: the model could not be reached or returned nothing usable.
        FabricationError: a draft claimed something the profile does not support.
        DocumentError: a draft does not follow the format contract.
        RenderError: a document could not be written or exported.
    """
    profile = load(profile_path)
    progress("tailoring the resume and the cover letter")
    draft = tailor(posting, profile, model, progress=progress)
    reviewed = _review(
        {RESUME: draft.resume, COVER_LETTER: draft.cover_letter},
        profile,
        model,
        steps=_Steps(profile_path, answers_path, ask, progress),
        first=tuple(Question(text) for text in draft.questions),
    )
    slug = slugify(draft.company, draft.role)
    documents = {
        JOB_DESCRIPTION_FILE: posting,
        RESUME_FILE: reviewed.documents[RESUME],
        COVER_LETTER_FILE: reviewed.documents[COVER_LETTER],
    }
    directory = _publish(applications_dir, slug, documents, export=_export if export else None)
    return reviewed.application(
        slug, directory, company=draft.company, role=draft.role, fit=draft.fit
    )


# --- the review -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Steps:
    """How a review reaches the candidate and their profile."""

    profile_path: Path
    answers_path: Path
    ask: Asker | None
    progress: Progress


@dataclass(frozen=True, slots=True)
class _Reviewed:
    documents: dict[str, str]
    review: Review
    questions: tuple[Question, ...]
    asked: bool = False
    update: ProfileUpdate | None = None
    problems: tuple[str, ...] = ()

    def application(self, slug: str, directory: Path, **job: str) -> Application:
        return Application(
            slug=slug,
            directory=directory,
            files=_files(directory),
            review=self.review,
            questions=self.questions,
            asked=self.asked,
            update=self.update,
            problems=self.problems,
            **job,
        )


def _review(
    documents: Mapping[str, str],
    profile: Profile,
    model: LanguageModel,
    *,
    steps: _Steps,
    first: tuple[Question, ...] = (),
) -> _Reviewed:
    """Fix, edit, ask, and revise: everything between a draft and its export."""
    steps.progress("reviewing: fixing the mechanical problems and editing for readability")
    fixed, applied = apply_fixes(documents[RESUME])
    edited = edit_documents(
        {**documents, RESUME: fixed},
        profile,
        model,
        flagged=_flagged(review_resume(fixed)),
        progress=steps.progress,
    )
    current = dict(edited.documents)
    current[RESUME], more = apply_fixes(current[RESUME])
    applied += more
    questions = gather(
        first,
        (Question(text) for text in edited.questions),
        from_findings(review_resume(current[RESUME]).findings, skip=_UNASKED),
    )
    if steps.ask is None or not questions:
        return _Reviewed(current, _remaining(current, applied), questions)

    update = apply_answers(
        steps.profile_path,
        steps.ask(questions),
        model,
        answers_path=steps.answers_path,
        progress=steps.progress,
    )
    problems: list[str] = []
    if update is not None and update.error:
        problems.append(f"your answers could not be recorded in the profile: {update.error}")
    elif update is not None and update.profile is not None:
        steps.progress("working your answers into the documents")
        try:
            revised = edit_documents(
                current, update.profile, model, answers=update.answers, progress=steps.progress
            )
        except ResumeTailorError as exc:
            problems.append(
                f"your answers are in the profile, but the documents do not use them yet: {exc}"
            )
        else:
            current = dict(revised.documents)
            current[RESUME], more = apply_fixes(current[RESUME])
            applied += more
    return _Reviewed(
        current,
        _remaining(current, applied),
        questions,
        asked=True,
        update=update,
        problems=tuple(problems),
    )


def _remaining(documents: Mapping[str, str], applied: tuple[Finding, ...]) -> Review:
    """Return the resume's review as it will ship: the fixes made, the advice nobody took."""
    return Review(review_resume(documents[RESUME]).findings, applied)


def _flagged(review: Review) -> str:
    """Render what the mechanical review found as the list the editor works through."""
    return "\n".join(
        f"- line {finding.line}: {finding.rule}: {finding.message}"
        + (f' ("{finding.text}")' if finding.text else "")
        for finding in (*review.advice, *review.questions)
    )


# --- writing the folder ---------------------------------------------------------------------------
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

    A rename cannot land on a non-empty target, so regenerating the same folder removes the old
    one first. The window that opens is microseconds wide, and ``staging`` is a sibling on the
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
