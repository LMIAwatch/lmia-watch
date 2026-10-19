"""Statistics Canada table 14-10-0444-01 and the NOC 2021 titles, against trimmed copies
of the real files (tests/fixtures/make_fixtures.py)."""

import io
import zipfile

import pytest

from lmia_pipeline import cli
from lmia_pipeline.db import get_meta
from lmia_pipeline.sources import vacancies

NOW = "2026-10-18T00:00:00Z"


@pytest.fixture
def table(fixtures) -> bytes:
    return (fixtures / "vacancies_14100444_trim.zip").read_bytes()


@pytest.fixture
def mapping(fixtures, table) -> dict:
    return {
        vacancies.URL: table,
        vacancies.NOC_URLS["en"]: (fixtures / "noc2021_en_trim.csv").read_bytes(),
        vacancies.NOC_URLS["fr"]: (fixtures / "noc2021_fr_trim.csv").read_bytes(),
    }


@pytest.fixture(autouse=True)
def few_unit_groups(monkeypatch):
    # The trimmed structure files hold three unit groups, not five hundred.
    monkeypatch.setattr(vacancies, "MIN_UNIT_GROUPS", 3)


def rows_by_key(rows):
    return {(r[0], r[1], r[2]): r for r in rows}


def test_parse_keeps_unit_groups_and_the_total_for_the_newest_eight_quarters(table):
    rows = vacancies.parse_table(table)
    by = rows_by_key(rows)
    # The file holds 2024 Q1 to 2026 Q2; the oldest two quarters are dropped.
    assert sorted({r[2] for r in rows}) == ["2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    # Unit groups and the total only; the minor group 4410 is left out.
    assert {r[0] for r in rows} == {"63200", "44101", "22101", "total"}
    # Figures as published (cooks in Winnipeg, Manitoba and Canada).
    assert by[("63200", "4650", "2026Q2")][3:] == ("Winnipeg", 0, 300, "E", 17.05, "A")
    assert by[("63200", "00", "2026Q2")][3:] == ("Canada", 0, 13310, "B", 19.55, "A")
    assert by[("total", "46", "2026Q2")][3:] == ("Manitoba", 0, 20480, "A", 25.65, "A")
    # A suppressed vacancy count (quality F) leaves the wage in place.
    assert by[("63200", "4650", "2025Q1")][5:] == (None, None, 17.45, "B")
    # A combined region is stored under both member regions, flagged.
    for code in ("4620", "4640"):
        assert by[("63200", code, "2026Q1")][3:] == ("South Central and North Central", 1, 10, "E", 19.75, "E")
    # The province suffix is dropped from region names.
    assert by[("44101", "1010", "2024Q3")][3] == "Avalon Peninsula"


def test_parse_without_the_metadata_file_reads_every_line_and_agrees(table):
    src = zipfile.ZipFile(io.BytesIO(table))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("14100444.csv", src.read("14100444.csv"))
    assert vacancies.parse_table(buf.getvalue()) == vacancies.parse_table(table)


def test_quarter_labels():
    assert vacancies.quarter_of("2026-04") == "2026Q2"
    assert vacancies.quarter_of("2025-10") == "2025Q4"
    assert vacancies.quarter_of("2025-11") is None
    assert vacancies._shift("2026Q2", 7) == "2024Q3"


def test_titles_join_both_languages(fixtures):
    rows = vacancies.parse_titles((fixtures / "noc2021_en_trim.csv").read_bytes(), (fixtures / "noc2021_fr_trim.csv").read_bytes())
    by = {r[0]: r for r in rows}
    assert by["63200"][1:4] == (5, "Cooks", "Cuisiniers/cuisinières")
    assert by["6"][1:4] == (1, "Sales and service occupations", "Vente et services")
    assert by["63200"][4].startswith("Cooks prepare and cook") and by["63200"][5].startswith("Les cuisiniers")


def test_run_loads_once_and_checks_monthly(conn, fake_client, mapping):
    client = fake_client(mapping)
    loaded = vacancies.run(conn, client, now=NOW)
    assert loaded == conn.execute("SELECT COUNT(*) FROM statcan_vacancies").fetchone()[0] > 0
    assert conn.execute("SELECT title_fr FROM noc_titles WHERE noc_code = '63200'").fetchone()[0] == "Cuisiniers/cuisinières"
    log = conn.execute("SELECT detail, ok FROM sources_log WHERE source = 'vacancies' ORDER BY id DESC").fetchone()
    assert log["ok"] == 1 and "latest=2026Q2" in log["detail"] and "14-10-0444-01" in log["detail"]
    # Within 30 days nothing is requested; the check date lives in the database.
    calls = len(client.fake_session.calls)
    assert vacancies.run(conn, client, now="2026-11-10T00:00:00Z") == 0
    assert len(client.fake_session.calls) == calls
    # After 30 days the table is fetched again (the nightly runner starts with
    # an empty download cache); the same file is not reloaded, and the titles
    # (a fixed classification) are not fetched again.
    for url in mapping:
        client.forget(url)
    assert vacancies.run(conn, client, now="2026-11-20T00:00:00Z") == 0
    assert get_meta(conn, "vacancies_checked_at") == "2026-11-20T00:00:00Z"
    later = [url for url, _ in client.fake_session.calls[calls:]]
    assert later == [vacancies.URL]


@pytest.mark.parametrize("body", [b"", b"<html>Service unavailable</html>"])
def test_a_broken_table_keeps_the_old_rows_and_is_fetched_again(conn, fake_client, mapping, body):
    client = fake_client(mapping)
    before = vacancies.run(conn, client, now=NOW)
    conn.execute("DELETE FROM meta WHERE key IN ('vacancies_checked_at', 'vacancies_sha')")
    conn.commit()
    client.forget(vacancies.URL)
    client.fake_session.mapping[vacancies.URL] = body
    assert vacancies.run(conn, client, now="2026-11-20T00:00:00Z") == 0
    assert conn.execute("SELECT COUNT(*) FROM statcan_vacancies").fetchone()[0] == before
    log = conn.execute("SELECT detail, ok FROM sources_log WHERE source = 'vacancies' ORDER BY id DESC").fetchone()
    assert log["ok"] == 0 and "table:" in log["detail"]
    # The bad body is not kept, and the check date is not moved, so the next run tries again.
    assert client._cache_entry(vacancies.URL) is None
    assert get_meta(conn, "vacancies_checked_at") is None


def test_an_archive_with_another_layout_is_refused(conn, fake_client, mapping):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("14100444.csv", "REF_DATE,GEO,VALUE\n2026-04,Canada,1\n")
    mapping[vacancies.URL] = buf.getvalue()
    client = fake_client(mapping)
    assert vacancies.run(conn, client, now=NOW) == 0
    assert conn.execute("SELECT COUNT(*) FROM statcan_vacancies").fetchone()[0] == 0
    # The titles still loaded.
    assert conn.execute("SELECT COUNT(*) FROM noc_titles").fetchone()[0] > 0


def test_stage_runs_right_after_lfs():
    assert cli.STAGES.index("vacancies") == cli.STAGES.index("lfs") + 1
    assert cli.build_parser().parse_args(["run", "--vacancies"]).vacancies is True
