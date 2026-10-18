"""The wage, LFS and boundary loaders when their sources change or fail: the indicators
say what is missing and the rest of the run goes on."""

import io
import json
import zipfile

import pytest

from conftest import FakeResponse, FakeSession
from lmia_pipeline import cli, config
from lmia_pipeline.db import connect, upsert_employer
from lmia_pipeline.http import PoliteClient
from lmia_pipeline.sources import lfs, wages

NOW = "2026-10-17T00:00:00Z"
LISTING = config.CKAN_PACKAGE_SHOW.format(dataset=wages.DATASET)


def wage_listing(url: str) -> bytes:
    return json.dumps({"result": {"resources": [{"id": "w2025", "name": "2025 Wages", "created": "2025-11-19", "url": url}]}}).encode()


@pytest.mark.parametrize("body", [b"", b"NOC,Area,Wage\n1,2,3\n", b"<html>Service unavailable</html>"])
def test_a_wage_file_that_changed_or_came_back_empty_keeps_the_old_table_and_is_fetched_again(conn, fake_client, fixtures, body):
    good = (fixtures / "wages_trim.csv").read_bytes()
    url = "https://example.test/w2025.csv"
    client = fake_client({LISTING: wage_listing(url), url: good})
    assert wages.run(conn, client, now=NOW) > 0
    before = conn.execute("SELECT COUNT(*) FROM jobbank_wages").fetchone()[0]
    # A new revision of the file arrives broken.
    conn.execute("UPDATE wage_tables SET source_modified = 'older'")
    conn.execute("DELETE FROM meta WHERE key = 'wages_checked_at'")
    client.forget(url)
    broken = fake_client({LISTING: wage_listing(url), url: body})
    broken.cache_dir = client.cache_dir
    assert wages.run(conn, broken, now=NOW) == 0
    assert conn.execute("SELECT COUNT(*) FROM jobbank_wages").fetchone()[0] == before
    row = conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'wages' ORDER BY id DESC LIMIT 1").fetchone()
    assert row["ok"] == 0
    # The bad copy is not cached for a year; the next check downloads again.
    assert broken._cache_entry(url) is None


def zipped(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("14100459.csv", csv_text)
    return buf.getvalue()


@pytest.mark.parametrize("body", [b"", zipped("REF_DATE,GEO,Characteristic,VALUE\n2026-09,Winnipeg,Rate,5.9\n")])
def test_an_lfs_table_that_changed_or_came_back_empty_is_refused_and_not_kept(conn, fake_client, body):
    client = fake_client({lfs.URL: body})
    with pytest.raises(Exception):
        lfs.run(conn, client, now=NOW)
    assert client._cache_entry(lfs.URL) is None
    assert conn.execute("SELECT COUNT(*) FROM lfs_unemployment").fetchone()[0] == 0


class Down(FakeSession):
    """Every host answers 500."""

    def __init__(self) -> None:
        super().__init__({})

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append((url, headers or {}))
        return FakeResponse(500)


def test_every_reference_source_down_still_computes_indicators_that_say_what_is_missing(tmp_path, monkeypatch):
    db = tmp_path / "lmia.sqlite"
    conn = connect(db)
    eid = upsert_employer(conn, "Low Wage Diner", "NS", source="esdc_positive", now=NOW)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, date_posted, first_seen, last_seen, flag_current, "
        "flag_first, url, updated_at, wage_min, wage_max, wage_unit, noc_code, postal_code) "
        "VALUES (7, ?, 'Low Wage Diner', '2026-10-01', ?, ?, 'requested', 'requested', 'u', ?, 16.0, 16.0, 'HOUR', '65201', 'B3H 1A1')",
        (eid, NOW, NOW, NOW),
    )
    conn.commit()
    conn.close()
    session = Down()
    monkeypatch.setattr(cli, "PoliteClient", lambda **kw: PoliteClient(
        session=session, cache_dir=tmp_path / "cache", sleep=lambda s: None, clock=lambda: 0.0, **kw))
    code = cli.main(["run", "--wages", "--lfs", "--geography", "--indicators", "--db", str(db)])
    assert code == 1
    conn = connect(db)
    logged = {r["source"]: r["ok"] for r in conn.execute("SELECT source, ok FROM sources_log")}
    assert logged["wages"] == 0 and logged["lfs"] == 0 and logged["geography"] == 0
    states = {r["indicator"]: r["state"] for r in conn.execute("SELECT indicator, state FROM indicators WHERE employer_id = ?", (eid,))}
    assert states["wage_at_floor"] == "not_evaluated"
    assert "status" not in logged or logged["status"] == 1
    conn.close()
    # Bounded: the client gave up instead of retrying forever.
    assert len(session.calls) < 200
