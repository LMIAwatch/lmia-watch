"""The identity migration, on a database built with version 1 of the normalization."""

import re
import unicodedata

from lmia_pipeline import migrate
from lmia_pipeline.db import get_meta, set_meta
from lmia_pipeline.normalize import NORMALIZE_VERSION, employer_id, norm_name

T0 = "2026-10-01T00:00:00Z"
NOW = "2026-10-17T00:00:00Z"
V1_SUFFIXES = {
    "ltd", "ltee", "ltée", "limited", "limitee", "limitée", "inc", "incorporated", "incorporee", "incorporée",
    "corp", "corporation", "ulc", "llp", "llc", "lp", "co", "company", "cie", "compagnie", "senc", "sencrl",
    "enr", "enrg", "partnership", "plc",
}


def v1_norm(raw: str) -> str:
    """norm_name as it was before normalize_version 2."""
    text = re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", raw).casefold()).replace("_", " ")
    tokens = text.split()
    while tokens and tokens[-1] in V1_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def v1_id(raw: str, province: str) -> str:
    return employer_id(v1_norm(raw), province)


def employer(conn, raw: str, province: str, *, source: str = "esdc_positive", city: str | None = None,
             postal: str | None = None, street: str | None = None, first: str | None = None,
             last: str | None = None) -> str:
    eid = v1_id(raw, province)
    conn.execute(
        "INSERT OR IGNORE INTO employers (id, display_name, norm_name, province, city, postal_code, street, "
        "street_source, first_seen, last_seen, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eid, raw, v1_norm(raw), province, city, postal, street, "jobbank" if street else None, first, last, T0),
    )
    conn.execute("INSERT OR IGNORE INTO employer_names VALUES (?, ?, ?)", (eid, raw, source))
    return eid


def esdc_row(conn, eid: str, raw: str, period: str, positions: int = 1) -> None:
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, lmias, positions, resource_id, "
        "row_hash) VALUES ('positive', ?, ?, ?, 'BC', 1, ?, 'r', ?)",
        (period, eid, raw, positions, f"{eid}{raw}{period}"),
    )


def seed(conn) -> dict[str, str]:
    ids: dict[str, str] = {}
    # 1. Trade-name suffixes: three employers for one company.
    ids["assi"] = employer(conn, "0704250 BC Ltd.", "BC", city="Burnaby", postal="V5H 2G3",
                           first="2016-01-01", last="2026-03-31")
    ids["assi_dba"] = employer(conn, "0704250 BC Ltd. dba Assi Supermarket", "BC", city="Burnaby",
                               first="2015-01-01", last="2015-12-31")
    ids["assi_oa"] = employer(conn, "0704250 BC Ltd. o/a Assi Supermarket", "BC", first="2019-01-01",
                              last="2019-06-30")
    esdc_row(conn, ids["assi"], "0704250 BC Ltd.", "2026Q1", 5)
    esdc_row(conn, ids["assi_dba"], "0704250 BC Ltd. dba Assi Supermarket", "2015", 1)
    esdc_row(conn, ids["assi_oa"], "0704250 BC Ltd. o/a Assi Supermarket", "2019Q1-Q2", 3)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, "
        "flag_first, url, updated_at) VALUES (7, ?, '0704250 BC Ltd. o/a Assi Supermarket', ?, ?, 'requested', "
        "'requested', 'u', ?)", (ids["assi_oa"], T0, T0, T0))
    # 4. A finding with an address and an operating name the profile lacks.
    conn.execute(
        "INSERT INTO findings (employer_id, operating_name, legal_name, address, decision_date, row_hash, fetched_at) "
        "VALUES (?, 'Assi Supermarket', '0704250 BC Ltd.', 'A-5593 Kingsway, Burnaby, BC', '2024-02-01', 'f1', ?)",
        (ids["assi"], T0))
    for eid, when in ((ids["assi"], "2026-09-30T00:00:00Z"), (ids["assi_dba"], "2026-09-30T00:00:00Z")):
        conn.execute("INSERT INTO registry_checks VALUES (?, 'bc_orgbook', ?)", (eid, when))
    for eid, state in ((ids["assi"], "not_triggered"), (ids["assi_dba"], "triggered"), (ids["assi_oa"], "triggered")):
        conn.execute("INSERT INTO indicators VALUES (?, 'repeat_applicant', ?, 'b', '0.1', ?)", (eid, state, T0))

    # 3. Dotted abbreviations: the list spells "B.C.", Job Bank "BC", and the
    # OrgBook hit graded against "1116089 b c" was only possible.
    ids["dotted"] = employer(conn, "1116089 B.C. LTD.", "BC", first="2020-01-01", last="2020-03-31")
    ids["plain"] = employer(conn, "1116089 BC Ltd", "BC", source="jobbank", street="9 Main Street",
                            first="2026-09-01", last="2026-10-01")
    esdc_row(conn, ids["dotted"], "1116089 B.C. LTD.", "2020Q1")
    esdc_row(conn, ids["plain"], "1116089 BC Ltd", "2026Q1")
    conn.execute(
        "INSERT INTO registry_matches VALUES (?, 'bc_orgbook', 'BC1116089', '1116089 B.C. LTD.', 'BC', 'ACT', "
        "'2017-04-03', 'possible', ?)", (ids["plain"], T0))

    # Accents, and initials that only change the id.
    ids["accent"] = employer(conn, "Ferme Célijean S.E.N.C.", "QC", first="2018-01-01", last="2018-03-31")
    ids["plain_accent"] = employer(conn, "Ferme Celijean", "QC", first="2022-01-01", last="2022-03-31")
    esdc_row(conn, ids["accent"], "Ferme Célijean S.E.N.C.", "2018Q1")
    esdc_row(conn, ids["plain_accent"], "Ferme Celijean", "2022Q1")
    ids["initials"] = employer(conn, "J M Peeters Nurseries Ltd", "ON", first="2021-01-01", last="2021-03-31")
    esdc_row(conn, ids["initials"], "J M Peeters Nurseries Ltd", "2021Q1")
    esdc_row(conn, ids["initials"], "J.M. Peeters Nurseries Ltd.", "2021Q2")

    # A findings-only employer created under its operating name by version 1.
    ids["sushi"] = employer(conn, "Sushi Five", "BC", source="ircc", city="North Vancouver")
    conn.execute(
        "INSERT INTO findings (employer_id, operating_name, legal_name, address, decision_date, row_hash, fetched_at) "
        "VALUES (?, 'Sushi Five', 'Golden Koi Food Ltd.', '115-1199 Lynn Valley Road, North Vancouver, BC, V7J 3H2', "
        "'2023-05-01', 'f2', ?)", (ids["sushi"], T0))

    # A federal corporation the employer spells with an abbreviation.
    ids["federal"] = employer(conn, "7286139 Can. Ltd.", "QC", first="2019-01-01", last="2019-03-31")
    esdc_row(conn, ids["federal"], "7286139 Can. Ltd.", "2019Q1")
    conn.execute(
        "INSERT INTO federal_corporations VALUES ('7286139', '7286139 CANADA LTD.', ?, 'Active', '2009-11-26', "
        "'Sherbrooke', 'QC', 'J1M 1J2', 'u')", (v1_norm("7286139 CANADA LTD."),))
    conn.execute("INSERT INTO registry_checks VALUES (?, 'corporations_canada', ?)", (ids["federal"], T0))

    # Untouched by the new rules.
    ids["steady"] = employer(conn, "Jealous Fruits Ltd.", "BC", first="2020-01-01", last="2020-03-31")
    esdc_row(conn, ids["steady"], "Jealous Fruits Ltd.", "2020Q1")
    conn.execute("INSERT INTO registry_checks VALUES (?, 'bc_orgbook', ?)", (ids["steady"], T0))
    conn.commit()
    return ids


def test_migration_merges_rewrites_and_enriches(conn):
    ids = seed(conn)
    before = conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0]
    report = migrate.ensure_current(conn, now=NOW)
    assert report is not None
    assert get_meta(conn, "normalize_version") == str(NORMALIZE_VERSION)
    assert report.employers_before == before == 11
    assert report.employers_after == 7

    assi = employer_id("0704250 bc", "BC")
    assert assi == ids["assi"]  # the legal-name spelling keeps its id
    emp = conn.execute("SELECT * FROM employers WHERE id = ?", (assi,)).fetchone()
    assert emp["first_seen"] == "2015-01-01"                     # earliest of the three
    assert emp["approved_positions"] == 9 and emp["pending_count"] == 1
    assert emp["current_status"] == "pending"
    assert emp["street"] == "A-5593 Kingsway" and emp["street_source"] == "ircc"
    assert emp["finding_count"] == 1
    for old in (ids["assi_dba"], ids["assi_oa"]):
        assert conn.execute("SELECT 1 FROM employers WHERE id = ?", (old,)).fetchone() is None
        # A retired id points at the profile that took its records.
        assert conn.execute("SELECT new_id FROM employer_aliases WHERE old_id = ?", (old,)).fetchone()[0] == assi
    assert conn.execute("SELECT COUNT(*) FROM esdc_records WHERE employer_id = ?", (assi,)).fetchone()[0] == 3
    assert conn.execute("SELECT employer_id FROM jobbank_postings WHERE posting_id = 7").fetchone()[0] == assi
    names = {(r["raw_name"], r["source"]) for r in conn.execute(
        "SELECT raw_name, source FROM employer_names WHERE employer_id = ?", (assi,))}
    assert names == {
        ("0704250 BC Ltd.", "esdc_positive"),
        ("0704250 BC Ltd. dba Assi Supermarket", "esdc_positive"),
        ("0704250 BC Ltd. o/a Assi Supermarket", "esdc_positive"),
        ("Assi Supermarket", "esdc_positive"),
        ("Assi Supermarket", "ircc"),
        ("0704250 BC Ltd.", "ircc"),
    }
    # The survivor's own indicator row wins; the merged rows' checks go, so
    # OrgBook is asked again only for identities that changed.
    assert conn.execute("SELECT state FROM indicators WHERE employer_id = ?", (assi,)).fetchone()[0] == "not_triggered"
    assert conn.execute(
        "SELECT COUNT(*) FROM registry_checks WHERE registry = 'bc_orgbook' AND employer_id = ?", (assi,)
    ).fetchone()[0] == 1

    # Dotted and plain spellings are one employer, and the OrgBook hit is exact now.
    dotted = employer_id("1116089 bc", "BC")
    assert dotted == ids["plain"]
    match = conn.execute("SELECT * FROM registry_matches WHERE employer_id = ? AND registry = 'bc_orgbook'",
                         (dotted,)).fetchone()
    assert match["grade"] == "exact"
    row = conn.execute("SELECT * FROM employers WHERE id = ?", (dotted,)).fetchone()
    assert row["registry_grade"] == "exact" and row["first_seen"] == "2020-01-01"
    assert row["street"] == "9 Main Street" and row["street_source"] == "jobbank"

    # Accents fold; initials only change the id.
    assert conn.execute("SELECT COUNT(*) FROM esdc_records WHERE employer_id = ?",
                        (employer_id("ferme celijean", "QC"),)).fetchone()[0] == 2
    peeters = employer_id("jm peeters nurseries", "ON")
    assert peeters != ids["initials"]
    assert conn.execute("SELECT COUNT(*) FROM esdc_records WHERE employer_id = ?", (peeters,)).fetchone()[0] == 2
    assert conn.execute("SELECT norm_name FROM employers WHERE id = ?", (peeters,)).fetchone()[0] == "jm peeters nurseries"

    # The findings-only employer now carries the company's legal name.
    koi = employer_id(norm_name("Golden Koi Food Ltd."), "BC")
    finding = conn.execute("SELECT employer_id FROM findings WHERE row_hash = 'f2'").fetchone()[0]
    assert finding == koi
    koi_row = conn.execute("SELECT * FROM employers WHERE id = ?", (koi,)).fetchone()
    assert koi_row["display_name"] == "Golden Koi Food Ltd." and koi_row["street"] == "115-1199 Lynn Valley Road"
    assert koi_row["city"] == "North Vancouver" and koi_row["postal_code"] == "V7J 3H2"
    assert conn.execute("SELECT 1 FROM employers WHERE id = ?", (ids["sushi"],)).fetchone() is None
    koi_names = {r[0] for r in conn.execute("SELECT raw_name FROM employer_names WHERE employer_id = ?", (koi,))}
    assert koi_names == {"Sushi Five", "Golden Koi Food Ltd."}

    # The federal extract is normalized again and matched again.
    fed = employer_id("7286139 canada", "QC")
    assert conn.execute("SELECT norm_name FROM federal_corporations").fetchone()[0] == "7286139 canada"
    fed_match = conn.execute("SELECT * FROM registry_matches WHERE employer_id = ?", (fed,)).fetchone()
    assert fed_match["registry"] == "corporations_canada" and fed_match["grade"] == "exact"
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE registry = 'corporations_canada'").fetchone()[0] == 7

    # Untouched employers keep their id, their check and their updated_at.
    steady = conn.execute("SELECT * FROM employers WHERE id = ?", (ids["steady"],)).fetchone()
    assert steady is not None
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE employer_id = ? AND registry = 'bc_orgbook'",
                        (ids["steady"],)).fetchone()[0] == 1

    # Nothing points at an employer that no longer exists.
    for table in ("employer_names", "jobbank_postings", "esdc_records", "findings", "registry_matches", "indicators"):
        orphans = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE employer_id IS NOT NULL "
            f"AND employer_id NOT IN (SELECT id FROM employers)").fetchone()[0]
        assert orphans == 0, table
    # Every stored id is the hash of its stored normalized name.
    for r in conn.execute("SELECT id, norm_name, province FROM employers"):
        assert r["id"] == employer_id(r["norm_name"], r["province"])

    assert report.merge_groups == 3 and report.ids_changed == 7 and report.dropped == 0
    assert report.findings_relinked == 1 and report.streets_added == 2


def test_migration_runs_once_and_is_idempotent(conn):
    seed(conn)
    migrate.ensure_current(conn, now=NOW)
    snapshot = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
                for t in ("employers", "employer_names", "esdc_records", "findings", "registry_matches", "indicators")}
    assert migrate.ensure_current(conn, now="2026-10-18T00:00:00Z") is None
    again = migrate.rederive(conn, now="2026-10-18T00:00:00Z")
    assert again.employers_before == again.employers_after
    assert again.ids_changed == 0 and again.merge_groups == 0 and again.findings_relinked == 0
    for table, rows in snapshot.items():
        now_rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        if table == "employers":
            strip = lambda rs: [tuple(v for k, v in dict(r).items() if k != "updated_at") for r in rs]  # noqa: E731
            assert strip(now_rows) == strip(rows)
        elif table == "registry_matches":
            assert [tuple(r)[:8] for r in now_rows] == [tuple(r)[:8] for r in rows]
        else:
            assert [tuple(r) for r in now_rows] == [tuple(r) for r in rows], table


def test_fresh_database_only_records_the_version(conn):
    report = migrate.ensure_current(conn, now=NOW)
    assert report is not None and report.employers_before == 0 and report.employers_after == 0
    assert get_meta(conn, "normalize_version") == str(NORMALIZE_VERSION)


def test_newer_database_is_left_alone(conn):
    set_meta(conn, "normalize_version", NORMALIZE_VERSION + 1)
    assert migrate.ensure_current(conn, now=NOW) is None
