import hashlib
import json

from lmia_pipeline import config, export, export_static, releases, status
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-18T00:00:00Z"
PUBLISHED = {"2016": "2017-04-01", "2023Q4": "2024-04-10", "2024Q1": "2024-07-15", "2024Q2": "2024-10-20"}


def add_resource(conn, rid, dataset, period):
    url = f"https://open.canada.ca/data/dataset/x/resource/{rid}/download/tfwp_{period.lower()}_{dataset[:3]}_en.xlsx"
    conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                 "loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1000, 1, ?)",
                 (rid, dataset, period, f"{period} {dataset} list", url, PUBLISHED[period], "ab" * 32, NOW))


def add_row(conn, lst, period, name, prov, stream, noc, title, positions, city=None, n=[0]):
    n[0] += 1
    eid = upsert_employer(conn, name, prov, source=f"esdc_{lst}", city=city, now=NOW)
    rid = f"{lst[:3]}-{period}"
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, city, noc_code, noc_title, "
                 "lmias, positions, resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                 (lst, period, eid, name, prov, stream, city, noc, title, positions, rid, f"h{n[0]}"))
    return eid


def seed(conn):
    for period in PUBLISHED:
        add_resource(conn, f"pos-{period}", "positive", period)
        if period != "2016":
            add_resource(conn, f"neg-{period}", "negative", period)
    ids = {}
    ids["delta"] = add_row(conn, "positive", "2016", "Delta Old Co", "AB", None, "6322", "Cooks", 7, "Calgary")
    ids["beta"] = add_row(conn, "positive", "2023Q4", "Beta Health Authority", "NS", "High Wage", "3012", "Registered nurses", 40, "Halifax")
    ids["eps"] = add_row(conn, "positive", "2023Q4", "Epsilon Ltd", "QC", "Low Wage", "6711", "Food counter attendants", 20, "Laval")
    add_row(conn, "positive", "2024Q1", "Alpha Farms Ltd", "BC", "Primary Agriculture", "8611", "Harvesting labourers", 100, "Kelowna")
    add_row(conn, "positive", "2024Q1", "Beta Health Authority", "NS", "High Wage", "3012", "Registered nurses and psychiatric nurses", 60, "Halifax")
    ids["alpha"] = add_row(conn, "positive", "2024Q2", "Alpha Farms Ltd", "BC", "Primary Agriculture", "85101", "Harvesting labourers", 150, "Kelowna")
    add_row(conn, "positive", "2024Q2", "Beta Health Authority", "NS", "Global Talent", "31301", "Registered nurses", 10, "Halifax")
    ids["gamma"] = add_row(conn, "positive", "2024Q2", "Gamma Cafe Inc", "ON", "Low Wage", "65201", "Food counter attendants", 5, "Toronto")
    add_row(conn, "negative", "2024Q2", "Phi Diner Ltd", "ON", "Low Wage", "65201", "Food counter attendants", 2, "Ottawa")
    add_row(conn, "negative", "2024Q2", "Unplaced Co", None, None, "75110", "Construction helpers", 1)
    add_row(conn, "negative", "2023Q4", "Phi Diner Ltd", "ON", "Low Wage", "6711", "Food counter attendants", 3, "Ottawa")
    conn.commit()
    status.recompute(conn, now=NOW)
    return ids


def load(out, rel):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_slugs_streams_and_eras():
    assert releases.period_slug("2026Q1") == "2026-q1"
    assert releases.period_slug("2017Q1-Q2") == "2017-q1-q2"
    assert releases.period_slug("2015") == "2015"
    assert releases.stream_key("Global Talent") == "Global Talent Stream"
    assert releases.stream_key("Talent mondial") == "Global Talent Stream"
    assert releases.stream_key("99") == "Other" and releases.stream_key(None) is None
    assert releases.noc_era("6322") == "2011" and releases.noc_era("63200") == "2021" and releases.noc_era("63") is None


def test_release_pages(conn, tmp_path):
    ids = seed(conn)
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    assert counts["release_files"] == 5 and counts["ranking_files"] == 4

    index = load(out, "releases/index.json")["releases"]
    assert [r["slug"] for r in index] == ["2024-q2", "2024-q1", "2023-q4", "2016"]
    assert index[0] == {"period": "2024Q2", "slug": "2024-q2", "quarters": 1, "published": "2024-10-20", "positive_rows": 3,
                        "positions": 165, "employers": 3, "negative_rows": 2, "negative_positions": 3}
    assert index[-1]["quarters"] == 4

    rel = load(out, "releases/2024-q2.json")
    assert rel["prev"]["slug"] == "2024-q1" and rel["prev"]["totals"]["positions"] == 160 and rel["next"] is None
    assert rel["totals"]["lmias"] is None and rel["totals"]["negative_employers"] == 2
    assert [(r["id"], r["positions"]) for r in rel["top"]] == [(ids["alpha"], 150), (ids["beta"], 10), (ids["gamma"], 5)]
    assert rel["top"][0]["city"] == "Kelowna" and rel["top"][0]["stream"] == "Primary Agriculture"
    # Gamma is the only employer with no earlier positive row.
    assert rel["new"]["count"] == 1 and rel["new"]["positions"] == 5 and rel["new"]["top"][0]["id"] == ids["gamma"]
    up, down = rel["changes"]["up"], rel["changes"]["down"]
    assert [(r["id"], r["prev"], r["positions"], r["change"]) for r in up] == [(ids["alpha"], 100, 150, 50), (ids["gamma"], 0, 5, 5)]
    assert [(r["id"], r["change"]) for r in down] == [(ids["beta"], -50)]
    assert {r["k"]: r["positions"] for r in rel["approvals"]["prov"]} == {"BC": 150, "NS": 10, "ON": 5}
    assert rel["approvals"]["stream"]["shown"] is True
    assert {r["k"] for r in rel["approvals"]["stream"]["rows"]} == {"Primary Agriculture", "Global Talent Stream", "Low Wage"}
    # Refusals: one row in two has no stream, so no breakdown by stream is published.
    assert [(r["k"], r["rows"], r["positions"]) for r in rel["refusals"]["prov"]] == [("ON", 1, 2), ("UN", 1, 1)]
    assert rel["refusals"]["stream"] == {"shown": False, "missing_share": 0.5, "rows": []}
    pos = rel["sources"][0]
    assert pos["dataset"] == "positive" and pos["published"] == "2024-10-20"
    assert pos["page"] == "https://open.canada.ca/data/en/dataset/90fed587-1364-4f33-a9ee-208181dc0b97/resource/pos-2024Q2"
    assert pos["mirror"] == "positive_2024Q2_tfwp_2024q2_pos_en.xlsx"
    assert rel["sources"][1]["dataset"] == "negative"

    # The previous release lost Epsilon entirely: a decrease to zero.
    q1 = load(out, "releases/2024-q1.json")
    assert [(r["id"], r["positions"], r["change"]) for r in q1["changes"]["down"]] == [(ids["eps"], 0, -20)]
    assert q1["changes"]["down"][0]["name"] == "Epsilon Ltd"

    first = load(out, "releases/2016.json")
    assert first["first"] is True and first["new"] is None and first["changes"] is None and first["prev"] is None
    assert first["approvals"]["stream"]["shown"] is False and first["approvals"]["stream"]["missing_share"] == 1.0
    assert first["next"]["slug"] == "2023-q4" and first["sources"][0]["dataset"] == "positive"

    # Deterministic: a second export writes the same bytes.
    before = (out / "releases" / "2024-q2.json").read_bytes()
    export_static.export_static(conn, out)
    assert (out / "releases" / "2024-q2.json").read_bytes() == before


def test_rankings_keep_the_two_noc_eras_apart(conn, tmp_path):
    ids = seed(conn)
    out = tmp_path / "static"
    export_static.export_static(conn, out)

    year = load(out, "rankings/2024.json")
    assert year["years"] == [2024, 2023, 2016] and year["periods"] == ["2024Q1", "2024Q2"]
    eras = {o["era"]: o for o in year["occupations"]}
    assert eras["2011"]["periods"] == ["2024Q1"] and eras["2021"]["periods"] == ["2024Q2"]
    assert all(len(r["code"]) == 4 for r in eras["2011"]["rows"])
    assert all(len(r["code"]) == 5 for r in eras["2021"]["rows"])
    assert eras["2021"]["rows"][0] == {"code": "85101", "title": "Harvesting labourers", "positions": 150, "rows": 1}
    assert eras["2011"]["positions"] + eras["2021"]["positions"] == year["totals"]["positions"] == 325
    assert [(e["id"], e["positions"]) for e in year["employers"]] == [(ids["alpha"], 250), (ids["beta"], 70), (ids["gamma"], 5)]
    assert year["streams"]["shown"] is True and year["streams"]["years"] == [2024]

    every = load(out, "rankings/all.json")
    assert every["scope"] == "all" and every["periods"] == ["2016", "2023Q4", "2024Q1", "2024Q2"]
    eras = {o["era"]: o for o in every["occupations"]}
    assert eras["2011"]["periods"] == ["2016", "2023Q4", "2024Q1"]
    # A code keeps the title of its newest row.
    assert next(r for r in eras["2011"]["rows"] if r["code"] == "3012")["title"] == "Registered nurses and psychiatric nurses"
    assert [(e["id"], e["positions"]) for e in every["employers"]][:2] == [(ids["alpha"], 250), (ids["beta"], 110)]
    assert every["employers"][0]["name"] == "Alpha Farms Ltd" and every["employers"][0]["prov"] == "BC"
    assert {r["k"]: r["positions"] for r in every["provinces"]} == {"BC": 250, "NS": 110, "QC": 20, "AB": 7, "ON": 5}
    # 2016 has no stream on any row, so the all-time stream table leaves that year out and says so.
    assert every["streams"]["shown"] is True and every["streams"]["years"] == [2023, 2024]
    assert sum(r["positions"] for r in every["streams"]["rows"]) == every["streams"]["positions"] == 385
    old = load(out, "rankings/2016.json")
    assert old["streams"] == {"shown": False, "missing_share": 1.0, "years": [], "positions": 0, "rows": []}


def test_files_without_an_occupation_are_named(conn, tmp_path):
    add_resource(conn, "pos-2016", "positive", "2016")
    add_row(conn, "positive", "2016", "Harbour Farms", "NS", None, None, None, 3)
    conn.commit()
    status.recompute(conn, now=NOW)
    export_static.export_static(conn, tmp_path / "static")
    ranking = load(tmp_path / "static", "rankings/2016.json")
    assert ranking["occupations"] == [] and ranking["no_occupation_periods"] == ["2016"]


def test_sitemap_lists_the_release_pages_dated_by_publication(conn, tmp_path, monkeypatch):
    assert releases.sitemap_entries(conn) == []
    seed(conn)
    entries = releases.sitemap_entries(conn)
    assert entries == [
        ("/releases", "2024-10-20"),
        ("/rankings", "2024-10-20"),
        ("/rankings/2024", "2024-10-20"),
        ("/rankings/2023", "2024-04-10"),
        ("/rankings/2016", "2017-04-01"),
        ("/releases/2024-q2", "2024-10-20"),
        ("/releases/2024-q1", "2024-07-15"),
        ("/releases/2023-q4", "2024-04-10"),
        ("/releases/2016", "2017-04-01"),
    ]
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    export_static.export_static(conn, tmp_path / "static")
    text = (tmp_path / "static" / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    assert "<loc>https://lmiawatch.ca/releases/2024-q2</loc><lastmod>2024-10-20</lastmod>" in text
    # After the fixed pages and before the first profile.
    assert text.index("/support<") < text.index("/releases<") < text.index("/employers/")


def test_mirror_names_match_the_mirror_export(conn, tmp_path):
    seed(conn)
    cache = tmp_path / "cache"
    cache.mkdir()
    for r in conn.execute("SELECT url FROM esdc_resources"):
        (cache / f"{hashlib.sha1(r['url'].encode('utf-8')).hexdigest()}.bin").write_bytes(b"x")
    export.export_mirror(conn, tmp_path / "mirror", cache)
    written = {p.name for p in (tmp_path / "mirror").iterdir()} - {"SHA256SUMS"}
    named = {releases.mirror_name(r["dataset"], r["period"], r["url"]) for r in conn.execute("SELECT * FROM esdc_resources")}
    assert written == named
    assert releases.mirror_name("positive", "2026Q1", "https://x.invalid/a b.xlsx") is None


def test_an_empty_database_writes_no_release_files(conn, tmp_path):
    counts = export_static.export_static(conn, tmp_path / "static")
    assert counts["release_files"] == 0 and counts["ranking_files"] == 0
    assert not (tmp_path / "static" / "releases").exists()
