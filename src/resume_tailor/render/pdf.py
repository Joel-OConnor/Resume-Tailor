"""Print HTML to PDF with headless Chrome.

Chrome is used rather than a Python PDF library for one reason: the text stays selectable, so the
PDF is as readable to an ATS as the ``.docx``. An image-only PDF is invisible to a screener.

When no Chromium-family browser is installed the HTML is left on disk instead, so the user can
open it and print to PDF by hand — the export never silently produces nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = ["CHROME_CANDIDATES", "find_chrome", "html_to_pdf"]

CHROME_CANDIDATES: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
_TIMEOUT_SECONDS = 90


def find_chrome() -> str | None:
    """Return a usable Chromium-family executable, or ``None`` if there isn't one."""
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in _ON_PATH:
        if found := shutil.which(name):
            return found
    return None


def html_to_pdf(html: str, out: Path) -> bool:
    """Render ``html`` to ``out``.

    Returns ``True`` on success. On failure the HTML is written to ``out.with_suffix('.html')``
    and ``False`` is returned, so the caller can tell the user how to finish by hand.
    """
    chrome = find_chrome()
    if chrome is None:
        out.with_suffix(".html").write_text(html, encoding="utf-8")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "document.html"
        source.write_text(html, encoding="utf-8")
        # --headless=new is current Chrome; --headless keeps older builds and Edge working.
        for flag in ("--headless=new", "--headless"):
            if _run_chrome(chrome, flag, source, out) and out.exists() and out.stat().st_size:
                return True

    out.with_suffix(".html").write_text(html, encoding="utf-8")
    return False


def _run_chrome(chrome: str, flag: str, source: Path, out: Path) -> bool:
    """Invoke Chrome once; ``False`` means it failed rather than that the PDF is bad."""
    command = [
        chrome,
        flag,
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={os.fspath(out)}",
        source.as_uri(),
    ]
    try:
        subprocess.run(command, capture_output=True, timeout=_TIMEOUT_SECONDS, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return False
    return True
