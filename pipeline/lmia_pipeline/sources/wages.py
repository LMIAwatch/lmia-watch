"""Job Bank wages by occupation and area, the prevailing-wage reference.

Source: Wages, Employment and Social Development Canada, on open.canada.ca
under the Open Government Licence, Canada
(https://open.canada.ca/data/en/dataset/adad580f-76b0-4502-bd05-20c125de9116).
One CSV a year (the 2025 file is about 18 MB, revised 2025-11-19) gives the
low, median and high wage for each NOC 2021 occupation in Canada, in each
province and territory, and in each of the 76 economic regions. ESDC tells
employers to pay at least the Job Bank median for the economic region of the
job, or the provincial and then the national median where the regional one
is shown as N/A.

The dataset listing is read at most once every 30 days; the date of the last
check is kept in the database, because the nightly runner starts with an
empty download cache. A file is downloaded only when its resource is new or
its modified date changed. The newest two tables are kept, so a posting is
compared with the table in force on its posting date. Rows without a
published median are not stored.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import re
import sqlite3

from .. import config
from ..db import hours_since, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import PRUID_PROVINCE, iso_date
from .esdc import decode_csv_bytes

log = logging.getLogger(__name__)

DATASET = "adad580f-76b0-4502-bd05-20c125de9116"
CHECK_EVERY_HOURS = 30 * 24
FILE_MAX_AGE_S = 365 * 86400
KEEP_TABLES = 2

# Column names carry both languages and change slightly between years
# (Source2025_NHQ, Non_WageBen_pct), so columns are found by prefix.
COLUMNS = {
    "noc": "noc_cnp",
    "area": "er_code",
    "name": "er_name",
    "low": "low_wage",
    "median": "median_wage",
    "high": "high_wage",
    "reference": "reference_period",
    "revision": "revision_date",
    "annual": "annual_wage_flag",
}


def _columns(headers: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, prefix in COLUMNS.items():
        for header in headers:
            if header and header.strip().lower().startswith(prefix):
                out[key] = header
                break
    return out


def _num(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_wages(data: bytes) -> tuple[list[tuple], str | None]:
    """Rows (noc, area_code, province, area_name, median, low, high, annual, reference) and the revision date."""
    reader = csv.DictReader(io.StringIO(decode_csv_bytes(data)))
    cols = _columns(list(reader.fieldnames or []))
    missing = [k for k in ("noc", "area", "median") if k not in cols]
    if missing:
        raise ValueError(f"wage file lacks columns: {', '.join(missing)}")
    rows: dict[tuple[str, str], tuple] = {}
    revision: str | None = None
    for rec in reader:
        median = _num(rec.get(cols["median"]))
        noc = re.search(r"(\d{5})", rec.get(cols["noc"]) or "")
        area = re.sub(r"\D", "", rec.get(cols["area"]) or "")
        if median is None or median <= 0 or noc is None or len(area) not in (2, 4):
            continue
        rev = iso_date((rec.get(cols.get("revision", "")) or "").strip()) if "revision" in cols else None
        if rev and (revision is None or rev > revision):
            revision = rev
        annual = 1 if (rec.get(cols.get("annual", "")) or "").strip() == "1" else 0
        rows[(noc.group(1), area)] = (
            noc.group(1),
            area,
            None if area == "00" else PRUID_PROVINCE.get(area[:2]),
            (rec.get(cols.get("name", "")) or "").strip() or area,
            median,
            _num(rec.get(cols.get("low", ""))),
            _num(rec.get(cols.get("high", ""))),
            annual,
            (rec.get(cols.get("reference", "")) or "").strip() or None,
        )
    return list(rows.values()), revision


def newest_resources(package: dict) -> list[dict]:
    resources = package.get("result", {}).get("resources", [])
    csvs = [r for r in resources if (r.get("url") or "").lower().endswith(".csv")]
    csvs.sort(key=lambda r: (r.get("created") or "", r.get("id") or ""), reverse=True)
    return csvs[:KEEP_TABLES]


def modified(res: dict) -> str:
    return str(res.get("last_modified") or res.get("created") or "")


def load_table(conn: sqlite3.Connection, res: dict, data: bytes, *, now: str | None = None) -> int:
    """Load one yearly CSV; returns rows loaded, 0 when the same file is already in."""
    stamp = now or now_iso()
    sha = hashlib.sha256(data).hexdigest()
    existing = conn.execute("SELECT sha256 FROM wage_tables WHERE resource_id = ?", (res["id"],)).fetchone()
    if existing and existing["sha256"] == sha:
        conn.execute("UPDATE wage_tables SET source_modified = ? WHERE resource_id = ?", (modified(res), res["id"]))
        conn.commit()
        return 0
    rows, revision = parse_wages(data)
    name = res.get("name")
    if isinstance(name, dict):
        name = name.get("en")
    conn.execute("DELETE FROM jobbank_wages WHERE resource_id = ?", (res["id"],))
    conn.executemany(
        "INSERT INTO jobbank_wages (resource_id, noc_code, area_code, province, area_name, median, low, high, "
        "annual, reference_period) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(res["id"], *row) for row in rows],
    )
    conn.execute(
        """
        INSERT INTO wage_tables (resource_id, name, url, source_modified, revision_date, sha256, bytes,
          rows_loaded, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(resource_id) DO UPDATE SET
          name = excluded.name, url = excluded.url, source_modified = excluded.source_modified,
          revision_date = excluded.revision_date, sha256 = excluded.sha256, bytes = excluded.bytes,
          rows_loaded = excluded.rows_loaded, loaded_at = excluded.loaded_at
        """,
        (res["id"], name or "", res.get("url") or "", modified(res), revision or iso_date(res.get("created")),
         sha, len(data), len(rows), stamp),
    )
    conn.commit()
    return len(rows)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    loaded_tables = {
        r["resource_id"]: r["source_modified"]
        for r in conn.execute("SELECT resource_id, source_modified FROM wage_tables")
    }
    hours = hours_since(conn, "wages_checked_at", now=stamp)
    if loaded_tables and hours is not None and hours < CHECK_EVERY_HOURS:
        log_run(conn, "wages", detail=f"skipped: checked {hours / 24:.0f} days ago; tables={len(loaded_tables)}",
                rows_in=len(loaded_tables))
        return 0
    listing = config.CKAN_PACKAGE_SHOW.format(dataset=DATASET)
    try:
        package = client.get_json(listing, cache=True, max_age_s=3600)
        keep = newest_resources(package)
    except (ValueError, AttributeError):
        client.forget(listing)  # an error page cached as the listing is not reused
        raise
    loaded = 0
    failures: list[str] = []
    for res in keep:
        if loaded_tables.get(res["id"]) == modified(res):
            continue
        try:
            data = client.get(res["url"], cache=True, max_age_s=FILE_MAX_AGE_S, timeout=300)
        except FetchError as exc:
            failures.append(f"{res.get('id')}: {exc}")
            continue
        try:
            n = load_table(conn, res, data, now=stamp)
        except Exception as exc:  # a malformed year must not drop the table already loaded
            conn.rollback()
            # The file is cached for a year; without this a bad copy (an empty
            # or truncated download, an error page) would be re-read every
            # night instead of fetched again.
            client.forget(res["url"])
            failures.append(f"{res.get('id')}: {exc}")
            log.warning("wage table %s failed: %s", res.get("id"), exc)
            continue
        loaded += n
        if n:
            log.info("wage table %s: %d rows", res.get("id"), n)
    if keep and not failures:
        ids = [r["id"] for r in keep]
        marks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM jobbank_wages WHERE resource_id NOT IN ({marks})", ids)
        conn.execute(f"DELETE FROM wage_tables WHERE resource_id NOT IN ({marks})", ids)
        set_meta(conn, "wages_checked_at", stamp)
        conn.commit()
    tables = conn.execute("SELECT COUNT(*) FROM wage_tables").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM jobbank_wages").fetchone()[0]
    detail = f"tables={tables} rows={total} loaded_now={loaded}"
    if failures:
        detail += " failures=" + "; ".join(failures)[:900]
    log_run(conn, "wages", detail=detail, rows_in=total, rows_new=loaded, ok=not failures)
    return loaded
