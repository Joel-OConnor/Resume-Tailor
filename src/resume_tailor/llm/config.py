"""Settings for the standalone path, read from the environment or a ``.env`` file.

The API key is read once and never logged, never echoed, and never written to any artefact. It
lives only in :class:`Settings`, which has a ``__repr__`` that redacts it — an accidental
``print(settings)`` in a handler is otherwise exactly how a key reaches a log aggregator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import override

from resume_tailor.errors import ConfigError

__all__ = ["DEFAULT_ENV_FILE", "Settings", "load_settings", "read_env_file"]

DEFAULT_ENV_FILE = Path(".env")
_DEFAULT_MODEL = "claude-opus-5"
# A complete master profile for a long career runs well past 8,000 tokens — the first version of
# this default truncated one mid-file, and the retry then asked the model to *cut* career history
# to fit. max_tokens is a ceiling, not a target: raising it changes no cost, only what fits.
_DEFAULT_MAX_TOKENS = 32000
_KEY = "ANTHROPIC_API_KEY"
_VISIBLE_KEY_CHARS = 4


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the standalone path needs to reach a model."""

    api_key: str
    model: str = _DEFAULT_MODEL
    max_tokens: int = _DEFAULT_MAX_TOKENS

    @override
    def __repr__(self) -> str:
        """Redact the key so it cannot reach a log through a stray repr."""
        tail = self.api_key[-_VISIBLE_KEY_CHARS:] if self.api_key else ""
        return f"Settings(api_key='***{tail}', model={self.model!r}, max_tokens={self.max_tokens})"


def read_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping. A missing file is not an error."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def load_settings(env_file: Path = DEFAULT_ENV_FILE) -> Settings:
    """Load settings, preferring a real environment variable over the ``.env`` file.

    Raises:
        ConfigError: when no API key is available, with the exact steps to fix it.
    """
    from_file = read_env_file(env_file)

    def value(name: str) -> str:
        return os.environ.get(name) or from_file.get(name, "")

    api_key = value(_KEY)
    if not api_key:
        msg = (
            f"no {_KEY} found. Copy .env.example to .env and add your key, or export "
            f"{_KEY} in your shell. Get one at https://console.anthropic.com/settings/keys"
        )
        raise ConfigError(msg)

    return Settings(
        api_key=api_key,
        model=value("RESUME_TAILOR_MODEL") or _DEFAULT_MODEL,
        max_tokens=_positive_int(value("RESUME_TAILOR_MAX_TOKENS"), _DEFAULT_MAX_TOKENS),
    )


def _positive_int(raw: str, fallback: int) -> int:
    if not raw:
        return fallback
    try:
        parsed = int(raw)
    except ValueError as exc:
        msg = f"RESUME_TAILOR_MAX_TOKENS must be a whole number, got {raw!r}"
        raise ConfigError(msg) from exc
    if parsed <= 0:
        msg = f"RESUME_TAILOR_MAX_TOKENS must be positive, got {parsed}"
        raise ConfigError(msg)
    return parsed
