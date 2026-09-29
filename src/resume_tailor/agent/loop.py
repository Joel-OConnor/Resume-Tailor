"""The loop that refuses to trust the model, and the helpers that read what it says.

Nothing here believes a reply. Each operation hands :func:`generate` a check, and a reply is
accepted only once that check passes; a rejected reply goes back with the *specific* problems
attached, because a generic "try again" returns the same answer with different adjectives.

When the attempts run out the operation raises rather than returning its best effort. That is the
point of the module: "never fabricates" is a property the caller gets from the checks, not a hope
about the prompt, so there is no path through here that writes an unchecked answer to a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.agent import prompts
from resume_tailor.errors import FabricationError, ModelError

if TYPE_CHECKING:
    from collections.abc import Callable

    from resume_tailor.errors import ResumeTailorError
    from resume_tailor.llm import LanguageModel

__all__ = [
    "TRUNCATED_DOCUMENTS",
    "TRUNCATED_PROFILE",
    "Ask",
    "Progress",
    "Rejection",
    "Usage",
    "generate",
    "missing_sections",
    "one_line",
    "questions",
    "split_sections",
    "unfence",
]


type Progress = Callable[[str], None]
"""Report, one line at a time, what a long-running step is doing."""


@dataclass(frozen=True, slots=True)
class Usage:
    """What one operation cost, summed over every attempt it took."""

    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1

    def __add__(self, other: Usage) -> Usage:
        """Combine the cost of two operations."""
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.attempts + other.attempts,
        )


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why an answer cannot be used, in the words the model is retried with."""

    feedback: str
    fabricated: bool = False
    """True when the answer claimed something the profile cannot support, not merely malformed."""


@dataclass(frozen=True, slots=True)
class Ask:
    """One thing to get from a model: what to say, and what to call it when it never arrives."""

    system: str
    prompt: str
    artefact: str
    truncated: Rejection
    """How to retry after a cut-off reply — the right advice differs per operation."""


TRUNCATED_DOCUMENTS = Rejection(
    "Your previous answer stopped mid-document because it hit the length limit. A document that "
    "is missing its last section is worse than a shorter one: cut the least relevant content and "
    "return every section complete."
)
"""A cut-off reply is a failure, not a short answer: it reads as plausible and has no ending."""

TRUNCATED_PROFILE = Rejection(
    "Your previous answer stopped mid-file because it hit the length limit. Do not drop roles, "
    "highlights or technologies to fit — the profile is the only record of them, and no resume "
    "can surface what is missing here. Write the same content more compactly instead: one line "
    "per highlight, no commentary, no blank lines between entries."
)
"""Truncating a *profile* loses career history for good, so the advice is the opposite one."""


def generate[T](
    model: LanguageModel,
    ask: Ask,
    *,
    check: Callable[[str], T | Rejection],
    max_attempts: int,
    progress: Progress | None = None,
) -> tuple[T, Usage]:
    """Ask ``model`` until ``check`` accepts the answer, retrying with each specific rejection.

    Each retry is reported through ``progress``, because an attempt takes minutes and a silent
    retry looks exactly like a hang.

    Raises:
        FabricationError: if the last attempt still claimed something unsupported.
        ModelError: if no attempt produced a usable answer for any other reason.
        ValueError: if ``max_attempts`` is less than 1.
    """
    prompt = ask.prompt
    input_tokens = 0
    output_tokens = 0
    for attempt in range(1, max_attempts + 1):
        reply = model.complete(ask.system, prompt)
        input_tokens += reply.input_tokens
        output_tokens += reply.output_tokens
        outcome = ask.truncated if reply.truncated else check(reply.text)
        if not isinstance(outcome, Rejection):
            return outcome, Usage(input_tokens, output_tokens, attempt)
        if attempt == max_attempts:
            raise _exhausted(ask.artefact, outcome, attempt)
        if progress is not None:
            progress(_retrying(ask.artefact, outcome.feedback, attempt + 1, max_attempts))
        prompt = prompts.retry_prompt(ask.prompt, outcome.feedback)
    msg = f"max_attempts must be at least 1, got {max_attempts}"
    raise ValueError(msg)


_NUMBERED = re.compile(r"^[0-9]+\.\s+(?P<problem>.*)$", re.MULTILINE)
_GIST = 90


def _retrying(artefact: str, feedback: str, attempt: int, attempts: int) -> str:
    """Say in one line why an answer was sent back, and which attempt comes next."""
    problems = [match["problem"] for match in _NUMBERED.finditer(feedback)]
    first = problems[0] if problems else feedback.strip().splitlines()[0]
    gist = first if len(first) <= _GIST else first[: _GIST - 1].rstrip() + "…"
    count = f"{len(problems)} problems, the first: " if len(problems) > 1 else ""
    return (
        f"{artefact} did not pass its checks ({count}{gist}); trying again, {attempt} of {attempts}"
    )


def _exhausted(artefact: str, rejection: Rejection, attempts: int) -> ResumeTailorError:
    """Build the error that ends a run, carrying the last rejection so it can be acted on."""
    plural = "" if attempts == 1 else "s"
    msg = (
        f"{artefact} still failed its checks after {attempts} attempt{plural}:"
        f"\n{rejection.feedback}"
    )
    if rejection.fabricated:
        return FabricationError(msg)
    return ModelError(msg)


# --- reading a reply ------------------------------------------------------------------------------
_MARKER = re.compile(r"^=====[ \t]*(?P<name>[A-Z][A-Z ]*[A-Z])[ \t]*=====[ \t]*$", re.MULTILINE)
# A whole answer wrapped in one fence, which models do to anything that looks like a file. An
# inner fence is left alone: `$` anchors this at the end of the text, not the end of a line.
_FENCE = re.compile(r"^```[^\n]*\n(?P<body>.*?)\n```$", re.DOTALL)
_ORNAMENT = "#*_` "
_NO_QUESTIONS = frozenset({"none", "nothing", "n/a", "no questions"})


def split_sections(text: str) -> dict[str, str]:
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


def missing_sections(sections: dict[str, str], expected: tuple[str, ...]) -> Rejection | None:
    """Reject an answer that left out, or left empty, any section it was asked for."""
    if missing := [name for name in expected if not sections.get(name)]:
        return Rejection(
            f"The answer is missing these sections, or left them empty: {', '.join(missing)}. "
            f"Return all {len(expected)} sections, each opened by its own delimiter line."
        )
    return None


def unfence(text: str) -> str:
    """Strip a code fence the model wrapped a whole section in."""
    body = text.strip()
    if match := _FENCE.match(body):
        return match["body"].strip()
    return body


def one_line(text: str) -> str:
    """Reduce a one-value section to its first line, without any Markdown the model dressed it in.

    Callers reach here only for a section already known to be non-empty.
    """
    return text.splitlines()[0].strip(_ORNAMENT).strip()


def questions(text: str) -> tuple[str, ...]:
    """Read a list section as one item per line, dropping a "none"."""
    lines = (line.strip().lstrip("-*• ").strip() for line in text.splitlines())
    return tuple(
        line for line in lines if line and line.casefold().rstrip(".") not in _NO_QUESTIONS
    )
