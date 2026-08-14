"""The boundary between this package and a language model.

Everything model-facing goes through :class:`LanguageModel`. Keeping it a Protocol is what makes
the rest of the standalone path testable: the agent layer never imports ``anthropic``, so its
tests drive a fake and stay deterministic.
"""

from __future__ import annotations

from resume_tailor.llm.client import AnthropicModel, LanguageModel, Reply, build_model
from resume_tailor.llm.config import Settings, load_settings

__all__ = [
    "AnthropicModel",
    "LanguageModel",
    "Reply",
    "Settings",
    "build_model",
    "load_settings",
]
