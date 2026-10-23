"""The hosted search database: its rows, and the nightly sync that keeps it current.

The search database (D1 `lmia-watch-search`, schema in pipeline/search_schema.sql)
holds one row per ESDC list row since 2014 and per Job Bank posting whose LMIA
flag is requested or approved. These are the rows and fields export_static
writes for the search page, built by the same functions, plus a stable integer
id, the year, the employer name folded for sorting, and a content hash.

Why a ledger: sending all 487,000 rows every night would cost millions of row
writes each time for a dataset that changes by a few thousand rows a day. The
pipeline-local table `search_sync` (schema.sql) records the key, rid and hash
of every row as last confirmed in D1, and tonight's rows are compared with it:

  plan_sync      the upserts (a new key, or a hash that changed) and the
                 deletes (a key the ledger holds that tonight's rows lack)
  write_batches  SQL files of at most 5 MB or 5,000 statements each (up to
                 100 rows per upsert, 500 keys per delete, 64 KiB per
                 statement), plus manifest.json: the files in order, the
                 counts, the row total D1 must hold afterwards, and the
                 ledger entries to record
  record_sync    applies those entries. The workflow calls it (search-synced)
                 only after every batch applied and the row count read back
                 from D1 matched the manifest

Nothing else writes the ledger, so a night that failed part way leaves it as
it was and the next night sends the same changes again; every statement in a
batch can be applied twice with the same result.

A full reload drops both tables, applies the schema again and sends every
row. `search-sync --full` asks for one. The sync makes one by itself on an
empty ledger (the first load, or a database restored without its ledger) and
after the count read back from D1 disagreed with the manifest (search-check
notes the date in meta), but not within RELOAD_MIN_DAYS of the last one, so a
fault that keeps the count wrong cannot reload every night. The count can
stay wrong in a way a resend cannot repair: a row applied on a night whose
later batch failed, then gone from the data before the retry, is in D1 but
was never in the ledger, so no night would delete it; a full reload removes
every such row. Between reloads an empty ledger still sends every row, and a
row D1 already holds with the same hash costs no write.

No value here comes from a visitor (the rows are pipeline data), but each is
still written as a literal no content can break out of; see sql_literal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config, export_static
from .db import get_meta, now_iso, set_meta, today_iso

TABLE = "search_rows"
# The fields of a search row, in the order export_static writes them.
ROW_FIELDS = (
    "kind", "ref", "employer_id", "employer", "job", "noc", "street", "city", "prov", "postal",
    "wage_min", "wage_max", "unit", "date", "period", "positions", "status", "stream", "source", "sort_date",
)
EXTRA_FIELDS = ("year", "ind", "name_fold")
# Every column but the hash, in the order the hash reads them. Changing this
# order changes every hash, which resends every row once.
HASHED = ("rid", "key") + ROW_FIELDS + EXTRA_FIELDS
COLUMNS = HASHED + ("hash",)

# D1 runs each batch file as one import; these keep a file small enough to
# upload and apply in seconds, and a failed one cheap to retry.
MAX_BATCH_BYTES = 5_000_000
MAX_BATCH_STATEMENTS = 5_000
# Rows go several to a statement, since the ON CONFLICT clause is longer than
# a row and is written once per statement. D1 refuses a statement above
# 100,000 bytes, so a statement stays under 64 KiB whatever the names hold.
MAX_ROWS_PER_UPSERT = 100
MAX_KEYS_PER_DELETE = 500
MAX_STATEMENT_BYTES = 64 * 1024
# A full reload writes about as many rows as a month of nights, so one forced
# by a count that disagreed is not repeated within this many days.
RELOAD_MIN_DAYS = 7

META_RELOAD = "search_reload_due"       # the date search-check found the count disagreeing
META_FULL_AT = "search_full_at"         # the date the last full reload was written
MANIFEST = "manifest.json"
OUTCOME = "last_outcome.txt"            # under data/out/search, read by `nightly status`

_MARKS = re.compile("[\u0300-\u036f]")
_INT64 = (-(2 ** 63), 2 ** 63 - 1)

# The statements a batch holds. Rows are written with INSERT ... ON CONFLICT
# DO UPDATE rather than INSERT OR REPLACE: REPLACE deletes the old row without
# firing the delete trigger (unless recursive triggers are on), and the
# full-text index would keep the old name. The WHERE makes a row already
# carrying tonight's hash cost no write when a batch is applied again.
_UPSERT_HEAD = f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES "
_UPSERT_TAIL = (
    " ON CONFLICT (rid) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in COLUMNS if c != "rid")
    + f" WHERE {TABLE}.hash IS NOT excluded.hash;"
)
_DELETE_HEAD = f"DELETE FROM {TABLE} WHERE key IN ("
_DELETE_TAIL = ");"
# The first batch of a full reload. Dropping the tables takes their indexes
# and triggers with them and costs no per-row work, where a DELETE would fire
# the index trigger once per row; the schema then creates them as they are
# written today, so a changed column or tokenizer reaches D1 this way.
_RESET_HEAD = (
    "-- Full reload: drop the search tables and create them again from search_schema.sql.\n"
    "DROP TABLE IF EXISTS search_fts;\n"
    f"DROP TABLE IF EXISTS {TABLE};\n"
)


# -- the rows ----------------------------------------------------------------


def fold(text: str | None) -> str:
    """Lower case without accents, the way search.js's fold does it: NFD,
    combining marks U+0300 to U+036F removed, then lower case."""
    t = text or ""
    if t.isascii():
        return t.lower()
    return _MARKS.sub("", unicodedata.normalize("NFD", t)).lower()


def _year(text: str | None) -> int | None:
    head = (text or "")[:4]
    return int(head) if len(head) == 4 and head.isascii() and head.isdigit() else None


def table_row(row: dict) -> dict:
    """A search row as export_static builds it, as a search_rows row (without the hash).

    rid doubles the source id and adds one for a posting, so a list row and a
    posting never share one, and a row keeps it for as long as its source row
    exists. The year is the list period's on a list row and the sort date's on
    a posting (its posting date, else the day it was first seen).
    """
    posting = row["kind"] == "posting"
    ref = row["ref"]
    if not isinstance(ref, int) or isinstance(ref, bool):
        raise ValueError(f"a search row's ref must be an integer id, not {ref!r}")
    out = {"rid": ref * 2 + 1 if posting else ref * 2, "key": f"{'p' if posting else 'e'}:{ref}"}
    for f in ROW_FIELDS:
        out[f] = row[f]
    out["year"] = _year(row["sort_date"] if posting else row["period"])
    out["ind"] = ",".join(row["ind"])
    out["name_fold"] = fold(row["employer"])
    return out


def search_rows(conn: sqlite3.Connection) -> Iterator[dict]:
    """Every row of the search database: the searched postings, then every list row, each in id order."""
    ind = export_static.triggered_map(conn)
    for p in conn.execute(
            export_static.POSTING_SQL + f" WHERE {export_static.SEARCHED_POSTINGS} ORDER BY posting_id"):
        yield table_row(export_static.posting_row(p, ind))
    for r in conn.execute(export_static.ESDC_SQL + " ORDER BY id"):
        yield table_row(export_static.esdc_row(r, ind))


def row_hash(row: dict) -> str:
    """SHA-1 over the row's values in HASHED order.

    JSON keeps None, "" and 0 apart and writes each number one way, so the
    hash changes exactly when a value does.
    """
    payload = json.dumps([row[c] for c in HASHED], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# -- the plan ----------------------------------------------------------------


@dataclass
class SyncPlan:
    upserts: list[tuple]   # values in COLUMNS order, the hash last
    deletes: list[str]     # keys
    total: int             # rows the search database holds once the plan is applied
    full: bool = False
    reason: str = ""       # why a full reload, when it is one


def _days_between(earlier: str, later: str) -> int | None:
    try:
        return (date.fromisoformat(later[:10]) - date.fromisoformat(earlier[:10])).days
    except ValueError:
        return None


def full_reason(conn: sqlite3.Connection, *, requested: bool = False, ledger_empty: bool = False,
                today: str | None = None) -> str:
    """Why tonight's sync is a full reload, or "" when it is not."""
    if requested:
        return "requested"
    due = get_meta(conn, META_RELOAD)
    if ledger_empty:
        why = "first load (the ledger is empty)"
    elif due:
        why = f"the row count read back from D1 disagreed on {due}"
    else:
        return ""
    last = get_meta(conn, META_FULL_AT)
    days = _days_between(last, today or today_iso()) if last else None
    return why if days is None or days >= RELOAD_MIN_DAYS else ""


def plan_sync(conn: sqlite3.Connection, *, full: bool = False, today: str | None = None) -> SyncPlan:
    """Compare tonight's rows with the ledger: what to upsert, what to delete."""
    ledger = {key: h for key, h in conn.execute("SELECT key, hash FROM search_sync")}
    reason = full_reason(conn, requested=full, ledger_empty=not ledger, today=today)
    upserts: list[tuple] = []
    total = 0
    for row in search_rows(conn):
        total += 1
        h = row_hash(row)
        # Popped, so what is left afterwards is the keys tonight's rows lack.
        old = ledger.pop(row["key"], None)
        if reason or old != h:
            upserts.append(tuple(row[c] for c in HASHED) + (h,))
    # A full reload starts from empty tables, so it deletes nothing by key.
    deletes = [] if reason else sorted(ledger)
    return SyncPlan(upserts=upserts, deletes=deletes, total=total, full=bool(reason), reason=reason)


# -- the batch files ---------------------------------------------------------


def sql_literal(value: object) -> str:
    """value as an SQL literal for a statement in a batch file.

    A batch is a text file D1 runs as it stands, so nothing can be bound as a
    parameter; each value is written in the one form SQLite reads back as
    exactly that value. Text is quoted with every single quote doubled, the
    only escape inside an SQL string (a backslash, a semicolon, a newline or
    `--` there is an ordinary character), so no content can end the string
    early. A NUL byte cannot be carried in SQL text (the parser stops at it),
    so text holding one is refused rather than quietly changed.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        if not _INT64[0] <= value <= _INT64[1]:
            raise ValueError(f"{value} is outside SQLite's 64-bit integer range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{value!r} has no SQL literal")
        return repr(value)
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError(f"text holds a NUL byte, which SQL text cannot carry: {value[:60]!r}")
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"no SQL literal for a {type(value).__name__}")


def row_tuple(values: Sequence) -> str:
    """One row's values (COLUMNS order) as a parenthesised list of literals."""
    if len(values) != len(COLUMNS):
        raise ValueError(f"a search row has {len(COLUMNS)} values, not {len(values)}")
    parts = []
    for column, value in zip(COLUMNS, values):
        try:
            parts.append(sql_literal(value))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"search row {values[1]!r}, column {column}: {exc}") from None
    return "(" + ", ".join(parts) + ")"


def upsert_statement(rows: Sequence[Sequence]) -> str:
    """Rows (values in COLUMNS order) as one INSERT ... ON CONFLICT DO UPDATE statement."""
    if not rows:
        raise ValueError("an upsert needs at least one row")
    return _UPSERT_HEAD + ", ".join(row_tuple(v) for v in rows) + _UPSERT_TAIL


def delete_statement(keys: Sequence[str]) -> str:
    """Keys as one DELETE ... WHERE key IN (...) statement."""
    if not keys:
        raise ValueError("a delete needs at least one key")
    return _DELETE_HEAD + ", ".join(sql_literal(k) for k in keys) + _DELETE_TAIL


def _grouped(items: Sequence, render, head: str, tail: str, max_items: int, max_bytes: int,
             what: str) -> Iterator[str]:
    """head + rendered items joined by ", " + tail, as few statements as the caps allow.

    Each statement holds at most max_items items and at most max_bytes bytes
    of UTF-8; an item too long for a statement of its own is refused, named.
    """
    fixed = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
    sep = 2  # ", "
    chunk: list[str] = []
    size = fixed
    for item in items:
        text = render(item)
        try:
            n = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError(f"{what(item)}: the text is not valid Unicode ({exc.reason})") from None
        if fixed + n > max_bytes:
            raise ValueError(f"{what(item)}: {fixed + n} bytes as a statement of its own, over the "
                             f"{max_bytes}-byte statement limit")
        if chunk and (len(chunk) >= max_items or size + sep + n > max_bytes):
            yield head + ", ".join(chunk) + tail
            chunk, size = [], fixed
        size += (sep if chunk else 0) + n
        chunk.append(text)
    if chunk:
        yield head + ", ".join(chunk) + tail


def upsert_statements(rows: Sequence[Sequence], *, max_rows: int = MAX_ROWS_PER_UPSERT,
                      max_bytes: int = MAX_STATEMENT_BYTES) -> Iterator[str]:
    """The rows as multi-row upserts, each within max_rows and max_bytes."""
    return _grouped(rows, row_tuple, _UPSERT_HEAD, _UPSERT_TAIL, max_rows, max_bytes,
                    lambda v: f"search row {v[1]!r}")


def delete_statements(keys: Sequence[str], *, max_keys: int = MAX_KEYS_PER_DELETE,
                      max_bytes: int = MAX_STATEMENT_BYTES) -> Iterator[str]:
    """The keys as DELETE ... WHERE key IN (...) statements, each within max_keys and max_bytes."""
    return _grouped(keys, sql_literal, _DELETE_HEAD, _DELETE_TAIL, max_keys, max_bytes,
                    lambda k: f"delete {k!r}")


def reset_sql(schema_path: Path | None = None) -> str:
    return _RESET_HEAD + (schema_path or config.SEARCH_SCHEMA_PATH).read_text(encoding="utf-8")


class _BatchWriter:
    """Fills batch-0001.sql, batch-0002.sql and so on, each within both caps."""

    def __init__(self, out_dir: Path, max_bytes: int, max_statements: int) -> None:
        self.out_dir = out_dir
        self.max_bytes = max_bytes
        self.max_statements = max_statements
        self.files: list[str] = []
        self.bytes = 0
        self._parts: list[bytes] = []
        self._size = 0

    def add(self, statement: str, label: str) -> None:
        try:
            data = statement.encode("utf-8") + b"\n"
        except UnicodeEncodeError as exc:
            raise ValueError(f"{label}: the text is not valid Unicode ({exc.reason})") from None
        if len(data) > self.max_bytes:
            raise ValueError(f"{label}: one statement of {len(data)} bytes is over the {self.max_bytes}-byte batch limit")
        if self._parts and (self._size + len(data) > self.max_bytes or len(self._parts) >= self.max_statements):
            self.flush()
        self._parts.append(data)
        self._size += len(data)

    def flush(self) -> None:
        if not self._parts:
            return
        name = f"batch-{len(self.files) + 1:04d}.sql"
        # Bytes, not text mode: Windows would write a newline inside a name as
        # CRLF and change the value.
        (self.out_dir / name).write_bytes(b"".join(self._parts))
        self.files.append(name)
        self.bytes += self._size
        self._parts = []
        self._size = 0


def write_batches(plan: SyncPlan, out_dir: Path, *, max_bytes: int = MAX_BATCH_BYTES,
                  max_statements: int = MAX_BATCH_STATEMENTS, max_rows_per_upsert: int = MAX_ROWS_PER_UPSERT,
                  max_keys_per_delete: int = MAX_KEYS_PER_DELETE, max_statement_bytes: int = MAX_STATEMENT_BYTES,
                  schema_path: Path | None = None) -> dict:
    """Write the plan as batch files and manifest.json under out_dir; return the manifest.

    The reset of a full reload is a batch of its own and comes first; then the
    deletes, then the upserts. The manifest is written last and in one step,
    so a manifest on disk always names batches that were written in full.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.sql"):
        old.unlink()
    (out_dir / MANIFEST).unlink(missing_ok=True)
    writer = _BatchWriter(out_dir, max_bytes, max_statements)
    if plan.full:
        writer.add(reset_sql(schema_path), "the reset batch")
        writer.flush()
    for statement in delete_statements(plan.deletes, max_keys=max_keys_per_delete, max_bytes=max_statement_bytes):
        writer.add(statement, "a delete statement")
    for statement in upsert_statements(plan.upserts, max_rows=max_rows_per_upsert, max_bytes=max_statement_bytes):
        writer.add(statement, "an upsert statement")
    writer.flush()
    manifest = {
        "generated_at": now_iso(),
        "full": plan.full,
        "reason": plan.reason,
        "batches": writer.files,
        "bytes": writer.bytes,
        "upserts": len(plan.upserts),
        "deletes": len(plan.deletes),
        "expected_total": plan.total,
        # What record_sync writes to the ledger once D1 holds all of this.
        "record": {
            "upserts": [[v[1], v[0], v[-1]] for v in plan.upserts],
            "deletes": list(plan.deletes),
        },
    }
    partial = out_dir / (MANIFEST + ".partial")
    partial.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    partial.replace(out_dir / MANIFEST)
    return manifest


def sync(conn: sqlite3.Connection, out_dir: Path | None = None, *, full: bool = False) -> dict:
    """Plan tonight's sync and write it (the search-sync command); return the manifest.

    The date of a full reload is noted in meta, which spaces out the reloads a
    disagreeing count asks for. The ledger is not touched.
    """
    plan = plan_sync(conn, full=full)
    manifest = write_batches(plan, out_dir or (config.OUT_DIR / "search"))
    if plan.full:
        set_meta(conn, META_FULL_AT, today_iso())
        conn.commit()
    return manifest


# -- after the apply ---------------------------------------------------------


def read_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("batches"), list):
        raise ValueError(f"{path} is not a search sync manifest")
    return manifest


def record_sync(conn: sqlite3.Connection, manifest: dict) -> dict[str, int]:
    """Write the manifest's ledger entries, once D1 holds every batch.

    A full reload replaces the whole ledger. The ledger must then hold exactly
    the manifest's expected total, which is how a manifest planned against a
    different ledger (an old file, a second database) is caught: nothing is
    recorded, and the next night sends its changes again.
    """
    record = manifest.get("record")
    if not isinstance(record, dict) or not isinstance(record.get("upserts"), list) \
            or not isinstance(record.get("deletes"), list):
        raise ValueError("the manifest carries no ledger entries")
    upserts = [(str(key), int(rid), str(h)) for key, rid, h in record["upserts"]]
    deletes = [(str(key),) for key in record["deletes"]]
    expected = int(manifest["expected_total"])
    try:
        if manifest.get("full"):
            conn.execute("DELETE FROM search_sync")
        conn.executemany(
            "INSERT INTO search_sync (key, rid, hash) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET rid = excluded.rid, hash = excluded.hash", upserts)
        conn.executemany("DELETE FROM search_sync WHERE key = ?", deletes)
        held = conn.execute("SELECT COUNT(*) FROM search_sync").fetchone()[0]
        if held != expected:
            raise ValueError(f"the ledger would hold {held} rows where the manifest expects {expected}; "
                             f"the manifest was not planned against this database's ledger")
        # The count matched, so a reload asked for earlier is no longer needed.
        conn.execute("DELETE FROM meta WHERE key = ?", (META_RELOAD,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"recorded": len(upserts), "removed": len(deletes), "ledger": held}


def count_check(expected: int, actual: int) -> str | None:
    """None when D1 holds the expected number of rows, otherwise what disagrees."""
    if expected == actual:
        return None
    return f"the search database holds {actual} rows where the manifest expects {expected}"


def request_reload(conn: sqlite3.Connection, when: str | None = None) -> None:
    """Note that the count disagreed, so a coming sync reloads in full (see full_reason)."""
    set_meta(conn, META_RELOAD, when or today_iso())
    conn.commit()
