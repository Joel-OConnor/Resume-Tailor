"""Build the master profile from the user's documents, and keep it current as they answer questions.

Building is two model passes and one mechanical one. The first pass drafts the YAML from everything
in ``my-documents/career-history/``; the second refines it (one record per fact, each in the right
place, no noise), held by :func:`resume_tailor.verify.changes.check_refinement` to adding nothing
and losing nothing; then the audit in :func:`resume_tailor.review.review_profile` says what still
needs a look, and the open questions go to the candidate.

Answers are recorded twice, on purpose. They are appended to ``answers.md`` in the same folder,
which is source material like any other document there, so the next full rebuild keeps them. And
they are written straight into ``master-profile.yaml`` by a model held to
:func:`resume_tailor.verify.changes.check_update`, so the documents being reviewed can use them now
rather than after a rebuild.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from resume_tailor.agent import build_profile, refine_profile, update_profile
from resume_tailor.errors import FabricationError, ModelError, ProfileError, RenderError
from resume_tailor.paths import ANSWERS_PATH, BACKUPS_FOLDER, CAREER_HISTORY_DIR, SCHEMA_PATH
from resume_tailor.profile import loads
from resume_tailor.review import Review, from_findings, gather, review_profile
from resume_tailor.verify.changes import describe_changes

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile.models import Profile
    from resume_tailor.review import Answer, Question

__all__ = [
    "DEFAULT_ANSWERS_PATH",
    "DEFAULT_CAREER_DIR",
    "Asker",
    "ProfileBuild",
    "ProfileUpdate",
    "Progress",
    "RawDocuments",
    "apply_answers",
    "build_master_profile",
    "read_raw_documents",
    "record_answers",
    "write_profile",
]

DEFAULT_CAREER_DIR = CAREER_HISTORY_DIR
DEFAULT_ANSWERS_PATH = ANSWERS_PATH
"""Where answers are kept: with the user's documents, as source material for the next rebuild."""

_SCHEMA_COMMENT = "# yaml-language-server: $schema="
_RAW_GUIDE = "README.md"
"""The project's own instructions for the folder, not the user's career history."""

type Asker = Callable[[tuple[Question, ...]], Sequence[Answer]]
"""Put questions to the candidate and return what they answered (blank answers are skips)."""

type Progress = Callable[[str], None]
"""Report what a long-running step is doing, one line at a time."""


def _silent(_: str) -> None:
    """Report progress nowhere: the default for a caller that does not want it."""


@dataclass(frozen=True, slots=True)
class RawDocuments:
    """What a profile build found to read, and what it could not."""

    documents: dict[str, str]
    """Filename to extracted text, for every file that yielded any."""

    skipped: tuple[str, ...] = ()
    """Files that produced no text — an unsupported format, or a PDF that is only a scan."""


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    """What recording the candidate's answers did to their profile."""

    answers: tuple[Answer, ...]
    """The answers that gave a fact; the ones that declined are logged but change nothing."""

    changes: tuple[str, ...] = ()
    """What changed, one line each, computed by comparing the profile before and after."""

    backup: Path | None = None
    profile: Profile | None = None
    """The updated profile; ``None`` when the update failed and the file was left as it was."""

    error: str = ""
    """Why the answers could not be recorded automatically, when they could not."""


@dataclass(frozen=True, slots=True)
class ProfileBuild:
    """Everything a profile build did, for the caller to report."""

    path: Path
    backup: Path | None
    changes: tuple[str, ...] = ()
    """The refining model's own account of what it merged, moved and dropped."""

    difference: tuple[str, ...] = ()
    """The draft and the refined profile compared: what actually changed, counted."""

    refine_error: str = ""
    """Why refining failed, when it did: the checked draft was written instead."""

    review: Review = field(default_factory=Review)
    """The audit of the profile as written: what still needs a look, and its open questions."""

    questions: tuple[Question, ...] = ()
    update: ProfileUpdate | None = None


def build_master_profile(  # noqa: PLR0913 - one run; every argument is a distinct input
    raw: RawDocuments,
    *,
    out: Path,
    model: LanguageModel,
    force: bool = False,
    ask: Asker | None = None,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    progress: Progress = _silent,
) -> ProfileBuild:
    """Draft, refine and write the master profile from ``raw``, then ask what it could not settle.

    A refinement that fails its checks does not cost the draft: the draft (which the loader has
    validated) is written instead and the failure is reported on the result. At most
    :data:`~resume_tailor.review.MAX_QUESTIONS` open notes are asked, most consequential first;
    the rest stay in ``notes`` for ``resume-tailor profile validate`` to list.

    Raises:
        ProfileError: there is nothing to read, or a profile exists and ``force`` is not set.
        ModelError: the draft could not be produced.
        RenderError: the profile could not be written.
    """
    if not raw.documents:
        msg = "no readable documents to build a profile from"
        raise ProfileError(msg)
    if out.exists() and not force:
        msg = (
            f"{out} already exists. Building would replace it, losing any correction made by "
            f"hand. Re-run with --force to replace it (a timestamped backup is kept)."
        )
        raise ProfileError(msg)

    progress(f"drafting the profile from {len(raw.documents)} document(s)")
    draft, _ = build_profile(raw.documents, model, progress=progress)
    progress("refining it: one record per fact, each in the right place, nothing irrelevant")
    text, error = draft, ""
    changes: tuple[str, ...] = ()
    difference: tuple[str, ...] = ()
    try:
        edit = refine_profile(draft, raw.documents, model, progress=progress)
    except (FabricationError, ModelError) as exc:
        error = str(exc)
    else:
        text, changes = edit.yaml, edit.changes
        difference = describe_changes(loads(draft), edit.profile)
    backup = write_profile(out, text)

    profile = loads(text)
    questions = gather(from_findings(review_profile(profile).findings))
    update = None
    if ask is not None and questions:
        update = apply_answers(
            out,
            ask(questions),
            model,
            answers_path=answers_path,
            progress=progress,
            back_up=False,
        )
        if update is not None and update.profile is not None:
            profile = update.profile
    return ProfileBuild(
        path=out,
        backup=backup,
        changes=changes,
        difference=difference,
        refine_error=error,
        review=review_profile(profile),
        questions=questions,
        update=update,
    )


def apply_answers(  # noqa: PLR0913 - one step; every argument is a distinct input
    profile_path: Path,
    answers: Sequence[Answer],
    model: LanguageModel,
    *,
    answers_path: Path = DEFAULT_ANSWERS_PATH,
    progress: Progress = _silent,
    back_up: bool = True,
) -> ProfileUpdate | None:
    """Record ``answers`` in the answers log and in the profile; ``None`` when none gave a fact.

    A model failure is reported on the result rather than raised: the answers are already safe in
    the log, and whatever the candidate was reviewing can still be finished without them.
    ``back_up=False`` skips the backup, for a profile this same run has only just written.
    """
    given = tuple(answer for answer in answers if answer.text.strip())
    if given:
        record_answers(answers_path, str(profile_path), given)
    facts = tuple(answer for answer in given if answer.substantive)
    if not facts:
        return None
    progress("recording your answers in the profile")
    current = profile_path.read_text(encoding="utf-8-sig")
    try:
        edit = update_profile(current, facts, model, progress=progress)
    except (FabricationError, ModelError) as exc:
        return ProfileUpdate(facts, error=str(exc))
    backup = write_profile(profile_path, edit.yaml, back_up=back_up)
    return ProfileUpdate(
        answers=facts,
        changes=describe_changes(loads(current), edit.profile),
        backup=backup,
        profile=edit.profile,
    )


def record_answers(path: Path, source: str, answers: Sequence[Answer]) -> None:
    """Append ``answers`` to the Q&A log as one dated section."""
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    lines = [f"## {stamp} · {source}", ""]
    for answer in answers:
        about = f' (about: "{answer.question.about}")' if answer.question.about else ""
        lines += [f"- **Q:** {answer.question.text}{about}", f"  **A:** {answer.text}", ""]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        msg = f"cannot write {path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc


def write_profile(path: Path, text: str, *, back_up: bool = True) -> Path | None:
    """Write profile YAML to ``path``, backing up whatever was there; return the backup.

    The YAML gains the ``yaml-language-server`` comment that points an editor at the schema, so
    the file autocompletes and validates as the user corrects it.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = _back_up(path) if back_up else None
        path.write_text(_with_schema(text, path), encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write {path}: {exc.strerror or exc}"
        raise RenderError(msg) from exc
    return backup


def _back_up(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    backup = path.parent / BACKUPS_FOLDER / f"{path.stem}.{stamp}{path.suffix}"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(path, backup)
    return backup


def _with_schema(text: str, path: Path) -> str:
    body = text if text.endswith("\n") else text + "\n"
    if body.lstrip().startswith(_SCHEMA_COMMENT) or not SCHEMA_PATH.is_file():
        return body
    reference = Path(os.path.relpath(SCHEMA_PATH.resolve(), path.parent.resolve())).as_posix()
    return f"{_SCHEMA_COMMENT}{reference}\n{body}"


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
