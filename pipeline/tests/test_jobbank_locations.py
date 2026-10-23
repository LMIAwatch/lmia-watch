"""Job Bank locations: the province is always a two-letter code or None.

Some stored postings held a province like ", ON" or ", AB T2C 2Z2" while
their city was right. The search listing cannot produce that (its pattern
takes two capital letters inside parentheses); the posting page can, when the
comma, and sometimes the postal code, sit inside the addressRegion element,
because the posting-page update replaces the listing's province. The inputs
below are the published fixtures with only that element changed.
"""

from __future__ import annotations

import pytest

from lmia_pipeline.db import upsert_employer
from lmia_pipeline.sources import jobbank
from lmia_pipeline.sources.jobbank import (
    parse_detail_page, parse_search_page, posting_url, repair_locations, search_url, split_location, split_region,
)

STAMP = "2026-10-22T00:00:00Z"
EMPTY = b"<html><body><div class='results-jobs'></div></body></html>"
# The location line of posting 50456228 exactly as the fixture holds it.
DETAIL_LOCATION = (
    '<span property="addressLocality">Brackendale</span>, <span property="addressRegion">BC</span>'
    '<span class="nomargin" property="postalCode">V0N 1H0</span>'
)


def _detail(fixtures, location: str) -> str:
    html = (fixtures / "jobbank_detail_50456228.html").read_text(encoding="utf-8")
    assert DETAIL_LOCATION in html
    return html.replace(DETAIL_LOCATION, location)


def _listing(fixtures, location: str) -> str:
    html = (fixtures / "jobbank_requested.html").read_text(encoding="utf-8")
    assert html.count("Brackendale (BC)") == 1
    return html.replace("Brackendale (BC)", location)


@pytest.mark.parametrize("raw, expected", [
    (", ON", ("ON", None)),
    (", BC", ("BC", None)),
    (", QC", ("QC", None)),
    (", AB T2C 2Z2", ("AB", "T2C 2Z2")),
    (", BC V1V 2X4", ("BC", "V1V 2X4")),
    (", bc v1v2x4", ("BC", "V1V 2X4")),
    ("ON", ("ON", None)),
    ("Ontario", ("ON", None)),
    ("Sudbury, ON", ("ON", None)),
    ("(NS)", ("NS", None)),
    (", ", (None, None)),
    (", ZZ", (None, None)),
    ("Head office outside of Canada", (None, None)),
    (None, (None, None)),
])
def test_split_region(raw, expected):
    assert split_region(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Sept-Îles (QC)", ("Sept-Îles", "QC", None)),
    ("Sudbury, ON", ("Sudbury", "ON", None)),
    ("Calgary, AB T2C 2Z2", ("Calgary", "AB", "T2C 2Z2")),
    ("Kelowna (BC) V1V 2X4", ("Kelowna", "BC", "V1V 2X4")),
    ("Dartmouth", ("Dartmouth", None, None)),
    ("Saint-Jean-sur-Richelieu, Montérégie", ("Saint-Jean-sur-Richelieu, Montérégie", None, None)),
    ("Somewhere (ZZ)", ("Somewhere", None, None)),
    ("", (None, None, None)),
])
def test_split_location(raw, expected):
    assert split_location(raw) == expected


def test_posting_page_with_the_comma_inside_the_region(fixtures):
    f = parse_detail_page(_detail(
        fixtures,
        '<span property="addressLocality">Brackendale</span><span property="addressRegion">, BC</span>'
        '<span class="nomargin" property="postalCode">V0N 1H0</span>',
    ))
    assert (f.city, f.province, f.postal_code) == ("Brackendale", "BC", "V0N 1H0")


def test_posting_page_with_the_postal_code_inside_the_region(fixtures):
    f = parse_detail_page(_detail(
        fixtures,
        '<span property="addressLocality">Brackendale</span><span property="addressRegion">, BC V0N 1H0</span>',
    ))
    assert (f.city, f.province, f.postal_code) == ("Brackendale", "BC", "V0N 1H0")


def test_postal_code_element_outranks_the_region_text(fixtures):
    f = parse_detail_page(_detail(
        fixtures,
        '<span property="addressLocality">Brackendale</span><span property="addressRegion">, BC V1V 2X4</span>'
        '<span class="nomargin" property="postalCode">V0N 1H0</span>',
    ))
    assert (f.province, f.postal_code) == ("BC", "V0N 1H0")


def test_search_listing_in_the_comma_form(fixtures):
    items = {i.posting_id: i for i in parse_search_page(_listing(fixtures, "Brackendale, BC V0N 1H0"))}
    pink = items[50456228]
    assert (pink.city, pink.province, pink.postal_code) == ("Brackendale", "BC", "V0N 1H0")
    # The other results keep the usual form.
    assert (items[50469136].city, items[50469136].province, items[50469136].postal_code) == ("Sept-Îles", "QC", None)


def test_a_run_never_stores_the_region_text(conn, fixtures, fake_client):
    region_only = _detail(
        fixtures,
        '<span property="addressLocality">Brackendale</span><span property="addressRegion">, BC V0N 1H0</span>',
    )
    mapping = {
        search_url("101010", 1): _listing(fixtures, "Brackendale, BC").encode("utf-8"),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): EMPTY,
        posting_url(50456228): region_only.encode("utf-8"),
    }
    jobbank.run(conn, fake_client(mapping), detail_budget=10, now=STAMP)
    row = conn.execute("SELECT city, province, postal_code, employer_id FROM jobbank_postings WHERE posting_id = 50456228").fetchone()
    assert (row["city"], row["province"], row["postal_code"]) == ("Brackendale", "BC", "V0N 1H0")
    emp = conn.execute("SELECT province, postal_code FROM employers WHERE id = ?", (row["employer_id"],)).fetchone()
    assert tuple(emp) == ("BC", "V0N 1H0")
    odd = conn.execute(
        "SELECT COUNT(*) FROM jobbank_postings WHERE province IS NOT NULL AND (length(province) != 2 OR province GLOB '*[^A-Z]*')"
    ).fetchone()[0]
    assert odd == 0


def _posting(conn, posting_id: int, eid: str, province: str | None, postal: str | None = None) -> None:
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, city, province, postal_code, "
        "first_seen, last_seen, flag_current, flag_first, url, updated_at) "
        "VALUES (?, ?, 'x', 'cook', 'Sudbury', ?, ?, ?, ?, 'requested', 'requested', 'u', ?)",
        (posting_id, eid, province, postal, STAMP, STAMP, STAMP),
    )


def _stored_like_the_old_parser(conn) -> dict[str, str]:
    old = "2026-10-01T00:00:00Z"
    ids = {
        "on": upsert_employer(conn, "Sudbury Diner Ltd.", "ON", source="jobbank", now=old),
        "ab": upsert_employer(conn, "Foothills Feedlot Inc.", "AB", source="jobbank", now=old),
        "bc": upsert_employer(conn, "Okanagan Orchards Ltd.", "BC", source="jobbank", postal_code="V1V 1A1", now=old),
        "qc": upsert_employer(conn, "Boulangerie du Port Inc.", "QC", source="jobbank", now=old),
        "ns": upsert_employer(conn, "Harbour Seafoods Ltd.", "NS", source="jobbank", now=old),
        # Not from this fault: an employer row whose province is not a code is
        # counted and kept as it is, because its id hashes the province.
        "odd": upsert_employer(conn, "Odd Province Ltd.", "Ontario", source="esdc_positive", now=old),
    }
    for pid, key, province, postal in [
        (1, "on", ", ON", None),
        (2, "ab", ", AB T2C 2Z2", None),
        (3, "bc", ", BC V1V 2X4", "V1V 1A1"),
        (4, "on", "Ontario", None),
        (5, "qc", ", ", None),          # no province in the text: the listing's code stands in
        (6, "ns", "NS", None),          # already a code: untouched
        (7, "ns", None, None),          # unknown: untouched
    ]:
        _posting(conn, pid, ids[key], province, postal)
    conn.execute("UPDATE jobbank_postings SET updated_at = ?", (old,))
    conn.commit()
    return ids


def test_cleanup_repairs_stored_rows_and_is_idempotent(conn):
    ids = _stored_like_the_old_parser(conn)
    before = {r["id"]: tuple(r) for r in conn.execute("SELECT id, province FROM employers")}

    assert repair_locations(conn, now=STAMP) == {"postings": 5, "postal_codes": 1, "employers_not_codes": 1}
    rows = {r["posting_id"]: (r["province"], r["postal_code"]) for r in conn.execute("SELECT * FROM jobbank_postings")}
    assert rows == {
        1: ("ON", None),
        2: ("AB", "T2C 2Z2"),
        3: ("BC", "V1V 1A1"),   # a stored postal code is never replaced
        4: ("ON", None),
        5: ("QC", None),
        6: ("NS", None),
        7: (None, None),
    }
    touched = {r[0] for r in conn.execute("SELECT posting_id FROM jobbank_postings WHERE updated_at = ?", (STAMP,))}
    assert touched == {1, 2, 3, 4, 5}
    # The postal code moved to the employer that had none; the one that had one keeps it.
    assert conn.execute("SELECT postal_code FROM employers WHERE id = ?", (ids["ab"],)).fetchone()[0] == "T2C 2Z2"
    assert conn.execute("SELECT postal_code FROM employers WHERE id = ?", (ids["bc"],)).fetchone()[0] == "V1V 1A1"
    # No employer re-keyed or moved.
    assert {r["id"]: tuple(r) for r in conn.execute("SELECT id, province FROM employers")} == before

    assert repair_locations(conn, now="2026-10-23T00:00:00Z") == {"postings": 0, "postal_codes": 0, "employers_not_codes": 1}
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE updated_at = '2026-10-23T00:00:00Z'").fetchone()[0] == 0


def test_the_jobbank_stage_runs_the_cleanup_and_logs_it(conn, fake_client):
    _stored_like_the_old_parser(conn)
    mapping = {search_url("101010", 1): EMPTY, search_url("101020", 1): EMPTY}
    stats = jobbank.run(conn, fake_client(mapping), detail_budget=0, now=STAMP)
    assert stats.locations_fixed == 5
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'jobbank' ORDER BY id DESC").fetchone()[0]
    assert "provinces_fixed=5 postal_codes_moved=1" in detail
    assert "employer_provinces_not_codes=1" in detail
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE province LIKE ',%'").fetchone()[0] == 0
