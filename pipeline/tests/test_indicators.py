from lmia_pipeline import indicators
from lmia_pipeline.sources import wages
from lmia_pipeline.db import upsert_employer

NOW = "2026-10-12T00:00:00Z"


def add_posting(conn, eid, pid, *, date_posted, first_seen, flag="requested"):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, date_posted, first_seen, last_seen, "
        "flag_current, flag_first, url, updated_at) VALUES (?, ?, 'x', ?, ?, ?, ?, ?, 'u', ?)",
        (pid, eid, date_posted, first_seen, first_seen, flag, flag, first_seen),
    )


def add_esdc(conn, eid, list_name, period, *, noc="63200", positions=1, resource="r", published=None):
    conn.execute(
        "INSERT OR IGNORE INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, "
        "rows_loaded, loaded_at) VALUES (?, ?, ?, 'n', 'u', ?, 's', 1, 1, ?)",
        (resource, list_name, period, published, NOW),
    )
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, stream, noc_code, lmias, positions, "
        "resource_id, row_hash) VALUES (?, ?, ?, 'x', 'High Wage', ?, 1, ?, ?, ?)",
        (list_name, period, eid, noc, positions, resource, f"{eid}-{list_name}-{period}-{noc}-{positions}-{resource}"),
    )


def states(conn, eid):
    return {r["indicator"]: (r["state"], r["basis"]) for r in
            conn.execute("SELECT indicator, state, basis FROM indicators WHERE employer_id = ?", (eid,))}


def test_newly_incorporated(conn):
    eid = upsert_employer(conn, "Fresh Co Ltd.", "BC", source="jobbank", now=NOW)
    add_posting(conn, eid, 1, date_posted="2026-10-08", first_seen=NOW)
    assert states_after(conn, eid)["newly_incorporated"][0] == "not_evaluated"
    conn.execute(
        "INSERT INTO registry_matches (employer_id, registry, registry_id, legal_name, registered_on, grade, checked_at) "
        "VALUES (?, 'bc_orgbook', 'BC1', 'FRESH CO LTD.', '2026-06-22', 'exact', ?)", (eid, NOW))
    state, basis = states_after(conn, eid)["newly_incorporated"]
    assert state == "triggered" and "108 days" in basis
    conn.execute("UPDATE registry_matches SET registered_on = '2018-09-04'")
    assert states_after(conn, eid)["newly_incorporated"][0] == "not_triggered"


def states_after(conn, eid):
    indicators.compute(conn, now=NOW)
    return states(conn, eid)


def test_repeat_applicant_needs_three_consecutive_quarters(conn):
    eid = upsert_employer(conn, "Repeat Farms", "ON", source="esdc_positive", now=NOW)
    add_esdc(conn, eid, "positive", "2025Q3", resource="a")
    add_esdc(conn, eid, "positive", "2025Q4", resource="b")
    assert states_after(conn, eid)["repeat_applicant"][0] == "not_triggered"
    add_esdc(conn, eid, "positive", "2026Q1", resource="c")
    state, basis = states_after(conn, eid)["repeat_applicant"]
    assert state == "triggered" and "2025Q3 to 2026Q1" in basis
    # A different occupation does not extend the run.
    other = upsert_employer(conn, "Mixed Jobs Inc", "ON", source="esdc_positive", now=NOW)
    add_esdc(conn, other, "positive", "2025Q3", noc="1", resource="a")
    add_esdc(conn, other, "positive", "2025Q4", noc="2", resource="b")
    add_esdc(conn, other, "positive", "2026Q1", noc="3", resource="c")
    assert states_after(conn, other)["repeat_applicant"][0] == "not_triggered"


def test_high_volume(conn):
    eid = upsert_employer(conn, "Big Berry", "BC", source="esdc_positive", now=NOW)
    add_esdc(conn, eid, "positive", "2026Q1", positions=760, resource="a")
    state, basis = states_after(conn, eid)["high_volume"]
    assert state == "triggered" and "760 positions" in basis
    small = upsert_employer(conn, "Small Shop", "BC", source="esdc_positive", now=NOW)
    add_esdc(conn, small, "positive", "2026Q1", positions=2, resource="a")
    assert states_after(conn, small)["high_volume"][0] == "not_triggered"
    none = upsert_employer(conn, "Nothing Yet", "BC", source="jobbank", now=NOW)
    assert states_after(conn, none)["high_volume"][0] == "not_applicable"


def test_refused_then_reposted(conn):
    eid = upsert_employer(conn, "Try Again Ltd", "AB", source="esdc_negative", now=NOW)
    add_esdc(conn, eid, "negative", "2026Q1", resource="neg", published="2026-07-21")
    assert states_after(conn, eid)["refused_then_reposted"][0] == "not_triggered"
    add_posting(conn, eid, 9, date_posted="2026-08-01", first_seen="2026-08-02T00:00:00Z")
    state, basis = states_after(conn, eid)["refused_then_reposted"]
    assert state == "triggered" and "2026-08-02" in basis


def test_without_reference_tables_the_new_rules_say_what_is_missing(conn):
    low = upsert_employer(conn, "Low Wage Diner", "NS", source="esdc_positive", now=NOW)
    add_low_wage(conn, low, "2026Q1", "B3H 1A1")
    add_posting(conn, low, 7, date_posted="2026-10-01", first_seen=NOW)
    high = upsert_employer(conn, "Only High", "NS", source="esdc_positive", now=NOW)
    s_low, s_high = states_after(conn, low), states(conn, high)
    assert s_low["wage_at_floor"] == ("not_evaluated", "Prevailing wage table not yet loaded.")
    assert s_low["low_wage_high_unemployment"] == ("not_evaluated", "Regional unemployment table not yet loaded.")
    assert s_high["wage_at_floor"] == ("not_applicable", "No Job Bank posting.")
    assert s_high["low_wage_high_unemployment"] == ("not_applicable", "No low-wage stream records.")


# -- wage at the prevailing-wage floor -----------------------------------------

def setup_regions(conn):
    conn.executemany(
        "INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) VALUES (?, ?, ?, ?, ?, 0, 0, 'centroid')",
        [("R2H", "4650", "Winnipeg", "602", "Winnipeg"), ("R0G", "4620", "South Central", None, None),
         ("B3H", "1250", "Halifax", "205", "Halifax")],
    )


def load_wage_fixture(conn, fixtures):
    wages.load_table(conn, {"id": "w2025", "name": "2025 Wages", "url": "u", "created": "2025-11-19"},
                     (fixtures / "wages_trim.csv").read_bytes(), now=NOW)


def add_priced_posting(conn, eid, pid, noc, wage, unit="HOUR", postal="R2H 1A1", date_posted="2026-09-01"):
    add_posting(conn, eid, pid, date_posted=date_posted, first_seen=NOW)
    conn.execute("UPDATE jobbank_postings SET noc_code = ?, wage_min = ?, wage_max = ?, wage_unit = ?, postal_code = ? "
                 "WHERE posting_id = ?", (noc, wage, wage, unit, postal, pid))


def wage_state(conn, eid):
    return states_after(conn, eid)["wage_at_floor"]


def test_wage_at_floor_triggered_and_not(conn, fixtures):
    setup_regions(conn)
    load_wage_fixture(conn, fixtures)
    at = upsert_employer(conn, "Floor Care", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, at, 101, "44101", 17.10)
    assert wage_state(conn, at) == ("triggered", (
        "Posting 101: posted minimum $17.10/h is within 1 percent of the Job Bank median $16.95/h for NOC 44101 "
        "in the Winnipeg economic region (Manitoba), wage table dated 2025-11-19."))
    above = upsert_employer(conn, "Above Care", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, above, 102, "44101", 19.00)
    add_priced_posting(conn, above, 103, "44101", 21.00)
    assert wage_state(conn, above) == ("not_triggered", (
        "Closest of 2 posting(s) compared: posting 102, posted minimum $19.00/h against the Job Bank median "
        "$16.95/h for NOC 44101 in the Winnipeg economic region (Manitoba), wage table dated 2025-11-19."))
    # Below the median by more than 1 percent is not "at the floor" either.
    below = upsert_employer(conn, "Under Care", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, below, 104, "44101", 16.00)
    assert wage_state(conn, below)[0] == "not_triggered"


def test_wage_at_floor_falls_back_to_province_then_canada(conn, fixtures):
    setup_regions(conn)
    load_wage_fixture(conn, fixtures)
    prov = upsert_employer(conn, "Lab One", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, prov, 201, "22101", 31.00)
    assert wage_state(conn, prov) == ("triggered", (
        "Posting 201: posted minimum $31.00/h is within 1 percent of the Job Bank median $31.00/h for NOC 22101 "
        "in Manitoba (provincial figure), wage table dated 2025-11-19."))
    nat = upsert_employer(conn, "Lab Two", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, nat, 202, "21103", 60.00)
    state, basis = wage_state(conn, nat)
    assert state == "not_triggered" and "$53.94/h for NOC 21103 in Canada (national figure)" in basis


def test_wage_at_floor_compares_annual_wages_as_published(conn, fixtures):
    setup_regions(conn)
    load_wage_fixture(conn, fixtures)
    eid = upsert_employer(conn, "Council Office", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, eid, 301, "00010", 99000, unit="YEAR")
    assert wage_state(conn, eid) == ("triggered", (
        "Posting 301: posted minimum $99,000/yr is within 1 percent of the Job Bank median $99,000/yr for NOC 00010 "
        "in the Winnipeg economic region (Manitoba), wage table dated 2025-11-19."))
    hourly = upsert_employer(conn, "Council Hourly", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, hourly, 302, "00010", 48.0)
    assert wage_state(conn, hourly) == (
        "not_evaluated", "No posted wage matches the hourly or yearly unit of the Job Bank median.")


def test_wage_at_floor_not_evaluated_reasons(conn, fixtures):
    setup_regions(conn)
    load_wage_fixture(conn, fixtures)
    no_noc = upsert_employer(conn, "List Only", "MB", source="jobbank", now=NOW)
    add_posting(conn, no_noc, 401, date_posted="2026-09-01", first_seen=NOW)
    assert wage_state(conn, no_noc) == (
        "not_evaluated", "No posting page parsed yet, so the occupation is unknown.")
    nowhere = upsert_employer(conn, "No Postal", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, nowhere, 402, "44101", 17.0, postal=None)
    assert wage_state(conn, nowhere) == (
        "not_evaluated", "No posting has a postal code that places it in an economic region.")
    # A postal code inside the city text still places the posting.
    conn.execute("UPDATE jobbank_postings SET city = '5110 Main St Winnipeg, MB R2H 1A1' WHERE posting_id = 402")
    assert wage_state(conn, nowhere)[0] == "triggered"
    unknown = upsert_employer(conn, "Odd Job", "MB", source="jobbank", now=NOW)
    add_priced_posting(conn, unknown, 403, "99999", 20.0)
    assert wage_state(conn, unknown) == ("not_evaluated", "No Job Bank median for NOC 99999.")


def test_wage_table_in_force_on_the_posting_date():
    tables = indicators.WageTables([("t2024", "2024-12-03"), ("t2025", "2025-11-19")], {})
    assert tables.in_force("2025-06-01") == ("t2024", "2024-12-03")
    assert tables.in_force("2025-11-19") == ("t2025", "2025-11-19")
    # Older than every loaded table: the oldest one, named in the basis.
    assert tables.in_force("2023-01-01") == ("t2024", "2024-12-03")


# -- low-wage stream in a high-unemployment area -------------------------------

def add_low_wage(conn, eid, period, postal, list_name="positive"):
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, stream, postal_code, noc_code, "
        "resource_id, row_hash) VALUES (?, ?, ?, 'x', 'Low Wage', ?, '63200', 'r', ?)",
        (list_name, period, eid, postal, f"{eid}-{list_name}-{period}-{postal}"),
    )


def add_rates(conn, rates):
    conn.executemany(
        "INSERT INTO lfs_unemployment (cma_uid, ref_month, rate, cma_name) VALUES (?, ?, ?, ?)",
        [(uid, month, rate, name) for uid, name, month, rate in rates],
    )


def low_state(conn, eid):
    return states_after(conn, eid)["low_wage_high_unemployment"]


def test_low_wage_in_a_high_unemployment_cma(conn):
    setup_regions(conn)
    add_rates(conn, [("602", "Winnipeg", "2025-03", 5.8), ("602", "Winnipeg", "2025-06", 6.4),
                     ("602", "Winnipeg", "2025-09", 6.6), ("205", "Halifax", "2025-06", 5.5),
                     ("205", "Halifax", "2025-09", 5.7)])
    hit = upsert_employer(conn, "Busy Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, hit, "2025Q4", "R2H 2B2")
    assert low_state(conn, hit) == ("triggered", (
        "Low Wage stream approval in 2025Q4; the Winnipeg CMA unemployment rate was 6.4 percent for the three months "
        "ending 2025-06 and 6.6 percent for the three months ending 2025-09 (Statistics Canada LFS)."))
    # In 2025Q3 the earlier window (ending 2025-03) was below 6 percent.
    edge = upsert_employer(conn, "Edge Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, edge, "2025Q3", "R2H 2B2")
    assert low_state(conn, edge) == ("not_triggered", (
        "1 low-wage positive-list row(s) from 2025Q1 on; none in a census metropolitan area at or above 6 percent "
        "in both three-month periods checked."))
    rural = upsert_employer(conn, "Farm Kitchen", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, rural, "2025Q4", "R0G 1A0")
    add_low_wage(conn, rural, "2025Q4", "B3H 4R2")
    assert low_state(conn, rural)[0] == "not_triggered"
    assert low_state(conn, rural)[1].startswith("2 low-wage positive-list row(s)")


def test_low_wage_scope_and_missing_inputs(conn):
    setup_regions(conn)
    add_rates(conn, [("602", "Winnipeg", "2025-06", 6.4), ("602", "Winnipeg", "2025-09", 6.6)])
    old = upsert_employer(conn, "Old Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, old, "2024Q3", "R2H 2B2")
    add_low_wage(conn, old, "2026Q1", "R2H 2B2", list_name="negative")
    assert low_state(conn, old) == ("not_applicable", "No low-wage approvals from 2025Q1 on.")
    unplaced = upsert_employer(conn, "Lost Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, unplaced, "2025Q4", None)
    add_low_wage(conn, unplaced, "2025Q4", "X9X 9X9")
    assert low_state(conn, unplaced) == (
        "not_evaluated", "The low-wage approvals could not be placed in an area with a published unemployment rate.")
    # A quarter whose rates are not loaded cannot be judged either.
    later = upsert_employer(conn, "Late Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, later, "2026Q1", "R2H 2B2")
    assert low_state(conn, later)[0] == "not_evaluated"


def test_reference_month_is_the_window_in_force_when_the_quarter_began():
    assert indicators._reference_month(2026, 1) == "2025-12"
    assert indicators._reference_month(2026, 4) == "2026-09"
    assert indicators._reference_month(2025, 2) == "2025-03"


def test_only_changed_rows_are_rewritten(conn):
    eid = upsert_employer(conn, "Steady Co", "MB", source="jobbank", now=NOW)
    assert indicators.compute(conn, now=NOW) == 6
    assert indicators.compute(conn, now="2026-10-13T00:00:00Z") == 0
    assert conn.execute("SELECT DISTINCT computed_at FROM indicators").fetchone()[0] == NOW


# -- the two bases of the low-wage rule: ESDC's published lists, the LFS reconstruction --

def load_lists(conn, fixtures):
    """Store the three lists on the refusal page of 2026-10-09 (in force from
    2026-04-10, 2026-07-10 and 2026-10-09), as the program_cma stage does."""
    from lmia_pipeline.sources import program
    page = program.parse_cma_refusal((fixtures / "program_refusal_en.html").read_text(encoding="utf-8"))
    program.store(conn, program.CMA, page, source_url=program.SOURCES[program.CMA].url, now=NOW)


def setup_toronto(conn):
    conn.execute("INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) "
                 "VALUES ('M5V', '3530', 'Toronto', '535', 'Toronto', 0, 0, 'centroid')")


def test_a_published_list_carries_the_window_the_reconstruction_reads():
    assert indicators.window_month("2026-10-09") == "2026-09"
    assert indicators.window_month("2027-01-08") == "2026-12"
    assert indicators.window_month("2026-04-10") == indicators._reference_month(2026, 2)
    assert indicators.window_month("not a date") is None


def test_each_quarter_has_one_basis(conn, fixtures):
    assert all(b["basis"] == "lfs" for b in indicators.quarter_bases({}, (2026, 1)))
    load_lists(conn, fixtures)
    bases = indicators.quarter_bases(indicators.load_cma_lists(conn), (2026, 4))
    assert [b["quarter"] for b in bases][:2] == ["2025Q1", "2025Q2"]
    assert {b["quarter"]: b["basis"] for b in bases}["2026Q2"] == "lfs"  # the list of 2026-01 is not stored
    assert [b for b in bases if b["basis"] == "lists"] == [
        {"quarter": "2026Q3", "basis": "lists", "lists": ["2026-04-10", "2026-07-10"]},
        {"quarter": "2026Q4", "basis": "lists", "lists": ["2026-07-10", "2026-10-09"]},
    ]


def test_low_wage_reads_the_published_lists_where_they_are_stored(conn, fixtures):
    setup_regions(conn)
    setup_toronto(conn)
    # LFS figures that disagree with the lists on purpose: Winnipeg at 6.5 in
    # both windows of 2026 Q3, where the lists of 2026-04-10 and 2026-07-10
    # give 6.0 and 5.6.
    add_rates(conn, [("602", "Winnipeg", "2026-03", 6.5), ("602", "Winnipeg", "2026-06", 6.5),
                     ("602", "Winnipeg", "2025-06", 6.4), ("602", "Winnipeg", "2025-09", 6.6)])
    grill = upsert_employer(conn, "Lists Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, grill, "2026Q3", "R2H 2B2")
    # Without the lists the quarter is judged on the LFS table.
    assert low_state(conn, grill) == ("triggered", (
        "Low Wage stream approval in 2026Q3; the Winnipeg CMA unemployment rate was 6.5 percent for the three months "
        "ending 2026-03 and 6.5 percent for the three months ending 2026-06 (Statistics Canada LFS)."))
    load_lists(conn, fixtures)
    assert low_state(conn, grill) == ("not_triggered", (
        "1 low-wage positive-list row(s) from 2025Q1 on; none in a census metropolitan area at or above 6 percent "
        "in both periods checked: 1 against ESDC's published refusal-to-process lists, 0 against Statistics Canada "
        "LFS rates."))
    # Toronto was at or above 6 percent on both lists that could have applied.
    cafe = upsert_employer(conn, "Lists Cafe", "ON", source="esdc_positive", now=NOW)
    add_low_wage(conn, cafe, "2026Q3", "M5V 2T6")
    assert low_state(conn, cafe) == ("triggered", (
        "Low Wage stream approval in 2026Q3; ESDC's refusal-to-process lists gave the Toronto CMA 7.9 percent from "
        "2026-04-10 and 7.3 percent from 2026-07-10."))


def test_earlier_quarters_keep_the_reconstruction(conn, fixtures):
    setup_regions(conn)
    add_rates(conn, [("602", "Winnipeg", "2025-06", 6.4), ("602", "Winnipeg", "2025-09", 6.6),
                     ("602", "Winnipeg", "2025-12", 5.7), ("602", "Winnipeg", "2026-03", 6.0)])
    load_lists(conn, fixtures)
    early = upsert_employer(conn, "Early Grill", "MB", source="esdc_positive", now=NOW)
    add_low_wage(conn, early, "2025Q4", "R2H 2B2")
    # 2025 Q4 is before the stored lists, so the sentence is the LFS one, unchanged from rules 0.2.
    assert low_state(conn, early) == ("triggered", (
        "Low Wage stream approval in 2025Q4; the Winnipeg CMA unemployment rate was 6.4 percent for the three months "
        "ending 2025-06 and 6.6 percent for the three months ending 2025-09 (Statistics Canada LFS)."))
    # One row on each basis: Winnipeg in 2026 Q2 (the list of 2026-01 is not
    # stored, so the LFS table: 5.7 and 6.0) and Halifax in 2026 Q4 (the lists
    # of 2026-07-10 and 2026-10-09: 5.9 and 6.1).
    mixed = upsert_employer(conn, "Mixed Diner", "NS", source="esdc_positive", now=NOW)
    add_low_wage(conn, mixed, "2026Q2", "R2H 2B2")
    add_low_wage(conn, mixed, "2026Q4", "B3H 4R2")
    assert low_state(conn, mixed) == ("not_triggered", (
        "2 low-wage positive-list row(s) from 2025Q1 on; none in a census metropolitan area at or above 6 percent "
        "in both periods checked: 1 against ESDC's published refusal-to-process lists, 1 against Statistics Canada "
        "LFS rates."))


def test_with_lists_but_no_lfs_table_the_covered_quarters_are_still_judged(conn, fixtures):
    setup_regions(conn)
    setup_toronto(conn)
    load_lists(conn, fixtures)
    late = upsert_employer(conn, "Late Lists", "ON", source="esdc_positive", now=NOW)
    add_low_wage(conn, late, "2026Q4", "M5V 2T6")
    assert low_state(conn, late)[0] == "triggered"
    early = upsert_employer(conn, "Early Lists", "ON", source="esdc_positive", now=NOW)
    add_low_wage(conn, early, "2025Q4", "M5V 2T6")
    assert low_state(conn, early) == (
        "not_evaluated", "The low-wage approvals could not be placed in an area with a published unemployment rate.")


def test_an_area_a_list_leaves_out_is_not_at_the_threshold(conn, fixtures):
    setup_regions(conn)
    conn.execute("INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) "
                 "VALUES ('Y1A', '6010', 'Yukon', '999', 'Nowhere', 0, 0, 'centroid')")
    load_lists(conn, fixtures)
    eid = upsert_employer(conn, "North Diner", "YT", source="esdc_positive", now=NOW)
    add_low_wage(conn, eid, "2026Q3", "Y1A 1A1")
    assert low_state(conn, eid)[0] == "not_triggered"
