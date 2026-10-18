import io
import zipfile

import pytest

from lmia_pipeline.db import get_meta
from lmia_pipeline.sources import lfs


def test_parse_keeps_the_unadjusted_cma_unemployment_rate(fixtures):
    rows = lfs.parse_table((fixtures / "lfs_14100459_trim.zip").read_bytes())
    by_key = {(r[0], r[1]): r for r in rows}
    # The rates ESDC put in force on 2026-10-09: Winnipeg 5.9, St. John's 6.4, Ottawa-Gatineau 7.9.
    assert by_key[("602", "2026-09")][2:4] == (5.9, "Winnipeg")
    assert by_key[("001", "2026-09")][2:4] == (6.4, "St. John's")
    assert by_key[("505", "2026-09")][2:4] == (7.9, "Ottawa-Gatineau")
    assert by_key[("602", "2026-09")][4] == "v1643280007"
    # Canada, the Ontario part of Ottawa-Gatineau, population rows, standard
    # errors and the seasonally adjusted series are all left out.
    assert {r[0] for r in rows} == {"001", "505", "602"}
    assert len(rows) == 3 * 11  # 2024-03 to 2026-09, quarter ends


def test_run_loads_once_and_checks_monthly(conn, fake_client, fixtures):
    data = (fixtures / "lfs_14100459_trim.zip").read_bytes()
    client = fake_client({lfs.URL: data})
    assert lfs.run(conn, client, now="2026-10-17T00:00:00Z") == 33
    assert get_meta(conn, "lfs_sha")
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'lfs' ORDER BY id DESC").fetchone()[0]
    assert "latest=2026-09" in detail and "14-10-0459-01" in detail
    rate = conn.execute(
        "SELECT rate FROM lfs_unemployment WHERE cma_uid = '602' AND ref_month = '2024-12'").fetchone()[0]
    assert rate == 5.6
    # Within 30 days no request is made; the check date lives in the database.
    calls = len(client.fake_session.calls)
    assert lfs.run(conn, client, now="2026-11-10T00:00:00Z") == 0
    assert len(client.fake_session.calls) == calls
    # After 30 days the table is read again; the same file loads nothing.
    assert lfs.run(conn, client, now="2026-11-20T00:00:00Z") == 0
    assert get_meta(conn, "lfs_checked_at") == "2026-11-20T00:00:00Z"


def test_an_archive_without_rates_is_refused(conn, fake_client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("14100459.csv", "REF_DATE,GEO,DGUID,Labour force characteristics,Statistics,Data type,VALUE\n")
    with pytest.raises(ValueError):
        lfs.run(conn, fake_client({lfs.URL: buf.getvalue()}))
