"""Hold a LinkedIn profile draft to what LinkedIn will actually accept.

LinkedIn cuts a headline at 220 characters, an About section at 2,600 and a position's description
at 2,000, pins at most five top skills, and takes at most a hundred skills in all. A draft over any
of those limits reads fine in Markdown and is truncated mid-sentence in the one place it matters,
so these are hard checks on the draft rather than advice: an answer that breaks one is sent back.
"""

from __future__ import annotations

import re

__all__ = [
    "ABOUT_LIMIT",
    "DESCRIPTION_LIMIT",
    "HEADLINE_LIMIT",
    "REQUIRED_SECTIONS",
    "SKILLS_LIMIT",
    "TOP_SKILLS_LIMIT",
    "check_linkedin",
]

HEADLINE_LIMIT = 220
ABOUT_LIMIT = 2600
DESCRIPTION_LIMIT = 2000
TOP_SKILLS_LIMIT = 5
SKILLS_LIMIT = 100
REQUIRED_SECTIONS = ("Headline", "About", "Experience", "Skills")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SECTION = re.compile(r"^##\s+(?P<title>\S.*)$")
_ENTRY = re.compile(r"^###\s+(?P<title>\S.*)$")
_SKILL_LINE = re.compile(r"^\*\*[^*]+?:\*\*\s*(?P<items>.*)$")
_BULLET = re.compile(r"^[-*]\s+\S")


def check_linkedin(markdown: str) -> tuple[str, ...]:
    """Return every way ``markdown`` breaks the LinkedIn format or LinkedIn's limits."""
    sections = _sections(markdown)
    problems = [
        f"the ## {name} section is missing"
        for name in REQUIRED_SECTIONS
        if name.casefold() not in sections
    ]
    headline = " ".join(line for line in sections.get("headline", []) if line)
    if len(headline) > HEADLINE_LIMIT:
        problems.append(
            f"the headline is {len(headline)} characters; LinkedIn stops at {HEADLINE_LIMIT}"
        )
    about = _text(sections.get("about", []))
    if len(about) > ABOUT_LIMIT:
        problems.append(
            f"the About section is {len(about)} characters; LinkedIn stops at {ABOUT_LIMIT}"
        )
    problems += _descriptions(sections.get("experience", []))
    top = _count_skills(sections.get("top skills", []))
    if top > TOP_SKILLS_LIMIT:
        problems.append(f"{top} top skills; LinkedIn pins at most {TOP_SKILLS_LIMIT}")
    total = _count_skills(sections.get("skills", []))
    if total > SKILLS_LIMIT:
        problems.append(f"{total} skills; LinkedIn takes at most {SKILLS_LIMIT}")
    return tuple(problems)


def _sections(markdown: str) -> dict[str, list[str]]:
    """Split the document into ``{section title, casefolded: its lines}``."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in _COMMENT.sub("", markdown).splitlines():
        line = raw.strip()
        if match := _SECTION.match(line):
            current = found.setdefault(match["title"].strip().casefold(), [])
        elif current is not None:
            current.append(line)
    return found


def _text(lines: list[str]) -> str:
    """Join lines the way they are pasted: one line break between them, blank lines kept."""
    return "\n".join(lines).strip()


def _descriptions(lines: list[str]) -> list[str]:
    """Check each position's description: what sits under its dates line, less its skills."""
    problems: list[str] = []
    for title, body in _entries(lines):
        text = _text([line for line in body[1:] if not _SKILL_LINE.match(line)])
        if len(text) > DESCRIPTION_LIMIT:
            problems.append(
                f"the description for {title} is {len(text)} characters; LinkedIn stops at "
                f"{DESCRIPTION_LIMIT}"
            )
    return problems


def _entries(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split a section into its ``### `` entries, each with the lines beneath it."""
    entries: list[tuple[str, list[str]]] = []
    for line in lines:
        if match := _ENTRY.match(line):
            entries.append((match["title"].strip(), []))
        elif entries:
            entries[-1][1].append(line)
    return entries


def _count_skills(lines: list[str]) -> int:
    """Count the skills listed in a section: comma-separated on a label line, or one per bullet."""
    count = 0
    for line in lines:
        if match := _SKILL_LINE.match(line):
            count += len([item for item in match["items"].split(",") if item.strip()])
        elif _BULLET.match(line):
            count += 1
    return count
