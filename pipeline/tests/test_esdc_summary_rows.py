"""Summary, footnote and heading lines in the ESDC files are not employers.

The 2014 positive file ends with "Other employers" (5,967 positions) and
"Total" (30,396), and the 2014 and 2015 files with "Notes:" and two numbered
footnotes; the 2015 negative file repeats one province heading in two cells.
An earlier parser loaded all of them as employer rows.
"""

import json

from lmia_pipeline import config, export_static, indicators, status
from lmia_pipeline.db import get_meta, set_meta, upsert_employer
from lmia_pipeline.sources import esdc
from lmia_pipeline.sources.esdc import is_summary_row, load_resource, remove_summary_rows

NOW = "2026-10-18T00:00:00Z"

FILE_2014 = (
    '"Employers who have requested a Labour Market Impact Assessment (LMIA) and were issued a positive LMIA between June 20 and December 31, 2014 inclusively, by province/territory ",,\r\r\n'
    "Alberta,Alberta,\r\r\n"
    "Employer ,Address,Positions\r\r\n"
    'Harbour Farms,"Box 3, Brooks, AB  T1R 0N9",3\r\r\n'
    'Total Maintenance Services Inc.,"10333 56th Avenue, Edmonton, AB  T6R 0X5",2\r\r\n'
    "Outside Canada,,\r\r\n"
    "Employer ,Address,Positions\r\r\n"
    "Zetec Inc.,,3\r\r\n"
    'Other employers,,"5,967"\r\r\n'
    'Total ,,"30,396"\r\r\n'
    "Notes:,,\r\r\n"
    '"1. This list excludes all personal names, such as employers of caregivers.",,\r\r\n'
    '"2. The data provided in this report tracks temporary foreign worker (TFW) positions on Labour Market Impact Assessments only.",,\r\r\n'
).encode("cp1252")
RES_2014 = {"id": "res-2014", "name": "2014 positive employers", "url": "https://example.invalid/positive_employers_en.csv",
            "created": "2016-10-21T00:00:00"}


def rec(name, address=None, noc=None, positions=None, lmias=None, title=None):
    return {"employer_raw": name, "address_raw": address, "noc_code": noc, "noc_title": title,
            "positions": positions, "lmias": lmias}


def test_the_rule_reads_the_row_not_a_list_of_names():
    assert is_summary_row(rec("Total", positions=30396))
    assert is_summary_row(rec("Total ", positions=30396))
    assert is_summary_row(rec("Other employers", positions=5967))
    assert is_summary_row(rec("Grand total:", positions=1))
    assert is_summary_row(rec("Autres employeurs", positions=4))
    assert is_summary_row(rec("Notes:"))
    assert is_summary_row(rec("1. This list excludes all personal names."))
    assert is_summary_row(rec("Alberta", address="Alberta"))
    # Real employers: a place, an occupation or a count with a name that is not a summary word.
    assert not is_summary_row(rec("Total", address="Edmonton, AB T6R 0X5", positions=2))
    assert not is_summary_row(rec("Total Lubrication Management Company", positions=5))
    assert not is_summary_row(rec("Total", noc="7511", title="Transport truck drivers", positions=2))
    assert not is_summary_row(rec("Zetec Inc.", positions=3))
    assert not is_summary_row(rec("Alberta 3210 Holdings Ltd", address="Hinton, AB T7V 1T1", positions=2))
    assert not is_summary_row(rec("Alberta", address="Calgary, AB T2C 2G5", positions=1))
    assert not is_summary_row(rec("Other Employers Inc", positions=1))


def test_parser_skips_summary_rows_and_reads_a_repeated_heading(conn):
    assert load_resource(conn, "positive", RES_2014, FILE_2014, now=NOW) == 3
    got = {r["employer_raw"]: r for r in conn.execute("SELECT * FROM esdc_records")}
    assert sorted(got) == ["Harbour Farms", "Total Maintenance Services Inc.", "Zetec Inc."]
    assert got["Zetec Inc."]["province"] == "XX"
    assert got["Harbour Farms"]["province"] == "AB"
    names = {r["display_name"] for r in conn.execute("SELECT display_name FROM employers")}
    assert not names & {"Total", "Other employers", "Notes:", "Alberta"}
    assert conn.execute("SELECT rows_loaded FROM esdc_resources").fetchone()[0] == 3


def _load_like_the_old_parser(conn):
    """The rows as the earlier parser stored them, with their employers and side tables."""
    conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                 "loaded_at) VALUES ('res-2014', 'positive', '2014', 'n', 'u', '2016-10-21', 's', 1, 5, ?)", (NOW,))
    conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                 "loaded_at) VALUES ('res-n2015', 'negative', '2015', 'n', 'u', '2016-10-21', 't', 1, 2, ?)", (NOW,))
    rows = [
        ("positive", "2014", "Harbour Farms", "AB", "Box 3, Brooks, AB  T1R 0N9", 3, "res-2014"),
        ("positive", "2014", "Other employers", "XX", None, 5967, "res-2014"),
        ("positive", "2014", "Total", "XX", None, 30396, "res-2014"),
        ("positive", "2014", "Notes:", "XX", None, None, "res-2014"),
        ("positive", "2014", "1. This list excludes all personal names.", "XX", None, None, "res-2014"),
        ("negative", "2015", "Alberta", "SK", "Alberta", None, "res-n2015"),
        ("negative", "2015", "Prairie Diner Ltd", "SK", "Regina, SK  S4P 1A1", 1, "res-n2015"),
    ]
    ids = {}
    for i, (lst, period, name, prov, address, positions, rid) in enumerate(rows):
        eid = upsert_employer(conn, name, prov, source=f"esdc_{lst}", now=NOW)
        ids[name] = eid
        conn.execute("INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, address_raw, positions, "
                     "resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (lst, period, eid, name, prov, address, positions, rid, f"h{i}"))
    conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
                 "VALUES (?, 'high_volume', 'triggered', '30396 positions approved in 2014.', '0.2', ?)", (ids["Total"], NOW))
    conn.execute("INSERT INTO registry_checks (employer_id, registry, checked_at) VALUES (?, 'corporations_canada', ?)",
                 (ids["Other employers"], NOW))
    # The "Alberta" heading also names an employer that has a posting: that employer stays, its list row goes.
    conn.execute("INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, province, first_seen, last_seen, "
                 "flag_current, flag_first, url, updated_at) VALUES (9, ?, 'Alberta', 'cook', 'SK', ?, ?, 'requested', "
                 "'requested', 'u', ?)", (ids["Alberta"], NOW, NOW, NOW))
    conn.commit()
    status.recompute(conn, now=NOW)
    return ids


def test_cleanup_on_a_loaded_database_is_idempotent(conn):
    ids = _load_like_the_old_parser(conn)
    assert conn.execute("SELECT approved_positions FROM employers WHERE id = ?", (ids["Total"],)).fetchone()[0] == 30396

    assert remove_summary_rows(conn) == {"rows": 5, "employers": 4}
    left = sorted(r["employer_raw"] for r in conn.execute("SELECT employer_raw FROM esdc_records"))
    assert left == ["Harbour Farms", "Prairie Diner Ltd"]
    employers = {r["id"] for r in conn.execute("SELECT id FROM employers")}
    gone = [ids[n] for n in ("Total", "Other employers", "Notes:", "1. This list excludes all personal names.")]
    assert not employers & set(gone)
    assert ids["Alberta"] in employers  # kept for its posting
    for table in ("employer_names", "indicators", "registry_checks"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE employer_id IN ({','.join('?' * len(gone))})", gone).fetchone()[0]
        assert n == 0, table
    loaded = dict(conn.execute("SELECT resource_id, rows_loaded FROM esdc_resources").fetchall())
    assert loaded == {"res-2014": 1, "res-n2015": 1}

    assert remove_summary_rows(conn) == {"rows": 0, "employers": 0}
    status.recompute(conn, now=NOW)
    assert conn.execute("SELECT COALESCE(SUM(positions), 0) FROM esdc_records WHERE period = '2014'").fetchone()[0] == 3
    alberta = conn.execute("SELECT refused_positions, current_status FROM employers WHERE id = ?", (ids["Alberta"],)).fetchone()
    assert tuple(alberta) == (0, "pending")


def test_the_esdc_stage_cleans_up_even_when_the_portal_is_down(conn, fake_client):
    _load_like_the_old_parser(conn)
    esdc.run(conn, fake_client({}), now=NOW)  # every listing answers 404
    assert conn.execute("SELECT COUNT(*) FROM esdc_records").fetchone()[0] == 2
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'esdc' ORDER BY id DESC").fetchone()[0]
    assert "summary_rows_removed=5 employers_removed=4" in detail


def test_stats_carry_the_current_rules_version(conn, tmp_path, monkeypatch):
    # A database last written under an older rule set: the next recompute and
    # export must publish the version the code computes with, so the
    # Methodology page cannot go on showing a stale one.
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    upsert_employer(conn, "Harbour Farms", "AB", source="esdc_positive", now=NOW)
    set_meta(conn, "rules_version", "0.1")
    conn.commit()
    status.recompute(conn, now=NOW)
    assert get_meta(conn, "rules_version") == indicators.RULES_VERSION
    export_static.export_static(conn, tmp_path / "static")
    stats = json.loads((tmp_path / "static" / "stats.json").read_text(encoding="utf-8"))
    assert stats["rules_version"] == indicators.RULES_VERSION
