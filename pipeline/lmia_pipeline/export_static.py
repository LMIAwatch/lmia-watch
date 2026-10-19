"""Static JSON export: the files the site serves as assets.

Why static: a read-heavy public dataset fits the free tiers only if page views
cost nothing per row. The site therefore ships the data as JSON files beside
the Worker (static assets are free to serve), the search and map pages filter
in the browser, and the profile page reads one small shard. The database stays
on the operator's side.

Why so many slices: the browser should download only what the current view
needs. A plain visit is rendered on the server from `search/first.json`; a
filter fetches the smallest slice that answers it; the long scope is split by
province and year so no file exceeds the 25 MiB asset limit, and
`search/facets.json` carries every file's row count and size so the page can
say what a view costs before loading it.

Output tree (under data/out/static):
  stats.json                         counts, breakdowns, recent lists, resources, runs
  search/first.json                  newest FIRST_ROWS rows of the default scope
  search/facets.json                 counts by status and province for both scopes, plus file sizes
  search/latest/all.json             the default scope: pending and approved postings plus the latest quarter
  search/latest/status/<s>.json      the default scope, one status
  search/latest/prov/<P>.json        the default scope, one province
  search/latest/prov/<P>/<s>.json    the default scope, one province and one status
  search/long/<P>/postings.json      the long scope: that province's postings
  search/long/<P>/<YEAR>.json        the long scope: that province's list rows for one year
  clusters/latest.json, clusters/since_2023q4.json   per postal area counts
  areas/<FSA>.json                   rows for one postal area, latest scope, capped
  profiles/<abc>.json                employer profiles keyed by id, sharded on id characters 5 to 7
  sitemaps/sitemap-<n>.xml           the fixed pages and every profile URL, at most 50,000 per file
  sitemaps/index.xml                 the sitemap index; the site serves it at /sitemap.xml and the
                                     parts at /sitemap-<n>.xml, since a sitemap may list only URLs
                                     at or below its own directory

Every file is written deterministically (sorted keys and rows) so an unchanged
shard keeps its bytes and the deploy skips it.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from . import config, releases
from .db import log_run
from .feeds import write_feeds
from .normalize import period_end_date, period_sort_key
from .zenodo import citation_from_meta

SEARCH_FROM_PERIOD = "2023Q4"
FIRST_ROWS = 500
RECENT = 8
TOP = 6
AREA_ROW_CAP = 200
POSITIVE_DATASET = "90fed587-1364-4f33-a9ee-208181dc0b97"
NEGATIVE_DATASET = "f82f66f2-a22b-4511-bccf-e1d74db39ae5"

PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX"]
UNKNOWN_PROVINCE = "UN"
STATUSES = ["pending", "approved", "refused"]

# The sitemap protocol's limit per file (the 50 MB cap is never near: a profile
# entry is about 100 bytes).
SITEMAP_MAX_URLS = 50_000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITEMAP_PAGES = ["/", "/search", "/map", "/methodology", "/data", "/support", "/corrections"]
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


def _sort_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r["sort_date"], r["employer"] or "", r["kind"], r["ref"]), reverse=True)
    return rows


def _prov(row: dict) -> str:
    return row["prov"] or UNKNOWN_PROVINCE


def search_latest(conn: sqlite3.Connection, latest: str, ind: dict[str, list[str]]) -> list[dict]:
    rows = [posting_row(p, ind) for p in conn.execute(POSTING_SQL + " WHERE flag_current IN ('requested', 'approved')")]
    rows += [esdc_row(r, ind) for r in conn.execute(ESDC_SQL + " WHERE period = ?", (latest,))]
    return _sort_rows(rows)


def search_province(conn: sqlite3.Connection, prov: str, ind: dict[str, list[str]]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Postings for the province, and list rows grouped by the period's year."""
    where = "province IS NULL" if prov == UNKNOWN_PROVINCE else "province = ?"
    params: tuple = () if prov == UNKNOWN_PROVINCE else (prov,)
    postings = _sort_rows([posting_row(p, ind) for p in conn.execute(
        POSTING_SQL + f" WHERE flag_current IN ('requested', 'approved') AND {where}", params)])
    by_year: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(ESDC_SQL + f" WHERE {where} AND period >= ?", (*params, SEARCH_FROM_PERIOD)):
        by_year[r["period"][:4]].append(esdc_row(r, ind))
    for rows in by_year.values():
        _sort_rows(rows)
    return postings, by_year


def write_search(conn: sqlite3.Connection, out: Path, latest: str, ind: dict[str, list[str]]) -> tuple[list[dict], list[dict], dict]:
    """Write every search slice and facets.json; return (latest rows, long rows, counts)."""
    files: dict[str, dict] = {}

    def dump(rel: str, rows: list[dict]) -> None:
        files[rel] = {"rows": len(rows), "bytes": _dump(out / rel, rows)}

    latest_rows = search_latest(conn, latest, ind)
    dump("search/first.json", latest_rows[:FIRST_ROWS])
    dump("search/latest/all.json", latest_rows)
    by_status: dict[str, list[dict]] = defaultdict(list)
    by_prov: dict[str, list[dict]] = defaultdict(list)
    for row in latest_rows:
        by_status[row["status"]].append(row)
        by_prov[_prov(row)].append(row)
    for s, rows in by_status.items():
        dump(f"search/latest/status/{s}.json", rows)
    status_prov: Counter = Counter()
    for p, rows in by_prov.items():
        dump(f"search/latest/prov/{p}.json", rows)
        sub: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            sub[row["status"]].append(row)
            status_prov[f"{row['status']}|{p}"] += 1
        for s, rows2 in sub.items():
            dump(f"search/latest/prov/{p}/{s}.json", rows2)
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
            dump(f"search/long/{prov}/postings.json", postings)
            long_prov_year[f"{prov}|postings"] += len(postings)
        for year, rows in sorted(by_year.items()):
            dump(f"search/long/{prov}/{year}.json", rows)
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


def write_stats(conn: sqlite3.Connection, out: Path, latest: str, ind: dict[str, list[str]]) -> dict:
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    counts = {
        "pending": int(meta.get("count_pending", 0)),
        "approved_records": int(meta.get("count_approved_records", 0)),
        "approved_positions": int(meta.get("count_approved_positions", 0)),
        "refused_records": int(meta.get("count_refused_records", 0)),
        "findings": int(meta.get("count_findings", 0)),
        "employers": conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0],
    }
    by_stream = [{"k": r["k"] or "Unknown", "n": r["n"]} for r in conn.execute(
        "SELECT stream AS k, COUNT(*) AS n FROM esdc_records WHERE list = 'positive' AND period = ? GROUP BY stream ORDER BY n DESC", (latest,))]
    by_province = [{"k": r["k"] or "Unknown", "n": r["n"]} for r in conn.execute(
        "SELECT province AS k, COUNT(*) AS n FROM esdc_records WHERE list = 'positive' AND period = ? GROUP BY province ORDER BY n DESC", (latest,))]
    recent_pending = [posting_row(p, ind) for p in conn.execute(
        POSTING_SQL + " WHERE flag_current = 'requested' ORDER BY date_posted DESC, posting_id DESC LIMIT ?", (RECENT,))]
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
    first_year = int(SEARCH_FROM_PERIOD[:4])
    last_year = int(latest[:4]) if latest[:4].isdigit() else first_year
    stats = {
        "data_as_of": meta.get("data_as_of"),
        "jobbank_last_run": meta.get("jobbank_last_run"),
        "esdc_latest_period": latest,
        "esdc_latest_published": meta.get("esdc_latest_published"),
        "rules_version": meta.get("rules_version"),
        "search_from_period": SEARCH_FROM_PERIOD,
        "search_years": list(range(first_year, max(first_year, last_year) + 1)),
        "counts": counts,
        "by_stream": by_stream,
        "by_province": by_province,
        "recent_pending": recent_pending,
        "recent_approved": recent_approved,
        "top_approvals": top,
        "resources": resources,
        "runs": runs,
        # The Zenodo record behind "How to cite"; null until one is published.
        "citation": citation_from_meta(meta),
    }
    _dump(out / "stats.json", stats)
    return stats


def shard_key(employer_id: str) -> str:
    return employer_id[4:7]


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
            }
        _dump(out / "profiles" / f"{key}.json", shard)
        written += 1
    return written


def _lastmod(value: str | None) -> str | None:
    """The date part of an ISO date or datetime, or None for anything else."""
    if value and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def sitemap_entries(conn: sqlite3.Connection, data_as_of: str | None) -> list[tuple[str, str | None]]:
    """(path, lastmod) for the fixed pages, the release pages, then every profile in id order.

    A profile's lastmod is the employer row's updated_at, which status.recompute
    rewrites only when something on the profile changed.
    """
    dated = _lastmod(data_as_of)
    entries: list[tuple[str, str | None]] = [(p, dated if p in SITEMAP_DATED_PAGES else None) for p in SITEMAP_PAGES]
    # Feeds and the browser watchlist. The feed list follows the nightly data;
    # the watchlist page changes only with the code.
    entries += [("/feeds", dated), ("/watchlist", None)]
    # --- releases and rankings: /releases, /rankings, each year's rankings and
    # each release page, dated by the lists' publication; none until a list is
    # loaded, so an empty page is never listed.
    entries += releases.sitemap_entries(conn)
    entries += [(f"/employers/{r['id']}", _lastmod(r["updated_at"]))
                for r in conn.execute("SELECT id, updated_at FROM employers ORDER BY id")]
    return entries


def sitemap_chunks(entries: Sequence, max_urls: int = SITEMAP_MAX_URLS) -> list[Sequence]:
    return [entries[i:i + max_urls] for i in range(0, len(entries), max_urls)]


def _xml(lines: list[str]) -> bytes:
    return ("\n".join(['<?xml version="1.0" encoding="UTF-8"?>', *lines]) + "\n").encode("utf-8")


def _entry(tag: str, loc: str, lastmod: str | None) -> str:
    stamp = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return f"<{tag}><loc>{escape(loc)}</loc>{stamp}</{tag}>"


def write_sitemaps(conn: sqlite3.Connection, out: Path, base_url: str, data_as_of: str | None,
                   max_urls: int = SITEMAP_MAX_URLS) -> dict[str, int]:
    """Write sitemaps/sitemap-<n>.xml and the index that lists them.

    URLs are absolute, as the protocol requires, on `base_url`. The index names
    each part at the site root (/sitemap-<n>.xml), where the site serves it, with
    the newest lastmod inside that part.
    """
    base = base_url.rstrip("/")
    entries = sitemap_entries(conn, data_as_of)
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
    counts.update(write_feeds(conn, out))
    counts.update(releases.write_all(conn, out))
    counts["profile_shards"] = write_profiles(conn, out)
    counts.update(write_sitemaps(conn, out, config.SITE_URL, stats["data_as_of"]))
    counts["employers"] = stats["counts"]["employers"]
    return counts
