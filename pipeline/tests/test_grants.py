"""Federal grants and contributions: the parser on a trimmed copy of grants.csv, and the join to employers.

The fixture is 266 rows cut from the head of the live file (2026-10-22): no
row of recipient type P and no recipient named as a person, free text
blanked, titles cut short. The person names in the synthetic rows below are
invented.
"""

import csv
import io

import pytest

from conftest import FakeResponse
from lmia_pipeline.db import get_meta, upsert_employer
from lmia_pipeline.normalize import norm_name
from lmia_pipeline.sources import grants, registry_federal

NOW = "2026-10-22T00:00:00Z"
FIXTURE = "grants_trim.csv"


def fixture_text(fixtures) -> str:
    return (fixtures / FIXTURE).read_bytes().decode("utf-8-sig")


def every_name(fixtures) -> set[str]:
    reader = csv.DictReader(io.StringIO(fixture_text(fixtures), newline=""))
    return {norm_name(r["recipient_legal_name"].split("|")[0]) for r in reader}


def parsed(fixtures, wanted=None, numbers=frozenset()):
    rows, counts = grants.parse_file(fixtures / FIXTURE, every_name(fixtures) if wanted is None else wanted,
                                     set(numbers), NOW)
    return {r[0]: dict(zip(grants.COLUMNS, r)) for r in rows}, counts


def test_one_row_per_agreement_at_its_latest_amendment(fixtures):
    rows, counts = parsed(fixtures)
    assert counts == {"read": 266, "persons": 0, "kept": 211}
    feeders = rows["aafc-aac,235-2018-2019-Q3-00007"]
    assert feeders["amendment_number"] == 4 and feeders["agreement_value"] == 260980.0
    # The fourth amendment types the business number with eight digits: not used.
    assert feeders["business_number"] is None
    cattle = rows["aafc-aac,235-2018-2019-Q3-00005"]
    assert (cattle["amendment_number"], cattle["business_number"], cattle["recipient_type"]) == (3, "106844228", "N")
    assert cattle["operating_name"] == "Canadian Roundtable for Sustainable Beef"
    assert (cattle["department_en"], cattle["department_fr"]) == (
        "Agriculture and Agri-Food Canada", "Agriculture et Agroalimentaire Canada")
    assert cattle["start_date"] == "2018-06-21" and cattle["agreement_type"] == "C"
    # A program account after the number is dropped; the postal code is reformatted.
    kampman = rows["aafc-aac,235-2019-2020-Q3-00054"]
    assert (kampman["business_number"], kampman["postal_code"], kampman["province"]) == ("133507087", "V3G 1R6", "BC")
    # Older rows write the province into the city.
    classroom = rows["aafc-aac,GC-2017-Q1-00001"]
    assert (classroom["city"], classroom["province"], classroom["recipient_type"]) == ("Headingley", "MB", None)
    # A field given in both languages keeps its first part.
    avalon = rows["acoa-apeca,276-2020-2021-Q3-00013"]
    assert (avalon["legal_name"], avalon["city"], avalon["province"]) == ("Avalon Laboratories Inc.", "St. John's", "NL")
    # A placeholder number (000000000) is no number; foreign recipients are left out.
    assert all(r["business_number"] != "000000000" for r in rows.values())
    assert not any(r["legal_name"].startswith(("Winnow", "Organisation for Economic")) for r in rows.values())


def test_only_wanted_names_and_numbers_are_kept(fixtures):
    rows, counts = parsed(fixtures, wanted={"kampman farms"}, numbers={"106844228"})
    assert counts["read"] == 266
    # The number brings in the agreement that carries it in its latest amendment.
    assert sorted(rows) == ["aafc-aac,235-2018-2019-Q3-00005", "aafc-aac,235-2019-2020-Q3-00054"]


def synthetic(*rows: dict) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(grants.REQUIRED))
    writer.writeheader()
    for i, row in enumerate(rows):
        base = {c: "" for c in grants.REQUIRED}
        base.update({"ref_number": f"R-{i}", "amendment_number": "0", "agreement_type": "G", "recipient_country": "CA",
                     "recipient_province": "BC", "recipient_city": "Victoria", "recipient_postal_code": "V8W 1A1",
                     "agreement_value": "50000", "agreement_start_date": "2025-04-01", "owner_org": "test-org",
                     "owner_org_title": "Test Department | Ministère de test"})
        base.update(row)
        writer.writerow(base)
    return out.getvalue()


def test_individuals_are_never_stored():
    text = synthetic(
        {"recipient_type": "P", "recipient_legal_name": "Harbour View Farms Ltd."},
        {"recipient_type": "F", "recipient_legal_name": "Ana Ferreira"},
        {"recipient_type": "", "recipient_legal_name": "Priya Sandhu, Arjun Sandhu"},
        {"recipient_type": "N", "recipient_legal_name": "Lena Okafor, Mira Law"},
        {"recipient_type": "F", "recipient_legal_name": "Ana Ferreira o/a Little Steps Farm"},
        {"recipient_type": "F", "recipient_legal_name": "Corvid Orchard Ltd.", "recipient_operating_name": "Owen T Mercer"},
    )
    wanted = {norm_name(n) for n in ("Harbour View Farms Ltd.", "Ana Ferreira", "Priya Sandhu, Arjun Sandhu",
                                     "Lena Okafor, Mira Law", "Ana Ferreira", "Corvid Orchard Ltd.")}
    rows, counts = grants.parse_rows(io.StringIO(text, newline=""), wanted, set(), NOW)
    assert counts == {"read": 6, "persons": 5, "kept": 1}
    kept = dict(zip(grants.COLUMNS, rows[0]))
    # The business stays; the person named as its operating name does not.
    assert kept["legal_name"] == "Corvid Orchard Ltd." and kept["operating_name"] is None


def test_a_file_without_the_columns_is_refused():
    with pytest.raises(ValueError, match="lacks columns"):
        grants.parse_rows(io.StringIO("ref_number,recipient_legal_name\nR-1,Corvid Orchard Ltd.\n"), set(), set(), NOW)


def seed(conn):
    """Employers built from fixture names, one for each rule."""
    ids = {
        # Name and postal area agree: exact.
        "dykshoorn": upsert_employer(conn, "Dykshoorn Farms Ltd", "BC", source="esdc_positive", postal_code="V3G 1S8", now=NOW),
        # Name and province agree, another postal area: probable.
        "kampman": upsert_employer(conn, "Kampman Farms Ltd.", "BC", source="esdc_positive", postal_code="V2T 1A1", now=NOW),
        # The same name in another province: nothing.
        "jireh": upsert_employer(conn, "Jireh Farms Ltd.", "AB", source="esdc_positive", postal_code="T4L 1A1", now=NOW),
        # One word and another postal area: too common to match on the province.
        "realize": upsert_employer(conn, "Realize", "ON", source="jobbank", postal_code="M4C 1A1", now=NOW),
        # The operating name with the postal area: probable.
        "chilliwack": upsert_employer(conn, "Chilliwack Cattle Sales", "BC", source="esdc_positive",
                                      postal_code="V2P 6H3", now=NOW),
        # A numbered company is specific enough for the province alone.
        "numbered": upsert_employer(conn, "0956796 BC Ltd", "BC", source="esdc_positive", postal_code="V4Z 1A1", now=NOW),
        # Matched to a federal corporation with a business number.
        "cattle": upsert_employer(conn, "Canadian Cattlemen's Association", "AB", source="esdc_positive",
                                  postal_code="T2E 7H7", now=NOW),
    }
    conn.execute(
        "INSERT INTO federal_corporations (number, legal_name, norm_name, status, registered_on, city, province, "
        "postal_code, source_url, business_number) VALUES ('1000001', 'CANADIAN CATTLEMEN''S ASSOCIATION', ?, 'Active', "
        "'1932-01-01', 'Calgary', 'AB', 'T2E 7H7', 'u', '106844228')", (norm_name("Canadian Cattlemen's Association"),))
    conn.commit()
    registry_federal.match(conn, now=NOW)
    return ids


def test_load_and_match(conn, fake_client, fixtures, tmp_path):
    ids = seed(conn)
    client = fake_client({grants.URL: (fixtures / FIXTURE).read_bytes()})
    assert grants.run(conn, client, now=NOW, work_dir=tmp_path / "work") == 6
    # The download is deleted once read.
    assert not any((tmp_path / "work").iterdir())
    assert get_meta(conn, grants.LOADED_KEY) == NOW
    found = {(r["employer_id"], r["agreement_key"]): (r["grade"], r["basis"])
             for r in conn.execute("SELECT * FROM grant_matches")}
    assert found == {
        (ids["dykshoorn"], "aafc-aac,235-2019-2020-Q3-00058"): ("exact", "name_postal_area"),
        (ids["kampman"], "aafc-aac,235-2019-2020-Q3-00054"): ("probable", "name_province"),
        (ids["chilliwack"], "aafc-aac,235-2019-2020-Q3-00065"): ("probable", "operating_name_postal_area"),
        (ids["numbered"], "aafc-aac,235-2019-2020-Q3-00065"): ("probable", "name_province"),
        # The agreement carrying the corporation's number joins by number, at
        # the registry match's grade; the one without a number by name.
        (ids["cattle"], "aafc-aac,235-2018-2019-Q3-00005"): ("exact", "business_number"),
        (ids["cattle"], "aafc-aac,235-2018-2019-Q1-00003"): ("exact", "name_postal_area"),
    }
    assert not any(eid in (ids["jireh"], ids["realize"]) for eid, _ in found)
    log = conn.execute("SELECT detail, ok FROM sources_log WHERE source = 'grants'").fetchone()
    assert log["ok"] == 1 and "agreements=7 loaded_now=7 matched=6" in log["detail"]


def test_a_quarter_between_downloads_and_a_failed_download_keeps_the_rows(conn, fake_client, fixtures, tmp_path):
    seed(conn)
    client = fake_client({grants.URL: (fixtures / FIXTURE).read_bytes()})
    grants.run(conn, client, now=NOW, work_dir=tmp_path)
    calls = len(client.fake_session.calls)
    total = conn.execute("SELECT COUNT(*) FROM federal_grants").fetchone()[0]
    # Within the quarter the file is not fetched; the matching still runs.
    assert grants.run(conn, client, now="2026-12-01T00:00:00Z", work_dir=tmp_path) == 6
    assert len(client.fake_session.calls) == calls
    # After it, a download that fails is a failed stage and the rows stay.
    broken = fake_client({grants.URL: FakeResponse(404)})
    assert grants.run(conn, broken, now="2027-02-01T00:00:00Z", work_dir=tmp_path) == 6
    assert conn.execute("SELECT COUNT(*) FROM federal_grants").fetchone()[0] == total
    row = conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'grants' ORDER BY id DESC").fetchone()
    assert row["ok"] == 0 and "download failed" in row["detail"]
    assert get_meta(conn, grants.LOADED_KEY) == NOW


def test_a_changed_layout_raises_and_keeps_the_rows(conn, fake_client, fixtures, tmp_path):
    seed(conn)
    grants.run(conn, fake_client({grants.URL: (fixtures / FIXTURE).read_bytes()}), now=NOW, work_dir=tmp_path)
    total = conn.execute("SELECT COUNT(*) FROM federal_grants").fetchone()[0]
    changed = fake_client({grants.URL: b"ref,name\n1,x\n"})
    with pytest.raises(ValueError):
        grants.run(conn, changed, now="2027-02-01T00:00:00Z", work_dir=tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM federal_grants").fetchone()[0] == total
    assert not any(tmp_path.iterdir())


def test_another_business_number_is_never_joined_by_name(conn):
    eid = upsert_employer(conn, "Corvid Orchard Ltd.", "BC", source="esdc_positive", postal_code="V8W 1A1", now=NOW)
    conn.execute(
        "INSERT INTO federal_corporations (number, legal_name, norm_name, province, postal_code, source_url, "
        "business_number) VALUES ('1000002', 'CORVID ORCHARD LTD.', 'corvid orchard', 'BC', 'V8W 1A1', 'u', '835752437')")
    registry_federal.match(conn, now=NOW)
    text = synthetic(
        {"recipient_type": "F", "recipient_legal_name": "Corvid Orchard Ltd.", "recipient_business_number": "837253251"},
        {"recipient_type": "F", "recipient_legal_name": "Corvid Orchard Ltd.", "recipient_business_number": "835752437RC0001"},
        {"recipient_type": "F", "recipient_legal_name": "Corvid Orchard Ltd."},
    )
    rows, _ = grants.parse_rows(io.StringIO(text, newline=""), {"corvid orchard"}, {"835752437"}, NOW)
    conn.executemany(f"INSERT INTO federal_grants ({', '.join(grants.COLUMNS)}) VALUES ({', '.join('?' * len(grants.COLUMNS))})", rows)
    assert grants.match(conn, now=NOW) == 2
    found = {r["agreement_key"]: r["basis"] for r in conn.execute("SELECT * FROM grant_matches WHERE employer_id = ?", (eid,))}
    assert found == {"test-org,R-1": "business_number", "test-org,R-2": "name_postal_area"}
