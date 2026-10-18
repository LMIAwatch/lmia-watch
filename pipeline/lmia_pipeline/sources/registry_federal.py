"""Corporations Canada: federal business corporations from the open-data extract.

Source: Federal Corporations, Innovation, Science and Economic Development
Canada, Open Government Licence, Canada
(https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2).
Two CSV files cover corporations under the Canada Business Corporations Act:
active, and inactive or dissolved. Each row carries the corporate name, the
status, the anniversary date (the date of incorporation or continuance), and
the registered office's city, province and postal code.

The files are cached for a week and loaded into a pipeline-local table, so no
per-employer requests are made. Employers are matched on the normalized name;
the grade is exact when the province or postal code also agrees, probable
otherwise, and nothing is stored when names differ at all.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import sqlite3
from collections import defaultdict

from ..db import get_meta, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import POSTAL_RE, format_postal, norm_name, province_code

log = logging.getLogger(__name__)

REGISTRY = "corporations_canada"
URLS = [
    "https://d4bf66bykfyaf.cloudfront.net/corporations-active-cbca-en.csv",
    "https://d4bf66bykfyaf.cloudfront.net/corporations-inactive-or-dissolved-cbca-en.csv",
]
MAX_AGE_S = 7 * 86400
CHUNK = 5000
STATUS_RANK = {"Active": 0, "Inactive": 1, "Dissolved": 2}


def _postal(raw: str | None) -> str | None:
    if not raw:
        return None
    m = POSTAL_RE.search(raw)
    return format_postal(m.group(1), m.group(2)) if m else None


def parse_extract(data: bytes, source_url: str) -> list[tuple]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple] = []
    for rec in reader:
        number = (rec.get("Corporation number") or "").strip()
        name = (rec.get("Corporate name - form 1") or "").strip()
        if not number or not name:
            continue
        rows.append((
            number,
            name,
            norm_name(name),
            (rec.get("Status") or "").strip() or None,
            (rec.get("Anniversary date") or "").strip()[:10] or None,
            (rec.get("City/town") or "").strip() or None,
            province_code(rec.get("Province/territory")),
            _postal(rec.get("Postal code")),
            source_url,
        ))
    return rows


def load_extract(conn: sqlite3.Connection, client: PoliteClient) -> int:
    """Download (cached) and load both files; returns rows loaded this run."""
    loaded = 0
    for url in URLS:
        try:
            data = client.get(url, cache=True, max_age_s=MAX_AGE_S, timeout=600)
        except FetchError as exc:
            log.warning("federal extract %s: %s", url, exc)
            continue
        sha = hashlib.sha256(data).hexdigest()
        key = f"federal_extract_sha:{url.rsplit('/', 1)[-1]}"
        if get_meta(conn, key) == sha:
            continue
        rows = parse_extract(data, url)
        conn.execute("DELETE FROM federal_corporations WHERE source_url = ?", (url,))
        for i in range(0, len(rows), CHUNK):
            conn.executemany(
                "INSERT OR REPLACE INTO federal_corporations (number, legal_name, norm_name, status, registered_on, "
                "city, province, postal_code, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows[i:i + CHUNK],
            )
        set_meta(conn, key, sha)
        conn.commit()
        loaded += len(rows)
        log.info("federal extract %s: %d rows", url.rsplit("/", 1)[-1], len(rows))
    return loaded


def renormalize(conn: sqlite3.Connection) -> int:
    """Recompute norm_name for every loaded corporation after a normalization change."""
    changed = [
        (new, number)
        for number, legal, old in conn.execute("SELECT number, legal_name, norm_name FROM federal_corporations")
        if (new := norm_name(legal)) != old
    ]
    for i in range(0, len(changed), CHUNK):
        conn.executemany("UPDATE federal_corporations SET norm_name = ? WHERE number = ?", changed[i:i + CHUNK])
    conn.commit()
    return len(changed)


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Join employers to corporations on the normalized name; keep the best per employer."""
    stamp = now or now_iso()
    if conn.execute("SELECT 1 FROM federal_corporations LIMIT 1").fetchone() is None:
        return 0  # nothing loaded yet: no lookup happened, so no check is recorded
    best: dict[str, tuple] = {}
    for r in conn.execute(
        """
        SELECT e.id AS employer_id, e.province AS e_prov, e.postal_code AS e_postal,
               f.number, f.legal_name, f.status, f.registered_on, f.province AS f_prov, f.postal_code AS f_postal
        FROM employers e JOIN federal_corporations f ON f.norm_name = e.norm_name
        WHERE e.norm_name != ''
        """
    ):
        grade = "exact" if (
            (r["e_postal"] and r["e_postal"] == r["f_postal"]) or (r["e_prov"] and r["e_prov"] == r["f_prov"])
        ) else "probable"
        rank = (0 if grade == "exact" else 1, STATUS_RANK.get(r["status"] or "", 3), -(int((r["registered_on"] or "0")[:4]) or 0))
        current = best.get(r["employer_id"])
        if current is None or rank < current[0]:
            best[r["employer_id"]] = (rank, r["number"], r["legal_name"], r["status"], r["registered_on"], grade)
    conn.executemany(
        """
        INSERT INTO registry_matches (employer_id, registry, registry_id, legal_name, entity_type, status,
          registered_on, grade, checked_at)
        VALUES (?, ?, ?, ?, 'CBCA', ?, ?, ?, ?)
        ON CONFLICT(employer_id, registry, registry_id) DO UPDATE SET
          legal_name = excluded.legal_name, status = excluded.status, registered_on = excluded.registered_on,
          grade = excluded.grade, checked_at = excluded.checked_at
        """,
        [(eid, REGISTRY, v[1], v[2], v[3], v[4], v[5], stamp) for eid, v in best.items()],
    )
    # SQLite needs the WHERE to disambiguate an upsert after INSERT ... SELECT.
    conn.execute(
        "INSERT INTO registry_checks (employer_id, registry, checked_at) SELECT id, ?, ? FROM employers WHERE true "
        "ON CONFLICT(employer_id, registry) DO UPDATE SET checked_at = excluded.checked_at",
        (REGISTRY, stamp),
    )
    conn.commit()
    return len(best)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    loaded = load_extract(conn, client)
    total = conn.execute("SELECT COUNT(*) FROM federal_corporations").fetchone()[0]
    matched = match(conn, now=now) if total else 0
    log_run(conn, "registry_federal", detail=f"corporations={total} loaded_now={loaded} matched={matched}",
            rows_in=total, rows_new=matched)
    return matched
