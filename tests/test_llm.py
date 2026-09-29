"""The model boundary: settings, secret handling, and the Anthropic adapter.

No test here reaches the network. The adapter takes an injected client precisely so the error
mapping can be exercised for every failure a real key would eventually produce.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Self

import pytest

from resume_tailor.errors import ConfigError, ModelError
from resume_tailor.llm import AnthropicModel, LanguageModel, Reply, Settings, build_model
from resume_tailor.llm.config import load_settings, read_env_file

if TYPE_CHECKING:
    from pathlib import Path

KEY = "ANTHROPIC_API_KEY"


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Usage:
    input_tokens = 11
    output_tokens = 22


class _Message:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.usage = _Usage()
        self.stop_reason = stop_reason


class _Stream:
    """The SDK's streaming context manager, reduced to what the adapter actually uses."""

    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.closed = True

    def get_final_message(self) -> Any:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Messages:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.streams: list[_Stream] = []

    def stream(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        opened = _Stream(self._outcome)
        self.streams.append(opened)
        return opened


class _Client:
    def __init__(self, outcome: Any) -> None:
        self.messages = _Messages(outcome)


def _model(outcome: Any) -> AnthropicModel:
    return AnthropicModel(Settings(api_key="sk-test", model="m", max_tokens=99), _Client(outcome))


# --- settings ---------------------------------------------------------------------------------
def test_the_key_is_redacted_in_a_repr() -> None:
    """A stray print of settings in a handler is how a key reaches a log aggregator."""
    text = repr(Settings(api_key="sk-ant-secret-tail"))
    assert "sk-ant-secret" not in text
    assert "***tail" in text


def test_an_env_file_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# a comment\n\nA=1\nB = 'quoted'\nC=\"double\"\nbroken\n", encoding="utf-8")
    assert read_env_file(path) == {"A": "1", "B": "quoted", "C": "double"}


def test_a_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / "absent") == {}


def test_the_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text(f"{KEY}=from-file\n", encoding="utf-8")
    monkeypatch.setenv(KEY, "from-env")
    assert load_settings(path).api_key == "from-env"


def test_settings_fall_back_to_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text(
        f"{KEY}=from-file\nRESUME_TAILOR_MODEL=m\nRESUME_TAILOR_MAX_TOKENS=42\n", encoding="utf-8"
    )
    monkeypatch.delenv(KEY, raising=False)
    settings = load_settings(path)
    assert (settings.api_key, settings.model, settings.max_tokens) == ("from-file", "m", 42)


def test_a_missing_key_says_exactly_how_to_fix_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY, raising=False)
    with pytest.raises(ConfigError, match=re.escape("Copy .env.example")):
        load_settings(tmp_path / "absent")


@pytest.mark.parametrize("value", ["nonsense", "0", "-5"])
def test_a_bad_token_limit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    path = tmp_path / ".env"
    path.write_text(f"{KEY}=k\nRESUME_TAILOR_MAX_TOKENS={value}\n", encoding="utf-8")
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv("RESUME_TAILOR_MAX_TOKENS", raising=False)
    with pytest.raises(ConfigError, match="MAX_TOKENS"):
        load_settings(path)


def test_defaults_apply_when_only_a_key_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text(f"{KEY}=k\n", encoding="utf-8")
    for name in (KEY, "RESUME_TAILOR_MODEL", "RESUME_TAILOR_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(path)
    assert settings.model and settings.max_tokens > 0


# --- the adapter ------------------------------------------------------------------------------
def test_a_reply_carries_its_text_and_cost() -> None:
    reply = _model(_Message("hello")).complete("sys", "prompt")
    assert reply == Reply("hello", 11, 22, "end_turn")
    assert not reply.truncated


def test_the_request_uses_the_configured_model_and_limit() -> None:
    model = _model(_Message("hi"))
    model.complete("sys", "prompt")
    call = model._client.messages.calls[0]
    assert call["model"] == "m"
    assert call["max_tokens"] == 99
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "prompt"}]


def test_a_truncated_reply_is_flagged() -> None:
    """A cut-off resume looks plausible and is missing its last section."""
    assert _model(_Message("partial", "max_tokens")).complete("s", "p").truncated


def test_the_reply_is_streamed_and_the_stream_is_closed() -> None:
    """A long generation exceeds the SDK's non-streaming ceiling, which it refuses outright."""
    model = _model(_Message("hi"))
    model.complete("s", "p")
    assert [stream.closed for stream in model._client.messages.streams] == [True]


def test_a_key_in_an_error_message_is_redacted() -> None:
    """SDK messages quote arguments back; one must never carry the key into a log."""
    with pytest.raises(ModelError, match=re.escape("sk-ant-***")) as caught:
        _model(RuntimeError("bad header x-api-key: sk-ant-abc123DEF")).complete("s", "p")
    assert "abc123DEF" not in str(caught.value)


def test_an_empty_reply_is_an_error() -> None:
    with pytest.raises(ModelError, match="no text"):
        _model(_Message("")).complete("s", "p")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "API key was rejected"),
        (429, "rate limited"),
        (503, "temporarily unavailable"),
        # The type alone said nothing actionable; the SDK's own message names the cause.
        (None, "could not reach the model: RuntimeError: boom"),
    ],
)
def test_api_failures_become_actionable_messages(status: int | None, expected: str) -> None:
    error = RuntimeError("boom")
    if status is not None:
        error.status_code = status  # type: ignore[attr-defined]
    with pytest.raises(ModelError, match=re.escape(expected)) as caught:
        _model(error).complete("s", "p")
    assert "sk-test" not in str(caught.value), "the key must never appear in an error"


def test_build_model_returns_something_satisfying_the_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("resume_tailor.llm.client._make_client", lambda _: _Client(_Message("x")))
    assert isinstance(build_model(Settings(api_key="k")), LanguageModel)


def test_the_sdk_client_is_built_when_none_is_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _Client(_Message("x"))
    monkeypatch.setattr("resume_tailor.llm.client._make_client", lambda _: sentinel)
    assert AnthropicModel(Settings(api_key="k"))._client is sentinel


def test_the_sdk_client_is_constructed_from_the_key() -> None:
    """Exercises the real import path; the SDK builds a client without touching the network."""
    from resume_tailor.llm.client import _make_client

    client = _make_client("sk-ant-not-a-real-key")
    assert hasattr(client, "messages")


# --- choosing who answers -----------------------------------------------------------------------
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    for name in (
        KEY,
        "RESUME_TAILOR_LLM",
        "RESUME_TAILOR_MODEL",
        "RESUME_TAILOR_EFFORT",
        "RESUME_TAILOR_MAX_TOKENS",
        "RESUME_TAILOR_RELAY_DIR",
        "RESUME_TAILOR_RELAY_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_api_is_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(_env(tmp_path, monkeypatch, f"{KEY}=k\n"))
    assert (settings.provider, settings.effort) == ("anthropic", "")


def test_claude_code_needs_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = (
        "RESUME_TAILOR_LLM=Claude-Code\nRESUME_TAILOR_RELAY_DIR=relay\n"
        "RESUME_TAILOR_RELAY_TIMEOUT=5\n"
    )
    settings = load_settings(_env(tmp_path, monkeypatch, env))
    assert settings.provider == "claude-code"
    assert (str(settings.relay_dir), settings.relay_minutes) == ("relay", 5)


def test_a_missing_key_names_the_relay_as_the_alternative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigError, match="RESUME_TAILOR_LLM=claude-code"):
        load_settings(_env(tmp_path, monkeypatch, ""))


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("RESUME_TAILOR_LLM=ollama", "RESUME_TAILOR_LLM must be one of anthropic, claude-code"),
        ("RESUME_TAILOR_EFFORT=extreme", "RESUME_TAILOR_EFFORT must be blank or one of low"),
        ("RESUME_TAILOR_RELAY_TIMEOUT=0", "RESUME_TAILOR_RELAY_TIMEOUT must be positive"),
    ],
)
def test_a_bad_setting_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str, expected: str
) -> None:
    with pytest.raises(ConfigError, match=re.escape(expected)):
        load_settings(_env(tmp_path, monkeypatch, f"{KEY}=k\n{line}\n"))


def test_effort_is_read_and_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(_env(tmp_path, monkeypatch, f"{KEY}=k\nRESUME_TAILOR_EFFORT=Medium\n"))
    assert settings.effort == "medium"
    model = AnthropicModel(settings, _Client(_Message("hi")))
    model.complete("s", "p")
    assert model._client.messages.calls[0]["output_config"] == {"effort": "medium"}


def test_no_effort_sends_no_output_config() -> None:
    model = _model(_Message("hi"))
    model.complete("s", "p")
    assert "output_config" not in model._client.messages.calls[0]


def test_the_relay_folder_can_be_read_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from resume_tailor.llm import load_relay_dir

    assert str(load_relay_dir(_env(tmp_path, monkeypatch, "RESUME_TAILOR_LLM=nonsense\n"))) == (
        ".relay"
    ), "reading the folder must not trip over an unrelated bad setting"
    env = _env(tmp_path, monkeypatch, "RESUME_TAILOR_RELAY_DIR=elsewhere\n")
    assert str(load_relay_dir(env)) == "elsewhere"


def test_the_repr_names_who_answers() -> None:
    text = repr(Settings(api_key="sk-ant-secret-tail", provider="claude-code"))
    assert "provider='claude-code'" in text
    assert "secret" not in text


def test_an_empty_credit_balance_says_what_to_do() -> None:
    error = RuntimeError(
        "{'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit "
        "balance is too low to access the Anthropic API.'}}"
    )
    error.status_code = 400  # type: ignore[attr-defined]
    with pytest.raises(ModelError, match="out of credits") as caught:
        _model(error).complete("s", "p")
    assert "RESUME_TAILOR_LLM=claude-code" in str(caught.value)


def test_build_model_hands_claude_code_the_relay(tmp_path: Path) -> None:
    from resume_tailor.llm import RelayModel

    heard: list[str] = []
    model = build_model(
        Settings(provider="claude-code", relay_dir=tmp_path, relay_minutes=3), announce=heard.append
    )
    assert isinstance(model, RelayModel)
    assert (model.directory, model.minutes, model.announce) == (tmp_path, 3, heard.append)
