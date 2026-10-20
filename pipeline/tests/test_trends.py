"""The /trends series against figures worked out by hand from a small seed.

The seed has ESDC's three kinds of period (annual files for 2014 to 2016, the
2017 Q1 to Q2 file, quarterly files), a quarter with no negative file, rows
without a province, and a Job Bank history with a test sweep, a failed pass,
a skipped run, two passes ending on one day and a pass killed before it
logged.
"""

import json

from lmia_pipeline import export_static, releases, trends
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-18T00:00:00Z"
POSITIVE = ["2014", "2015", "2016", "2017Q1-Q2", "2024Q1", "2024Q2", "2025Q1", "2025Q2"]
NEGATIVE = ["2015", "2016", "2017Q1-Q2", "2024Q1", "2024Q2", "2025Q2"]


def add_resource(conn, dataset, period):
    rid = f"{dataset[:3]}-{period}"
    conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                 "loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1000, 1, ?)",
                 (rid, dataset, period, f"{period} {dataset}", f"https://example.invalid/{rid}.csv",
                  f"{period[:4]}-12-01", "ab" * 32, NOW))


def add_row(conn, lst, period, name, prov, stream, noc, positions, n=[0]):
    n[0] += 1
    eid = upsert_employer(conn, name, prov, source=f"esdc_{lst}", now=NOW)
    conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, noc_code, positions, "
                 "resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (lst, period, eid, name, prov, stream, noc, positions, f"{lst[:3]}-{period}", f"t{n[0]}"))


def seed_esdc(conn):
    for p in POSITIVE:
        add_resource(conn, "positive", p)
    for p in NEGATIVE:
        add_resource(conn, "negative", p)
    pos = lambda *a: add_row(conn, "positive", *a)  # noqa: E731
    neg = lambda *a: add_row(conn, "negative", *a)  # noqa: E731
    pos("2014", "Bravo Farms Ltd", "BC", None, None, 2)
    pos("2015", "Alpha Inc", "ON", None, None, 10)
    pos("2015", "Bravo Farms Ltd", "BC", None, None, 5)
    neg("2015", "Xray Ltd", "ON", None, None, 1)
    pos("2016", "Alpha Inc", "ON", None, "6711", 20)
    pos("2016", "Alpha Inc", "ON", None, "6322", 4)
    pos("2016", "Charlie Ltee", "QC", None, "6711", 6)
    neg("2016", "Xray Ltd", "ON", None, "6711", 1)
    neg("2016", "Yankee Ltd", "BC", None, "6711", 1)
    pos("2017Q1-Q2", "Alpha Inc", "ON", "Low Wage", "6711", 8)
    pos("2017Q1-Q2", "Delta Farms Ltd", "AB", "Primary Agriculture", "8611", 12)
    pos("2024Q1", "Alpha Inc", "ON", "Low Wage", "6711", 10)
    pos("2024Q1", "Delta Farms Ltd", "AB", "Primary Agriculture", "8611", 30)
    neg("2024Q1", "Xray Ltd", "ON", "Low Wage", "6711", 1)
    pos("2024Q2", "Delta Farms Ltd", "AB", "Primary Agriculture", "85101", 50)
    pos("2024Q2", "Echo Health Authority", "NS", "High Wage", "31301", 10)
    neg("2024Q2", "Xray Ltd", "ON", "Low Wage", "65201", 1)
    neg("2024Q2", "Zulu Clinic Inc", "NS", "High Wage", "31301", 1)
    pos("2025Q1", "Delta Farms Ltd", "AB", "Primary Agriculture", "85101", 20)
    pos("2025Q1", "Alpha Inc", "ON", "Low Wage", "65201", 5)
    pos("2025Q2", "Delta Farms Ltd", "AB", "Primary Agriculture", "85101", 30)
    pos("2025Q2", "Echo Health Authority", "NS", "High Wage", "31301", 15)
    pos("2025Q2", "Foxtrot Software Corp", None, "Global Talent", "21231", 3)
    neg("2025Q2", "Zulu Clinic Inc", "NS", "High Wage", "31301", 1)
    neg("2025Q2", "Xray Ltd", "ON", "Low Wage", "65201", 1)
    neg("2025Q2", "Whiskey Diner Ltd", "ON", "Low Wage", "65201", 1)
    conn.commit()


def series(conn):
    return trends._Series(releases._Data(conn))


def test_national_periods_years_and_markers(conn):
    seed_esdc(conn)
    n = trends.national(series(conn))
    first = n["periods"][0]
    # ESDC's 2014 file starts on June 20; every other period on its first quarter's first day.
    assert first == {"p": "2014", "start": "2014-06-20", "end": "2014-12-31", "quarters": 4,
                     "positions": 2, "rows": 1, "employers": 1, "refused": None}
    half = next(p for p in n["periods"] if p["p"] == "2017Q1-Q2")
    assert (half["start"], half["end"], half["quarters"]) == ("2017-01-01", "2017-06-30", 2)
    # A negative file with no rows is zero refusals; no negative file at all is no figure.
    assert half["refused"] == 0
    q = {p["p"]: p for p in n["periods"]}
    assert (q["2016"]["positions"], q["2016"]["rows"], q["2016"]["employers"], q["2016"]["refused"]) == (30, 3, 2, 2)
    assert q["2025Q1"]["refused"] is None and q["2025Q2"]["refused"] == 3
    assert n["latest"] == "2025Q2" and n["published"] == "2025-12-01"
    assert n["noc2021_from"] == "2024Q2" and n["streams_from"] == "2017Q1-Q2"

    years = {y["year"]: y for y in n["years"]}
    assert [y["year"] for y in n["years"]] == [2014, 2015, 2016, 2017, 2024, 2025]
    assert years[2014]["complete"] is False and years[2014]["start"] == "2014-06-20"
    assert years[2016]["complete"] is True and years[2016]["quarters"] == [1, 2, 3, 4]
    assert years[2017]["complete"] is False and years[2017]["quarters"] == [1, 2]
    # 2025: Q1 has no negative file, so the year has no refused total.
    assert (years[2025]["positions"], years[2025]["rows"], years[2025]["employers"], years[2025]["refused"]) == (73, 5, 4, None)
    assert (years[2024]["positions"], years[2024]["employers"], years[2024]["refused"]) == (100, 3, 3)


def test_year_over_year_arithmetic(conn):
    seed_esdc(conn)
    yoy = trends.year_over_year(series(conn))
    # 2025 Q2 against 2024 Q2: 48 positions on 3 rows (3 employers) against 60 on 2 (2 employers); refused 3 against 2.
    quarter = yoy["quarter"]
    assert (quarter["now"], quarter["then"]) == ("2025Q2", "2024Q2")
    assert quarter["metrics"]["positions"] == {"now": 48, "then": 60, "change": -12, "pct": -20.0}
    assert quarter["metrics"]["rows"] == {"now": 3, "then": 2, "change": 1, "pct": 50.0}
    assert quarter["metrics"]["employers"] == {"now": 3, "then": 2, "change": 1, "pct": 50.0}
    assert quarter["metrics"]["refused"] == {"now": 3, "then": 2, "change": 1, "pct": 50.0}
    # Year to date: Q1 and Q2 of 2025 (25 + 48) against the same of 2024 (40 + 60); four
    # distinct employers against three; no refused comparison, since 2025 Q1 has no negative file.
    ytd = yoy["ytd"]
    assert (ytd["year"], ytd["quarters"], ytd["now"], ytd["then"]) == (2025, 2, ["2025Q1", "2025Q2"], ["2024Q1", "2024Q2"])
    assert ytd["metrics"]["positions"] == {"now": 73, "then": 100, "change": -27, "pct": -27.0}
    assert ytd["metrics"]["employers"] == {"now": 4, "then": 3, "change": 1, "pct": 33.3}
    assert ytd["metrics"]["refused"] is None
    # The last two complete years are 2016 and 2015 (2017, 2024 and 2025 are partial here).
    year = yoy["year"]
    assert (year["now"], year["then"]) == (2016, 2015)
    assert year["metrics"]["positions"] == {"now": 30, "then": 15, "change": 15, "pct": 100.0}
    assert year["metrics"]["employers"] == {"now": 2, "then": 2, "change": 0, "pct": 0.0}
    assert year["metrics"]["refused"] == {"now": 2, "then": 1, "change": 1, "pct": 100.0}


def test_spans_never_split_a_file(conn):
    seed_esdc(conn)
    s = series(conn)
    assert s.span(2017, {1, 2}) == ["2017Q1-Q2"]
    # 2017 Q1 alone sits inside the half-year file, and no part of 2014 is whole.
    assert s.span(2017, {1}) is None
    assert s.span(2014, {1, 2, 3, 4}) is None
    assert s.span(2016, {1, 2}) is None
    assert trends.compare(5, 0) == {"now": 5, "then": 0, "change": 5, "pct": None}
    assert trends.compare(None, 4) is None


def test_streams_and_provinces(conn):
    seed_esdc(conn)
    s = series(conn)
    st = trends.streams(s)
    # 2014 to 2016 carry no stream, so the series starts with the 2017 Q1 to Q2 file.
    assert st["streams_from"] == "2017Q1-Q2" and [p["p"] for p in st["periods"]][0] == "2017Q1-Q2"
    assert st["noc2021_from"] == "2024Q2"
    assert "2016" not in [p["p"] for p in st["periods"]]
    # Ordered by positions over the series: 142, 25, 23, 3 ("Global Talent" is ESDC's older spelling).
    assert st["keys"] == ["Primary Agriculture", "High Wage", "Low Wage", "Global Talent Stream"]
    by = {p["p"]: p for p in st["periods"]}
    assert by["2017Q1-Q2"]["positions"] == [12, 0, 8, 0] and by["2017Q1-Q2"]["refused"] == [0, 0, 0, 0]
    assert by["2025Q2"]["positions"] == [30, 15, 0, 3] and by["2025Q2"]["refused"] == [0, 1, 2, 0]
    assert by["2025Q1"]["refused"] is None
    assert st["yoy"]["now"] == "2025Q2" and st["yoy"]["then"] == "2024Q2"
    assert st["yoy"]["rows"] == [
        {"k": "Primary Agriculture", "now": 30, "then": 50, "change": -20, "pct": -40.0},
        {"k": "High Wage", "now": 15, "then": 10, "change": 5, "pct": 50.0},
        {"k": "Low Wage", "now": 0, "then": 0, "change": 0, "pct": None},
        {"k": "Global Talent Stream", "now": 3, "then": 0, "change": 3, "pct": None},
    ]

    pr = trends.provinces(s)
    # AB 142, ON 57, NS 25, BC 7, QC 6; rows without a province (UN) always last.
    assert pr["keys"] == ["AB", "ON", "NS", "BC", "QC", "UN"]
    byp = {p["p"]: p for p in pr["periods"]}
    assert byp["2016"]["positions"] == [0, 24, 0, 0, 6, 0] and byp["2016"]["rows"] == [0, 2, 0, 0, 1, 0]
    assert byp["2024Q2"]["refused"] == [0, 1, 1, 0, 0, 0]
    assert byp["2014"]["refused"] is None
    assert pr["yoy"]["rows"][0] == {"k": "AB", "now": 30, "then": 50, "change": -20, "pct": -40.0}
    assert pr["yoy"]["rows"][-1] == {"k": "UN", "now": 3, "then": 0, "change": 3, "pct": None}


def log(conn, run_at, listed, ok=1, detail=None):
    conn.execute("INSERT INTO sources_log (run_at, source, detail, rows_in, rows_new, excluded, ok) VALUES (?, 'jobbank', ?, ?, 0, 0, ?)",
                 (run_at, detail or f"pages=1 listed={listed}", listed, ok))


def observe(conn, stamp, requested, approved=0, start=[1000]):
    for flag, count in (("requested", requested), ("approved", approved)):
        for _ in range(count):
            start[0] += 1
            conn.execute("INSERT INTO jobbank_observations (posting_id, observed_at, flag, facet) VALUES (?, ?, ?, ?)",
                         (start[0], stamp, flag, "101010" if flag == "requested" else "101020"))


def seed_jobbank(conn):
    # The live history to 2026-10-20: a test sweep, three complete passes, a skipped
    # run, and a pass the host cut short (ok = 0).
    observe(conn, "2026-10-13T03:21:29Z", 3, 1)
    log(conn, "2026-10-13T03:21:49Z", 50)
    observe(conn, "2026-10-17T22:16:16Z", 5, 2)
    log(conn, "2026-10-18T04:29:40Z", 6000)
    observe(conn, "2026-10-19T00:10:02Z", 4)
    log(conn, "2026-10-19T04:00:15Z", 5900)
    log(conn, "2026-10-19T04:29:14Z", 0, detail="skipped: last Job Bank pass was 4.3 h ago")
    observe(conn, "2026-10-20T00:14:27Z", 2)
    log(conn, "2026-10-20T00:50:01Z", 1500, ok=0, detail="pages=63 listed=1500 problems=requested page 63: timeout")
    observe(conn, "2026-10-20T01:27:49Z", 6)
    log(conn, "2026-10-20T02:24:47Z", 6100)
    conn.commit()


def test_complete_pass_rule(conn):
    seed_jobbank(conn)
    runs, complete = trends.complete_passes(conn)
    # The skipped row is no pass at all; the test sweep listed 50 against a median of 6,000.
    assert [(r["run_at"], r["complete"]) for r in runs] == [
        ("2026-10-13T03:21:49Z", False),
        ("2026-10-18T04:29:40Z", True),
        ("2026-10-19T04:00:15Z", True),
        ("2026-10-20T00:50:01Z", False),
        ("2026-10-20T02:24:47Z", True),
    ]
    assert len(complete) == 3
    # Approved-flag observations are not counted; each point is dated by the day the pass ended.
    assert trends.pending_series(conn) == [
        {"date": "2026-10-18", "n": 5}, {"date": "2026-10-19", "n": 4}, {"date": "2026-10-20", "n": 6},
    ]


def test_same_day_passes_and_a_killed_pass(conn):
    seed_jobbank(conn)
    observe(conn, "2026-11-01T01:00:00Z", 7)
    log(conn, "2026-11-01T03:00:00Z", 6000)
    observe(conn, "2026-11-01T22:00:00Z", 8)
    log(conn, "2026-11-01T23:00:00Z", 6050)
    # A pass killed before it logged leaves its stamp; the next pass's row is not its own.
    observe(conn, "2026-11-02T00:30:00Z", 2)
    observe(conn, "2026-11-02T05:00:00Z", 9)
    log(conn, "2026-11-02T06:00:00Z", 6020)
    conn.commit()
    points = trends.pending_series(conn)
    assert points[-2:] == [{"date": "2026-11-01", "n": 8}, {"date": "2026-11-02", "n": 9}]


def test_a_lone_pass_counts(conn):
    observe(conn, "2026-10-13T03:21:29Z", 3)
    log(conn, "2026-10-13T03:21:49Z", 50)
    conn.commit()
    assert trends.pending_series(conn) == [{"date": "2026-10-13", "n": 3}]


def test_export_writes_each_view_and_lists_it(conn, tmp_path):
    seed_esdc(conn)
    seed_jobbank(conn)
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    assert counts["trend_files"] == 4
    for name in ("national", "streams", "provinces", "pending"):
        path = out / "trends" / f"{name}.json"
        assert path.stat().st_size < 300_000
        json.loads(path.read_text(encoding="utf-8"))
    pending = json.loads((out / "trends" / "pending.json").read_text(encoding="utf-8"))
    assert pending["first"] == "2026-10-18" and pending["latest"] == "2026-10-20" and len(pending["points"]) == 3
    entries = dict(export_static.sitemap_entries(conn, "2026-10-20"))
    assert entries["/trends"] == "2025-12-01" and entries["/trends/streams"] == "2025-12-01"
    assert entries["/trends/provinces"] == "2025-12-01" and entries["/trends/pending"] == "2026-10-20"


def test_nothing_loaded_writes_nothing(conn, tmp_path):
    assert trends.write_all(conn, tmp_path) == {"trend_files": 0, "trend_bytes": 0}
    assert trends.sitemap_entries(conn) == []
