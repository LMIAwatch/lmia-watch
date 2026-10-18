import sqlite3

from lmia_pipeline import export, status
from lmia_pipeline.db import apply_schema, upsert_employer

NOW = "2026-10-12T00:00:00Z"


def seed(conn):
    a = upsert_employer(conn, "Alpha Farms Ltd", "BC", source="esdc_positive", city="Kelowna",
                        postal_code="V4V 1T3", now=NOW)
    b = upsert_employer(conn, "Beta Inn", "NS", source="jobbank", now=NOW)
    conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, "
                 "rows_loaded, loaded_at) VALUES ('p', 'positive', '2026Q1', 'n', 'u', '2026-07-21', 's', 1, 1, ?)", (NOW,))
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, stream, noc_code, noc_title, "
                 "lmias, positions, resource_id, row_hash) VALUES ('positive', '2026Q1', ?, 'Alpha Farms Ltd', "
                 "'Primary Agriculture', '85101', 'Harvesting labourers', 19, 760, 'p', 'h1')", (a,))
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, date_posted, first_seen, "
                 "last_seen, flag_current, flag_first, url, updated_at) VALUES (5, ?, 'Beta Inn', ?, "
                 "'2026-10-06', ?, ?, 'requested', 'requested', 'u', ?)", (b, "cook's helper", NOW, NOW, NOW))
    conn.execute("INSERT INTO jobbank_observations (posting_id, observed_at, flag, facet) VALUES (5, ?, 'requested', '101010')", (NOW,))
    conn.execute("INSERT INTO fsa_centroids (fsa, province, lat, lon) VALUES ('V4V', 'BC', 50.03, -119.41)")
    status.recompute(conn, now=NOW)
    return a, b


def load_batches(out_dir) -> sqlite3.Connection:
    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    for name in sorted(p.name for p in out_dir.glob("*.sql")):
        target.executescript((out_dir / name).read_text(encoding="utf-8"))
    return target


def test_d1_round_trip_and_incremental(conn, tmp_path):
    a, b = seed(conn)
    out = tmp_path / "d1"
    manifest = export.export_d1(conn, out)
    assert manifest["files"][0] == "000_schema.sql"
    target = load_batches(out)
    for table in ("employers", "esdc_records", "jobbank_postings", "jobbank_observations", "meta",
                  "fsa_centroids", "employer_names", "esdc_resources", "indicators"):
        src = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        dst = target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert src == dst, table
    row = target.execute("SELECT title FROM jobbank_postings WHERE posting_id = 5").fetchone()
    assert row["title"] == "cook's helper"

    # Until the apply is confirmed nothing moves; after it, only changes export.
    manifest2 = export.export_d1(conn, out)
    assert manifest2["row_counts"]["employers"] == 2
    export.mark_synced(conn, out / "manifest.json")
    manifest3 = export.export_d1(conn, out)
    assert manifest3["row_counts"]["employers"] == 0
    assert manifest3["row_counts"]["esdc_records"] == 0
    assert manifest3["row_counts"]["meta"] == len(conn.execute("SELECT * FROM meta").fetchall())

    conn.execute("UPDATE employers SET city = 'Lake Country', updated_at = '2026-10-13T00:00:00Z' WHERE id = ?", (a,))
    manifest4 = export.export_d1(conn, out)
    assert manifest4["row_counts"]["employers"] == 1
    target2 = load_batches(out)
    assert target2.execute("SELECT city FROM employers WHERE id = ?", (a,)).fetchone()[0] == "Lake Country"


def test_full_export_resets(conn, tmp_path):
    seed(conn)
    out = tmp_path / "d1"
    manifest = export.export_d1(conn, out, full=True)
    assert manifest["full"] is True and "001_reset.sql" in manifest["files"]
    text = (out / "001_reset.sql").read_text(encoding="utf-8")
    assert "DELETE FROM employers;" in text
    assert "employer_responses" not in text and "corrections" not in text


def test_csv_and_mirror(conn, tmp_path):
    seed(conn)
    counts = export.export_csv(conn, tmp_path / "csv")
    assert counts["approved_quarterly.csv"] == 1
    assert counts["pending_observations.csv"] == 1
    assert counts["employers.csv"] == 2
    header = (tmp_path / "csv" / "employers.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("id,display_name,province")
    assert export.export_mirror(conn, tmp_path / "mirror", cache_dir=tmp_path / "nocache") == 0
    assert (tmp_path / "mirror" / "SHA256SUMS").exists()


def test_sql_literal_escaping():
    assert export.sql_literal(None) == "NULL"
    assert export.sql_literal("O'Brien") == "'O''Brien'"
    assert export.sql_literal(3) == "3"
    assert export.sql_literal(2.5) == "2.5"
