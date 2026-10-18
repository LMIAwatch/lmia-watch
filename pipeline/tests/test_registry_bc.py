import json
from urllib.parse import urlencode

from lmia_pipeline import config
from lmia_pipeline.db import upsert_employer
from lmia_pipeline.sources import registry_bc

NOW = "2026-10-17T00:00:00Z"


def url(name: str) -> str:
    return f"{config.ORGBOOK_SEARCH}?{urlencode({'q': name, 'inactive': 'false'})}"


def topic(source_id: str, *names: str) -> dict:
    return {
        "source_id": source_id,
        "names": [{"text": n} for n in names],
        "attributes": [
            {"type": "entity_type", "value": "BC"},
            {"type": "entity_status", "value": "ACT"},
            {"type": "registration_date", "value": "2004-08-26T00:00:00+00:00"},
        ],
    }


def payload(*results: dict) -> bytes:
    return json.dumps({"results": list(results)}).encode("utf-8")


def seed(conn):
    """One BC employer per priority tier, plus two that must not be looked up."""
    ids = {}
    ids["rest"] = upsert_employer(conn, "Quiet Orchard Ltd.", "BC", source="esdc_positive", now=NOW)
    ids["finding"] = upsert_employer(conn, "Harbour Cafe Ltd.", "BC", source="ircc", now=NOW)
    ids["latest"] = upsert_employer(conn, "Fraser Packers Ltd.", "BC", source="esdc_positive", now=NOW)
    ids["pending"] = upsert_employer(conn, "0704250 BC Ltd. o/a Assi Supermarket", "BC", source="jobbank", now=NOW)
    ids["recent"] = upsert_employer(conn, "Checked Lately Ltd.", "BC", source="esdc_positive", now=NOW)
    ids["stale"] = upsert_employer(conn, "Checked Long Ago Ltd.", "BC", source="esdc_positive", now=NOW)
    ids["ontario"] = upsert_employer(conn, "Fraser Packers Ltd.", "ON", source="esdc_positive", now=NOW)
    for period, rid in (("2025Q4", "r1"), ("2026Q1", "r2")):
        conn.execute(
            "INSERT INTO esdc_resources (resource_id, dataset, period, name, url, sha256, bytes, rows_loaded, loaded_at) "
            "VALUES (?, 'positive', ?, ?, 'u', 's', 1, 1, ?)", (rid, period, period, NOW))
    for n, (key, period) in enumerate((("latest", "2026Q1"), ("rest", "2025Q4"), ("ontario", "2026Q1"))):
        conn.execute(
            "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, resource_id, row_hash) "
            "VALUES ('positive', ?, ?, 'x', 'BC', 'r', ?)", (period, ids[key], f"h{n}"))
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, "
        "flag_first, url, updated_at) VALUES (1, ?, '0704250 BC Ltd. o/a Assi Supermarket', ?, ?, 'requested', "
        "'requested', 'u', ?)", (ids["pending"], NOW, NOW, NOW))
    conn.execute(
        "INSERT INTO findings (employer_id, operating_name, legal_name, row_hash, fetched_at) "
        "VALUES (?, 'Harbour Cafe', 'Harbour Cafe Ltd.', 'f1', ?)", (ids["finding"], NOW))
    conn.execute("INSERT INTO registry_checks VALUES (?, 'bc_orgbook', '2026-09-01T00:00:00Z')", (ids["recent"],))
    conn.execute("INSERT INTO registry_checks VALUES (?, 'bc_orgbook', '2026-03-01T00:00:00Z')", (ids["stale"],))
    conn.commit()
    return ids


def test_candidates_come_in_priority_order(conn):
    ids = seed(conn)
    rows = registry_bc.candidates(conn, budget=10, cutoff_iso="2026-04-20T00:00:00Z")
    order = [r["id"] for r in rows]
    assert order[:3] == [ids["pending"], ids["latest"], ids["finding"]]
    assert set(order[3:]) == {ids["rest"], ids["stale"]}
    # A check inside 180 days is skipped; Ontario employers are never looked up.
    assert ids["recent"] not in order and ids["ontario"] not in order
    assert [r["tier"] for r in rows] == [0, 1, 2, 3, 3]


def test_run_queries_the_legal_name_and_grades_dotted_names_exact(conn, fake_client):
    ids = seed(conn)
    client = fake_client({url("0704250 BC Ltd."): payload(topic("BC0704250", "0704250 B.C. LTD."))})
    assert registry_bc.run(conn, client, budget=1, now=NOW) == 1
    asked = [u for u, _ in client.fake_session.calls]
    assert asked == [url("0704250 BC Ltd.")]
    row = conn.execute("SELECT * FROM registry_matches WHERE employer_id = ?", (ids["pending"],)).fetchone()
    assert row["registry_id"] == "BC0704250" and row["grade"] == "exact" and row["status"] == "ACT"
    assert row["registered_on"] == "2004-08-26"
    # The budget held: one lookup, one check recorded.
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE checked_at = ?", (NOW,)).fetchone()[0] == 1


def empty_answers(conn) -> dict[str, bytes]:
    """No match for anyone: a lookup that finds nothing still counts as a check."""
    names = [r[0] for r in conn.execute("SELECT display_name FROM employers")]
    return {url(registry_bc.split_trade_name(n)[0]): payload() for n in names}


def test_run_stops_at_the_time_cap(conn, fake_client):
    seed(conn)
    ticks = iter(range(0, 10_000, 1000))
    client = fake_client(empty_answers(conn))
    registry_bc.run(conn, client, budget=10, max_seconds=2500, now=NOW, clock=lambda: next(ticks))
    # The clock reads 0 at the start, then 1000, 2000 and 3000 before each lookup.
    assert len(client.fake_session.calls) == 2


def test_failed_lookup_is_not_a_check(conn, fake_client):
    seed(conn)
    client = fake_client({})
    registry_bc.run(conn, client, budget=100, now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE checked_at = ?", (NOW,)).fetchone()[0] == 0


def test_recheck_waits_180_days(conn, fake_client):
    seed(conn)
    client = fake_client(empty_answers(conn))
    registry_bc.run(conn, client, budget=100, now=NOW)
    first = len(client.fake_session.calls)
    registry_bc.run(conn, client, budget=100, now="2027-02-20T00:00:00Z")
    assert len(client.fake_session.calls) == first
    registry_bc.run(conn, client, budget=100, now="2027-05-01T00:00:00Z")
    assert len(client.fake_session.calls) > first


def test_defaults_fit_fifteen_minutes():
    assert registry_bc.RECHECK_DAYS == 180
    assert registry_bc.MAX_SECONDS == 900
    # One request a second plus about 0.3 s of response time.
    assert registry_bc.DEFAULT_BUDGET * 1.3 <= registry_bc.MAX_SECONDS * 1.02
