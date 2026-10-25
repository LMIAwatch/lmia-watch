"""Job Bank postings open to international candidates: parsers on saved pages, and the nightly pass end to end.

Fixtures are real pages saved on 2026-10-25 (scripts removed, search pages cut
to a few results, any employer name that read as a person replaced by an
invented one): the facet's first search page, a facet page of postings with
an LMIA requested, the 48-hour Atom feed, and five posting pages.
"""

from __future__ import annotations

import json
import re

import pytest

from lmia_pipeline.db import get_meta, set_meta, upsert_employer
from lmia_pipeline.http import AbortRun
from lmia_pipeline.sources import jobbank, jobbank_intl as ji

NOW = "2026-10-26T00:10:00Z"
ARTICLE_RE = re.compile(r"<article[^>]*id=\"article-\d+\".*?</article>", re.S)


def text(fixtures, name):
    return (fixtures / name).read_text(encoding="utf-8")


def page_stating(html: str, total: int) -> str:
    """The facet page with its stated result count changed, so a six-result sweep can be complete."""
    return re.sub(r'(id="results-count">)[\d,]+(<)', rf"\g<1>{total:,}\g<2>", html, count=1)


def empty_page(html: str) -> str:
    return ARTICLE_RE.sub("", html)


# -- parsers --------------------------------------------------------------------------


def test_the_feed_gives_each_posting_with_its_employer_place_and_salary(fixtures):
    items = ji.parse_feed(text(fixtures, "jobbank_intl_feed.xml"))
    assert len(items) == 12
    first = items[0]
    assert (first.posting_id, first.title, first.employer) == (50578251, "restaurant manager", "Railway Chai House")
    assert (first.city, first.province, first.salary_text, first.date_posted) == ("Brampton", "ON", "$37.00 hourly", "2026-10-25")
    assert items[1].employer == "P & O International Trading Inc."


def test_a_body_that_is_not_an_atom_feed_is_an_error(fixtures):
    with pytest.raises(ValueError):
        ji.parse_feed(text(fixtures, "jobbank_intl_search.html"))
    with pytest.raises(ValueError):
        ji.parse_feed('<?xml version="1.0"?><rss><channel/></rss>')


def test_the_facet_page_states_its_counts_and_shows_the_filter_applied(fixtures):
    counts, applied = ji.parse_facet_page(text(fixtures, "jobbank_intl_search.html"))
    assert applied is True
    assert counts == {"total": 8032, "lmia_requested": 1086, "lmia_approved": 15, "last_48h": 82, "last_30d": 2966,
                      "authorized": 34776}


def test_a_search_page_without_the_filter_is_not_read_as_the_facet(fixtures):
    # The LMIA crawl's page: the international-candidates box is not checked.
    _, applied = ji.parse_facet_page(text(fixtures, "jobbank_requested.html"))
    assert applied is False


def test_listings_carry_the_lmia_flag_only_where_job_bank_shows_one(fixtures):
    lmia = jobbank.parse_search_page(text(fixtures, "jobbank_intl_search_lmia.html"))
    assert [i.lmia_flag for i in lmia] == ["requested"] * 3
    plain = jobbank.parse_search_page(text(fixtures, "jobbank_intl_search.html"))
    assert len(plain) == 6 and {i.lmia_flag for i in plain} == {None}


@pytest.mark.parametrize("posting, audience, lmia, terms, full_time, permanent", [
    ("50578251", "international", "none", "Permanent employment Full time", 1, 1),
    ("50565576", "international", "requested", "Permanent employment Full time", 1, 1),
    ("50571474", "international", "none", "Permanent employment Full time", 1, 1),
    ("50572922", "international", "none", "Permanent employment Full time", 1, 1),
    ("50575022", "international", "none", "Seasonal employment Full time", 1, 0),
])
def test_posting_pages_give_the_audience_the_lmia_marker_and_the_terms(fixtures, posting, audience, lmia, terms,
                                                                       full_time, permanent):
    f = ji.parse_intl_detail(text(fixtures, f"jobbank_intl_detail_{posting}.html"))
    assert (f.audience, f.lmia, f.employment_terms, f.full_time, f.permanent) == (audience, lmia, terms, full_time, permanent)
    assert "other candidates, with or without a valid Canadian work permit" in f.audience_text
    # Job Bank's own notice names permanent residents and an LMIA; neither is the posting's wording.
    assert (f.ee, f.pr, f.exempt) == ([], [], [])


def test_an_authorized_workers_posting_reads_as_authorized(fixtures):
    f = ji.parse_intl_detail(text(fixtures, "jobbank_detail_50440025.html"))
    assert (f.audience, f.lmia) == ("authorized", "requested")


@pytest.mark.parametrize("items, expected", [
    (["a Canadian citizen", "a permanent resident of Canada"], "canadians"),
    (["Canadian citizens and permanent or temporary residents of Canada",
      "other candidates, with or without a valid Canadian work permit"], "international"),
    (["a temporary resident of Canada with a valid work permit"], "authorized"),
    (["something Job Bank has not written before"], "unknown"),
])
def test_the_audience_rule_covers_each_kind(items, expected):
    from bs4 import BeautifulSoup
    html = '<div class="job-audience"><ul>' + "".join(f"<li>{i}</li>" for i in items) + "</ul></div>"
    assert ji.parse_audience(BeautifulSoup(html, "html.parser"))[0] == expected


def test_a_page_without_the_audience_block_or_terms_reads_as_unknown():
    f = ji.parse_intl_detail("<html><body><h1>Expired</h1></body></html>")
    assert (f.audience, f.audience_text, f.employment_terms, f.full_time, f.permanent) == ("unknown", None, None, None, None)


@pytest.mark.parametrize("terms, full_time, permanent", [
    ("Permanent employment Full time", 1, 1),
    ("Temporary employment Full time", 1, 0),
    ("Permanent employment Part time", 0, 1),
    ("Permanent employment Part time leading to full time", 0, 1),
    ("Casual employment Full time or part time", 0, 0),
])
def test_terms_of_employment(terms, full_time, permanent):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(f'<span property="employmentType">{terms}</span>', "html.parser")
    assert ji.parse_terms(soup)[1:] == (full_time, permanent)


def test_phrases_in_the_posting_text_are_kept_as_matched(fixtures):
    # The real page with the employer's own words added to the job details.
    html = text(fixtures, "jobbank_intl_detail_50578251.html")
    words = ("Candidates in the Express Entry pool welcome. We provide PR sponsorship after probation. "
             "This position is LMIA exempt under CUSMA.")
    assert "Job details" in html
    html = html.replace("Job details", f"Job details <p>{words}</p>", 1)
    f = ji.parse_intl_detail(html)
    assert f.ee == ["Express Entry"]
    assert f.pr == ["PR sponsorship"]
    assert f.exempt == ["LMIA exempt"]


@pytest.mark.parametrize("phrase, ee, pr, exempt", [
    ("Comprehensive Ranking System points available", ["Comprehensive Ranking System"], [], []),
    ("We support your permanent residence application", [], ["support your permanent residence"], []),
    ("pathway to PR for the right candidate", [], ["pathway to PR"], []),
    ("No LMIA required for this role", [], [], ["No LMIA required"]),
    ("LMIA not required", [], [], ["LMIA not required"]),
    ("hiring without an LMIA", [], [], ["without an LMIA"]),
    ("permanent employment, full time", [], [], []),
    ("Canadian citizens and permanent residents are encouraged to apply", [], [], []),
    ("crs points matter", [], [], []),   # CRS is matched in capitals only
])
def test_phrase_patterns(phrase, ee, pr, exempt):
    assert ji.find_phrases(phrase, ji.EE_PATTERNS) == ee
    assert ji.find_phrases(phrase, ji.PR_PATTERNS) == pr
    assert ji.find_phrases(phrase, ji.EXEMPT_PATTERNS) == exempt


# -- the nightly pass --------------------------------------------------------------------


def mapping_for(fixtures, *, total: int = 6, details: dict[str, str] | None = None) -> dict[str, bytes]:
    page = page_stating(text(fixtures, "jobbank_intl_search.html"), total)
    m = {
        ji.search_url(1): page.encode("utf-8"),
        ji.search_url(2): empty_page(page).encode("utf-8"),
        ji.feed_url(): text(fixtures, "jobbank_intl_feed.xml").encode("utf-8"),
    }
    for pid, name in (details or {}).items():
        m[jobbank.posting_url(int(pid))] = text(fixtures, name).encode("utf-8")
    return m


DETAILS = {
    "50578251": "jobbank_intl_detail_50578251.html",
    "50571474": "jobbank_intl_detail_50571474.html",
    "50572922": "jobbank_intl_detail_50572922.html",
}


def test_a_first_night_reads_the_counts_the_feed_and_the_whole_facet_and_sets_the_baseline(conn, fixtures, fake_client):
    client = fake_client(mapping_for(fixtures))
    stats = ji.run(conn, client, detail_budget=0, now=NOW)
    assert stats.problems == []
    assert stats.sweep == "complete"
    assert dict(conn.execute("SELECT key, value FROM jobbank_facet_counts WHERE day = '2026-10-26'").fetchall())["total"] == 6
    assert get_meta(conn, "intl_baseline") == "2026-10-26"
    assert get_meta(conn, "intl_sweep_at") == NOW and get_meta(conn, "intl_last_run") == NOW
    rows = {r["posting_id"]: dict(r) for r in conn.execute("SELECT * FROM jobbank_intl_postings")}
    # The feed's household postings and the names read as a person are never stored.
    assert stats.excluded >= 3
    assert not any(r["employer_raw"] in ("Jane Example", "John Sample", "Mary Placeholder") for r in rows.values())
    assert rows[50578251]["found_by"] == "feed" and rows[50578251]["in_facet"] == 1
    assert rows[50578251]["wage_min"] == 37.0 and rows[50578251]["wage_unit"] == "HOUR"
    # Not read yet: no grade.
    assert {r["grade"] for r in rows.values()} == {None}


def test_posting_pages_are_read_and_graded(conn, fixtures, fake_client):
    # Two postings found by an earlier night's feed, and a sweep not due tonight.
    for pid, title in ((50571474, "cybersecurity specialist"), (50572922, "food service counter attendant")):
        ji._upsert(conn, posting_id=pid, title=title, employer="Earlier Feed Employer Inc", city=None, province="ON",
                   postal_code=None, salary_text=None, date_posted=None, lmia_flag=None, found_by="feed",
                   stamp="2026-10-25T00:10:00Z")
    set_meta(conn, "intl_sweep_at", "2026-10-25T00:10:00Z")
    client = fake_client(mapping_for(fixtures, details=DETAILS))
    stats = ji.run(conn, client, detail_budget=50, now=NOW)
    rows = {r["posting_id"]: dict(r) for r in conn.execute("SELECT * FROM jobbank_intl_postings")}
    assert rows[50571474]["noc_code"] == "21220" and rows[50571474]["grade"] == "A"
    assert json.loads(rows[50571474]["grade_reasons"]) == ["intl", "no_lmia", "full_time", "permanent", "high_wage:70"]
    assert rows[50578251]["grade"] == "B"   # restaurant managers, TEER 0, not on the list
    assert rows[50572922]["grade"] == "C"   # food counter attendants, TEER 5
    # Pages the fake does not serve answer 404: fetched, unread, ungraded.
    missing = [r for pid, r in rows.items() if str(pid) not in DETAILS]
    assert missing and all(r["detail_fetched_at"] == NOW and r["grade"] is None for r in missing)
    assert stats.grades["A"] == 1 and stats.details_fetched == 3   # pages read; a 404 is not counted


def test_a_household_posting_page_drops_the_row(conn, fixtures, fake_client):
    ji._upsert(conn, posting_id=50575022, title="room attendant", employer="La maison de travers", city=None,
               province="QC", postal_code=None, salary_text=None, date_posted=None, lmia_flag=None, found_by="feed",
               stamp=NOW)
    client = fake_client({jobbank.posting_url(50575022): text(fixtures, "jobbank_intl_detail_50575022.html").encode()})
    stats = ji.IntlStats()
    ji._read_details(conn, client, stats, NOW, 5, deadline=float("inf"), clock=lambda: 0.0)
    # "housekeeping room attendant" is dropped by the household title rule, like on the LMIA crawl.
    assert conn.execute("SELECT COUNT(*) FROM jobbank_intl_postings").fetchone()[0] == 0
    assert stats.excluded == 1


def test_a_page_without_the_filter_applied_stops_the_pass_and_fails_it(conn, fixtures, fake_client):
    client = fake_client({ji.search_url(1): text(fixtures, "jobbank_requested.html").encode()})
    stats = ji.run(conn, client, detail_budget=5, now=NOW)
    assert stats.problems and "filter" in stats.problems[0]
    assert conn.execute("SELECT COUNT(*) FROM jobbank_intl_postings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobbank_facet_counts").fetchone()[0] == 0
    assert get_meta(conn, "intl_last_run") is None and get_meta(conn, "intl_sweep_at") is None
    row = conn.execute("SELECT ok FROM sources_log WHERE source = 'jobbank_intl'").fetchone()
    assert row["ok"] == 0


def test_a_sweep_that_lists_too_few_marks_nothing_gone_and_is_tried_again(conn, fixtures, fake_client):
    ji.run(conn, fake_client(mapping_for(fixtures)), detail_budget=0, now=NOW)
    conn.execute("INSERT INTO jobbank_intl_postings (posting_id, employer_raw, first_seen, last_seen, found_by, url, updated_at) "
                 "VALUES (1, 'Old Posting Ltd', ?, ?, 'sweep', 'u', ?)", (NOW, NOW, NOW))
    conn.commit()
    later = "2026-11-02T00:10:00Z"
    stats = ji.run(conn, fake_client(mapping_for(fixtures, total=8032)), detail_budget=0, now=later)
    assert stats.sweep == "incomplete" and "6 of the 8032" in stats.problems[-1]
    assert conn.execute("SELECT in_facet FROM jobbank_intl_postings WHERE posting_id = 1").fetchone()[0] == 1
    assert get_meta(conn, "intl_sweep_at") == NOW


def test_a_complete_weekly_sweep_marks_what_left_the_facet_gone_and_a_return_brings_it_back(conn, fixtures, fake_client):
    ji.run(conn, fake_client(mapping_for(fixtures)), detail_budget=0, now=NOW)
    conn.execute("INSERT INTO jobbank_intl_postings (posting_id, employer_raw, first_seen, last_seen, found_by, url, updated_at) "
                 "VALUES (1, 'Old Posting Ltd', ?, ?, 'sweep', 'u', ?)", (NOW, NOW, NOW))
    conn.commit()
    # Six days later the sweep is not due yet.
    stats = ji.run(conn, fake_client(mapping_for(fixtures)), detail_budget=0, now="2026-11-01T00:10:00Z")
    assert stats.sweep == "not due"
    later = "2026-11-02T00:10:00Z"
    stats = ji.run(conn, fake_client(mapping_for(fixtures)), detail_budget=0, now=later)
    # Posting 1 and the feed's postings the six-result sweep does not list.
    assert stats.sweep == "complete" and stats.marked_gone >= 1
    listed = {i.posting_id for i in jobbank.parse_search_page(text(fixtures, "jobbank_intl_search.html"))}
    still = {r[0] for r in conn.execute("SELECT posting_id FROM jobbank_intl_postings WHERE in_facet = 1")}
    assert still == listed - {50576712, 50575863, 50575872}  # less the names read as a person
    gone = conn.execute("SELECT in_facet, gone_at FROM jobbank_intl_postings WHERE posting_id = 1").fetchone()
    assert (gone["in_facet"], gone["gone_at"]) == (0, later)
    assert get_meta(conn, "intl_baseline") == "2026-10-26"   # set once
    ji._upsert(conn, posting_id=1, title=None, employer="Old Posting Ltd", city=None, province=None, postal_code=None,
               salary_text=None, date_posted=None, lmia_flag=None, found_by="feed", stamp="2026-11-03T00:10:00Z")
    back = conn.execute("SELECT in_facet, gone_at, found_by FROM jobbank_intl_postings WHERE posting_id = 1").fetchone()
    assert (back["in_facet"], back["gone_at"], back["found_by"]) == (1, None, "sweep")


def test_a_full_feed_is_followed_by_the_48_hour_pages(conn, fixtures, fake_client, monkeypatch):
    monkeypatch.setattr(ji, "FEED_ROWS", 12)   # the fixture feed holds 12 entries
    m = mapping_for(fixtures)
    lmia_page = text(fixtures, "jobbank_intl_search_lmia.html")
    m[ji.search_url(1, recent=True)] = lmia_page.encode()
    m[ji.search_url(2, recent=True)] = empty_page(lmia_page).encode()
    stats = ji.run(conn, fake_client(m), detail_budget=0, now=NOW)
    assert stats.recent_pages == 1
    found = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT posting_id, found_by, lmia FROM jobbank_intl_postings")}
    recent = [v for v in found.values() if v[0] == "recent"]
    assert recent and all(v[1] == "requested" for v in recent)


def test_the_lmia_flag_is_sticky_and_joined_from_the_lmia_crawl(conn):
    for pid in (10, 11, 12):
        ji._upsert(conn, posting_id=pid, title="cook", employer="Cook Shop Ltd", city=None, province="ON",
                   postal_code=None, salary_text=None, date_posted=None, lmia_flag="requested" if pid == 10 else None,
                   found_by="sweep", stamp=NOW)
    # A later listing without a flag never clears it.
    ji._upsert(conn, posting_id=10, title=None, employer="Cook Shop Ltd", city=None, province="ON", postal_code=None,
               salary_text=None, date_posted=None, lmia_flag=None, found_by="sweep", stamp=NOW)
    eid = upsert_employer(conn, "Cook Shop Ltd", "ON", source="jobbank", now=NOW)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, first_seen, last_seen, flag_current, flag_first, "
        "approved_seen_at, url, updated_at) VALUES (11, ?, 'Cook Shop Ltd', ?, ?, 'approved', 'requested', ?, 'u', ?)",
        (eid, NOW, NOW, NOW, NOW))
    conn.commit()
    ji.join_lmia(conn)
    got = dict(conn.execute("SELECT posting_id, lmia FROM jobbank_intl_postings").fetchall())
    assert got == {10: "requested", 11: "approved", 12: "unknown"}


def test_employer_ids_link_existing_employers_only(conn):
    eid = upsert_employer(conn, "Cook Shop Ltd", "ON", source="jobbank", now=NOW)
    before = conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0]
    ji._upsert(conn, posting_id=20, title="cook", employer="COOK SHOP LTD.", city=None, province="ON", postal_code=None,
               salary_text=None, date_posted=None, lmia_flag=None, found_by="feed", stamp=NOW)
    ji._upsert(conn, posting_id=21, title="cook", employer="Cook Shop Ltd", city=None, province="BC", postal_code=None,
               salary_text=None, date_posted=None, lmia_flag=None, found_by="feed", stamp=NOW)
    ji._upsert(conn, posting_id=22, title="baker", employer="Brand New Bakery Inc", city=None, province="ON",
               postal_code=None, salary_text=None, date_posted=None, lmia_flag=None, found_by="feed", stamp=NOW)
    ji.resolve_employers(conn)
    got = dict(conn.execute("SELECT posting_id, employer_id FROM jobbank_intl_postings").fetchall())
    assert got == {20: eid, 21: None, 22: None}
    assert conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0] == before


def test_the_pass_runs_once_in_twenty_hours(conn):
    assert ji.allowed(conn, now=NOW) == (True, "ok")
    set_meta(conn, "intl_last_run", NOW)
    ok, reason = ji.allowed(conn, now="2026-10-26T10:00:00Z")
    assert ok is False and "ago" in reason
    assert ji.allowed(conn, now="2026-10-26T10:00:00Z", force=True) == (True, "forced")
    assert ji.allowed(conn, now="2026-10-26T20:30:00Z")[0] is True


def test_a_host_that_stops_answering_ends_the_pass(conn, fixtures, fake_client):
    client = fake_client(mapping_for(fixtures))

    def refuse(url, **kwargs):
        raise AbortRun("www.jobbank.gc.ca stopped accepting connections")

    client.get_text = refuse
    stats = ji.run(conn, client, detail_budget=5, now=NOW)
    assert stats.problems and "stopped accepting" in stats.problems[0]
    assert get_meta(conn, "intl_last_run") is None


def test_the_digest_counts_new_feed_postings_without_an_lmia(conn):
    assert ji.digest_count(conn) is None
    set_meta(conn, "intl_prev_run", "2026-10-25T00:10:00Z")
    set_meta(conn, "intl_last_run", NOW)
    rows = [
        (1, "feed", "none", "international", NOW),
        (2, "recent", "none", "international", NOW),
        (3, "feed", "requested", "international", NOW),     # LMIA requested
        (4, "sweep", "none", "international", NOW),         # the weekly sweep's find
        (5, "feed", "none", "international", "2026-10-25T00:10:00Z"),  # the previous pass
        (6, "feed", "unknown", "unknown", NOW),             # page not read
    ]
    for pid, found, lmia, audience, seen in rows:
        conn.execute(
            "INSERT INTO jobbank_intl_postings (posting_id, employer_raw, first_seen, last_seen, found_by, lmia, audience, url, "
            "updated_at) VALUES (?, 'X Ltd', ?, ?, ?, ?, ?, 'u', ?)", (pid, seen, seen, found, lmia, audience, seen))
    conn.commit()
    assert ji.digest_count(conn) == 2


def test_posting_pages_are_read_newest_first_within_a_budget_of_400(conn, fixtures, fake_client):
    assert ji.DEFAULT_DETAIL_BUDGET == 400 and ji.DETAIL_BUDGET_S == 90 * 60
    rows = [
        (1, "2026-10-26T00:10:00Z", "sweep", "2026-09-01"),   # the first sweep's backlog
        (2, "2026-10-26T00:10:00Z", "sweep", "2026-10-20"),
        (3, "2026-11-04T00:10:00Z", "sweep", "2026-11-01"),   # tonight's sweep find
        (4, "2026-11-04T00:10:00Z", "feed", "2026-11-03"),    # tonight's feed find
        (5, "2026-11-04T00:10:00Z", "feed", "2026-11-04"),
        (6, "2026-11-03T00:10:00Z", "feed", "2026-11-03"),    # last night's, page not read
    ]
    for pid, seen, found, posted in rows:
        conn.execute("INSERT INTO jobbank_intl_postings (posting_id, employer_raw, first_seen, last_seen, found_by, "
                     "date_posted, url, updated_at) VALUES (?, 'X Ltd', ?, ?, ?, ?, 'u', ?)", (pid, seen, seen, found, posted, seen))
    conn.commit()
    client = fake_client({})
    asked: list[str] = []
    real = client.get_text

    def record(url, **kwargs):
        asked.append(url.rsplit("/", 1)[1])
        return real(url, **kwargs)

    client.get_text = record
    ji._read_details(conn, client, ji.IntlStats(), "2026-11-04T00:30:00Z", 4, deadline=float("inf"), clock=lambda: 0.0)
    assert asked == ["5", "4", "3", "6"]
