"""Print HTML to PDF with headless Chrome.

Chrome is used rather than a Python PDF library for one reason: the text stays selectable, so the
PDF is as readable to an ATS as the ``.docx``. An image-only PDF is invisible to a screener.

When no Chromium-family browser is installed, or the one that is installed fails, the HTML is
left on disk instead so the user can print it by hand — the export never silently produces
nothing, and never leaves a stale or half-written PDF behind pretending to be the current one.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = ["CHROME_CANDIDATES", "PdfResult", "find_chrome", "html_to_pdf"]

CHROME_CANDIDATES: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
_TIMEOUT_SECONDS = 90
_FONT_WAIT_MS = 10_000

NO_BROWSER = "no browser found — open the .html and print to PDF"
BROWSER_FAILED = "the browser could not produce a PDF — open the .html and print it by hand"


@dataclass(frozen=True, slots=True)
class PdfResult:
    """Whether the PDF was produced, and why not when it wasn't."""

    ok: bool
    reason: str = ""


def find_chrome() -> str | None:
    """Return a usable Chromium-family executable, or ``None`` if there isn't one."""
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in _ON_PATH:
        if found := shutil.which(name):
            return found
    return None


def html_to_pdf(html: str, out: Path) -> PdfResult:
    """Render ``html`` to ``out``.

    On failure the HTML is written to ``out.with_suffix('.html')`` and any partial PDF is
    removed, so the caller can tell the user how to finish by hand and the directory never holds
    a PDF that does not correspond to the current source.
    """
    chrome = find_chrome()
    if chrome is None:
        return _fall_back(html, out, NO_BROWSER)

    # An earlier build's PDF must not be mistaken for this one's output.
    _remove(out)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "document.html"
        source.write_text(html, encoding="utf-8")
        # --headless=new is current Chrome; --headless keeps older builds and Edge working.
        for flag in ("--headless=new", "--headless"):
            if _run_chrome(chrome, flag, source, out) and out.exists() and out.stat().st_size:
                # Drop a fallback left by a previous run, so only one of the two ever exists.
                _remove(out.with_suffix(".html"))
                return PdfResult(ok=True)
            _remove(out)

    return _fall_back(html, out, BROWSER_FAILED)


def _fall_back(html: str, out: Path, reason: str) -> PdfResult:
    """Write the printable HTML beside the intended PDF and report why."""
    out.with_suffix(".html").write_text(html, encoding="utf-8")
    return PdfResult(ok=False, reason=reason)


def _remove(path: Path) -> None:
    """Delete ``path`` if it is there, ignoring a directory or a permission problem."""
    with contextlib.suppress(OSError):  # a directory or a permission problem is not fatal here
        path.unlink(missing_ok=True)


def _run_chrome(chrome: str, flag: str, source: Path, out: Path) -> bool:
    """Invoke Chrome once. ``False`` means it failed, not that the PDF is bad."""
    command = [
        chrome,
        flag,
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        # The polished layout fetches its typeface from Google Fonts; this lets that download
        # finish before the page is printed, instead of racing it and printing the fallback.
        f"--virtual-time-budget={_FONT_WAIT_MS}",
        f"--print-to-pdf={os.fspath(out)}",
        source.as_uri(),
    ]
    try:
        completed = subprocess.run(  # noqa: S603
            command, capture_output=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # A non-zero exit means Chrome gave up; whatever is at `out` is stale or half-written.
    return completed.returncode == 0
