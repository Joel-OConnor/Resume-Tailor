"""Read a resume the way a tired recruiter does, and say what gets in the way.

Three kinds of finding come out. A FIX is mechanical and safe — a missing full stop where every
other bullet has one, a doubled space, a hyphen where a date range wants a dash, a skill listed
twice — and is applied without asking, then named so the change is visible. ADVISE is a
readability call that needs an editor: a bullet that runs to four lines, a role whose bullets
switch tense halfway, a phrase that appears three times, an opener like "responsible for". ASK is
a gap only the candidate can fill: an accomplishment with no outcome attached, a role with no
dates, a current role with no numbers anywhere.

Nothing here touches a fact. A FIX changes punctuation, spacing and capitalisation only, which is
why it can be applied unattended; the caller still runs the verifier afterwards, because that is
the check that matters and it is cheap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from resume_tailor.review.models import Finding, Level, Review
from resume_tailor.verify.source import Area, Kind, Line, scan

if TYPE_CHECKING:
    from resume_tailor.verify.source import Source

__all__ = ["apply_fixes", "review_and_fix", "review_resume"]

_LONG_BULLET_WORDS = 40
_LONG_SUMMARY_WORDS = 70
_MANY_BULLETS = 6
_MANY_SKILLS = 40
_MANY_SEMICOLONS = 2
_MAX_ROUNDS = 4
_PHRASE_WORDS = 4
_MIN_INFLECTED = 4
_QUOTE_CHARS = 60
_TERMINAL = ".!?"
_UNFINISHED = ":;,"

_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_LEAD_IN = re.compile(r"^(?P<lead>[-*] \*\*[^*]+?:\*\*)(?P<gap> *)(?P<rest>.*)$")
_SKILL_LINE = re.compile(r"^\*\*(?P<label>[^*]+?):\*\*\s*(?P<items>.*)$")
_DOUBLE_STOP = re.compile(r"(?<!\.)\.\.(?!\.)")
_SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:])(?=\s|$)")
_HYPHEN_RANGE = re.compile(r"(?<=[0-9A-Za-z]) - (?=[0-9A-Za-z])")
_LOWER_PRESENT = re.compile(r"\b(present|current)\b")
_DIGIT = re.compile(r"[0-9]")
_WORD = re.compile(r"[a-z]+")
_OUTCOME_TOKEN = re.compile(r"[a-z%$]+")

_WEAK_OPENERS = (
    "responsible for",
    "helped ",
    "worked on",
    "assisted",
    "participated in",
    "involved in",
    "duties included",
    "tasked with",
    "was part of",
)
_FILLER = (
    "synergy",
    "leverage",
    "leveraged",
    "leveraging",
    "results-driven",
    "detail-oriented",
    "team player",
    "go-getter",
    "passionate",
    "dynamic",
    "guru",
    "ninja",
    "rockstar",
    "cutting-edge",
    "world-class",
    "best-in-class",
    "seamless",
    "seamlessly",
    "robust",
    "utilize",
    "utilized",
)
_PAST_IRREGULAR = frozenset(
    {
        "led",
        "built",
        "wrote",
        "cut",
        "grew",
        "ran",
        "drove",
        "set",
        "made",
        "took",
        "won",
        "brought",
        "kept",
        "held",
        "sold",
        "taught",
        "found",
        "spent",
        "met",
        "put",
        "gave",
        "began",
        "became",
        "chose",
        "drew",
        "paid",
        "read",
        "rose",
        "saw",
        "sent",
        "stood",
        "threw",
        "understood",
        "shipped",
        "oversaw",
        "rebuilt",
        "co-designed",
    }
)
_OUTCOME_WORDS = frozenset(
    {
        "cut",
        "reduced",
        "reducing",
        "increased",
        "increasing",
        "saved",
        "saving",
        "launched",
        "shipped",
        "grew",
        "improved",
        "eliminated",
        "automated",
        "migrated",
        "replaced",
        "resolved",
        "delivered",
        "enabled",
        "prevented",
        "doubled",
        "tripled",
        "halved",
        "first",
        "fastest",
        "zero",
        "retired",
        "sunset",
        "%",
        "$",
    }
)
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "by",
        "from",
        "that",
        "this",
        "as",
        "at",
        "or",
        "its",
        "it",
        "into",
        "across",
        "every",
        "one",
    }
)


@dataclass(frozen=True, slots=True)
class _Role:
    """One ``### `` entry in the experience section and the lines that belong to it."""

    entry: Line
    meta: Line | None
    bullets: tuple[Line, ...]


def review_resume(markdown: str) -> Review:
    """Review resume ``markdown`` and return every finding, in line order."""
    source = scan(markdown)
    roles = _roles(source)
    findings = [
        *_whitespace(markdown.splitlines()),
        *_lead_ins(source),
        *_punctuation(source),
        *_dates(source),
        *_duplicate_skills(source),
        *_lengths(source, roles),
        *_tense(roles),
        *_openers(roles),
        *_filler(source),
        *_repetition(roles),
        *_outcomes(roles),
        *_structure(source, roles),
    ]
    findings.sort(key=lambda finding: (finding.line, finding.rule))
    return Review(tuple(findings))


def apply_fixes(markdown: str) -> tuple[str, tuple[Finding, ...]]:
    """Apply every FIX the review finds, and return the text with the fixes that were made.

    One fix per line per round: two rules can each rewrite the same line, and applying both
    replacements at once would lose one. A rule that still has something to say gets its turn
    in the next round, and the loop ends when a round finds nothing.
    """
    applied: list[Finding] = []
    for _ in range(_MAX_ROUNDS):
        fixes = review_resume(markdown).fixes
        if not fixes:
            break
        lines = markdown.splitlines()
        touched: set[int] = set()
        for fix in fixes:
            if fix.line in touched:
                continue
            lines[fix.line - 1] = fix.replacement
            touched.add(fix.line)
            applied.append(fix)
        trailing = "\n" if markdown.endswith("\n") else ""
        markdown = "\n".join(lines) + trailing
    return markdown, tuple(applied)


def review_and_fix(markdown: str) -> tuple[str, Review]:
    """Fix what can be fixed, then review what remains; the review records the fixes made."""
    fixed, applied = apply_fixes(markdown)
    return fixed, Review(review_resume(fixed).findings, applied)


# --- the document, grouped ------------------------------------------------------------------------
def _roles(source: Source) -> list[_Role]:
    """Group the experience section into one role per ``### `` entry."""
    roles: list[_Role] = []
    current: list[Line] = []
    for line in source.lines:
        if line.kind in (Kind.ENTRY, Kind.HEADING):
            if current:
                roles.append(_role(current))
            current = [line] if line.kind is Kind.ENTRY and line.area is Area.EXPERIENCE else []
        elif current:
            current.append(line)
    if current:
        roles.append(_role(current))
    return roles


def _role(lines: list[Line]) -> _Role:
    meta = next((line for line in lines[1:] if line.kind is Kind.META), None)
    bullets = tuple(line for line in lines[1:] if line.kind is Kind.BULLET)
    return _Role(lines[0], meta, bullets)


def _content(line: Line) -> str:
    """Return the words of a bullet, without the marker and any bold lead-in label."""
    match = _LEAD_IN.match(line.text)
    return match["rest"].strip() if match else line.body


def _quote(line: Line) -> str:
    content = _content(line) if line.kind is Kind.BULLET else line.body or line.text
    return content if len(content) <= _QUOTE_CHARS else content[: _QUOTE_CHARS - 1].rstrip() + "…"


def _experience_bullets(source: Source) -> list[Line]:
    return [
        line for line in source.lines if line.kind is Kind.BULLET and line.area is Area.EXPERIENCE
    ]


# --- FIX: safe to apply unattended ----------------------------------------------------------------
def _whitespace(raw: list[str]) -> list[Finding]:
    """Doubled spaces inside a line and trailing spaces, outside HTML comments.

    The template's leading comment aligns its syntax table with runs of spaces on purpose, so
    comment lines are left exactly as they are.
    """
    found: list[Finding] = []
    inside = False
    for number, line in enumerate(raw, start=1):
        if "<!--" in line:
            inside = True
        if inside:
            inside = "-->" not in line
            continue
        fixed = _INNER_SPACES.sub(" ", line.rstrip())
        if fixed != line:
            message = "doubled or trailing spaces"
            found.append(Finding("whitespace", Level.FIX, number, line.strip(), message, fixed))
    return found


def _lead_ins(source: Source) -> list[Finding]:
    """Give a bold lead-in one space after it and a capital letter to follow."""
    found: list[Finding] = []
    for line in source.lines:
        if line.kind is not Kind.BULLET:
            continue
        match = _LEAD_IN.match(line.text)
        if match is None or not match["rest"]:
            continue
        rest = match["rest"]
        first = rest.split(" ", 1)[0]
        if first.isalpha() and first.islower():
            rest = rest[0].upper() + rest[1:]
        fixed = f"{match['lead']} {rest}"
        if fixed != line.text:
            message = "one space and a capital letter after the lead-in"
            found.append(Finding("lead-in", Level.FIX, line.number, line.text, message, fixed))
    return found


def _punctuation(source: Source) -> list[Finding]:
    """End every experience bullet the way most of them end, and collapse doubled marks."""
    found: list[Finding] = []
    bullets = _experience_bullets(source)
    ended = [line for line in bullets if line.text[-1] in _TERMINAL]
    if bullets and len(ended) * 2 >= len(bullets):
        for line in bullets:
            if line.text[-1] not in _TERMINAL + _UNFINISHED:
                message = "a full stop, like the other bullets"
                fixed = line.text + "."
                found.append(
                    Finding("full-stop", Level.FIX, line.number, line.text, message, fixed)
                )
    for line in source.lines:
        if line.kind in (Kind.HEADING, Kind.ENTRY):
            continue
        fixed = _SPACE_BEFORE_PUNCT.sub(r"\1", _DOUBLE_STOP.sub(".", line.text))
        if fixed != line.text:
            message = "doubled punctuation, or a space before a mark"
            found.append(Finding("punctuation", Level.FIX, line.number, line.text, message, fixed))
    return found


def _dates(source: Source) -> list[Finding]:
    """Date ranges take an en dash, and 'present' is a proper word on a dates line."""
    found: list[Finding] = []
    for line in source.lines:
        if line.kind is not Kind.META:
            continue
        fixed = _HYPHEN_RANGE.sub(" – ", line.text)
        fixed = _LOWER_PRESENT.sub(lambda match: match.group(1).capitalize(), fixed)
        if fixed != line.text:
            message = "an en dash in the date range, and Present capitalised"
            found.append(Finding("dates", Level.FIX, line.number, line.text, message, fixed))
    return found


def _duplicate_skills(source: Source) -> list[Finding]:
    """Drop a skill listed in an earlier group from the later one."""
    found: list[Finding] = []
    seen: set[str] = set()
    for line in source.lines:
        if line.kind is not Kind.SKILL or line.area is not Area.SKILLS:
            continue
        match = _SKILL_LINE.match(line.text)
        if match is None:  # pragma: no cover - Kind.SKILL is only assigned to lines that match
            continue
        items = _split_items(match["items"])
        kept = [item for item in items if item.casefold() not in seen]
        dropped = [item for item in items if item.casefold() in seen]
        seen.update(item.casefold() for item in kept)
        if dropped:
            fixed = f"**{match['label']}:** {', '.join(kept)}".rstrip()
            message = "already listed in an earlier skills group"
            found.append(
                Finding(
                    "duplicate-skill", Level.FIX, line.number, ", ".join(dropped), message, fixed
                )
            )
    return found


def _split_items(text: str) -> list[str]:
    """Split ``a, b (c, d), e`` on the commas outside parentheses."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


# --- ADVISE: an editor's call ---------------------------------------------------------------------
def _lengths(source: Source, roles: list[_Role]) -> list[Finding]:
    found: list[Finding] = []
    for line in _experience_bullets(source):
        words = len(_content(line).split())
        if words > _LONG_BULLET_WORDS:
            message = (
                f"{words} words; a bullet should fit two or three lines, so split it or cut to "
                "the outcome"
            )
            found.append(Finding("long-bullet", Level.ADVISE, line.number, _quote(line), message))
        if line.body.count(";") > _MANY_SEMICOLONS:
            message = "three or more clauses stitched with semicolons; split it into bullets"
            found.append(Finding("semicolons", Level.ADVISE, line.number, _quote(line), message))
    found += _summary_length(source)
    found += _skills_count(source)
    for role in roles:
        if len(role.bullets) > _MANY_BULLETS:
            message = f"{len(role.bullets)} bullets; keep the six that matter most for this role"
            found.append(
                Finding("many-bullets", Level.ADVISE, role.entry.number, role.entry.body, message)
            )
    return found


def _summary_length(source: Source) -> list[Finding]:
    in_summary = False
    words = 0
    first: Line | None = None
    for line in source.lines:
        if line.kind is Kind.HEADING:
            in_summary = "summary" in line.text.casefold()
        elif in_summary and line.kind is Kind.PROSE:
            words += len(line.body.split())
            first = first or line
    if first is not None and words > _LONG_SUMMARY_WORDS:
        message = (
            f"{words} words; a summary is read in five seconds, so keep it under "
            f"{_LONG_SUMMARY_WORDS}"
        )
        return [Finding("long-summary", Level.ADVISE, first.number, _quote(first), message)]
    return []


def _skills_count(source: Source) -> list[Finding]:
    lines = [line for line in source.lines if line.kind is Kind.SKILL and line.area is Area.SKILLS]
    total = sum(len(_split_items(line.body)) for line in lines)
    if lines and total > _MANY_SKILLS:
        message = (
            f"{total} skills; a reader scans about {_MANY_SKILLS}, so keep the ones the target "
            "role screens for"
        )
        return [Finding("many-skills", Level.ADVISE, lines[0].number, lines[0].body, message)]
    return []


def _tense(roles: list[_Role]) -> list[Finding]:
    """Bullets under one role should agree on tense."""
    found: list[Finding] = []
    for role in roles:
        openers = {_tense_of(_opener(line)): _opener(line) for line in role.bullets}
        openers.pop("", None)
        if len(openers) > 1:
            ing, past = openers.get("ing", ""), openers.get("past", "")
            message = (
                f"bullets switch between '{ing}' and '{past}'; pick present tense for a current "
                "role, past for the rest"
            )
            found.append(
                Finding("tense", Level.ADVISE, role.entry.number, role.entry.body, message)
            )
    return found


def _opener(line: Line) -> str:
    content = _content(line)
    return content.split(" ", 1)[0].strip(".,;:").casefold() if content else ""


def _tense_of(word: str) -> str:
    if word.endswith("ing") and len(word) > _MIN_INFLECTED:
        return "ing"
    if (word.endswith("ed") and len(word) > _MIN_INFLECTED - 1) or word in _PAST_IRREGULAR:
        return "past"
    return ""


def _openers(roles: list[_Role]) -> list[Finding]:
    found: list[Finding] = []
    for role in roles:
        for line in role.bullets:
            content = _content(line).casefold()
            if any(content.startswith(weak) for weak in _WEAK_OPENERS):
                message = (
                    "opens with an activity, not an accomplishment; start with what you did and "
                    "what it produced"
                )
                found.append(
                    Finding("weak-opener", Level.ADVISE, line.number, _quote(line), message)
                )
    return found


def _filler(source: Source) -> list[Finding]:
    found: list[Finding] = []
    for line in source.lines:
        if line.kind not in (Kind.BULLET, Kind.PROSE):
            continue
        folded = line.body.casefold()
        hits = [word for word in _FILLER if re.search(rf"\b{re.escape(word)}\b", folded)]
        if hits:
            message = f"filler: {', '.join(hits)}; say what was actually done instead"
            found.append(Finding("filler", Level.ADVISE, line.number, _quote(line), message))
    return found


def _repetition(roles: list[_Role]) -> list[Finding]:
    """Flag a four-word phrase that appears in two bullets; it reads as padding."""
    seen: dict[tuple[str, ...], int] = {}
    reported: set[tuple[int, int]] = set()
    found: list[Finding] = []
    for role in roles:
        for line in role.bullets:
            words = _WORD.findall(_content(line).casefold())
            grams = {
                tuple(words[index : index + _PHRASE_WORDS])
                for index in range(len(words) - _PHRASE_WORDS + 1)
            }
            for gram in sorted(grams):
                if all(word in _STOPWORDS for word in gram):
                    continue
                earlier = seen.setdefault(gram, line.number)
                if earlier != line.number and (earlier, line.number) not in reported:
                    reported.add((earlier, line.number))
                    message = f"repeats '{' '.join(gram)}' from line {earlier}; say it once"
                    found.append(
                        Finding("repetition", Level.ADVISE, line.number, _quote(line), message)
                    )
    return found


# --- ASK: only the candidate knows ----------------------------------------------------------------
def _outcomes(roles: list[_Role]) -> list[Finding]:
    found: list[Finding] = []
    for role in roles:
        for line in role.bullets:
            content = _content(line)
            tokens = set(_OUTCOME_TOKEN.findall(content.casefold()))
            if _DIGIT.search(content) or tokens & _OUTCOME_WORDS:
                continue
            message = (
                "What did this achieve? Add a number, a scale, or the decision you owned, or cut "
                "it."
            )
            found.append(Finding("no-outcome", Level.ASK, line.number, _quote(line), message))
    return found


def _structure(source: Source, roles: list[_Role]) -> list[Finding]:
    found: list[Finding] = []
    headings = [line for line in source.lines if line.kind is Kind.HEADING]
    if not any("summary" in line.text.casefold() for line in headings):
        line = headings[0].number if headings else 1
        message = (
            "There is no Summary. What is the two-line pitch: target role, and the three "
            "strengths that back it?"
        )
        found.append(Finding("no-summary", Level.ASK, line, "", message))
    if not any(line.area is Area.HEADER and "|" in line.text for line in source.lines):
        message = "There is no contact line. Which email, phone and links should a recruiter use?"
        found.append(Finding("no-contact", Level.ASK, 1, "", message))
    for role in roles:
        if role.meta is None:
            message = "When was this, and where? Add the dates line under the heading."
            found.append(
                Finding("no-dates", Level.ASK, role.entry.number, role.entry.body, message)
            )
        if not role.bullets:
            message = "What did you accomplish here? A role with no bullets reads as a gap."
            found.append(
                Finding("no-bullets", Level.ASK, role.entry.number, role.entry.body, message)
            )
    if (
        roles
        and roles[0].bullets
        and not any(_DIGIT.search(line.body) for line in roles[0].bullets)
    ):
        message = (
            "Your most recent role has no numbers at all. What can be counted: people, records, "
            "money, time, traffic?"
        )
        found.append(
            Finding("no-numbers", Level.ASK, roles[0].entry.number, roles[0].entry.body, message)
        )
    return found
