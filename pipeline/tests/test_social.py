import json

import pytest
import requests

from lmia_pipeline import cli, config, social
from lmia_pipeline.db import connect, get_meta, set_meta, upsert_employer
from lmia_pipeline.social import Digest, EmployerLine, compose, x_length

EARLIER = "2026-10-16T12:04:00Z"
LATEST = "2026-10-17T12:05:00Z"
CREDS = {
    "X_API_KEY": "key", "X_API_SECRET": "secret",
    "X_ACCESS_TOKEN": "token", "X_ACCESS_TOKEN_SECRET": "token-secret",
}


class FakeJSON:
    def __init__(self, status: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body or {})

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakePoster:
    """Stands in for requests.Session: records each request, answers or raises as told.

    `response`/`exc` apply to the post itself; `upload`/`metadata` to the two media calls."""

    def __init__(self, response: FakeJSON | None = None, exc: Exception | None = None, *,
                 upload: FakeJSON | Exception | None = None, metadata: FakeJSON | Exception | None = None) -> None:
        self.response = response or FakeJSON(201, {"data": {"id": "1850000000000000001", "text": "t"}})
        self.exc = exc
        self.upload = upload or FakeJSON(200, {"data": {"id": "1850000000000000777", "media_key": "3_1850000000000000777"}})
        self.metadata = metadata or FakeJSON(200, {"data": {"id": "1850000000000000777"}})
        self.calls: list[dict] = []

    def post(self, url, json=None, auth=None, timeout=None, headers=None, files=None, data=None):
        self.calls.append({"url": url, "json": json, "auth": auth, "headers": headers, "files": files, "data": data})
        if url == social.UPLOAD_URL:
            if isinstance(self.upload, Exception):
                raise self.upload
            return self.upload
        if url == social.METADATA_URL:
            if isinstance(self.metadata, Exception):
                raise self.metadata
            return self.metadata
        if self.exc is not None:
            raise self.exc
        return self.response

    def tweets(self) -> list[dict]:
        return [c for c in self.calls if c["url"] == social.POST_URL]


def add_posting(conn, pid, employer, prov, city, vacancies, *, first_seen=LATEST, flag="requested", last_seen=None, date_posted=None):
    eid = upsert_employer(conn, employer, prov, source="jobbank", city=city, now=first_seen)
    conn.execute(
        "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, city, province, vacancies, "
        "first_seen, last_seen, flag_current, flag_first, url, updated_at, date_posted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'u', ?, ?)",
        (pid, eid, employer, city, prov, vacancies, first_seen, last_seen or first_seen, flag, flag, first_seen, date_posted or first_seen[:10]),
    )


def seed(conn):
    add_posting(conn, 1, "Old Posting Ltd", "MB", "Brandon", 9, first_seen=EARLIER)
    add_posting(conn, 10, "Acme Greenhouses Inc", "ON", "Leamington", 30)
    add_posting(conn, 11, "Acme Greenhouses Inc", "ON", "Kingsville", 12)
    add_posting(conn, 12, "Example Seafoods Ltd", "BC", "Prince Rupert", 25)
    add_posting(conn, 13, "Sample Hotels Corp", "AB", "Banff", 6)
    add_posting(conn, 14, "Ferme Exemple", "QC", "Saint-Rémi", 4)
    add_posting(conn, 15, "No Count Bakery", "NS", "Halifax", None)
    # First seen in the approved facet: not a new request, so not in the digest.
    add_posting(conn, 16, "Approved Already Inc", "SK", "Regina", 50, flag="approved")
    set_meta(conn, "jobbank_last_run", LATEST)
    conn.commit()


def test_collect_and_compose_from_seeded_database(conn, monkeypatch):
    seed(conn)
    d = social.collect(conn)
    assert (d.data_date, d.postings, d.positions, d.positions_known) == ("2026-10-17", 6, 77, 5)
    assert d.provinces == ["AB", "BC", "NS", "ON", "QC"]
    assert not d.first_pass
    # Acme's two postings add up; its location is the posting with the most vacancies.
    assert [(e.name, e.city, e.province, e.positions) for e in d.employers] == [
        ("Acme Greenhouses Inc", "Leamington", "ON", 42),
        ("Example Seafoods Ltd", "Prince Rupert", "BC", 25),
        ("Sample Hotels Corp", "Banff", "AB", 6),
    ]
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    text = compose(d, link=social.search_link())
    assert text == (
        'Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 6 postings, at least 77 positions.\n'
        "In AB, BC, NS, ON, QC\n"
        "Most positions:\n"
        "Acme Greenhouses Inc, Leamington ON: 42\n"
        "Example Seafoods Ltd, Prince Rupert BC: 25\n"
        "Sample Hotels Corp, Banff AB: 6\n"
        "https://lmiawatch.ca/search?date=7d"
    )
    assert x_length(text) <= 280


def test_headline_when_every_count_is_known_and_singular():
    d = Digest("2026-10-17", postings=1, positions=1, positions_known=1, provinces=["BC"])
    assert compose(d, link=None) == (
        'Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 1 posting, 1 position.\nIn BC'
    )
    none_known = Digest("2026-10-17", postings=3, positions=0, positions_known=0)
    assert compose(none_known, link=None) == 'Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 3 postings.'
    # Fewer than half the postings counted: the floor is left out rather than printed as "at least 2".
    few_known = Digest("2026-10-17", postings=2000, positions=2, positions_known=2)
    assert compose(few_known, link=None) == 'Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 2,000 postings.'
    half_known = Digest("2026-10-17", postings=4, positions=9, positions_known=2)
    assert compose(half_known, link=None).endswith('4 postings, at least 9 positions.')


def test_x_length_counts_links_as_23_and_wide_characters_as_two():
    assert x_length("https://lmiawatch.ca/search?date=7d") == 23
    assert x_length("Saint-Rémi") == 10
    assert x_length("東京") == 4
    assert x_length("Amazon.com.ca ULC") == 23 + 4
    assert x_length("St. John's") == 10


def test_truncation_ladder_drops_employers_from_the_end_then_provinces():
    d = Digest(
        "2026-10-17", postings=9, positions=90, positions_known=9,
        provinces=["AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK"],
        employers=[EmployerLine(f"Employer {c} Holdings Limited", "Somewhere", "ON", n)
                   for c, n in (("A", 40), ("B", 30), ("C", 20))],
    )
    link = "https://lmiawatch.ca/search?date=7d"
    full = compose(d, link=link, limit=10_000)
    seen: list[str] = []
    for limit in range(x_length(full), 0, -1):
        text = compose(d, link=link, limit=limit)
        if not seen or seen[-1] != text:
            seen.append(text)
    lines = [t.split("\n") for t in seen]
    head, prov = lines[0][0], lines[0][1]
    emp = lines[0][3:6]
    assert lines == [
        [head, prov, "Most positions:", *emp, link],
        [head, prov, "Most positions:", *emp[:2], link],
        [head, prov, "Most positions:", emp[0], link],
        [head, prov, link],
        [head, link],
    ]
    # At the real limit, long names give way before the province line does.
    d.employers = [EmployerLine("Long Name " * 9, "Somewhere", "ON", n) for n in (40, 30, 20)]
    text = compose(d, link=link)
    assert x_length(text) <= 280
    assert "\nIn AB, BC" in text and text.count("Long Name") == 9


def test_names_cannot_mention_or_tag():
    line = social._employer_line(EmployerLine("Cafe @Home #Bakery $ABC #1 Shop@Home", "Halifax", "NS", 2))
    assert line == "Cafe @ Home # Bakery $ ABC #1 Shop@Home, Halifax NS: 2"


def test_run_posts_once_and_refuses_a_second_post_for_the_same_data(conn, tmp_path):
    seed(conn)
    poster = FakePoster()
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
    # Upload, alt text, post: in that order, and the post carries the media id.
    assert [c["url"] for c in poster.calls] == [social.UPLOAD_URL, social.METADATA_URL, social.POST_URL]
    up, meta, call = poster.calls
    assert up["data"] == {"media_category": "tweet_image"} and up["files"]["media"][2] == "image/png"
    assert up["files"]["media"][1][:8] == b"\x89PNG\r\n\x1a\n"
    assert meta["json"]["id"] == "1850000000000000777" and "57" not in meta["json"]["metadata"]["alt_text"]["text"]
    assert meta["json"]["metadata"]["alt_text"]["text"].startswith("LMIA Watch daily card. Job Bank, 2026-10-17")
    assert call["json"]["text"].startswith('Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 6 postings')
    assert "http" not in call["json"]["text"]  # the link is off unless asked for
    assert call["json"]["media"] == {"media_ids": ["1850000000000000777"]}
    assert call["headers"]["User-Agent"].startswith("LMIAWatch/")
    assert get_meta(conn, "x_last_post_date") == "2026-10-17"
    assert get_meta(conn, "x_last_post_id") == "1850000000000000001"
    assert (tmp_path / "2026-10-17.txt").read_text(encoding="utf-8").strip() == call["json"]["text"]
    assert (tmp_path / "2026-10-17.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # A re-run of the night (the Job Bank guard leaves jobbank_last_run alone) posts nothing.
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "already posted"
    assert len(poster.tweets()) == 1


def test_link_is_opt_in(conn, tmp_path, monkeypatch):
    seed(conn)
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    poster = FakePoster()
    assert social.run(conn, link=True, image=False, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
    assert poster.tweets()[0]["json"]["text"].endswith("https://lmiawatch.ca/search?date=7d")
    assert [c["url"] for c in poster.calls] == [social.POST_URL]


def test_upload_failure_posts_text_only(conn, tmp_path):
    seed(conn)
    for poster in (FakePoster(upload=FakeJSON(402, {"title": "CreditsDepleted"})), FakePoster(upload=RuntimeError("boom"))):
        assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
        tweet = poster.tweets()[0]["json"]
        assert "media" not in tweet and tweet["text"].startswith("Newly flagged")
        conn.execute("DELETE FROM meta WHERE key IN ('x_last_post_date', 'x_last_post_id')"); conn.commit()


def test_alt_text_failure_keeps_the_image(conn, tmp_path):
    seed(conn)
    poster = FakePoster(metadata=FakeJSON(403, {"title": "Forbidden"}))
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
    assert poster.tweets()[0]["json"]["media"] == {"media_ids": ["1850000000000000777"]}


def test_card_renders_at_the_expected_size(conn):
    from io import BytesIO

    from PIL import Image

    from lmia_pipeline.social_card import CARD_EMPLOYERS, alt_text, render_card

    seed(conn)
    card = social.card_for(social.collect(conn))
    assert card.postings == 6 and card.positions_line == "at least 77 positions"
    assert card.title == "Job Bank, 2026-10-17"
    assert card.context == "Last 7 days: 7 postings, at least 86 positions"
    assert card.province_counts == {"AB": 1, "BC": 1, "NS": 1, "ON": 2, "QC": 1}
    assert [e.name for e in card.employers][:2] == ["Acme Greenhouses Inc", "Example Seafoods Ltd"]
    assert len(card.employers) <= CARD_EMPLOYERS and card.site == "lmiawatch.example"
    img = Image.open(BytesIO(render_card(card)))
    assert img.size == (1200, 675) and img.mode == "RGB"
    text = alt_text(card)
    assert len(text) <= 1000 and "Acme Greenhouses Inc, Leamington ON: 42" in text
    # A card for a thin day draws too.
    thin = social.card_for(social.Digest("2026-10-17", postings=1, positions=0, positions_known=0))
    assert thin.context is None
    assert Image.open(BytesIO(render_card(thin))).size == (1200, 675)


def test_empty_day_posts_nothing(conn, tmp_path):
    add_posting(conn, 1, "Old Posting Ltd", "MB", "Brandon", 9, first_seen=EARLIER)
    set_meta(conn, "jobbank_last_run", LATEST)
    poster = FakePoster()
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "no new postings"
    assert poster.calls == [] and list(tmp_path.iterdir()) == []
    assert get_meta(conn, "x_last_post_date") is None


def test_bulk_pass_posts_nothing(conn, tmp_path):
    # An earlier posting exists, so this is not a first pass, but the pass saw a backlog, not a day.
    add_posting(conn, 1, "Old Posting Ltd", "MB", "Brandon", 9, first_seen=EARLIER)
    for i in range(social.MAX_NEW_POSTINGS + 1):
        add_posting(conn, 100 + i, f"Employer {i} Ltd", "ON", "Toronto", 1)
    set_meta(conn, "jobbank_last_run", LATEST)
    conn.commit()
    poster = FakePoster()
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "bulk pass"
    assert poster.calls == [] and get_meta(conn, "x_last_post_date") is None


def test_no_pass_and_first_pass_post_nothing(conn, tmp_path):
    poster = FakePoster()
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "no pass"
    add_posting(conn, 10, "Acme Greenhouses Inc", "ON", "Leamington", 30)
    set_meta(conn, "jobbank_last_run", LATEST)
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "first pass"
    assert poster.calls == []


@pytest.mark.parametrize("poster", [
    FakePoster(exc=requests.ConnectionError("unreachable")),
    FakePoster(exc=RuntimeError("anything at all")),
    FakePoster(FakeJSON(403, {"title": "Forbidden", "detail": "duplicate content"})),
    FakePoster(FakeJSON(402, {"title": "CreditsDepleted"})),
])
def test_failed_post_is_logged_not_raised(conn, tmp_path, poster, caplog):
    seed(conn)
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "failed"
    assert len(poster.tweets()) == 1
    assert get_meta(conn, "x_last_post_date") is None
    assert "x: " in caplog.text
    assert "token-secret" not in caplog.text


def test_created_without_a_readable_id_still_counts_as_posted(conn, tmp_path):
    seed(conn)
    poster = FakePoster(FakeJSON(201, None, text="not json"))
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
    assert get_meta(conn, "x_last_post_date") == "2026-10-17"


def test_missing_credentials_skip_but_still_write_the_text(conn, tmp_path):
    seed(conn)
    poster = FakePoster()
    partial = dict(CREDS, X_ACCESS_TOKEN_SECRET="")
    assert social.run(conn, out_dir=tmp_path, env=partial, session=poster) == "no credentials"
    assert poster.calls == []
    assert (tmp_path / "2026-10-17.txt").exists() and (tmp_path / "2026-10-17.png").exists()
    assert repr(social.credentials_from_env(CREDS)) == "Credentials(****)"


def test_dry_run_prints_and_posts_nothing(conn, tmp_path):
    seed(conn)
    poster = FakePoster()
    printed: list[str] = []
    out = social.run(conn, dry_run=True, out_dir=tmp_path, env=CREDS, session=poster, echo=printed.append)
    assert out == "dry run" and poster.calls == []
    assert len(printed) == 1 and "http" not in printed[0]
    assert (tmp_path / "2026-10-17.png").exists()
    assert get_meta(conn, "x_last_post_date") is None


def test_oauth1_signs_the_request_without_the_json_body():
    from requests_oauthlib import OAuth1

    creds = social.credentials_from_env(CREDS)
    auth = OAuth1(creds.api_key, creds.api_secret, creds.access_token, creds.access_token_secret)
    prepared = requests.Request("POST", social.POST_URL, json={"text": "hello"}, auth=auth).prepare()
    header = prepared.headers["Authorization"]
    if isinstance(header, bytes):
        header = header.decode()
    assert header.startswith("OAuth ")
    for part in ("oauth_consumer_key=\"key\"", "oauth_token=\"token\"", "oauth_signature_method=\"HMAC-SHA1\"",
                 "oauth_signature="):
        assert part in header
    assert json.loads(prepared.body) == {"text": "hello"}


def test_local_date_is_the_eastern_day_of_the_pass():
    # 00:05 UTC on the 17th is 20:05 Eastern on the 16th; midday UTC stays the same day.
    assert social.local_date("2026-10-17T00:05:00Z") == "2026-10-16"
    assert social.local_date("2026-10-17T12:05:00Z") == "2026-10-17"
    assert social.local_date("2026-01-20T03:00:00Z") == "2026-01-19"


def test_gap_wording_and_week_context(conn, monkeypatch):
    # The previous pass was three days back (its postings' last_seen says so), so the
    # digest covers "since" that day; the week context counts by Job Bank's posting date.
    old_pass = "2026-10-14T12:00:00Z"
    add_posting(conn, 1, "Old Posting Ltd", "MB", "Brandon", 9, first_seen="2026-10-09T12:00:00Z", last_seen=old_pass, date_posted="2026-10-09")
    add_posting(conn, 2, "Week Posting Inc", "ON", "Ottawa", 4, first_seen="2026-10-12T12:00:00Z", last_seen=old_pass, date_posted="2026-10-12")
    add_posting(conn, 10, "Acme Greenhouses Inc", "ON", "Leamington", 30, date_posted="2026-10-16")
    add_posting(conn, 11, "Example Seafoods Ltd", "BC", "Prince Rupert", None, date_posted="2026-10-17")
    set_meta(conn, "jobbank_last_run", LATEST)
    conn.commit()
    d = social.collect(conn)
    assert d.since_date == "2026-10-14" and d.data_date == "2026-10-17"
    assert (d.week_postings, d.week_positions, d.week_known) == (3, 34, 2)
    text = compose(d, link=None)
    assert text.startswith('Newly flagged "LMIA requested" on Job Bank, since 2026-10-14: 2 postings, at least 30 positions.')
    card = social.card_for(d)
    assert card.title == "Job Bank, since 2026-10-14"
    assert card.context == "Last 7 days: 3 postings, at least 34 positions"
    # A day-old previous pass keeps the plain wording.
    conn.execute("UPDATE jobbank_postings SET last_seen = ? WHERE posting_id IN (1, 2)", (EARLIER,))
    conn.commit()
    d2 = social.collect(conn)
    assert d2.since_date is None and compose(d2, link=None).startswith('Newly flagged "LMIA requested" on Job Bank, 2026-10-17:')


def test_cli_exit_code_and_outcome_file(tmp_path, monkeypatch, capsys):
    db = tmp_path / "lmia.sqlite"
    c = connect(db)
    seed(c)
    c.close()
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    for name in CREDS:
        monkeypatch.setenv(name, CREDS[name])
    # Credentials set but the network is a fake that fails: the post fails, the exit is 1, the outcome is written.
    monkeypatch.setattr(social, "send_post", lambda *a, **k: None)
    assert cli.main(["post-digest", "--db", str(db), "--no-image"]) == 1
    assert (tmp_path / "out" / "social" / "last_outcome.txt").read_text(encoding="utf-8").strip() == "failed"


def test_cli_dry_run_returns_zero(tmp_path, monkeypatch, capsys):
    db = tmp_path / "lmia.sqlite"
    c = connect(db)
    seed(c)
    c.close()
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    for name in CREDS:
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["post-digest", "--db", str(db), "--dry-run", "--no-image"]) == 0
    assert capsys.readouterr().out.startswith('Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 6 postings')
    assert (tmp_path / "out" / "social" / "2026-10-17.txt").exists()
    assert not (tmp_path / "out" / "social" / "2026-10-17.png").exists()
