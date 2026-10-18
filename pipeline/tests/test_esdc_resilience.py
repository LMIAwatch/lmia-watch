"""The ESDC and IRCC loaders against an open-data portal that changed or failed."""

import json

from conftest import FakeResponse
from lmia_pipeline import config
from lmia_pipeline.sources import esdc, ircc

POS_LISTING = config.CKAN_PACKAGE_SHOW.format(dataset=config.ESDC_DATASETS["positive"])
NEG_LISTING = config.CKAN_PACKAGE_SHOW.format(dataset=config.ESDC_DATASETS["negative"])
HEADER = "Province/Territory,Stream,Employer,Address,Occupation,Approved LMIAs,Approved Positions\n"
ROWS = (
    'Manitoba,High Wage,Acme Farms Ltd,"Winnipeg, MB R3C 1A1",72600-Electricians,1,2\n'
    'Ontario,Low Wage,Sample Hotels Corp,"Toronto, ON M5V 1A1",65201-Food counter attendants,2,5\n'
)


def res(rid: str, period: str, created: str, ext: str = "csv") -> dict:
    return {"id": rid, "name": f"{period} employers with a positive LMIA", "url": f"https://example.invalid/{rid}.{ext}",
            "language": ["en"], "created": created}


def listing(*resources) -> bytes:
    return json.dumps({"success": True, "result": {"resources": list(resources)}}).encode()


# A healthy negative list for the tests about the positive one.
NEG = res("neg-q1", "2026Q1", "2026-07-01T00:00:00")
NEG_ROW = 'Alberta,High Wage,Other Co,"Calgary, AB T2P 1A1",72600-Electricians,1,1'
NEG_OK = {NEG_LISTING: listing(NEG), NEG["url"]: (HEADER + NEG_ROW + "\n").encode()}


def esdc_log(conn):
    return conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'esdc' ORDER BY id DESC LIMIT 1").fetchone()


def test_a_portal_outage_costs_one_list_one_night(conn, fake_client):
    a = res("q1", "2026Q1", "2026-07-01T00:00:00")
    client = fake_client({
        POS_LISTING: FakeResponse(503),
        NEG_LISTING: listing(a),
        a["url"]: (HEADER + ROWS).encode(),
    }, max_attempts=1)
    totals = esdc.run(conn, client)
    assert totals == {"positive": 0, "negative": 2}
    ok, detail = esdc_log(conn)
    assert ok == 0 and "positive listing: " in detail and "HTTP 503" in detail


def test_a_maintenance_page_served_as_the_listing_is_not_kept_in_the_cache(conn, fake_client):
    client = fake_client({POS_LISTING: b"<html>Down for maintenance</html>", NEG_LISTING: listing()})
    esdc.run(conn, client)
    ok, detail = esdc_log(conn)
    assert ok == 0 and "positive listing" in detail and "negative listing: no English resources" in detail
    assert client._cache_entry(POS_LISTING) is None


def test_a_pdf_behind_an_xlsx_link_fails_that_quarter_and_is_fetched_again_next_time(conn, fake_client):
    pdf = res("pdf", "2026Q1", "2026-07-01T00:00:00", ext="xlsx")
    good = res("q4", "2025Q4", "2026-04-01T00:00:00")
    client = fake_client({
        POS_LISTING: listing(pdf, good),
        NEG_LISTING: listing(),
        pdf["url"]: b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\n",
        good["url"]: (HEADER + ROWS).encode(),
    })
    totals = esdc.run(conn, client)
    assert totals["positive"] == 2
    ok, detail = esdc_log(conn)
    assert ok == 0 and "no header row found" in detail
    assert client._cache_entry(pdf["url"]) is None


def test_a_renamed_employer_column_fails_loudly(conn, fake_client):
    renamed = res("ren", "2026Q1", "2026-07-01T00:00:00")
    client = fake_client({
        POS_LISTING: listing(renamed),
        NEG_LISTING: listing(),
        renamed["url"]: (HEADER.replace("Employer", "Business operating name") + ROWS).encode(),
    })
    assert esdc.run(conn, client)["positive"] == 0
    assert "no header row found" in esdc_log(conn)[1]


def test_an_extra_header_row_and_a_zero_row_quarter_load(conn, fake_client):
    extra = res("x", "2026Q1", "2026-07-01T00:00:00")
    empty = res("e", "2025Q4", "2026-04-01T00:00:00")
    client = fake_client({
        POS_LISTING: listing(extra, empty),
        **NEG_OK,
        extra["url"]: ("Title line,,,,,,\n" + HEADER + HEADER + ROWS).encode(),
        empty["url"]: HEADER.encode(),
    })
    assert esdc.run(conn, client)["positive"] == 2
    assert esdc_log(conn)[0] == 1
    loaded = {r[0]: r[1] for r in conn.execute("SELECT resource_id, rows_loaded FROM esdc_resources WHERE dataset = 'positive'")}
    assert loaded == {"x": 2, "e": 0}


def test_a_file_published_twice_is_loaded_once(conn, fake_client):
    # ESDC published the 2020 Q2 negative file a second time as 2021 Q2 (same
    # bytes, resource 4f9a23d3-...); loading both counted every row twice.
    first = res("2020q2", "2020Q2", "2020-09-24T00:00:00")
    copy = res("2021q2", "2021Q2", "2021-09-03T00:00:00")
    body = (HEADER + ROWS).encode()
    client = fake_client({POS_LISTING: listing(copy, first), **NEG_OK, first["url"]: body, copy["url"]: body})
    assert esdc.run(conn, client)["positive"] == 2
    ok, detail = esdc_log(conn)
    assert ok == 1 and "duplicates=2021Q2 positive: same file as 2020Q2" in detail
    assert [tuple(r) for r in conn.execute("SELECT DISTINCT period FROM esdc_records WHERE list = 'positive'")] == [("2020Q2",)]


def test_a_copy_loaded_by_an_earlier_version_is_removed(conn, monkeypatch):
    first = res("2020q2", "2020Q2", "2020-09-24T00:00:00")
    copy = res("2021q2", "2021Q2", "2021-09-03T00:00:00")
    body = (HEADER + ROWS).encode()
    esdc.load_resource(conn, "positive", first, body)
    # What the loader did before it knew about copies: load the second as a quarter of its own.
    with monkeypatch.context() as m:
        m.setattr(esdc, "_earlier_twin", lambda *a: None)
        esdc.load_resource(conn, "positive", copy, body)
    assert conn.execute("SELECT COUNT(*) FROM esdc_records").fetchone()[0] == 4
    try:
        esdc.load_resource(conn, "positive", copy, body)
    except esdc.DuplicateFile:
        pass
    assert [tuple(r) for r in conn.execute("SELECT resource_id, COUNT(*) FROM esdc_records GROUP BY resource_id")] == [("2020q2", 2)]
    assert [r[0] for r in conn.execute("SELECT resource_id FROM esdc_resources")] == ["2020q2"]


def test_ircc_json_with_changed_keys_loads_nothing_and_raises_nothing():
    # The loader is not ours to change here; this pins what it does today so a
    # change in the source is noticed: zero rows, no exception.
    changed = {"data": [{"operating_name": "Acme", "legal": "Acme Inc", "why": "1"}]}
    assert ircc.parse_rows(changed, {}) == []
    renamed_fields = {"list": [{"bn_operating_name": "Acme", "reason": "<a>1</a>"}]}
    rows = ircc.parse_rows(renamed_fields, {"1": "Did not pay"})
    assert len(rows) == 1 and rows[0]["operating_name"] is None
