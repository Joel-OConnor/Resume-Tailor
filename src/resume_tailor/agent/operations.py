"""The two model-driven operations, and the loop that refuses to trust the model.

Nothing here believes a reply. A tailored resume is accepted only once the document parser accepts
its format and the verifier finds no claim the profile cannot support; generated profile YAML only
once the profile loader validates it. A rejected reply goes back with the *specific* violations
attached, because a generic "try again" returns the same answer with different adjectives.

When the attempts run out the operation raises rather than returning its best effort. That is the
point of the module: "never fabricates" is a property the caller gets from the checks, not a hope
about the prompt, so there is no path here that writes a resume with an invented claim on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.agent import prompts
from resume_tailor.documents import parse
from resume_tailor.errors import DocumentError, FabricationError, ModelError, ProfileError
from resume_tailor.profile import loads
from resume_tailor.verify import format_violations, verify_resume
from resume_tailor.verify.source import scan

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from resume_tailor.errors import ResumeTailorError
    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile.models import Profile
    from resume_tailor.review import Review

__all__ = ["RefineResult", "TailorResult", "Usage", "build_profile", "refine_resume", "tailor"]


@dataclass(frozen=True, slots=True)
class Usage:
    """What one operation cost, summed over every attempt it took."""

    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class TailorResult:
    """One tailored application: the four documents, plus the job they were written for."""

    resume: str
    """Resume Markdown that parses and carries no claim the profile cannot support."""

    fit_report: str
    cover_letter: str
    linkedin: str
    company: str
    role: str
    usage: Usage


def tailor(
    posting: str, profile: Profile, model: LanguageModel, *, max_attempts: int = 3
) -> TailorResult:
    """Write a tailored application for ``posting`` from ``profile``.

    Raises:
        FabricationError: if the last attempt still claimed something ``profile`` cannot support.
        ModelError: if no attempt produced a usable answer for any other reason.
    """

    def check(text: str) -> _Draft | _Rejection:
        return _check_draft(text, profile)

    ask = _Ask(
        system=prompts.TAILOR_SYSTEM,
        prompt=prompts.tailor_prompt(posting, profile),
        artefact="the tailored resume",
        truncated=_TRUNCATED_RESUME,
    )
    draft, usage = _generate(model, ask, check=check, max_attempts=max_attempts)
    return TailorResult(
        resume=draft.resume,
        fit_report=draft.fit_report,
        cover_letter=draft.cover_letter,
        linkedin=draft.linkedin,
        company=draft.company,
        role=draft.role,
        usage=usage,
    )


@dataclass(frozen=True, slots=True)
class RefineResult:
    """An edited resume: the same facts, better read, plus what only the candidate can add."""

    resume: str
    questions: tuple[str, ...]
    usage: Usage


def refine_resume(
    resume: str, profile: Profile, review: Review, model: LanguageModel, *, max_attempts: int = 3
) -> RefineResult:
    """Have the model edit ``resume`` for readability without changing a fact.

    The edit is held to three checks: it must still parse, it must keep every ``### `` entry in
    place, and it must claim nothing ``profile`` does not support — the same verifier that
    guards a tailored draft, because an editor that "clarifies" a number has invented one.

    Raises:
        FabricationError: if the last attempt still altered or invented a claim.
        ModelError: if no attempt produced a usable edit for any other reason.
    """

    def check(text: str) -> _Edited | _Rejection:
        return _check_edited(text, resume, profile)

    ask = _Ask(
        system=prompts.REFINE_SYSTEM,
        prompt=prompts.refine_prompt(resume, profile, review),
        artefact="the edited resume",
        truncated=_TRUNCATED_RESUME,
    )
    edited, usage = _generate(model, ask, check=check, max_attempts=max_attempts)
    return RefineResult(edited.resume, edited.questions, usage)


def build_profile(
    documents: Mapping[str, str], model: LanguageModel, *, max_attempts: int = 3
) -> tuple[str, Usage]:
    """Build master-profile YAML from ``documents``, a mapping of filename to extracted text.

    The YAML is returned rather than written: what a caller does with it — diff it against an
    existing profile, show it for review, save it — is not this module's decision.

    Raises:
        ModelError: if no attempt produced YAML that :func:`resume_tailor.profile.loads` accepts.
    """
    ask = _Ask(
        system=prompts.PROFILE_SYSTEM,
        prompt=prompts.profile_prompt(documents),
        artefact="the master profile",
        truncated=_TRUNCATED_PROFILE,
    )
    return _generate(model, ask, check=_check_profile, max_attempts=max_attempts)


# --- the retry loop -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Ask:
    """One thing to get from a model: what to say, and what to call it when it never arrives."""

    system: str
    prompt: str
    artefact: str
    truncated: _Rejection
    """How to retry after a cut-off reply — the right advice differs per operation."""


@dataclass(frozen=True, slots=True)
class _Rejection:
    """Why an answer cannot be used, in the words the model is retried with."""

    feedback: str
    fabricated: bool = False
    """True when the answer claimed something the profile cannot support, not merely malformed."""


_TRUNCATED_RESUME = _Rejection(
    "Your previous answer stopped mid-document because it hit the length limit. A resume that is "
    "missing its last section is worse than a shorter one: cut the least relevant content and "
    "return every section complete."
)
"""A cut-off reply is a failure, not a short answer: it reads as plausible and has no ending."""

_TRUNCATED_PROFILE = _Rejection(
    "Your previous answer stopped mid-file because it hit the length limit. Do not drop roles, "
    "highlights or technologies to fit — the profile is the only record of them, and tailoring "
    "can never surface what is missing here. Write the same content more compactly instead: one "
    "line per highlight, no commentary, no blank lines between entries."
)
"""Truncating a *profile* loses career history for good, so the advice is the opposite one."""


def _generate[T](
    model: LanguageModel,
    ask: _Ask,
    *,
    check: Callable[[str], T | _Rejection],
    max_attempts: int,
) -> tuple[T, Usage]:
    """Ask ``model`` until ``check`` accepts the answer, retrying with each specific rejection."""
    prompt = ask.prompt
    input_tokens = 0
    output_tokens = 0
    for attempt in range(1, max_attempts + 1):
        reply = model.complete(ask.system, prompt)
        input_tokens += reply.input_tokens
        output_tokens += reply.output_tokens
        outcome = ask.truncated if reply.truncated else check(reply.text)
        if not isinstance(outcome, _Rejection):
            return outcome, Usage(input_tokens, output_tokens, attempt)
        if attempt == max_attempts:
            raise _exhausted(ask.artefact, outcome, attempt)
        prompt = prompts.retry_prompt(ask.prompt, outcome.feedback)
    # Only reachable when the loop never ran, which no sane caller asks for.
    msg = f"max_attempts must be at least 1, got {max_attempts}"
    raise ValueError(msg)


def _exhausted(artefact: str, rejection: _Rejection, attempts: int) -> ResumeTailorError:
    """Build the error that ends a run, carrying the last rejection so it can be acted on."""
    plural = "" if attempts == 1 else "s"
    msg = (
        f"{artefact} still failed its checks after {attempts} attempt{plural}:"
        f"\n{rejection.feedback}"
    )
    if rejection.fabricated:
        return FabricationError(msg)
    return ModelError(msg)


# --- what makes an answer acceptable --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Draft:
    """A tailoring answer that passed every check."""

    company: str
    role: str
    resume: str
    fit_report: str
    cover_letter: str
    linkedin: str


def _check_draft(text: str, profile: Profile) -> _Draft | _Rejection:
    """Accept a tailoring answer only if it is complete, parses, and claims nothing invented."""
    sections = _split_sections(text)
    if missing := [name for name in prompts.SECTIONS if not sections.get(name)]:
        listed = ", ".join(missing)
        return _Rejection(
            f"The answer is missing these sections, or left them empty: {listed}. Return all "
            f"{len(prompts.SECTIONS)} sections, each opened by its own delimiter line."
        )

    resume = _unfence(sections["RESUME"])
    letter = _unfence(sections["COVER LETTER"])
    # Both go through the renderer, so both have to parse now rather than at export time.
    for label, source in (("resume", resume), ("cover letter", letter)):
        try:
            parse(source)
        except DocumentError as exc:
            return _Rejection(f"The {label} does not follow the format contract: {exc}")

    verdict = verify_resume(resume, profile)
    if not verdict.ok:
        return _Rejection(format_violations(verdict), fabricated=True)

    return _Draft(
        company=_one_line(sections["COMPANY"]),
        role=_one_line(sections["ROLE"]),
        resume=resume,
        fit_report=_unfence(sections["FIT REPORT"]),
        cover_letter=letter,
        linkedin=_unfence(sections["LINKEDIN"]),
    )


@dataclass(frozen=True, slots=True)
class _Edited:
    """An editing answer that passed every check."""

    resume: str
    questions: tuple[str, ...]


_NO_QUESTIONS = frozenset({"none", "nothing", "n/a", "no questions"})


def _check_edited(text: str, original: str, profile: Profile) -> _Edited | _Rejection:
    """Accept an edit only if it parses, keeps every entry, and claims nothing new."""
    sections = _split_sections(text)
    if missing := [name for name in prompts.REFINE_SECTIONS if not sections.get(name)]:
        listed = ", ".join(missing)
        return _Rejection(
            f"The answer is missing these sections, or left them empty: {listed}. Return both "
            f"sections, each opened by its own delimiter line."
        )
    resume = _unfence(sections["RESUME"])
    try:
        parse(resume)
    except DocumentError as exc:
        return _Rejection(f"The resume does not follow the format contract: {exc}")
    if _entries(resume) != _entries(original):
        kept = "; ".join(_entries(original))
        return _Rejection(
            f"The edit changed the ### entries. Keep every role and degree heading exactly as "
            f"it was, in the same order: {kept}"
        )
    verdict = verify_resume(resume, profile)
    if not verdict.ok:
        return _Rejection(format_violations(verdict), fabricated=True)
    return _Edited(resume, _questions(sections["QUESTIONS"]))


def _entries(markdown: str) -> tuple[str, ...]:
    """Every ``### `` heading in the document, in order."""
    return tuple(entry.title for entry in scan(markdown).entries)


def _questions(text: str) -> tuple[str, ...]:
    """Read the QUESTIONS section as one question per line, dropping a "none"."""
    lines = (line.strip().lstrip("-*• ").strip() for line in text.splitlines())
    return tuple(
        line for line in lines if line and line.casefold().rstrip(".") not in _NO_QUESTIONS
    )


def _check_profile(text: str) -> str | _Rejection:
    """Accept generated YAML only if the profile loader validates it."""
    source = _unfence(text)
    try:
        loads(source)
    except ProfileError as exc:
        return _Rejection(f"The YAML is not a valid master profile: {exc}")
    return source


# --- reading a reply ------------------------------------------------------------------------------
_MARKER = re.compile(r"^=====[ \t]*(?P<name>[A-Z][A-Z ]*[A-Z])[ \t]*=====[ \t]*$", re.MULTILINE)
# A whole answer wrapped in one fence, which models do to anything that looks like a file. An
# inner fence is left alone: `$` anchors this at the end of the text, not the end of a line.
_FENCE = re.compile(r"^```[^\n]*\n(?P<body>.*?)\n```$", re.DOTALL)
_ORNAMENT = "#*_` "


def _split_sections(text: str) -> dict[str, str]:
    """Split a delimited answer into ``{section name: body}``.

    Each body runs to the next delimiter, so anything the model says before the first one — the
    "Certainly! Here is your resume" it was told not to write — is dropped rather than printed.
    """
    found = list(_MARKER.finditer(text))
    ends = [match.start() for match in found[1:]] + [len(text)]
    return {
        match["name"].strip(): text[match.end() : end].strip()
        for match, end in zip(found, ends, strict=True)
    }


def _unfence(text: str) -> str:
    """Strip a code fence the model wrapped a whole section in."""
    body = text.strip()
    if match := _FENCE.match(body):
        return match["body"].strip()
    return body


def _one_line(text: str) -> str:
    """Reduce a one-value section to its first line, without any Markdown the model dressed it in.

    Callers reach here only for a section already known to be non-empty.
    """
    return text.splitlines()[0].strip(_ORNAMENT).strip()
