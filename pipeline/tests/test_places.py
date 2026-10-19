"""Occupation and place pages: the aggregation against figures worked out by hand
from a small seeded database, the thin-page rule and the sitemap entries."""

import json

import pytest

from lmia_pipeline import config, export_static, places, status
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-18T00:00:00Z"


def esdc(conn, list_, period, eid, raw, prov, stream, city, postal, noc, positions, resource):
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, "
        "noc_title, lmias, positions, resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (list_, period, eid, raw, prov, stream, city, postal, noc, "Cooks" if noc == "63200" else "Other", positions,
         resource, f"{list_}{period}{eid}{noc}{city}"),
    )


def posting(conn, pid, eid, raw, noc, city, prov, postal, wage, unit, flag, posted, seen, vacancies=None):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, noc_code, city, province, postal_code, "
        "wage_min, wage_max, wage_unit, vacancies, date_posted, first_seen, last_seen, flag_current, flag_first, url, updated_at) "
        "VALUES (?, ?, ?, 'cook', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', 'u', ?)",
        (pid, eid, raw, noc, city, prov, postal, wage, wage, unit, vacancies, posted, seen, seen, flag, seen),
    )


def seed(conn) -> dict[str, str]:
    """Seven employers in Manitoba, BC and abroad; the site's fixtures are written from this too."""
    up = lambda name, prov, city=None: upsert_employer(conn, name, prov, source="esdc_positive", city=city, now=NOW)  # noqa: E731
    ids = {
        "A": up("Prairie Diner Ltd", "MB", "Winnipeg"),
        "B": up("Malo Farms Inc", "MB", "St Malo"),
        "C": up("Malo Cafe Inc", "MB", "Saint-Malo"),
        "D": up("Old Times Co", "MB", "Winnipeg"),
        "E": up("Foreign Head Office Ltd", "XX"),
        "F": up("Kelowna Bistro Ltd", "BC", "Kelowna"),
        "G": up("Remote Ranch Ltd", "MB", "Winnipeg"),
    }
    for rid, dataset, period, published in (("r0", "positive", "2019Q2", "2019-10-01"), ("r1", "positive", "2025Q4", "2026-04-20"),
                                            ("r2", "positive", "2026Q1", "2026-07-22"), ("n2", "negative", "2026Q1", "2026-07-22")):
        conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                     "loaded_at) VALUES (?, ?, ?, 'n', 'u', ?, 's', 1, 1, ?)", (rid, dataset, period, published, NOW))
    a, b, c, d, e = ids["A"], ids["B"], ids["C"], ids["D"], ids["E"]
    esdc(conn, "positive", "2026Q1", a, "Prairie Diner Ltd", "MB", "Low Wage", "Winnipeg", "R3C 1A1", "63200", 3, "r2")
    esdc(conn, "positive", "2025Q4", a, "Prairie Diner Ltd", "MB", "Low Wage", "Winnipeg", "R3C 1A1", "63200", 2, "r1")
    esdc(conn, "negative", "2026Q1", a, "Prairie Diner Ltd", "MB", "Low Wage", "Winnipeg", "R3C 1A1", "63200", 1, "n2")
    esdc(conn, "positive", "2026Q1", b, "Malo Farms Inc", "MB", "Primary Agriculture", "St Malo", "R0G 2A0", "85101", 10, "r2")
    esdc(conn, "positive", "2026Q1", c, "Malo Cafe Inc", "MB", "High Wage", "SAINT-MALO", "R0G 2A0", "63200", 1, "r2")
    esdc(conn, "positive", "2019Q2", d, "Old Times Co", "MB", None, "Winnipeg", "R3C 1A1", "6322", 4, "r0")
    esdc(conn, "positive", "2026Q1", e, "Foreign Head Office Ltd", "XX", "High Wage", None, None, "63200", 5, "r2")
    posting(conn, 101, a, "Prairie Diner Ltd", "63200", "Winnipeg", "MB", "R3C 1A1", 17.0, "HOUR", "requested", "2026-10-05", "2026-10-06T01:00:00Z", 2)
    posting(conn, 102, ids["F"], "Kelowna Bistro Ltd", "63200", "Kelowna", "BC", "V1Y 1A1", 20.0, "HOUR", "approved", "2026-10-01", "2026-10-02T01:00:00Z")
    posting(conn, 103, a, "Prairie Diner Ltd", "63200", "Winnipeg", "MB", "R3C 1A1", 15.0, "HOUR", "gone", "2026-09-01", "2026-09-02T01:00:00Z")
    posting(conn, 104, ids["G"], "Remote Ranch Ltd", None, "Winnipeg", "MB", None, 52000.0, "YEAR", "requested", "2026-10-02", "2026-10-03T01:00:00Z")
    conn.executemany("INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) VALUES (?, ?, ?, ?, ?, 0, 0, 'centroid')", [
        ("R3C", "4650", "Winnipeg", "602", "Winnipeg"),
        ("R0G", "4620", "South Central", None, None),
        ("V1Y", "5930", "Thompson--Okanagan", "915", "Kelowna"),
    ])
    conn.execute("INSERT INTO wage_tables (resource_id, name, url, source_modified, revision_date, sha256, bytes, rows_loaded, loaded_at) "
                 "VALUES ('w1', '2025 Wages', 'u', 'm', '2025-11-19', 's', 1, 5, ?)", (NOW,))
    conn.executemany("INSERT INTO jobbank_wages (resource_id, noc_code, area_code, province, area_name, median, low, high, annual, "
                     "reference_period) VALUES ('w1', ?, ?, ?, ?, ?, NULL, NULL, ?, '2023-2024')", [
        ("63200", "4650", "MB", "Winnipeg", 16.0, 0),
        ("63200", "46", "MB", "Manitoba", 16.5, 0),
        ("63200", "00", None, "Canada", 18.0, 0),
    ])
    conn.executemany("INSERT INTO statcan_vacancies VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)", [
        ("63200", "4650", "2026Q2", "Winnipeg", 300, "E", 17.05, "A"),
        ("63200", "4650", "2025Q2", "Winnipeg", 220, "E", 18.85, "B"),
        ("63200", "00", "2026Q2", "Canada", 13310, "B", 19.55, "A"),
        ("total", "4650", "2026Q2", "Winnipeg", 11315, "B", 26.0, "A"),
        ("total", "4650", "2025Q2", "Winnipeg", 12200, "B", 25.5, "A"),
    ])
    conn.executemany("INSERT INTO noc_titles VALUES (?, ?, ?, ?, ?, ?)", [
        ("6", 1, "Sales and service occupations", "Vente et services", None, None),
        ("63200", 5, "Cooks", "Cuisiniers/cuisinières", "Cooks prepare food.", "Les cuisiniers préparent."),
    ])
    conn.execute("INSERT INTO lfs_unemployment VALUES ('602', '2026-09', 5.9, 'Winnipeg', NULL)")
    status.recompute(conn, now=NOW)
    conn.commit()
    return ids


@pytest.fixture
def seeded(conn):
    return seed(conn)


@pytest.fixture
def small_threshold(monkeypatch):
    monkeypatch.setattr(places, "THRESHOLD", 3)


def load(out, rel):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_occupation_page_figures(conn, seeded, tmp_path, small_threshold):
    counts = places.write_places(conn, tmp_path)
    o = load(tmp_path, "occupations/63200.json")
    assert o["title"] == {"en": "Cooks", "fr": "Cuisiniers/cuisinières"}
    assert o["category_title"]["fr"] == "Vente et services" and o["teer"] == "3"
    # Five-digit codes start in 2025 Q4 here; the 2019 four-digit row is not an occupation record.
    assert o["from"] == "2025Q4" and o["latest"] == "2026Q1"
    # Five list rows (A three times, C, the head office abroad) and three postings.
    assert o["totals"] == {"records": 8, "approved": 4, "positions": 11, "refused": 1, "refused_positions": 1,
                           "pending": 1, "postings": 3, "employers": 4}
    assert o["quarters"] == [["2025Q4", 1, 2, 0, 0], ["2026Q1", 3, 9, 1, 1]]
    assert o["streams"] == [["High Wage", 2, 6], ["Low Wage", 2, 5]]
    assert o["provinces"] == [["MB", 6, 6, 1], ["BC", 1, 0, 0], ["XX", 1, 5, 0]]
    # Posted minimums 17, 20 and 15 an hour: median 17 across Canada.
    assert o["national"]["posted"] == {"hourly": 17.0, "hourly_n": 3, "annual": None, "annual_n": 0}
    assert o["national"]["jobbank"]["median"] == 18.0 and o["national"]["jobbank"]["level"] == "canada"
    assert o["national"]["statcan"]["wage"] == 19.55 and o["national"]["statcan"]["vacancies"] == 13310
    assert "vacancies_year_before" not in o["national"]["statcan"]
    regions = {r["er"]: r for r in o["regions"]}
    assert [r["er"] for r in o["regions"]] == ["4650", "4620", "5930"]
    win = regions["4650"]
    assert (win["records"], win["positions"], win["refused"]) == (5, 5, 1)
    assert win["posted"]["hourly"] == 16.0 and win["posted"]["hourly_n"] == 2
    assert win["jobbank"]["median"] == 16.0 and win["jobbank"]["level"] == "region"
    assert win["statcan"]["vacancies"] == 300 and win["statcan"]["vacancies_year_before"] == 220
    assert win["statcan"]["wage"] == 17.05 and win["statcan"]["wage_quality"] == "A"
    # No regional median in South Central: the provincial one; in Thompson-Okanagan: the national one.
    assert regions["4620"]["jobbank"]["median"] == 16.5 and regions["4620"]["jobbank"]["level"] == "province"
    assert regions["5930"]["jobbank"]["level"] == "canada" and regions["5930"]["statcan"]["level"] == "canada"
    # Newest record first, one row per employer: postings 101 (A) and 102 (F), then the 2026 Q1 rows.
    ids = seeded
    assert [e["id"] for e in o["employers"]] == [ids["A"], ids["F"], ids["E"], ids["C"]]
    assert o["employers"][0]["status"] == "pending" and o["employers"][0]["positions"] == 2
    assert o["national_latest"] == {"period": "2026Q1", "approved": 4, "positions": 19, "refused": 1}
    assert o["updated"] == "2026-10-06"
    index = load(tmp_path, "occupations/index.json")
    rows = {r["noc"]: r for r in index["rows"]}
    assert set(rows) == {"63200", "85101"}
    assert rows["63200"]["indexed"] and not rows["85101"]["indexed"]
    assert rows["63200"]["latest_positions"] == 9
    assert counts["occupation_pages"] == 2 and counts["occupation_indexed"] == 1


def test_place_pages_figures(conn, seeded, tmp_path, small_threshold):
    places.write_places(conn, tmp_path)
    mb = load(tmp_path, "places/mb.json")
    # Six list rows (A three times, B, C, D) and three postings; the head office abroad is not in Manitoba.
    assert mb["totals"] == {"records": 9, "approved": 5, "positions": 20, "refused": 1, "refused_positions": 1,
                            "pending": 2, "postings": 3, "employers": 5}
    assert mb["quarters"] == [["2019Q2", 1, 4, 0, 0], ["2025Q4", 1, 2, 0, 0], ["2026Q1", 3, 14, 1, 1]]
    assert mb["streams"] == [["Primary Agriculture", 1, 10], ["Low Wage", 2, 5], [None, 1, 4], ["High Wage", 1, 1]]
    occ = {o["noc"]: o for o in mb["occupations"]}
    assert [o["noc"] for o in mb["occupations"]] == ["63200", "85101"]
    assert (occ["63200"]["records"], occ["63200"]["positions"], occ["63200"]["refused"]) == (6, 6, 1)
    # A province page compares with provincial figures, falling back to Canada.
    assert occ["63200"]["posted"]["hourly"] == 16.0
    assert occ["63200"]["jobbank"]["median"] == 16.5 and occ["63200"]["statcan"]["level"] == "canada"
    assert mb["region"] is None and mb["context"] is None
    assert [c["slug"] for c in mb["cmas"]] == ["winnipeg-cma"]
    assert [c["slug"] for c in mb["cities"]] == ["winnipeg"]

    cma = load(tmp_path, "places/mb/winnipeg-cma.json")
    assert cma["kind"] == "cma" and cma["totals"]["records"] == 6
    assert cma["region"] == {"er": "4650", "name": "Winnipeg"}
    assert cma["context"]["vacancies"] == 11315 and cma["context"]["vacancies_year_before"] == 12200
    assert cma["context"]["wage"] == 26.0
    assert cma["lfs"] == {"month": "2026-09", "rate": 5.9}

    city = load(tmp_path, "places/mb/winnipeg.json")
    assert city["kind"] == "city" and city["name"] == "Winnipeg" and city["totals"]["records"] == 7
    assert city["cma"] == {"slug": "winnipeg-cma", "name": "Winnipeg", "prov": "MB"}
    # Two records in St Malo: under the threshold, so no city page.
    assert not (tmp_path / "places" / "mb" / "st-malo.json").exists()
    # A province or metropolitan area under the threshold still gets its page (marked noindex by the site).
    assert load(tmp_path, "places/bc.json")["totals"]["records"] == 1
    assert (tmp_path / "places" / "bc" / "kelowna-cma.json").exists()
    assert not (tmp_path / "places" / "xx.json").exists()

    index = load(tmp_path, "places/index.json")
    provs = {p["prov"]: p for p in index["provinces"]}
    assert set(provs) == {"BC", "MB"}
    assert provs["MB"]["indexed"] and not provs["BC"]["indexed"]
    assert provs["MB"]["top_cities"] == [{"name": "Winnipeg", "records": 7, "slug": "winnipeg"}]


def test_spellings_of_one_city_fold_together(conn, seeded):
    model = places.build(conn)
    st_malo = model.city[("MB", "st-malo")]
    assert st_malo.records == 2
    assert places.display_name(st_malo.spellings) == "St Malo"


def test_slugs_and_display_names():
    from collections import Counter
    assert places.slugify("Saint-Hyacinthe") == places.slugify("St Hyacinthe") == places.slugify("ST-HYACINTHE") == "st-hyacinthe"
    assert places.slugify("Montréal") == "montreal"
    assert places.slugify("Sainte-Agathe-des-Monts") == "ste-agathe-des-monts"
    assert places.slugify("St. John's") == "st-johns"
    assert places.slugify(". Calgary") == "calgary"
    assert places.slugify(None) == ""
    assert places.display_name(Counter({"CALGARY": 9, "Calgary": 3})) == "Calgary"
    assert places.display_name(Counter({"KELOWNA": 2})) == "Kelowna"


def test_thin_pages_stay_out_of_the_sitemap(conn, seeded, small_threshold):
    paths = [p for p, _ in places.sitemap_entries(conn)]
    assert paths == ["/occupations", "/occupations/63200", "/places", "/places/mb", "/places/mb/winnipeg-cma", "/places/mb/winnipeg"]
    dated = dict(places.sitemap_entries(conn))
    assert dated["/occupations/63200"] == "2026-10-06" and dated["/occupations"] == "2026-10-06"


def test_the_default_threshold_is_twenty(conn, seeded):
    assert places.THRESHOLD == 20
    # Nothing in the seed reaches twenty records, so nothing is listed.
    assert places.sitemap_entries(conn) == []


def test_static_export_writes_the_pages_and_lists_them(conn, seeded, tmp_path, monkeypatch, small_threshold):
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    counts = export_static.export_static(conn, tmp_path / "static")
    assert counts["place_files"] == len(list((tmp_path / "static" / "places").rglob("*.json"))) + len(
        list((tmp_path / "static" / "occupations").rglob("*.json")))
    assert counts["place_largest"] < 300_000
    text = (tmp_path / "static" / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    assert "<loc>https://lmiawatch.ca/occupations/63200</loc><lastmod>2026-10-06</lastmod>" in text
    assert "https://lmiawatch.ca/places/mb/winnipeg<" in text
    assert "/places/bc<" not in text and "/occupations/85101" not in text


def test_new_data_rebuilds_the_catalog(conn, seeded, small_threshold):
    first = places.catalog(conn)
    assert places.catalog(conn) is first
    esdc(conn, "positive", "2026Q1", seeded["B"], "Malo Farms Inc", "MB", "Primary Agriculture", "St-Malo", "R0G 2A0", "85101", 2, "r2")
    conn.commit()
    second = places.catalog(conn)
    assert second is not first
    assert ("MB", "st-malo") in second.cities


def test_at_most_twenty_employers(conn, tmp_path, small_threshold):
    for i in range(25):
        eid = upsert_employer(conn, f"Employer {i:02d} Ltd", "NS", source="esdc_positive", now=NOW)
        esdc(conn, "positive", "2026Q1", eid, f"Employer {i:02d} Ltd", "NS", "High Wage", "Halifax", "B3H 1A1", "63200", 1, "r2")
    conn.commit()
    places.write_places(conn, tmp_path)
    assert len(load(tmp_path, "occupations/63200.json")["employers"]) == 20
    assert len(load(tmp_path, "places/ns/halifax.json")["employers"]) == 20
