"""Static JSON export: the files the site serves as assets.

Why static: a read-heavy public dataset costs nothing per row when page views
read files. The site therefore ships the data as JSON files beside the Worker
(static assets are free to serve), the map page filters in the browser, and
the profile page reads one small shard. The database stays on the operator's
side. The search page queries the hosted search database (search_db.py fills
it), and the files below are its fallback when that database cannot answer.

Search files: the search page renders from the database, so the export writes
only what still has a reader. `search/first.json` is the page's fallback (the
newest rows, rendered on the server); `search/facets.json` gives the fallback
and the home page their counts; `search/counts.json` gives the search API its
totals; `search/latest/status/pending.json` is what /api/pending serves. The
browser-side slices of earlier versions (the default scope by status and
province, the long scope by province and year) are no longer written.

Output tree (under data/out/static):
  stats.json                         counts, breakdowns, recent lists, resources, runs
  search/first.json                  newest FIRST_ROWS rows of the default scope (pending and approved
                                     postings plus the latest quarter)
  search/facets.json                 counts by status and province for the default scope and since
                                     SEARCH_FROM_PERIOD, plus the sizes of the search files written
  search/counts.json                 the hosted search database's rows counted by status, province,
                                     stream, year and indicators, for the search API's totals, with
                                     the data's date and the latest ESDC period (date=last_quarter)
  search/latest/status/pending.json  the pending postings, newest first, for /api/pending
  clusters/latest.json, clusters/since_2023q4.json   per postal area counts
  areas/<FSA>.json                   rows for one postal area, latest scope, capped
  profiles/<abc>.json                employer profiles keyed by id, sharded on id characters 5 to 7, with the
                                     public records matched to each (grants, Alberta accounts, US carrier records)
  aliases/<abc>.json                 retired employer id -> the live id that took its records,
                                     sharded on the retired id's characters 5 to 7 like the profiles
  trends/*.json                      the series behind /trends (trends.py)
  international/index.json           postings open to international candidates, their grades and the
                                     designated-employer lists, behind /international (intl.py)
  program/index.json                 the program conditions behind /program (conditions.py)
  notices.json                       IRCC and ESDC news items that name the programs, both languages, with
                                     each feed's state, behind /notices and the home page (sources/notices.py)
  sitemaps/sitemap-<n>.xml           the fixed pages and every profile URL, at most 50,000 per file
  sitemaps/index.xml                 the sitemap index; the site serves it at /sitemap.xml and the
                                     parts at /sitemap-<n>.xml, since a sitemap may list only URLs
                                     at or below its own directory

Every file is written deterministically (sorted keys and rows) so an unchanged
shard keeps its bytes and the deploy skips it.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from . import conditions, config, intl, places, releases, trends
from .db import get_meta, log_run
from .sources import high_wage, notices, registers
from .feeds import write_feeds
from .normalize import period_end_date, period_sort_key
from .zenodo import citation_from_meta

log = logging.getLogger(__name__)

SEARCH_FROM_PERIOD = "2023Q4"
FIRST_ROWS = 500
RECENT = 8
TOP = 6
AREA_ROW_CAP = 200
# Public records on a profile (grants, Alberta accounts, US carrier records):
# the newest agreements up to this many, with the full count beside them, and
# at most RECORDS_SHOWN matched accounts or carrier records.
GRANTS_SHOWN = 20
RECORDS_SHOWN = 3
POSITIVE_DATASET = "90fed587-1364-4f33-a9ee-208181dc0b97"
NEGATIVE_DATASET = "f82f66f2-a22b-4511-bccf-e1d74db39ae5"

PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX"]
UNKNOWN_PROVINCE = "UN"
STATUSES = ["pending", "approved", "refused"]

# The sitemap protocol's limit per file (the 50 MB cap is never near: a profile
# entry is about 100 bytes).
SITEMAP_MAX_URLS = 50_000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITEMAP_PAGES = ["/", "/search", "/map", "/methodology", "/data", "/support", "/cite", "/corrections"]
# Pages whose content follows the nightly data carry its date; the others
# change only with the code, so they carry none rather than a false one.
SITEMAP_DATED_PAGES = {"/", "/search", "/map", "/data"}


def _dump(path: Path, obj: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: Python would write NaN or Infinity, which no browser's
    # JSON parser accepts, and one such value would break a whole file on the
    # site. The export fails instead, and the previous one stays published.
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def _esdc_source(list_name: str, resource_id: str) -> str:
    dataset = POSITIVE_DATASET if list_name == "positive" else NEGATIVE_DATASET
    return f"https://open.canada.ca/data/en/dataset/{dataset}/resource/{resource_id}"


def triggered_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT employer_id, indicator FROM indicators WHERE state = 'triggered' ORDER BY indicator"):
        out[r["employer_id"]].append(r["indicator"])
    return out


def posting_row(p: sqlite3.Row, ind: dict[str, list[str]]) -> dict:
    status = "pending" if p["flag_current"] == "requested" else "approved" if p["flag_current"] == "approved" else "lapsed"
    return {
        "kind": "posting",
        "ref": p["posting_id"],
        "employer_id": p["employer_id"],
        "employer": p["employer_raw"],
        "job": p["title"],
        "noc": p["noc_code"],
        "street": p["street"],
        "city": p["city"],
        "prov": p["province"],
        "postal": p["postal_code"],
        "wage_min": p["wage_min"],
        "wage_max": p["wage_max"],
        "unit": p["wage_unit"],
        "date": p["date_posted"],
        "period": None,
        "positions": p["vacancies"],
        "status": status,
        "stream": None,
        "source": p["url"],
        "sort_date": p["date_posted"] or (p["first_seen"] or "")[:10],
        "ind": ind.get(p["employer_id"], []),
    }


def esdc_row(r: sqlite3.Row, ind: dict[str, list[str]]) -> dict:
    return {
        "kind": "esdc",
        "ref": r["id"],
        "employer_id": r["employer_id"],
        "employer": r["employer_raw"],
        "job": r["noc_title"],
        "noc": r["noc_code"],
        "street": None,
        "city": r["city"],
        "prov": r["province"],
        "postal": r["postal_code"],
        "wage_min": None,
        "wage_max": None,
        "unit": None,
        "date": None,
        "period": r["period"],
        "positions": r["positions"],
        "status": "approved" if r["list"] == "positive" else "refused",
        "stream": r["stream"],
        "source": _esdc_source(r["list"], r["resource_id"]),
        "sort_date": period_end_date(r["period"]) or "",
        "ind": ind.get(r["employer_id"], []),
    }


POSTING_SQL = (
    "SELECT posting_id, employer_id, employer_raw, title, noc_code, street, city, province, postal_code, "
    "wage_min, wage_max, wage_unit, vacancies, date_posted, first_seen, flag_current, url FROM jobbank_postings"
)
ESDC_SQL = (
    "SELECT id, list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, noc_title, "
    "lmias, positions, resource_id FROM esdc_records"
)
# The postings search shows: a lapsed one (the flag gone from Job Bank) is
# left out. Shared with search_db, so the hosted search holds the same set.
SEARCHED_POSTINGS = "flag_current IN ('requested', 'approved')"


def _sort_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r["sort_date"], r["employer"] or "", r["kind"], r["ref"]), reverse=True)
    return rows


def _prov(row: dict) -> str:
    return row["prov"] or UNKNOWN_PROVINCE


def search_latest(conn: sqlite3.Connection, latest: str, ind: dict[str, list[str]]) -> list[dict]:
    rows = [posting_row(p, ind) for p in conn.execute(POSTING_SQL + f" WHERE {SEARCHED_POSTINGS}")]
    rows += [esdc_row(r, ind) for r in conn.execute(ESDC_SQL + " WHERE period = ?", (latest,))]
    return _sort_rows(rows)


def search_province(conn: sqlite3.Connection, prov: str, ind: dict[str, list[str]]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Postings for the province, and list rows since SEARCH_FROM_PERIOD
    grouped by the period's year (the map's longer period and its counts)."""
    where = "province IS NULL" if prov == UNKNOWN_PROVINCE else "province = ?"
    params: tuple = () if prov == UNKNOWN_PROVINCE else (prov,)
    postings = [posting_row(p, ind) for p in conn.execute(POSTING_SQL + f" WHERE {SEARCHED_POSTINGS} AND {where}", params)]
    by_year: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(ESDC_SQL + f" WHERE {where} AND period >= ?", (*params, SEARCH_FROM_PERIOD)):
        by_year[r["period"][:4]].append(esdc_row(r, ind))
    return postings, by_year


def write_search(conn: sqlite3.Connection, out: Path, latest: str, ind: dict[str, list[str]]) -> tuple[list[dict], list[dict], dict]:
    """Write the search files that still have a reader (see the module
    docstring) and facets.json; return (latest rows, long rows, counts).

    The latest and long rows are still built in full: the map's cluster files
    and the area files are made from them, and facets.json counts them.
    """
    files: dict[str, dict] = {}

    def dump(rel: str, rows: list[dict]) -> None:
        files[rel] = {"rows": len(rows), "bytes": _dump(out / rel, rows)}

    latest_rows = search_latest(conn, latest, ind)
    dump("search/first.json", latest_rows[:FIRST_ROWS])
    # Written even when empty: /api/pending answers 503 for a missing file,
    # and a night with no pending posting is not a missing export.
    dump("search/latest/status/pending.json", [r for r in latest_rows if r["status"] == "pending"])
    status_prov: Counter = Counter(f"{r['status']}|{_prov(r)}" for r in latest_rows)
    default = {
        "total": len(latest_rows),
        "status": dict(Counter(r["status"] for r in latest_rows)),
        "prov": dict(Counter(_prov(r) for r in latest_rows)),
        "status_prov": dict(status_prov),
    }

    long_rows: list[dict] = []
    long_prov: Counter = Counter()
    long_prov_year: Counter = Counter()
    long_status: Counter = Counter()
    long_status_prov: Counter = Counter()
    for prov in PROVINCES + [UNKNOWN_PROVINCE]:
        postings, by_year = search_province(conn, prov, ind)
        if postings:
            long_prov_year[f"{prov}|postings"] += len(postings)
        for year, rows in sorted(by_year.items()):
            long_prov_year[f"{prov}|{year}"] += len(rows)
        for row in postings + [r for rows in by_year.values() for r in rows]:
            long_rows.append(row)
            long_prov[prov] += 1
            long_status[row["status"]] += 1
            long_status_prov[f"{row['status']}|{prov}"] += 1
    long = {
        "total": len(long_rows),
        "status": dict(long_status),
        "prov": dict(long_prov),
        "prov_year": dict(long_prov_year),
        "status_prov": dict(long_status_prov),
    }
    facets = {"default": default, "long": long, "files": files, "first_rows": FIRST_ROWS}
    _dump(out / "search" / "facets.json", facets)
    return latest_rows, long_rows, {"search_latest": len(latest_rows), "search_long": len(long_rows), "search_files": len(files)}


# The dimensions of search/counts.json, each a column of the search database.
SEARCH_COUNT_DIMS = ("status", "prov", "stream", "year", "ind")


def _none_last(value: object) -> tuple:
    return (value is None, value if value is not None else 0)


def write_search_counts(conn: sqlite3.Connection, out: Path, data_as_of: str | None,
                        latest_period: str | None = None) -> dict[str, int]:
    """search/counts.json: the hosted search database's rows counted by status,
    province, stream, year and triggered indicators, with the data's date and
    the latest ESDC period.

    The API counts its date windows from data_as_of, and date=last_quarter
    keeps the list rows of latest_period (meta esdc_latest_period), so the
    filter names the quarter the search page's control names.

    Why: a total is the expensive part of a search on D1, since counting the
    rows that match a filter reads every one of them. The search API sums the
    cells matching a request's status, province, stream, year and indicator
    filters instead, which gives an exact total and exact facet counts with no
    database read for every request that filters on nothing else. The
    indicators are a dimension of their own because no index can answer that
    filter, so in D1 its count would read the whole table every time.

    Over exactly the rows search_db.search_rows yields (the rows the nightly
    sync sends), with each value as the database holds it: the province and
    stream as written (null where there is none), the indicator keys comma
    separated. Each dimension's values are listed once under "values", and a
    cell is the index of its value in each list, then its row count, so the
    file stays small (about 3,000 cells, 60 KB, on 2026-10-23 data).
    """
    from .search_db import search_rows  # search_db imports this module, so not at the top

    cells: Counter = Counter()
    for row in search_rows(conn):
        cells[tuple(row[d] for d in SEARCH_COUNT_DIMS)] += 1
    values = {d: sorted({key[i] for key in cells}, key=_none_last) for i, d in enumerate(SEARCH_COUNT_DIMS)}
    position = {d: {v: i for i, v in enumerate(vals)} for d, vals in values.items()}
    rows = sorted([position[d][key[i]] for i, d in enumerate(SEARCH_COUNT_DIMS)] + [n] for key, n in cells.items())
    doc = {
        "data_as_of": data_as_of,
        "latest_period": latest_period or None,
        "total": sum(cells.values()),
        "dims": list(SEARCH_COUNT_DIMS),
        "values": values,
        "cells": rows,
    }
    _dump(out / "search" / "counts.json", doc)
    return {"search_count_cells": len(rows)}


def clusters(conn: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    centroids = {r["fsa"]: r for r in conn.execute("SELECT fsa, province, lat, lon FROM fsa_centroids")}
    agg: dict[str, dict] = {}
    for row in rows:
        postal = row["postal"]
        if not postal:
            continue
        fsa = postal[:3].upper()
        c = centroids.get(fsa)
        if c is None:
            continue
        a = agg.setdefault(fsa, {"fsa": fsa, "prov": c["province"], "lat": c["lat"], "lon": c["lon"],
                                 "pending": 0, "approved": 0, "refused": 0})
        if row["status"] in ("pending", "approved", "refused"):
            a[row["status"]] += 1
    return [agg[k] for k in sorted(agg)]


# The home page's count of the public records matched to employers. A match
# row is one employer and one agreement, and an agreement can match two
# employers of the same name, so agreements are counted once each.
PUBLIC_RECORD_COUNTS = {
    "grant_employers": ("grant_matches", "COUNT(DISTINCT employer_id)"),
    "grant_agreements": ("grant_matches", "COUNT(DISTINCT agreement_key)"),
    "alberta_employers": ("alberta_matches", "COUNT(DISTINCT employer_id)"),
    "carrier_employers": ("fmcsa_matches", "COUNT(DISTINCT employer_id)"),
}


def public_record_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Counts over the match tables; a table not created yet counts 0."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {key: conn.execute(f"SELECT {expr} FROM {table}").fetchone()[0] if table in tables else 0
            for key, (table, expr) in PUBLIC_RECORD_COUNTS.items()}


# The home page's chart of pending postings by occupation. A posting's code
# comes from its detail page, which the nightly budget works through, so many
# pending postings have none yet: the chart counts only those with a NOC 2021
# code and says how many that is.
PENDING_BY_NOC = 8
PENDING_NOC_SQL = (
    "SELECT p.noc_code AS k, COUNT(*) AS n, t.title_en, t.title_fr, MAX(p.noc_title) AS posted "
    "FROM jobbank_postings p LEFT JOIN noc_titles t ON t.noc_code = p.noc_code "
    "WHERE p.flag_current = 'requested' AND p.noc_code GLOB '[0-9][0-9][0-9][0-9][0-9]' "
    "GROUP BY p.noc_code ORDER BY n DESC, p.noc_code"
)


def pending_by_noc(conn: sqlite3.Connection) -> tuple[list[dict], int]:
    """The codes with the most pending postings, titled in English and French, and the pending postings with a code.

    Titles come from the NOC 2021 classification (noc_titles), as on the
    occupation pages. A code it lacks takes the posting's own occupation
    title, else the title an ESDC list gives the code, else the code, in both
    languages.
    """
    rows = conn.execute(PENDING_NOC_SQL).fetchall()
    out = []
    for r in rows[:PENDING_BY_NOC]:
        if r["title_en"]:
            title = {"en": r["title_en"], "fr": r["title_fr"] or r["title_en"]}
        else:
            name = r["posted"] or conn.execute(
                "SELECT MAX(noc_title) FROM esdc_records WHERE noc_code = ?", (r["k"],)).fetchone()[0] or r["k"]
            title = {"en": name, "fr": name}
        out.append({"k": r["k"], "n": r["n"], "title": title})
    return out, sum(r["n"] for r in rows)


def write_stats(conn: sqlite3.Connection, out: Path, latest: str, ind: dict[str, list[str]]) -> dict:
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    counts = {
        "pending": int(meta.get("count_pending", 0)),
        "approved_records": int(meta.get("count_approved_records", 0)),
        "approved_positions": int(meta.get("count_approved_positions", 0)),
        "refused_records": int(meta.get("count_refused_records", 0)),
        "findings": int(meta.get("count_findings", 0)),
        "employers": conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0],
        **public_record_counts(conn),
        # Postings open to international candidates and designated employers (intl.py); absent before the first pass.
        **intl.stats_counts(conn),
    }
    by_noc, counts["pending_with_noc"] = pending_by_noc(conn)
    by_stream = [{"k": r["k"] or "Unknown", "n": r["n"]} for r in conn.execute(
        "SELECT stream AS k, COUNT(*) AS n FROM esdc_records WHERE list = 'positive' AND period = ? GROUP BY stream ORDER BY n DESC", (latest,))]
    by_province = [{"k": r["k"] or "Unknown", "n": r["n"]} for r in conn.execute(
        "SELECT province AS k, COUNT(*) AS n FROM esdc_records WHERE list = 'positive' AND period = ? GROUP BY province ORDER BY n DESC", (latest,))]
    # The home page's "Applying This Week": the postings whose "LMIA requested"
    # flag was first seen most recently, since the flag follows the posting by
    # days. Each row carries that date as "flagged" beside the posting date;
    # only these rows do, so the search files and their hashes are unchanged.
    recent_pending = []
    for p in conn.execute(
            POSTING_SQL + " WHERE flag_current = 'requested' ORDER BY first_seen DESC, date_posted DESC, posting_id DESC LIMIT ?",
            (RECENT,)):
        row = posting_row(p, ind)
        row["flagged"] = (p["first_seen"] or "")[:10]
        recent_pending.append(row)
    recent_approved = [posting_row(p, ind) for p in conn.execute(
        POSTING_SQL + " WHERE approved_seen_at IS NOT NULL ORDER BY approved_seen_at DESC, date_posted DESC LIMIT ?", (RECENT,))]
    top = [dict(r) for r in conn.execute(
        "SELECT employer_id, MAX(employer_raw) AS employer, MAX(city) AS city, MAX(province) AS prov, MAX(stream) AS stream, "
        "SUM(COALESCE(positions, 0)) AS positions FROM esdc_records WHERE list = 'positive' AND period = ? "
        "GROUP BY employer_id ORDER BY positions DESC, employer LIMIT ?", (latest, TOP))]
    resources = [dict(r) for r in conn.execute(
        "SELECT dataset, period, published, rows_loaded, loaded_at FROM esdc_resources ORDER BY dataset, period")]
    resources.sort(key=lambda r: (r["dataset"], period_sort_key(r["period"])), reverse=True)
    runs = [dict(r) for r in conn.execute(
        "SELECT run_at, source, detail, rows_new, ok FROM sources_log ORDER BY id DESC LIMIT 20")]
    stats = {
        "data_as_of": meta.get("data_as_of"),
        "jobbank_last_run": meta.get("jobbank_last_run"),
        "esdc_latest_period": latest,
        "esdc_latest_published": meta.get("esdc_latest_published"),
        "rules_version": meta.get("rules_version"),
        # The start of the map's longer period (clusters/since_2023q4.json).
        # The name is older than hosted search, which covers every year; the
        # list of the long scope's file years went with those files.
        "search_from_period": SEARCH_FROM_PERIOD,
        "counts": counts,
        "by_stream": by_stream,
        "by_province": by_province,
        "recent_pending": recent_pending,
        "pending_by_noc": by_noc,
        "recent_approved": recent_approved,
        "top_approvals": top,
        "resources": resources,
        "runs": runs,
        # The Zenodo record behind "How to cite"; null until one is published.
        "citation": citation_from_meta(meta),
        # The designated-employer lists and their terms, for the Data page's sources (sources/registers.py).
        "registers": registers.export_rows(conn),
        # IRCC's high-wage list in use (its version date), for the methodology page.
        "high_wage": high_wage.list_version(conn),
    }
    _dump(out / "stats.json", stats)
    return stats


def shard_key(employer_id: str) -> str:
    return employer_id[4:7]


def _grade_order(column: str) -> str:
    return f"CASE {column} WHEN 'exact' THEN 0 WHEN 'probable' THEN 1 ELSE 2 END"


def profile_grants(conn: sqlite3.Connection, ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Each employer's matched federal agreements, newest first, at most GRANTS_SHOWN, and the full count.

    The cap keeps a shard small: a university or a health authority can hold
    hundreds of agreements, and the page shows the newest with a count of the
    rest.
    """
    marks = ",".join("?" * len(ids))
    shown: dict[str, list[dict]] = defaultdict(list)
    totals: Counter = Counter()
    for r in conn.execute(
        f"""
        SELECT m.employer_id, m.grade, m.basis, g.ref_number, g.amendment_number, g.owner_org, g.department_en,
               g.department_fr, g.program_en, g.program_fr, g.agreement_type, g.agreement_value, g.start_date, g.end_date
        FROM grant_matches m JOIN federal_grants g ON g.agreement_key = m.agreement_key
        WHERE m.employer_id IN ({marks})
        ORDER BY m.employer_id, COALESCE(g.start_date, '') DESC, g.agreement_value DESC, g.agreement_key
        """, ids):
        eid = r["employer_id"]
        totals[eid] += 1
        if len(shown[eid]) < GRANTS_SHOWN:
            row = dict(r)
            del row["employer_id"]
            shown[eid].append(row)
    return shown, dict(totals)


def profile_alberta(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """Each Alberta employer's matched workers' compensation accounts, latest year of each, best first."""
    marks = ",".join("?" * len(ids))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        f"""
        SELECT m.employer_id, m.grade, m.basis, a.emp_key, a.year, a.employer_name, a.trade_name, a.city, a.industry,
               a.person_years, a.lost_time_claims, a.lost_time_rate, a.disabling_injuries, a.disabling_rate,
               a.fatalities, a.cor_year,
               (SELECT MIN(b.year) FROM alberta_employer_records b WHERE b.emp_key = a.emp_key) AS first_year
        FROM alberta_matches m
        JOIN alberta_employer_records a ON a.emp_key = m.emp_key AND a.employer_name = m.account_name
        WHERE m.employer_id IN ({marks})
          AND a.year = (SELECT MAX(b.year) FROM alberta_employer_records b
                        WHERE b.emp_key = a.emp_key AND b.employer_name = a.employer_name)
        ORDER BY m.employer_id, {_grade_order('m.grade')}, a.year DESC, COALESCE(a.person_years, 0) DESC, a.emp_key
        """, ids):
        eid = r["employer_id"]
        if len(out[eid]) < RECORDS_SHOWN:
            row = dict(r)
            del row["employer_id"]
            out[eid].append(row)
    return out


def profile_carriers(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """Each employer's matched US carrier records, best first: active before inactive, newest record first."""
    marks = ",".join("?" * len(ids))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        f"""
        SELECT m.employer_id, m.grade, m.basis, f.dot_number, f.legal_name, f.dba_name, f.city, f.province,
               f.postal_code, f.status, f.power_units, f.drivers, f.safety_rating, f.safety_rating_date,
               f.record_date
        FROM fmcsa_matches m JOIN fmcsa_carriers f ON f.dot_number = m.dot_number
        WHERE m.employer_id IN ({marks})
        ORDER BY m.employer_id, {_grade_order('m.grade')}, CASE f.status WHEN 'A' THEN 0 ELSE 1 END,
                 COALESCE(f.record_date, '') DESC, f.dot_number
        """, ids):
        eid = r["employer_id"]
        if len(out[eid]) < RECORDS_SHOWN:
            row = dict(r)
            del row["employer_id"]
            out[eid].append(row)
    return out


def write_profiles(conn: sqlite3.Connection, out: Path) -> int:
    """One JSON file per shard, keyed by employer id, with the full history."""
    published = {r["resource_id"]: r["published"] for r in conn.execute("SELECT resource_id, published FROM esdc_resources")}
    employers = conn.execute("SELECT * FROM employers ORDER BY id").fetchall()
    shards: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for e in employers:
        shards[shard_key(e["id"])].append(e)
    written = 0
    for key in sorted(shards):
        group = shards[key]
        ids = [e["id"] for e in group]
        marks = ",".join("?" * len(ids))
        names = defaultdict(list)
        for r in conn.execute(f"SELECT employer_id, raw_name, source FROM employer_names WHERE employer_id IN ({marks}) ORDER BY raw_name", ids):
            names[r["employer_id"]].append({"name": r["raw_name"], "source": r["source"]})
        postings = defaultdict(list)
        for r in conn.execute(f"SELECT * FROM jobbank_postings WHERE employer_id IN ({marks}) ORDER BY date_posted DESC, posting_id DESC", ids):
            postings[r["employer_id"]].append(dict(r))
        records = defaultdict(list)
        for r in conn.execute(
            f"SELECT employer_id, id, list, period, employer_raw, province, stream, city, postal_code, noc_code, noc_title, "
            f"incorporate_status, lmias, positions, resource_id FROM esdc_records WHERE employer_id IN ({marks})", ids):
            d = dict(r)
            del d["employer_id"]
            d["published"] = published.get(r["resource_id"])
            records[r["employer_id"]].append(d)
        for lst in records.values():
            lst.sort(key=lambda d: (period_sort_key(d["period"]), d["list"], d["noc_code"] or ""), reverse=True)
        registry = defaultdict(list)
        for r in conn.execute(
            f"SELECT employer_id, registry, registry_id, legal_name, entity_type, status, registered_on, grade, checked_at "
            f"FROM registry_matches WHERE employer_id IN ({marks}) ORDER BY CASE grade WHEN 'exact' THEN 0 WHEN 'probable' THEN 1 ELSE 2 END", ids):
            registry[r["employer_id"]].append(dict(r))
        indicators = defaultdict(list)
        for r in conn.execute(
            f"SELECT employer_id, indicator, state, basis, rule_version, computed_at FROM indicators "
            f"WHERE employer_id IN ({marks}) ORDER BY indicator", ids):
            indicators[r["employer_id"]].append(dict(r))
        findings = defaultdict(list)
        for r in conn.execute(
            f"SELECT employer_id, operating_name, legal_name, address, reasons, decision_date, penalty, status "
            f"FROM findings WHERE employer_id IN ({marks}) ORDER BY decision_date DESC", ids):
            findings[r["employer_id"]].append(dict(r))
        grants, grant_totals = profile_grants(conn, ids)
        alberta = profile_alberta(conn, ids)
        carriers = profile_carriers(conn, ids)
        intl_rows = intl.profile_rows(conn, ids)
        designated = registers.profile_rows(conn, ids)
        shard = {}
        for e in group:
            eid = e["id"]
            shard[eid] = {
                "employer": dict(e),
                "names": names.get(eid, []),
                "postings": postings.get(eid, []),
                "esdc": records.get(eid, []),
                "registry": registry.get(eid, []),
                "indicators": indicators.get(eid, []),
                "findings": findings.get(eid, []),
                "grants": grants.get(eid, []),
                "grants_total": grant_totals.get(eid, 0),
                "alberta": alberta.get(eid, []),
                "us_carrier": carriers.get(eid, []),
            }
            # Written only when there is something, so the shard of an employer
            # without either keeps its bytes (the site reads absent as none).
            if intl_rows.get(eid):
                shard[eid]["intl"] = intl_rows[eid]
            if designated.get(eid):
                shard[eid]["designated"] = designated[eid]
        _dump(out / "profiles" / f"{key}.json", shard)
        written += 1
    return written


def resolve_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """Each retired employer id mapped to the live id its records ended up under.

    An alias may point at an id that was itself retired later (a second
    normalization change, a parser reload), so each one is followed until it
    reaches a live employer. A chain that loops, or ends at an id with no
    employer row, leads nowhere and is left out rather than sending a visitor
    to a missing page. An old id that is live again answers for itself.
    """
    live = {r[0] for r in conn.execute("SELECT id FROM employers")}
    step = {r[0]: r[1] for r in conn.execute("SELECT old_id, new_id FROM employer_aliases")}
    out: dict[str, str] = {}
    for old, target in step.items():
        if old in live:
            continue
        seen = {old}
        while target not in live and target in step and target not in seen:
            seen.add(target)
            target = step[target]
        if target in live:
            out[old] = target
    return out


def write_aliases(conn: sqlite3.Connection, out: Path) -> dict[str, int]:
    """One JSON file per shard mapping each retired employer id to its live id.

    Why: a profile link shared before a normalization change or a parser
    reload names an id that no longer exists, and the site can look a
    missing id up here to send the visitor on. The shard is the retired id's,
    by the same shard_key as the profiles, so the lookup reads one small file
    named like the profile shard it just missed in. Retired ids never go in
    the sitemap.
    """
    shards: dict[str, dict[str, str]] = defaultdict(dict)
    for old, new in resolve_aliases(conn).items():
        shards[shard_key(old)][old] = new
    for key in sorted(shards):
        _dump(out / "aliases" / f"{key}.json", shards[key])
    return {"alias_shards": len(shards)}


def _lastmod(value: str | None) -> str | None:
    """The date part of an ISO date or datetime, or None for anything else."""
    if value and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def sitemap_entries(conn: sqlite3.Connection, data_as_of: str | None,
                    skip: Collection[str] = ()) -> list[tuple[str, str | None]]:
    """(path, lastmod) for the fixed pages, the release pages, then every profile in id order.

    A profile's lastmod is the employer row's updated_at, which status.recompute
    rewrites only when something on the profile changed. `skip` names sections
    whose files were not written tonight (see _write_static), so their pages
    are left out rather than listed while they answer "not published".
    """
    dated = _lastmod(data_as_of)
    entries: list[tuple[str, str | None]] = [(p, dated if p in SITEMAP_DATED_PAGES else None) for p in SITEMAP_PAGES]
    # Feeds and the browser watchlist. The feed list follows the nightly data;
    # the watchlist page changes only with the code.
    entries += ([] if "feeds" in skip else [("/feeds", dated)]) + [("/watchlist", None)]
    # --- releases and rankings: /releases, /rankings, each year's rankings and
    # each release page, dated by the lists' publication; none until a list is
    # loaded, so an empty page is never listed.
    if "releases" not in skip:
        entries += releases.sitemap_entries(conn)
    # The trends views (trends.py): the ESDC series dated by the lists'
    # publication, the daily pending series by its latest complete pass.
    if "trends" not in skip:
        entries += trends.sitemap_entries(conn)
    # The program conditions page, dated by the newest edition read.
    if "program" not in skip:
        entries += conditions.sitemap_entries(conn)
    # Postings open to international candidates, once a pass has written its file.
    if "international" not in skip and get_meta(conn, "intl_last_run"):
        entries.append(("/international", dated))
    # Government notices, once a read has written the file, dated by the day
    # the list last gained an item.
    if "notices" not in skip and get_meta(conn, "notices_last_run"):
        entries.append(("/notices", notices.sitemap_lastmod(conn, data_as_of)))
    entries += [(f"/employers/{r['id']}", _lastmod(r["updated_at"]))
                for r in conn.execute("SELECT id, updated_at FROM employers ORDER BY id")]
    # Occupation and place pages at or above the record threshold, each dated
    # by its newest record, and their two index pages (places.py).
    if "places" not in skip:
        entries += [(path, _lastmod(mod)) for path, mod in places.sitemap_entries(conn)]
    return entries


def sitemap_chunks(entries: Sequence, max_urls: int = SITEMAP_MAX_URLS) -> list[Sequence]:
    return [entries[i:i + max_urls] for i in range(0, len(entries), max_urls)]


def _xml(lines: list[str]) -> bytes:
    return ("\n".join(['<?xml version="1.0" encoding="UTF-8"?>', *lines]) + "\n").encode("utf-8")


def _entry(tag: str, loc: str, lastmod: str | None) -> str:
    stamp = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return f"<{tag}><loc>{escape(loc)}</loc>{stamp}</{tag}>"


def write_sitemaps(conn: sqlite3.Connection, out: Path, base_url: str, data_as_of: str | None,
                   max_urls: int = SITEMAP_MAX_URLS, skip: Collection[str] = ()) -> dict[str, int]:
    """Write sitemaps/sitemap-<n>.xml and the index that lists them.

    URLs are absolute, as the protocol requires, on `base_url`. The index names
    each part at the site root (/sitemap-<n>.xml), where the site serves it, with
    the newest lastmod inside that part.
    """
    base = base_url.rstrip("/")
    entries = sitemap_entries(conn, data_as_of, skip)
    folder = out / "sitemaps"
    folder.mkdir(parents=True, exist_ok=True)
    index: list[str] = []
    chunks = sitemap_chunks(entries, max_urls)
    for n, chunk in enumerate(chunks, start=1):
        lines = [f'<urlset xmlns="{SITEMAP_NS}">', *(_entry("url", base + path, mod) for path, mod in chunk), "</urlset>"]
        (folder / f"sitemap-{n}.xml").write_bytes(_xml(lines))
        dates = [mod for _, mod in chunk if mod]
        index.append(_entry("sitemap", f"{base}/sitemap-{n}.xml", max(dates) if dates else None))
    (folder / "index.xml").write_bytes(_xml([f'<sitemapindex xmlns="{SITEMAP_NS}">', *index, "</sitemapindex>"]))
    return {"sitemap_files": len(chunks), "sitemap_urls": len(entries)}


def export_static(conn: sqlite3.Connection, out_dir: Path | None = None) -> dict[str, int]:
    final = out_dir or (config.OUT_DIR / "static")
    # Written beside the final folder and moved into place only when every
    # file is written, so a failure part way leaves the previous export (or
    # none at all) rather than a half-written tree the deploy would publish.
    out = final.with_name(final.name + ".partial")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    counts = _write_static(conn, out)
    if final.exists():
        shutil.rmtree(final)
    out.rename(final)
    log_run(conn, "export", detail=f"static {counts}", rows_in=counts["search_latest"])
    return counts


def _write_static(conn: sqlite3.Connection, out: Path) -> dict[str, int]:
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    latest = meta.get("esdc_latest_period") or ""
    ind = triggered_map(conn)

    stats = write_stats(conn, out, latest, ind)
    latest_rows, long_rows, counts = write_search(conn, out, latest, ind)

    _dump(out / "clusters" / "latest.json", clusters(conn, latest_rows))
    _dump(out / "clusters" / "since_2023q4.json", clusters(conn, long_rows))

    by_fsa: dict[str, list[dict]] = defaultdict(list)
    for row in latest_rows:
        if row["postal"]:
            by_fsa[row["postal"][:3].upper()].append(row)
    centroids = {r["fsa"]: dict(r) for r in conn.execute("SELECT fsa, province, lat, lon FROM fsa_centroids")}
    areas = 0
    for fsa, rows in by_fsa.items():
        c = centroids.get(fsa)
        if c is None:
            continue
        _dump(out / "areas" / f"{fsa}.json", {"fsa": fsa, "prov": c["province"], "lat": c["lat"], "lon": c["lon"],
                                              "total": len(rows), "rows": rows[:AREA_ROW_CAP]})
        areas += 1
    counts["areas"] = areas
    # The feeds, the release pages, the trends, the program conditions, the
    # place pages and the alias map each come from their own aggregation, and
    # the site answers "not published" for a section whose files are missing
    # (a retired id without its alias file is a plain 404, as before the map
    # existed). So one bad value in one of them must not hold back the
    # night's data for every other page: a section that fails is logged as a
    # stage of its own (the run status reports it), its files stay unwritten
    # and the sitemap leaves its pages out until an export writes them again.
    # The search, map, profile and stats files are the site itself and still
    # fail the export. The search counts only spare the search API a count (it
    # counts in D1 without them), so they are a section too.
    failed: set[str] = set()
    sections = (
        ("search_counts", lambda: write_search_counts(conn, out, meta.get("data_as_of"), latest)),
        ("feeds", lambda: write_feeds(conn, out)),
        ("releases", lambda: releases.write_all(conn, out)),
        ("trends", lambda: trends.write_all(conn, out)),
        ("program", lambda: conditions.write_all(conn, out)),
        ("places", lambda: places.write_places(conn, out)),
        ("aliases", lambda: write_aliases(conn, out)),
        ("international", lambda: intl.write_all(conn, out, meta.get("data_as_of"), registers.export_rows(conn))),
        ("notices", lambda: notices.write_all(conn, out, meta.get("data_as_of"))),
    )
    for name, write in sections:
        try:
            counts.update(write())
        except Exception as exc:
            log.exception("export: the %s section failed", name)
            failed.add(name)
            log_run(conn, f"export_{name}", detail=f"{type(exc).__name__}: {exc}"[:900], ok=False)
    counts["profile_shards"] = write_profiles(conn, out)
    counts.update(write_sitemaps(conn, out, config.SITE_URL, stats["data_as_of"], skip=failed))
    counts["employers"] = stats["counts"]["employers"]
    return counts
