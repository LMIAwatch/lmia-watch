import json

from lmia_pipeline import config
from lmia_pipeline.db import get_meta
from lmia_pipeline.sources import wages

NOW = "2026-10-17T00:00:00Z"
LISTING = config.CKAN_PACKAGE_SHOW.format(dataset=wages.DATASET)


def resource(rid: str, created: str, url: str | None = None) -> dict:
    return {"id": rid, "name": f"{created[:4]} Wages", "created": created, "url": url or f"https://example.test/{rid}.csv"}


def test_parse_keeps_rows_with_a_median(fixtures):
    rows, revision = wages.parse_wages((fixtures / "wages_trim.csv").read_bytes())
    assert revision == "2025-11-19"
    by_key = {(r[0], r[1]): r for r in rows}
    noc, area, province, name, median, low, high, annual, reference = by_key[("44101", "4650")]
    assert (province, name, median, low, high, annual, reference) == ("MB", "Winnipeg", 16.95, 16.0, 22.5, 0, "2023-2024")
    assert by_key[("44101", "46")][4] == 17.75
    assert by_key[("44101", "00")][2] is None  # Canada has no province
    assert by_key[("00010", "00")][7] == 1  # published at an annual rate
    # Avalon Peninsula has no published median for legislators: not stored.
    assert ("00010", "1010") not in by_key
    assert ("22101", "4650") not in by_key and ("22101", "46") in by_key


def test_run_loads_the_newest_two_tables_once(conn, fake_client, fixtures):
    data = (fixtures / "wages_trim.csv").read_bytes()
    listing = {"result": {"resources": [
        resource("old", "2023-11-29T00:00:00"),
        resource("new", "2025-11-19T15:21:11"),
        resource("mid", "2024-12-02T16:50:35"),
        {"id": "pdf", "created": "2026-01-01", "url": "https://example.test/guide.pdf"},
    ]}}
    client = fake_client({
        LISTING: json.dumps(listing).encode(),
        "https://example.test/new.csv": data,
        "https://example.test/mid.csv": data,
        "https://example.test/old.csv": data,
    })
    loaded = wages.run(conn, client, now=NOW)
    tables = {r["resource_id"]: r for r in conn.execute("SELECT * FROM wage_tables")}
    assert set(tables) == {"new", "mid"}
    assert tables["new"]["revision_date"] == "2025-11-19" and tables["new"]["name"] == "2025 Wages"
    assert loaded == 2 * tables["new"]["rows_loaded"] > 0
    called = [url for url, _ in client.fake_session.calls]
    assert "https://example.test/old.csv" not in called
    # Within 30 days nothing is requested at all; the check date lives in the database.
    calls_before = len(client.fake_session.calls)
    assert wages.run(conn, client, now="2026-11-10T00:00:00Z") == 0
    assert len(client.fake_session.calls) == calls_before
    log = conn.execute("SELECT detail, ok FROM sources_log WHERE source = 'wages' ORDER BY id DESC").fetchone()
    assert log["ok"] == 1 and log["detail"].startswith("skipped") and "tables=2" in log["detail"]
    # After 30 days the listing is read again; unchanged resources are not downloaded.
    client.fake_session.mapping["https://example.test/new.csv"] = b"would fail to parse"
    assert wages.run(conn, client, now="2026-11-20T00:00:00Z") == 0
    assert get_meta(conn, "wages_checked_at") == "2026-11-20T00:00:00Z"
    # A resource whose modified date changed is fetched and reloaded.
    client.fake_session.mapping["https://example.test/new.csv"] = data
    listing["result"]["resources"][1]["last_modified"] = "2026-01-05T00:00:00"
    client.forget(LISTING)
    client.fake_session.mapping[LISTING] = json.dumps(listing).encode()
    client.forget("https://example.test/new.csv")
    wages.run(conn, client, now="2026-12-25T00:00:00Z")
    assert conn.execute("SELECT source_modified FROM wage_tables WHERE resource_id = 'new'").fetchone()[0] == "2026-01-05T00:00:00"


def test_a_newer_year_replaces_the_oldest(conn, fake_client, fixtures):
    data = (fixtures / "wages_trim.csv").read_bytes()
    conn.execute(
        "INSERT INTO wage_tables (resource_id, name, url, revision_date, sha256, bytes, rows_loaded, loaded_at) "
        "VALUES ('gone', '2023 Wages', 'u', '2023-12-08', 's', 1, 1, ?)", (NOW,))
    conn.execute(
        "INSERT INTO jobbank_wages (resource_id, noc_code, area_code, province, area_name, median, annual) "
        "VALUES ('gone', '44101', '4650', 'MB', 'Winnipeg', 15.0, 0)")
    listing = {"result": {"resources": [resource("a", "2024-12-02"), resource("b", "2025-11-19")]}}
    client = fake_client({LISTING: json.dumps(listing).encode(),
                          "https://example.test/a.csv": data, "https://example.test/b.csv": data})
    wages.run(conn, client, now=NOW)
    assert {r[0] for r in conn.execute("SELECT DISTINCT resource_id FROM jobbank_wages")} == {"a", "b"}


def test_a_failed_download_keeps_what_is_loaded(conn, fake_client, fixtures):
    listing = {"result": {"resources": [resource("missing", "2025-11-19")]}}
    conn.execute(
        "INSERT INTO wage_tables (resource_id, name, url, revision_date, sha256, bytes, rows_loaded, loaded_at) "
        "VALUES ('kept', '2024 Wages', 'u', '2024-12-03', 's', 1, 1, ?)", (NOW,))
    client = fake_client({LISTING: json.dumps(listing).encode()})
    wages.run(conn, client, now=NOW)
    assert conn.execute("SELECT resource_id FROM wage_tables").fetchone()[0] == "kept"
    assert conn.execute("SELECT ok FROM sources_log WHERE source = 'wages'").fetchone()[0] == 0
