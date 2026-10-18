"""Statistics Canada Labour Force Survey: unemployment rate by census metropolitan area.

Source: table 14-10-0459-01, "Labour force characteristics by census
metropolitan area, three-month moving average, seasonally adjusted", which
also carries the unadjusted series. Statistics Canada Open Licence. The full
table is one zipped CSV (https://www150.statcan.gc.ca/n1/tbl/csv/14100459-eng.zip,
about 4 MB, 61 MB unzipped), released monthly with the survey. It is fetched
at most once every 30 days; the date of the last check is kept in the
database, because the nightly runner starts with an empty download cache.
The low-wage rule needs windows that end three months or more before the
newest ESDC quarter, so a month's delay never leaves it short.

Only the unadjusted unemployment rate for the 41 census metropolitan areas is
kept. That is the figure ESDC's refusal-to-process table on canada.ca shows:
the rates in force from 2026-10-09 equal the unadjusted three-month averages
ending 2026-09 (Winnipeg 5.9, Toronto 7.5, Calgary 6.4, Vancouver 7.0).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import sqlite3
import zipfile

from ..db import get_meta, hours_since, log_run, now_iso, set_meta
from ..http import PoliteClient

log = logging.getLogger(__name__)

URL = "https://www150.statcan.gc.ca/n1/tbl/csv/14100459-eng.zip"
TABLE = "14-10-0459-01"
CHECK_EVERY_HOURS = 30 * 24
# DGUID prefix of a 2021 CMA; CMA parts (Ottawa-Gatineau's two sides) use 2021S0505.
CMA_PREFIX = "2021S0503"


def parse_table(data: bytes) -> list[tuple[str, str, float, str, str | None]]:
    """Rows (cma_uid, ref_month, rate, cma_name, vector) from the zipped table."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv") and "metadata" not in n.lower()]
        if not names:
            raise ValueError("no data CSV in the LFS archive")
        text = zf.read(names[0]).decode("utf-8-sig")
    out: dict[tuple[str, str], tuple[str, str, float, str, str | None]] = {}
    for rec in csv.DictReader(io.StringIO(text)):
        if rec.get("Labour force characteristics") != "Unemployment rate":
            continue
        if rec.get("Statistics") != "Estimate" or rec.get("Data type") != "Unadjusted":
            continue
        dguid = (rec.get("DGUID") or "").strip()
        if not dguid.startswith(CMA_PREFIX):
            continue
        try:
            rate = float(rec.get("VALUE") or "")
        except ValueError:
            continue
        # Statistics Canada drops leading zeros (St. John's is 2021S05031 for CMA 001).
        uid = dguid[len(CMA_PREFIX):].zfill(3)
        month = (rec.get("REF_DATE") or "")[:7]
        name = (rec.get("GEO") or "").rsplit(",", 1)[0].strip()
        out[(uid, month)] = (uid, month, rate, name, (rec.get("VECTOR") or "").strip() or None)
    return list(out.values())


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    have = conn.execute("SELECT COUNT(*) FROM lfs_unemployment").fetchone()[0]
    hours = hours_since(conn, "lfs_checked_at", now=stamp)
    if have and hours is not None and hours < CHECK_EVERY_HOURS:
        log_run(conn, "lfs", detail=f"skipped: checked {hours / 24:.0f} days ago; rows={have}", rows_in=have)
        return 0
    data = client.get(URL, cache=True, max_age_s=3600, timeout=300)
    sha = hashlib.sha256(data).hexdigest()
    loaded = 0
    if get_meta(conn, "lfs_sha") != sha:
        rows = parse_table(data)
        if not rows:
            raise ValueError("LFS table held no CMA unemployment rates")
        conn.execute("DELETE FROM lfs_unemployment")
        conn.executemany(
            "INSERT INTO lfs_unemployment (cma_uid, ref_month, rate, cma_name, vector) VALUES (?, ?, ?, ?, ?)", rows
        )
        set_meta(conn, "lfs_sha", sha)
        loaded = len(rows)
        log.info("lfs: %d CMA months", loaded)
    set_meta(conn, "lfs_checked_at", stamp)
    conn.commit()
    total, latest = conn.execute("SELECT COUNT(*), MAX(ref_month) FROM lfs_unemployment").fetchone()
    log_run(conn, "lfs", detail=f"table={TABLE} rows={total} latest={latest} loaded_now={loaded}",
            rows_in=total, rows_new=loaded)
    return loaded
