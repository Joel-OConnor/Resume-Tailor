"""The model operations that write documents, and what every document must pass to be kept.

Three writers share one standard: the general resume with its LinkedIn profile, the tailored
resume with its cover letter, and the editor that reads any of them a second time. A document is
accepted only when:

* it follows its format contract: the resume and the cover letter parse, and the LinkedIn profile
  keeps LinkedIn's sections and limits and gives every role in the profile its own entry, because
  LinkedIn is the whole record;
* it claims nothing the profile cannot support: :func:`resume_tailor.verify.verify_resume` runs on
  every document, the cover letter and the LinkedIn profile included, because an invented figure
  in a letter is as much a lie as one on the resume;
* an edit keeps every ``### `` entry of the resume and the LinkedIn profile: every role, degree
  and certification, with the same heading, in the same order. Working in facts the candidate has
  just supplied may add an entry, and may bring a heading up to date with what the answers
  complete or correct, but never drops or reorders one.

Every failing document is reported in the same retry, so one attempt can fix all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from resume_tailor.agent import prompts
from resume_tailor.agent.loop import (
    TRUNCATED_DOCUMENTS,
    Ask,
    Rejection,
    Usage,
    generate,
    missing_sections,
    one_line,
    questions,
    split_sections,
    unfence,
)
from resume_tailor.agent.prompts import COVER_LETTER, LINKEDIN, QUESTIONS, RESUME
from resume_tailor.documents import parse
from resume_tailor.errors import DocumentError
from resume_tailor.match.tokens import normalise
from resume_tailor.review import check_linkedin
from resume_tailor.verify import format_violations, verify_resume
from resume_tailor.verify.source import Area, scan

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from resume_tailor.agent.loop import Progress
    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile.models import Profile
    from resume_tailor.review import Answer

__all__ = [
    "EditResult",
    "GeneralResult",
    "TailorResult",
    "check_documents",
    "edit_documents",
    "tailor",
    "write_general",
]


@dataclass(frozen=True, slots=True)
class GeneralResult:
    """The general resume and the LinkedIn profile, both checked against the profile."""

    resume: str
    linkedin: str
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class TailorResult:
    """One tailored application: the two documents, the job they are for, and what to ask."""

    company: str
    role: str
    fit: str
    """Two to four sentences for the candidate on how strong the match is."""

    resume: str
    cover_letter: str
    questions: tuple[str, ...] = ()
    """Must-haves the profile does not support, and facts that would strengthen the application."""

    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class EditResult:
    """Documents after an editing pass, and what the editor wants to ask the candidate."""

    documents: dict[str, str]
    questions: tuple[str, ...] = ()
    usage: Usage = field(default_factory=Usage)


def write_general(
    profile: Profile,
    model: LanguageModel,
    *,
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> GeneralResult:
    """Write the general resume and the LinkedIn profile from ``profile``.

    Raises:
        FabricationError: if the last attempt still claimed something ``profile`` cannot support.
        ModelError: if no attempt produced usable documents for any other reason.
    """

    def check(text: str) -> GeneralResult | Rejection:
        sections = split_sections(text)
        if rejection := missing_sections(sections, prompts.GENERAL_SECTIONS):
            return rejection
        documents = {kind: unfence(sections[kind]) for kind in prompts.GENERAL_SECTIONS}
        if rejection := check_documents(documents, profile):
            return rejection
        return GeneralResult(documents[RESUME], documents[LINKEDIN])

    ask = Ask(
        system=prompts.GENERAL_SYSTEM,
        prompt=prompts.general_prompt(profile),
        artefact="the general resume and LinkedIn profile",
        truncated=TRUNCATED_DOCUMENTS,
    )
    result, usage = generate(model, ask, check=check, max_attempts=max_attempts, progress=progress)
    return GeneralResult(result.resume, result.linkedin, usage)


def tailor(
    posting: str,
    profile: Profile,
    model: LanguageModel,
    *,
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> TailorResult:
    """Write a tailored resume and cover letter for ``posting`` from ``profile``.

    Raises:
        FabricationError: if the last attempt still claimed something ``profile`` cannot support.
        ModelError: if no attempt produced a usable answer for any other reason.
    """

    def check(text: str) -> TailorResult | Rejection:
        sections = split_sections(text)
        if rejection := missing_sections(sections, prompts.TAILOR_SECTIONS):
            return rejection
        documents = {kind: unfence(sections[kind]) for kind in (RESUME, COVER_LETTER)}
        if rejection := check_documents(documents, profile):
            return rejection
        return TailorResult(
            company=one_line(sections["COMPANY"]),
            role=one_line(sections["ROLE"]),
            fit=unfence(sections["FIT"]),
            resume=documents[RESUME],
            cover_letter=documents[COVER_LETTER],
            questions=questions(sections[QUESTIONS]),
        )

    ask = Ask(
        system=prompts.TAILOR_SYSTEM,
        prompt=prompts.tailor_prompt(posting, profile),
        artefact="the tailored resume and cover letter",
        truncated=TRUNCATED_DOCUMENTS,
    )
    result, usage = generate(model, ask, check=check, max_attempts=max_attempts, progress=progress)
    return TailorResult(
        company=result.company,
        role=result.role,
        fit=result.fit,
        resume=result.resume,
        cover_letter=result.cover_letter,
        questions=result.questions,
        usage=usage,
    )


def edit_documents(  # noqa: PLR0913 - one pass; every argument is a distinct input
    documents: Mapping[str, str],
    profile: Profile,
    model: LanguageModel,
    *,
    flagged: str = "",
    answers: Sequence[Answer] = (),
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> EditResult:
    """Have the model edit ``documents`` for readability without changing a fact.

    ``documents`` maps a kind (:data:`~resume_tailor.agent.prompts.RESUME`, ``COVER_LETTER`` or
    ``LINKEDIN``) to its Markdown. Without ``answers`` this is the review: the editor acts on
    ``flagged`` (what the mechanical review found) and returns its questions for the candidate.
    With ``answers`` it is the revision after the review: the documents take in what the candidate
    said, which ``profile`` must already record, and no further questions come back.

    Raises:
        FabricationError: if the last attempt still altered or invented a claim.
        ModelError: if no attempt produced a usable edit for any other reason.
    """
    revising = bool(answers)
    expected = prompts.edit_sections(documents, questions=not revising)
    # A revision's profile already records the answers, so a heading they correct no longer
    # verifies against it. Those are the headings the revision has to rewrite.
    outdated = (
        {kind: _outdated(text, profile) for kind, text in documents.items()} if revising else None
    )

    def check(text: str) -> EditResult | Rejection:
        sections = split_sections(text)
        if rejection := missing_sections(sections, expected):
            return rejection
        edited = {kind: unfence(sections[kind]) for kind in documents}
        found = check_documents(edited, profile)
        if moved := _moved_entries(documents, edited, outdated):
            return Rejection(
                f"{moved}\n\n{found.feedback}" if found else moved,
                fabricated=found is not None and found.fabricated,
            )
        if found:
            return found
        asked = () if revising else questions(sections[QUESTIONS])
        return EditResult(edited, asked)

    ask = Ask(
        system=prompts.EDIT_SYSTEM,
        prompt=prompts.edit_prompt(documents, profile, flagged=flagged, answers=answers),
        artefact="the edited documents",
        truncated=TRUNCATED_DOCUMENTS,
    )
    result, usage = generate(model, ask, check=check, max_attempts=max_attempts, progress=progress)
    return EditResult(result.documents, result.questions, usage)


def check_documents(documents: Mapping[str, str], profile: Profile) -> Rejection | None:
    """Check every document against its format and the profile, reporting all failures at once."""
    found = [
        rejection
        for kind, text in documents.items()
        if (rejection := _check_document(kind, text, profile)) is not None
    ]
    if not found:
        return None
    return Rejection(
        "\n\n".join(rejection.feedback for rejection in found),
        fabricated=any(rejection.fabricated for rejection in found),
    )


def _check_document(kind: str, text: str, profile: Profile) -> Rejection | None:
    label = kind.lower()
    if kind == LINKEDIN:
        if problems := [*check_linkedin(text), *_missing_positions(text, profile)]:
            return Rejection(
                f"The linkedin profile breaks LinkedIn's format: {'; '.join(problems)}."
            )
    else:
        try:
            parse(text)
        except DocumentError as exc:
            return Rejection(f"The {label} does not follow the format contract: {exc}")
    verdict = verify_resume(text, profile)
    if not verdict.ok:
        return Rejection(
            f"The {label} claims what the profile does not support:\n{format_violations(verdict)}",
            fabricated=True,
        )
    return None


def _moved_entries(
    documents: Mapping[str, str],
    edited: Mapping[str, str],
    outdated: Mapping[str, Collection[int]] | None,
) -> str:
    """Say which documents lost, renamed or reordered a ``### `` entry in the edit, if any did.

    The review (``outdated`` is ``None``) must hand back the same entries. A revision works in the
    candidate's answers, which may supply a role or degree and may complete or correct a heading,
    so there the old entries need only survive, in their order, among the new: see :func:`_kept`.
    The verifier still reads every heading the revision writes.
    """
    problems: list[str] = []
    for kind in (RESUME, LINKEDIN):
        if kind not in documents:
            continue
        before, after = _entries(documents[kind]), _entries(edited[kind])
        if before == after or (outdated is not None and _kept(before, after, outdated[kind])):
            continue
        label = "linkedin profile" if kind == LINKEDIN else kind.lower()
        rule = "as it was" if outdated is not None else "exactly as it was"
        allowed = (
            " Add an entry only for a role or degree the answers supply. Change a heading only"
            " where the answers complete or correct it."
            if outdated is not None
            else ""
        )
        problems.append(
            f"The edit changed the {label}'s ### entries. Keep every role and degree heading "
            f"{rule}, in the same order: {'; '.join(before) or 'none'}.{allowed}"
        )
    return "\n\n".join(problems)


def _entries(markdown: str) -> tuple[str, ...]:
    """Every ``### `` heading in the document, in order."""
    return tuple(entry.title for entry in scan(markdown).entries)


def _outdated(markdown: str, profile: Profile) -> frozenset[int]:
    """Return the positions of the ``### `` headings ``profile`` does not support as written."""
    unsupported = {violation.line for violation in verify_resume(markdown, profile).violations}
    entries = scan(markdown).entries
    return frozenset(index for index, entry in enumerate(entries) if entry.line in unsupported)


def _kept(before: Sequence[str], after: Sequence[str], outdated: Collection[int]) -> bool:
    """Return whether every entry of ``before`` is still in ``after``, in the same order.

    An entry is still there when its heading is unchanged or has only gained words, as a degree
    does when the answers give its field. One the answers made untrue (its position is in
    ``outdated``) may be rewritten outright, as a corrected title is. Whatever else ``after`` holds
    is new.
    """
    remaining = iter(after)
    # ``any`` consumes the iterator up to the match, so each entry must come after the last one.
    return all(
        any(index in outdated or _extends(heading, old) for heading in remaining)
        for index, old in enumerate(before)
    )


def _extends(heading: str, old: str) -> bool:
    """Return whether ``heading`` keeps every word of ``old``, in order, adding only words."""
    words = iter(_words(heading))
    return all(word in words for word in _words(old))


# " – " between title and employer, as the formats write it, and the list separators a title can
# hold. normalise() has already folded every dash to "-"; the spaces keep "Full-Stack" whole.
_PARTS = re.compile(r"\s*[,;·|]\s*|\s+-\s+")


def _missing_positions(markdown: str, profile: Profile) -> list[str]:
    """Name every role in ``profile`` that no Experience entry of the LinkedIn profile gives.

    An entry gives a role when one part of its heading names the employer and another the title,
    each read as the verifier reads them, so a shortened name still counts.
    """
    given = [
        [words for part in _PARTS.split(normalise(entry.title)) if (words := _words(part))]
        for entry in scan(markdown).entries
        if entry.area is Area.EXPERIENCE
    ]
    missing = [
        f"{role.title} at {tenure.company}"
        for tenure in profile.experience
        for role in tenure.roles
        if not any(_gives(parts, _words(tenure.company), _words(role.title)) for parts in given)
    ]
    if not missing:
        return []
    return [
        (
            f"the Experience section leaves out {'; '.join(missing)}, and LinkedIn lists every "
            "role in the profile, each as its own ### entry"
        )
    ]


def _gives(parts: list[tuple[str, ...]], company: tuple[str, ...], title: tuple[str, ...]) -> bool:
    """Return whether one of a heading's ``parts`` names ``company`` and another ``title``."""
    return any(
        _within(part, company)
        and any(_within(other, title) for other in parts[:at] + parts[at + 1 :])
        for at, part in enumerate(parts)
    )


def _words(text: str) -> tuple[str, ...]:
    """Reduce text to comparable words, dropping case, punctuation and emphasis."""
    folded = normalise(text).casefold()
    return tuple("".join(c if c.isalnum() else " " for c in folded).split())


def _within(claim: tuple[str, ...], known: tuple[str, ...]) -> bool:
    """Return whether every word of ``claim`` appears, in order and unbroken, inside ``known``."""
    size = len(claim)
    return any(known[at : at + size] == claim for at in range(len(known) - size + 1))
