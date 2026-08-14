"""Read the dates a resume prints, at the precision it prints them.

A resume writes ``Mar 2021 – Present`` where the profile stores ``2021-03``; both have to become
the same comparable point before a widened tenure can be caught. Precision is preserved rather
than filled in, because filling it in invents a lie that is not there: a resume saying ``2020`` is
not claiming January, so comparing it against a profile's ``2020-06`` at month precision would
report a violation on a line that is true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "PRESENT",
    "Point",
    "Range",
    "Span",
    "earlier",
    "find_points",
    "parse_point",
    "read_range",
]

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_ABBREVIATION = 3
_MONTHS = {name[:_ABBREVIATION]: index for index, name in enumerate(_MONTH_NAMES, start=1)}
_PRESENT_YEAR = 9999

# The leading (?<![0-9]) stops a five-digit zip code from reading as a year plus a stray digit.
_POINT = re.compile(
    r"(?<![0-9])(?:"
    r"(?P<name>[A-Za-z]{3,9})\.?\s+(?P<named_year>[0-9]{4})(?![0-9])"
    r"|(?P<iso_year>[0-9]{4})-(?P<iso_month>0[1-9]|1[0-2])(?![0-9])"
    r"|(?P<slash_month>0?[1-9]|1[0-2])/(?P<slash_year>[0-9]{4})(?![0-9])"
    r"|(?P<year>[0-9]{4})(?![0-9])"
    r"|(?<![A-Za-z])(?P<present>present|current|now)\b"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Point:
    """One end of a date range. ``month`` is 0 when the source stated only a year."""

    year: int
    month: int = 0


PRESENT = Point(_PRESENT_YEAR)


@dataclass(frozen=True, slots=True)
class Span:
    """A date found in text, and the characters it occupies."""

    point: Point
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Range:
    """The period a resume line prints, and the exact text that prints it."""

    start: Point
    end: Point
    text: str


def earlier(first: Point, second: Point) -> bool:
    """Report whether ``first`` falls before ``second``, at the precision both sides state."""
    if first.year != second.year:
        return first.year < second.year
    if not first.month or not second.month:
        return False
    return first.month < second.month


def parse_point(value: str) -> Point:
    """Turn a profile date (``YYYY``, ``YYYY-MM``, or ``present``) into a comparable point."""
    if value == "present":
        return PRESENT
    year, _, month = value.partition("-")
    return Point(int(year), int(month) if month else 0)


def find_points(text: str) -> tuple[Span, ...]:
    """Find every date ``text`` states, in order, with the characters each one occupies."""
    return tuple(_span(match) for match in _POINT.finditer(text))


def read_range(text: str) -> Range | None:
    """Read the period a resume line prints, or ``None`` when it prints none."""
    spans = find_points(text)
    if not spans:
        return None
    return Range(spans[0].point, spans[-1].point, text[spans[0].start : spans[-1].end])


def _span(match: re.Match[str]) -> Span:
    if match["present"]:
        return Span(PRESENT, match.start(), match.end())
    if match["iso_year"]:
        point = Point(int(match["iso_year"]), int(match["iso_month"]))
        return Span(point, match.start(), match.end())
    if match["slash_year"]:
        point = Point(int(match["slash_year"]), int(match["slash_month"]))
        return Span(point, match.start(), match.end())
    if match["named_year"]:
        # "Remote 2021" is a location and a year, not a month and a year: keep only the year.
        month = _MONTHS.get(match["name"][:_ABBREVIATION].casefold(), 0)
        start = match.start() if month else match.start("named_year")
        return Span(Point(int(match["named_year"]), month), start, match.end())
    return Span(Point(int(match["year"])), match.start("year"), match.end())
