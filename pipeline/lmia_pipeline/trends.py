"""Trends: the JSON behind /trends, built on the aggregation in releases.py.

The release pages compare one ESDC release with the previous one, and the
rankings give one year at a time. These files hold each series whole, so the
Worker can draw it as a chart with its table: approved positions, approved
rows (employer records) and refused rows for every ESDC period, the same by
stream and by province, and the daily count of Job Bank postings flagged
"LMIA requested".

Periods are ESDC's own: an annual file for 2014 (June 20 to December 31),
2015 and 2016, one file for 2017 Q1 and Q2, and one file a quarter from
2017 Q3. Each period carries its first and last day, so a chart can draw a
file across the quarters it covers; nothing is split or interpolated here.
A period with no negative file (2021 Q2) has no refused figure (None), never
a zero.

Year over year: quarterly volumes are seasonal (farm approvals peak in the
first half), so the comparisons are the latest quarter against the same
quarter a year earlier, the year to date against the same quarters of the
year before, and the last complete year against the one before it. A
comparison that would need part of a multi-quarter file (2017 Q1 alone, say)
is None rather than an estimate.

Complete passes (pending.json): the jobbank stage writes one sources_log row
per pass when it ends, and stamps every observation of the pass with the
time the pass began. A pass counts when its row has ok = 1 (no fetch
failure, page cap or budget stop), is not a "skipped" row, and listed at
least PASS_SHARE of the median listed count of the other ok passes within
PASS_WINDOW_DAYS on either side; a lone pass with no neighbour counts. The
listed check leaves out short development sweeps run with --limit, which end
cleanly with ok = 1. Each observation stamp belongs to the first non-skipped
row logged at or after it. A point is the number of postings observed with
the "requested" flag at that stamp (private households are never stored, so
they are not in it), dated by the UTC day the pass ended; if two complete
passes end on the same day, the later one stands.

Output (under data/out/static/trends), each well under 20 KB:
  national.json   per period and per calendar year, and the comparisons
  streams.json    by stream, from the first period whose rows carry one
  provinces.json  by province or territory (UN: not recorded)
  pending.json    the daily pending series
The three ESDC files also name where two of the page's caveats begin: the
first period with NOC 2021 codes (noc2021_from) and the first with streams
(streams_from).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from . import releases
from .normalize import period_end_date, period_quarters, period_start_date

# ESDC says the 2014 lists cover LMIAs issued from June 20 to December 31, 2014.
COVERAGE_START = {"2014": "2014-06-20"}

PASS_SHARE = 0.5
PASS_WINDOW_DAYS = 14

STREAM_ORDER = (*releases.STREAMS, releases.OTHER_STREAM)


def _quarters(period: str) -> list[tuple[int, int]]:
    return period_quarters(period)


def _year(period: str) -> int:
    return _quarters(period)[0][0]


def _pct(now: int, then: int) -> float | None:
    return round((now - then) * 100 / then, 1) if then else None


def compare(now: int | None, then: int | None) -> dict | None:
    """Two figures and their difference, or None when either is missing."""
    if now is None or then is None:
        return None
    return {"now": now, "then": then, "change": now - then, "pct": _pct(now, then)}


class _Series:
    """The per-period figures the three ESDC files share."""

    def __init__(self, d: releases._Data) -> None:
        self.d = d
        self.periods = list(d.periods)
        self.refused_file = {p: any(r["dataset"] == "negative" for r in d.resources[p]) for p in self.periods}
        self.single = {(_year(p), _quarters(p)[0][1]): p for p in self.periods if len(_quarters(p)) == 1}
        # Where two of the page's caveats begin, named in every file.
        self.marks = {
            "noc2021_from": next((p for p in self.periods if any(releases.noc_era(c) == "2021" for c in d.noc.get(p, {}))), None),
            "streams_from": next(iter(_stream_periods(d, self.periods)), None),
        }

    def meta(self, period: str) -> dict:
        return {
            "p": period,
            "start": COVERAGE_START.get(period, period_start_date(period)),
            "end": period_end_date(period),
            "quarters": len(_quarters(period)),
        }

    def refused(self, period: str) -> int | None:
        if not self.refused_file[period]:
            return None
        agg = self.d.neg_totals.get(period)
        return agg.rows if agg else 0

    def figures(self, period: str) -> dict:
        t = self.d.totals(period)
        return {"positions": t["positions"], "rows": t["positive_rows"], "employers": t["employers"],
                "refused": self.refused(period)}

    def span(self, year: int, quarters: set[int]) -> list[str] | None:
        """The periods of `year` that together cover exactly `quarters`, or None."""
        chosen = [p for p in self.periods if _year(p) == year and {q for _, q in _quarters(p)} <= quarters]
        covered = {q for p in chosen for _, q in _quarters(p)}
        # The 2014 files start on June 20, so no set of 2014's quarters is whole.
        if covered != quarters or any(p in COVERAGE_START for p in chosen):
            return None
        return chosen

    def summed(self, periods: list[str] | None) -> dict | None:
        if periods is None:
            return None
        emps: set[str] = set()
        out = {"positions": 0, "rows": 0, "refused": 0}
        for p in periods:
            f = self.figures(p)
            out["positions"] += f["positions"]
            out["rows"] += f["rows"]
            out["refused"] = None if out["refused"] is None or f["refused"] is None else out["refused"] + f["refused"]
            emps |= set(self.d.pos.get(p, {}))
        out["employers"] = len(emps)
        return out


def _metrics(now: dict | None, then: dict | None) -> dict | None:
    if now is None or then is None:
        return None
    return {k: compare(now[k], then[k]) for k in ("positions", "rows", "employers", "refused")}


def year_over_year(s: _Series) -> dict:
    """The three comparisons for the latest period; each None when it cannot be made."""
    out: dict = {"quarter": None, "ytd": None, "year": None}
    if not s.periods:
        return out
    latest = s.periods[-1]
    lq = _quarters(latest)
    year, q = lq[-1]
    if len(lq) == 1 and (year - 1, q) in s.single:
        then = s.single[(year - 1, q)]
        out["quarter"] = {"now": latest, "then": then, "metrics": _metrics(s.figures(latest), s.figures(then))}
    wanted = set(range(1, q + 1))
    now_p, then_p = s.span(year, wanted), s.span(year - 1, wanted)
    if now_p and then_p:
        out["ytd"] = {"year": year, "quarters": q, "now": now_p, "then": then_p,
                      "metrics": _metrics(s.summed(now_p), s.summed(then_p))}
    # The last complete year and the one before it.
    whole = set(range(1, 5))
    for y in range(year, _year(s.periods[0]), -1):
        a, b = s.span(y, whole), s.span(y - 1, whole)
        if a and b:
            out["year"] = {"now": y, "then": y - 1, "metrics": _metrics(s.summed(a), s.summed(b))}
            break
    return out


def national(s: _Series) -> dict:
    periods = [{**s.meta(p), **s.figures(p)} for p in s.periods]
    by_year: dict[int, list[str]] = defaultdict(list)
    for p in s.periods:
        by_year[_year(p)].append(p)
    years = []
    for y in sorted(by_year):
        covered = sorted({q for p in by_year[y] for _, q in _quarters(p)})
        years.append({
            "year": y,
            "periods": by_year[y],
            "quarters": covered,
            "start": COVERAGE_START.get(by_year[y][0], period_start_date(by_year[y][0])),
            "complete": covered == [1, 2, 3, 4] and not any(p in COVERAGE_START for p in by_year[y]),
            **s.summed(by_year[y]),
        })
    return {
        "periods": periods,
        "years": years,
        "latest": s.periods[-1],
        "published": s.d.published(s.periods[-1]),
        "yoy": year_over_year(s),
        **s.marks,
    }


def _stream_periods(d: releases._Data, periods: list[str]) -> list[str]:
    """Periods where few enough positions lack a stream for a breakdown (as on the release pages)."""
    out = []
    for p in periods:
        total = d.totals(p)["positions"]
        if total and d.pos_stream_missing[p] / total <= releases.STREAM_MISSING_MAX:
            out.append(p)
    return out


def _breakdown_yoy(s: _Series, keys: list[str], value) -> dict | None:
    latest = s.periods[-1]
    lq = _quarters(latest)
    if len(lq) != 1 or (lq[0][0] - 1, lq[0][1]) not in s.single:
        return None
    then = s.single[(lq[0][0] - 1, lq[0][1])]
    rows = []
    for k in keys:
        c = compare(value(latest, k), value(then, k))
        rows.append({"k": k, **c} if c else {"k": k})
    return {"now": latest, "then": then, "rows": rows}


def streams(s: _Series) -> dict | None:
    periods = _stream_periods(s.d, s.periods)
    if not periods:
        return None
    d = s.d
    totals = {k: sum(d.pos_stream.get(p, {}).get(k, releases._Agg()).positions for p in periods) for k in STREAM_ORDER}
    keys = [k for k in sorted(STREAM_ORDER, key=lambda k: (-totals[k], STREAM_ORDER.index(k))) if totals[k] or any(
        d.neg_stream.get(p, {}).get(k) for p in periods)]

    def agg(table: dict, p: str, k: str) -> releases._Agg:
        return table.get(p, {}).get(k) or releases._Agg()

    rows = []
    for p in periods:
        neg = None
        if s.refused_file[p]:
            neg = [agg(d.neg_stream, p, k).rows for k in keys]
        rows.append({
            **s.meta(p),
            "positions": [agg(d.pos_stream, p, k).positions for k in keys],
            "rows": [agg(d.pos_stream, p, k).rows for k in keys],
            "refused": neg,
            "missing": d.pos_stream_missing[p],
            "refused_missing": d.neg_stream_missing[p] if s.refused_file[p] else None,
        })
    return {
        "keys": keys,
        "periods": rows,
        "latest": s.periods[-1],
        "yoy": _breakdown_yoy(s, keys, lambda p, k: agg(d.pos_stream, p, k).positions),
        **s.marks,
    }


def provinces(s: _Series) -> dict:
    d = s.d
    totals: dict[str, int] = defaultdict(int)
    for p in s.periods:
        for k, a in d.pos_prov.get(p, {}).items():
            totals[k] += a.positions
        for k in d.neg_prov.get(p, {}):
            totals.setdefault(k, 0)
    keys = sorted(totals, key=lambda k: (k == releases.UNKNOWN_PROVINCE, -totals[k], k))

    def agg(table: dict, p: str, k: str) -> releases._Agg:
        return table.get(p, {}).get(k) or releases._Agg()

    rows = []
    for p in s.periods:
        rows.append({
            **s.meta(p),
            "positions": [agg(d.pos_prov, p, k).positions for k in keys],
            "rows": [agg(d.pos_prov, p, k).rows for k in keys],
            "refused": [agg(d.neg_prov, p, k).rows for k in keys] if s.refused_file[p] else None,
        })
    return {
        "keys": keys,
        "periods": rows,
        "latest": s.periods[-1],
        "yoy": _breakdown_yoy(s, keys, lambda p, k: agg(d.pos_prov, p, k).positions),
        **s.marks,
    }


# -- the daily pending series ----------------------------------------------------------


def _ts(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def complete_passes(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    """(every non-skipped jobbank pass in time order, each marked complete or not) per the module rule."""
    runs = [dict(r) for r in conn.execute(
        "SELECT id, run_at, detail, rows_in, ok FROM sources_log WHERE source = 'jobbank' ORDER BY run_at, id")]
    runs = [r for r in runs if not (r["detail"] or "").startswith("skipped")]
    ok = [r for r in runs if r["ok"] == 1]
    window = timedelta(days=PASS_WINDOW_DAYS)
    for r in runs:
        r["complete"] = False
        if r["ok"] != 1:
            continue
        at = _ts(r["run_at"])
        others = [o["rows_in"] or 0 for o in ok if o["id"] != r["id"] and abs(_ts(o["run_at"]) - at) <= window]
        r["complete"] = not others or (r["rows_in"] or 0) >= PASS_SHARE * median(others)
    return runs, [r for r in runs if r["complete"]]


def pending_series(conn: sqlite3.Connection) -> list[dict]:
    runs, _ = complete_passes(conn)
    stamps = conn.execute(
        "SELECT observed_at, COUNT(DISTINCT posting_id) AS n FROM jobbank_observations WHERE flag = 'requested' "
        "GROUP BY observed_at").fetchall()
    # A stamp belongs to the first row logged at or after it. A pass killed
    # before it logged leaves a stamp that would land on the next pass's row;
    # only the latest stamp before a row is that row's own pass.
    own: dict[int, tuple[datetime, int]] = {}
    for stamp, n in stamps:
        at = _ts(stamp)
        run = next((r for r in runs if _ts(r["run_at"]) >= at), None)
        if run is not None and (run["id"] not in own or at > own[run["id"]][0]):
            own[run["id"]] = (at, n)
    by_day: dict[str, tuple[str, int]] = {}
    for run in runs:
        if not run["complete"] or run["id"] not in own:
            continue
        day = run["run_at"][:10]
        if day not in by_day or run["run_at"] >= by_day[day][0]:
            by_day[day] = (run["run_at"], own[run["id"]][1])
    return [{"date": day, "n": n} for day, (_, n) in sorted(by_day.items())]


# -- output -------------------------------------------------------------------------------


def write_all(conn: sqlite3.Connection, out: Path) -> dict[str, int]:
    """Write trends/*.json under `out`; returns file count and bytes."""
    written = {"trend_files": 0, "trend_bytes": 0}

    def dump(name: str, obj: object) -> None:
        written["trend_bytes"] += releases._dump(out / "trends" / name, obj)
        written["trend_files"] += 1

    d = releases._Data(conn)
    if d.periods:
        s = _Series(d)
        dump("national.json", national(s))
        stream_file = streams(s)
        if stream_file:
            dump("streams.json", stream_file)
        dump("provinces.json", provinces(s))
    points = pending_series(conn)
    if points:
        dump("pending.json", {"points": points, "first": points[0]["date"], "latest": points[-1]["date"]})
    return written


def sitemap_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    """(path, lastmod) for each view that write_all publishes.

    The ESDC views change when a list is published, so they carry the newest
    publication date; the pending view carries the latest complete pass.
    """
    entries: list[tuple[str, str | None]] = []
    rel = releases.sitemap_entries(conn)
    if rel:
        latest = rel[0][1]
        entries += [("/trends", latest), ("/trends/streams", latest), ("/trends/provinces", latest)]
    points = pending_series(conn)
    if points:
        entries.append(("/trends/pending", points[-1]["date"]))
    return entries
