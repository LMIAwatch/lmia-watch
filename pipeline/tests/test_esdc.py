from lmia_pipeline.sources import esdc
from lmia_pipeline.sources.esdc import load_resource, map_headers, normalize_row, parse_csv, parse_xlsx

POS_RES = {"id": "res-pos", "name": "2026Q1 employers with a positive LMIA (English)",
           "url": "https://example.invalid/tfwp_2026q1_pos_en.xlsx", "created": "2026-07-21T14:00:00"}
NEG_RES = {"id": "res-neg", "name": "2026Q1 employers with a negative LMIA (English)",
           "url": "https://example.invalid/tfwp_2026q1_neg_en.xlsx", "created": "2026-07-21T14:00:00"}


def test_map_headers_keywords():
    fields = map_headers(["Province/Territory", "Program Stream", "Employer", "Address", "Occupation",
                          "Incorporate Status", "Approved LMIAs", "Approved Positions"])
    assert fields == {"province": 0, "stream": 1, "employer": 2, "address": 3, "occupation": 4,
                      "incorporate": 5, "lmias": 6, "positions": 7}
    assert map_headers(["Employer ", "Address", "Positions"]) == {"employer": 0, "address": 1, "positions": 2}
    assert map_headers(["Province/Territory", "Stream", "Employer Name", "Address", "Occupation",
                        "Approved LMIA Positions"])["positions"] == 5


def test_parse_xlsx_fixture_rows(fixtures):
    headers, rows = parse_xlsx((fixtures / "esdc_2026q1_pos_trim.xlsx").read_bytes())
    fields = map_headers(headers)
    rec = normalize_row(fields, rows[0])
    assert rec["employer_raw"] == "#1Nails"
    assert rec["province"] == "NL"
    assert (rec["city"], rec["postal_code"]) == ("St. John’s", "A1B 1W3")
    assert (rec["noc_code"], rec["noc_title"]) == ("62029", "Other services supervisors")
    assert (rec["lmias"], rec["positions"], rec["stream"]) == (1, 1, "High Wage")
    # Footnote rows have no employer and normalize to None.
    assert normalize_row(fields, rows[-1]) is None


def test_parse_csv_2014_layout_with_province_sections(conn):
    text = (
        '"Employers who have requested a Labour Market Impact Assessment (LMIA) and were issued a positive LMIA between June 20 and December 31, 2014 inclusively, by province/territory ",,\r\r\n'
        "Newfoundland and Labrador,,\r\r\n"
        "Employer ,Address,Positions\r\r\n"
        'Aker Solutions AIM,"Box 20, 215 Water Street, Suite 511, St. John\'s, NL  A1C 6C9",2\r\r\n'
        "Nova Scotia,,\r\r\n"
        "Employer ,Address,Positions\r\r\n"
        'Harbour Farms,"Truro",3\r\r\n'
    ).encode("cp1252")
    headers, rows = parse_csv(text)
    assert map_headers(headers)["employer"] == 0
    res = {"id": "res-2014", "name": "2014 positive employers", "url": "https://example.invalid/positive_employers_en.csv",
           "created": "2015-01-01T00:00:00"}
    assert load_resource(conn, "positive", res, text, now="2026-01-01T00:00:00Z") == 2
    got = {r["employer_raw"]: r for r in conn.execute("SELECT * FROM esdc_records")}
    assert got["Aker Solutions AIM"]["province"] == "NL"
    assert got["Aker Solutions AIM"]["city"] == "St. John's"
    assert got["Aker Solutions AIM"]["positions"] == 2
    assert got["Harbour Farms"]["province"] == "NS"   # from the section line
    assert got["Harbour Farms"]["period"] == "2014"


def test_parse_csv_2018_layout():
    text = (
        '"Employers who were issued a positive LMIA by Stream, NOC 2011 and business location in 2018 (January-March)",,,,,\r\n'
        "Province/Territory,Stream,Employer,Address,Occupation,Approved Positions\r\n"
        'Newfoundland and Labrador,    High Wage,Central Regional Health Authority,"GRAND FALLS-WINDSOR, NL A2A 1Y4",3111-Specialist physicians,3\r\n'
    ).encode("utf-8-sig")
    headers, rows = parse_csv(text)
    rec = normalize_row(map_headers(headers), rows[0])
    assert rec["stream"] == "High Wage"
    assert (rec["province"], rec["city"], rec["postal_code"]) == ("NL", "Grand Falls-Windsor", "A2A 1Y4")
    assert (rec["noc_code"], rec["positions"], rec["lmias"]) == ("3111", 3, None)


def test_load_resource_dedupes_and_reloads_revisions(conn, fixtures):
    data = (fixtures / "esdc_2026q1_pos_trim.xlsx").read_bytes()
    n = load_resource(conn, "positive", POS_RES, data, now="2026-07-22T00:00:00Z")
    assert n == 40
    assert load_resource(conn, "positive", POS_RES, data) == 0
    res = conn.execute("SELECT * FROM esdc_resources WHERE resource_id = 'res-pos'").fetchone()
    assert (res["period"], res["published"], res["rows_loaded"]) == ("2026Q1", "2026-07-21", 40)
    assert conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0] > 20

    neg = (fixtures / "esdc_2026q1_neg_trim.xlsx").read_bytes()
    assert load_resource(conn, "negative", NEG_RES, neg) == 40
    row = conn.execute("SELECT * FROM esdc_records WHERE list = 'negative' LIMIT 1").fetchone()
    assert row["lmias"] is not None and row["positions"] is not None

    # A revised file replaces the resource's rows instead of stacking them.
    import io

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data))
    wb.worksheets[0]["H3"] = 9
    buf = io.BytesIO()
    wb.save(buf)
    revised = buf.getvalue()
    before = conn.execute("SELECT COUNT(*) FROM esdc_records WHERE resource_id = 'res-pos'").fetchone()[0]
    load_resource(conn, "positive", POS_RES, revised)
    after = conn.execute("SELECT COUNT(*) FROM esdc_records WHERE resource_id = 'res-pos'").fetchone()[0]
    assert before == after == 40


def test_run_discovers_english_resources(conn, fake_client, fixtures):
    package = {"result": {"resources": [
        {**POS_RES, "language": ["en"], "format": "XLSX"},
        {"id": "fr", "name": "2026Q1 (French)", "url": "https://example.invalid/pos_fr.xlsx",
         "language": ["fr"], "format": "XLSX", "created": "2026-07-21T14:00:00"},
    ]}}
    neg_package = {"result": {"resources": [{**NEG_RES, "language": ["en"], "format": "XLS"}]}}
    import json

    from lmia_pipeline import config
    mapping = {
        config.CKAN_PACKAGE_SHOW.format(dataset=config.ESDC_DATASETS["positive"]): json.dumps(package).encode(),
        config.CKAN_PACKAGE_SHOW.format(dataset=config.ESDC_DATASETS["negative"]): json.dumps(neg_package).encode(),
        POS_RES["url"]: (fixtures / "esdc_2026q1_pos_trim.xlsx").read_bytes(),
        NEG_RES["url"]: (fixtures / "esdc_2026q1_neg_trim.xlsx").read_bytes(),
    }
    client = fake_client(mapping)
    totals = esdc.run(conn, client)
    assert totals == {"positive": 40, "negative": 40}
    assert not any("pos_fr" in url for url, _ in client.fake_session.calls)
    assert conn.execute("SELECT ok FROM sources_log WHERE source = 'esdc'").fetchone()[0] == 1
