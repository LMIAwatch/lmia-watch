from lmia_pipeline import status
from lmia_pipeline.db import get_meta, upsert_employer

NOW = "2026-10-12T00:00:00Z"


def add_posting(conn, eid, pid, *, flag="requested", flag_first="requested", date_posted="2026-10-08",
                approved_seen_at=None, valid_through=None):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, date_posted, first_seen, last_seen, "
        "flag_current, flag_first, approved_seen_at, valid_through, url, updated_at) "
        "VALUES (?, ?, 'Raw Name', ?, ?, ?, ?, ?, ?, ?, 'u', ?)",
        (pid, eid, date_posted, NOW, NOW, flag, flag_first, approved_seen_at, valid_through, NOW),
    )


def add_resource(conn, rid, period, published, dataset="positive"):
    conn.execute(
        "INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
        "loaded_at) VALUES (?, ?, ?, 'n', 'u', ?, 's', 1, 1, ?)", (rid, dataset, period, published, NOW))


def add_record(conn, eid, list_name, period, rid, *, lmias=1, positions=4):
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, stream, lmias, positions, resource_id, "
        "row_hash) VALUES (?, ?, ?, 'List Name', 'High Wage', ?, ?, ?, ?)",
        (list_name, period, eid, lmias, positions, rid, f"{eid}{list_name}{period}{rid}"))


def current(conn, eid):
    return conn.execute("SELECT * FROM employers WHERE id = ?", (eid,)).fetchone()


def test_lifecycle_transitions(conn):
    eid = upsert_employer(conn, "Cycle Co", "BC", source="jobbank", now=NOW)
    status.recompute(conn, now=NOW)
    assert current(conn, eid)["current_status"] == "none"

    add_posting(conn, eid, 1, valid_through="2026-10-22")
    status.recompute(conn, now=NOW)
    row = current(conn, eid)
    assert row["current_status"] == "pending" and row["pending_count"] == 1
    assert row["status_changed_at"] == NOW and row["display_name"] == "Raw Name"

    conn.execute("UPDATE jobbank_postings SET flag_current = 'approved', approved_seen_at = ?", ("2026-10-20T00:00:00Z",))
    status.recompute(conn, now="2026-10-20T00:00:00Z")
    assert current(conn, eid)["current_status"] == "approved"

    # Gone without a decision: lapsed only once two positive lists were published after the posting closed.
    conn.execute("UPDATE jobbank_postings SET flag_current = 'gone', approved_seen_at = NULL")
    status.recompute(conn, now="2027-06-01T00:00:00Z")
    assert current(conn, eid)["current_status"] == "none"
    add_resource(conn, "r1", "2026Q4", "2027-01-20")
    status.recompute(conn, now="2027-06-01T00:00:00Z")
    assert current(conn, eid)["current_status"] == "none"
    add_resource(conn, "r2", "2027Q1", "2027-04-20")
    status.recompute(conn, now="2027-06-01T00:00:00Z")
    assert current(conn, eid)["current_status"] == "lapsed"

    # A later refusal in a list outranks the lapse because it is the newer event.
    add_resource(conn, "n1", "2027Q1", "2027-04-20", dataset="negative")
    add_record(conn, eid, "negative", "2027Q1", "n1")
    status.recompute(conn, now="2027-06-01T00:00:00Z")
    row = current(conn, eid)
    assert row["current_status"] == "refused" and row["refused_positions"] == 4


def test_rollups_and_meta(conn):
    a = upsert_employer(conn, "Alpha Farms", "ON", source="esdc_positive", now=NOW)
    b = upsert_employer(conn, "Beta Inn", "NS", source="esdc_negative", now=NOW)
    add_resource(conn, "p", "2026Q1", "2026-07-21")
    add_resource(conn, "n", "2026Q1", "2026-07-21", dataset="negative")
    add_record(conn, a, "positive", "2026Q1", "p", lmias=19, positions=760)
    add_record(conn, b, "negative", "2026Q1", "n", lmias=1, positions=3)
    add_posting(conn, b, 5)
    conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
                 "VALUES (?, 'high_volume', 'triggered', 'b', '0.1', ?)", (a, NOW))
    status.recompute(conn, now=NOW)
    ra, rb = current(conn, a), current(conn, b)
    assert (ra["current_status"], ra["approved_lmias"], ra["approved_positions"], ra["indicator_count"]) == (
        "approved", 19, 760, 1)
    assert (ra["first_seen"], ra["last_seen"]) == ("2026-01-01", "2026-03-31")
    assert (rb["current_status"], rb["pending_count"], rb["refused_lmias"]) == ("pending", 1, 1)
    assert get_meta(conn, "esdc_latest_period") == "2026Q1"
    assert get_meta(conn, "esdc_latest_published") == "2026-07-21"
    assert get_meta(conn, "count_pending") == "1"
    assert get_meta(conn, "count_approved_records") == "1"
    assert get_meta(conn, "count_approved_positions") == "760"
    assert get_meta(conn, "count_refused_records") == "1"
    assert get_meta(conn, "rules_version") == "0.2"
