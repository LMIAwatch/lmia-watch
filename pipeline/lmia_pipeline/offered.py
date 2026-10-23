"""What LMIA-flagged Job Bank postings offered: posted-wage tables for the occupation pages.

Why: the occupation pages compare one median posted minimum with the Job Bank
median and Statistics Canada's offered wage. A reader asking whether flagged
postings advertise low, typical or high wages needs the spread too, and how
it moves month to month. These tables give it from the nightly archive
(jobbank_observations), as statistics of the postings and never the postings
themselves.

Rules (docs/occupations.md states them in full, the page in short):
- A posting counts when a nightly pass saw it with an LMIA flag, requested or
  approved. A flag that lapsed later does not take it out: the tables describe
  what postings offered while they carried the flag.
- It counts once, in the month (UTC) of its first_seen. A posting seen on many
  nights, or seen again after a month ends, is still one posting in one month.
- It belongs to an occupation only when its page gave a five-digit NOC 2021
  code, and to an economic region when its postal area places it in one
  (places.py reads both the same way for the wage block above).
- Quartiles use hourly postings only. A posting stated in another unit (the
  parser stores YEAR, WEEK, WEEKLY, BIWEEK, BIWEEKLY, SEMIMONTH, MONTH, DAY) is counted under its
  unit and never converted: hours a week and weeks a year are not on the
  posting, so any conversion would invent them. A posting with no wage or no
  unit is counted as unstated.
- Quartiles: the 25th, 50th and 75th percentiles by linear interpolation
  between ranks (statistics.quantiles, method "inclusive"), rounded to the cent.
- A table or a month with fewer than THRESHOLD hourly postings shows its counts
  and withholds its figures: a quartile of a handful of postings describes a
  few employers, not the occupation. A regional table is written only once
  the region holds THRESHOLD postings of the occupation; until then those
  postings count in the national table alone.
"""

from __future__ import annotations

import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict

THRESHOLD = 10
FLAGS = ("requested", "approved")
# The list pages give a unit word the parser maps to HOUR, YEAR, WEEK, MONTH,
# BIWEEK, SEMIMONTH or DAY (normalize.parse_salary_text); the posting pages
# give schema.org's unitText, which spells some of them differently (WEEKLY,
# BIWEEKLY). One spelling per unit, so a unit is not split across two counts.
# Nothing is converted.
UNIT_ALIASES = {
    "HOURLY": "HOUR", "YEARLY": "YEAR", "ANNUAL": "YEAR", "ANNUALLY": "YEAR", "WEEKLY": "WEEK",
    "BIWEEKLY": "BIWEEK", "BI-WEEKLY": "BIWEEK", "SEMIMONTHLY": "SEMIMONTH", "SEMI-MONTHLY": "SEMIMONTH",
    "MONTHLY": "MONTH", "DAILY": "DAY",
}
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])")


def unit_of(raw: str | None) -> str | None:
    text = (raw or "").strip().upper()
    return UNIT_ALIASES.get(text, text) or None


def _amount(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(value) and value > 0 else None


def quartiles(values: list[float]) -> list[float] | None:
    """[25th, median, 75th] rounded to the cent, or None for no values."""
    if not values:
        return None
    if len(values) == 1:
        v = round(values[0], 2)
        return [v, v, v]
    return [round(q, 2) for q in statistics.quantiles(values, n=4, method="inclusive")]


def _months_between(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    end = (int(last[:4]), int(last[5:7]))
    out: list[str] = []
    while (y, m) <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class Cell:
    """The postings of one table: an occupation, or an occupation in one economic region."""

    __slots__ = ("postings", "mins", "maxes", "other", "unstated", "months")

    def __init__(self) -> None:
        self.postings = 0
        self.mins: list[float] = []
        self.maxes: list[float] = []
        self.other: Counter = Counter()
        self.unstated = 0
        self.months: dict[str, list] = {}           # month -> [postings, hourly posted minimums]

    def add(self, month: str, unit: str | None, low: float | None, high: float | None) -> None:
        self.postings += 1
        entry = self.months.setdefault(month, [0, []])
        entry[0] += 1
        if low is None or unit is None:
            self.unstated += 1
        elif unit == "HOUR":
            self.mins.append(low)
            self.maxes.append(high if high is not None else low)
            entry[1].append(low)
        else:
            self.other[unit] += 1


class Archive:
    """Every flagged posting with an occupation code, by occupation and by occupation and region."""

    def __init__(self, first: str | None = None, last: str | None = None) -> None:
        self.national: dict[str, Cell] = defaultdict(Cell)
        self.regional: dict[str, dict[str, Cell]] = defaultdict(lambda: defaultdict(Cell))
        self.first = first                          # month of the archive's first and newest night
        self.last = last

    def add(self, noc: str, er: str | None, first_seen: str | None, unit_raw: str | None,
            wage_min: float | None, wage_max: float | None) -> None:
        m = MONTH_RE.match(first_seen or "")
        if not m:
            return  # a posting that cannot be placed in a month cannot be counted once by month
        month = m.group(0)
        # Job Bank writes a single figure as both ends of the range; a missing
        # minimum falls back to the maximum, as the wage block above reads it.
        low = _amount(wage_min) if wage_min is not None else _amount(wage_max)
        high = _amount(wage_max) or low
        unit = unit_of(unit_raw)
        self.national[noc].add(month, unit, low, high)
        if er:
            self.regional[noc][er].add(month, unit, low, high)
        self.first = month if self.first is None or month < self.first else self.first
        self.last = month if self.last is None or month > self.last else self.last

    def months(self) -> list[str]:
        """Every month from the archive's start to its newest night, empty months included."""
        if not self.first or not self.last:
            return []
        return _months_between(self.first, self.last)


def flagged(conn: sqlite3.Connection) -> set[int]:
    """Postings some nightly pass saw with an LMIA flag, whatever their flag is now."""
    marks = ",".join("?" * len(FLAGS))
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT posting_id FROM jobbank_observations WHERE flag IN ({marks})", FLAGS)}


def span(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    """Months of the archive's first and newest nights, so the series runs to the present."""
    first, last = conn.execute("SELECT MIN(observed_at), MAX(observed_at) FROM jobbank_observations").fetchone()
    fm = MONTH_RE.match(first or "")
    lm = MONTH_RE.match(last or "")
    return (fm.group(0) if fm else None, lm.group(0) if lm else None)


def _month_row(month: str, entry: list | None) -> list:
    if not entry:
        return [month, 0, 0, None]
    postings, mins = entry
    median = round(statistics.median(mins), 2) if len(mins) >= THRESHOLD else None
    return [month, postings, len(mins), median]


def table(cell: Cell | None, months: list[str]) -> dict:
    """One table as the occupation file carries it; figures are None below the threshold."""
    cell = cell or Cell()
    published = len(cell.mins) >= THRESHOLD
    return {
        "postings": cell.postings,
        "hourly_n": len(cell.mins),
        "other": sorted(([u, n] for u, n in cell.other.items()), key=lambda r: (-r[1], r[0])),
        "unstated": cell.unstated,
        "min": quartiles(cell.mins) if published else None,
        "max": quartiles(cell.maxes) if published else None,
        "months": [_month_row(m, cell.months.get(m)) for m in months],
    }
