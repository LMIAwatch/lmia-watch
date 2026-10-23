"""The rules the public-record sources share (sources/matching.py) and what a profile carries of them.

Every person name here is invented.
"""

import json

import pytest

from lmia_pipeline import cli, export_static
from lmia_pipeline.db import upsert_employer
from lmia_pipeline.normalize import business_number
from lmia_pipeline.sources import matching

NOW = "2026-10-22T00:00:00Z"


@pytest.mark.parametrize("raw, expected", [
    ("835752437", "835752437"),
    ("818620981RC0001", "818620981"),
    ("818 620 981 RC0001", "818620981"),
    ("123-456-789", None),          # fails the check digit
    ("846087173", None),            # a typed number from the grants file that fails it
    ("000000000", None),            # a placeholder passes the check digit and is refused
    ("82951529", None),             # eight digits
    ("", None),
    (None, None),
])
def test_business_number(raw, expected):
    assert business_number(raw) == expected


@pytest.mark.parametrize("name", [
    "Ana Ferreira", "OWEN T MERCER", "Priya Sandhu, Arjun Sandhu", "Tom Walsh and Erin Walsh",
    # "Law" is a surname here, not a firm.
    "Ann Law", "Lena Okafor, Mira Law",
    # A sole proprietor operating under a business name: the legal name is a person.
    "Ana Ferreira o/a Little Steps Farm",
    "Ana Ferreira|Ana Ferreira",
])
def test_names_that_read_as_people(name):
    assert matching.is_person_name(name) is True
    assert matching.business_name(name) is None


@pytest.mark.parametrize("name", [
    "Dykshoorn Farms Ltd.", "Neil Squire Society", "John Penner Farms Ltd.", "0956796 B.C. Ltd.",
    "Okafor Law Corporation", "Canadian Cattlemen's Association", "Ferme Marc Duval inc.", "S. K. TRUCKING LTD.",
])
def test_names_that_read_as_businesses(name):
    assert matching.is_person_name(name) is False
    assert matching.business_name(name) == name


@pytest.mark.parametrize("norm, common", [
    ("", True),
    ("realize", True),
    ("katalyst", True),
    ("west coast services", True),
    ("golden group", True),
    ("canadian farms", True),
    ("kampman farms", False),
    ("pine cliff energy", False),
    ("1776155 alberta", False),
    ("canadian cattlemens association", False),
])
def test_common_names(norm, common):
    assert matching.is_common_name(norm) is common


def test_grades():
    # The legal name with the place key is exact, with only the province probable.
    assert matching.grade("legal", True, True, "realize") == "exact"
    assert matching.grade("legal", False, True, "kampman farms") == "probable"
    # A name alone never matches, and a common one needs the place key.
    assert matching.grade("legal", False, False, "kampman farms") is None
    assert matching.grade("legal", False, True, "realize") is None
    # A name the record operates under needs the place key and is probable at best.
    assert matching.grade("other", True, True, "chilliwack cattle sales") == "probable"
    assert matching.grade("other", False, True, "chilliwack cattle sales") is None
    assert matching.grade("other", True, True, "rosedale") is None


def test_places_read_alike():
    assert matching.fold_city("ST. ALBERT") == matching.fold_city("Saint-Albert") == matching.fold_city("St Albert")
    assert matching.fold_city("Lamèque|Lamèque") == "lameque"
    assert matching.postal_code("\nv4g0a2") == "V4G 0A2" and matching.postal_code("CANADA") is None
    assert matching.province_of("Manitoba", None) == "MB" and matching.province_of("N/A", "T2E 7H7") == "AB"
    assert matching.province_of("Oxfordshire", None) is None


def test_employer_places_gather_every_record(conn):
    eid = upsert_employer(conn, "Corvid Orchard Ltd.", "BC", source="esdc_positive", city="Kelowna",
                          postal_code="V1Y 1A1", now=NOW)
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, city, postal_code, resource_id, row_hash) "
        "VALUES ('positive', '2025Q1', ?, 'Corvid Orchard Ltd.', 'Oliver', 'V0H 1T0', 'r', 'h1')", (eid,))
    places = matching.employer_places(conn, [eid])[eid]
    assert places.province == "BC"
    assert places.postals == {"V1Y 1A1", "V0H 1T0"} and places.areas == {"V1Y", "V0H"}
    assert places.cities == {"kelowna", "oliver"}


def test_stages_run_after_the_registries_and_before_the_reference_tables():
    order = cli.STAGES
    assert order.index("registry") < order.index("grants") < order.index("alberta") < order.index("fmcsa") < order.index("wages")
    args = cli.build_parser().parse_args(["run", "--grants", "--alberta", "--fmcsa"])
    assert args.grants and args.alberta and args.fmcsa


def test_a_profile_carries_the_newest_twenty_agreements_and_the_count(conn, tmp_path):
    funded = upsert_employer(conn, "Corvid Orchard Ltd.", "BC", source="esdc_positive", now=NOW)
    plain = upsert_employer(conn, "Harbour Haul Ltd.", "NS", source="esdc_positive", now=NOW)
    for i in range(25):
        key = f"test-org,R-{i:02d}"
        conn.execute(
            "INSERT INTO federal_grants (agreement_key, ref_number, amendment_number, owner_org, department_en, "
            "department_fr, legal_name, norm_name, program_en, program_fr, agreement_type, agreement_value, start_date, "
            "loaded_at) VALUES (?, ?, 1, 'test-org', 'Test Department', 'Ministère de test', 'Corvid Orchard Ltd.', "
            "'corvid orchard', 'Program', 'Programme', 'G', ?, ?, ?)",
            (key, f"R-{i:02d}", 1000.0 * i, f"20{10 + i}-04-01", NOW))
        conn.execute("INSERT INTO grant_matches VALUES (?, ?, 'exact', 'name_postal_area', ?)", (funded, key, NOW))
    conn.commit()
    export_static.write_profiles(conn, tmp_path)
    shard = json.loads((tmp_path / "profiles" / f"{export_static.shard_key(funded)}.json").read_text(encoding="utf-8"))
    prof = shard[funded]
    assert prof["grants_total"] == 25 and len(prof["grants"]) == export_static.GRANTS_SHOWN == 20
    assert [g["start_date"] for g in prof["grants"][:2]] == ["2034-04-01", "2033-04-01"]
    assert prof["grants"][0] == {
        "grade": "exact", "basis": "name_postal_area", "ref_number": "R-24", "amendment_number": 1,
        "owner_org": "test-org", "department_en": "Test Department", "department_fr": "Ministère de test",
        "program_en": "Program", "program_fr": "Programme", "agreement_type": "G", "agreement_value": 24000.0,
        "start_date": "2034-04-01", "end_date": None,
    }
    other = json.loads((tmp_path / "profiles" / f"{export_static.shard_key(plain)}.json").read_text(encoding="utf-8"))
    assert (other[plain]["grants"], other[plain]["grants_total"], other[plain]["alberta"], other[plain]["us_carrier"]) == (
        [], 0, [], [])
