"""The two things this project generates once the profile exists, and the review both go through.

``general_application`` writes the general resume and the LinkedIn profile into
``output/general/``; ``tailor_application`` writes a resume and cover letter for one posting into
``output/applications/<company>-<role>/``. Between drafting and exporting, both run the same review:

1. The mechanical fixes are applied to the resume (spacing, a missing full stop, a hyphen in a
   date range, a skill listed twice).
2. An editor pass reads every document for readability, held to the same checks as the draft, and
   comes back with the questions only the candidate can answer. For a tailored application the
   editor sees the posting too, so the edit keeps to what the documents were tailored for.
3. Those questions (the writer's, the editor's and the mechanical review's, merged and capped)
   go to the candidate. Answers that give a fact are recorded in the profile, and the documents
   are revised to use them.
4. Only then is anything exported.

Nothing appears in the application folder until every document is written and every export has
succeeded: the run builds into a hidden sibling directory and swaps it in at the end, so a model
failure or a broken render leaves an earlier version of the folder exactly as it was. Nor is an
earlier version ever deleted. The folder a run replaces moves, hand edits and all, into
``output/backups/``; and a different posting that happens to share its company and role with an
earlier application gets a folder of its own (``<company>-<role>-2``) instead of replacing it.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from resume_tailor.paths import APPLICATIONS_FOLDER, BACKUPS_FOLDER, GENERAL_FOLDER, OUTPUT_DIR
from resume_tailor.profile import load
from resume_tailor.render import Layout, build
from resume_tailor.render.pdf import NO_BROWSER
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
    from resume_tailor.render import Artifact
    from resume_tailor.review import Finding
    from resume_tailor.service.profile import Asker, ProfileUpdate, Progress

__all__ = [
    "COVER_LETTER_FILE",
    "DEFAULT_OUTPUT_DIR",
    "GENERAL_SLUG",
    "JOB_DESCRIPTION_FILE",
    "LINKEDIN_FILE",
    "RESUME_FILE",
    "Application",
    "general_application",
    "slugify",
    "tailor_application",
]

DEFAULT_OUTPUT_DIR = OUTPUT_DIR

GENERAL_SLUG = GENERAL_FOLDER
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

type _Export = Callable[[Path], list[Artifact]]
"""Render the documents written into a folder, returning every file the render produced."""


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
    """What the candidate's answers changed in their profile, when they changed anything."""

    backup: Path | None = None
    """Where the earlier version of this folder went, under ``output/backups/``, when there was
    one: a run never deletes it."""

    problems: tuple[str, ...] = ()
    """What the candidate needs to know that did not stop the run, one sentence each: a step that
    failed (answers not worked in, a PDF no browser could print), where the earlier version of the
    folder went, and why a tailored application did not get the folder its name would give it."""


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
    output_dir: Path,
    model: LanguageModel,
    ask: Asker | None = None,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    export: bool = True,
    progress: Progress = _silent,
) -> Application:
    """Write, review and export the general resume and the LinkedIn profile.

    The folder is always ``output_dir / GENERAL_SLUG``, replaced whole on every run; the version
    it replaces moves into ``output_dir / "backups"``. Without ``ask`` the review's questions are
    returned unasked on the result.

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
    published = _publish(
        output_dir,
        GENERAL_SLUG,
        documents,
        backups=output_dir / BACKUPS_FOLDER,
        export=_export_resume if export else None,
    )
    return reviewed.application(published)


def tailor_application(  # noqa: PLR0913 - one run; every argument is a distinct input
    posting: str,
    *,
    profile_path: Path,
    output_dir: Path,
    model: LanguageModel,
    ask: Asker | None = None,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    export: bool = True,
    progress: Progress = _silent,
) -> Application:
    """Write, review and export a resume and cover letter tailored to ``posting``.

    The folder is ``output_dir / "applications" / <company>-<role>``, named from the posting. A
    rerun for the same posting replaces it, and the version it replaces moves into
    ``output_dir / "backups" / "applications"``. A different posting that gets the same name goes
    to ``<company>-<role>-2`` (or ``-3``, and so on) instead, so it never replaces another
    application. The writer's own questions (chiefly the posting's must-haves the profile does not
    support) are asked first. Without ``ask`` every question is returned unasked on the result.

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
        posting=posting,
    )
    applications = output_dir / APPLICATIONS_FOLDER
    named = slugify(draft.company, draft.role)
    slug = _slug_for(applications, named, posting)
    documents = {
        JOB_DESCRIPTION_FILE: posting,
        RESUME_FILE: reviewed.documents[RESUME],
        COVER_LETTER_FILE: reviewed.documents[COVER_LETTER],
    }
    published = _publish(
        applications,
        slug,
        documents,
        backups=output_dir / BACKUPS_FOLDER / APPLICATIONS_FOLDER,
        export=_export if export else None,
    )
    taken = () if slug == named else (_elsewhere(applications / named, published.directory),)
    return reviewed.application(
        published, taken=taken, company=draft.company, role=draft.role, fit=draft.fit
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
class _Published:
    """Where a run's documents landed, what they replaced, and which PDFs fell back to HTML."""

    directory: Path
    backup: Path | None = None
    unprinted: tuple[Artifact, ...] = ()

    @property
    def problems(self) -> tuple[str, ...]:
        """Say where the earlier version went, and which PDF each printable HTML stands in for."""
        kept = (
            (f"the previous version of {self.directory} is kept in {self.backup}",)
            if self.backup is not None
            else ()
        )
        return (*kept, *(_unprinted(artifact) for artifact in self.unprinted))


@dataclass(frozen=True, slots=True)
class _Reviewed:
    documents: dict[str, str]
    review: Review
    questions: tuple[Question, ...]
    asked: bool = False
    update: ProfileUpdate | None = None
    problems: tuple[str, ...] = ()

    def application(
        self, published: _Published, *, taken: tuple[str, ...] = (), **job: str
    ) -> Application:
        return Application(
            slug=published.directory.name,
            directory=published.directory,
            files=_files(published.directory),
            review=self.review,
            questions=self.questions,
            asked=self.asked,
            update=self.update,
            backup=published.backup,
            problems=(*self.problems, *published.problems, *taken),
            **job,
        )


def _review(  # noqa: PLR0913 - one step; every argument is a distinct input
    documents: Mapping[str, str],
    profile: Profile,
    model: LanguageModel,
    *,
    steps: _Steps,
    first: tuple[Question, ...] = (),
    posting: str = "",
) -> _Reviewed:
    """Fix, edit, ask, and revise: everything between a draft and its export.

    ``posting`` is the job a tailored application is for. Both editing passes see it, so neither
    undoes the tailoring it cannot otherwise see the reason for.
    """
    steps.progress("reviewing: fixing the mechanical problems and editing for readability")
    fixed, applied = apply_fixes(documents[RESUME])
    edited = edit_documents(
        {**documents, RESUME: fixed},
        profile,
        model,
        flagged=_flagged(review_resume(fixed)),
        posting=posting,
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
    # An update that failed carries its own error, which is reported with it, so it adds nothing
    # here; one that changed nothing comes back as None, and needs no revision either.
    problems: list[str] = []
    if update is not None and update.profile is not None:
        steps.progress("working your answers into the documents")
        try:
            revised = edit_documents(
                current,
                update.profile,
                model,
                answers=update.answers,
                posting=posting,
                progress=steps.progress,
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


# --- naming the folder ----------------------------------------------------------------------------
def _slug_for(parent: Path, slug: str, posting: str) -> str:
    """Return the folder name for ``posting``: ``slug``, unless that holds a different posting.

    A rerun for the same posting replaces its own folder. A different posting that produces the
    same company and role (two teams hiring for one title) gets the first free name after it,
    ``slug-2``, ``slug-3`` and so on, or the one of those that already holds this posting.
    """
    candidate, number = slug, 1
    while (parent / candidate).exists() and not _holds(parent / candidate, posting):
        number += 1
        candidate = f"{slug}-{number}"
    return candidate


def _elsewhere(taken: Path, directory: Path) -> str:
    """Say why a tailored application is not in the folder its company and role name."""
    return (
        f"{taken} holds the application for a different posting with the same company and "
        f"role, so this one is in {directory} instead"
    )


def _holds(folder: Path, posting: str) -> bool:
    """Report whether ``folder`` is the application for ``posting``, going by the posting it kept.

    A folder whose posting cannot be read (removed, or not a folder at all) is not known to be
    this application, so it is never the one replaced.
    """
    try:
        kept = (folder / JOB_DESCRIPTION_FILE).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    return kept.strip() == posting.strip()


# --- writing the folder ---------------------------------------------------------------------------
def _publish(
    parent: Path,
    slug: str,
    documents: Mapping[str, str],
    *,
    backups: Path,
    export: _Export | None,
) -> _Published:
    """Write ``documents`` into ``parent / slug``: all of them, or none.

    The run builds into a hidden sibling directory and swaps it in at the end, so a failure
    anywhere below (a write, a render) leaves whatever was there before exactly as it was. The
    folder the swap replaces moves into ``backups``.
    """
    staging = _staging_dir(parent, slug)
    with contextlib.ExitStack() as unwind:
        # Registered before the first write and cancelled only once everything is on disk, so
        # every failure path below discards the partial folder without an except clause of its
        # own — including the ones raised by code this module does not own.
        unwind.callback(shutil.rmtree, staging, ignore_errors=True)
        for name, text in documents.items():
            _write(staging / name, text)
        artifacts = export(staging) if export is not None else []
        unwind.pop_all()

    directory = parent / slug
    backup = _swap(staging, directory, backups)
    unprinted = tuple(artifact for artifact in artifacts if not artifact.ok)
    return _Published(directory, backup, unprinted)


def _staging_dir(parent: Path, slug: str) -> Path:
    """Create the hidden sibling directory this run builds into.

    ``mkdtemp`` makes it readable by its owner alone, and it keeps that mode once swapped into
    place: the folder holds the user's career, so nobody else on the machine needs to read it.
    """
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=parent))
    except OSError as exc:
        msg = f"cannot write to {parent}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def _write(path: Path, text: str) -> None:
    """Write one generated document, reporting a filesystem problem as one clean line."""
    try:
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write {path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def _export(directory: Path) -> list[Artifact]:
    """Render the resume and the cover letter, each single-column."""
    return [*_export_resume(directory), *build(directory / COVER_LETTER_FILE, layout=Layout.ATS)]


def _export_resume(directory: Path) -> list[Artifact]:
    """Render the resume alone, in the single-column layout that serves parsers and people."""
    return build(directory / RESUME_FILE, layout=Layout.ATS)


def _unprinted(fallback: Artifact) -> str:
    """Say which PDF a printable HTML stands in for, why, and how to finish it by hand."""
    pdf, html = fallback.path.with_suffix(".pdf").name, fallback.path.name
    if fallback.reason == NO_BROWSER:
        return (
            f"{pdf} was not made: no browser that can print one (Chrome, Edge, Brave or "
            f"Chromium) is installed. Open {html} in a browser and print it to PDF, or install "
            f"Google Chrome and run this again."
        )
    return (
        f"{pdf} was not made: the browser could not print it. Open {html} in a browser and "
        f"print it to PDF."
    )


def _swap(staging: Path, directory: Path, backups: Path) -> Path | None:
    """Put the finished ``staging`` directory in place of ``directory``, and return the backup.

    The folder already there is never deleted. It is renamed into ``backups`` first, under its own
    name and the time, so hand edits and any file added beside the generated ones survive the run.
    If the rename of ``staging`` then fails, the old folder is renamed back, so it is never left
    half replaced; if that rename fails too, the error names the backup that holds it.
    """
    backup = _set_aside(staging, directory, backups) if directory.exists() else None
    try:
        staging.replace(directory)
    except OSError as exc:
        msg = f"cannot write {directory}: {exc.strerror or exc}"
        if backup is not None:
            try:
                backup.replace(directory)
            except OSError:
                msg += f"; the previous version is in {backup}"
        shutil.rmtree(staging, ignore_errors=True)
        raise RenderError(msg) from exc
    return backup


def _set_aside(staging: Path, directory: Path, backups: Path) -> Path:
    """Move the earlier version of ``directory`` into ``backups``, and return where it went.

    A version that cannot be kept is not replaced: the new one is discarded instead, and the
    error says why.
    """
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    backup = backups / f"{directory.name}.{stamp}"
    try:
        backups.mkdir(parents=True, exist_ok=True)
        directory.replace(backup)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        msg = (
            f"cannot keep the previous version of {directory} in {backups}, so it was left as "
            f"it was and nothing new was written: {exc.strerror or exc}"
        )
        raise RenderError(msg) from exc
    return backup


def _files(directory: Path) -> tuple[Path, ...]:
    """Every file in an application folder, in a stable order."""
    return tuple(sorted(path for path in directory.iterdir() if path.is_file()))
