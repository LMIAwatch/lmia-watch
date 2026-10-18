import re

from lmia_pipeline.sources import jobbank
from lmia_pipeline.sources.jobbank import parse_detail_page, parse_search_page, posting_url, search_url

EMPTY = b"<html><body><div class='results-jobs'></div></body></html>"


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
    return {
        search_url("101010", 1): _counted(requested_html),
        search_url("101010", 2): EMPTY,
        search_url("101020", 1): _counted((fixtures / "jobbank_approved.html").read_bytes()),
        search_url("101020", 2): EMPTY,
        posting_url(50456228): (fixtures / "jobbank_detail_50456228.html").read_bytes(),
    }


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
    # Missing posting pages are marked fetched so they are not retried nightly.
    assert conn.execute("SELECT COUNT(*) FROM jobbank_postings WHERE detail_fetched_at IS NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobbank_observations").fetchone()[0] == 7
    assert conn.execute("SELECT excluded FROM sources_log WHERE source = 'jobbank'").fetchone()[0] == 1

    # Next night only PinkCloud is still flagged: the other three requested
    # postings are marked gone, the approved ones are untouched.
    only_pink = re.sub(
        r"<article[^>]*id=\"article-(?!50456228)\d+\".*?</article>", "", requested.decode("utf-8"), flags=re.S
    ).encode("utf-8")
    client2 = fake_client(_mapping(fixtures, only_pink))
    stats2 = jobbank.run(conn, client2, detail_budget=0, now="2026-10-13T00:00:00Z")
    assert stats2.marked_gone == 3
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
