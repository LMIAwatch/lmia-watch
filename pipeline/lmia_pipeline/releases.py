"""Quarterly release pages and rankings: the JSON behind /releases and /rankings.

Each ESDC release (a quarter, or the annual and half-year files before 2017
Q3) gets one small file the Worker renders as it stands: totals against the
previous release, the largest approvals, employers new to the positive list,
the largest changes from the previous release, approvals and refusals by
province and stream, and the source files with their mirrored copies. The
rankings are yearly and all-time tables of approved positions by province,
stream and occupation, and of employers. The Worker reads one of these files
per page and loops only over the few dozen rows it shows, which keeps a page
inside the free plan's CPU allowance.

Two properties of the files shape what is published:
- Occupations moved from NOC 2011 (four-digit codes) to NOC 2021 (five
  digits) with the 2024 Q2 file. The two classifications do not map one to
  one, so each is ranked on its own and no table adds them together. The
  era comes from the code's length, not from a date.
- The 2014 to 2016 files have no stream column, and from 2017 Q1 to 2019 Q2
  the stream is filled only on the first row of a group, so most of those
  rows load without one. A breakdown by stream is published only where at
  most STREAM_MISSING_MAX of the positions (or, for refusals, of the rows)
  lack one.

Output (under data/out/static):
  releases/index.json      every release, newest first, with its totals
  releases/<slug>.json     one release; the slug is the period in lower case
                           with a hyphen after the year (2026-q1, 2017-q1-q2, 2015)
  rankings/all.json        all-time tables
  rankings/<year>.json     one calendar year's tables
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .normalize import period_quarters, period_sort_key

TOP_EMPLOYERS = 25
TOP_NEW = 15
TOP_CHANGES = 10
TOP_OCCUPATIONS = 25
STREAM_MISSING_MAX = 0.05
UNKNOWN_PROVINCE = "UN"

POSITIVE_DATASET = "90fed587-1364-4f33-a9ee-208181dc0b97"
NEGATIVE_DATASET = "f82f66f2-a22b-4511-bccf-e1d74db39ae5"

# ESDC's spellings of the five streams over the years; anything else (a
# stray "99", "Unspecified") is counted as Other rather than shown as a stream.
STREAMS = ("High Wage", "Low Wage", "Primary Agriculture", "Global Talent Stream", "Permanent Resident Only")
STREAM_ALIASES = {"Global Talent": "Global Talent Stream", "Talent mondial": "Global Talent Stream"}
OTHER_STREAM = "Other"

# The site's download route serves mirror/<name> only for these characters.
MIRROR_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def period_slug(period: str) -> str:
    """'2026Q1' -> '2026-q1', '2017Q1-Q2' -> '2017-q1-q2', '2015' -> '2015'."""
    return re.sub(r"^(\d{4})q", r"\1-q", period.lower())


def stream_key(raw: str | None) -> str | None:
    if not raw:
        return None
    name = STREAM_ALIASES.get(raw.strip(), raw.strip())
    return name if name in STREAMS else OTHER_STREAM


def noc_era(code: str | None) -> str | None:
    if code and re.fullmatch(r"\d{4}", code):
        return "2011"
    if code and re.fullmatch(r"\d{5}", code):
        return "2021"
    return None


def mirror_name(dataset: str, period: str, url: str) -> str | None:
    """The file's name in the checksummed mirror, as export.export_mirror writes it."""
    name = f"{dataset}_{period}_{url.rsplit('/', 1)[-1]}"
    return name if MIRROR_NAME_RE.match(name) else None


def resource_page(dataset: str, resource_id: str) -> str:
    ds = POSITIVE_DATASET if dataset == "positive" else NEGATIVE_DATASET
    return f"https://open.canada.ca/data/en/dataset/{ds}/resource/{resource_id}"


def _published(resources: list) -> str | None:
    """The newest publication date among a release's files (both lists usually share one)."""
    dates = [r["published"][:10] for r in resources if r["published"] and re.match(r"\d{4}-\d{2}-\d{2}", r["published"])]
    return max(dates) if dates else None


def _dump(path: Path, obj: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def _ranked(counter: dict, n: int | None = None) -> list:
    """Keys by value, largest first, ties by key so the files are deterministic."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:n] if n is not None else items


class _Agg:
    """Rows, positions and distinct employers for one breakdown."""

    __slots__ = ("rows", "positions", "employers")

    def __init__(self) -> None:
        self.rows = 0
        self.positions = 0
        self.employers: set[str] = set()

    def add(self, positions: int, employer_id: str) -> None:
        self.rows += 1
        self.positions += positions
        self.employers.add(employer_id)

    def out(self, key: str) -> dict:
        return {"k": key, "rows": self.rows, "positions": self.positions, "employers": len(self.employers)}


def _table(aggs: dict[str, _Agg]) -> list[dict]:
    return [a.out(k) for k, a in sorted(aggs.items(), key=lambda kv: (-kv[1].positions, -kv[1].rows, kv[0]))]


class _Data:
    """One pass over the list rows, aggregated every way the pages need."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.resources: dict[str, list[dict]] = defaultdict(list)
        for r in conn.execute(
            "SELECT resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded FROM esdc_resources"
        ):
            self.resources[r["period"]].append(dict(r))
        # A file whose period could not be read ("unknown") has no place in a sequence of quarters.
        self.periods = sorted((p for p in self.resources if period_quarters(p)), key=lambda p: (period_sort_key(p), p))

        # period -> employer -> [positions, lmias, rows, lmias seen]
        self.pos: dict[str, dict[str, list[int]]] = defaultdict(dict)
        self.names: dict[tuple[str, str], str] = {}
        self.places: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        self.emp_streams: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.pos_prov: dict[str, dict[str, _Agg]] = defaultdict(lambda: defaultdict(_Agg))
        self.pos_stream: dict[str, dict[str, _Agg]] = defaultdict(lambda: defaultdict(_Agg))
        self.pos_stream_missing: Counter = Counter()  # period -> positions with no stream
        self.noc: dict[str, dict[str, list[int]]] = defaultdict(dict)  # period -> code -> [positions, rows]
        self.titles: dict[str, tuple[tuple[int, int], str]] = {}
        self.no_occupation: Counter = Counter()  # period -> rows with no usable code
        for r in conn.execute(
            "SELECT period, employer_id, employer_raw, province, city, stream, noc_code, noc_title, lmias, positions "
            "FROM esdc_records WHERE list = 'positive'"
        ):
            period, eid = r["period"], r["employer_id"]
            positions = int(r["positions"] or 0)
            slot = self.pos[period].setdefault(eid, [0, 0, 0, 0])
            slot[0] += positions
            slot[1] += int(r["lmias"] or 0)
            slot[2] += 1
            slot[3] += r["lmias"] is not None
            key = (period, eid)
            # The largest spelling wins, as on the home page, so a rerun picks the same one.
            if r["employer_raw"] > self.names.get(key, ""):
                self.names[key] = r["employer_raw"]
            city, prov = self.places.get(key, (None, None))
            self.places[key] = (max(filter(None, (city, r["city"])), default=None),
                                max(filter(None, (prov, r["province"])), default=None))
            stream = stream_key(r["stream"])
            self.emp_streams[key][stream or ""] += positions
            self.pos_prov[period][r["province"] or UNKNOWN_PROVINCE].add(positions, eid)
            if stream:
                self.pos_stream[period][stream].add(positions, eid)
            else:
                self.pos_stream_missing[period] += positions
            code = r["noc_code"]
            if noc_era(code):
                cell = self.noc[period].setdefault(code, [0, 0])
                cell[0] += positions
                cell[1] += 1
                if r["noc_title"]:
                    rank = period_sort_key(period)
                    if code not in self.titles or rank >= self.titles[code][0]:
                        self.titles[code] = (rank, r["noc_title"])
            else:
                self.no_occupation[period] += 1

        self.neg_totals: dict[str, _Agg] = defaultdict(_Agg)
        self.neg_prov: dict[str, dict[str, _Agg]] = defaultdict(lambda: defaultdict(_Agg))
        self.neg_stream: dict[str, dict[str, _Agg]] = defaultdict(lambda: defaultdict(_Agg))
        self.neg_stream_missing: Counter = Counter()  # period -> rows with no stream
        self.neg_lmias: Counter = Counter()
        self.neg_lmias_seen: Counter = Counter()
        for r in conn.execute(
            "SELECT period, employer_id, province, stream, lmias, positions FROM esdc_records WHERE list = 'negative'"
        ):
            period, eid = r["period"], r["employer_id"]
            positions = int(r["positions"] or 0)
            self.neg_totals[period].add(positions, eid)
            self.neg_prov[period][r["province"] or UNKNOWN_PROVINCE].add(positions, eid)
            stream = stream_key(r["stream"])
            if stream:
                self.neg_stream[period][stream].add(positions, eid)
            else:
                self.neg_stream_missing[period] += 1
            self.neg_lmias[period] += int(r["lmias"] or 0)
            self.neg_lmias_seen[period] += r["lmias"] is not None

        self.first_positive: dict[str, str] = {}
        for period in self.periods:
            for eid in self.pos.get(period, {}):
                self.first_positive.setdefault(eid, period)

        self.employers = {
            r["id"]: (r["display_name"], r["city"], r["province"])
            for r in conn.execute("SELECT id, display_name, city, province FROM employers")
        }

    def published(self, period: str) -> str | None:
        return _published(self.resources[period])

    def totals(self, period: str) -> dict:
        emps = self.pos.get(period, {})
        lmias_seen = any(v[3] for v in emps.values())
        neg = self.neg_totals.get(period) or _Agg()
        return {
            "positive_rows": sum(v[2] for v in emps.values()),
            "positions": sum(v[0] for v in emps.values()),
            "lmias": sum(v[1] for v in emps.values()) if lmias_seen else None,
            "employers": len(emps),
            "negative_rows": neg.rows,
            "negative_positions": neg.positions,
            "negative_lmias": self.neg_lmias[period] if self.neg_lmias_seen[period] else None,
            "negative_employers": len(neg.employers),
        }

    def employer_row(self, period: str, eid: str) -> dict:
        slot = self.pos.get(period, {}).get(eid, [0, 0, 0, 0])
        city, prov = self.places.get((period, eid), (None, None))
        streams = self.emp_streams.get((period, eid))
        top_stream = _ranked(streams, 1)[0][0] if streams else ""
        return {
            "id": eid,
            "name": self.names.get((period, eid)) or self.employers.get(eid, ("",))[0],
            "city": city,
            "prov": prov,
            "stream": top_stream or None,
            "positions": slot[0],
            "rows": slot[2],
        }


def _release(d: _Data, i: int) -> dict:
    period = d.periods[i]
    prev = d.periods[i - 1] if i > 0 else None
    nxt = d.periods[i + 1] if i + 1 < len(d.periods) else None
    emps = d.pos.get(period, {})
    by_pos = {eid: v[0] for eid, v in emps.items()}
    top = [d.employer_row(period, eid) for eid, _ in _ranked(by_pos, TOP_EMPLOYERS)]

    new = None
    if prev is not None:
        fresh = {eid: v for eid, v in by_pos.items() if d.first_positive.get(eid) == period}
        new = {
            "count": len(fresh),
            "positions": sum(fresh.values()),
            "top": [d.employer_row(period, eid) for eid, _ in _ranked(fresh, TOP_NEW)],
        }

    changes = None
    if prev is not None:
        before = {eid: v[0] for eid, v in d.pos.get(prev, {}).items()}
        delta = {eid: by_pos.get(eid, 0) - before.get(eid, 0) for eid in set(by_pos) | set(before)}

        def change_row(eid: str) -> dict:
            row = d.employer_row(period if eid in by_pos else prev, eid)
            row.update(positions=by_pos.get(eid, 0), prev=before.get(eid, 0), change=delta[eid])
            row["rows"] = d.pos.get(period, {}).get(eid, [0, 0, 0])[2]
            return row

        up = [eid for eid, v in _ranked({k: v for k, v in delta.items() if v > 0}, TOP_CHANGES)]
        down = [eid for eid, _ in sorted(((k, v) for k, v in delta.items() if v < 0), key=lambda kv: (kv[1], kv[0]))[:TOP_CHANGES]]
        changes = {"up": [change_row(e) for e in up], "down": [change_row(e) for e in down]}

    def stream_block(aggs: dict[str, _Agg], missing: int, total: int) -> dict:
        share = (missing / total) if total else 0.0
        return {
            "shown": total > 0 and share <= STREAM_MISSING_MAX,
            "missing_share": round(share, 3),
            "rows": _table(aggs) if total and share <= STREAM_MISSING_MAX else [],
        }

    totals = d.totals(period)
    sources = []
    for r in sorted(d.resources[period], key=lambda r: (r["dataset"] != "positive", r["resource_id"])):
        sources.append({
            "dataset": r["dataset"],
            "name": r["name"],
            "url": r["url"],
            "page": resource_page(r["dataset"], r["resource_id"]),
            "published": r["published"],
            "sha256": r["sha256"],
            "bytes": r["bytes"],
            "rows": r["rows_loaded"],
            "mirror": mirror_name(r["dataset"], period, r["url"]),
        })

    return {
        "period": period,
        "slug": period_slug(period),
        "quarters": len(period_quarters(period)),
        "published": d.published(period),
        "first": prev is None,
        "prev": {"period": prev, "slug": period_slug(prev), "quarters": len(period_quarters(prev)),
                 "totals": d.totals(prev)} if prev else None,
        "next": {"period": nxt, "slug": period_slug(nxt)} if nxt else None,
        "totals": totals,
        "top": top,
        "new": new,
        "changes": changes,
        "approvals": {
            "prov": _table(d.pos_prov.get(period, {})),
            "stream": stream_block(d.pos_stream.get(period, {}), d.pos_stream_missing[period], totals["positions"]),
        },
        "refusals": {
            "prov": _table(d.neg_prov.get(period, {})),
            "stream": stream_block(d.neg_stream.get(period, {}), d.neg_stream_missing[period], totals["negative_rows"]),
        },
        "sources": sources,
    }


def _ranking(d: _Data, scope: str, periods: list[str], years: list[int], stream_years: list[int]) -> dict:
    by_emp: Counter = Counter()
    emp_rows: Counter = Counter()
    prov: dict[str, _Agg] = defaultdict(_Agg)
    for period in periods:
        for eid, v in d.pos.get(period, {}).items():
            by_emp[eid] += v[0]
            emp_rows[eid] += v[2]
        for k, a in d.pos_prov.get(period, {}).items():
            p = prov[k]
            p.rows += a.rows
            p.positions += a.positions
            p.employers |= a.employers
    total_positions = sum(by_emp.values())

    # Streams: one year is shown when few of its positions lack a stream; the
    # all-time table adds only the years that are shown, and names them.
    def year_of(period: str) -> int:
        return period_quarters(period)[0][0]

    stream_periods = [p for p in periods if year_of(p) in stream_years]
    streams: dict[str, _Agg] = defaultdict(_Agg)
    missing = sum(d.pos_stream_missing[p] for p in periods)
    for period in stream_periods:
        for k, a in d.pos_stream.get(period, {}).items():
            s = streams[k]
            s.rows += a.rows
            s.positions += a.positions
            s.employers |= a.employers
    share = (missing / total_positions) if total_positions else 0.0
    shown = bool(stream_periods) and (scope == "all" or share <= STREAM_MISSING_MAX)

    occupations = []
    for era in ("2011", "2021"):
        codes: dict[str, list[int]] = {}
        era_periods = []
        for period in periods:
            hit = False
            for code, (positions, rows) in d.noc.get(period, {}).items():
                if noc_era(code) != era:
                    continue
                hit = True
                cell = codes.setdefault(code, [0, 0])
                cell[0] += positions
                cell[1] += rows
            if hit:
                era_periods.append(period)
        if not codes:
            continue
        ranked = sorted(codes.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:TOP_OCCUPATIONS]
        occupations.append({
            "era": era,
            "periods": era_periods,
            "codes": len(codes),
            "positions": sum(v[0] for v in codes.values()),
            "rows": [{"code": c, "title": d.titles.get(c, (None, None))[1], "positions": v[0], "rows": v[1]} for c, v in ranked],
        })

    employers = []
    for eid, positions in _ranked(by_emp, TOP_EMPLOYERS):
        name, city, province = d.employers.get(eid, (None, None, None))
        employers.append({"id": eid, "name": name or eid, "city": city, "prov": province,
                          "positions": positions, "rows": emp_rows[eid]})

    return {
        "scope": scope,
        "years": years,
        "periods": periods,
        "totals": {
            "positions": total_positions,
            "rows": sum(emp_rows.values()),
            "employers": len(by_emp),
        },
        "provinces": _table(prov),
        "streams": {
            "shown": shown,
            "missing_share": round(share, 3),
            "years": sorted({year_of(p) for p in stream_periods}) if shown else [],
            "positions": sum(a.positions for a in streams.values()) if shown else 0,
            "rows": _table(streams) if shown else [],
        },
        "occupations": occupations,
        "no_occupation_periods": [p for p in periods if d.no_occupation[p] and not d.noc.get(p)],
        "employers": employers,
    }


def write_all(conn: sqlite3.Connection, out: Path) -> dict[str, int]:
    """Write releases/ and rankings/ under `out`; returns file counts and bytes."""
    d = _Data(conn)
    written = {"release_files": 0, "ranking_files": 0, "release_bytes": 0}
    if not d.periods:
        return written
    index = []
    for i, period in enumerate(d.periods):
        rel = _release(d, i)
        written["release_bytes"] += _dump(out / "releases" / f"{rel['slug']}.json", rel)
        written["release_files"] += 1
        index.append({"period": period, "slug": rel["slug"], "quarters": rel["quarters"], "published": rel["published"],
                      **{k: rel["totals"][k] for k in ("positive_rows", "positions", "employers", "negative_rows", "negative_positions")}})
    index.reverse()
    written["release_bytes"] += _dump(out / "releases" / "index.json", {"releases": index})
    written["release_files"] += 1

    by_year: dict[int, list[str]] = defaultdict(list)
    for period in d.periods:
        by_year[period_quarters(period)[0][0]].append(period)
    years = sorted(by_year, reverse=True)
    stream_years = []
    for year, periods in by_year.items():
        total = sum(sum(v[0] for v in d.pos.get(p, {}).values()) for p in periods)
        missing = sum(d.pos_stream_missing[p] for p in periods)
        if total and missing / total <= STREAM_MISSING_MAX:
            stream_years.append(year)
    stream_years.sort()
    written["release_bytes"] += _dump(out / "rankings" / "all.json", _ranking(d, "all", d.periods, years, stream_years))
    written["ranking_files"] += 1
    for year in years:
        written["release_bytes"] += _dump(out / "rankings" / f"{year}.json",
                                          _ranking(d, str(year), by_year[year], years, stream_years))
        written["ranking_files"] += 1
    return written


def sitemap_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    """(path, lastmod) for the release index, the rankings and each release, newest first.

    Empty when no list is loaded, so the sitemap never names an empty page. A
    release's lastmod is its publication date; the index and rankings carry
    the newest one, since they change only when a list is published.
    """
    by_period: dict[str, list] = defaultdict(list)
    for r in conn.execute("SELECT period, published FROM esdc_resources"):
        if period_quarters(r["period"]):
            by_period[r["period"]].append(r)
    if not by_period:
        return []
    published = {p: _published(rows) for p, rows in by_period.items()}
    periods = sorted(published, key=lambda p: (period_sort_key(p), p), reverse=True)
    latest = max((v for v in published.values() if v), default=None)
    entries: list[tuple[str, str | None]] = [("/releases", latest), ("/rankings", latest)]
    years: dict[int, str | None] = {}
    for p in periods:
        y = period_quarters(p)[0][0]
        years[y] = max(filter(None, (years.get(y), published[p])), default=None)
    entries += [(f"/rankings/{y}", years[y]) for y in sorted(years, reverse=True)]
    entries += [(f"/releases/{period_slug(p)}", published[p]) for p in periods]
    return entries
