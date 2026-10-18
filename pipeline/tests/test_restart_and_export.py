"""A database from an earlier schema opens without a migration step, and a failed
export never leaves a half-written tree for the deploy."""

import json
import sqlite3

import pytest

from lmia_pipeline import export, export_static
from lmia_pipeline.db import add_missing_columns, connect, upsert_employer
from lmia_pipeline import config

NOW = "2026-10-17T00:00:00Z"
NEWER_TABLES = ["wage_tables", "jobbank_wages", "lfs_unemployment", "fsa_regions", "donations"]


def previous_version(path):
    """A database as the schema before the wage and unemployment indicators left it,
    plus a column dropped, as a column added later would be missing."""
    conn = connect(path)
    eid = upsert_employer(conn, "Acme Farms Ltd", "BC", source="jobbank", city="Abbotsford", now=NOW)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, flag_first, "
        "url, updated_at, valid_through) VALUES (1, ?, 'Acme Farms Ltd', ?, ?, 'requested', 'requested', 'u', ?, '2026-11-01')",
        (eid, NOW, NOW, NOW),
    )
    conn.execute("DROP INDEX idx_employers_postal")
    conn.execute("ALTER TABLE employers DROP COLUMN postal_code")
    conn.execute("ALTER TABLE jobbank_postings DROP COLUMN valid_through")
    for table in NEWER_TABLES:
        conn.execute(f"DROP TABLE {table}")
    conn.commit()
    conn.close()
    return eid


def test_a_database_from_the_previous_schema_is_brought_up_to_date_without_data_loss(tmp_path):
    db = tmp_path / "old.sqlite"
    eid = previous_version(db)
    conn = connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(NEWER_TABLES) <= tables
    columns = {r[1] for r in conn.execute("PRAGMA table_info(employers)")}
    assert "postal_code" in columns
    assert "valid_through" in {r[1] for r in conn.execute("PRAGMA table_info(jobbank_postings)")}
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'idx_employers_postal'").fetchone() is not None
    row = conn.execute("SELECT display_name, city FROM employers WHERE id = ?", (eid,)).fetchone()
    assert (row["display_name"], row["city"]) == ("Acme Farms Ltd", "Abbotsford")
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings").fetchone()[0] == 1
    # Opening again changes nothing.
    assert add_missing_columns(conn, config.SCHEMA_PATH.read_text(encoding="utf-8")) == []
    conn.close()


def test_a_not_null_column_with_a_default_is_added_with_it(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.sqlite")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    conn.execute("INSERT INTO t (a) VALUES ('kept')")
    added = add_missing_columns(conn, "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, a TEXT, "
                                      "n INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL);")
    assert added == ["t.n", "t.note"]
    assert conn.execute("SELECT a, n, note FROM t").fetchone() == ("kept", 0, None)


def test_a_failed_export_keeps_the_previous_tree(conn, tmp_path, monkeypatch):
    out = tmp_path / "static"
    out.mkdir()
    (out / "stats.json").write_text('{"previous": true}', encoding="utf-8")

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(export_static, "write_profiles", broken)
    with pytest.raises(RuntimeError):
        export_static.export_static(conn, out)
    assert json.loads((out / "stats.json").read_text(encoding="utf-8")) == {"previous": True}
    monkeypatch.undo()
    export_static.export_static(conn, out)
    assert "counts" in json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert not (tmp_path / "static.partial").exists()


def test_a_value_json_cannot_carry_stops_the_export_instead_of_publishing_it(conn, tmp_path):
    eid = upsert_employer(conn, "Acme Farms Ltd", "BC", source="jobbank", now=NOW)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, flag_first, "
        "url, updated_at, wage_min) VALUES (1, ?, 'Acme', ?, ?, 'requested', 'requested', 'u', ?, ?)",
        (eid, NOW, NOW, NOW, float("inf")),
    )
    with pytest.raises(ValueError):
        export_static.export_static(conn, tmp_path / "static")
    assert not (tmp_path / "static").exists()


def test_csv_files_are_replaced_whole(conn, tmp_path, monkeypatch):
    out = tmp_path / "csv"
    export.export_csv(conn, out)
    names = sorted(p.name for p in out.iterdir())
    assert names and all(n.endswith(".csv") for n in names)
