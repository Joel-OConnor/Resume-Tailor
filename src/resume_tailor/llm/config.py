"""Settings for the model behind the scripts, read from the environment or a ``.env`` file.

``RESUME_TAILOR_LLM`` picks who answers: ``anthropic`` calls the Anthropic API with the key in
``ANTHROPIC_API_KEY``; ``claude-code`` hands every request to a Claude Code session through files
in ``RESUME_TAILOR_RELAY_DIR`` (see :mod:`resume_tailor.llm.relay`), with no key and no API bill.

The API key is read once and never logged, never echoed, and never written to any artefact. It
lives only in :class:`Settings`, which has a ``__repr__`` that redacts it — an accidental
``print(settings)`` in a handler is otherwise exactly how a key reaches a log aggregator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from resume_tailor.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "ANTHROPIC",
    "CLAUDE_CODE",
    "DEFAULT_ENV_FILE",
    "DEFAULT_RELAY_DIR",
    "EFFORTS",
    "PROVIDERS",
    "Settings",
    "load_relay_dir",
    "load_settings",
    "read_env_file",
]

DEFAULT_ENV_FILE = Path(".env")
ANTHROPIC = "anthropic"
CLAUDE_CODE = "claude-code"
PROVIDERS = (ANTHROPIC, CLAUDE_CODE)
EFFORTS = ("low", "medium", "high", "xhigh", "max")
"""How hard the model thinks. Thinking is billed as output, so this is the first cost lever."""

DEFAULT_RELAY_DIR = Path(".relay")
_DEFAULT_MODEL = "claude-opus-5"
# A complete master profile for a long career runs well past 8,000 tokens — the first version of
# this default truncated one mid-file, and the retry then asked the model to *cut* career history
# to fit. max_tokens is a ceiling, not a target: raising it changes no cost, only what fits.
_DEFAULT_MAX_TOKENS = 32000
_DEFAULT_RELAY_MINUTES = 60
_KEY = "ANTHROPIC_API_KEY"
_VISIBLE_KEY_CHARS = 4


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the scripts need to reach a model, whichever one answers."""

    api_key: str = ""
    model: str = _DEFAULT_MODEL
    max_tokens: int = _DEFAULT_MAX_TOKENS
    provider: str = ANTHROPIC
    effort: str = ""
    """One of :data:`EFFORTS`, or empty for the model's own default."""

    relay_dir: Path = DEFAULT_RELAY_DIR
    relay_minutes: int = _DEFAULT_RELAY_MINUTES
    """How long a script waits for each relayed reply before giving up."""

    @override
    def __repr__(self) -> str:
        """Redact the key so it cannot reach a log through a stray repr."""
        tail = self.api_key[-_VISIBLE_KEY_CHARS:] if self.api_key else ""
        return (
            f"Settings(provider={self.provider!r}, api_key='***{tail}', model={self.model!r}, "
            f"max_tokens={self.max_tokens}, effort={self.effort!r}, "
            f"relay_dir={str(self.relay_dir)!r}, relay_minutes={self.relay_minutes})"
        )


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
        ConfigError: when a setting is invalid, or the API is chosen with no key to call it,
            with the exact steps to fix it.
    """
    value = _reader(env_file)
    provider = (value("RESUME_TAILOR_LLM") or ANTHROPIC).casefold()
    if provider not in PROVIDERS:
        msg = f"RESUME_TAILOR_LLM must be one of {', '.join(PROVIDERS)}, got {provider!r}"
        raise ConfigError(msg)
    api_key = value(_KEY)
    if provider == ANTHROPIC and not api_key:
        msg = (
            f"no {_KEY} found. Copy .env.example to .env and add your key, or export "
            f"{_KEY} in your shell. Get one at https://console.anthropic.com/settings/keys — or "
            f"set RESUME_TAILOR_LLM={CLAUDE_CODE} to have a Claude Code session answer instead."
        )
        raise ConfigError(msg)
    effort = value("RESUME_TAILOR_EFFORT").casefold()
    if effort and effort not in EFFORTS:
        msg = f"RESUME_TAILOR_EFFORT must be blank or one of {', '.join(EFFORTS)}, got {effort!r}"
        raise ConfigError(msg)
    return Settings(
        api_key=api_key,
        model=value("RESUME_TAILOR_MODEL") or _DEFAULT_MODEL,
        max_tokens=_positive_int(
            value("RESUME_TAILOR_MAX_TOKENS"), _DEFAULT_MAX_TOKENS, "RESUME_TAILOR_MAX_TOKENS"
        ),
        provider=provider,
        effort=effort,
        relay_dir=Path(value("RESUME_TAILOR_RELAY_DIR") or DEFAULT_RELAY_DIR),
        relay_minutes=_positive_int(
            value("RESUME_TAILOR_RELAY_TIMEOUT"),
            _DEFAULT_RELAY_MINUTES,
            "RESUME_TAILOR_RELAY_TIMEOUT",
        ),
    )


def load_relay_dir(env_file: Path = DEFAULT_ENV_FILE) -> Path:
    """Return the relay folder alone, without validating the rest of the settings."""
    return Path(_reader(env_file)("RESUME_TAILOR_RELAY_DIR") or DEFAULT_RELAY_DIR)


def _reader(env_file: Path) -> Callable[[str], str]:
    """Return a lookup that prefers a real environment variable over the ``.env`` file."""
    from_file = read_env_file(env_file)

    def value(name: str) -> str:
        return (os.environ.get(name) or from_file.get(name, "")).strip()

    return value


def _positive_int(raw: str, fallback: int, name: str) -> int:
    if not raw:
        return fallback
    try:
        parsed = int(raw)
    except ValueError as exc:
        msg = f"{name} must be a whole number, got {raw!r}"
        raise ConfigError(msg) from exc
    if parsed <= 0:
        msg = f"{name} must be positive, got {parsed}"
        raise ConfigError(msg)
    return parsed
