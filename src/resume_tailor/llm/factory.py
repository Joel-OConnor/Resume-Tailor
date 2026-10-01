"""Build whichever model the settings name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from resume_tailor.llm.client import AnthropicModel
from resume_tailor.llm.config import CLAUDE_CODE
from resume_tailor.llm.relay import RelayModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from resume_tailor.llm.client import LanguageModel
    from resume_tailor.llm.config import Settings

__all__ = ["build_model"]


def build_model(
    settings: Settings, *, announce: Callable[[str], None] | None = None
) -> LanguageModel:
    """Construct the model ``settings`` name: the Anthropic API, or a Claude Code relay.

    ``announce`` hears where each relayed request waits, so the person watching a script knows
    what it is waiting for; the API needs no such line.
    """
    if settings.provider == CLAUDE_CODE:
        return RelayModel(settings.relay_dir, minutes=settings.relay_minutes, announce=announce)
    return AnthropicModel(settings)
