"""What Chrome really prints: the text in reading order, and every line inside its column.

Every other test stubs the browser out, which keeps the suite fast and lets it run where there is
no browser (CI has none), so nothing else reads a real print. A layout can look right on the page
and still store its text out of order: with the bullet glyph positioned, Chrome wrote every
bullet after all other text, and a parser reading the PDF in stored order found each
accomplishment under the last heading. These tests print through the project's own exporter and
read the result with pypdf's default extraction, the reader this project itself uses for an old
resume.pdf. They skip themselves on a machine with no Chromium-family browser.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from pypdf import PdfReader

from resume_tailor.render.exporter import Layout, build
from resume_tailor.render.pdf import find_chrome

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    find_chrome() is None, reason="no Chromium-family browser installed to print with"
)

EMAIL = "ada.augusta.king.lovelace@analyticalengine.example"
"""Longer than the polished rail is wide, with no hyphen or space for the browser to break at."""

# Two roles, so a bullet read under the wrong one shows, and two rail skill groups likewise.
RESUME_MD = f"""\
# Ada Lovelace
Principal Engineer
{EMAIL} | London, UK

## Summary
Engineer who writes programs for engines that do not exist yet.

## Skills
**Languages:** Analytical Notation, Symbolic Algebra
**Machines:** Difference Engine, Jacquard Loom

## Experience

### **Principal Engineer** – Analytical Engine Programme
London, UK | Jan 1843 – Present
- Published the first algorithm intended for a machine.
- Corresponded with Babbage on engine semantics.
*Tech Stack – Bernoulli numbers, punched cards*

### **Translator** – Scientific Memoirs
London, UK | 1842 – 1843
- Translated Menabrea's paper on the engine.
- Added notes three times the length of the paper.

## Education
### **Mathematics** – Private tuition
1840

## Certifications
- Fellow of the Analytical Society – 1843
"""

ROLES_IN_ORDER = (
    "Analytical Engine Programme",
    "Published the first algorithm",
    "Corresponded with Babbage",
    "Tech Stack",
    "Scientific Memoirs",
    "Translated Menabrea",
    "Added notes three times",
)
# Each bullet's opening words, short enough never to wrap, even in the rail.
BULLETS = (
    "Published the first",
    "Corresponded with",
    "Translated Menabrea",
    "Added notes three",
    "Fellow of the",
)


@pytest.fixture(scope="module")
def printed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Print both layouts once; return each PDF's text as pypdf's default extraction reads it."""
    folder = tmp_path_factory.mktemp("printed")
    source = folder / "resume.md"
    source.write_text(RESUME_MD, encoding="utf-8")
    artifacts = build(source, layout=Layout.BOTH)
    if failed := [artifact.reason for artifact in artifacts if not artifact.ok]:
        pytest.fail(f"the browser is installed but did not print: {failed}")
    pdfs = [artifact.path for artifact in artifacts if artifact.path.suffix == ".pdf"]
    return {pdf.name: _text(pdf) for pdf in pdfs}


def _text(pdf: Path) -> str:
    """Every page's text, as pypdf's default (stored-order) extraction reads it."""
    return "\n".join(page.extract_text() for page in PdfReader(pdf).pages)


def _read_order(text: str, phrases: Sequence[str]) -> list[str]:
    """Return ``phrases`` in the order they are first read in ``text``."""
    missing = [phrase for phrase in phrases if phrase not in text]
    assert not missing, f"not in the PDF's text: {missing}"
    return sorted(phrases, key=text.index)


@pytest.mark.parametrize("name", ["resume.pdf", "resume-polished.pdf"])
def test_every_bullet_is_read_under_its_own_role(printed: dict[str, str], name: str) -> None:
    text = printed[name]
    assert _read_order(text, ROLES_IN_ORDER) == list(ROLES_IN_ORDER)


def test_the_last_sections_are_read_after_the_experience(printed: dict[str, str]) -> None:
    """Where every bullet used to land: after the Certifications heading."""
    phrases = ("Added notes three times", "Education", "Certifications", "Fellow of the Analytical")
    assert _read_order(printed["resume.pdf"], phrases) == list(phrases)


@pytest.mark.parametrize("name", ["resume.pdf", "resume-polished.pdf"])
def test_each_glyph_is_read_with_its_bullet_ahead_of_the_text(
    printed: dict[str, str], name: str
) -> None:
    """A positioned glyph was written after its text, leaving each line without its bullet."""
    opens = [rf"^•[ \t]*{re.escape(bullet)}" for bullet in BULLETS]
    assert [line for line in opens if not re.search(line, printed[name], re.MULTILINE)] == []


def test_each_rail_skill_is_read_under_its_own_label(printed: dict[str, str]) -> None:
    rail = (
        "Skills",
        "Languages",
        "Analytical Notation",
        "Symbolic Algebra",
        "Machines",
        "Difference Engine",
        "Jacquard Loom",
        "Education",
    )
    assert _read_order(printed["resume-polished.pdf"], rail) == list(rail)


def test_a_long_email_wraps_inside_the_rail(printed: dict[str, str]) -> None:
    """Unwrapped, it ran across the rule and into the name; the .docx wraps it in the rail."""
    text = printed["resume-polished.pdf"]
    assert EMAIL not in text, "printed on one line, wider than the rail"
    assert EMAIL in text.replace("\n", ""), "every character is still there, in order"


def test_the_single_column_keeps_the_email_whole(printed: dict[str, str]) -> None:
    """Breaking a word is only for one that cannot fit: this one fits the single column."""
    assert f"{EMAIL} | London, UK" in printed["resume.pdf"]
