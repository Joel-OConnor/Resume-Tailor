"""The boundary between this package and whatever model answers it.

Everything model-facing goes through :class:`LanguageModel`. Keeping it a Protocol is what makes
the rest of the package testable, and what lets two very different backends stand behind it: the
Anthropic API (:class:`AnthropicModel`) and a Claude Code session answering through files
(:class:`RelayModel`). ``RESUME_TAILOR_LLM`` in ``.env`` chooses between them.
"""

from __future__ import annotations

from resume_tailor.llm.client import AnthropicModel, LanguageModel, Reply
from resume_tailor.llm.config import Settings, load_relay_dir, load_settings
from resume_tailor.llm.factory import build_model
from resume_tailor.llm.relay import RelayModel, pending_requests, response_for, wait_for_request

__all__ = [
    "AnthropicModel",
    "LanguageModel",
    "RelayModel",
    "Reply",
    "Settings",
    "build_model",
    "load_relay_dir",
    "load_settings",
    "pending_requests",
    "response_for",
    "wait_for_request",
]
