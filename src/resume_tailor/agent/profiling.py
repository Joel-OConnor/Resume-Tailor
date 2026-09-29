"""The model operations on the master profile: draft it, refine it, and record answers in it.

Every one returns YAML the profile loader has validated, and the last two are also held to the
profile they replace (:mod:`resume_tailor.verify.changes`): refining may merge, move, reword and
drop, but never add a fact or lose one; an update may add only what the candidate's answers state.
YAML is returned rather than written: what a caller does with it (back up the old file, show the
difference, save it) is not this module's decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from resume_tailor.agent import prompts
from resume_tailor.agent.loop import (
    TRUNCATED_PROFILE,
    Ask,
    Rejection,
    Usage,
    generate,
    missing_sections,
    questions,
    split_sections,
    unfence,
)
from resume_tailor.errors import ProfileError
from resume_tailor.profile import loads
from resume_tailor.review import Level, review_profile, said
from resume_tailor.verify.changes import check_refinement, check_update

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from resume_tailor.agent.loop import Progress
    from resume_tailor.llm import LanguageModel
    from resume_tailor.profile.models import Profile
    from resume_tailor.review import Answer

__all__ = ["ProfileEdit", "build_profile", "refine_profile", "update_profile"]


@dataclass(frozen=True, slots=True)
class ProfileEdit:
    """A profile a model rewrote, validated and checked against the version it replaces."""

    yaml: str
    profile: Profile
    changes: tuple[str, ...] = ()
    """The model's own account of what it changed and why, one line each."""

    usage: Usage = field(default_factory=Usage)


def build_profile(
    documents: Mapping[str, str],
    model: LanguageModel,
    *,
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> tuple[str, Usage]:
    """Draft master-profile YAML from ``documents``, a mapping of filename to extracted text.

    Raises:
        ModelError: if no attempt produced YAML that :func:`resume_tailor.profile.loads` accepts.
    """
    ask = Ask(
        system=prompts.PROFILE_SYSTEM,
        prompt=prompts.profile_prompt(documents),
        artefact="the master profile",
        truncated=TRUNCATED_PROFILE,
    )
    return generate(model, ask, check=_check_draft, max_attempts=max_attempts, progress=progress)


def refine_profile(
    draft: str,
    documents: Mapping[str, str],
    model: LanguageModel,
    *,
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> ProfileEdit:
    """Give a drafted profile a second read: one record per fact, in the right place, no noise.

    The model sees the draft, the documents it came from, and the mechanical audit of it. What it
    returns must validate and must keep every fact the draft had while adding none.

    Raises:
        ProfileError: if ``draft`` itself does not validate.
        FabricationError: if the last attempt still added or lost a fact.
        ModelError: if no attempt produced a usable profile for any other reason.
    """
    before = loads(draft)

    def check(text: str) -> ProfileEdit | Rejection:
        sections = split_sections(text)
        if rejection := missing_sections(sections, prompts.REFINE_PROFILE_SECTIONS):
            return rejection
        source = unfence(sections["PROFILE"])
        after = _load(source)
        if isinstance(after, Rejection):
            return after
        if problems := check_refinement(before, after):
            return Rejection(_numbered(problems), fabricated=True)
        return ProfileEdit(source, after, questions(sections["CHANGES"]))

    ask = Ask(
        system=prompts.REFINE_PROFILE_SYSTEM,
        prompt=prompts.refine_profile_prompt(draft, documents, _audit(before)),
        artefact="the refined master profile",
        truncated=TRUNCATED_PROFILE,
    )
    edit, usage = generate(model, ask, check=check, max_attempts=max_attempts, progress=progress)
    return replace(edit, usage=usage)


def update_profile(
    current: str,
    answers: Sequence[Answer],
    model: LanguageModel,
    *,
    max_attempts: int = 3,
    progress: Progress | None = None,
) -> ProfileEdit:
    """Record the candidate's ``answers`` in the profile ``current``, and change nothing else.

    Raises:
        ProfileError: if ``current`` itself does not validate.
        FabricationError: if the last attempt still recorded something no answer states.
        ModelError: if no attempt produced a usable profile for any other reason.
    """
    before = loads(current)
    words = said(answers)

    def check(text: str) -> ProfileEdit | Rejection:
        source = unfence(text)
        after = _load(source)
        if isinstance(after, Rejection):
            return after
        if problems := check_update(before, after, words):
            return Rejection(_numbered(problems), fabricated=True)
        return ProfileEdit(source, after)

    ask = Ask(
        system=prompts.UPDATE_PROFILE_SYSTEM,
        prompt=prompts.update_profile_prompt(current, answers),
        artefact="the updated master profile",
        truncated=TRUNCATED_PROFILE,
    )
    edit, usage = generate(model, ask, check=check, max_attempts=max_attempts, progress=progress)
    return replace(edit, usage=usage)


def _check_draft(text: str) -> str | Rejection:
    """Accept drafted YAML only if the profile loader validates it."""
    source = unfence(text)
    loaded = _load(source)
    return loaded if isinstance(loaded, Rejection) else source


def _load(source: str) -> Profile | Rejection:
    try:
        return loads(source)
    except ProfileError as exc:
        return Rejection(f"The YAML is not a valid master profile: {exc}")


def _audit(profile: Profile) -> str:
    """Render the mechanical audit of a draft as the list the refining prompt carries."""
    return "\n".join(
        f"- {finding.text}: {finding.message}"
        for finding in review_profile(profile).findings
        if finding.level is Level.ADVISE
    )


def _numbered(problems: Iterable[str]) -> str:
    return "\n".join(f"{index}. {problem}" for index, problem in enumerate(problems, start=1))
