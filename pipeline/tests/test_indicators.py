from lmia_pipeline import indicators
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


def test_wage_and_unemployment_rules_are_placeholders(conn):
    low = upsert_employer(conn, "Low Wage Diner", "NS", source="esdc_positive", now=NOW)
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, stream, resource_id, row_hash) "
        "VALUES ('positive', '2026Q1', ?, 'x', 'Low Wage', 'r', 'h-low')", (low,))
    high = upsert_employer(conn, "Only High", "NS", source="jobbank", now=NOW)
    s_low, s_high = states_after(conn, low), states(conn, high)
    assert s_low["wage_at_floor"][0] == "not_evaluated"
    assert s_low["low_wage_high_unemployment"][0] == "not_evaluated"
    assert s_high["low_wage_high_unemployment"][0] == "not_applicable"


def test_only_changed_rows_are_rewritten(conn):
    eid = upsert_employer(conn, "Steady Co", "MB", source="jobbank", now=NOW)
    assert indicators.compute(conn, now=NOW) == 6
    assert indicators.compute(conn, now="2026-10-13T00:00:00Z") == 0
    assert conn.execute("SELECT DISTINCT computed_at FROM indicators").fetchone()[0] == NOW
