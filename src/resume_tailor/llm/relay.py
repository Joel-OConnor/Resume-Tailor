"""Answer the scripts' model requests from a Claude Code session instead of the Anthropic API.

With ``RESUME_TAILOR_LLM=claude-code`` every request becomes a file, and the script waits for a
reply file beside it. Whoever watches the folder answers: a Claude Code session, which reads the
request and writes the reply, at no API cost. Nothing else changes: the reply goes through the same
checks and retries as an API reply, so a relayed resume is held to exactly the same standard.

The protocol, all inside the relay folder:

* the script writes ``<id>.request.md``, holding the system prompt and the prompt;
* the answerer writes the whole reply to ``<id>.response.md`` (``<id>.error.md`` to give up on
  the request, with a line saying why);
* the script reads the reply once the file has stopped growing, and moves both into ``answered/``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from resume_tailor.errors import ModelError
from resume_tailor.llm.client import Reply

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "ANSWERED",
    "RelayModel",
    "error_for",
    "pending_requests",
    "response_for",
    "wait_for_request",
]

ANSWERED = "answered"
"""Where answered requests and their replies are kept, for the record."""

_REQUEST = ".request.md"
_RESPONSE = ".response.md"
_ERROR = ".error.md"
_SECONDS_PER_MINUTE = 60


def response_for(request: Path) -> Path:
    """Return the file a reply to ``request`` is written to."""
    return request.with_name(request.name.removesuffix(_REQUEST) + _RESPONSE)


def error_for(request: Path) -> Path:
    """Return the file that declines ``request``, with the reason inside."""
    return request.with_name(request.name.removesuffix(_REQUEST) + _ERROR)


def pending_requests(directory: Path) -> tuple[Path, ...]:
    """Return every request in ``directory`` with no reply yet, oldest first."""
    if not directory.is_dir():
        return ()
    return tuple(
        request
        for request in sorted(directory.glob(f"*{_REQUEST}"))
        if not response_for(request).exists() and not error_for(request).exists()
    )


def wait_for_request(
    directory: Path,
    *,
    timeout: float,
    poll: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Path | None:
    """Wait up to ``timeout`` seconds for a request to answer; return it, or ``None``."""
    deadline = clock() + timeout
    while True:
        if waiting := pending_requests(directory):
            return waiting[0]
        if clock() >= deadline:
            return None
        sleep(poll)


@dataclass(slots=True)
class RelayModel:
    """A :class:`~resume_tailor.llm.LanguageModel` answered through files by Claude Code."""

    directory: Path
    minutes: int = 60
    """How long to wait for each reply before giving up."""

    announce: Callable[[str], None] | None = None
    """Told where each request is, so a person watching the terminal knows what is awaited."""

    poll: float = 1.0
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    _sent: int = field(default=0, repr=False)

    def complete(self, system: str, prompt: str) -> Reply:
        """Write the request, wait for its reply, and return the reply as a :class:`Reply`.

        Raises:
            ModelError: the request could not be written, the answerer declined it, the reply
                was empty, or none arrived in time.
        """
        request = self._write(system, prompt)
        if self.announce is not None:
            self.announce(f"waiting for Claude Code to answer {request}")
        text = self._await(request)
        self._archive(request)
        if not text.strip():
            msg = f"the reply to {request.name} was empty"
            raise ModelError(msg)
        return Reply(text.strip(), stop_reason="end_turn")

    def _write(self, system: str, prompt: str) -> Path:
        self._sent += 1
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        request = self.directory / f"{stamp}-{self._sent:03d}{_REQUEST}"
        body = (
            f"# Relay request {request.name.removesuffix(_REQUEST)}\n\n"
            f"Write the complete reply, and nothing else, to `{response_for(request)}`. To "
            f"decline, write the reason to `{error_for(request)}`.\n\n"
            f"## System\n\n{system.strip()}\n\n## Prompt\n\n{prompt.strip()}\n"
        )
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            partial = request.with_name(request.name + ".partial")
            partial.write_text(body, encoding="utf-8")
            partial.replace(request)
        except OSError as exc:
            msg = f"cannot write the relay request to {self.directory}: {exc.strerror or exc}"
            raise ModelError(msg) from exc
        return request

    def _await(self, request: Path) -> str:
        """Wait for the reply to exist and stop growing, then read it."""
        response, declined = response_for(request), error_for(request)
        deadline = self.clock() + self.minutes * _SECONDS_PER_MINUTE
        last_size = -1
        while self.clock() < deadline:
            if declined.exists():
                reason = declined.read_text(encoding="utf-8").strip() or "no reason given"
                self._archive(request)
                msg = f"Claude Code declined {request.name}: {reason}"
                raise ModelError(msg)
            if response.exists():
                size = response.stat().st_size
                if size == last_size:
                    return response.read_text(encoding="utf-8")
                last_size = size
            self.sleep(self.poll)
        msg = (
            f"no reply to {request} within {self.minutes} minutes. Is a Claude Code session "
            f"answering {self.directory}? Or set RESUME_TAILOR_LLM=anthropic to use the API."
        )
        raise ModelError(msg)

    def _archive(self, request: Path) -> None:
        """Move a finished request and whatever answered it into ``answered/``."""
        store = self.directory / ANSWERED
        store.mkdir(exist_ok=True)
        for path in (request, response_for(request), error_for(request)):
            if path.exists():
                path.replace(store / path.name)
