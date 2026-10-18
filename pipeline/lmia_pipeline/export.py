"""Exports: CSV files for the Data page, the raw ESDC mirror, and D1 batches.

The D1 export is incremental. Each pipeline-owned table has a high-water
column; rows past the mark recorded in d1_sync are written as INSERT OR
REPLACE (or plain INSERT for append-only tables). The marks are written to a
manifest, and `mark-synced` commits them only after the batches were applied,
so a failed apply simply re-exports the same rows next time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from . import config
from .db import log_run, now_iso

# table -> (high-water column, mode). mode: replace | append | full
TABLES: dict[str, tuple[str | None, str]] = {
    "meta": (None, "full"),
    "fsa_centroids": (None, "full"),
    "employers": ("updated_at", "replace"),
    "jobbank_postings": ("updated_at", "replace"),
    "indicators": ("computed_at", "replace"),
    "registry_matches": ("checked_at", "replace"),
    "findings": ("fetched_at", "replace"),
    "esdc_resources": ("loaded_at", "replace"),
    "esdc_records": ("id", "append"),
    "jobbank_observations": ("observed_at", "append"),
    "employer_names": ("rowid", "append"),
}
ROWS_PER_STATEMENT = 40
MAX_FILE_BYTES = 2 * 1024 * 1024


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value).replace("'", "''").replace("\x00", "")
    return f"'{text}'"


class _BatchWriter:
    def __init__(self, out_dir: Path, start_index: int) -> None:
        self.out_dir = out_dir
        self.index = start_index
        self.files: list[str] = []
        self._buf: list[str] = []
        self._size = 0
        self._name = ""

    def start(self, name: str) -> None:
        self.flush()
        self._name = name

    def add(self, statement: str) -> None:
        if self._size + len(statement) > MAX_FILE_BYTES and self._buf:
            self.flush()
        self._buf.append(statement)
        self._size += len(statement) + 1

    def flush(self) -> None:
        if not self._buf:
            return
        path = self.out_dir / f"{self.index:03d}_{self._name}.sql"
        path.write_text("\n".join(self._buf) + "\n", encoding="utf-8")
        self.files.append(path.name)
        self.index += 1
        self._buf = []
        self._size = 0


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _insert_statements(table: str, columns: list[str], rows: list[sqlite3.Row], verb: str):
    cols = ", ".join(columns)
    for i in range(0, len(rows), ROWS_PER_STATEMENT):
        chunk = rows[i:i + ROWS_PER_STATEMENT]
        values = ",\n".join("(" + ", ".join(sql_literal(r[c]) for c in columns) + ")" for r in chunk)
        yield f"{verb} INTO {table} ({cols}) VALUES\n{values};"


def export_d1(conn: sqlite3.Connection, out_dir: Path | None = None, *, full: bool = False) -> dict:
    out = out_dir or (config.OUT_DIR / "d1")
    if out.exists():
        for old in out.glob("*.sql"):
            old.unlink()
    out.mkdir(parents=True, exist_ok=True)
    stamp = now_iso()

    shutil.copyfile(config.SCHEMA_PATH, out / "000_schema.sql")
    files = ["000_schema.sql"]
    writer = _BatchWriter(out, 1)
    if full:
        writer.start("reset")
        for table in reversed(list(TABLES)):
            writer.add(f"DELETE FROM {table};")
        writer.flush()

    marks = {r["table_name"]: r["high_water"] for r in conn.execute("SELECT table_name, high_water FROM d1_sync")}
    new_marks: dict[str, str] = {}
    counts: dict[str, int] = {}
    for table, (hw_col, mode) in TABLES.items():
        columns = _columns(conn, table)
        select_cols = ", ".join(columns)
        if mode == "full" or full or hw_col is None or table not in marks:
            rows = conn.execute(f"SELECT {select_cols} FROM {table}").fetchall()
        else:
            rows = conn.execute(
                f"SELECT {select_cols} FROM {table} WHERE {hw_col} > ?", (marks[table],)
            ).fetchall()
        counts[table] = len(rows)
        if hw_col is not None:
            top = conn.execute(f"SELECT MAX({hw_col}) AS m FROM {table}").fetchone()["m"]
            if top is not None:
                new_marks[table] = str(top)
        if not rows:
            continue
        verb = "INSERT OR IGNORE" if mode == "append" and table == "employer_names" else (
            "INSERT OR REPLACE" if mode != "append" else "INSERT OR IGNORE"
        )
        writer.start(table)
        for stmt in _insert_statements(table, columns, rows, verb):
            writer.add(stmt)
        writer.flush()
    files.extend(writer.files)

    manifest = {
        "generated_at": stamp,
        "full": full,
        "files": files,
        "row_counts": counts,
        "high_water": new_marks,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log_run(conn, "export", detail=f"d1 files={len(files)} rows={sum(counts.values())} full={full}",
            rows_in=sum(counts.values()))
    return manifest


def mark_synced(conn: sqlite3.Connection, manifest_path: Path | None = None) -> int:
    path = manifest_path or (config.OUT_DIR / "d1" / "manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    marks = manifest.get("high_water", {})
    for table, value in marks.items():
        conn.execute(
            "INSERT INTO d1_sync (table_name, high_water) VALUES (?, ?) "
            "ON CONFLICT(table_name) DO UPDATE SET high_water = excluded.high_water",
            (table, value),
        )
    conn.commit()
    return len(marks)


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
