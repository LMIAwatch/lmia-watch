import json

from lmia_pipeline import config
from lmia_pipeline.db import upsert_employer
from lmia_pipeline.sources import ircc


def test_parse_rows_maps_reasons_and_addresses(fixtures):
    legend = ircc.parse_legend((fixtures / "ircc_legend.html").read_text(encoding="utf-8"))
    assert legend and all(k.isdigit() for k in legend)
    data = json.loads((fixtures / "ircc_sample.json").read_text(encoding="utf-8"))
    rows = ircc.parse_rows(data, legend)
    assert len(rows) == 3
    first = rows[0]
    assert first["operating_name"] and first["legal_name"]
    assert "<" not in (first["address"] or "")
    assert first["decision_date"] and len(first["decision_date"]) == 10
    assert first["penalty"].startswith("$")
    assert first["status"] in ("Eligible", "Ineligible")
    assert first["reasons"].split(":")[0].strip().isdigit()


def test_run_inserts_findings_and_links_employers(conn, fake_client, fixtures):
    mapping = {
        config.IRCC_NONCOMPLIANT_URL: (fixtures / "ircc_legend.html").read_bytes(),
        ircc.JSON_URL: (fixtures / "ircc_sample.json").read_bytes(),
    }
    client = fake_client(mapping)
    assert ircc.run(conn, client, now="2026-10-12T00:00:00Z") == 3
    assert ircc.run(conn, client, now="2026-10-13T00:00:00Z") == 0
    rows = conn.execute("SELECT * FROM findings ORDER BY id").fetchall()
    assert all(r["employer_id"] for r in rows)
    assert conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0] == 3
    emp = conn.execute("SELECT * FROM employers WHERE id = ?", (rows[1]["employer_id"],)).fetchone()
    assert emp["province"] in ("BC", "QC", "ON", "AB")
    # The finding's address supplies the street, and says so.
    assert emp["street"] == "213-8334 128 Street" and emp["street_source"] == "ircc"


def _finding_json(*rows: tuple[str, str, str]) -> bytes:
    return json.dumps({"list": [
        {"bn_operating": op, "bn_legal": legal, "bn_address_en": address, "reason": "<a>1</a>",
         "date": "2024-05-01", "penalty_en": "$1,000", "status_en": "Eligible"}
        for op, legal, address in rows
    ]}).encode("utf-8")


def test_findings_link_by_legal_name_and_fill_the_profile(conn, fake_client, fixtures):
    known = upsert_employer(conn, "0704250 B.C. LTD.", "BC", source="esdc_positive", city="Burnaby",
                            postal_code="V5H 2G3", now="2026-10-12T00:00:00Z")
    elsewhere = upsert_employer(conn, "Harbour Foods Ltd.", "BC", source="esdc_positive", city="Victoria",
                                now="2026-10-12T00:00:00Z")
    mapping = {
        config.IRCC_NONCOMPLIANT_URL: (fixtures / "ircc_legend.html").read_bytes(),
        ircc.JSON_URL: _finding_json(
            ("Assi Supermarket", "0704250 BC Ltd.", "A-5593 Kingsway<br>Burnaby, BC"),
            ("Harbour Foods", "Harbour Foods Ltd.", "12 Main Street<br>Nanaimo, BC"),
            ("Cafe Italia", "Jeff Example", "62 Provost Street<br>New Glasgow, NS"),
            ("Sushi Five", "Golden Koi Food Ltd.", "115-1199 Lynn Valley Road<br>North Vancouver, BC, V7J 3H2"),
        ),
    }
    assert ircc.run(conn, fake_client(mapping), now="2026-10-13T00:00:00Z") == 4

    emp = conn.execute("SELECT * FROM employers WHERE id = ?", (known,)).fetchone()
    assert emp["street"] == "A-5593 Kingsway" and emp["street_source"] == "ircc"
    assert emp["postal_code"] == "V5H 2G3"
    names = {(r["raw_name"], r["source"]) for r in conn.execute(
        "SELECT raw_name, source FROM employer_names WHERE employer_id = ?", (known,))}
    assert ("Assi Supermarket", "ircc") in names and ("0704250 BC Ltd.", "ircc") in names
    assert ("0704250 B.C. LTD.", "esdc_positive") in names

    # A finding in another city links by name but does not lend its street.
    other = conn.execute("SELECT * FROM employers WHERE id = ?", (elsewhere,)).fetchone()
    assert other["street"] is None and other["street_source"] is None
    linked = conn.execute("SELECT employer_id FROM findings WHERE operating_name = 'Harbour Foods'").fetchone()[0]
    assert linked == elsewhere

    # A sole proprietor's profile is created under the operating name, a
    # company's under its legal name.
    cafe = conn.execute(
        "SELECT e.* FROM findings f JOIN employers e ON e.id = f.employer_id WHERE f.operating_name = 'Cafe Italia'"
    ).fetchone()
    assert cafe["display_name"] == "Cafe Italia" and cafe["street"] == "62 Provost Street"
    koi = conn.execute(
        "SELECT e.* FROM findings f JOIN employers e ON e.id = f.employer_id WHERE f.operating_name = 'Sushi Five'"
    ).fetchone()
    assert koi["display_name"] == "Golden Koi Food Ltd." and koi["postal_code"] == "V7J 3H2"
    assert koi["street"] == "115-1199 Lynn Valley Road" and koi["street_source"] == "ircc"

    # Running the enrichment again adds nothing.
    assert ircc.enrich_employers(conn, now="2026-10-14T00:00:00Z") == (0, 0)


def test_upsert_records_where_a_street_came_from(conn):
    eid = upsert_employer(conn, "Harbour Foods Ltd.", "BC", source="ircc", street="12 Main Street",
                          now="2026-10-12T00:00:00Z")
    upsert_employer(conn, "Harbour Foods Ltd", "BC", source="jobbank", street="99 Other Road",
                    now="2026-10-13T00:00:00Z")
    row = conn.execute("SELECT street, street_source FROM employers WHERE id = ?", (eid,)).fetchone()
    assert tuple(row) == ("12 Main Street", "ircc")


def test_creation_name_and_candidates():
    assert ircc.creation_name("Sushi Five", "Golden Koi Food Ltd.") == "Golden Koi Food Ltd."
    assert ircc.creation_name("Garage Pepin", "2164-8431 Québec Inc.") == "2164-8431 Québec Inc."
    assert ircc.creation_name("Cafe Italia", "Jeff Example") == "Cafe Italia"
    assert ircc.creation_name(None, "Jeff Example") == "Jeff Example"
    assert ircc.creation_name("Cafe Italia", None) == "Cafe Italia"
    assert ircc.creation_name(None, None) is None
    legal_first = ircc.candidate_ids("Assi Supermarket", "0704250 BC Ltd.", "BC")
    assert len(legal_first) == 2 and legal_first[0].startswith("emp-")
    assert ircc.candidate_ids("0704250 BC Ltd.", "0704250 B.C. LTD.", "BC") == legal_first[:1]
    assert ircc.candidate_ids(None, None, "BC") == []
