import json
import xml.etree.ElementTree as ET
from datetime import date

from lmia_pipeline import config, export_static, feeds, status
from lmia_pipeline.db import upsert_employer

A = "{http://www.w3.org/2005/Atom}"
BASE = "https://lmiawatch.ca"
NOW = "2026-10-12T00:00:00Z"
TODAY = date(2026, 10, 18)
EM_DASH = chr(0x2014)


def posting(conn, pid, employer, raw, *, first_seen, flag_first="requested", flag="requested", approved_seen_at=None,
            city="Vancouver", prov="BC", postal="V6B 1A1", noc=None, title="Cook"):
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, noc_code, city, province, postal_code, "
        "date_posted, first_seen, last_seen, flag_current, flag_first, approved_seen_at, url, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, employer, raw, title, noc, city, prov, postal, first_seen[:10], first_seen, first_seen, flag, flag_first,
         approved_seen_at, f"https://www.jobbank.gc.ca/jobsearch/jobposting/{pid}", NOW),
    )


def esdc(conn, employer, raw, period, lst, resource, *, prov="BC", stream="High Wage", noc="73300", postal="V6B 1A1",
         positions=3, n=0):
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, "
        "noc_title, lmias, positions, resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, 'Vancouver', ?, ?, 'x', 1, ?, ?, ?)",
        (lst, period, employer, raw, prov, stream, postal, noc, positions, resource, f"{period}-{lst}-{raw}-{n}"),
    )


def seed(conn):
    van = upsert_employer(conn, "Harbour Grill Ltd", "BC", source="jobbank", city="Vancouver", postal_code="V6B 1A1", now=NOW)
    hal = upsert_employer(conn, "Bluenose Inn", "NS", source="jobbank", city="Halifax", postal_code="B3H 1A1", now=NOW)
    old = upsert_employer(conn, "Yukon Old Co", "YT", source="jobbank", city="Whitehorse", postal_code="Y1A 1A1", now=NOW)
    conn.execute("INSERT INTO meta (key, value) VALUES ('data_as_of', '2026-10-18')")
    conn.executemany(
        "INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) VALUES (?, ?, ?, ?, ?, 0, 0, 'centroid')",
        [("V6B", "5920", "Lower Mainland--Southwest", "933", "Vancouver"), ("B3H", "1230", "Halifax", "205", "Halifax"),
         ("Y1A", "6010", "Yukon", None, None)],
    )
    posting(conn, 101, van, "Harbour Grill Ltd", first_seen="2026-10-17T03:00:00Z", noc="63200")
    posting(conn, 102, hal, "Bluenose Inn", first_seen="2026-10-16T03:00:00Z", city="Halifax", prov=", NS B3H 1A1",
            postal=None)
    posting(conn, 103, van, "Harbour Grill Ltd", first_seen="2026-10-13T03:00:00Z", flag_first="approved", flag="approved",
            approved_seen_at="2026-10-13T03:00:00Z")
    posting(conn, 104, van, "Harbour Grill Ltd", first_seen="2026-10-14T03:00:00Z", flag="approved",
            approved_seen_at="2026-10-15T03:00:00Z")
    # Seen months ago: Yukon has nothing recent, so its scoped feeds are skipped.
    posting(conn, 105, old, "Yukon Old Co", first_seen="2026-03-01T03:00:00Z", city="Whitehorse", prov="YT",
            postal="Y1A 1A1")
    conn.execute(
        "INSERT INTO findings (employer_id, operating_name, legal_name, address, reasons, decision_date, penalty, status, row_hash, "
        "fetched_at) VALUES (?, 'Bluenose Inn', 'Bluenose Inn', '1 Water St, Halifax, NS B3H 1A1', '1: reason', '3/4/2026', "
        "'$5,000', 'Eligible to apply', 'abc123', '2026-10-17T03:00:00Z')", (hal,))
    for rid, period, ds, pub in (("p261", "2026Q1", "positive", "2026-07-22"), ("n261", "2026Q1", "negative", "2026-07-22"),
                                 ("p254", "2025Q4", "positive", "2026-03-16"), ("p19", "2019Q2", "positive", "2019-09-01")):
        conn.execute("INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes, rows_loaded, "
                     "loaded_at) VALUES (?, ?, ?, 'n', 'u', ?, 's', 1, 1, ?)", (rid, ds, period, pub, NOW))
    esdc(conn, van, "Harbour Grill Ltd", "2026Q1", "positive", "p261", positions=4)
    esdc(conn, van, "Harbour Grill Ltd", "2026Q1", "positive", "p261", stream="Talent mondial", noc="21231", positions=1, n=1)
    esdc(conn, hal, "Bluenose Inn", "2026Q1", "negative", "n261", prov="NS", stream="Low Wage", noc="63200", postal="B3H 1A1")
    esdc(conn, van, "Harbour Grill Ltd", "2025Q4", "positive", "p254", positions=2)
    # NOC 2011 code and a release from 2019: neither makes a NOC group, the old one only reaches Canada and BC.
    esdc(conn, van, "Harbour Grill Ltd", "2019Q2", "positive", "p19", noc="2171", stream="Primary Agriculture")
    status.recompute(conn, now=NOW)
    return van, hal, old


def parse(path):
    root = ET.parse(path).getroot()  # raises on malformed XML
    assert root.tag == f"{A}feed"
    return root


def entries(root):
    return root.findall(f"{A}entry")


def written(out):
    return sorted(p.relative_to(out).as_posix() for p in (out / "feeds").rglob("*.xml"))


def test_every_feed_is_valid_atom(conn, tmp_path):
    seed(conn)
    counts = feeds.write_feeds(conn, tmp_path, today=TODAY, base_url=BASE + "/")
    paths = written(tmp_path)
    assert counts["feeds"] == len(paths) and counts["feed_bytes"] > 0
    for rel in paths:
        root = parse(tmp_path / rel)
        assert root.findtext(f"{A}id").startswith("tag:lmiawatch.ca,2026:feeds/")
        assert root.findtext(f"{A}title").startswith("LMIA Watch: ")
        assert root.findtext(f"{A}updated").endswith("Z")
        self_links = [l for l in root.findall(f"{A}link") if l.get("rel") == "self"]
        assert [l.get("href") for l in self_links] == [f"{BASE}/data/{rel}"]
        assert self_links[0].get("type") == "application/atom+xml"
        assert root.findtext(f"{A}author/{A}name") == "LMIA Watch"
        assert "Licence" in root.findtext(f"{A}rights") or "attribution" in root.findtext(f"{A}rights")
        ids = [e.findtext(f"{A}id") for e in entries(root)]
        assert len(ids) == len(set(ids))
        for e in entries(root):
            assert e.findtext(f"{A}id").startswith("tag:lmiawatch.ca,2026:")
            assert e.findtext(f"{A}title") and e.findtext(f"{A}summary")
            assert e.findtext(f"{A}updated").endswith("Z")
            alternates = [l for l in e.findall(f"{A}link") if l.get("rel") == "alternate"]
            assert alternates and alternates[0].get("href").startswith(BASE)
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert EM_DASH not in text
        assert text.startswith('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">')


def test_scopes_written_and_skipped(conn, tmp_path):
    seed(conn)
    feeds.write_feeds(conn, tmp_path, today=TODAY, base_url=BASE)
    assert written(tmp_path) == [
        "feeds/canada/approved.xml", "feeds/canada/findings.xml", "feeds/canada/pending.xml", "feeds/canada/quarters.xml",
        "feeds/cma/205/findings.xml", "feeds/cma/205/pending.xml", "feeds/cma/205/quarters.xml",
        "feeds/cma/933/approved.xml", "feeds/cma/933/pending.xml", "feeds/cma/933/quarters.xml",
        "feeds/noc/21/quarters.xml", "feeds/noc/63/pending.xml", "feeds/noc/63/quarters.xml", "feeds/noc/73/quarters.xml",
        "feeds/prov/BC/approved.xml", "feeds/prov/BC/pending.xml", "feeds/prov/BC/quarters.xml",
        "feeds/prov/NS/findings.xml", "feeds/prov/NS/pending.xml", "feeds/prov/NS/quarters.xml",
        "feeds/stream/global-talent/quarters.xml", "feeds/stream/high-wage/quarters.xml", "feeds/stream/low-wage/quarters.xml",
    ]
    # Primary Agriculture's only row is from 2019, older than the release window.
    assert not (tmp_path / "feeds" / "stream" / "primary-agriculture").exists()
    # Yukon's only posting is from March: past the 90-day window, so no Yukon feed at all.
    assert not (tmp_path / "feeds" / "prov" / "YT").exists()

    index = json.loads((tmp_path / "feeds" / "index.json").read_text(encoding="utf-8"))
    assert sorted(f["path"] for f in index["feeds"]) == written(tmp_path)
    # Canada first, then province, stream, NOC group and CMA, as the /feeds page lists them.
    assert [f["scope"] for f in index["feeds"]][:5] == ["canada"] * 4 + ["prov"]
    by_path = {f["path"]: f for f in index["feeds"]}
    assert by_path["feeds/cma/933/pending.xml"]["name"] == "Vancouver"
    assert by_path["feeds/stream/global-talent/quarters.xml"]["name"] == "Global Talent Stream"
    assert by_path["feeds/canada/pending.xml"] == {
        "scope": "canada", "key": "", "name": None, "event": "pending", "path": "feeds/canada/pending.xml",
        "entries": 4, "updated": "2026-10-17T03:00:00Z",
    }
    assert index["as_of"] == "2026-10-18" and index["max_entries"] == 50


def test_entries_carry_the_event_the_place_and_the_source(conn, tmp_path):
    van, hal, _ = seed(conn)
    feeds.write_feeds(conn, tmp_path, today=TODAY, base_url=BASE)
    pending = entries(parse(tmp_path / "feeds" / "canada" / "pending.xml"))
    # Posting 103 was first seen already approved, so it is in the approved feed only.
    assert [e.findtext(f"{A}id") for e in pending] == [
        "tag:lmiawatch.ca,2026:jobbank/101/requested", "tag:lmiawatch.ca,2026:jobbank/102/requested",
        "tag:lmiawatch.ca,2026:jobbank/104/requested", "tag:lmiawatch.ca,2026:jobbank/105/requested",
    ]
    first = pending[0]
    assert first.findtext(f"{A}title") == "Harbour Grill Ltd, Vancouver, BC"
    assert first.findtext(f"{A}updated") == "2026-10-17T03:00:00Z"
    summary = first.findtext(f"{A}summary")
    assert summary.startswith('Harbour Grill Ltd, Vancouver, BC: Job Bank posting 101 (Cook) first seen on 2026-10-17 with the "LMIA requested" flag.')
    assert "« EIMT demandée »" in summary and "Source : Guichet-Emplois." in summary
    links = {(l.get("rel"), l.get("hreflang")): l.get("href") for l in first.findall(f"{A}link")}
    assert links[("alternate", "en")] == f"{BASE}/employers/{van}"
    assert links[("alternate", "fr")] == f"{BASE}/employers/{van}?lang=fr"
    assert links[("via", None)] == "https://www.jobbank.gc.ca/jobsearch/jobposting/101"
    # The province field held an address fragment; the code inside it still files the posting under Nova Scotia.
    ns = entries(parse(tmp_path / "feeds" / "prov" / "NS" / "pending.xml"))
    assert [e.findtext(f"{A}title") for e in ns] == ["Bluenose Inn, Halifax, NS"]

    approved = entries(parse(tmp_path / "feeds" / "canada" / "approved.xml"))
    assert [e.findtext(f"{A}id") for e in approved] == [
        "tag:lmiawatch.ca,2026:jobbank/104/approved", "tag:lmiawatch.ca,2026:jobbank/103/approved"]
    assert '"Approved LMIA" flag' in approved[0].findtext(f"{A}summary")

    finding = entries(parse(tmp_path / "feeds" / "prov" / "NS" / "findings.xml"))[0]
    assert finding.findtext(f"{A}title") == "Bluenose Inn, Halifax, NS"
    text = finding.findtext(f"{A}summary")
    assert "decision dated 2026-03-04; $5,000; Eligible to apply. Source: IRCC." in text
    assert "décision du 2026-03-04" in text
    assert finding.findtext(f"{A}id") == "tag:lmiawatch.ca,2026:ircc/abc123"

    quarters = entries(parse(tmp_path / "feeds" / "prov" / "BC" / "quarters.xml"))
    assert [e.findtext(f"{A}id") for e in quarters] == [
        "tag:lmiawatch.ca,2026:esdc/2026Q1/prov/BC", "tag:lmiawatch.ca,2026:esdc/2025Q4/prov/BC",
        "tag:lmiawatch.ca,2026:esdc/2019Q2/prov/BC"]
    q1 = quarters[0]
    assert q1.findtext(f"{A}title") == "ESDC lists for 2026 Q1 / Listes d’EDSC du T1 2026"
    assert q1.findtext(f"{A}updated") == "2026-07-22T00:00:00Z"
    assert q1.findtext(f"{A}summary").startswith(
        "British Columbia: 2 approved records (5 positions) and 0 refused records in ESDC's 2026 Q1 lists, published 2026-07-22.")
    assert [l.get("href") for l in q1.findall(f"{A}link") if l.get("hreflang") == "en"] == [f"{BASE}/search?province=BC"]
    national = entries(parse(tmp_path / "feeds" / "canada" / "quarters.xml"))[0].findtext(f"{A}summary")
    assert national.startswith("Canada: 2 approved records (5 positions) and 1 refused records")
    noc = entries(parse(tmp_path / "feeds" / "noc" / "63" / "quarters.xml"))[0]
    assert [l.get("href") for l in noc.findall(f"{A}link") if l.get("hreflang") == "en"] == [f"{BASE}/search?noc=63"]
    stream = parse(tmp_path / "feeds" / "stream" / "high-wage" / "quarters.xml")
    assert stream.findtext(f"{A}title") == (
        "LMIA Watch: ESDC quarterly lists, High Wage / Listes trimestrielles d’EDSC, Haut salaire")


def test_feeds_hold_the_newest_fifty(conn, tmp_path):
    van, _, _ = seed(conn)
    for i in range(60):
        posting(conn, 1000 + i, van, "Harbour Grill Ltd", first_seen=f"2026-10-0{1 + i % 9}T{i % 24:02d}:00:00Z")
    feeds.write_feeds(conn, tmp_path, today=TODAY, base_url=BASE)
    items = entries(parse(tmp_path / "feeds" / "canada" / "pending.xml"))
    assert len(items) == feeds.MAX_ENTRIES
    stamps = [e.findtext(f"{A}updated") for e in items]
    assert stamps == sorted(stamps, reverse=True)
    assert stamps[0] == "2026-10-17T03:00:00Z"


def test_national_feeds_are_written_even_when_empty(conn, tmp_path):
    counts = feeds.write_feeds(conn, tmp_path, today=TODAY, base_url=BASE)
    assert written(tmp_path) == [f"feeds/canada/{e}.xml" for e in sorted(feeds.EVENTS)]
    assert counts["feeds"] == 4 and counts["feed_entries"] == 0
    root = parse(tmp_path / "feeds" / "canada" / "findings.xml")
    assert entries(root) == [] and root.findtext(f"{A}updated") == "2026-10-18T00:00:00Z"


def test_output_is_deterministic_and_clean(conn, tmp_path):
    van, _, _ = seed(conn)
    posting(conn, 200, van, "Bad\x0bName\x01 Ltd", first_seen="2026-10-17T05:00:00Z")
    feeds.write_feeds(conn, tmp_path / "a", today=TODAY, base_url=BASE)
    feeds.write_feeds(conn, tmp_path / "b", today=TODAY, base_url=BASE)
    for rel in written(tmp_path / "a") + ["feeds/index.json"]:
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes(), rel
    first = entries(parse(tmp_path / "a" / "feeds" / "canada" / "pending.xml"))[0]
    assert first.findtext(f"{A}title") == "BadName Ltd, Vancouver, BC"


def test_helpers():
    assert feeds.rfc3339("2026-10-12") == "2026-10-12T00:00:00Z"
    assert feeds.rfc3339("2026-10-12T09:10:00Z") == "2026-10-12T09:10:00Z"
    assert feeds.rfc3339("2026-10-12T09:10:00-07:00") == "2026-10-12T16:10:00Z"
    assert feeds.rfc3339("soon") is None and feeds.rfc3339(None) is None
    assert feeds.decision_date("2/29/2024") == "2024-02-29"
    assert feeds.decision_date("2026-10-08") == "2026-10-08"
    assert feeds.decision_date("2/30/2024") is None and feeds.decision_date(None) is None
    assert feeds.province_code(", AB T2C 2Z2") == "AB" and feeds.province_code(None, "QC") == "QC"
    assert feeds.province_code("Ontario") is None
    assert feeds.noc_group("73300") == "73" and feeds.noc_group("2171") is None
    assert feeds.fsa_of(None, "v6b 1a1") == "V6B"
    assert feeds.period_label("2017Q1-Q2", "fr") == "T1 à T2 2017" and feeds.period_label("2015", "en") == "2015"
    assert feeds.fmt_int(33202, "fr") == "33 202" and feeds.fmt_int(33202, "en") == "33,202"


def test_static_export_writes_the_feeds(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", BASE)
    seed(conn)
    counts = export_static.export_static(conn, tmp_path / "static")
    assert counts["feeds"] == 23
    root = parse(tmp_path / "static" / "feeds" / "canada" / "pending.xml")
    assert [l.get("href") for l in root.findall(f"{A}link") if l.get("rel") == "self"] == [
        f"{BASE}/data/feeds/canada/pending.xml"]
    assert (tmp_path / "static" / "feeds" / "index.json").exists()
