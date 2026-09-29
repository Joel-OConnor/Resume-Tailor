"""The Claude Code relay: requests out as files, replies back as files, checked like any reply."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from resume_tailor import cli
from resume_tailor.errors import ModelError
from resume_tailor.llm import RelayModel, Reply, pending_requests, response_for, wait_for_request
from resume_tailor.llm.relay import ANSWERED, error_for

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _Clock:
    """Time that moves only when the relay sleeps, so waiting is instant and exact."""

    def __init__(self) -> None:
        self.now = 0.0
        self.naps = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.naps += 1


def _relay(
    tmp_path: Path, on_sleep: Callable[[Path, int], None] | None = None, minutes: int = 1
) -> tuple[RelayModel, _Clock, list[str]]:
    """Build a relay whose ``on_sleep`` plays the answerer: it sees the folder at each nap."""
    clock = _Clock()
    heard: list[str] = []

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if on_sleep is not None:
            on_sleep(tmp_path, clock.naps)

    model = RelayModel(tmp_path, minutes=minutes, announce=heard.append, clock=clock, sleep=sleep)
    return model, clock, heard


def _answer(text: str) -> Callable[[Path, int], None]:
    def answer(folder: Path, _: int) -> None:
        for request in pending_requests(folder):
            response_for(request).write_text(text, encoding="utf-8")

    return answer


def test_a_request_is_written_and_its_reply_returned(tmp_path: Path) -> None:
    model, _, heard = _relay(tmp_path, _answer("  the reply  \n"))

    reply = model.complete("the system prompt", "the prompt")

    assert reply == Reply("the reply", stop_reason="end_turn")
    [request] = (tmp_path / ANSWERED).glob("*.request.md")
    text = request.read_text(encoding="utf-8")
    assert "## System\n\nthe system prompt" in text
    assert "## Prompt\n\nthe prompt" in text
    assert str(response_for(tmp_path / request.name)) in text, "it says where the reply goes"
    assert (tmp_path / ANSWERED / response_for(request).name).exists()
    assert pending_requests(tmp_path) == ()
    assert heard == [f"waiting for Claude Code to answer {tmp_path / request.name}"]


def test_a_reply_is_read_only_once_it_stops_growing(tmp_path: Path) -> None:
    """A large reply is written in pieces; reading the first piece would lose the rest."""

    def grow(folder: Path, nap: int) -> None:
        for request in pending_requests(folder) or list(folder.glob("*.request.md")):
            response = response_for(request)
            if nap <= 2:
                response.write_text("part " * nap, encoding="utf-8")

    model, _, _ = _relay(tmp_path, grow)
    assert model.complete("s", "p").text == "part part"


def test_each_request_gets_its_own_file(tmp_path: Path) -> None:
    model, _, _ = _relay(tmp_path, _answer("ok"))
    model.complete("s", "first")
    model.complete("s", "second")
    names = sorted(path.name for path in (tmp_path / ANSWERED).glob("*.request.md"))
    assert [name[-15:] for name in names] == ["-001.request.md", "-002.request.md"]


def test_a_declined_request_ends_with_the_reason(tmp_path: Path) -> None:
    def decline(folder: Path, _: int) -> None:
        for request in pending_requests(folder):
            error_for(request).write_text("the prompt is truncated\n", encoding="utf-8")

    model, _, _ = _relay(tmp_path, decline)
    with pytest.raises(ModelError, match=r"declined .*: the prompt is truncated"):
        model.complete("s", "p")
    assert list((tmp_path / ANSWERED).glob("*.error.md"))


def test_a_decline_with_no_reason_still_says_so(tmp_path: Path) -> None:
    def decline(folder: Path, _: int) -> None:
        for request in pending_requests(folder):
            error_for(request).write_text("", encoding="utf-8")

    model, _, _ = _relay(tmp_path, decline)
    with pytest.raises(ModelError, match="no reason given"):
        model.complete("s", "p")


def test_an_empty_reply_is_an_error(tmp_path: Path) -> None:
    model, _, _ = _relay(tmp_path, _answer("   \n"))
    with pytest.raises(ModelError, match="was empty"):
        model.complete("s", "p")


def test_no_reply_in_time_says_what_to_check(tmp_path: Path) -> None:
    model, clock, _ = _relay(tmp_path, minutes=2)
    with pytest.raises(ModelError, match="within 2 minutes") as caught:
        model.complete("s", "p")
    assert "RESUME_TAILOR_LLM=anthropic" in str(caught.value)
    assert clock.now >= 120


def test_an_unwritable_relay_folder_is_reported(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("in the way", encoding="utf-8")
    model = RelayModel(blocked / "relay")
    with pytest.raises(ModelError, match="cannot write the relay request"):
        model.complete("s", "p")


def test_a_relay_without_an_announcer_stays_quiet(tmp_path: Path) -> None:
    clock = _Clock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        _answer("ok")(tmp_path, clock.naps)

    assert RelayModel(tmp_path, clock=clock, sleep=sleep).complete("s", "p").text == "ok"


# --- the answerer's side -------------------------------------------------------------------------
def test_pending_requests_are_the_unanswered_ones_oldest_first(tmp_path: Path) -> None:
    assert pending_requests(tmp_path / "absent") == ()
    for name in ("b", "a", "c", "d"):
        (tmp_path / f"{name}.request.md").write_text("?", encoding="utf-8")
    (tmp_path / "c.response.md").write_text("!", encoding="utf-8")
    (tmp_path / "d.error.md").write_text("no", encoding="utf-8")
    assert [path.name for path in pending_requests(tmp_path)] == ["a.request.md", "b.request.md"]


def test_waiting_returns_a_request_as_soon_as_one_appears(tmp_path: Path) -> None:
    clock = _Clock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        (tmp_path / "x.request.md").write_text("?", encoding="utf-8")

    found = wait_for_request(tmp_path, timeout=60, clock=clock, sleep=sleep)
    assert found == tmp_path / "x.request.md"
    assert clock.naps == 1


def test_waiting_gives_up_at_the_timeout(tmp_path: Path) -> None:
    clock = _Clock()
    assert wait_for_request(tmp_path, timeout=5, clock=clock, sleep=clock.sleep) is None
    assert clock.now >= 5


def test_relay_wait_prints_the_request_and_where_to_reply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = tmp_path / "20260928-120000-001.request.md"
    request.write_text("?", encoding="utf-8")

    assert cli.main(["relay", "wait", "--dir", str(tmp_path), "--timeout", "0.01"]) == 0

    assert capsys.readouterr().out == (
        f"request: {request}\nreply to: {tmp_path / '20260928-120000-001.response.md'}\n"
    )


def test_relay_wait_reports_an_empty_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_relay_dir", lambda: tmp_path)
    asked: list[tuple[Path, float]] = []

    def nothing(directory: Path, timeout: float) -> None:
        asked.append((directory, timeout))

    monkeypatch.setattr(cli, "wait_for_request", nothing)
    assert cli.main(["relay", "wait", "--timeout", "2"]) == 1
    assert asked == [(tmp_path, 120.0)], "the folder comes from .env, the timeout in seconds"
    assert "no request waiting in" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["soon", "0", "-1"])
def test_a_bad_relay_timeout_is_refused(value: str) -> None:
    with pytest.raises(SystemExit):
        cli.main(["relay", "wait", "--timeout", value])
