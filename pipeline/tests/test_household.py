"""Private households on the ESDC lists are kept out like Job Bank household postings.

A row goes only when the occupation is a household one (NOC 4411, 4412, 44100,
44101, or the title when no code is given) and the employer name reads as a
person. Every name here is invented.
"""

import pytest

from lmia_pipeline import status
from lmia_pipeline.db import upsert_employer
from lmia_pipeline.household import (
    is_household_occupation, is_household_record, is_household_row, reads_as_person, remove_household_rows,
)
from lmia_pipeline.sources import esdc
from lmia_pipeline.sources.esdc import load_resource

NOW = "2026-10-18T00:00:00Z"

CHILD_2011 = ("4411", "Home child care providers")
SUPPORT_2011 = ("4412", "Home support workers, housekeepers and related occupations")
CHILD_2021 = ("44100", "Home child care providers")
SUPPORT_2021 = ("44101", "Home support workers, caregivers and related occupations")


@pytest.mark.parametrize("employer, occupation", [
    ("Ana Ferreira", CHILD_2011),
    ("Walter Ian Penner", SUPPORT_2011),
    ("Owen T Mercer", SUPPORT_2021),
    ("J.R. Okafor", CHILD_2021),
    ("NADIA OKONKWO", SUPPORT_2021),
    ("lucia de la vega", CHILD_2011),
    ("Santos, Maria", CHILD_2011),
    ("Priya Sandhu, Arjun Sandhu", CHILD_2011),
    ("Maria Clara Santos, Jose Luis Santos", SUPPORT_2011),
    ("Tom Walsh and Erin Walsh", SUPPORT_2021),
    ("Grace Mwangi (Peter Mwangi)", SUPPORT_2011),
    ("Private Childcare/Reyes Family", CHILD_2011),
    # Surnames that are also words on the Job Bank business list.
    ("Mary White", CHILD_2011),
    ("Daniel West", SUPPORT_2021),
])
def test_a_person_with_a_household_occupation_is_left_out(employer, occupation):
    assert is_household_record(employer, *occupation, "Toronto, ON M4C 1A1") is True


@pytest.mark.parametrize("employer, occupation", [
    # Businesses named after their owner stay.
    ("Penner Farms", SUPPORT_2011),
    ("John Penner Farms Ltd.", SUPPORT_2011),
    ("Harjit Gill Trucking", SUPPORT_2021),
    ("Gill Transport Inc", CHILD_2021),
    ("Rosa Lima Consulting Services", SUPPORT_2011),
    ("Okafor Law", CHILD_2011),
    ("Ana Ferreira o/a Little Steps Dayhome", CHILD_2011),
    ("Ana Ferreira Childcare", CHILD_2011),
    ("Maple Grove Seniors Society", SUPPORT_2011),
    # The usual employers of home support workers.
    ("Sunrise Home Care Ltd.", SUPPORT_2021),
    ("Bright Path Health Services", SUPPORT_2021),
    ("Coopérative de solidarité de services à domicile de Laval", SUPPORT_2021),
    ("CIUSSS de l'Estrie", SUPPORT_2021),
    ("Aide chez soi Rive-Nord", SUPPORT_2011),
    ("Corporation of the County of Lanark", SUPPORT_2011),
    ("Cedar River First Nation", CHILD_2021),
    ("1234567 Ontario Inc.", CHILD_2011),
    ("9123-4567 Québec inc.", SUPPORT_2011),
    ("Home sweet home", CHILD_2011),
    ("Maple Grove Care Centre", SUPPORT_2011),
    ("Penner Family Services Association", SUPPORT_2011),
])
def test_a_business_with_a_household_occupation_stays(employer, occupation):
    assert is_household_record(employer, *occupation, "Toronto, ON M4C 1A1") is False


@pytest.mark.parametrize("occupation", [
    ("7511", "Transport truck drivers"),
    ("8431", "General farm workers"),
    ("63200", "Cooks"),
    ("6312", "Executive housekeepers"),
    ("62021", "Executive housekeepers"),
    ("4214", "Early childhood educators and assistants"),
    (None, None),
])
def test_a_person_with_any_other_occupation_stays(occupation):
    assert is_household_record("Ana Ferreira", *occupation, "Toronto, ON M4C 1A1") is False


@pytest.mark.parametrize("title", [
    "Home child care providers",
    "Home support workers, housekeepers and related occupations",
    "Home support workers, caregivers and related occupations",
    "Nanny",
    "Live-in caregiver",
    "Housekeeper",
    "Gardiens/gardiennes d'enfants en milieu familial",
    "Gardiens/gardiennes d’enfants en milieu familial",
    "Aides familiaux résidants/aides familiales résidantes, aides de maintien à domicile et personnel assimilé",
    "Aides de maintien à domicile, aides familiaux/aides familiales et personnel assimilé",
    "Aide familiale",
])
def test_the_title_decides_when_there_is_no_code(title):
    assert is_household_occupation(None, title) is True
    assert is_household_record("Ana Ferreira", None, title) is True


@pytest.mark.parametrize("title", [
    "Executive housekeepers",
    "Gouvernants principaux/gouvernantes principales",
    "Light duty cleaners",
    "Early childhood educators and assistants",
    "Éducateurs/éducatrices et aides-éducateurs/aides-éducatrices de la petite enfance",
    "Nurse aides, orderlies and patient service associates",
    "Aides-infirmiers/aides-infirmières, préposés/préposées aux bénéficiaires",
])
def test_other_titles_are_not_household_ones(title):
    assert is_household_occupation(None, title) is False


def test_the_code_wins_over_the_title():
    assert is_household_occupation("6312", "Housekeeper") is False
    assert is_household_occupation(" 44101 ", None) is True


def test_names_that_are_not_names():
    for name in (None, "", "   ", "A B", "Ana", "Ana Maria Clara Lucia Santos", "Ana Ferreira #2", "Ana@Ferreira Care"):
        assert reads_as_person(name) is False, name


def rec(name, code, title, address="Toronto, ON M4C 1A1"):
    return {"employer_raw": name, "noc_code": code, "noc_title": title, "address_raw": address}


def test_the_row_form_reads_the_same_fields():
    assert is_household_row(rec("Ana Ferreira", *CHILD_2011))
    assert not is_household_row(rec("Sunrise Home Care Ltd.", *CHILD_2011))


FILE_2024 = (
    '"Employers who were issued a positive Labour Market Impact Assessment (LMIA) by stream in 2024 (July-September)",,,,,\n'
    "Province/Territory,Stream,Employer,Address,Occupation,Approved Positions\n"
    'Ontario,Low Wage,Ana Ferreira,"Toronto, ON M4C 1A1",44100-Home child care providers,1\n'
    'Ontario,Low Wage,Sunrise Home Care Ltd.,"Toronto, ON M4C 1A1","44101-Home support workers, caregivers and related occupations",3\n'
    'Ontario,Primary Agriculture,Harjit Gill,"Brampton, ON L6P 1A1",85100-Livestock labourers,2\n'
    'Ontario,Low Wage,Priya Sandhu,"Brampton, ON L6P 1A1",63200-Cooks,1\n'
    'Alberta,Low Wage,Tom Walsh and Erin Walsh,"Calgary, AB T2T 1A1","44101-Home support workers, caregivers and related occupations",1\n'
).encode("utf-8")
RES_2024 = {"id": "res-2024q3", "name": "2024Q3 positive", "url": "https://example.invalid/tfwp_2024q3_pos_en.csv",
            "created": "2024-12-01T00:00:00"}


def test_the_loader_skips_household_rows(conn):
    assert load_resource(conn, "positive", RES_2024, FILE_2024, now=NOW) == 3
    names = sorted(r["employer_raw"] for r in conn.execute("SELECT employer_raw FROM esdc_records"))
    # A person named with a farm occupation or a cook's job stays: only the
    # household occupation makes a name a household.
    assert names == ["Harjit Gill", "Priya Sandhu", "Sunrise Home Care Ltd."]
    shown = {r["display_name"] for r in conn.execute("SELECT display_name FROM employers")}
    assert not shown & {"Ana Ferreira", "Tom Walsh and Erin Walsh"}
    seen = {r["raw_name"] for r in conn.execute("SELECT raw_name FROM employer_names")}
    assert not seen & {"Ana Ferreira", "Tom Walsh and Erin Walsh"}
    assert conn.execute("SELECT rows_loaded FROM esdc_resources").fetchone()[0] == 3


def _load_like_the_old_parser(conn):
    """Rows as a loader without the rule stored them, with employers and side tables."""
    for rid, lst, n in (("res-2018q1", "positive", 4), ("res-2024q3n", "negative", 1)):
        conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, "
                     "rows_loaded, loaded_at) VALUES (?, ?, 'p', 'n', 'u', '2024-12-01', ?, 1, ?, ?)", (rid, lst, rid, n, NOW))
    rows = [
        ("positive", "2018Q1", "Ana Ferreira", "ON", "4411", "Home child care providers", 1, "res-2018q1"),
        ("positive", "2018Q1", "Sunrise Home Care Ltd.", "ON", "4412", SUPPORT_2011[1], 3, "res-2018q1"),
        # This person also has a cook's row: that row and the employer stay.
        ("positive", "2018Q1", "Priya Sandhu", "ON", "4411", "Home child care providers", 1, "res-2018q1"),
        ("positive", "2018Q1", "Priya Sandhu", "ON", "6322", "Cooks", 2, "res-2018q1"),
        ("negative", "2024Q3", "Mary White", "AB", "44101", SUPPORT_2021[1], 4, "res-2024q3n"),
    ]
    ids = {}
    for i, (lst, period, name, prov, code, title, positions, rid) in enumerate(rows):
        eid = upsert_employer(conn, name, prov, source=f"esdc_{lst}", now=NOW)
        ids[name] = eid
        conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, address_raw, noc_code, "
                     "noc_title, positions, resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (lst, period, eid, name, prov, "Toronto, ON M4C 1A1", code, title, positions, rid, f"h{i}"))
    conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
                 "VALUES (?, 'repeat_applicant', 'not_triggered', 'One application.', '0.2', ?)", (ids["Ana Ferreira"], NOW))
    conn.execute("INSERT INTO registry_checks (employer_id, registry, checked_at) VALUES (?, 'corporations_canada', ?)",
                 (ids["Mary White"], NOW))
    conn.execute("INSERT INTO registry_matches (employer_id, registry, registry_id, legal_name, grade, checked_at) "
                 "VALUES (?, 'corporations_canada', '1234567', 'WHITE HOLDINGS INC.', 'possible', ?)", (ids["Mary White"], NOW))
    conn.commit()
    status.recompute(conn, now=NOW)
    return ids


def test_the_cleanup_removes_loaded_rows_once(conn):
    ids = _load_like_the_old_parser(conn)
    assert remove_household_rows(conn) == {"rows": 3, "positions": 6, "employers": 2}

    left = sorted((r["employer_raw"], r["noc_code"]) for r in conn.execute("SELECT employer_raw, noc_code FROM esdc_records"))
    assert left == [("Priya Sandhu", "6322"), ("Sunrise Home Care Ltd.", "4412")]
    employers = {r["id"] for r in conn.execute("SELECT id FROM employers")}
    gone = [ids["Ana Ferreira"], ids["Mary White"]]
    assert not employers & set(gone)
    assert ids["Priya Sandhu"] in employers
    for table in ("employer_names", "indicators", "registry_checks", "registry_matches"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE employer_id IN (?, ?)", gone).fetchone()[0]
        assert n == 0, table
    loaded = dict(conn.execute("SELECT resource_id, rows_loaded FROM esdc_resources").fetchall())
    assert loaded == {"res-2018q1": 2, "res-2024q3n": 0}

    assert remove_household_rows(conn) == {"rows": 0, "positions": 0, "employers": 0}
    status.recompute(conn, now=NOW)
    sandhu = conn.execute("SELECT approved_positions FROM employers WHERE id = ?", (ids["Priya Sandhu"],)).fetchone()[0]
    assert sandhu == 2


def test_the_esdc_stage_runs_the_cleanup_and_logs_it(conn, fake_client):
    _load_like_the_old_parser(conn)
    esdc.run(conn, fake_client({}), now=NOW)  # every listing answers 404
    assert conn.execute("SELECT COUNT(*) FROM esdc_records").fetchone()[0] == 2
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'esdc' ORDER BY id DESC").fetchone()[0]
    assert "household_rows_removed=3 household_employers_removed=2" in detail
    assert "Ana Ferreira" not in detail
    esdc.run(conn, fake_client({}), now=NOW)
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'esdc' ORDER BY id DESC").fetchone()[0]
    assert "household" not in detail
