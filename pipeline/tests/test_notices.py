"""Government notices: the feed parser, the keyword match in both languages, pairing, the dateline,
the nightly stage's notices and resilience, the export, the run status and the wiring.

Fixtures are the Canada.ca news feeds as the API answered on 2026-10-25 for
the 12 months to that day (notices_<dept>_<lang>.xml), cut to a few entries
with each entry's bytes as published: IRCC's two releases of 2026-10-16,
items that share a timestamp (two pairs of different types, one pair of the
same type), an item only the French matches, and items that match nothing;
ESDC's two Temporary Foreign Worker Program releases. The trimmed French IRCC
feed leaves out the two items of 2026-03-31, so their English items have no
French pair.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from lmia_pipeline import cli, config, export_static, nightly
from lmia_pipeline.db import connect, get_meta
from lmia_pipeline.sources import notices as N

NOW = "2026-10-26T00:10:00Z"
EM_DASH = "\u2014"


def feed_bytes(fixtures, key: str) -> bytes:
    dept, lang = key.split("_")
    return (fixtures / f"notices_{dept}_{lang}.xml").read_bytes()


def night_urls(now: str = NOW) -> dict[str, str]:
    since = N.window_start(date.fromisoformat(now[:10]))
    return {f.key: f.url(since) for f in N.FEEDS}


def mapping(fixtures, now: str = NOW, *, skip: tuple[str, ...] = (), feeds: dict[str, bytes] | None = None) -> dict[str, bytes]:
    urls = night_urls(now)
    bodies = {k: feed_bytes(fixtures, k) for k in urls}
    bodies.update(feeds or {})
    return {urls[k]: bodies[k] for k in urls if k not in skip}


def entry(title: str, url: str, stamp: str, category: str, summary: str = "") -> str:
    return (f'<entry><title>{title}</title><id>{url}</id><summary type="html">{summary or title}</summary>'
            f'<author><name>Dept</name></author><category term="{category}"/><updated>{stamp}</updated>'
            f'<link href="{url}"/></entry>')


def with_entries(raw: bytes, *entries: str) -> bytes:
    text = raw.decode("utf-8")
    at = text.index("<entry>")
    return (text[:at] + "".join(entries) + text[at:]).encode("utf-8")


def rows(conn):
    return {r["id"]: r for r in conn.execute("SELECT * FROM gov_notices")}


def last_log(conn):
    return conn.execute("SELECT * FROM sources_log WHERE source = 'gov_notices' ORDER BY id DESC").fetchone()


def notices_of(conn) -> list[str]:
    text = last_log(conn)["notice"]
    return text.split(N.NOTICE_SEP) if text else []


# -- the feeds -------------------------------------------------------------------------


def test_the_feeds_are_the_prototypes_addresses_with_a_12_month_window():
    urls = night_urls("2026-10-25T00:10:00Z")
    assert urls["ircc_en"] == (
        "https://api.io.canada.ca/io-server/gc/news/en/v2?dept=departmentofcitizenshipandimmigration&sort=publishedDate"
        "&orderBy=desc&publishedDate%3E=2025-10-25&pick=300&format=atom&atomtitle=Immigration,%20Refugees%20and%20Citizenship%20Canada")
    assert urls["esdc_fr"] == (
        "https://api.io.canada.ca/io-server/gc/news/fr/v2?dept=departmentofemploymentandsocialdevelopment&sort=publishedDate"
        "&orderBy=desc&publishedDate%3E=2025-10-25&pick=500&format=atom&atomtitle=Emploi%20et%20D%C3%A9veloppement%20social%20Canada")
    assert [f.key for f in N.FEEDS] == ["ircc_en", "ircc_fr", "esdc_en", "esdc_fr"]
    assert N.window_start(date(2028, 2, 29)) == "2027-02-28"


def test_the_keyword_set_is_the_prototypes():
    assert [k for k, _, _ in N.KEYWORDS] == [
        "lmia", "labour market impact assessment", "temporary foreign worker", "tfwp", "express entry",
        "work permit", "job bank", "wage threshold", "refusal to process", "international mobility program",
        "permanent residence job offer",
        "eimt", "étude d'impact sur le marché du travail", "travailleurs étrangers temporaires",
        "travailleur étranger temporaire", "entrée express", "permis de travail", "guichet-emplois",
    ]
    labels = [t["label"] for t in N.term_labels()]
    assert len(labels) == 17 and labels.count("travailleurs étrangers temporaires") == 1
    assert {t["lang"] for t in N.term_labels()} == {"en", "fr"}


# -- the parser ------------------------------------------------------------------------


def test_the_english_feed_parses_with_types_dates_and_links(fixtures):
    items = N.parse_feed(feed_bytes(fixtures, "ircc_en"), "en")
    assert len(items) == 16
    first = items[0]
    assert first.title == "Canada refocusing Express Entry on top talent that drives economic growth"
    assert first.url == ("https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/"
                         "canada-refocusing-express-entry-on-top-talent-that-drives-economic-growth.html")
    assert (first.published_at, first.item_type) == ("2026-10-16T11:02:27-04:00", "news_release")
    assert {i.item_type for i in items} == {"news_release", "backgrounder", "media_advisory", "speech"}


def test_the_french_feed_parses_its_own_category_names(fixtures):
    items = N.parse_feed(feed_bytes(fixtures, "ircc_fr"), "fr")
    assert len(items) == 14
    assert items[0].title.startswith("Le Canada réoriente le système Entrée express")
    assert [i.item_type for i in items[:3]] == ["news_release", "backgrounder", "media_advisory"]
    assert any(i.item_type == "speech" for i in items)


def test_the_dateline_is_left_out_in_both_languages(fixtures):
    en = N.parse_feed(feed_bytes(fixtures, "ircc_en"), "en")[0]
    fr = N.parse_feed(feed_bytes(fixtures, "ircc_fr"), "fr")[0]
    assert en.summary.startswith("Building a stronger Canada means restoring confidence")
    assert fr.summary.startswith("Pour bâtir un Canada plus fort")
    assert EM_DASH not in en.summary and "Kitchener" not in en.summary
    assert N.strip_dateline("Le 1er juillet 2026 – Ottawa (Ontario) – Texte.") == "Texte."
    assert N.strip_dateline("July 9, 2026 - Ottawa, Ontario - Text.") == "Text."
    # A sentence that opens on a date is not a dateline.
    assert N.strip_dateline("Le 3 novembre 2026, des modifications").startswith("Le 3 novembre 2026, des")
    assert N.strip_dateline("On November 3, 2026, changes").startswith("On November 3")


@pytest.mark.parametrize("body, problem", [
    (b"<html><body>Service unavailable</body></html>", "not an Atom feed"),
    (b"not xml at all", "not XML"),
    (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>', "no entries"),
])
def test_a_body_that_is_not_a_readable_feed_is_a_problem(body, problem):
    with pytest.raises(N.FeedProblem, match=problem):
        N.parse_feed(body, "en")


def test_an_entry_without_a_canada_ca_link_is_skipped():
    raw = with_entries(
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title><entry></entry></feed>',
        entry("Express Entry news", "https://example.com/en/news.html", "2026-10-01T10:00:00-04:00", "news releases"),
        entry("Express Entry news", "https://www.canada.ca/en/news/2026/10/a.html", "2026-10-01T10:00:00-04:00", "readouts"),
    )
    items = N.parse_feed(raw, "en")
    assert [i.url for i in items] == ["https://www.canada.ca/en/news/2026/10/a.html"]
    assert items[0].item_type == "other"


# -- matching --------------------------------------------------------------------------


def test_terms_match_in_either_language_on_word_boundaries():
    assert N.matched_terms("Changes to Express Entry", "remove labour market impact assessment (LMIA) requirements") == [
        "LMIA", "labour market impact assessment", "Express Entry"]
    assert N.matched_terms("Modifications", "les exigences relatives à l’étude d’impact sur le marché du travail (EIMT)") == [
        "EIMT", "étude d’impact sur le marché du travail"]
    # The singular is shown under the plural's label.
    assert N.matched_terms("Un travailleur étranger temporaire", "") == ["travailleurs étrangers temporaires"]
    assert N.matched_terms("Le Guichet\u00ad-Emplois", "") == ["Guichet-Emplois"]
    # Inside another word, or another form of the word, is not a match.
    assert N.matched_terms("Olmiac climate", "work permits for students") == []
    assert N.matched_terms("Entrée Express", "") == ["Entrée express"]


def test_an_item_only_the_french_matches_is_kept(fixtures):
    en = N.parse_feed(feed_bytes(fixtures, "ircc_en"), "en")
    fr = N.parse_feed(feed_bytes(fixtures, "ircc_fr"), "fr")
    pairs = {e.title: f for e, f in N.pair(en, fr) if e is not None}
    e = next(i for i in en if i.title.startswith("Canada strengthens borders"))
    assert e.terms == [] and pairs[e.title].terms == ["permis de travail"]


# -- pairing ---------------------------------------------------------------------------


def test_items_pair_on_the_timestamp_then_the_type_then_the_feed_order(fixtures):
    en = N.parse_feed(feed_bytes(fixtures, "ircc_en"), "en")
    fr = N.parse_feed(feed_bytes(fixtures, "ircc_fr"), "fr")
    pairs = {(e.title if e else None): f for e, f in N.pair(en, fr)}
    assert None not in pairs  # every French item found its English one
    # Same timestamp, different types: the backgrounder pairs with the backgrounder.
    assert pairs["Projects aimed at supporting Francophone minority communities"].title.startswith("Projets visant à soutenir")
    assert pairs["Canada is supporting new projects to promote Francophone immigration and strengthen Francophone "
                 "minority communities"].item_type == "news_release"
    # Same timestamp and type: the feed order, which both languages keep.
    morning = next(t for t in pairs if t and t.endswith("(morning)"))
    afternoon = next(t for t in pairs if t and t.endswith("(afternoon)"))
    assert pairs[morning].title.endswith("(matin)") and pairs[afternoon].title.endswith("(après-midi)")
    # The two items the trimmed French feed lacks have no pair.
    assert sorted(t for t, f in pairs.items() if f is None) == [
        "Canada begins new “30 days or free” guarantee for passport processing",
        "Canada extends certain work permit measures for Ukrainians",
    ]


def test_a_french_item_with_no_english_partner_is_returned_alone(fixtures):
    fr = N.parse_feed(feed_bytes(fixtures, "esdc_fr"), "fr")
    assert [(e, f.title[:20]) for e, f in N.pair([], fr)] == [(None, "Le gouvernement du C"), (None, "Le gouvernement du C")]


# -- the stage -------------------------------------------------------------------------


def test_the_first_night_stores_the_matched_items_with_one_request_per_feed(conn, fixtures, fake_client):
    client = fake_client(mapping(fixtures))
    stats = N.run(conn, client, now=NOW)
    assert stats.summary() == "10 listed, 10 new tonight (first read)"
    calls = client.fake_session.calls
    assert sorted(url for url, _ in calls) == sorted(night_urls().values())
    assert all(h["User-Agent"] == config.USER_AGENT for _, h in calls)
    stored = rows(conn)
    assert len(stored) == 10
    ukraine = next(r for r in stored.values() if r["title_en"] == "Canada extends certain work permit measures for Ukrainians")
    # No French item paired: the French side stays empty and the site shows the English.
    assert (ukraine["title_fr"], ukraine["url_fr"], json.loads(ukraine["terms_en"])) == (None, None, ["work permit"])
    assert ukraine["id"] == N.notice_id(ukraine["url_en"])
    release = stored[N.notice_id("https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/"
                                 "canada-refocusing-express-entry-on-top-talent-that-drives-economic-growth.html")]
    assert (release["department"], release["item_type"], release["published"]) == ("ircc", "news_release", "2026-10-16")
    assert release["title_fr"].startswith("Le Canada réoriente")
    assert release["summary_en"].startswith("Building a stronger Canada")
    assert release["summary_fr"].startswith("Pour bâtir un Canada plus fort")
    assert (release["first_seen"], release["last_seen"]) == (NOW, NOW)
    esdc = [r for r in stored.values() if r["department"] == "esdc"]
    assert len(esdc) == 2 and all(json.loads(r["terms_en"]) == ["Temporary Foreign Worker"] for r in esdc)
    # The first night is the baseline: one line, no notice per item.
    assert notices_of(conn) == ["Government notices read for the first time: 10 listed from the last 12 months "
                                "(no notice per item on the first night)"]
    assert last_log(conn)["ok"] == 1
    assert get_meta(conn, "notices_baseline") == "2026-10-26"
    states = {r["key"]: r["state"] for r in conn.execute("SELECT key, state FROM gov_notice_feeds")}
    assert states == {"ircc_en": "ok", "ircc_fr": "ok", "esdc_en": "ok", "esdc_fr": "ok"}


def test_items_first_listed_tonight_are_one_notice_each_up_to_five(conn, fixtures, fake_client):
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    later = "2026-10-27T00:10:00Z"
    news = [entry(f"Express Entry measure {n}", f"https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/m{n}.html",
                  f"2026-10-26T1{n}:00:00-04:00", "news releases") for n in range(7)]
    feeds = {"ircc_en": with_entries(feed_bytes(fixtures, "ircc_en"), *reversed(news))}
    stats = N.run(conn, fake_client(mapping(fixtures, later, feeds=feeds)), now=later)
    assert stats.summary() == "17 listed, 7 new tonight"
    got = notices_of(conn)
    assert got[:5] == [
        f"Government notice: 2026-10-26 Express Entry measure {n} "
        f"https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/m{n}.html"
        for n in (6, 5, 4, 3, 2)
    ]
    assert got[5] == "Government notices: 2 more first listed tonight, on the Notices page"
    assert len(got) == 6 and last_log(conn)["ok"] == 1
    # The next night with nothing new: no notice at all.
    third = "2026-10-28T00:10:00Z"
    N.run(conn, fake_client(mapping(fixtures, third, feeds=feeds)), now=third)
    assert notices_of(conn) == []


def test_each_notice_keeps_its_full_title_and_link_and_only_whole_notices_fill_the_row(conn):
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/" + "x" * 150 + ".html"
    title = ("Express Entry " * 35).strip()
    assert N.item_notice("2026-10-26", title, url) == f"Government notice: 2026-10-26 {title} {url}"
    # The separator the run status splits on never reaches a notice from a title.
    assert N.item_notice("2026-10-26", "Express Entry | Work permits", url).count(N.NOTICE_SEP) == 0
    # Seven items with long titles and links: as many whole notices as the
    # 3,000-character row holds, then a count of the rest.
    ids = []
    for n in range(7):
        rid = f"long{n:012d}"
        conn.execute("INSERT INTO gov_notices (id, department, item_type, published_at, published, title_en, url_en, "
                     "terms_en, first_seen, last_seen) VALUES (?, 'ircc', 'news_release', ?, '2026-10-26', ?, ?, "
                     "'[\"Express Entry\"]', ?, ?)",
                     (rid, f"2026-10-26T1{n}:00:00-04:00", f"{title} {n}", f"{url[:-5]}{n}.html", NOW, NOW))
        ids.append(rid)
    lines = N.new_item_notices(conn, ids)
    shown = lines[:-1]
    assert 0 < len(shown) < 5
    for n, line in zip(range(6, -1, -1), shown):
        assert line == f"Government notice: 2026-10-26 {title} {n} {url[:-5]}{n}.html"
    assert lines[-1] == f"Government notices: {7 - len(shown)} more first listed tonight, on the Notices page"
    assert len(N.NOTICE_SEP.join(lines)) <= N.NOTICE_MAX_CHARS == 3000


def test_a_feed_that_cannot_be_read_keeps_its_items_and_is_reported_on_a_change_only(conn, fixtures, fake_client):
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    before = {k: dict(r) for k, r in rows(conn).items()}
    seen = []
    for night in range(27, 32):
        now = f"2026-10-{night}T00:10:00Z"
        skip = ("ircc_fr",) if night in (27, 28, 29) else ()
        stats = N.run(conn, fake_client(mapping(fixtures, now, skip=skip)), now=now)
        seen.append(notices_of(conn))
        if night == 27:
            assert stats.states["ircc_fr"] == "failing"
            assert stats.summary() == "10 listed, 0 new tonight; not read: ircc_fr"
            # The French side of every stored item is kept.
            for rid, row in rows(conn).items():
                assert (row["title_fr"], row["summary_fr"], row["terms_fr"]) == (
                    before[rid]["title_fr"], before[rid]["summary_fr"], before[rid]["terms_fr"])
    assert seen[0] == [
        "Government notice feeds not read from tonight (their items are kept): ircc_fr (not fetched: HTTP 404 for "
        + night_urls("2026-10-27T00:10:00Z")["ircc_fr"][:120 - len("not fetched: HTTP 404 for ")] + ")"]
    assert seen[1] == [] and seen[2] == []
    assert seen[3] == ["Government notice feeds read again: ircc_fr"]
    assert seen[4] == []
    feed = conn.execute("SELECT * FROM gov_notice_feeds WHERE key = 'ircc_fr'").fetchone()
    assert (feed["state"], feed["last_ok_at"], feed["entries"]) == ("ok", "2026-10-31T00:10:00Z", 14)
    assert all(r["ok"] == 1 for r in conn.execute("SELECT ok FROM sources_log WHERE source = 'gov_notices'"))


def test_a_feed_failing_on_the_first_night_is_reported_once(conn, fixtures, fake_client):
    N.run(conn, fake_client(mapping(fixtures, skip=("esdc_en", "esdc_fr"))), now=NOW)
    assert notices_of(conn)[0].startswith("Government notice feeds not read from tonight (their items are kept): esdc_en (")
    assert "; esdc_fr (" in notices_of(conn)[0]
    assert len(rows(conn)) == 8
    # Read the next night: its items are new to the site, and announced.
    later = "2026-10-27T00:10:00Z"
    N.run(conn, fake_client(mapping(fixtures, later)), now=later)
    got = notices_of(conn)
    assert got[0] == "Government notice feeds read again: esdc_en, esdc_fr"
    assert [n.split(" https://")[0] for n in got[1:]] == [
        "Government notice: 2026-07-09 The Government of Canada highlights doubling of compliance monetary penalties "
        "under the Temporary Foreign Worker Program",
        "Government notice: 2026-03-13 Government of Canada taking action to support rural employers under the "
        "Temporary Foreign Worker Program",
    ]


def test_nothing_read_at_all_sets_no_baseline_and_stores_nothing(conn, fake_client):
    stats = N.run(conn, fake_client({}), now=NOW)
    assert stats.summary() == "0 listed, 0 new tonight; not read: esdc_en, esdc_fr, ircc_en, ircc_fr"
    assert get_meta(conn, "notices_baseline") is None and rows(conn) == {}
    assert get_meta(conn, "notices_last_run") == NOW


def test_a_layout_change_is_a_failing_feed_that_keeps_its_items(conn, fixtures, fake_client):
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    later = "2026-10-27T00:10:00Z"
    stats = N.run(conn, fake_client(mapping(fixtures, later, feeds={"ircc_en": b"<html>moved</html>"})), now=later)
    assert stats.states["ircc_en"] == "failing" and len(rows(conn)) == 10
    assert "ircc_en (not read: not an Atom feed" in notices_of(conn)[0]


def test_with_the_english_feed_down_the_french_side_still_updates(conn, fixtures, fake_client):
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    later = "2026-10-27T00:10:00Z"
    fr = feed_bytes(fixtures, "ircc_fr").replace("Le Canada réoriente le système Entrée express".encode(),
                                                 "Le Canada réoriente Entrée express".encode())
    N.run(conn, fake_client(mapping(fixtures, later, skip=("ircc_en",), feeds={"ircc_fr": fr})), now=later)
    stored = rows(conn)
    assert len(stored) == 10
    release = next(r for r in stored.values() if (r["title_en"] or "").startswith("Canada refocusing"))
    assert release["title_fr"].startswith("Le Canada réoriente Entrée express")
    assert release["last_seen"] == later and release["first_seen"] == NOW


def test_french_only_rows_are_folded_into_their_english_row_on_a_later_night(conn, fixtures, fake_client):
    # The first night the English IRCC feed is down: the French items are stored on their own.
    N.run(conn, fake_client(mapping(fixtures, skip=("ircc_en",))), now=NOW)
    first = rows(conn)
    french_only = [r for r in first.values() if r["url_en"] is None]
    assert len(first) == 9 and len(french_only) == 7
    assert all(r["id"] == N.notice_id(r["url_fr"]) for r in french_only)
    later = "2026-10-27T00:10:00Z"
    N.run(conn, fake_client(mapping(fixtures, later)), now=later)
    stored = rows(conn)
    assert len(stored) == 10
    assert all(r["url_en"] for r in stored.values())
    release = stored[N.notice_id("https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/"
                                 "canada-refocusing-express-entry-on-top-talent-that-drives-economic-growth.html")]
    # Folded, not new: it keeps the night it was first listed and is not announced again.
    assert release["first_seen"] == NOW and release["title_fr"].startswith("Le Canada réoriente")
    got = notices_of(conn)
    assert got[0] == "Government notice feeds read again: ircc_en"
    assert [n.split(" https://")[0] for n in got[1:]] == [
        "Government notice: 2026-03-31 Canada extends certain work permit measures for Ukrainians"]


# -- export, status and wiring ---------------------------------------------------------------


def test_the_export_writes_notices_json_and_the_sitemap_entry_after_the_first_read(conn, fixtures, fake_client, tmp_path,
                                                                                   monkeypatch):
    monkeypatch.setattr("lmia_pipeline.config.SITE_URL", "https://lmiawatch.ca")
    conn.execute("INSERT INTO meta (key, value) VALUES ('data_as_of', '2026-10-26')")
    conn.commit()
    out = tmp_path / "static"
    export_static.export_static(conn, out)
    assert not (out / "notices.json").exists()
    assert "/notices<" not in (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    # An item published before the 12-month window stays stored and is not listed.
    conn.execute("INSERT INTO gov_notices (id, department, item_type, published_at, published, title_en, url_en, "
                 "terms_en, first_seen, last_seen) VALUES ('old0000000000000', 'ircc', 'news_release', "
                 "'2025-10-01T10:00:00-04:00', '2025-10-01', 'Old Express Entry', "
                 "'https://www.canada.ca/en/x.html', '[\"Express Entry\"]', ?, ?)", (NOW, NOW))
    conn.commit()
    export_static.export_static(conn, out)
    doc = json.loads((out / "notices.json").read_text(encoding="utf-8"))
    assert (doc["count"], doc["first"], doc["last"], doc["window_from"]) == (10, "2026-02-17", "2026-10-16", "2025-10-26")
    assert (doc["as_of"], doc["last_checked"]) == ("2026-10-26", "2026-10-26")
    assert [f["key"] for f in doc["feeds"]] == ["ircc_en", "ircc_fr", "esdc_en", "esdc_fr"]
    assert {f["state"] for f in doc["feeds"]} == {"ok"} and doc["feeds"][0]["last_ok"] == "2026-10-26"
    assert len(doc["terms"]) == 17 and doc["terms"][0] == {"label": "LMIA", "lang": "en"}
    first = doc["items"][0]
    assert first["title"]["en"] == "Canada refocusing Express Entry on top talent that drives economic growth"
    assert first["terms"] == {"en": ["Express Entry"], "fr": ["Entrée express"]}
    assert (first["type"], first["department"], first["published"], first["first_seen"]) == (
        "news_release", "ircc", "2026-10-16", "2026-10-26")
    assert [i["published"] for i in doc["items"]] == sorted((i["published"] for i in doc["items"]), reverse=True)
    ukraine = next(i for i in doc["items"] if i["published"] == "2026-03-31")
    assert ukraine["title"]["fr"] is None and ukraine["url"]["fr"] is None and ukraine["terms"]["fr"] == []
    assert EM_DASH not in json.dumps(doc, ensure_ascii=False)
    sitemap = (out / "sitemaps" / "sitemap-1.xml").read_text(encoding="utf-8")
    assert "<url><loc>https://lmiawatch.ca/notices</loc><lastmod>2026-10-26</lastmod></url>" in sitemap


def test_the_run_status_carries_the_summary_and_the_notices(tmp_path, fixtures, fake_client):
    db = tmp_path / "lmia.sqlite"
    conn = connect(db)
    N.run(conn, fake_client(mapping(fixtures)), now=NOW)
    later = "2026-10-27T00:10:00Z"
    news = entry("Express Entry measure", "https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/m.html",
                 "2026-10-26T15:00:00-04:00", "news releases")
    N.run(conn, fake_client(mapping(fixtures, later, feeds={"ircc_en": with_entries(feed_bytes(fixtures, "ircc_en"), news)})),
          now=later)
    conn.close()
    status = nightly.run_status(db, "2026-10-27T00:00:00Z", {"problems": []}, None, {"deploy": "success"})
    assert status["government_notices"] == {
        "listed": 11, "new_tonight": 1, "summary": "11 listed, 1 new tonight", "last_checked": later,
        "feeds": {"esdc_en": "ok", "esdc_fr": "ok", "ircc_en": "ok", "ircc_fr": "ok"}}
    assert status["ok"] is True
    # The log rows carry the clock's time, not the stage's, so the notices are read from the start of the log.
    status = nightly.run_status(db, "2000-01-01T00:00:00Z", {"problems": []}, None, {"deploy": "success"})
    assert status["notices"][-1] == {"source": "gov_notices", "detail": "Government notice: 2026-10-26 Express Entry measure "
                                     "https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/m.html"}
    assert status["ok"] is True


def test_the_run_status_reads_a_database_from_before_the_stage(tmp_path):
    db = tmp_path / "lmia.sqlite"
    connect(db).close()
    status = nightly.run_status(db, "2026-10-27T00:00:00Z", {"problems": []}, None, {"deploy": "success"})
    assert status["government_notices"] == {} and status["ok"] is True


def test_the_stage_runs_after_the_lists_and_writes_its_outcome(tmp_path, fixtures, fake_client, monkeypatch):
    assert cli.STAGES.index("registers") < cli.STAGES.index("notices") < cli.STAGES.index("wages")
    assert cli.build_parser().parse_args(["run", "--notices"]).notices is True
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(N, "now_iso", lambda: NOW)
    made = []

    def client(*args, **kwargs):
        made.append(kwargs)
        return fake_client(mapping(fixtures))

    monkeypatch.setattr(cli, "PoliteClient", client)
    db = tmp_path / "lmia.sqlite"
    assert cli.main(["run", "--notices", "--db", str(db)]) == 0
    assert {"max_attempts": N.CLIENT_ATTEMPTS} in made
    assert (tmp_path / "out" / "notices" / "last_outcome.txt").read_text(encoding="utf-8") == \
        "10 listed, 10 new tonight (first read)\n"
    conn = connect(db)
    try:
        assert conn.execute("SELECT ok FROM sources_log WHERE source = 'gov_notices'").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_workflow_records_the_line_in_last_run():
    text = (config.REPO_ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    assert 'echo "Government notices: $(cat data/out/notices/last_outcome.txt)" >> LAST_RUN.md' in text
    # The stage runs inside the one pipeline step, which every stage shares.
    assert re.search(r"python -m lmia_pipeline run --db data/lmia.sqlite", text)
