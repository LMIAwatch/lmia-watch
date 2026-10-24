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
    # Only the long scope's files read it, and they are gone.
    assert "search_years" not in stats

    first = load(out, "search/first.json")
    assert {r["employer"] for r in first} == {"Alpha Farms Ltd", "Beta Inn", "Delta Nowhere"}
    alpha = next(r for r in first if r["employer"] == "Alpha Farms Ltd")
    assert alpha["ind"] == ["high_volume"] and alpha["status"] == "approved" and alpha["sort_date"] == "2026-03-31"
    assert alpha["source"].startswith("https://open.canada.ca/data/en/dataset/90fed587")
    assert [r["ref"] for r in load(out, "search/latest/status/pending.json")] == [5]

    facets = load(out, "search/facets.json")
    assert facets["default"]["total"] == 3
    assert facets["default"]["status"] == {"pending": 1, "approved": 1, "refused": 1}
    assert facets["default"]["status_prov"]["approved|BC"] == 1
    # A row without a province is counted in the unknown bucket instead of vanishing.
    assert facets["default"]["status_prov"]["refused|UN"] == 1
    # The 2019 row is older than the map's longer period, so Ontario counts nothing.
    assert facets["long"]["prov_year"] == {"BC|2026": 1, "NS|postings": 1, "UN|2026": 1}
    assert facets["long"]["total"] == 3 and counts["search_long"] == 3
    assert facets["first_rows"] == 500

    # The search page queries the search database: the export keeps the fallback
    # rows, the counts, the API's totals and the pending list, and nothing else
    # under search/.
    written = sorted(p.relative_to(out / "search").as_posix() for p in (out / "search").rglob("*") if p.is_file())
    assert written == ["counts.json", "facets.json", "first.json", "latest/status/pending.json"]
    assert sorted(facets["files"]) == ["search/first.json", "search/latest/status/pending.json"]
    assert facets["files"]["search/first.json"]["rows"] == 3
    assert facets["files"]["search/latest/status/pending.json"]["bytes"] > 100
    # The map still gets its longer period from the long rows.
    long_clusters = {x["fsa"]: x for x in load(out, "clusters/since_2023q4.json")}
    assert long_clusters["V4V"]["approved"] == 1 and long_clusters["B2Y"]["pending"] == 1 and "M5V" not in long_clusters

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


def test_recent_pending_ranks_by_the_day_the_flag_was_seen(conn, tmp_path):
    a, b, c, d = seed(conn)
    # A newer posting whose flag was seen earlier than Beta Inn's ranks below it.
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, date_posted, first_seen, last_seen, "
                 "flag_current, flag_first, url, updated_at) VALUES (9, ?, 'Alpha Farms Ltd', 'picker', '2026-10-20', "
                 "'2026-10-01T02:00:00Z', ?, 'requested', 'requested', 'u', ?)", (a, NOW, NOW))
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    rows = load(out, "stats.json")["recent_pending"]
    assert [(r["employer"], r["flagged"], r["date"]) for r in rows] == [
        ("Beta Inn", NOW[:10], "2026-10-06"), ("Alpha Farms Ltd", "2026-10-01", "2026-10-20")]
    # The search files carry no such field, so their rows and hashes are unchanged.
    assert all("flagged" not in r for r in load(out, "search/first.json"))


def test_stats_count_the_public_records_matched_to_employers(conn, tmp_path):
    a, b, c, d = seed(conn)
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    assert {k: load(out, "stats.json")["counts"][k] for k in export_static.PUBLIC_RECORD_COUNTS} == {
        "grant_employers": 0, "grant_agreements": 0, "alberta_employers": 0, "carrier_employers": 0}
    # Two employers share agreement K-1, so it counts once; Alpha holds two
    # agreements and is one employer.
    conn.executemany("INSERT INTO grant_matches VALUES (?, ?, 'exact', 'name_postal_area', ?)",
                     [(a, "org,K-1", NOW), (a, "org,K-2", NOW), (c, "org,K-1", NOW)])
    conn.executemany("INSERT INTO alberta_matches VALUES (?, ?, ?, 'exact', 'name_city', ?)",
                     [(a, "E1", "ALPHA FARMS LTD", NOW), (a, "E2", "ALPHA FARMS", NOW)])
    conn.executemany("INSERT INTO fmcsa_matches VALUES (?, ?, 'exact', 'name_postal_code', ?)",
                     [(b, 101, NOW), (d, 102, NOW)])
    export_static.export_static(conn, out)
    counts = load(out, "stats.json")["counts"]
    assert (counts["grant_employers"], counts["grant_agreements"], counts["alberta_employers"],
            counts["carrier_employers"]) == (2, 2, 1, 2)
    # A database from before these tables existed counts 0 rather than failing.
    for table in ("grant_matches", "alberta_matches", "fmcsa_matches"):
        conn.execute(f"DROP TABLE {table}")
    assert set(export_static.public_record_counts(conn).values()) == {0}


def test_stats_count_pending_postings_by_occupation(conn, tmp_path, monkeypatch):
    a, b, c, d = seed(conn)
    conn.execute("INSERT INTO noc_titles (noc_code, level, title_en, title_fr) VALUES ('63200', 5, 'Cooks', 'Cuisiniers/cuisinières')")
    # Posting 5 (seeded) is pending with no code. 73300 has no classification
    # title but the posting names its occupation; 85101 has neither, so the
    # ESDC list's title stands in. An approved posting and a four-digit code
    # are left out of both the rows and the total.
    for pid, noc, noc_title, flag in ((6, "63200", None, "requested"), (7, "63200", None, "requested"),
                                      (8, "73300", "Transport truck drivers", "requested"), (9, "85101", None, "requested"),
                                      (10, "63200", None, "approved"), (11, "6322", None, "requested")):
        conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, noc_code, noc_title, first_seen, "
                     "last_seen, flag_current, flag_first, url, updated_at) VALUES (?, ?, 'Beta Inn', 'job', ?, ?, ?, ?, ?, "
                     "'requested', 'u', ?)", (pid, b, noc, noc_title, NOW, NOW, flag, NOW))
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    stats = load(out, "stats.json")
    # Most postings first, then by code.
    assert stats["pending_by_noc"] == [
        {"k": "63200", "n": 2, "title": {"en": "Cooks", "fr": "Cuisiniers/cuisinières"}},
        {"k": "73300", "n": 1, "title": {"en": "Transport truck drivers", "fr": "Transport truck drivers"}},
        {"k": "85101", "n": 1, "title": {"en": "Harvesting labourers", "fr": "Harvesting labourers"}},
    ]
    assert stats["counts"]["pending_with_noc"] == 4
    # The total counts every pending posting with a code, past the rows shown.
    monkeypatch.setattr(export_static, "PENDING_BY_NOC", 1)
    rows, total = export_static.pending_by_noc(conn)
    assert [r["k"] for r in rows] == ["63200"] and total == 4
    # No pending posting with a code: an empty list and 0.
    conn.execute("UPDATE jobbank_postings SET noc_code = NULL")
    assert export_static.pending_by_noc(conn) == ([], 0)


def alias(conn, old, new):
    conn.execute("INSERT INTO employer_aliases (old_id, new_id, normalize_version, created_at) VALUES (?, ?, 2, ?)",
                 (old, new, NOW))


def test_retired_ids_are_sharded_like_profiles_and_followed_to_the_live_id(conn, tmp_path):
    a, b, c, d = seed(conn)
    alias(conn, "emp-aaa0000001", a)                  # direct
    alias(conn, "emp-bbb0000002", "emp-ccc0000003")   # retired twice: follows to b
    alias(conn, "emp-ccc0000003", b)
    alias(conn, "emp-ab10000004", a)                  # a second alias of the same employer
    alias(conn, "emp-ddd0000005", "emp-eee0000006")   # ends at an id with no employer: dropped
    alias(conn, "emp-fff0000007", "emp-fff0000008")   # a loop: dropped
    alias(conn, "emp-fff0000008", "emp-fff0000007")
    alias(conn, c, d)                                 # an old id that is live again answers for itself
    conn.commit()
    assert export_static.resolve_aliases(conn) == {
        "emp-aaa0000001": a, "emp-bbb0000002": b, "emp-ccc0000003": b, "emp-ab10000004": a}

    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    files = sorted(p.name for p in (out / "aliases").iterdir())
    assert files == ["aaa.json", "ab1.json", "bbb.json", "ccc.json"] and counts["alias_shards"] == 4
    assert load(out, "aliases/aaa.json") == {"emp-aaa0000001": a}
    assert load(out, "aliases/bbb.json") == {"emp-bbb0000002": b}
    assert load(out, "aliases/ccc.json") == {"emp-ccc0000003": b}
    # The shard is the old id's characters 5 to 7, the slice the site reads for a profile.
    for name in files:
        for old in load(out, f"aliases/{name}"):
            assert export_static.shard_key(old) == old[4:7] == name[:-5]
    # The live id keeps its profile and is redirected nowhere.
    assert c in load(out, f"profiles/{export_static.shard_key(c)}.json")
    assert all(c not in load(out, f"aliases/{name}") for name in files)
    # Old ids never reach the sitemap.
    sitemap = (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    for old in ("emp-aaa0000001", "emp-bbb0000002", "emp-ccc0000003", "emp-ddd0000005", "emp-fff0000007"):
        assert old not in sitemap
    assert f"/employers/{a}" in sitemap


def test_shards_group_every_old_id_with_its_key(conn, tmp_path):
    a, b, _, _ = seed(conn)
    for i in range(3):
        alias(conn, f"emp-777{i:07d}", a if i % 2 else b)
    conn.commit()
    assert export_static.write_aliases(conn, tmp_path) == {"alias_shards": 1}
    assert load(tmp_path, "aliases/777.json") == {"emp-7770000000": b, "emp-7770000001": a, "emp-7770000002": b}
    # Nothing retired: no folder and no shards.
    conn.execute("DELETE FROM employer_aliases")
    assert export_static.write_aliases(conn, tmp_path / "empty") == {"alias_shards": 0}
    assert not (tmp_path / "empty" / "aliases").exists()


def test_a_failing_alias_section_is_logged_and_the_export_goes_on(conn, tmp_path, monkeypatch):
    a, _, _, _ = seed(conn)
    alias(conn, "emp-aaa0000001", a)
    conn.commit()

    def boom(conn, out):
        raise RuntimeError("alias chain broke")

    monkeypatch.setattr(export_static, "write_aliases", boom)
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    assert (out / "stats.json").exists() and (out / "profiles").is_dir() and (out / "trends").is_dir()
    assert not (out / "aliases").exists() and "alias_shards" not in counts
    rows = [(r[0], r[1], r[2]) for r in conn.execute("SELECT source, ok, detail FROM sources_log ORDER BY id") if r[0].startswith("export")]
    assert [(s, ok) for s, ok, _ in rows] == [("export_aliases", 0), ("export", 1)]
    assert rows[0][2] == "RuntimeError: alias chain broke"
    # The sitemap is unchanged by it: retired ids were never listed.
    assert f"/employers/{a}" in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")


def test_search_counts_cover_exactly_the_search_rows(conn, tmp_path):
    a, b, c, d = seed(conn)
    # A second Alpha posting with no province and a lapsed one, which the
    # search database leaves out, so the counts must too.
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, date_posted, first_seen, last_seen, "
                 "flag_current, flag_first, url, updated_at) VALUES (6, ?, 'Alpha Farms Ltd', 'picker', '2025-12-30', ?, ?, "
                 "'approved', 'requested', 'u', ?)", (a, NOW, NOW, NOW))
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, date_posted, first_seen, last_seen, "
                 "flag_current, flag_first, url, updated_at) VALUES (7, ?, 'Beta Inn', 'cook', '2026-09-01', ?, ?, "
                 "'gone', 'requested', 'u', ?)", (b, NOW, NOW, NOW))
    conn.commit()
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    doc = load(out, "search/counts.json")
    assert doc["dims"] == ["status", "prov", "stream", "year", "ind"]
    assert doc["data_as_of"] == load(out, "stats.json")["data_as_of"]
    # The period whose list rows date=last_quarter keeps, as stats.json names it.
    assert doc["latest_period"] == load(out, "stats.json")["esdc_latest_period"] == "2026Q1"

    from lmia_pipeline.search_db import search_rows
    rows = list(search_rows(conn))
    assert doc["total"] == len(rows) == 5
    expected: dict[tuple, int] = {}
    for r in rows:
        k = (r["status"], r["prov"], r["stream"], r["year"], r["ind"])
        expected[k] = expected.get(k, 0) + 1
    v = doc["values"]
    got = {tuple(v[dim][i] for dim, i in zip(doc["dims"], cell[:5])): cell[5] for cell in doc["cells"]}
    assert got == expected
    assert sum(cell[5] for cell in doc["cells"]) == doc["total"]
    # Values are the database's own: null for no province or stream, keys comma separated.
    assert v["status"] == ["approved", "pending", "refused"]
    assert v["prov"] == ["BC", "NS", "ON", None]
    assert v["stream"] == ["High Wage", "Low Wage", "Primary Agriculture", None]
    assert v["year"] == [2019, 2025, 2026]
    assert v["ind"] == ["", "high_volume"]
    assert ("approved", None, None, 2025, "high_volume") in got
    # The search API bounds a year filter by the sort date as well, which is
    # exact only while a row's year is its sort date's year.
    assert all(str(r["year"]) == r["sort_date"][:4] for r in rows)
    # Deterministic, like every other file of the export.
    before = (out / "search" / "counts.json").read_bytes()
    export_static.export_static(conn, out)
    assert (out / "search" / "counts.json").read_bytes() == before


def test_a_failing_counts_section_leaves_the_search_files(conn, tmp_path, monkeypatch):
    seed(conn)

    def boom(conn, out, data_as_of, latest_period=None):
        raise ValueError("cannot count")

    monkeypatch.setattr(export_static, "write_search_counts", boom)
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    assert (out / "search" / "facets.json").exists() and not (out / "search" / "counts.json").exists()
    rows = [(r[0], r[1]) for r in conn.execute("SELECT source, ok FROM sources_log ORDER BY id") if r[0].startswith("export")]
    assert rows == [("export_search_counts", 0), ("export", 1)]


def test_the_pending_file_is_written_on_a_night_with_no_pending_posting(conn, tmp_path):
    # /api/pending answers 503 for a missing file; an empty night is an empty list.
    seed(conn)
    conn.execute("UPDATE jobbank_postings SET flag_current = 'approved'")
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    assert load(out, "search/latest/status/pending.json") == []
    assert load(out, "search/facets.json")["files"]["search/latest/status/pending.json"]["rows"] == 0


def test_search_counts_carry_no_latest_period_before_any_list_is_loaded(conn, tmp_path):
    # An empty meta value is no period: date=last_quarter then keeps postings only.
    export_static.write_search_counts(conn, tmp_path, "2026-10-22", "")
    assert load(tmp_path, "search/counts.json")["latest_period"] is None
