"""What LMIA postings offered: the posted-wage tables on the occupation pages,
against quartiles worked out by hand from a seeded archive.

The seed extends test_places.seed with nightly observations: hourly, yearly,
weekly, biweekly and unstated postings for NOC 65201, a posting seen on
several nights across two months, a flag that lapsed, a posting no pass saw
flagged, an economic region with enough postings (Winnipeg) and one without
(Thompson--Okanagan). The site's fixture occupation-65201.json is written from
this seed with places.THRESHOLD at 3.
"""

import json
import math

import pytest
from test_places import seed

from lmia_pipeline import offered, places
from lmia_pipeline.normalize import parse_salary_text

FOOD = "65201"
SEP, OCT, OCT_LATE, NOV, DEC = ("2026-09-28T01:00:00Z", "2026-10-05T01:00:00Z", "2026-10-20T01:00:00Z",
                                "2026-11-02T01:00:00Z", "2026-12-01T01:00:00Z")
WINNIPEG, KELOWNA = "R3C 1A1", "V1Y 1A1"


def post(conn, pid, eid, noc, postal, city, prov, low, high, unit, first_seen, flag="requested"):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, noc_code, city, province, postal_code, "
        "wage_min, wage_max, wage_unit, date_posted, first_seen, last_seen, flag_current, flag_first, url, updated_at) "
        "VALUES (?, ?, 'Employer', 'helper', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', 'u', ?)",
        (pid, eid, noc, city, prov, postal, low, high, unit, first_seen[:10], first_seen, first_seen, flag, first_seen),
    )


def seen(conn, pid, *nights, flag="requested"):
    for night in nights:
        conn.execute("INSERT INTO jobbank_observations (posting_id, observed_at, flag, facet) VALUES (?, ?, ?, ?)",
                     (pid, night, flag, "101020" if flag == "approved" else "101010"))


def seed_offered(conn) -> dict[str, str]:
    ids = seed(conn)
    a, f, g = ids["A"], ids["F"], ids["G"]
    # The cooks postings of the base seed, now observed: three postings, under the threshold.
    seen(conn, 101, "2026-10-06T01:00:00Z")
    seen(conn, 102, "2026-10-02T01:00:00Z", flag="approved")
    seen(conn, 103, "2026-09-02T01:00:00Z")
    seen(conn, 104, "2026-10-03T01:00:00Z")
    # Winnipeg: eleven hourly postings and one yearly; the region reaches the threshold.
    winnipeg = [
        (201, 16.00, 18.00, SEP), (202, 16.50, 16.50, OCT), (203, 17.00, 19.00, OCT), (204, 17.00, 20.00, OCT),
        (205, 17.50, 21.00, OCT), (206, 18.00, 22.00, OCT), (207, 18.00, 18.00, OCT), (208, 19.00, 23.00, OCT),
        (209, 20.00, 24.00, OCT), (210, 21.00, 25.00, OCT), (211, 25.00, 30.00, NOV),
    ]
    for pid, low, high, first in winnipeg:
        flag = {205: "gone", 210: "approved"}.get(pid, "requested")
        post(conn, pid, a, FOOD, WINNIPEG, "Winnipeg", "MB", low, high, "HOUR", first, flag)
        seen(conn, pid, first, flag="approved" if pid == 210 else "requested")
    # 201 is approved a week after it was first seen: still one posting, in September.
    seen(conn, 201, OCT, flag="approved")
    # 203 is seen again later in October and in November: still one posting, in October.
    seen(conn, 203, OCT_LATE, NOV)
    post(conn, 212, a, FOOD, WINNIPEG, "Winnipeg", "MB", 52000.0, 60000.0, "YEAR", OCT)
    seen(conn, 212, OCT)
    # In the postings table but never seen flagged by a nightly pass: left out.
    post(conn, 299, a, FOOD, WINNIPEG, "Winnipeg", "MB", 99.0, 99.0, "HOUR", OCT)
    # Kelowna: four postings, under the threshold, so no regional table.
    post(conn, 213, f, FOOD, KELOWNA, "Kelowna", "BC", 20.00, 22.00, "HOUR", OCT)
    post(conn, 214, f, FOOD, KELOWNA, "Kelowna", "BC", 22.00, 24.00, "HOUR", OCT)
    post(conn, 215, f, FOOD, KELOWNA, "Kelowna", "BC", 15.50, 17.00, "HOUR", SEP)
    post(conn, 216, f, FOOD, KELOWNA, "Kelowna", "BC", 1500.0, 1500.0, "BIWEEKLY", OCT)
    # No postal code: counted in the national table only.
    post(conn, 217, g, FOOD, None, "Brandon", "MB", 16.00, 17.00, "HOUR", OCT)
    post(conn, 218, g, FOOD, None, "Brandon", "MB", 700.0, 700.0, "WEEKLY", OCT)
    post(conn, 219, g, FOOD, None, "Brandon", "MB", None, None, None, NOV)
    for pid, first in ((213, OCT), (214, OCT), (215, SEP), (216, OCT), (217, OCT), (218, OCT), (219, NOV)):
        seen(conn, pid, first)
    # Another occupation's posting carries the archive into December.
    post(conn, 301, g, "73300", None, "Brandon", "MB", 30.0, 30.0, "HOUR", DEC)
    seen(conn, 301, DEC)
    conn.executemany("INSERT INTO jobbank_wages (resource_id, noc_code, area_code, province, area_name, median, low, high, annual, "
                     "reference_period) VALUES ('w1', ?, ?, ?, ?, ?, NULL, NULL, 0, '2023-2024')", [
        (FOOD, "4650", "MB", "Winnipeg", 15.80),
        (FOOD, "00", None, "Canada", 16.20),
    ])
    conn.executemany("INSERT INTO statcan_vacancies VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)", [
        (FOOD, "4650", "2026Q2", "Winnipeg", 410, "C", 16.40, "A"),
        (FOOD, "00", "2026Q2", "Canada", 21000, "A", 17.10, "A"),
    ])
    conn.execute("INSERT INTO noc_titles VALUES (?, 5, ?, ?, NULL, NULL)", (
        FOOD, "Food counter attendants, kitchen helpers and related support occupations",
        "Serveurs/serveuses au comptoir, aides de cuisine et personnel de soutien assimilé"))
    conn.commit()
    return ids


@pytest.fixture
def archive(conn):
    return seed_offered(conn)


def page(conn, tmp_path, monkeypatch, noc):
    monkeypatch.setattr(places, "THRESHOLD", 3)
    places.write_places(conn, tmp_path)
    return json.loads((tmp_path / "occupations" / f"{noc}.json").read_text(encoding="utf-8"))


MONTHS = ["2026-09", "2026-10", "2026-11", "2026-12"]


def test_national_table_against_hand_computed_quartiles(conn, archive, tmp_path, monkeypatch):
    o = page(conn, tmp_path, monkeypatch, FOOD)["offered"]
    assert o["threshold"] == 10 and o["since"] == "2026-09"
    nat = o["national"]
    # Nineteen flagged postings: twelve in Winnipeg, four in Kelowna, three unplaced; 299 was never seen flagged.
    assert nat["postings"] == 19
    assert nat["hourly_n"] == 15
    # Each other unit counted under its own name and never converted; the parser's WEEKLY and BIWEEKLY read as WEEK and BIWEEK.
    assert nat["other"] == [["BIWEEK", 1], ["WEEK", 1], ["YEAR", 1]]
    assert nat["unstated"] == 1
    # Hourly minimums sorted: 15.5 16 16 16.5 17 17 17.5 18 18 19 20 20 21 22 25 (n = 15).
    # 25th: rank 3.5 of 0..14, halfway from 16.5 to 17 = 16.75; median: rank 7 = 18; 75th: rank 10.5, 20 and 20 = 20.
    assert nat["min"] == [16.75, 18.0, 20.0]
    # Hourly maximums sorted: 16.5 17 17 18 18 19 20 21 22 22 23 24 24 25 30.
    # 25th: 18 and 18 = 18; median: 21; 75th: halfway from 23 to 24 = 23.5. A single figure (16.50) is both ends.
    assert nat["max"] == [18.0, 21.0, 23.5]


def test_monthly_series_counts_each_posting_once_by_first_seen(conn, archive, tmp_path, monkeypatch):
    nat = page(conn, tmp_path, monkeypatch, FOOD)["offered"]["national"]
    assert [m[0] for m in nat["months"]] == MONTHS
    # September: 201 (approved later, still September) and 215; two hourly, so no median.
    # October: twelve hourly postings (nine in Winnipeg, two in Kelowna, one unplaced) plus a yearly, a biweekly
    # and a weekly one; minimums 16 16.5 17 17 17.5 18 18 19 20 20 21 22, median 18.
    # November: 211 and the unstated 219; 203, seen again in November, stays in October.
    # December: nothing for this occupation, and the month is still listed.
    assert nat["months"] == [["2026-09", 2, 2, None], ["2026-10", 15, 12, 18.0], ["2026-11", 2, 1, None], ["2026-12", 0, 0, None]]
    assert sum(m[1] for m in nat["months"]) == nat["postings"]


def test_regional_tables_appear_at_ten_postings(conn, archive, tmp_path, monkeypatch):
    o = page(conn, tmp_path, monkeypatch, FOOD)["offered"]
    # Winnipeg holds twelve; Thompson--Okanagan four, which count in the national table only.
    assert [r["er"] for r in o["regions"]] == ["4650"]
    win = o["regions"][0]
    assert (win["name"], win["prov"]) == ("Winnipeg", "MB")
    assert (win["postings"], win["hourly_n"], win["other"], win["unstated"]) == (12, 11, [["YEAR", 1]], 0)
    # Minimums sorted: 16 16.5 17 17 17.5 18 18 19 20 21 25 (n = 11). 25th: rank 2.5, 17 and 17; median: rank 5 = 18;
    # 75th: rank 7.5, halfway from 19 to 20 = 19.5.
    assert win["min"] == [17.0, 18.0, 19.5]
    # Maximums sorted: 16.5 18 18 19 20 21 22 23 24 25 30. 25th: halfway from 18 to 19; median 21; 75th: halfway from 23 to 24.
    assert win["max"] == [18.5, 21.0, 23.5]
    # The table publishes on eleven hourly postings, but no single month reaches ten (October has nine).
    assert win["months"] == [["2026-09", 1, 1, None], ["2026-10", 10, 9, None], ["2026-11", 1, 1, None], ["2026-12", 0, 0, None]]
    # Beside it, the references for the same area: the regional Job Bank median and Statistics Canada's figure.
    assert win["jobbank"]["median"] == 15.8 and win["jobbank"]["level"] == "region"
    assert win["statcan"]["wage"] == 16.4 and win["statcan"]["area"] == "4650"


def test_a_table_under_the_threshold_shows_counts_only(conn, archive, tmp_path, monkeypatch):
    # The base seed's three cooks postings: 103's flag lapsed and it still counts, in September.
    o = page(conn, tmp_path, monkeypatch, "63200")["offered"]
    nat = o["national"]
    assert (nat["postings"], nat["hourly_n"], nat["min"], nat["max"]) == (3, 3, None, None)
    assert nat["months"] == [["2026-09", 1, 1, None], ["2026-10", 2, 2, None], ["2026-11", 0, 0, None], ["2026-12", 0, 0, None]]
    assert o["regions"] == []


def test_a_lapsed_flag_still_counts_and_an_unflagged_posting_does_not(conn, archive):
    model = places.build(conn)
    flagged = offered.flagged(conn)
    assert 205 in flagged and 103 in flagged
    assert 299 not in flagged
    winnipeg = model.offered.regional[FOOD]["4650"]
    assert 17.5 in winnipeg.mins and 99.0 not in winnipeg.mins


def test_no_archive_means_empty_tables(conn, tmp_path, monkeypatch):
    seed(conn)
    o = page(conn, tmp_path, monkeypatch, "63200")["offered"]
    # The base seed has postings but no nightly observations: nothing was seen flagged.
    assert o == {"threshold": 10, "since": None, "regions": [],
                 "national": {"postings": 0, "hourly_n": 0, "other": [], "unstated": 0, "min": None, "max": None, "months": []}}


def test_every_occupation_file_carries_the_block(conn, archive, tmp_path, monkeypatch):
    monkeypatch.setattr(places, "THRESHOLD", 3)
    places.write_places(conn, tmp_path)
    for path in (tmp_path / "occupations").glob("[0-9]*.json"):
        o = json.loads(path.read_text(encoding="utf-8"))["offered"]
        assert [m[0] for m in o["national"]["months"]] == MONTHS, path.name
    index = json.loads((tmp_path / "occupations" / "index.json").read_text(encoding="utf-8"))
    # The index is left as it was: it is the largest file the pages read.
    assert all(set(r) == {"noc", "title", "records", "approved", "positions", "refused", "pending", "latest_positions",
                          "indexed"} for r in index["rows"])


def test_quartiles_and_units():
    assert offered.quartiles([]) is None
    assert offered.quartiles([17.0]) == [17.0, 17.0, 17.0]
    # 1 2 3 4: ranks 0.75, 1.5 and 2.25 of 0..3.
    assert offered.quartiles([4.0, 1.0, 3.0, 2.0]) == [1.75, 2.5, 3.25]
    assert offered.unit_of(" weekly ") == "WEEK" and offered.unit_of("BIWEEKLY") == "BIWEEK"
    assert offered.unit_of("HOUR") == "HOUR" and offered.unit_of("YEAR") == "YEAR" and offered.unit_of("") is None
    assert offered.unit_of("FORTNIGHT") == "FORTNIGHT"


def test_unit_merging_agrees_with_the_parser():
    # Every code the list-page parser writes stays itself; the posting pages'
    # spellings fold onto it; each of the parser's compound units keeps its own count.
    for text in ("$17 hourly", "$45,000 annually", "$700 weekly", "$1,500 bi-weekly", "$2,000 semi-monthly",
                 "$3,000 monthly", "$150 daily"):
        code = parse_salary_text(text)[2]
        assert code is not None and offered.unit_of(code) == code, text
    assert offered.unit_of("BIWEEKLY") == offered.unit_of(parse_salary_text("$1,500 bi-weekly")[2]) == "BIWEEK"
    assert offered.unit_of("WEEKLY") == offered.unit_of(parse_salary_text("$700 weekly")[2]) == "WEEK"
    assert offered.unit_of("SEMIMONTHLY") == "SEMIMONTH" != offered.unit_of("MONTH")


def test_unusable_wages_count_as_unstated():
    cell = offered.Cell()
    cell.add("2026-10", "HOUR", None, None)
    cell.add("2026-10", None, 17.0, 17.0)
    cell.add("2026-10", "HOUR", 17.0, None)
    assert (cell.postings, cell.unstated, cell.mins, cell.maxes) == (3, 2, [17.0], [17.0])
    arch = offered.Archive()
    arch.add("65201", None, "2026-10-05T01:00:00Z", "HOUR", 0.0, None)
    arch.add("65201", None, "2026-10-05T01:00:00Z", "HOUR", math.inf, math.inf)
    arch.add("65201", None, "not a date", "HOUR", 17.0, 17.0)
    nat = arch.national["65201"]
    # A zero or infinite wage is no wage; a posting with no readable first-seen month is not counted at all.
    assert (nat.postings, nat.unstated, nat.mins) == (2, 2, [])


def test_months_cross_a_year_end():
    arch = offered.Archive("2026-11", "2027-02")
    assert arch.months() == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert offered.Archive().months() == []
