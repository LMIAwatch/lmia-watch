"""SQLite helpers: open, apply the shared schema, upsert employers, log runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .normalize import employer_id, norm_name, split_trade_name


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def connect(path: str | Path | None = None, *, memory: bool = False) -> sqlite3.Connection:
    if memory:
        conn = sqlite3.connect(":memory:")
    else:
        p = Path(path) if path else config.DEFAULT_DB
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    return conn


# Columns added to existing tables after the first release, each with the
# statement that backfills it. add_missing_columns adds every column the schema
# has and an older database lacks; this list is for the ones that also need a
# value for the rows already there.
ADDED_COLUMNS: list[tuple[str, str, str, str | None]] = [
    ("employers", "street_source", "TEXT",
     "UPDATE employers SET street_source = 'jobbank' WHERE street IS NOT NULL AND street_source IS NULL"),
]


def apply_schema(conn: sqlite3.Connection, schema_path: Path | None = None) -> None:
    sql = (schema_path or config.SCHEMA_PATH).read_text(encoding="utf-8")
    # Columns first: an index in the schema may name a column that a database
    # from an earlier version lacks, and the script would stop there.
    added = add_missing_columns(conn, sql)
    conn.executescript(sql)
    for table, column, decl, backfill in ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            added.append(f"{table}.{column}")
        # Backfilled once, on the run that added the column (a fresh database
        # gets it from the schema, with no rows to fill).
        if backfill and f"{table}.{column}" in added:
            conn.execute(backfill)
            conn.commit()


def add_missing_columns(conn: sqlite3.Connection, sql: str) -> list[str]:
    """Bring tables from an earlier schema up to date without a migration step.

    New tables come from the schema's CREATE TABLE IF NOT EXISTS, but a column
    added to an existing table would not, and the first query naming it would
    stop the run. The schema is built in memory and every column missing from
    the database is added with its type and default. A key column cannot be
    added this way and is left for a deliberate migration; a NOT NULL column
    with no default is added as nullable. Returns the columns added.
    """
    added: list[str] = []
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(sql)
        tables = [r[0] for r in ref.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            have = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            if not have:
                continue  # not there yet; the schema script creates it whole
            for _cid, name, ctype, notnull, default, pk in ref.execute(f'PRAGMA table_info("{table}")'):
                if name in have or pk:
                    continue
                clause = f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ctype or ""}'.rstrip()
                if default is not None:
                    clause += f" DEFAULT {default}"
                    if notnull:
                        clause += " NOT NULL"
                conn.execute(clause)
                added.append(f"{table}.{name}")
        if added:
            conn.commit()
    finally:
        ref.close()
    return added


def set_meta(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def hours_since(conn: sqlite3.Connection, key: str, *, now: str | None = None) -> float | None:
    """Hours since the ISO datetime stored under a meta key; None when unset or unparseable."""
    value = get_meta(conn, key)
    if not value:
        return None
    try:
        then = datetime.fromisoformat(value.replace("Z", "+00:00"))
        current = datetime.fromisoformat((now or now_iso()).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (current - then).total_seconds() / 3600.0


def upsert_employer(
    conn: sqlite3.Connection,
    raw_name: str,
    province: str | None,
    *,
    source: str,
    city: str | None = None,
    postal_code: str | None = None,
    street: str | None = None,
    now: str | None = None,
) -> str:
    """Create or refresh the merged employer row and return its id.

    The identity is the legal part of the name (normalize.split_trade_name);
    the raw spelling and any operating name after "dba" or "o/a" are both
    recorded as names seen. Location fields only fill blanks; status and
    counts are recomputed by status.recompute, so this function never touches
    them.
    """
    raw = raw_name.strip()
    norm = norm_name(raw)
    eid = employer_id(norm, province)
    stamp = now or now_iso()
    conn.execute(
        """
        INSERT INTO employers (id, display_name, norm_name, province, city, postal_code, street, street_source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          city = COALESCE(employers.city, excluded.city),
          postal_code = COALESCE(employers.postal_code, excluded.postal_code),
          street_source = CASE WHEN employers.street IS NULL THEN excluded.street_source ELSE employers.street_source END,
          street = COALESCE(employers.street, excluded.street)
        """,
        (eid, raw, norm, province, city, postal_code, street, source if street else None, stamp),
    )
    record_names(conn, eid, source, raw, split_trade_name(raw)[1])
    return eid


def record_names(conn: sqlite3.Connection, eid: str, source: str, *names: str | None) -> int:
    """Add names seen for an employer, ignoring blanks and repeats; returns rows added."""
    added = 0
    for name in names:
        text = (name or "").strip()
        if text:
            cur = conn.execute(
                "INSERT OR IGNORE INTO employer_names (employer_id, raw_name, source) VALUES (?, ?, ?)",
                (eid, text, source),
            )
            added += cur.rowcount
    return added


def log_run(
    conn: sqlite3.Connection,
    source: str,
    *,
    detail: str = "",
    rows_in: int = 0,
    rows_new: int = 0,
    excluded: int = 0,
    ok: bool = True,
) -> None:
    conn.execute(
        "INSERT INTO sources_log (run_at, source, detail, rows_in, rows_new, excluded, ok) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), source, detail, rows_in, rows_new, excluded, 1 if ok else 0),
    )
    conn.commit()
