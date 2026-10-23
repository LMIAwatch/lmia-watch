"""The program-conditions stages (sources/program.py) and their export (conditions.py),
against trimmed copies of the three canada.ca pages as read on 2026-10-22."""

import json

import pytest
from bs4 import BeautifulSoup

from lmia_pipeline import cli, conditions, export_static
from lmia_pipeline.db import connect, get_meta, set_meta
from lmia_pipeline.sources import program

NOW = "2026-10-22T00:30:00Z"
TIMES_URL = program.SOURCES[program.TIMES].url
CMA_URL = program.SOURCES[program.CMA].url
THRESHOLDS_URL = program.SOURCES[program.THRESHOLDS].url


@pytest.fixture
def pages(fixtures):
    return {
        TIMES_URL: (fixtures / "program_times_en.html").read_bytes(),
        CMA_URL: (fixtures / "program_refusal_en.html").read_bytes(),
        THRESHOLDS_URL: (fixtures / "program_thresholds_en.html").read_bytes(),
    }


def load_all(conn, client, now=NOW):
    return (program.run_times(conn, client, now=now), program.run_cma(conn, client, now=now),
            program.run_thresholds(conn, client, now=now))


def figures(edition):
    return {f.key: f.value for f in edition.figures}


# -- the parsers ------------------------------------------------------------------------

def test_processing_times_by_stream_for_the_month_in_the_caption(fixtures):
    page = program.parse_processing_times((fixtures / "program_times_en.html").read_text(encoding="utf-8"))
    assert page.published == "2026-10-07"
    [edition] = page.editions
    assert (edition.period, edition.in_force_to, edition.threshold) == ("2026-09", None, None)
    assert figures(edition) == {
        "global_talent": 9, "agricultural": 22, "sawp": 7, "high_wage": 98, "low_wage": 82, "permanent_resident": 79,
    }
    # The stream keeps the name the page gives it.
    assert edition.figures[3].label == "High-wage stream"


def test_processing_times_refuse_a_caption_in_another_unit(fixtures):
    html = (fixtures / "program_times_en.html").read_text(encoding="utf-8").replace("business days", "calendar days")
    with pytest.raises(ValueError, match="business days"):
        program.parse_processing_times(html)


def test_cma_list_one_edition_per_column_with_its_dates(fixtures):
    html = (fixtures / "program_refusal_en.html").read_text(encoding="utf-8")
    page = program.parse_cma_refusal(html)
    assert page.published == "2026-10-09"  # "Last updated: October 9, 2026"
    assert [(e.period, e.in_force_to, e.threshold) for e in page.editions] == [
        ("2026-04-10", "2026-07-09", 6.0), ("2026-07-10", "2026-10-08", 6.0), ("2026-10-09", "2027-01-07", 6.0),
    ]
    latest = page.editions[-1]
    assert len(latest.figures) == 41
    rates = figures(latest)
    # Keyed by the 2021 CMA code from the row's map link; Ottawa-Gatineau has
    # no link and is found by its name.
    assert rates["001"] == 6.4 and rates["602"] == 5.9 and rates["535"] == 7.5 and rates["505"] == 7.9
    assert next(f.label for f in latest.figures if f.key == "001") == "St. John's, Newfoundland and Labrador"
    # The areas at or above 6 percent are the cells ESDC prints in bold.
    soup = BeautifulSoup(html, "html.parser")
    for i, edition in enumerate(page.editions):
        bold = sum(1 for row in soup.find("table").find("tbody").find_all("tr")
                   if row.find_all("td")[i + 1].find("strong"))
        assert sum(1 for f in edition.figures if f.value >= edition.threshold) == bold
    assert sum(1 for f in latest.figures if f.value >= 6.0) == 30


def test_cma_list_rates_equal_the_lfs_windows_the_indicator_reconstructs(fixtures):
    from lmia_pipeline.sources import lfs
    page = program.parse_cma_refusal((fixtures / "program_refusal_en.html").read_text(encoding="utf-8"))
    lfs_rates = {(r[0], r[1]): r[2] for r in lfs.parse_table((fixtures / "lfs_14100459_trim.zip").read_bytes())}
    for edition, month in zip(page.editions, ("2026-03", "2026-06", "2026-09")):
        for uid in ("001", "505", "602"):
            assert figures(edition)[uid] == lfs_rates[(uid, month)], (edition.period, uid)


def test_wage_thresholds_thirteen_figures_per_edition(fixtures):
    page = program.parse_wage_thresholds((fixtures / "program_thresholds_en.html").read_text(encoding="utf-8"))
    assert page.published == "2026-10-07"
    assert [(e.period, e.in_force_to) for e in page.editions] == [("2025-06-27", "2026-07-16"), ("2026-07-17", None)]
    old, new = (figures(e) for e in page.editions)
    assert len(old) == len(new) == 13
    assert (new["ON"], new["BC"], new["QC"], new["NT"], new["YT"]) == (36.92, 38.40, 36.00, 48.00, 45.60)
    assert (old["ON"], old["BC"], old["NU"]) == (36.00, 36.60, 42.00)


def test_wage_thresholds_need_every_province_and_territory(fixtures):
    html = (fixtures / "program_thresholds_en.html").read_text(encoding="utf-8")
    start = html.index("<th class=\"text-left\" scope=\"row\"> Yukon </th>")
    html = html[:html.rindex("<tr>", 0, start)] + html[html.index("</tr>", start) + 5:]
    with pytest.raises(ValueError, match="lacks YT"):
        program.parse_wage_thresholds(html)


def test_dates_in_the_page_wording():
    assert program.iso_date("as of July 17, 2026") == "2026-07-17"
    assert program.iso_date("Sept. 26, 2024") == "2024-09-26"
    assert program.all_dates("from October 9, 2026, to January 7, 2027") == ["2026-10-09", "2027-01-07"]
    assert program.iso_date("Rates updated soon") is None


# -- the stages ---------------------------------------------------------------------------

def test_each_page_is_stored_once_and_read_at_most_daily(conn, fake_client, pages):
    client = fake_client(pages)
    assert load_all(conn, client) == (1, 3, 2)
    assert conn.execute("SELECT COUNT(*) FROM program_figures").fetchone()[0] == 6 + 3 * 41 + 2 * 13
    row = conn.execute("SELECT * FROM program_editions WHERE series = 'cma_refusal' AND period = '2026-10-09'").fetchone()
    assert (row["in_force_to"], row["threshold"], row["published"], row["source_url"], row["read_at"], row["items"]) == (
        "2027-01-07", 6.0, "2026-10-09", CMA_URL, NOW, 41)
    detail = conn.execute("SELECT detail FROM sources_log WHERE source = 'program_cma'").fetchone()[0]
    assert "editions=3" in detail and "newest=2026-10-09" in detail and "added_now=3" in detail
    # Within 20 hours no request is made; the date of the check lives in the database.
    calls = len(client.fake_session.calls)
    assert load_all(conn, client, now="2026-10-22T12:00:00Z") == (0, 0, 0)
    assert len(client.fake_session.calls) == calls
    # The next day the pages are read again and the same figures add nothing.
    assert load_all(conn, client, now="2026-10-23T00:30:00Z") == (0, 0, 0)
    assert len(client.fake_session.calls) == calls + 3
    assert get_meta(conn, "program_cma_refusal_checked_at") == "2026-10-23T00:30:00Z"
    assert conn.execute("SELECT COUNT(*) FROM program_editions").fetchone()[0] == 6


def test_a_revised_figure_is_a_new_edition_beside_the_old_one(conn, fake_client, pages):
    load_all(conn, fake_client(pages))
    # ESDC corrects Toronto's rate in the current column.
    html = pages[CMA_URL].decode("utf-8")
    toronto = html.index("Toronto, Ontario")
    end = html.index("</tr>", toronto)
    row = html[toronto:end]
    assert row.count("<strong>7.5</strong>") == 1
    revised = html[:toronto] + row.replace("<strong>7.5</strong>", "<strong>7.7</strong>") + html[end:]
    client = fake_client({**pages, CMA_URL: revised.encode("utf-8")})
    assert program.run_cma(conn, client, now="2026-10-23T00:30:00Z") == 1
    editions = conn.execute(
        "SELECT id, read_at FROM program_editions WHERE series = 'cma_refusal' AND period = '2026-10-09' ORDER BY id"
    ).fetchall()
    assert [e["read_at"] for e in editions] == [NOW, "2026-10-23T00:30:00Z"]
    # The first edition keeps its figure; the newest is what the export shows.
    first = conn.execute("SELECT value FROM program_figures WHERE edition_id = ? AND key = '535'", (editions[0]["id"],))
    assert first.fetchone()[0] == 7.5
    newest = program.editions(conn, program.CMA)[0]
    assert newest["period"] == "2026-10-09" and newest["revisions"] == 1 and newest["read"] == "2026-10-23"
    assert {f["key"]: f["value"] for f in newest["figures"]}["535"] == 7.7


def test_a_changed_layout_fails_the_stage_alone_and_keeps_what_was_stored(conn, fake_client, pages, fixtures):
    load_all(conn, fake_client(pages))
    before = conn.execute("SELECT COUNT(*) FROM program_figures").fetchone()[0]
    changed = (fixtures / "program_changed_layout.html").read_bytes()
    client = fake_client({TIMES_URL: changed, CMA_URL: changed, THRESHOLDS_URL: changed})
    later = "2026-11-07T00:30:00Z"
    for stage, fn in (("program_times", program.run_times), ("program_cma", program.run_cma),
                      ("program_thresholds", program.run_thresholds)):
        assert cli._stage(conn, stage, lambda fn=fn: fn(conn, client, now=later)) is False
        ok, detail = conn.execute(
            "SELECT ok, detail FROM sources_log WHERE source = ? ORDER BY id DESC LIMIT 1", (stage,)).fetchone()
        assert ok == 0 and detail.startswith("ValueError: ")
    assert conn.execute("SELECT COUNT(*) FROM program_figures").fetchone()[0] == before
    # The copy that could not be read was dropped from the cache, and the
    # check date did not move, so an hour later the page is read again.
    assert not any(client.cache_dir.glob("*.bin"))
    assert get_meta(conn, "program_processing_times_checked_at") == NOW
    again = fake_client(pages)
    assert program.run_times(conn, again, now="2026-11-07T01:30:00Z") == 0
    assert [url for url, _ in again.fake_session.calls] == [TIMES_URL]


def test_the_night_goes_on_past_a_page_that_changed(tmp_path, fake_client, pages, fixtures, monkeypatch):
    client = fake_client({**pages, TIMES_URL: (fixtures / "program_changed_layout.html").read_bytes()})
    monkeypatch.setattr(cli, "PoliteClient", lambda *a, **k: client)
    db = tmp_path / "lmia.sqlite"
    assert cli.main(["run", "--program", "--db", str(db)]) == 1
    conn = connect(db)
    try:
        log = {r["source"]: r["ok"] for r in conn.execute("SELECT source, ok FROM sources_log WHERE source LIKE 'program%'")}
        assert log == {"program_times": 0, "program_cma": 1, "program_thresholds": 1}
        series = {r[0] for r in conn.execute("SELECT DISTINCT series FROM program_editions")}
        assert series == {"cma_refusal", "wage_thresholds"}
    finally:
        conn.close()


def test_the_stage_runs_before_the_indicators():
    assert cli.STAGES.index("program") < cli.STAGES.index("indicators")
    assert cli.build_parser().parse_args(["run", "--program"]).program is True


# -- the export -------------------------------------------------------------------------------

def test_export_marks_what_is_in_force_on_the_export_date(conn, fake_client, pages, tmp_path):
    load_all(conn, fake_client(pages))
    set_meta(conn, "esdc_latest_period", "2026Q1")
    data = conditions.build(conn, today="2026-10-22")
    assert data["as_of"] == "2026-10-22"
    times = data["series"]["processing_times"]
    assert times["source"] == {"en": TIMES_URL, "fr": program.SOURCES[program.TIMES].url_fr}
    assert times["source"]["fr"].startswith("https://www.canada.ca/fr/")
    assert times["checked"] == "2026-10-22"
    [month] = times["editions"]
    assert (month["period"], month["status"], month["published"], month["read"], month["source"]) == (
        "2026-09", "latest", "2026-10-07", "2026-10-22", TIMES_URL)
    cma = data["series"]["cma_refusal"]["editions"]
    assert [(e["period"], e["to"], e["status"]) for e in cma] == [
        ("2026-10-09", "2027-01-07", "in_force"), ("2026-07-10", "2026-10-08", "past"), ("2026-04-10", "2026-07-09", "past"),
    ]
    assert cma[0]["threshold"] == 6.0 and len(cma[0]["figures"]) == 41
    thresholds = data["series"]["wage_thresholds"]["editions"]
    assert [(e["period"], e["to"], e["status"]) for e in thresholds] == [
        ("2026-07-17", None, "in_force"), ("2025-06-27", "2026-07-16", "past")]
    # The low-wage indicator reads the lists for every quarter whose two lists are stored.
    bases = {b["quarter"]: b for b in data["indicator_bases"]}
    assert list(bases)[0] == "2025Q1" and list(bases)[-1] == "2026Q4"
    assert bases["2026Q2"] == {"quarter": "2026Q2", "basis": "lfs", "months": ["2025-12", "2026-03"]}
    assert bases["2026Q3"] == {"quarter": "2026Q3", "basis": "lists", "lists": ["2026-04-10", "2026-07-10"]}
    assert bases["2026Q4"]["lists"] == ["2026-07-10", "2026-10-09"]


def test_export_on_other_dates(conn, fake_client, pages):
    load_all(conn, fake_client(pages))
    july = conditions.build(conn, today="2026-07-01")
    assert [e["status"] for e in july["series"]["cma_refusal"]["editions"]] == ["upcoming", "upcoming", "in_force"]
    assert [e["status"] for e in july["series"]["wage_thresholds"]["editions"]] == ["upcoming", "in_force"]
    # Past the newest list's last day with no newer list read, nothing is in force.
    january = conditions.build(conn, today="2027-01-08")
    assert [e["status"] for e in january["series"]["cma_refusal"]["editions"]] == ["past", "past", "past"]
    assert january["series"]["wage_thresholds"]["editions"][0]["status"] == "in_force"


def test_the_file_and_the_sitemap(conn, fake_client, pages, tmp_path):
    assert conditions.write_all(conn, tmp_path, today="2026-10-22") == {"program_files": 0}
    assert not (tmp_path / "program").exists()
    assert conditions.sitemap_entries(conn) == []
    load_all(conn, fake_client(pages))
    counts = conditions.write_all(conn, tmp_path, today="2026-10-22")
    assert counts["program_files"] == 1 and counts["program_bytes"] < 20_000
    data = json.loads((tmp_path / "program" / "index.json").read_text(encoding="utf-8"))
    assert set(data["series"]) == {"processing_times", "cma_refusal", "wage_thresholds"}
    assert conditions.sitemap_entries(conn) == [("/program", "2026-10-22")]


def test_the_static_export_writes_the_section(conn, fake_client, pages, tmp_path, monkeypatch):
    load_all(conn, fake_client(pages))
    set_meta(conn, "data_as_of", "2026-10-22")
    set_meta(conn, "esdc_latest_period", "2026Q1")
    conn.commit()
    out = tmp_path / "static"
    counts = export_static.export_static(conn, out)
    assert counts["program_files"] == 1
    assert (out / "program" / "index.json").exists()
    assert "/program</loc>" in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
