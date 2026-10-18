from lmia_pipeline.db import get_meta, upsert_employer
from lmia_pipeline.sources import registry_federal

HEADER = (
    "﻿Corporation number,Business number (BN),Corporate name - form 1,Corporate name - form 2,Governing legislation,"
    "Status,Status Detail,Anniversary date,Year of last annual filing,Date of last annual meeting,Street,Street 2,"
    "City/town,Province/territory,Country,Postal code,Minimum number of directors,Maximum number of directors\r\n"
)
ACTIVE = HEADER + (
    "8660115,835752437,MINDANGLER CAPITAL INC.,,Canada Business Corporations Act,Active,,2013-10-10,2025,2023-10-10,"
    "515 Legget Drive,Suite 800,Ottawa,ON,CA,K2K 3G4,1,12\r\n"
    "9000001,,PINKCLOUD SERVICES LTD.,,Canada Business Corporations Act,Active,,2026-06-22,,,,,Squamish,BC,CA,V8B 0A1,1,3\r\n"
    "9000002,,PINKCLOUD SERVICES LTD.,,Canada Business Corporations Act,Active,,2015-01-05,,,,,Calgary,AB,CA,T2P 1J9,1,3\r\n"
)
INACTIVE = HEADER + (
    "7286139,837253251,7286139 CANADA LTD.,,Canada Business Corporations Act,Inactive,Inactive - Amalgamated,2009-11-26,"
    "2025,2025-11-26,\"45, Queen Street\",,Sherbrooke,QC,CA,J1M 1J2,1,10\r\n"
)


def test_parse_extract_fields():
    rows = registry_federal.parse_extract(ACTIVE.encode("utf-8"), "u")
    assert rows[0][:3] == ("8660115", "MINDANGLER CAPITAL INC.", "mindangler capital")
    assert rows[0][3:8] == ("Active", "2013-10-10", "Ottawa", "ON", "K2K 3G4")


def test_load_and_match(conn, fake_client):
    mapping = {registry_federal.URLS[0]: ACTIVE.encode("utf-8"), registry_federal.URLS[1]: INACTIVE.encode("utf-8")}
    client = fake_client(mapping)
    ont = upsert_employer(conn, "Mindangler Capital Inc", "ON", source="jobbank", now="2026-10-12T00:00:00Z")
    pink = upsert_employer(conn, "PinkCloud Services", "BC", source="jobbank", postal_code="V0N 1H0", now="2026-10-12T00:00:00Z")
    numbered = upsert_employer(conn, "7286139 Canada Ltd.", "AB", source="esdc_positive", now="2026-10-12T00:00:00Z")
    upsert_employer(conn, "No Such Company", "NS", source="jobbank", now="2026-10-12T00:00:00Z")

    assert registry_federal.run(conn, client, now="2026-10-12T00:00:00Z") == 3
    assert conn.execute("SELECT COUNT(*) FROM federal_corporations").fetchone()[0] == 4
    rows = {r["employer_id"]: r for r in conn.execute("SELECT * FROM registry_matches WHERE registry = 'corporations_canada'")}
    assert rows[ont]["grade"] == "exact" and rows[ont]["registered_on"] == "2013-10-10" and rows[ont]["entity_type"] == "CBCA"
    # Two corporations share the name; the one in the employer's province wins.
    assert rows[pink]["registry_id"] == "9000001" and rows[pink]["grade"] == "exact"
    assert rows[numbered]["grade"] == "probable" and rows[numbered]["status"] == "Inactive"
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE registry = 'corporations_canada'").fetchone()[0] == 4

    # Unchanged files are not reloaded.
    calls_before = len(client.fake_session.calls)
    registry_federal.run(conn, client, now="2026-10-13T00:00:00Z")
    assert get_meta(conn, "federal_extract_sha:corporations-active-cbca-en.csv")
    assert conn.execute("SELECT COUNT(*) FROM federal_corporations").fetchone()[0] == 4
    assert len(client.fake_session.calls) == calls_before
