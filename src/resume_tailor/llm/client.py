"""The language-model client.

:class:`LanguageModel` is the only thing the agent layer knows about. It is a Protocol rather than
a base class so a test can pass a plain function-backed fake with no imports and no patching, and
so a second provider is a new file rather than a refactor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from resume_tailor.errors import ModelError

if TYPE_CHECKING:
    from resume_tailor.llm.config import Settings

__all__ = ["AnthropicModel", "LanguageModel", "Reply", "build_model"]

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_KEY_SHAPED = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


@dataclass(frozen=True, slots=True)
class Reply:
    """What a model returned, plus what it cost."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""

    @property
    def truncated(self) -> bool:
        """True when the model ran out of room mid-answer.

        Worth surfacing: a truncated resume looks plausible and is missing its last section.
        """
        return self.stop_reason == "max_tokens"


@runtime_checkable
class LanguageModel(Protocol):
    """Anything that can answer a prompt."""

    def complete(self, system: str, prompt: str) -> Reply:
        """Answer ``prompt`` under the instructions in ``system``."""
        ...  # pragma: no cover - Protocol body


@dataclass(slots=True)
class AnthropicModel:
    """A :class:`LanguageModel` backed by the Anthropic Messages API."""

    settings: Settings
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Build the SDK client unless one was injected for a test."""
        if self._client is None:
            self._client = _make_client(self.settings.api_key)

    def complete(self, system: str, prompt: str) -> Reply:
        """Send one turn and return the reply as text.

        Streamed rather than sent as one blocking call: a whole master profile or a four-document
        application can take longer than the SDK's non-streaming ceiling, and it refuses such a
        request outright rather than waiting. The reply is still assembled and returned whole —
        nothing upstream sees a stream.
        """
        try:
            with self._client.messages.stream(
                model=self.settings.model,
                max_tokens=self.settings.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:  # the SDK raises a wide family; all of them mean 'no reply'
            raise ModelError(_describe(exc)) from exc
        return _to_reply(message)


def _make_client(api_key: str) -> Any:  # noqa: ANN401 - the SDK type is not importable at rest
    try:
        import anthropic  # noqa: PLC0415 - deferred so the base install needs no SDK
    except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
        msg = "the standalone path needs the 'agent' extra: pip install 'resume-tailor[agent]'"
        raise ModelError(msg) from exc
    return anthropic.Anthropic(api_key=api_key)


def _to_reply(message: Any) -> Reply:  # noqa: ANN401 - shape is the SDK's, not ours
    blocks = getattr(message, "content", []) or []
    text = "".join(getattr(block, "text", "") for block in blocks).strip()
    if not text:
        msg = "the model returned no text"
        raise ModelError(msg)
    usage = getattr(message, "usage", None)
    return Reply(
        text=text,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        stop_reason=getattr(message, "stop_reason", "") or "",
    )


def _describe(exc: Exception) -> str:
    """Turn an SDK exception into something a user can act on, without leaking the key."""
    status = getattr(exc, "status_code", None)
    if status == 401:  # noqa: PLR2004 - the HTTP meaning is the documentation
        return "the API key was rejected — check ANTHROPIC_API_KEY in your .env"
    if status == 429:  # noqa: PLR2004
        return "rate limited by the API — wait a moment and try again"
    if status in _RETRYABLE_STATUS:
        return f"the API is temporarily unavailable (HTTP {status}) — try again"
    # The type alone named the failure but never what to do about it — "ValueError" was the whole
    # report for a config the SDK rejects by name. Carry the message, with any key redacted from
    # it: a URL or an argument the SDK echoes back is exactly the actionable part.
    return f"could not reach the model: {type(exc).__name__}: {_redact(str(exc))}".rstrip(": ")


def _redact(text: str) -> str:
    """Blank out anything shaped like an API key before it reaches a terminal or a log."""
    return _KEY_SHAPED.sub("sk-ant-***", text)


def build_model(settings: Settings) -> LanguageModel:
    """Construct the configured model."""
    return AnthropicModel(settings)
