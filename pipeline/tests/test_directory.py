"""The employer directory (A to Z by province, 200 to a page) and the related
employers on each profile: page splitting, a stable order, the ledger behind
the sitemap's lastmod, the province with no employers, the directory of head
offices outside Canada, and the related lists worked out by hand."""

import json

from lmia_pipeline import directory, export_static, places, status
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-29T00:00:00Z"


def load(out, rel):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def esdc(conn, eid, raw, prov, city, noc, n=1, period="2026Q1"):
    for i in range(n):
        conn.execute(
            "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, city, noc_code, noc_title, lmias, "
            "positions, resource_id, row_hash) VALUES ('positive', ?, ?, ?, ?, ?, ?, 'Title', 1, 1, 'r1', ?)",
            (period, eid, raw, prov, city, noc, f"{eid}{noc}{period}{i}"))


def posting(conn, pid, eid, raw, prov, city, noc):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, noc_code, city, province, first_seen, "
        "last_seen, flag_current, flag_first, url, updated_at) VALUES (?, ?, ?, 'cook', ?, ?, ?, ?, ?, 'requested', 'requested', "
        "'u', ?)", (pid, eid, raw, noc, city, prov, NOW, NOW, NOW))


def many(conn, n, prov="MB", city="Brandon"):
    """n employers named so that their normalized names sort in a known order."""
    return [upsert_employer(conn, f"Firm {i:04d} Ltd", prov, source="esdc_positive", city=city, now=NOW) for i in range(n)]


def write(conn, out, day="2026-10-29"):
    return directory.write_all(conn, out, day)


# -- the directory -----------------------------------------------------------------


def test_pages_split_at_200_in_name_order(conn, tmp_path):
    ids = many(conn, 401)
    # Inserted out of order and under a later spelling: the order is the normalized name's.
    late = upsert_employer(conn, "AAA Early Name Inc", "MB", source="jobbank", city="Winnipeg", now=NOW)
    conn.execute("UPDATE employers SET display_name = 'Zed Trading (formerly AAA Early Name)' WHERE id = ?", (late,))
    counts = write(conn, tmp_path)
    assert counts == {"directory_pages": 3, "directory_employers": 402}

    pages = [load(tmp_path, f"directory/mb/{n}.json") for n in (1, 2, 3)]
    assert [len(p["rows"]) for p in pages] == [200, 200, 2]
    assert not (tmp_path / "directory" / "mb" / "4.json").exists()
    assert [p["page"] for p in pages] == [1, 2, 3] and {p["code"] for p in pages} == {"mb"}
    flat = [r for p in pages for r in p["rows"]]
    assert flat[0] == {"id": late, "name": "Zed Trading (formerly AAA Early Name)", "city": "Winnipeg", "records": 0}
    assert [r["id"] for r in flat[1:]] == ids
    # Only the page's rows: the totals live in the index, so a new employer does
    # not rewrite pages it does not reach.
    assert set(pages[0]) == {"code", "page", "rows"}

    index = load(tmp_path, "directory/mb/index.json")
    assert index["employers"] == 402 and index["pages"] == 3 and index["page_size"] == 200
    assert index["ranges"][0] == ["Zed Trading (formerly AAA Early Name)", "Firm 0198 Ltd"]
    assert index["ranges"][2] == ["Firm 0399 Ltd", "Firm 0400 Ltd"]
    assert index["letters"] == [["A", 1], ["F", 1]]
    assert index["updated"] == "2026-10-29"


def test_order_is_stable_and_only_changed_pages_get_a_new_date(conn, tmp_path):
    many(conn, 401)
    write(conn, tmp_path / "a", "2026-10-28")
    before = {n: (tmp_path / "a" / "directory" / "mb" / f"{n}.json").read_bytes() for n in (1, 2, 3)}

    # A night with nothing new writes the same bytes and keeps every date.
    write(conn, tmp_path / "b", "2026-10-29")
    assert {n: (tmp_path / "b" / "directory" / "mb" / f"{n}.json").read_bytes() for n in (1, 2, 3)} == before
    assert dict(directory.sitemap_entries(conn)) == {
        "/places/mb/employers": "2026-10-28", "/places/mb/employers/2": "2026-10-28", "/places/mb/employers/3": "2026-10-28"}

    # One more record for an employer on page 3 and a new employer that sorts
    # last: pages 1 and 2 keep their rows and their date.
    eid = upsert_employer(conn, "Firm 0400 Ltd", "MB", source="esdc_positive", now=NOW)
    esdc(conn, eid, "Firm 0400 Ltd", "MB", "Brandon", "85100")
    upsert_employer(conn, "Zulu Farms Ltd", "MB", source="esdc_positive", now=NOW)
    write(conn, tmp_path / "c", "2026-10-30")
    assert (tmp_path / "c" / "directory" / "mb" / "1.json").read_bytes() == before[1]
    assert dict(directory.sitemap_entries(conn)) == {
        "/places/mb/employers": "2026-10-28", "/places/mb/employers/2": "2026-10-28", "/places/mb/employers/3": "2026-10-30"}
    assert load(tmp_path / "c", "directory/mb/3.json")["rows"][-2:] == [
        {"id": eid, "name": "Firm 0400 Ltd", "city": "Brandon", "records": 1},
        {"id": upsert_employer(conn, "Zulu Farms Ltd", "MB", source="esdc_positive", now=NOW), "name": "Zulu Farms Ltd",
         "city": None, "records": 0},
    ]
    assert load(tmp_path / "c", "directory/mb/index.json")["updated"] == "2026-10-30"

    # A page no longer written leaves the ledger, and the sitemap with it.
    conn.execute("DELETE FROM esdc_records")
    gone = "SELECT id FROM employers WHERE province = 'MB' AND norm_name >= 'firm 0200'"
    conn.execute(f"DELETE FROM employer_names WHERE employer_id IN ({gone})")
    conn.execute(f"DELETE FROM employers WHERE id IN ({gone})")
    write(conn, tmp_path / "d", "2026-10-31")
    assert dict(directory.sitemap_entries(conn)) == {"/places/mb/employers": "2026-10-28"}
    assert conn.execute("SELECT COUNT(*) FROM directory_pages").fetchone()[0] == 1


def test_a_province_with_no_employers_has_an_index_and_no_pages(conn, tmp_path):
    many(conn, 3, prov="BC", city="Kelowna")
    write(conn, tmp_path)
    yukon = load(tmp_path, "directory/yt/index.json")
    assert yukon == {"code": "yt", "employers": 0, "pages": 0, "page_size": 200, "ranges": [], "letters": [], "updated": None}
    assert not (tmp_path / "directory" / "yt" / "1.json").exists()
    summary = load(tmp_path, "directory/index.json")
    assert [d["code"] for d in summary["directories"]] == directory.CODES
    assert {d["code"]: d["employers"] for d in summary["directories"]}["yt"] == 0
    assert {d["code"]: d["pages"] for d in summary["directories"]}["bc"] == 1
    assert [p for p, _ in directory.sitemap_entries(conn)] == ["/places/bc/employers"]


def test_head_offices_outside_canada_and_no_province_share_one_directory(conn, tmp_path):
    abroad = upsert_employer(conn, "Global Rigging LLC", "XX", source="esdc_positive", city="Houston", now=NOW)
    unknown = upsert_employer(conn, "Nowhere Known Inc", None, source="esdc_negative", now=NOW)
    local = upsert_employer(conn, "Local Bakery Ltd", "NS", source="jobbank", city="Halifax", now=NOW)
    write(conn, tmp_path)
    rows = load(tmp_path, "directory/other/1.json")["rows"]
    assert rows == [
        {"id": abroad, "name": "Global Rigging LLC", "city": "Houston", "records": 0, "prov": "XX"},
        {"id": unknown, "name": "Nowhere Known Inc", "city": None, "records": 0, "prov": None},
    ]
    assert [r["id"] for r in load(tmp_path, "directory/ns/1.json")["rows"]] == [local]
    assert not (tmp_path / "directory" / "xx").exists()
    assert [p for p, _ in directory.sitemap_entries(conn)] == ["/places/ns/employers", "/places/other/employers"]


def test_the_record_count_is_the_one_the_profile_lists(conn, tmp_path):
    a = upsert_employer(conn, "Prairie Diner Ltd", "MB", source="esdc_positive", city="Winnipeg", now=NOW)
    esdc(conn, a, "Prairie Diner Ltd", "MB", "Winnipeg", "63200", n=3)
    posting(conn, 1, a, "Prairie Diner Ltd", "MB", "Winnipeg", "63200")
    posting(conn, 2, a, "Prairie Diner Ltd", "MB", "Winnipeg", None)
    conn.execute("UPDATE jobbank_postings SET flag_current = 'gone' WHERE posting_id = 2")
    status.recompute(conn, now=NOW)
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    profile = load(out, f"profiles/{export_static.shard_key(a)}.json")[a]
    row = load(out, "directory/mb/1.json")["rows"][0]
    assert row["records"] == len(profile["postings"]) + len(profile["esdc"]) == 5


def test_initials_file_digits_and_other_scripts_under_one_mark():
    assert directory.initial("0704250 bc") == "#"
    assert directory.initial("acme") == "A"
    assert directory.initial("") == "#"
    assert directory.initial("北京") == "#"


def test_a_city_named_employers_does_not_take_the_directory_path(conn):
    eid = upsert_employer(conn, "Odd Town Co", "MB", source="esdc_positive", city="Employers", now=NOW)
    esdc(conn, eid, "Odd Town Co", "MB", "Employers", "63200", n=places.THRESHOLD)
    assert ("MB", "employers") not in places.Catalog(conn).cities


# -- related employers -------------------------------------------------------------


def test_related_employers_are_the_nearest_in_record_count_in_the_city_then_the_occupation(conn):
    up = lambda name, city, prov="MB": upsert_employer(conn, name, prov, source="esdc_positive", city=city, now=NOW)  # noqa: E731
    # Winnipeg, ranked by records: w9 (9), w7 (7), w5 (5), w4 (4), w3 (3), w2 (2), w1 (1).
    w = {n: up(f"Winnipeg Firm {n}", "Winnipeg") for n in (9, 7, 5, 4, 3, 2, 1)}
    for n, eid in w.items():
        esdc(conn, eid, f"Winnipeg Firm {n}", "MB", "Winnipeg", "63200", n=n)
    # Brandon: one employer, so its list is filled from its occupation in the province.
    b = up("Brandon Grill", "BRANDON")
    esdc(conn, b, "Brandon Grill", "MB", "Brandon", "63200", n=4)
    # The same occupation in another province is never related.
    elsewhere = up("Calgary Cooks", "Calgary", prov="AB")
    esdc(conn, elsewhere, "Calgary Cooks", "AB", "Calgary", "63200", n=4)
    rel = directory.related(directory.Model(conn))

    # Nearest to w4 (rank 4 of 7): w5 and w3, then w7 and w2, then w9; ordered by records.
    assert [r["id"] for r in rel[w[4]]] == [w[9], w[7], w[5], w[3], w[2]]
    assert all("city" not in r for r in rel[w[4]])
    # The busiest has only employers below it.
    assert [r["id"] for r in rel[w[9]]] == [w[7], w[5], w[4], w[3], w[2]]
    # Brandon Grill (4 records, NOC 63200) ranks between w5 and w4 in the
    # Manitoba 63200 group (a tie on records goes to the name): the nearest are
    # w5 and w4, then w7 and w3, then w9, each with its city since it is not Brandon's.
    assert [r["id"] for r in rel[b]] == [w[9], w[7], w[5], w[4], w[3]]
    assert rel[b][0] == {"id": w[9], "name": "Winnipeg Firm 9", "city": "Winnipeg"}
    assert elsewhere not in rel  # alone in Calgary and in Alberta's 63200 group
    for eid, rows in rel.items():
        assert eid not in [r["id"] for r in rows] and len(rows) <= directory.RELATED_MAX


def test_a_city_list_short_of_five_is_filled_from_the_occupation(conn):
    up = lambda name, city: upsert_employer(conn, name, "BC", source="esdc_positive", city=city, now=NOW)  # noqa: E731
    a, b = up("Kelowna One Ltd", "Kelowna"), up("Kelowna Two Ltd", "Kelowna")
    esdc(conn, a, "Kelowna One Ltd", "BC", "Kelowna", "85100", n=2)
    esdc(conn, b, "Kelowna Two Ltd", "BC", "Kelowna", "85100", n=1)
    # Two other Kelowna codes would tie for most common at Kelowna Two: the
    # five-digit code wins, then the lower code.
    esdc(conn, b, "Kelowna Two Ltd", "BC", "Kelowna", "8431", n=1)
    v = up("Vernon Orchard Ltd", "Vernon")
    esdc(conn, v, "Vernon Orchard Ltd", "BC", "Vernon", "85100", n=1)
    p = up("Penticton Vines Ltd", "Penticton")
    esdc(conn, p, "Penticton Vines Ltd", "BC", "Penticton", "8431", n=3)
    m = directory.Model(conn)
    assert m.noc[b] == "85100"
    rel = directory.related(m)
    assert rel[a] == [{"id": b, "name": "Kelowna Two Ltd"}, {"id": v, "name": "Vernon Orchard Ltd", "city": "Vernon"}]
    assert p not in [r["id"] for r in rel[a]]


def test_related_employers_cost_a_fixed_number_of_queries(conn):
    def queries(n):
        for i in range(n):
            eid = upsert_employer(conn, f"Query Test {n}-{i}", "ON", source="esdc_positive", city="Guelph", now=NOW)
            esdc(conn, eid, f"Query Test {n}-{i}", "ON", "Guelph", "63200", n=1)
        seen: list[str] = []
        conn.set_trace_callback(seen.append)
        try:
            directory.related(directory.Model(conn))
        finally:
            conn.set_trace_callback(None)
        return len([q for q in seen if q.lstrip().upper().startswith("SELECT")])

    assert queries(3) == queries(60)


def test_profiles_carry_their_related_employers(conn, tmp_path):
    a = upsert_employer(conn, "Alpha Farms Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
    b = upsert_employer(conn, "Beta Orchards Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
    lone = upsert_employer(conn, "Lone Star LLC", "XX", source="esdc_positive", now=NOW)
    status.recompute(conn, now=NOW)
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    assert counts["related_profiles"] == 2 and counts["directory_pages"] == 2
    shard = lambda eid: load(out, f"profiles/{export_static.shard_key(eid)}.json")[eid]  # noqa: E731
    assert shard(a)["related"] == [{"id": b, "name": "Beta Orchards Ltd"}]
    assert shard(b)["related"] == [{"id": a, "name": "Alpha Farms Ltd"}]
    # Nothing related: no key, as with the other optional lists.
    assert "related" not in shard(lone)


def test_a_failing_directory_model_leaves_the_profiles_and_the_rest_of_the_export(conn, tmp_path, monkeypatch):
    a = upsert_employer(conn, "Alpha Farms Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
    upsert_employer(conn, "Beta Orchards Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
    status.recompute(conn, now=NOW)

    class Broken:
        def __init__(self, conn):
            raise ValueError("bad employer row")

    monkeypatch.setattr(export_static.directory, "Model", Broken)
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    failed = [r[0] for r in conn.execute("SELECT source FROM sources_log WHERE ok = 0 ORDER BY id")]
    assert failed == ["export_directory", "export_related"]
    assert not (out / "directory").exists()
    assert "related" not in load(out, f"profiles/{export_static.shard_key(a)}.json")[a]
    assert "/places/bc/employers" not in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
