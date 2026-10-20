"""Job Bank against a changed, failing or endless site: every run ends, logged and bounded,
and a sweep that stopped short never marks postings gone."""

import re

import pytest

from conftest import FakeResponse
from lmia_pipeline import cli
from lmia_pipeline.db import get_meta
from lmia_pipeline.sources import jobbank
from lmia_pipeline.sources.jobbank import parse_detail_page, parse_results_count, parse_search_page, posting_url, search_url

EMPTY = b"<html><body><div class='results-jobs'></div></body></html>"


def article(pid: int, employer: str | None = "Acme Farms Ltd", *, title: str = "farm worker",
            date: str = "October 10, 2026", business_class: str = "business") -> str:
    business = f'<li class="{business_class}">{employer}</li>' if employer is not None else ""
    return (
        f'<article id="article-{pid}"><span class="noctitle">{title}</span><ul>'
        f'<li class="date">{date}</li>{business}'
        f'<li class="location"><span class="wb-inv">Location</span> Abbotsford (BC)</li>'
        f'<li class="salary">Salary $18.00 hourly</li></ul></article>'
    )


def page(ids, count: int | None = None, **kw) -> bytes:
    head = f'<span class="found" id="results-count">{count:,}</span> results' if count is not None else ""
    return f"<html><body>{head}{''.join(article(i, **kw) for i in ids)}</body></html>".encode("utf-8")


def night_one(conn, fake_client):
    """A complete first pass: three requested postings and two approved."""
    client = fake_client({
        search_url("101010", 1): page([1, 2, 3], 3),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): page([4, 5], 2),
        search_url("101020", 2): EMPTY,
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-12T00:00:00Z")
    assert stats.complete and not stats.problems
    return client


def flags(conn) -> dict[int, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT posting_id, flag_current FROM jobbank_postings")}


def last_log(conn):
    return conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'jobbank' ORDER BY id DESC LIMIT 1").fetchone()


def test_results_count_parses_with_separators():
    assert parse_results_count('<span class="found" id="results-count">5,883</span> results') == 5883
    assert parse_results_count('<span id="results-count"> 97 </span>') == 97
    assert parse_results_count("<html>no count</html>") is None


def test_an_empty_first_page_in_one_facet_never_marks_that_facet_gone(conn, fake_client):
    night_one(conn, fake_client)
    client = fake_client({
        search_url("101010", 1): page([1, 2, 3], 3),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): EMPTY,  # the approved facet came back empty, no count either
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0 and not stats.complete
    assert flags(conn) == {1: "requested", 2: "requested", 3: "requested", 4: "approved", 5: "approved"}
    ok, detail = last_log(conn)
    assert ok == 0 and "listed no postings" in detail
    # A pass that did not finish is not the day's pass: no digest, and the next night runs.
    assert get_meta(conn, "jobbank_last_run") == "2026-10-12T00:00:00Z"


def test_a_sweep_that_lists_far_fewer_than_the_count_marks_nothing_gone(conn, fake_client):
    night_one(conn, fake_client)
    client = fake_client({
        search_url("101010", 1): page([1], 300),
        search_url("101010", 2): EMPTY,  # a glitch ends the list after one page
        search_url("101020", 1): page([4, 5], 2),
        search_url("101020", 2): EMPTY,
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0
    assert "listed 1 of the 300" in last_log(conn)[1]
    assert flags(conn)[2] == "requested"


def test_a_page_that_fails_mid_sweep_stops_the_facet_and_marks_nothing_gone(conn, fake_client):
    night_one(conn, fake_client)
    client = fake_client({
        search_url("101010", 1): page([1], 3),
        search_url("101010", 2): FakeResponse(410),
        search_url("101020", 1): page([4, 5], 2),
        search_url("101020", 2): EMPTY,
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0 and not stats.complete
    assert "requested page 2: HTTP 410" in last_log(conn)[1]
    # The approved facet was still swept after the failure.
    assert ("101020" in str(client.fake_session.calls))


def test_a_host_that_stops_answering_ends_the_pass_without_raising(conn, fake_client):
    night_one(conn, fake_client)
    client = fake_client({search_url("101010", 1): FakeResponse(503)}, max_attempts=1, max_consecutive_failures=1)
    stats = jobbank.run(conn, client, detail_budget=50, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0 and stats.details_fetched == 0
    assert "requests failed in a row" in last_log(conn)[1]
    # One request, then nothing: no posting pages were tried against a host that is down.
    assert len(client.fake_session.calls) == 1


def test_a_page_that_repeats_stops_the_loop(conn, fake_client):
    same = page([7, 8], 1000)
    mapping = {search_url("101010", n): same for n in range(1, 50)}
    mapping.update({search_url("101020", 1): EMPTY})
    client = fake_client(mapping)
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.pages == 1
    assert "page 2 repeats" in last_log(conn)[1]
    assert stats.marked_gone == 0


def test_pagination_that_never_ends_stops_at_the_cap(conn, fake_client, monkeypatch):
    monkeypatch.setattr(jobbank, "MAX_PAGES", 5)
    mapping = {search_url("101010", n): page([n * 10, n * 10 + 1]) for n in range(1, 20)}
    mapping[search_url("101020", 1)] = EMPTY
    stats = jobbank.run(conn, fake_client(mapping), detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.pages == 5
    assert "5-page cap" in last_log(conn)[1]


def test_the_list_and_detail_phases_stop_at_their_time_budgets(conn, fake_client):
    t = {"now": 0.0}

    def clock():
        t["now"] += 2000.0  # every check of the clock is half an hour later
        return t["now"]

    mapping = {search_url("101010", n): page([n]) for n in range(1, 20)}
    mapping[search_url("101020", 1)] = EMPTY
    stats = jobbank.run(conn, fake_client(mapping), detail_budget=10, now="2026-10-13T00:00:00Z", clock=clock)
    detail = last_log(conn)[1]
    assert "past the 3 h budget" in detail
    assert stats.pages < 10
    assert "posting pages stopped" in detail


def test_a_layout_change_that_hides_employer_names_is_reported_and_marks_nothing_gone(conn, fake_client):
    night_one(conn, fake_client)
    renamed = page([1, 2, 3], 3, business_class="employer-name")
    client = fake_client({
        search_url("101010", 1): renamed,
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): page([4, 5], 2, business_class="employer-name"),
        search_url("101020", 2): EMPTY,
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0
    assert "no employer name on 3 of 3" in last_log(conn)[1]
    assert set(flags(conn).values()) == {"requested", "approved"}


def test_detail_pages_stop_when_the_host_stops_answering(conn, fake_client):
    client = fake_client({
        search_url("101010", 1): page([1, 2, 3], 3),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): page([], 0),
        **{posting_url(i): FakeResponse(503) for i in (1, 2, 3)},
    }, max_attempts=1, max_consecutive_failures=1)
    stats = jobbank.run(conn, client, detail_budget=10, now="2026-10-13T00:00:00Z")
    assert stats.details_fetched == 0
    assert "posting pages stopped after 0" in last_log(conn)[1]
    # The posting that hit the outage is left for another night, not marked fetched.
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE detail_fetched_at IS NULL").fetchone()[0] == 3
    # The list itself was complete, so it counts as the day's pass.
    assert get_meta(conn, "jobbank_last_run") == "2026-10-13T00:00:00Z"


def test_cli_never_raises_out_of_main(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(cli.jobbank, "run", boom)
    db = tmp_path / "lmia.sqlite"
    assert cli.main(["run", "--jobbank", "--db", str(db)]) == 1
    from lmia_pipeline.db import connect
    conn = connect(db)
    row = conn.execute("SELECT ok, detail FROM sources_log WHERE source = 'jobbank'").fetchone()
    assert row["ok"] == 0 and "RuntimeError: parser exploded" in row["detail"]
    conn.close()
    # A database that will not open is an exit code, not a traceback.
    bad = tmp_path / "not-a-db.sqlite"
    bad.write_bytes(b"this is not sqlite" * 100)
    assert cli.main(["run", "--jobbank", "--db", str(bad)]) == 2


def test_a_stage_exception_rolls_back_its_uncommitted_rows(tmp_path, monkeypatch):
    def half_written(conn, client, **kwargs):
        conn.execute("INSERT INTO meta (key, value) VALUES ('half', 'written')")
        raise ValueError("stopped half way")

    monkeypatch.setattr(cli.jobbank, "run", half_written)
    db = tmp_path / "lmia.sqlite"
    assert cli.main(["run", "--jobbank", "--db", str(db)]) == 1
    from lmia_pipeline.db import connect
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM meta WHERE key = 'half'").fetchone()[0] == 0
    conn.close()


# -- parsing odd pages -------------------------------------------------------


def test_non_utf8_page_and_a_posting_with_no_employer(conn, fake_client):
    body = page([1, 2], 2).replace(b"Acme Farms Ltd", "Ferme Été".encode("cp1252"), 1)
    body = body.replace(b'<li class="business">Acme Farms Ltd</li>', b"", 1)
    client = fake_client({
        search_url("101010", 1): body,
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): page([], 0),
    })
    stats = jobbank.run(conn, client, detail_budget=0, now="2026-10-13T00:00:00Z")
    names = [r[0] for r in conn.execute("SELECT employer_raw FROM jobbank_postings")]
    assert names == ["Ferme Été"]
    assert stats.listed == 2


def test_impossible_dates_and_huge_ids_never_stop_the_parser():
    html = (
        "<html><body>"
        + article(1, date="February 30, 2026")
        + article(2, date="Posted on Octember 4, 2026")
        + '<article id="article-123456789012345678901234567890"><li class="business">X</li></article>'
        + "</body></html>"
    )
    items = parse_search_page(html)
    assert [(i.posting_id, i.date_posted) for i in items] == [(1, None), (2, None)]


def detail(body: str) -> str:
    return f"<html><body>{body}</body></html>"


def test_detail_pages_with_large_or_odd_numbers():
    f = parse_detail_page(detail("<p>10,000 vacancies</p>"))
    assert f.vacancies == 10000
    assert parse_detail_page(detail("<p>1 vacancy</p>")).vacancies == 1
    assert parse_detail_page(detail("<p>99999999999999999999999 vacancies</p>")).vacancies is None
    inf = parse_detail_page(detail('<span property="minValue">Infinity</span><span property="maxValue">1e999</span>'))
    assert (inf.wage_min, inf.wage_max) == (None, None)
    text = parse_detail_page(detail('<span property="minValue">$25.50</span>'))
    assert (text.wage_min, text.wage_max) == (None, None)
    ok = parse_detail_page(detail('<span property="minValue">1,234.50</span><span property="validThrough">February 30, 2026</span>'))
    assert ok.wage_min == 1234.5 and ok.valid_through is None


def test_marking_gone_handles_more_postings_than_sqlite_binds(conn, fake_client, monkeypatch):
    # Past SQLite's bound-parameter cap the old NOT IN (?, ...) query failed outright.
    ids = list(range(1, 40_001))
    conn.execute("INSERT OR IGNORE INTO employers (id, display_name, norm_name, updated_at) VALUES ('emp-0000000000', 'X', 'x', 's')")
    conn.executemany(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, flag_first, url, updated_at) "
        "VALUES (?, 'emp-0000000000', 'X', 's', 's', 'requested', 'requested', 'u', 's')",
        [(i,) for i in ids],
    )
    conn.commit()
    gone = jobbank._mark_gone(conn, set(ids[:35_000]), "2026-10-13T00:00:00Z")
    assert gone == 5_000


def test_a_complete_pass_keeps_the_previous_one_for_the_digest(conn, fake_client):
    from lmia_pipeline.db import set_meta
    set_meta(conn, "jobbank_last_run", "2026-10-11T00:00:00Z")
    night_one(conn, fake_client)
    assert get_meta(conn, "jobbank_last_run") == "2026-10-12T00:00:00Z"
    assert get_meta(conn, "jobbank_prev_run") == "2026-10-11T00:00:00Z"


def test_a_sweep_that_stopped_short_leaves_both_markers_alone(conn, fake_client):
    from lmia_pipeline.db import set_meta
    set_meta(conn, "jobbank_last_run", "2026-10-11T00:00:00Z")
    set_meta(conn, "jobbank_prev_run", "2026-10-10T00:00:00Z")
    client = fake_client({search_url("101010", 1): page([1, 2], count=50)}, max_attempts=1, max_consecutive_failures=1)
    stats = jobbank.run(conn, client, now="2026-10-12T00:00:00Z")
    assert not stats.complete
    assert get_meta(conn, "jobbank_last_run") == "2026-10-11T00:00:00Z"
    assert get_meta(conn, "jobbank_prev_run") == "2026-10-10T00:00:00Z"

