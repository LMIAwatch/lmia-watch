"""Program conditions: the JSON behind /program (program/index.json).

sources/program.py stores every edition of three canada.ca pages: LMIA
processing times by stream, the unemployment rates behind the low-wage refusal
to process by census metropolitan area, and the provincial and territorial
wage thresholds. This file writes them for the page, newest first, each
edition with the page it was read from and the day it was first read, plus the
quarters the low-wage indicator judges on ESDC's lists rather than on
Statistics Canada's rates.

In force: an edition of the CMA list or of the wage thresholds is in force on
a date when it took effect on or before that date, the page states no last day
before it, and no later edition has taken effect. One that has not taken
effect yet is upcoming; the others are past. Processing times are a monthly
measure, not a rule: the newest month is the latest and the rest are past.
Every status is worked out for the export date (as_of), which the page shows.

Output (under data/out/static), about 10 KB:
  program/index.json
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import indicators, releases
from .db import get_meta
from .normalize import period_sort_key
from .sources import program

SERIES = (program.TIMES, program.CMA, program.THRESHOLDS)


def _statuses(series: str, editions: list[dict], today: str) -> None:
    """Mark each edition (newest first) latest, in_force, upcoming or past."""
    if series == program.TIMES:
        for i, ed in enumerate(editions):
            ed["status"] = "latest" if i == 0 else "past"
        return
    current = None
    for ed in editions:
        if ed["period"] > today:
            ed["status"] = "upcoming"
        elif current is None and (ed["to"] is None or ed["to"] >= today):
            ed["status"] = "in_force"
            current = ed
        else:
            # Its last day has passed, or a later edition has taken its place.
            ed["status"] = "past"


def _last_quarter(conn: sqlite3.Connection, lists: dict[str, indicators.CmaList]) -> tuple[int, int] | None:
    """The newest quarter the indicator can be asked about: the newest ESDC
    period, or the quarter the newest stored list took effect in."""
    candidates: list[tuple[int, int]] = []
    latest = get_meta(conn, "esdc_latest_period")
    if latest and period_sort_key(latest) != (0, 0):
        candidates.append(period_sort_key(latest))
    for lst in lists.values():
        year, month = int(lst.start[:4]), int(lst.start[5:7])
        candidates.append((year, (month - 1) // 3 + 1))
    return max(candidates) if candidates else None


def build(conn: sqlite3.Connection, today: str | None = None) -> dict | None:
    """The file's content, or None when no edition of any series is stored."""
    as_of = today or datetime.now(timezone.utc).date().isoformat()
    series_out: dict[str, dict] = {}
    for series in SERIES:
        src = program.SOURCES[series]
        editions = program.editions(conn, series)
        _statuses(series, editions, as_of)
        checked = get_meta(conn, f"program_{series}_checked_at")
        series_out[series] = {
            "source": {"en": src.url, "fr": src.url_fr},
            "checked": checked[:10] if checked else None,
            "editions": editions,
        }
    if not any(s["editions"] for s in series_out.values()):
        return None
    lists = indicators.load_cma_lists(conn)
    last = _last_quarter(conn, lists)
    bases = indicators.quarter_bases(lists, last) if last else []
    return {
        "as_of": as_of,
        "series": series_out,
        "indicator_bases": bases,
    }


def write_all(conn: sqlite3.Connection, out: Path, today: str | None = None) -> dict[str, int]:
    """Write program/index.json under `out`; nothing when no edition is stored."""
    data = build(conn, today)
    if data is None:
        return {"program_files": 0}
    return {"program_files": 1, "program_bytes": releases._dump(out / "program" / "index.json", data)}


def sitemap_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    """/program, dated by the newest edition read, once any edition is stored."""
    newest = conn.execute("SELECT MAX(read_at) FROM program_editions").fetchone()[0]
    return [("/program", newest[:10])] if newest else []
