import re

import pytest
import requests

from conftest import FakeResponse
from lmia_pipeline.http import AbortRun
from lmia_pipeline.sources import jobbank
from lmia_pipeline.sources.jobbank import parse_detail_page, parse_search_page, posting_url, search_url

EMPTY = b"<html><body><div class='results-jobs'></div></body></html>"
# A posting page that answers but holds nothing the parser reads. The fake
# session answers 404 for a URL it does not serve, which now means "removed",
# so every listed posting gets a page unless a test says otherwise.
BLANK_POSTING = b"<html><body><h1>posting</h1></body></html>"


def test_parse_requested_page(fixtures):
    items = parse_search_page((fixtures / "jobbank_requested.html").read_text(encoding="utf-8"))
    assert [i.posting_id for i in items] == [50469136, 50459151, 50456228, 50455831]
    first = items[0]
    assert first.title == "cook"
    assert first.employer == "Restaurant St-Hubert Sept-Îles"
    assert (first.city, first.province) == ("Sept-Îles", "QC")
    assert first.date_posted == "2026-10-10"
    assert first.salary_text.startswith("$16.60 to $22.10 hourly")
    pink = items[2]
    assert pink.employer == "PinkCloud Cleaning & Home Services"
    assert (pink.city, pink.province, pink.date_posted) == ("Brackendale", "BC", "2026-10-08")


def test_parse_approved_page_has_no_flag_markup(fixtures):
    html = (fixtures / "jobbank_approved.html").read_text(encoding="utf-8")
    items = parse_search_page(html)
    assert items[0].posting_id == 50390781
    assert items[0].employer == "KN Berry Farms Inc"
    assert (items[0].city, items[0].province, items[0].date_posted) == ("Abbotsford", "BC", "2026-09-29")
    assert "jobLMIAflag" not in html.split("article-50390781", 1)[1].split("</article>", 1)[0]


def test_parse_detail_pages(fixtures):
    f = parse_detail_page((fixtures / "jobbank_detail_50456228.html").read_text(encoding="utf-8"))
    assert f.employer == "PinkCloud Cleaning & Home Services"
    assert (f.city, f.province, f.postal_code) == ("Brackendale", "BC", "V0N 1H0")
    assert f.street is None
    assert (f.wage_min, f.wage_max, f.wage_unit) == (38.0, 40.0, "HOUR")
    assert f.vacancies == 1
    assert (f.date_posted, f.valid_through) == ("2026-10-08", "2026-10-22")
    assert f.noc_code == "60040"
    assert f.status_text == "under review"
    assert "cleaning service manager" in (f.title or "").lower()

    g = parse_detail_page((fixtures / "jobbank_detail_50440025.html").read_text(encoding="utf-8"))
    assert g.street == "405 Martin Street"
    assert (g.city, g.postal_code, g.noc_code) == ("Penticton", "V2A 5L1", "60020")


def _counted(html: bytes) -> bytes:
    """The fixture pages are trimmed to a few results but still state the live
    page's result count; make the count match the trimmed list, as on a page
    that really held only these results."""
    n = len(re.findall(rb'<article[^>]*id="article-\d+"', html))
    return re.sub(rb'(id="results-count">)[\d,]+', rb"\g<1>" + str(n).encode(), html)


def _mapping(fixtures, requested_html: bytes):
    approved = (fixtures / "jobbank_approved.html").read_bytes()
    m = {
        search_url("101010", 1): _counted(requested_html),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): _counted(approved),
        search_url("101020", 2): EMPTY,
    }
    for html in (requested_html, approved):
        for item in parse_search_page(html.decode("utf-8")):
            m[posting_url(item.posting_id)] = BLANK_POSTING
    m[posting_url(50456228)] = (fixtures / "jobbank_detail_50456228.html").read_bytes()
    return m


def test_run_upserts_excludes_and_marks_gone(conn, fixtures, fake_client):
    requested = (fixtures / "jobbank_requested.html").read_bytes()
    client = fake_client(_mapping(fixtures, requested))
    stats = jobbank.run(conn, client, detail_budget=10, now="2026-10-12T00:00:00Z")
    # 4 requested + 4 approved listed; the approved page's fourth result is a
    # private household and must never be stored.
    assert (stats.listed, stats.excluded, stats.new_postings) == (8, 1, 7)
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings").fetchone()[0] == 7
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE employer_raw LIKE '%Talwar%'").fetchone()[0] == 0
    row = conn.execute("SELECT * FROM jobbank_postings WHERE posting_id = 50456228").fetchone()
    assert (row["postal_code"], row["noc_code"], row["flag_current"], row["flag_first"]) == (
        "V0N 1H0", "60040", "requested", "requested")
    assert row["detail_fetched_at"] == "2026-10-12T00:00:00Z"
    emp = conn.execute("SELECT * FROM employers WHERE id = ?", (row["employer_id"],)).fetchone()
    assert (emp["province"], emp["city"], emp["postal_code"]) == ("BC", "Brackendale", "V0N 1H0")
    approved = conn.execute("SELECT * FROM jobbank_postings WHERE posting_id = 50390781").fetchone()
    assert approved["flag_current"] == "approved" and approved["approved_seen_at"] == "2026-10-12T00:00:00Z"
    # A page that answers is marked fetched, read or not, so it is not asked for again.
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE detail_fetched_at IS NULL").fetchone()[0] == 0
    assert stats.gone_on_fetch == 0
    assert conn.execute("SELECT COUNT(*) FROM jobbank_observations").fetchone()[0] == 7
    assert conn.execute("SELECT excluded FROM sources_log WHERE source = 'jobbank'").fetchone()[0] == 1

    # Next night only PinkCloud is still flagged: the other three requested
    # postings are marked gone, the approved ones are untouched.
    only_pink = re.sub(
        r"<article[^>]*id=\"article-(?!50456228)\d+\".*?</article>", "", requested.decode("utf-8"), flags=re.S
    ).encode("utf-8")
    client2 = fake_client(_mapping(fixtures, only_pink))
    stats2 = jobbank.run(conn, client2, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats2.marked_gone == 3 and stats2.gone_on_fetch == 0
    assert conn.execute("SELECT flag_current FROM jobbank_postings WHERE posting_id = 50469136").fetchone()[0] == "gone"
    assert conn.execute("SELECT updated_at FROM jobbank_postings WHERE posting_id = 50469136").fetchone()[0] == "2026-10-13T00:00:00Z"
    assert conn.execute("SELECT flag_current FROM jobbank_postings WHERE posting_id = 50456228").fetchone()[0] == "requested"
    assert conn.execute("SELECT COUNT(*) FROM jobbank_observations WHERE posting_id = 50456228").fetchone()[0] == 2


def test_capped_run_never_marks_gone(conn, fixtures, fake_client):
    client = fake_client(_mapping(fixtures, (fixtures / "jobbank_requested.html").read_bytes()))
    jobbank.run(conn, client, detail_budget=0, now="2026-10-12T00:00:00Z")
    client2 = fake_client(_mapping(fixtures, EMPTY))
    stats = jobbank.run(conn, client2, limit=1, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats.marked_gone == 0
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE flag_current = 'gone'").fetchone()[0] == 0


def test_posting_page_street_outranks_a_finding_street(conn, fixtures, fake_client):
    from lmia_pipeline.db import upsert_employer

    stamp = "2026-10-12T00:00:00Z"
    eid = upsert_employer(conn, "Penticton Example Ltd.", "BC", source="ircc", street="1 Old Road", now=stamp)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, "
        "flag_first, url, updated_at) VALUES (50440025, ?, 'Penticton Example Ltd.', ?, ?, 'requested', 'requested', "
        "'u', ?)", (eid, stamp, stamp, stamp))
    client = fake_client({posting_url(50440025): (fixtures / "jobbank_detail_50440025.html").read_bytes()})
    assert jobbank._fetch_details(conn, client, 5, stamp) == (1, None)
    row = conn.execute("SELECT street, street_source FROM employers WHERE id = ?", (eid,)).fetchone()
    assert tuple(row) == ("405 Martin Street", "jobbank")


# -- posting pages that do not answer ----------------------------------------


def _one_posting(conn, posting_id: int = 900, attempts: int = 0) -> None:
    from lmia_pipeline.db import upsert_employer

    stamp = "2026-10-12T00:00:00Z"
    eid = upsert_employer(conn, "Fetch Test Farms Ltd", "BC", source="jobbank", now=stamp)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, "
        "flag_first, url, updated_at, detail_attempts) VALUES (?, ?, 'Fetch Test Farms Ltd', ?, ?, 'requested', "
        "'requested', 'u', ?, ?)", (posting_id, eid, stamp, stamp, stamp, attempts))
    conn.commit()


def _posting(conn, posting_id: int = 900):
    return conn.execute("SELECT * FROM jobbank_postings WHERE posting_id = ?", (posting_id,)).fetchone()


def _log_detail(conn) -> str:
    return conn.execute("SELECT detail FROM sources_log WHERE source = 'jobbank' ORDER BY id DESC LIMIT 1").fetchone()[0]


@pytest.mark.parametrize("status", [410, 404])
def test_a_removed_posting_page_marks_the_posting_gone_that_night(conn, fixtures, fake_client, status):
    requested = (fixtures / "jobbank_requested.html").read_bytes()
    mapping = _mapping(fixtures, requested)
    mapping[posting_url(50469136)] = FakeResponse(status)
    stats = jobbank.run(conn, fake_client(mapping), detail_budget=10, now="2026-10-12T00:00:00Z")
    row = _posting(conn, 50469136)
    assert (row["flag_current"], row["updated_at"], row["detail_fetched_at"]) == (
        "gone", "2026-10-12T00:00:00Z", "2026-10-12T00:00:00Z")
    assert row["detail_attempts"] == 0
    # Counted apart from the sweep's removals; the complete sweep listed every posting.
    assert (stats.gone_on_fetch, stats.marked_gone, stats.details_fetched) == (1, 0, 6)
    assert "gone=0 gone_on_fetch=1" in _log_detail(conn)
    assert not stats.problems

    # The next night's sweep marks what it no longer lists and does not count
    # the posting the page fetch already marked.
    only_pink = re.sub(
        r"<article[^>]*id=\"article-(?!50456228)\d+\".*?</article>", "", requested.decode("utf-8"), flags=re.S
    ).encode("utf-8")
    stats2 = jobbank.run(conn, fake_client(_mapping(fixtures, only_pink)), detail_budget=0, now="2026-10-13T00:00:00Z")
    assert (stats2.marked_gone, stats2.gone_on_fetch) == (2, 0)
    assert _posting(conn, 50469136)["updated_at"] == "2026-10-12T00:00:00Z"


def test_a_5xx_posting_page_is_left_for_a_later_night(conn, fixtures, fake_client):
    mapping = _mapping(fixtures, (fixtures / "jobbank_requested.html").read_bytes())
    mapping[posting_url(50469136)] = FakeResponse(500)
    stats = jobbank.run(conn, fake_client(mapping), detail_budget=10, now="2026-10-12T00:00:00Z")
    row = _posting(conn, 50469136)
    assert (row["detail_fetched_at"], row["detail_attempts"], row["flag_current"]) == (None, 1, "requested")
    assert (stats.detail_retry, stats.detail_given_up, stats.gone_on_fetch) == (1, 0, 0)
    assert "detail_retry_later=1 detail_gave_up=0" in _log_detail(conn)
    # A passing failure is not a problem with the stage.
    assert not stats.problems

    # The next night asks for it again, and only for it.
    client = fake_client({**mapping, posting_url(50469136): BLANK_POSTING})
    stats2 = jobbank.run(conn, client, detail_budget=10, now="2026-10-13T00:00:00Z")
    asked = [url for url, _ in client.fake_session.calls if "/jobposting/" in url]
    assert asked == [posting_url(50469136)]
    assert stats2.details_fetched == 1
    assert _posting(conn, 50469136)["detail_fetched_at"] == "2026-10-13T00:00:00Z"


def test_the_attempt_after_three_failures_gives_up(conn, fake_client):
    _one_posting(conn)
    nights = ["2026-10-12T00:00:00Z", "2026-10-13T00:00:00Z", "2026-10-14T00:00:00Z", "2026-10-15T00:00:00Z"]
    for n, night in enumerate(nights, start=1):
        stats = jobbank.RunStats()
        client = fake_client({posting_url(900): FakeResponse(503)}, max_attempts=1)
        assert jobbank._fetch_details(conn, client, 5, night, stats=stats) == (0, None)
        row = _posting(conn)
        assert row["detail_attempts"] == n
        if n <= jobbank.DETAIL_RETRIES:
            assert row["detail_fetched_at"] is None and (stats.detail_retry, stats.detail_given_up) == (1, 0)
        else:
            assert row["detail_fetched_at"] == night and (stats.detail_retry, stats.detail_given_up) == (0, 1)
    # Given up: no details, never asked for again.
    assert _posting(conn)["noc_code"] is None and _posting(conn)["flag_current"] == "requested"
    client = fake_client({posting_url(900): FakeResponse(503)}, max_attempts=1)
    jobbank._fetch_details(conn, client, 5, "2026-10-16T00:00:00Z")
    assert client.fake_session.calls == []


def test_a_timeout_counts_as_an_attempt(conn, fake_client):
    _one_posting(conn)
    client = fake_client({}, max_attempts=1)

    def time_out(url, **kwargs):
        raise requests.ReadTimeout("read timed out")

    client.session.get = time_out
    stats = jobbank.RunStats()
    jobbank._fetch_details(conn, client, 5, "2026-10-12T00:00:00Z", stats=stats)
    row = _posting(conn)
    assert (row["detail_fetched_at"], row["detail_attempts"]) == (None, 1)
    assert stats.detail_retry == 1


def test_a_run_stopped_by_the_breaker_leaves_the_attempts_alone(conn, fake_client):
    _one_posting(conn, attempts=2)
    client = fake_client({posting_url(900): FakeResponse(503)}, max_attempts=1, max_consecutive_failures=1)
    stats = jobbank.RunStats()
    fetched, problem = jobbank._fetch_details(conn, client, 5, "2026-10-12T00:00:00Z", stats=stats)
    assert fetched == 0 and "posting pages stopped after 0" in problem
    row = _posting(conn)
    assert (row["detail_fetched_at"], row["detail_attempts"]) == (None, 2)
    assert (stats.detail_retry, stats.detail_given_up) == (0, 0)


def test_a_page_the_client_refuses_some_other_way_is_marked_fetched(conn, fake_client, monkeypatch):
    # A redirect loop is neither removed nor passing: marked fetched, as before.
    _one_posting(conn)
    client = fake_client({}, max_attempts=1)

    def loop(url, **kwargs):
        raise requests.TooManyRedirects("Exceeded 30 redirects.")

    client.session.get = loop
    stats = jobbank.RunStats()
    jobbank._fetch_details(conn, client, 5, "2026-10-12T00:00:00Z", stats=stats)
    row = _posting(conn)
    assert (row["detail_fetched_at"], row["detail_attempts"], row["flag_current"]) == ("2026-10-12T00:00:00Z", 0, "requested")
    assert (stats.detail_retry, stats.gone_on_fetch) == (0, 0)


def test_a_page_that_will_not_parse_is_marked_fetched_and_the_run_goes_on(conn, fake_client, monkeypatch):
    _one_posting(conn, 900)
    _one_posting(conn, 901)

    def broken(html):
        if "900" in html:
            raise ValueError("unexpected layout")
        return jobbank.DetailFields(noc_code="60020")

    monkeypatch.setattr(jobbank, "parse_detail_page", broken)
    client = fake_client({posting_url(900): b"<html>900</html>", posting_url(901): b"<html>901</html>"})
    assert jobbank._fetch_details(conn, client, 5, "2026-10-12T00:00:00Z") == (1, None)
    assert _posting(conn, 900)["detail_fetched_at"] == "2026-10-12T00:00:00Z"
    assert _posting(conn, 900)["detail_attempts"] == 0
    assert _posting(conn, 901)["noc_code"] == "60020"
