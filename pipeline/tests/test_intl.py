"""Grades of postings open to international candidates, every rule and its edges, and the files the site reads."""

from __future__ import annotations

import json

import pytest

from lmia_pipeline import export_static, intl
from lmia_pipeline.db import set_meta, upsert_employer

NOW = "2026-10-26T00:10:00Z"
LISTED = {"21220": 70, "41200": 100, "31202": 70, "00010": 50}


def posting(**over) -> dict:
    row = {"lmia": "none", "detail_fetched_at": NOW, "audience": "international", "full_time": 1, "permanent": 1,
           "noc_code": "21220", "ee_phrases": None, "pr_phrases": None, "exempt_phrases": None}
    row.update(over)
    return row


# -- the rules ----------------------------------------------------------------------------


def test_a_listed_occupation_full_time_and_permanent_is_a():
    assert intl.grade_posting(posting(), LISTED) == ("A", ["intl", "no_lmia", "full_time", "permanent", "high_wage:70"])
    assert intl.grade_posting(posting(noc_code="41200"), LISTED)[1][-1] == "high_wage:100"
    assert intl.grade_posting(posting(noc_code="00010"), LISTED)[1][-1] == "high_wage:50"


@pytest.mark.parametrize("over, reason", [
    ({"full_time": 0}, "not_full_time"),
    ({"permanent": 0}, "not_permanent"),
    ({"full_time": None}, "not_full_time"),   # terms not stated
])
def test_a_listed_occupation_that_is_not_full_time_and_permanent_is_c(over, reason):
    g, reasons = intl.grade_posting(posting(**over), LISTED)
    assert g == "C" and reason in reasons and "high_wage:70" in reasons


def test_express_entry_wording_makes_any_international_posting_a():
    g, reasons = intl.grade_posting(posting(noc_code="65201", full_time=0, permanent=0, ee_phrases=json.dumps(["Express Entry"])),
                                    LISTED)
    assert g == "A"
    assert reasons == ["intl", "no_lmia", "not_full_time", "not_permanent", "teer_low:5", "ee_wording"]


def test_a_teer_0_to_3_occupation_off_the_list_full_time_and_permanent_is_b():
    for noc, teer in (("60030", 0), ("13110", 3), ("21100", 1), ("72010", 2)):
        g, reasons = intl.grade_posting(posting(noc_code=noc), LISTED)
        assert (g, reasons[-1]) == ("B", f"teer_listed_no:{teer}"), noc


@pytest.mark.parametrize("over", [
    {"noc_code": "60030", "permanent": 0},
    {"noc_code": "60030", "full_time": 0},
    {"noc_code": "65201"},                    # TEER 5
    {"noc_code": "44101"},                    # TEER 4
    {"noc_code": None},                       # no code on the page
    {"noc_code": "6322"},                     # a NOC 2016 code: no TEER
])
def test_everything_else_without_an_lmia_request_is_c(over):
    assert intl.grade_posting(posting(**over), LISTED)[0] == "C"


def test_reason_keys_for_the_occupation():
    assert intl.grade_posting(posting(noc_code="65201"), LISTED)[1][-1] == "teer_low:5"
    assert intl.grade_posting(posting(noc_code=None), LISTED)[1][-1] == "no_noc"


def test_pr_and_exempt_wording_are_reasons_but_never_raise_the_grade():
    g, reasons = intl.grade_posting(posting(noc_code="65201", pr_phrases='["PR sponsorship"]',
                                            exempt_phrases='["LMIA exempt"]'), LISTED)
    assert g == "C" and reasons[-2:] == ["pr_wording", "exempt_wording"]


@pytest.mark.parametrize("over, reason", [
    ({"lmia": "requested"}, "lmia_requested"),
    ({"lmia": "approved"}, "lmia_requested"),
    ({"lmia": "requested", "ee_phrases": '["Express Entry"]'}, "lmia_requested"),
    ({"detail_fetched_at": None}, "not_read"),
    ({"audience": "unknown"}, "not_read"),
    ({"audience": "authorized"}, "not_intl"),
    ({"audience": "canadians"}, "not_intl"),
])
def test_no_grade_with_an_lmia_request_before_the_page_is_read_or_off_the_facet(over, reason):
    assert intl.grade_posting(posting(**over), LISTED) == (None, [reason])


def test_an_lmia_unknown_on_a_read_page_is_graded_as_no_request():
    # The listing showed no flag, the page was read and showed none: "unknown" only before both.
    assert intl.grade_posting(posting(lmia="unknown"), LISTED)[0] == "A"


def test_the_list_tier_follows_the_noc_alone():
    # No wage enters the rule: a row's wage fields are not read at all.
    a = intl.grade_posting(posting(wage_min=15.0, wage_unit="HOUR"), LISTED)
    b = intl.grade_posting(posting(wage_min=150.0, wage_unit="HOUR"), LISTED)
    assert a == b


def test_teer():
    assert [intl.teer(c) for c in ("00010", "21220", "65201", "44101", "6322", None, "abcde")] == [0, 1, 5, 4, None, None, None]


# -- storing and exporting ---------------------------------------------------------------


def insert(conn, pid, **over):
    row = {"posting_id": pid, "employer_raw": "Silaris Solutions Inc", "title": "cybersecurity specialist", "noc_code": "21220",
           "city": "Milton", "province": "ON", "date_posted": "2026-10-26", "first_seen": NOW, "last_seen": NOW,
           "found_by": "feed", "in_facet": 1, "audience": "international", "lmia": "none", "full_time": 1, "permanent": 1,
           "detail_fetched_at": NOW, "url": f"https://www.jobbank.gc.ca/jobsearch/jobposting/{pid}", "updated_at": NOW}
    row.update(over)
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO jobbank_intl_postings ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()


def test_regrade_stores_every_grade_and_follows_a_new_list(conn):
    insert(conn, 1)
    insert(conn, 2, noc_code="60030")
    insert(conn, 3, lmia="requested")
    counts = intl.regrade(conn, LISTED, now=NOW)
    assert counts == {"A": 1, "B": 1, "none": 1}
    got = {r[0]: (r[1], json.loads(r[2])) for r in conn.execute("SELECT posting_id, grade, grade_reasons FROM jobbank_intl_postings")}
    assert got[1] == ("A", ["intl", "no_lmia", "full_time", "permanent", "high_wage:70"])
    assert got[3] == (None, ["lmia_requested"])
    # The list regenerated without 21220: the A becomes a B on the next run.
    intl.regrade(conn, {"41200": 100}, now=NOW)
    assert conn.execute("SELECT grade FROM jobbank_intl_postings WHERE posting_id = 1").fetchone()[0] == "B"


def test_the_index_is_absent_before_the_first_pass(conn):
    assert intl.build_index(conn, "2026-10-26") is None


def test_the_index_holds_the_series_breakdowns_recent_rows_and_the_list_version(conn):
    eid = upsert_employer(conn, "Silaris Solutions Inc", "ON", source="jobbank", now=NOW)
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, resource_id, row_hash) "
                 "VALUES ('positive', '2025Q4', ?, 'Silaris Solutions Inc', 'r', 'h1')", (eid,))
    insert(conn, 1, employer_id=eid)
    insert(conn, 2, noc_code="60030", province="BC", date_posted="2026-10-25", ee_phrases='["Express Entry"]')
    insert(conn, 3, lmia="requested", date_posted="2026-10-25")
    insert(conn, 4, detail_fetched_at=None, audience="unknown", date_posted="2026-10-26")
    insert(conn, 5, in_facet=0, date_posted="2026-10-20")     # before the baseline, and gone
    intl.regrade(conn, LISTED, now=NOW)
    set_meta(conn, "intl_baseline", "2026-10-25")
    set_meta(conn, "intl_last_run", NOW)
    conn.executemany("INSERT INTO jobbank_facet_counts (day, key, value) VALUES (?, ?, ?)",
                     [("2026-10-25", "total", 8032), ("2026-10-26", "total", 8100), ("2026-10-26", "lmia_requested", 1090)])
    conn.commit()
    doc = intl.build_index(conn, "2026-10-26")
    assert doc["baseline"] == "2026-10-25" and doc["change_date"] == "2026-11-03"
    assert doc["daily"] == [
        {"day": "2026-10-25", "all": 2, "lmia": 1, "A": 1, "B": 0, "C": 0, "unread": 0},
        {"day": "2026-10-26", "all": 2, "lmia": 0, "A": 1, "B": 0, "C": 0, "unread": 1},
    ]
    assert doc["facet"] == [{"day": "2026-10-25", "total": 8032}, {"day": "2026-10-26", "total": 8100, "lmia_requested": 1090}]
    assert doc["totals"] == {"live": 4, "live_lmia": 1, "live_no_lmia": 3, "unread": 1, "seen": 5}
    assert doc["by_grade"] == {"A": 2, "B": 0, "C": 0, "unread": 1}
    assert doc["by_province"][0] == {"k": "ON", "A": 1, "B": 0, "C": 0, "unread": 1}
    assert doc["by_noc"][0]["k"] == "21220" and doc["by_noc"][0]["points"] == 70 and doc["by_noc"][0]["teer"] == 1
    recent = {r["id"]: r for r in doc["recent"]}
    assert set(recent) == {1, 2, 5}
    assert recent[1]["lmia_history"] is True and recent[1]["employer_id"] == eid
    assert recent[2]["phrases"] == {"ee": ["Express Entry"]} and "ee_wording" in recent[2]["reasons"]
    assert doc["high_wage"]["count"] == 186 and doc["high_wage"]["read_on"] == "2026-10-25"


def test_profile_rows_and_stats_counts(conn):
    eid = upsert_employer(conn, "Silaris Solutions Inc", "ON", source="jobbank", now=NOW)
    insert(conn, 1, employer_id=eid)
    insert(conn, 2, employer_id=eid, lmia="requested", date_posted="2026-10-01")
    insert(conn, 3)
    intl.regrade(conn, LISTED, now=NOW)
    rows = intl.profile_rows(conn, [eid])[eid]
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["grade"] == "A" and rows[1]["grade"] is None and rows[1]["lmia"] == "requested"
    assert intl.stats_counts(conn) == {"intl_live": 3, "intl_no_lmia": 2, "intl_grade_a": 2, "designated_employers": 0}


def test_the_export_writes_the_page_file_profile_rows_stats_and_the_sitemap_entry(conn, tmp_path, monkeypatch):
    monkeypatch.setattr("lmia_pipeline.config.SITE_URL", "https://lmiawatch.ca")
    eid = upsert_employer(conn, "Silaris Solutions Inc", "ON", source="jobbank", now=NOW)
    insert(conn, 1, employer_id=eid)
    intl.regrade(conn, LISTED, now=NOW)
    set_meta(conn, "data_as_of", "2026-10-26")
    out = tmp_path / "static"
    # Before any pass: no file, no sitemap entry.
    export_static.export_static(conn, out)
    assert not (out / "international" / "index.json").exists()
    assert "/international" not in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    set_meta(conn, "intl_last_run", NOW)
    set_meta(conn, "intl_baseline", "2026-10-26")
    conn.commit()
    export_static.export_static(conn, out)
    doc = json.loads((out / "international" / "index.json").read_text(encoding="utf-8"))
    assert doc["totals"]["live"] == 1 and isinstance(doc["registers"], list)
    stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert stats["counts"]["intl_live"] == 1 and stats["counts"]["intl_grade_a"] == 1
    assert {r["key"] for r in stats["registers"]} >= {"aip_nl", "aip_pe", "rcip_sudbury", "fcip_kelowna"}
    shard = json.loads((out / "profiles" / f"{eid[4:7]}.json").read_text(encoding="utf-8"))
    assert shard[eid]["intl"][0]["grade"] == "A"
    assert "designated" not in shard[eid]
    assert "https://lmiawatch.ca/international</loc>" in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
