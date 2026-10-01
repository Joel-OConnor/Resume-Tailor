"""Reading a posting file: every encoding an editor saves, and a clear refusal for the rest."""

from __future__ import annotations

import codecs
from typing import TYPE_CHECKING

import pytest

from resume_tailor.errors import ResumeTailorError
from resume_tailor.match import PostingError, read_posting

if TYPE_CHECKING:
    from pathlib import Path

POSTING = "# Acme - Staff Engineer\n\n## Requirements\n- We’re after Go, Kafka and AWS.\n"
FIX = "Save the job description as a .md or .txt file and point at that."


def _saved(tmp_path: Path, data: bytes, name: str = "jd.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_utf8_is_read_as_written(tmp_path: Path) -> None:
    assert read_posting(_saved(tmp_path, POSTING.encode())) == POSTING


def test_a_utf8_byte_order_mark_is_stripped(tmp_path: Path) -> None:
    assert read_posting(_saved(tmp_path, codecs.BOM_UTF8 + POSTING.encode())) == POSTING


def test_windows_1252_is_read_with_its_curly_apostrophe(tmp_path: Path) -> None:
    """Notepad's "ANSI" writes the apostrophe as byte 0x92, which UTF-8 rejects.

    Tabs and Windows line endings are control codes too, and they are text.
    """
    text = POSTING.replace("\n", "\r\n").replace("- We", "-\tWe")
    data = text.encode("cp1252")
    assert b"\x92" in data
    assert read_posting(_saved(tmp_path, data)) == text


@pytest.mark.parametrize(
    ("mark", "codec"),
    [(codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")],
)
def test_utf16_is_read_when_its_byte_order_mark_says_so(
    tmp_path: Path, mark: bytes, codec: str
) -> None:
    """Notepad's "Unicode" and a Windows PowerShell redirect both write UTF-16 with a mark."""
    assert read_posting(_saved(tmp_path, mark + POSTING.encode(codec))) == POSTING


def test_a_blank_utf16_file_reads_as_blank_so_it_is_reported_as_empty(tmp_path: Path) -> None:
    assert read_posting(_saved(tmp_path, "  \r\n".encode("utf-16"))) == "  \r\n"


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("jd.pdf", "a PDF"),
        ("jd.PDF", "a PDF"),
        ("jd.docx", "a Word document"),
        ("jd.doc", "a Word document"),
    ],
)
def test_a_pdf_or_word_file_is_refused_by_name(tmp_path: Path, name: str, kind: str) -> None:
    """The name decides, whatever the bytes inside."""
    path = _saved(tmp_path, b"PK\x03\x04\x14\x00\x06\x00\x08\x00", name)
    with pytest.raises(PostingError) as refused:
        read_posting(path)
    assert str(refused.value) == f"cannot read {path}: it is {kind}, not plain text. {FIX}"


def test_a_pdf_saved_under_a_text_name_is_still_called_a_pdf(tmp_path: Path) -> None:
    path = _saved(tmp_path, b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", "jd.txt")
    with pytest.raises(PostingError, match="it is a PDF, not plain text"):
        read_posting(path)


@pytest.mark.parametrize(
    "data",
    [
        # A zip archive, which is what a .docx is, under a text name.
        b"PK\x03\x04\x14\x00\x06\x00\x08\x00!\x00\xa8",
        # Valid UTF-8, but no text holds a NUL.
        b"Go\x00Kafka\x00",
        # A byte Windows-1252 leaves undefined.
        b"Go and \x81 Kafka",
        # Windows-1252 control codes, not text.
        b"\xe9\x01\x02\x03",
        # A UTF-16 mark with no Latin text behind it: two bytes any file can start with.
        b"\xff\xfe\x00\x80",
        # A UTF-16 mark on an odd number of bytes.
        b"\xff\xfeG\x00o",
    ],
)
def test_anything_else_that_is_not_text_is_refused_with_the_fix(
    tmp_path: Path, data: bytes
) -> None:
    path = _saved(tmp_path, data, "jd.md")
    with pytest.raises(PostingError) as refused:
        read_posting(path)
    assert str(refused.value) == f"cannot read {path}: it is not plain text. {FIX}"


def test_a_refusal_is_an_error_the_cli_prints_as_one_line() -> None:
    """``cli.main`` prints a ResumeTailorError as its message; a codec error escaped raw."""
    assert issubclass(PostingError, ResumeTailorError)
