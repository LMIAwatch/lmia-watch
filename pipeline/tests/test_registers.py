"""Designated-employer lists: the parsers on saved pages, reading and keeping last rows, notices, matching, export.

Fixtures are the lists as published (the Newfoundland and Labrador and Prince
Edward Island pages as archived on 2025-08-27 and 2026-07-10, since the live
pages answered 404 and a bot challenge on 2026-10-25), with scripts removed,
each list cut to its first rows and no name that reads as a person; and one
real page of each distinct PDF layout, chosen so that no row on it reads as a
person.
"""

from __future__ import annotations

import pytest

from lmia_pipeline.db import upsert_employer
from lmia_pipeline.http import decode_text
from lmia_pipeline.sources import registers as R
from lmia_pipeline.sources.registers import REGISTERS, Register

NOW = "2026-10-26T00:10:00Z"
BY_KEY = {r.key: r for r in REGISTERS}


def html(fixtures, name):
    return decode_text((fixtures / name).read_bytes())


@pytest.fixture
def fake_client(fake_client):
    """Each night's client with a cache of its own: the stage revalidates a list
    it read under 20 hours ago, and a test's nights are seconds apart."""
    made = []

    def make(mapping, **kwargs):
        client = fake_client(mapping, **kwargs)
        made.append(client)
        client.cache_dir = client.cache_dir.parent / f"cache-{len(made)}"
        return client

    return make


# -- the registry ------------------------------------------------------------------------


def test_the_registry_covers_the_four_atlantic_provinces_and_both_pilots():
    aip = {r.jurisdiction for r in REGISTERS if r.program == "AIP"}
    assert aip == {"NB", "NS", "PE", "NL"}
    assert {r.program for r in REGISTERS} == {"AIP", "RCIP", "FCIP"}
    assert len({r.key for r in REGISTERS}) == len(REGISTERS)
    for r in REGISTERS:
        assert r.format in ("html", "json", "pdf") and r.terms in R.TERMS_URLS
        assert r.source_url.startswith("https://")
        assert (r.selector is not None or r.kind == "json") if r.format != "pdf" else r.selector is None
        assert (r.community is None) == (r.program == "AIP")


# -- parsers ------------------------------------------------------------------------------


def test_the_newfoundland_and_labrador_table(fixtures):
    rows, _ = R.parse_html(BY_KEY["aip_nl"], html(fixtures, "register_aip_nl.html"))
    assert len(rows) == 6
    assert (rows[0].name, rows[0].location, rows[0].designated_on) == (
        "10112755 Canada Inc. o/a Strobel TEK", "St. John's", "2022-09-23")


def test_the_prince_edward_island_list_and_its_date(fixtures):
    rows, list_date = R.parse_html(BY_KEY["aip_pe"], html(fixtures, "register_aip_pe.html"))
    assert len(rows) == 6 and rows[0].name == "100066 PEI Inc." and rows[0].location is None
    assert list_date == "2026-06-02"


def test_sudbury_gives_each_pilot_its_own_panel_with_addresses(fixtures):
    page = html(fixtures, "register_sudbury.html")
    rcip, _ = R.parse_html(BY_KEY["rcip_sudbury"], page)
    fcip, _ = R.parse_html(BY_KEY["fcip_sudbury"], page)
    assert len(rcip) == 6 and len(fcip) == 6
    assert (rcip[1].name, rcip[1].location) == ("Baker Tilly SNT LLP", "1174 St Jerome Street, Sudbury, Ontario, P3A2V9")
    assert fcip[2].name == "First North Property Management Inc."


def test_west_kootenay_splits_the_town_off_the_name_and_reads_its_date(fixtures):
    rows, list_date = R.parse_html(BY_KEY["rcip_west_kootenay"], html(fixtures, "register_west_kootenay.html"))
    by_name = {r.name: r.location for r in rows}
    assert by_name["Kootenay Lake Medical Clinic"] == "Nelson"
    assert "Employer Name" not in by_name
    assert list_date == "2026-09-16"


def test_claresholm_keeps_the_name_before_the_sector_and_status(fixtures):
    rows, list_date = R.parse_html(BY_KEY["rcip_claresholm"], html(fixtures, "register_claresholm.html"))
    assert [r.name for r in rows][:3] == ["Willow Creek Continuing Care Centre", "Optima Living", "El Molino"]
    assert not any("hiring" in r.name.lower() for r in rows)
    assert list_date == "2025-06-30"


def test_superior_east_reads_only_the_list_under_its_heading(fixtures):
    rows, _ = R.parse_html(BY_KEY["fcip_superior_east"], html(fixtures, "register_superior_east.html"))
    assert len(rows) == 6 and rows[0].name == "Magpie Relay Motel & Resort"
    assert not any(r.name.startswith(("is ", "show ")) for r in rows)


def test_north_bay_reads_the_json_its_page_loads(fixtures):
    rows = R.parse_json((fixtures / "register_north_bay.json").read_text(encoding="utf-8"))
    assert [r.name for r in rows][:2] == ["Degagne Group", "Industrial Plastics Canada (IPC)"]
    with pytest.raises(R.ParseProblem):
        R.parse_json("<html>not json</html>")
    with pytest.raises(R.ParseProblem):
        R.parse_json('{"name": "not a list"}')


@pytest.mark.parametrize("raw, clean", [
    ("Acera Insurance (not hiring at the moment)", "Acera Insurance"),
    ("MEADOW PARK MONTESSORI SCHOOL (Not currently hiring)", "MEADOW PARK MONTESSORI SCHOOL"),
    ("Pepco Corporation - Not Hiring at this time", "Pepco Corporation"),
    ("Chicken Chef (Altona)", "Chicken Chef (Altona)"),
    ("Industrial Plastics Canada (IPC)", "Industrial Plastics Canada (IPC)"),
    ("  Spaced   Out  Ltd. ", "Spaced Out Ltd."),
])
def test_status_notes_are_removed_from_names(raw, clean):
    assert R.clean_name(raw) == clean


@pytest.mark.parametrize("raw, legal, trade", [
    ("Boyuk Towing – 2591519 Ontario Inc.", "2591519 Ontario Inc.", "Boyuk Towing"),
    ("Caisse Desjardins Ontario Credit Union Inc. – Caisse Desjardins Ontario",
     "Caisse Desjardins Ontario Credit Union Inc.", "Caisse Desjardins Ontario"),
    ("10113 Newfoundland Ltd. o/a Mary Browns", "10113 Newfoundland Ltd.", "Mary Browns"),
    ("Plain Name Ltd", "Plain Name Ltd", None),
    ("Smith-Jones Welding Ltd", "Smith-Jones Welding Ltd", None),   # a hyphen inside a name is not a join
])
def test_names_joined_by_a_dash_are_read_as_legal_and_trade_names(raw, legal, trade):
    assert R.split_names(raw) == (legal, trade)


def test_a_challenge_page_or_a_page_without_rows_is_a_parse_problem():
    with pytest.raises(R.ParseProblem, match="bot challenge"):
        R.parse_html(BY_KEY["aip_pe"], "<html><script>radware bot manager</script><p>Please wait</p></html>")
    with pytest.raises(R.ParseProblem, match="no employer rows"):
        R.parse_html(BY_KEY["aip_nl"], "<html><body><p>Page moved</p></body></html>")


def test_the_pdf_link_is_found_on_its_page():
    reg = BY_KEY["rcip_moose_jaw"]
    page = ('<a href="/wp-content/uploads/2026/11/designated-employer-list-NOV-26.pdf">List</a>'
            '<a href="/other.pdf">x</a>')
    assert R.find_pdf_link(reg, page) == "https://rcip.mjchamber.com/wp-content/uploads/2026/11/designated-employer-list-NOV-26.pdf"
    assert R.find_pdf_link(reg, "<p>no link</p>") is None
    assert R.find_pdf_link(BY_KEY["aip_nb"], page) is None   # a fixed address


# -- reading, keeping last rows, notices --------------------------------------------------

NL = BY_KEY["aip_nl"]
NB_PDF = BY_KEY["aip_nb"]


def test_a_good_read_stores_rows_and_a_later_failure_keeps_them(conn, fixtures, fake_client):
    client = fake_client({NL.source_url: html(fixtures, "register_aip_nl.html").encode()})
    stats = R.run(conn, client, now=NOW, registers=(NL,))
    assert stats.states == {"aip_nl": "ok"} and stats.rows == 6
    state = conn.execute("SELECT * FROM designated_lists WHERE key = 'aip_nl'").fetchone()
    assert (state["state"], state["rows"], state["last_ok_at"], state["fail_streak"]) == ("ok", 6, NOW, 0)
    # The next night the page answers 404: the rows stay, the list is failing, a notice is raised.
    later = "2026-10-27T00:10:00Z"
    stats = R.run(conn, fake_client({}), now=later, registers=(NL,))
    assert stats.states == {"aip_nl": "failing"} and stats.rows == 6
    state = conn.execute("SELECT * FROM designated_lists WHERE key = 'aip_nl'").fetchone()
    assert (state["state"], state["rows"], state["last_ok_at"], state["fail_streak"]) == ("failing", 6, NOW, 1)
    row = conn.execute("SELECT ok, notice FROM sources_log WHERE source = 'registers' ORDER BY id DESC").fetchone()
    assert row["ok"] == 1
    assert row["notice"].startswith("Designated-employer lists not read from tonight (their last good rows are kept): aip_nl (not fetched")


def last_notice(conn):
    return conn.execute("SELECT notice FROM sources_log WHERE source = 'registers' ORDER BY id DESC").fetchone()[0]


def test_a_list_is_reported_only_when_it_stops_being_read_and_when_it_is_read_again(conn, fixtures, fake_client):
    page = html(fixtures, "register_aip_nl.html").encode()
    notices = []
    for night in range(1, 16):
        mapping = {NL.source_url: page} if night in (1, 12, 13) else {}
        R.run(conn, fake_client(mapping), now=f"2026-11-{night:02d}T00:10:00Z", registers=(NL,))
        notices.append(last_notice(conn))
    raised = {n: text for n, text in enumerate(notices, 1) if text}
    # Night 2 it stops, night 12 it is read again, night 14 it stops again; nothing in between.
    assert sorted(raised) == [2, 12, 14]
    assert raised[12] == "Designated-employer lists read again: aip_nl"
    # Every night the summary still names the list that is not read, without a notice.
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'registers' ORDER BY id DESC").fetchone()[0]
    assert detail.endswith("failing: aip_nl")


def test_a_list_that_fails_on_its_first_read_is_reported_once(conn, fake_client):
    R.run(conn, fake_client({}), now=NOW, registers=(NL,))
    assert "aip_nl" in last_notice(conn)
    R.run(conn, fake_client({}), now="2026-10-27T00:10:00Z", registers=(NL,))
    assert last_notice(conn) is None


def table(n: int) -> bytes:
    rows = "".join(f"<tr><td>Employer Number {i} Ltd</td><td>Gander</td><td>01-Jan-25</td></tr>" for i in range(n))
    return (f'<table class="dataTable"><tr><th>Employer Name</th><th>Location</th><th>Date Designated</th></tr>'
            f"{rows}</table>").encode()


@pytest.mark.parametrize("first, second, state, message", [
    (12, 4, "layout", "4 rows read, fewer than 5"),
    (20, 7, "layout", "7 rows read, down from 20"),
    (20, 8, "ok", None),            # a drop of exactly 60 percent still reads
])
def test_a_read_too_short_or_far_shorter_than_the_last_good_one_keeps_the_last_rows(conn, fake_client, first, second,
                                                                                    state, message):
    R.run(conn, fake_client({NL.source_url: table(first)}), now=NOW, registers=(NL,))
    stats = R.run(conn, fake_client({NL.source_url: table(second)}), now="2026-10-27T00:10:00Z", registers=(NL,))
    assert stats.states == {"aip_nl": state}
    row = conn.execute("SELECT rows, detail FROM designated_lists WHERE key = 'aip_nl'").fetchone()
    if message:
        assert row["rows"] == first and message in row["detail"] and stats.rows == first
        assert "aip_nl (" in last_notice(conn)
    else:
        assert row["rows"] == second


def test_names_that_read_as_a_person_are_never_stored(conn, fake_client):
    rows = "".join(f"<tr><td>Gander Fish Plant {i} Ltd</td><td>Gander</td></tr>" for i in range(5))
    page = ('<table class="dataTable"><tr><th>Employer Name</th><th>Location</th></tr>'
            f"<tr><td>Jane Example</td><td>Gander</td></tr>{rows}</table>")
    R.run(conn, fake_client({NL.source_url: page.encode()}), now=NOW, registers=(NL,))
    names = [r[0] for r in conn.execute("SELECT employer_name FROM designated_employers ORDER BY 1")]
    assert "Jane Example" not in names and len(names) == 5


# -- PDF lists ---------------------------------------------------------------------------------

# One real page per distinct layout (tests/fixtures/register_<key>.pdf), with
# the rows the rule must read from it.
PDF_LAYOUTS = [
    ("aip_nb", 29, ("12200601 Canada Inc.", None), "bullet"),
    ("rcip_pictou_county", 25, ("10725978 Canada Inc. (Protech)", None), "table, status column"),
    ("rcip_timmins", 48, None, "table, pilot column"),
    ("rcip_thunder_bay", 24, ("(1852075 Ontario Inc.) o/a Nook", "1-271 Bay St. Thunder Bay"), "table, address, hyphen"),
    ("rcip_steinbach", 15, ("1st Choice Convenience", None), "one name a line"),
    ("rcip_moose_jaw", 28, ("121 Steakhouse Lounge C Motel", None), "two names a line"),
    ("rcip_north_okanagan_shuswap", 22, None, "table, sector column"),
    ("rcip_peace_liard", 29, ("0731990 B.C. Ltd. o/a Rona Fort St John", None), "numbered, operating name"),
    ("fcip_acadian_peninsula", 10, None, "name - place"),
]


@pytest.mark.parametrize("key, count, first, layout", PDF_LAYOUTS, ids=[p[3] for p in PDF_LAYOUTS])
def test_each_pdf_layout_reads_one_name_a_row(fixtures, key, count, first, layout):
    rows, _ = R.parse_pdf(BY_KEY[key], (fixtures / f"register_{key}.pdf").read_bytes())
    assert len(rows) == count
    if first:
        assert (rows[0].name, rows[0].location) == first
    for r in rows:
        assert r.name == r.name.strip() and len(r.name) >= 2
        assert not R.PDF_HEADER_RE.match(r.name)
        assert "hiring" not in r.name.lower() and "recrute" not in r.name.lower()


def test_the_timmins_pdf_feeds_each_pilot_its_own_rows(fixtures):
    data = (fixtures / "register_rcip_timmins.pdf").read_bytes()
    rcip, _ = R.parse_pdf(BY_KEY["rcip_timmins"], data)
    fcip, _ = R.parse_pdf(BY_KEY["fcip_timmins"], data)
    assert len(fcip) < len(rcip)
    assert {r.name for r in fcip} <= {r.name for r in rcip} | {r.name for r in fcip}


def test_the_acadian_list_gives_the_place_without_the_note(fixtures):
    rows, _ = R.parse_pdf(BY_KEY["fcip_acadian_peninsula"], (fixtures / "register_fcip_acadian_peninsula.pdf").read_bytes())
    assert all(r.location and "recrute" not in r.location for r in rows)


def test_a_file_pypdf_cannot_read_is_unreadable_and_the_set_is_a_notice_when_it_changes(conn, fixtures, fake_client):
    nb, pictou = BY_KEY["aip_nb"], BY_KEY["rcip_pictou_county"]
    page = f'<a href="{pictou.data_url}">List</a>'.encode()
    good = (fixtures / "register_aip_nb.pdf").read_bytes()
    pictou_pdf = (fixtures / "register_rcip_pictou_county.pdf").read_bytes()
    client = fake_client({nb.source_url: b"%PDF-1.4 not really a pdf", pictou.page_url: page, pictou.data_url: pictou_pdf})
    stats = R.run(conn, client, now=NOW, registers=(nb, pictou))
    assert stats.states == {"aip_nb": "unreadable", "rcip_pictou_county": "ok"}
    assert last_notice(conn) == "Designated-employer lists not yet readable (pypdf could not read the PDF): aip_nb"
    # Unchanged the next night: no notice, and the summary still names it.
    R.run(conn, fake_client({nb.source_url: b"%PDF-1.4 not really a pdf", pictou.page_url: page,
                             pictou.data_url: pictou_pdf}), now="2026-10-27T00:10:00Z", registers=(nb, pictou))
    assert last_notice(conn) is None
    assert "unreadable: aip_nb" in conn.execute(
        "SELECT detail FROM sources_log WHERE source = 'registers' ORDER BY id DESC").fetchone()[0]
    # Readable again: the set is empty and that is the notice.
    R.run(conn, fake_client({nb.source_url: good, pictou.page_url: page, pictou.data_url: pictou_pdf}),
          now="2026-10-28T00:10:00Z", registers=(nb, pictou))
    assert last_notice(conn) == "Every designated-employer list is readable again"
    assert conn.execute("SELECT state, rows FROM designated_lists WHERE key = 'aip_nb'").fetchone()[0] == "ok"


def test_a_pdf_address_found_on_its_page_is_followed_and_kept(conn, fixtures, fake_client):
    moose = BY_KEY["rcip_moose_jaw"]
    newer = "https://rcip.mjchamber.com/wp-content/uploads/2026/11/designated-employer-list-NOV-26.pdf"
    page = '<a href="/wp-content/uploads/2026/11/designated-employer-list-NOV-26.pdf">List</a>'
    pdf = (fixtures / "register_rcip_moose_jaw.pdf").read_bytes()
    stats = R.run(conn, fake_client({moose.page_url: page.encode(), newer: pdf}), now=NOW, registers=(moose,))
    assert stats.states == {"rcip_moose_jaw": "ok"}
    assert conn.execute("SELECT source_url FROM designated_lists WHERE key = 'rcip_moose_jaw'").fetchone()[0] == newer
    # The page cannot be read the next night: the last address is used.
    stats = R.run(conn, fake_client({newer: pdf}), now="2026-10-27T00:10:00Z", registers=(moose,))
    assert stats.states == {"rcip_moose_jaw": "ok"}


def test_one_site_down_does_not_stop_the_others(conn, fixtures, fake_client):
    from lmia_pipeline.http import AbortRun
    pe = BY_KEY["aip_pe"]
    client = fake_client({NL.source_url: html(fixtures, "register_aip_nl.html").encode()})
    real = client.get

    def flaky(url, **kwargs):
        if url == pe.source_url:
            raise AbortRun("5 requests failed in a row")
        return real(url, **kwargs)

    client.get = flaky
    stats = R.run(conn, client, now=NOW, registers=(pe, NL))
    assert stats.states == {"aip_pe": "failing", "aip_nl": "ok"}


# -- matching and export ---------------------------------------------------------------------


FILLER = "".join(f"<tr><td>Filler Row Employer {i} Ltd</td><td>Corner Brook</td></tr>" for i in range(5))


def seed_nl(conn, fake_client, fixtures):
    R.run(conn, fake_client({NL.source_url: html(fixtures, "register_aip_nl.html").encode()}), now=NOW, registers=(NL,))


def test_matching_grades_by_name_and_place_never_across_provinces(conn, fixtures, fake_client):
    exact = upsert_employer(conn, "10112755 Canada Inc.", "NL", source="esdc_positive", city="St. John's", now=NOW)
    probable = upsert_employer(conn, "12924692 Canada Inc.", "NL", source="esdc_positive", city="Corner Brook", now=NOW)
    elsewhere = upsert_employer(conn, "10113 Newfoundland Ltd.", "NS", source="esdc_positive", now=NOW)
    seed_nl(conn, fake_client, fixtures)
    got = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT employer_id, grade, basis FROM designated_matches")}
    assert got[exact] == ("exact", "name_city")
    assert got[probable] == ("probable", "name_province")
    assert elsewhere not in got


def test_a_common_name_needs_the_place(conn, fake_client):
    table = ('<table class="dataTable"><tr><th>Employer Name</th><th>Location</th></tr>'
             "<tr><td>Sunrise Bakery</td><td>Gander</td></tr>" + FILLER + "</table>")
    far = upsert_employer(conn, "Sunrise Bakery", "NL", source="esdc_positive", city="Labrador City", now=NOW)
    R.run(conn, fake_client({NL.source_url: table.encode()}), now=NOW, registers=(NL,))
    assert conn.execute("SELECT COUNT(*) FROM designated_matches WHERE employer_id = ?", (far,)).fetchone()[0] == 0
    near = upsert_employer(conn, "Sunrise Bakery", "NL", source="esdc_positive", city="Gander", now=NOW)
    assert near == far   # one identity per name and province; the city fills the blank only
    conn.execute("UPDATE employers SET city = 'Gander' WHERE id = ?", (near,))
    R.match(conn, now=NOW)
    assert conn.execute("SELECT grade FROM designated_matches WHERE employer_id = ?", (near,)).fetchone()[0] == "exact"


def test_a_trade_name_matches_with_the_place(conn, fixtures, fake_client):
    table = ('<table class="dataTable"><tr><th>Employer Name</th><th>Location</th></tr>'
             "<tr><td>55555 Newfoundland Ltd. o/a Torngat Seafoods</td><td>Nain</td></tr>"
             "<tr><td>66666 Newfoundland Ltd. o/a Hotel North</td><td>St. Anthony</td></tr>" + FILLER + "</table>")
    eid = upsert_employer(conn, "Torngat Seafoods", "NL", source="jobbank", city="Nain", now=NOW)
    common = upsert_employer(conn, "Hotel North", "NL", source="jobbank", city="St. Anthony", now=NOW)
    R.run(conn, fake_client({NL.source_url: table.encode()}), now=NOW, registers=(NL,))
    row = conn.execute("SELECT grade, basis, employer_name FROM designated_matches WHERE employer_id = ?", (eid,)).fetchone()
    assert (row["grade"], row["basis"], row["employer_name"]) == (
        "probable", "trade_name_city", "55555 Newfoundland Ltd. o/a Torngat Seafoods")
    # A trade name made of generic words needs more than a name: none, even with the place.
    assert conn.execute("SELECT COUNT(*) FROM designated_matches WHERE employer_id = ?", (common,)).fetchone()[0] == 0


def test_a_trade_name_that_reads_as_a_person_is_not_kept(conn, fixtures, fake_client):
    seed_nl(conn, fake_client, fixtures)
    stored = conn.execute("SELECT trade_name FROM designated_employers WHERE employer_name LIKE '%Strobel%'").fetchone()[0]
    assert stored is None


def test_profile_rows_say_since_when_and_whether_still_listed(conn, fixtures, fake_client):
    eid = upsert_employer(conn, "10112755 Canada Inc.", "NL", source="esdc_positive", city="St. John's", now=NOW)
    seed_nl(conn, fake_client, fixtures)
    rows = R.profile_rows(conn, [eid])[eid]
    assert rows == [{
        "list": "aip_nl", "program": "AIP", "jurisdiction": "NL", "community": None,
        "name": "10112755 Canada Inc. o/a Strobel TEK", "location": "St. John's", "designated_on": "2022-09-23",
        "first_seen": "2026-10-26", "last_seen": "2026-10-26", "current": True, "url": NL.page_url,
        "grade": "exact", "basis": "name_city",
    }]
    # A later good read without the row: no longer current.
    table = ('<table class="dataTable"><tr><th>Employer Name</th><th>Location</th></tr>'
             "<tr><td>Other Employer Ltd</td><td>Gander</td></tr>" + FILLER + "</table>")
    R.run(conn, fake_client({NL.source_url: table.encode()}), now="2026-10-27T00:10:00Z", registers=(NL,))
    assert R.profile_rows(conn, [eid])[eid][0]["current"] is False


def test_export_rows_list_every_register_with_its_state(conn, fixtures, fake_client):
    eid = upsert_employer(conn, "10112755 Canada Inc.", "NL", source="esdc_positive", city="St. John's", now=NOW)
    seed_nl(conn, fake_client, fixtures)
    rows = {r["key"]: r for r in R.export_rows(conn)}
    assert set(rows) == {r.key for r in REGISTERS}
    nl = rows["aip_nl"]
    assert (nl["state"], nl["rows"], nl["matched"], nl["last_ok"], nl["terms"]) == ("ok", 6, 1, "2026-10-26", "nl_disclaimer")
    assert nl["terms_url"] == "https://www.gov.nl.ca/disclaimer/"
    assert rows["aip_nb"]["state"] == "not_read" and rows["aip_nb"]["format"] == "pdf"
    assert eid
