"""US FMCSA Company Census: the Canadian rows, paged from the API, and the join to employers.

The fixture is 300 Canadian records from one page of the live API
(2026-10-22), fetched with the same column list as the stage, so it holds no
officer, phone, fax or email field; no individual carrier and no name that
reads as a person. The person names in the synthetic records are invented.
"""

import json

import pytest

from conftest import FakeResponse
from lmia_pipeline import export_static
from lmia_pipeline.db import get_meta, upsert_employer
from lmia_pipeline.normalize import norm_name
from lmia_pipeline.sources import fmcsa

NOW = "2026-10-22T00:00:00Z"
FIXTURE = "fmcsa_canada_trim.json"


def records(fixtures) -> list[dict]:
    return json.loads((fixtures / FIXTURE).read_text(encoding="utf-8"))


def test_the_request_names_only_the_columns_read_and_canadian_rows():
    url = fmcsa.page_url(0)
    assert "phy_country%3D%27CA%27" in url and "%24offset=0" in url and "%24limit=50000" in url
    for field in ("company_officer", "phone", "cell_phone", "fax", "email"):
        assert field not in url
    assert all(field not in fmcsa.FIELDS for field in ("company_officer_1", "company_officer_2", "email_address"))


def test_parse_keeps_the_fields_and_reads_dates_and_ratings(fixtures):
    recs = records(fixtures)
    assert not any(k.startswith(("company_officer", "phone", "fax", "email", "cell")) for r in recs for k in r)
    wanted = {(norm_name(r["legal_name"]), r["phy_state"]) for r in recs}
    rows, counts = fmcsa.parse_rows(recs, wanted, NOW)
    assert counts == {"read": 300, "persons": 0, "kept": 300}
    by = {r[0]: dict(zip(fmcsa.COLUMNS, r)) for r in rows}
    bison = by[245330]
    assert (bison["legal_name"], bison["province"], bison["postal_code"], bison["status"]) == (
        "BISON TRANSPORT INC", "MB", "R3H 0T8", "A")
    assert (bison["power_units"], bison["drivers"], bison["safety_rating"]) == (6746, 1110, "S")
    assert (bison["safety_rating_date"], bison["record_date"], bison["added_on"]) == ("2009-11-05", "2026-09-27", "1984-04-12")
    assert by[208148]["dba_name"] == "ROSEDALE"
    # Older records give only CANADA for the postal code.
    assert by[184901]["postal_code"] is None and by[184901]["safety_rating"] == "U"
    ratings = {}
    for r in by.values():
        ratings[r["safety_rating"]] = ratings.get(r["safety_rating"], 0) + 1
    assert ratings == {None: 135, "S": 95, "C": 55, "U": 15}


def test_individuals_and_person_names_are_never_stored():
    recs = [
        {"dot_number": "1", "legal_name": "HARBOUR HAUL LTD", "phy_state": "BC", "business_org_desc": "INDIVIDUAL"},
        {"dot_number": "2", "legal_name": "OWEN T MERCER", "phy_state": "BC", "business_org_desc": "CORPORATION"},
        {"dot_number": "3", "legal_name": "CORVID FREIGHT LTD", "dba_name": "ANA FERREIRA", "phy_state": "BC",
         "business_org_desc": "CORPORATION"},
        {"dot_number": "4", "legal_name": "NONE", "phy_state": "BC"},
    ]
    wanted = {("harbour haul", "BC"), ("owen t mercer", "BC"), ("corvid freight", "BC")}
    rows, counts = fmcsa.parse_rows(recs, wanted, NOW)
    assert counts == {"read": 4, "persons": 2, "kept": 1}
    kept = dict(zip(fmcsa.COLUMNS, rows[0]))
    assert (kept["legal_name"], kept["dba_name"]) == ("CORVID FREIGHT LTD", None)
    with pytest.raises(ValueError):
        fmcsa.parse_rows(["not a record"], wanted, NOW)


def seed(conn):
    def emp(name, province, postal=None):
        return upsert_employer(conn, name, province, source="esdc_positive", postal_code=postal, now=NOW)

    return {
        # Name and postal code agree: exact.
        "bison": emp("Bison Transport Inc.", "MB", "R3H 0T8"),
        "transx": emp("TransX Ltd.", "MB", "R4B 0A3"),
        # Name and province agree, another postal code: probable.
        "rosedale": emp("Rosedale Transport Limited", "ON", "L5S 1A1"),
        # The record gives no postal code: probable on the province.
        "coombs": emp("Coombs Transport Ltd.", "NL", "A0A 1G0"),
        # The DBA name with the postal code: probable.
        "armour": emp("Armour Transportation Systems", "NB", "E1E 2L4"),
        # One word and another postal code: too common for the province alone.
        "camco": emp("Camco Inc.", "ON", "M5V 1A1"),
        # Another province: never compared.
        "lozon": emp("Gerald Lozon Trucking Ltd.", "QC", "J4B 1A1"),
    }


def paged(fixtures, monkeypatch, size=100) -> dict[str, bytes]:
    monkeypatch.setattr(fmcsa, "PAGE_SIZE", size)
    recs = records(fixtures)
    mapping = {fmcsa.page_url(i): json.dumps(recs[i:i + size]).encode() for i in range(0, len(recs), size)}
    mapping[fmcsa.page_url(len(recs))] = b"[]"
    return mapping


def test_load_pages_through_the_canadian_rows_and_matches(conn, fake_client, fixtures, monkeypatch):
    ids = seed(conn)
    client = fake_client(paged(fixtures, monkeypatch))
    assert fmcsa.run(conn, client, now=NOW) == 5
    # Three full pages and the empty one that ends the read.
    assert len(client.fake_session.calls) == 4
    found = {(r["employer_id"], r["dot_number"]): (r["grade"], r["basis"]) for r in conn.execute("SELECT * FROM fmcsa_matches")}
    assert found == {
        (ids["bison"], 245330): ("exact", "name_postal_code"),
        (ids["transx"], 180162): ("exact", "name_postal_code"),
        (ids["rosedale"], 208148): ("probable", "name_province"),
        (ids["coombs"], 184901): ("probable", "name_province"),
        (ids["armour"], 245809): ("probable", "dba_postal_code"),
    }
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'fmcsa'").fetchone()[0]
    assert detail == "carriers=6 loaded_now=6 matched=5"
    assert not any(eid in (ids["camco"], ids["lozon"]) for eid, _ in found)
    out = export_static.profile_carriers(conn, [ids["bison"], ids["lozon"]])
    assert out[ids["bison"]] == [{
        "grade": "exact", "basis": "name_postal_code", "dot_number": 245330, "legal_name": "BISON TRANSPORT INC",
        "dba_name": None, "city": "WINNIPEG", "province": "MB", "postal_code": "R3H 0T8", "status": "A",
        "power_units": 6746, "drivers": 1110, "safety_rating": "S", "safety_rating_date": "2009-11-05",
        "record_date": "2026-09-27",
    }]
    assert ids["lozon"] not in out


def test_monthly_cadence_and_failures(conn, fake_client, fixtures, monkeypatch):
    seed(conn)
    mapping = paged(fixtures, monkeypatch)
    client = fake_client(mapping)
    fmcsa.run(conn, client, now=NOW)
    calls = len(client.fake_session.calls)
    assert fmcsa.run(conn, client, now="2026-11-10T00:00:00Z") == 5
    assert len(client.fake_session.calls) == calls
    # After a month a failed request is recorded and the carriers stay.
    broken = fake_client({fmcsa.page_url(0): FakeResponse(404)})
    assert fmcsa.run(conn, broken, now="2026-11-30T00:00:00Z") == 5
    row = conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'fmcsa' ORDER BY id DESC").fetchone()
    assert row["ok"] == 0 and "download failed" in row["detail"]
    assert get_meta(conn, fmcsa.LOADED_KEY) == NOW
    # An answer that is not a list, or no Canadian row at all, is refused.
    with pytest.raises(ValueError):
        fmcsa.run(conn, fake_client({fmcsa.page_url(0): b'{"error": true}'}), now="2026-11-30T00:00:00Z")
    with pytest.raises(ValueError):
        fmcsa.run(conn, fake_client({fmcsa.page_url(0): b"[]"}), now="2026-11-30T00:00:00Z")
    assert conn.execute("SELECT COUNT(*) FROM fmcsa_carriers").fetchone()[0] == 6
