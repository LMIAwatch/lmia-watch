import json

from lmia_pipeline import export_static, status
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-12T00:00:00Z"


def seed(conn):
    a = upsert_employer(conn, "Alpha Farms Ltd", "BC", source="esdc_positive", city="Kelowna", postal_code="V4V 1T3", now=NOW)
    b = upsert_employer(conn, "Beta Inn", "NS", source="jobbank", city="Dartmouth", postal_code="B2Y 1A1", now=NOW)
    c = upsert_employer(conn, "Gamma Old Co", "ON", source="esdc_positive", city="Toronto", postal_code="M5V 1A1", now=NOW)
    d = upsert_employer(conn, "Delta Nowhere", None, source="esdc_negative", now=NOW)
    for rid, period, dataset in (("p26", "2026Q1", "positive"), ("p19", "2019Q2", "positive"), ("n26", "2026Q1", "negative")):
        conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                     "loaded_at) VALUES (?, ?, ?, 'n', 'u', '2026-07-21', 's', 1, 1, ?)", (rid, dataset, period, NOW))
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, "
                 "noc_title, lmias, positions, resource_id, row_hash) VALUES ('positive', '2026Q1', ?, 'Alpha Farms Ltd', 'BC', "
                 "'Primary Agriculture', 'Kelowna', 'V4V 1T3', '85101', 'Harvesting labourers', 19, 760, 'p26', 'h1')", (a,))
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, "
                 "noc_title, lmias, positions, resource_id, row_hash) VALUES ('positive', '2019Q2', ?, 'Gamma Old Co', 'ON', "
                 "'High Wage', 'Toronto', 'M5V 1A1', '2171', 'Analysts', 1, 2, 'p19', 'h2')", (c,))
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, noc_code, noc_title, lmias, "
                 "positions, resource_id, row_hash) VALUES ('negative', '2026Q1', ?, 'Delta Nowhere', NULL, 'Low Wage', '63200', "
                 "'Cooks', 1, 1, 'n26', 'h3')", (d,))
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, city, province, postal_code, wage_min, "
                 "wage_max, wage_unit, vacancies, date_posted, first_seen, last_seen, flag_current, flag_first, url, updated_at) "
                 "VALUES (5, ?, 'Beta Inn', 'cook', 'Dartmouth', 'NS', 'B2Y 1A1', 18, 20, 'HOUR', 2, '2026-10-06', ?, ?, "
                 "'requested', 'requested', 'u', ?)", (b, NOW, NOW, NOW))
    conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) VALUES "
                 "(?, 'high_volume', 'triggered', '760 positions', '0.1', ?)", (a, NOW))
    conn.executemany("INSERT INTO fsa_centroids (fsa, province, lat, lon) VALUES (?, ?, ?, ?)",
                     [("V4V", "BC", 50.03, -119.41), ("B2Y", "NS", 44.67, -63.57), ("M5V", "ON", 43.64, -79.39)])
    status.recompute(conn, now=NOW)
    return a, b, c, d


def load(out, rel):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_a_failing_section_is_logged_and_the_export_goes_on(conn, tmp_path, monkeypatch):
    seed(conn)

    def boom(conn, out):
        raise ValueError("Out of range float values are not JSON compliant")

    monkeypatch.setattr(export_static.trends, "write_all", boom)
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    # The site's own files are written; the failed section's are not.
    assert (out / "stats.json").exists() and (out / "releases" / "index.json").exists()
    assert not (out / "trends").exists()
    rows = [(r[0], r[1], r[2]) for r in conn.execute("SELECT source, ok, detail FROM sources_log ORDER BY id") if r[0].startswith("export")]
    assert [(s, ok) for s, ok, _ in rows] == [("export_trends", 0), ("export", 1)]
    assert rows[0][2].startswith("ValueError: Out of range")
    sitemap = (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    assert "/trends" not in sitemap and "/releases/2026-q1" in sitemap


def test_static_export_tree(conn, tmp_path):
    a, b, c, d = seed(conn)
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    stats = load(out, "stats.json")
    assert stats["esdc_latest_period"] == "2026Q1"
    assert stats["counts"]["pending"] == 1 and stats["counts"]["approved_positions"] == 760
    assert stats["counts"]["employers"] == 4
    assert stats["recent_pending"][0]["employer"] == "Beta Inn"
    assert stats["top_approvals"][0]["employer_id"] == a
    assert stats["by_stream"] == [{"k": "Primary Agriculture", "n": 1}]
    assert stats["search_from_period"] == "2023Q4"
    assert stats["search_years"] == [2023, 2024, 2025, 2026]

    latest = load(out, "search/latest/all.json")
    assert {r["employer"] for r in latest} == {"Alpha Farms Ltd", "Beta Inn", "Delta Nowhere"}
    assert load(out, "search/first.json") == latest
    alpha = next(r for r in latest if r["employer"] == "Alpha Farms Ltd")
    assert alpha["ind"] == ["high_volume"] and alpha["status"] == "approved" and alpha["sort_date"] == "2026-03-31"
    assert alpha["source"].startswith("https://open.canada.ca/data/en/dataset/90fed587")
    assert [r["ref"] for r in load(out, "search/latest/status/pending.json")] == [5]
    assert [r["employer"] for r in load(out, "search/latest/prov/BC.json")] == ["Alpha Farms Ltd"]
    assert [r["employer"] for r in load(out, "search/latest/prov/BC/approved.json")] == ["Alpha Farms Ltd"]
    # A row without a province lands in the unknown bucket instead of vanishing.
    assert [r["employer"] for r in load(out, "search/latest/prov/UN/refused.json")] == ["Delta Nowhere"]

    facets = load(out, "search/facets.json")
    assert facets["default"]["total"] == 3
    assert facets["default"]["status"] == {"pending": 1, "approved": 1, "refused": 1}
    assert facets["default"]["status_prov"]["approved|BC"] == 1
    assert facets["long"]["prov_year"] == {"BC|2026": 1, "NS|postings": 1, "UN|2026": 1}
    assert facets["files"]["search/latest/all.json"]["rows"] == 3
    assert facets["files"]["search/long/BC/2026.json"]["bytes"] > 100
    assert facets["first_rows"] == 500

    assert (out / "search" / "long" / "BC" / "2026.json").exists() and (out / "search" / "long" / "NS" / "postings.json").exists()
    # The 2019 row is older than the search scope, so Ontario has no files.
    assert not (out / "search" / "long" / "ON").exists()
    assert counts["search_long"] == 3

    cl = {x["fsa"]: x for x in load(out, "clusters/latest.json")}
    assert cl["V4V"]["approved"] == 1 and cl["B2Y"]["pending"] == 1 and "M5V" not in cl
    area = load(out, "areas/B2Y.json")
    assert area["total"] == 1 and area["rows"][0]["employer"] == "Beta Inn"

    prof = load(out, f"profiles/{export_static.shard_key(c)}.json")[c]
    assert prof["employer"]["display_name"] == "Gamma Old Co"
    assert prof["esdc"][0]["period"] == "2019Q2" and prof["esdc"][0]["published"] == "2026-07-21"
    assert prof["indicators"] == [] and prof["postings"] == []
    assert counts["profile_shards"] >= 1 and counts["areas"] == 2

    # Deterministic: a second export produces identical bytes.
    before = (out / "profiles" / f"{export_static.shard_key(a)}.json").read_bytes()
    export_static.export_static(conn, out)
    assert (out / "profiles" / f"{export_static.shard_key(a)}.json").read_bytes() == before
