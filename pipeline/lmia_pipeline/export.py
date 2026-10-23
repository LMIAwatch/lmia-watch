"""Exports: CSV files for the Data page and the raw ESDC mirror.

The hosted search database has its own sync (search_db.py).
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import sqlite3
from pathlib import Path

from . import config


# -- CSV and mirror ---------------------------------------------------------

CSV_QUERIES: dict[str, str] = {
    "pending_observations.csv": """
        SELECT o.posting_id, o.observed_at, o.flag, p.employer_id, p.employer_raw AS employer, p.title,
               p.noc_code, p.city, p.province, p.postal_code, p.wage_min, p.wage_max, p.wage_unit,
               p.vacancies, p.date_posted, p.valid_through, p.url
        FROM jobbank_observations o JOIN jobbank_postings p ON p.posting_id = o.posting_id
        ORDER BY o.observed_at, o.posting_id""",
    "approved_quarterly.csv": """
        SELECT period, employer_id, employer_raw AS employer, province, stream, city, postal_code,
               noc_code, noc_title, incorporate_status, lmias AS approved_lmias,
               positions AS approved_positions, resource_id
        FROM esdc_records WHERE list = 'positive' ORDER BY period, province, employer_raw""",
    "refused_quarterly.csv": """
        SELECT period, employer_id, employer_raw AS employer, province, stream, city, postal_code,
               noc_code, noc_title, incorporate_status, lmias AS requested_lmias,
               positions AS requested_positions, resource_id
        FROM esdc_records WHERE list = 'negative' ORDER BY period, province, employer_raw""",
    "employers.csv": """
        SELECT id, display_name, province, city, postal_code, street, current_status, first_seen,
               last_seen, pending_count, approved_lmias, approved_positions, refused_lmias,
               refused_positions, finding_count, indicator_count, registry_grade
        FROM employers ORDER BY province, display_name""",
    "indicators.csv": "SELECT employer_id, indicator, state, basis, rule_version, computed_at FROM indicators ORDER BY employer_id, indicator",
    "findings.csv": "SELECT employer_id, operating_name, legal_name, address, reasons, decision_date, penalty, status FROM findings ORDER BY decision_date",
    "esdc_resources.csv": "SELECT resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, loaded_at FROM esdc_resources ORDER BY dataset, period",
}


def export_csv(conn: sqlite3.Connection, out_dir: Path | None = None) -> dict[str, int]:
    out = out_dir or (config.OUT_DIR / "csv")
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, query in CSV_QUERIES.items():
        cur = conn.execute(query)
        headers = [d[0] for d in cur.description]
        # Each file is written under a temporary name and renamed when
        # complete, so a failure never leaves a truncated CSV for the upload.
        part = out / f"{name}.partial"
        with part.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            n = 0
            for row in cur:
                writer.writerow([row[h] for h in headers])
                n += 1
        part.replace(out / name)
        counts[name] = n
    return counts


def export_mirror(conn: sqlite3.Connection, out_dir: Path | None = None, cache_dir: Path | None = None) -> int:
    """Copy the raw ESDC files beside a SHA256SUMS file so readers can verify them."""
    out = out_dir or (config.OUT_DIR / "mirror")
    cache = cache_dir or config.CACHE_DIR
    out.mkdir(parents=True, exist_ok=True)
    sums: list[str] = []
    copied = 0
    for r in conn.execute("SELECT url, sha256, dataset, period FROM esdc_resources ORDER BY dataset, period"):
        key = hashlib.sha1(r["url"].encode("utf-8")).hexdigest()
        src = cache / f"{key}.bin"
        if not src.exists():
            continue
        name = f"{r['dataset']}_{r['period']}_{r['url'].rsplit('/', 1)[-1]}"
        shutil.copyfile(src, out / name)
        sums.append(f"{r['sha256']}  {name}")
        copied += 1
    (out / "SHA256SUMS").write_text("\n".join(sums) + ("\n" if sums else ""), encoding="utf-8")
    return copied
