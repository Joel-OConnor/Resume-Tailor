"""Answer the scripts' model requests from a Claude Code session instead of the Anthropic API.

With ``RESUME_TAILOR_LLM=claude-code`` every request becomes a file, and the script waits for a
reply file beside it. Whoever watches the folder answers: a Claude Code session, which reads the
request and writes the reply, at no API cost. Nothing else changes: the reply goes through the same
checks and retries as an API reply, so a relayed resume is held to exactly the same standard.

The protocol, all inside the relay folder:

* the script writes ``<id>.request.md``, holding the system prompt and the prompt. The id is the
  UTC second it was posted, a random id for the script's run, and a count, so two scripts sharing
  the folder never post under the same name and the names still sort oldest first;
* the answerer writes the whole reply to ``<id>.response.md.tmp`` and moves it onto
  ``<id>.response.md`` (``<id>.error.md`` to give up on the request, with a line saying why);
* the script reads the reply once the file has kept the same size for two polls in a row, and
  moves both into ``answered/``. A request it stops waiting for (no reply in time, or the script
  interrupted) moves there too.

A script can also be killed before it tidies up (a terminal closed, a background job stopped), and
then its request stays in the folder. So the script holds a lock on each request while it waits,
which the operating system releases however the script ends, and :func:`pending_requests` passes
over a request nobody holds. The next answerer is handed only a request a script is waiting for.
"""

from __future__ import annotations

import fcntl
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from resume_tailor.errors import ModelError
from resume_tailor.llm.client import Reply

if TYPE_CHECKING:
    from collections.abc import Callable
    from io import BufferedReader
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
_RUN_ID_BYTES = 4
_STEADY_POLLS = 2
"""How many polls in a row a reply must keep its size before it is read.

A reply moved into place is whole the moment it appears, so this costs it two polls. A reply
written in pieces gets that long to pause between them without being read half-finished.
"""


def _new_run() -> str:
    """Return a random id for one script's run, which no other run sharing the folder will have."""
    return secrets.token_hex(_RUN_ID_BYTES)


def response_for(request: Path) -> Path:
    """Return the file a reply to ``request`` is written to."""
    return request.with_name(request.name.removesuffix(_REQUEST) + _RESPONSE)


def error_for(request: Path) -> Path:
    """Return the file that declines ``request``, with the reason inside."""
    return request.with_name(request.name.removesuffix(_REQUEST) + _ERROR)


def pending_requests(directory: Path) -> tuple[Path, ...]:
    """Return every request in ``directory`` a script is still waiting on, oldest first.

    A request with a reply or a decline is answered, and one whose script is gone is left behind:
    nobody would read its reply.
    """
    if not directory.is_dir():
        return ()
    return tuple(
        request
        for request in sorted(directory.glob(f"*{_REQUEST}"))
        if not response_for(request).exists()
        and not error_for(request).exists()
        and not _left_behind(request)
    )


def _left_behind(request: Path) -> bool:
    """Return whether the script that wrote ``request`` has ended without taking it away.

    The script holds a lock on the request while it waits (see :func:`_awaited`), and the operating
    system releases it when the script ends, however it ends. A lock this call can take is one
    nobody holds. When the lock cannot be tried at all, the request counts as awaited.
    """
    try:
        with request.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _awaited(path: Path) -> BufferedReader:
    """Open ``path`` and lock it, the mark that its script is waiting for the reply.

    The lock lasts until the returned file is closed or the script ends. On a filesystem without
    locks the request goes unmarked, and :func:`_left_behind` then counts it as awaited too.
    """
    handle = path.open("rb")
    with suppress(OSError):
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


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
    _run: str = field(default_factory=_new_run, repr=False)
    """Sets this run's requests apart from those of any other script posting in the same second."""

    def complete(self, system: str, prompt: str) -> Reply:
        """Write the request, wait for its reply, and return the reply as a :class:`Reply`.

        Raises:
            ModelError: the request could not be written, the answerer declined it, the reply
                was empty or not UTF-8 text, or none arrived in time.
        """
        request, waiting = self._write(system, prompt)
        try:
            if self.announce is not None:
                self.announce(f"waiting for Claude Code to answer {request}")
            text = self._await(request)
        finally:
            # Answered, declined, timed out or interrupted, the request is finished. Left in the
            # folder, it would be the oldest pending one, and the next answerer would take it first.
            waiting.close()
            self._archive(request)
        if not text.strip():
            msg = f"the reply to {request.name} was empty"
            raise ModelError(msg)
        return Reply(text.strip(), stop_reason="end_turn")

    def _write(self, system: str, prompt: str) -> tuple[Path, BufferedReader]:
        """Put the request in the folder, locked as awaited, and return it with its lock."""
        self._sent += 1
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        # The time leads, so the oldest request sorts first. Two scripts can post in the same
        # second, and with the same name one would replace the other's request and take its reply.
        request = self.directory / f"{stamp}-{self._run}-{self._sent:03d}{_REQUEST}"
        response = response_for(request)
        body = (
            f"# Relay request {request.name.removesuffix(_REQUEST)}\n\n"
            f"Write the complete reply, and nothing else, to `{response}.tmp`, then move that "
            f"file onto `{response}`, so the script never reads a reply that is still being "
            f"written. To decline, write the reason to `{error_for(request)}`.\n\n"
            f"## System\n\n{system.strip()}\n\n## Prompt\n\n{prompt.strip()}\n"
        )
        waiting = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            partial = request.with_name(request.name + ".partial")
            partial.write_text(body, encoding="utf-8")
            # Locked before it can be seen, so no answerer ever takes it for one left behind.
            waiting = _awaited(partial)
            partial.replace(request)
        except OSError as exc:
            if waiting is not None:
                waiting.close()
            msg = f"cannot write the relay request to {self.directory}: {exc.strerror or exc}"
            raise ModelError(msg) from exc
        return request, waiting

    def _await(self, request: Path) -> str:
        """Wait for the reply to be written and keep its size, then read it.

        One quiet poll is not enough: a writer that pauses between pieces looks finished in the
        pause, and a shell redirect creates the file before it has anything to put in it. So an
        empty file counts as not written yet, and the size must hold for :data:`_STEADY_POLLS`
        polls in a row. A decline is read the same way, except that an empty one, held as long,
        still declines: the reason is optional.
        """
        response, declined = response_for(request), error_for(request)
        deadline = self.clock() + self.minutes * _SECONDS_PER_MINUTE
        last_size = steady = 0
        last_decline, decline_steady = -1, 0
        while self.clock() < deadline:
            if declined.exists():
                decline_size = _size(declined)
                decline_steady = decline_steady + 1 if decline_size == last_decline else 0
                last_decline = decline_size
                if decline_steady >= _STEADY_POLLS:
                    reason = _read_answer(declined).strip() or "no reason given"
                    msg = f"Claude Code declined {request.name}: {reason}"
                    raise ModelError(msg)
            size = _size(response)
            steady = steady + 1 if size and size == last_size else 0
            if steady >= _STEADY_POLLS:
                return _read_answer(response)
            last_size = size
            self.sleep(self.poll)
        msg = (
            f"no reply to {request} within {self.minutes} minutes. Is a Claude Code session "
            f"answering {self.directory}? Or set RESUME_TAILOR_LLM=anthropic to use the API."
        )
        raise ModelError(msg)

    def _archive(self, request: Path) -> None:
        """Move a finished request and whatever answered it into ``answered/``.

        This is housekeeping, so it never fails the run: with the folder deleted or read-only it
        does nothing, and the reply, the decline or the timeout is reported as it happened.
        """
        store = self.directory / ANSWERED
        with suppress(OSError):
            store.mkdir(exist_ok=True)
            for path in (request, response_for(request), error_for(request)):
                if path.exists():
                    path.replace(store / path.name)


def _size(path: Path) -> int:
    """Return how many bytes ``path`` holds, or 0 while it does not exist."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _read_answer(path: Path) -> str:
    """Read a reply or a decline as UTF-8, dropping a byte-order mark.

    Left in, the mark would hide the first section's heading from the checks.

    Raises:
        ModelError: the file is not UTF-8 text. Waiting longer would not change that, and a raw
            decoding error would reach the user as a traceback.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = (
            f"{path.name} is not UTF-8 text (byte {exc.object[exc.start]:#04x} at offset "
            f"{exc.start}): relay replies and declines must be written as UTF-8"
        )
        raise ModelError(msg) from exc
