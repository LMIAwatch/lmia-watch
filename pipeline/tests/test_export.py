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
