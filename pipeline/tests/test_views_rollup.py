"""The audience roll-up, against a stub session: nothing here reaches the network."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from lmia_pipeline import cli, config, nightly, views_rollup as vr

ACCOUNT = "0123456789abcdef0123456789abcdef"
TOKEN = "analytics-token-value"
ENV = {vr.TOKEN_ENV: TOKEN, vr.ACCOUNT_ENV: ACCOUNT, "BSKY_HANDLE": "lmiawatch.ca"}
NOW = datetime(2026, 10, 22, 0, 40, tzinfo=timezone.utc)
YESTERDAY = date(2026, 10, 21)
START = 1792540800  # 2026-10-21T00:00:00Z


class FakeResponse:
    def __init__(self, status: int, body: object = None, text: str | None = None) -> None:
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self) -> object:
        if self._body is None:
            raise ValueError("no json")
        return self._body


def answer(rows: list[dict]) -> FakeResponse:
    # The shape the SQL API gives with FORMAT JSON; 64-bit sums come quoted.
    return FakeResponse(200, {"meta": [], "data": rows, "rows": len(rows)})


KINDS = [{"kind": "page", "responses": "120"}, {"kind": "api", "responses": "30"},
         {"kind": "download", "responses": "4"}, {"kind": "form", "responses": "1"},
         {"kind": "feed", "responses": "40"}, {"kind": "hook", "responses": "2"}, {"kind": "other", "responses": "9"}]
COUNTS = [
    {"route": "/employers/:id", "kind": "page", "lang": "en", "country": "CA", "referrer": "news.example.org",
     "status": 200, "responses": "70"},
    {"route": "/", "kind": "page", "lang": "fr", "country": "CA", "referrer": "", "status": 200, "responses": "50"},
    {"route": "/api/stats", "kind": "api", "lang": "en", "country": "US", "referrer": "", "status": 200, "responses": "30"},
    {"route": "/downloads/employers.csv", "kind": "download", "lang": "en", "country": "", "referrer": "",
     "status": 200, "responses": "4"},
    {"route": "/corrections", "kind": "form", "lang": "en", "country": "CA", "referrer": "lmiawatch.ca",
     "status": 200, "responses": "1"},
    {"route": "/data/feeds/:file", "kind": "feed", "lang": "en", "country": "US", "referrer": "", "status": 200,
     "responses": "36"},
    {"route": "/data/feeds/:file", "kind": "feed", "lang": "en", "country": "US", "referrer": "", "status": 404,
     "responses": "4"},
    {"route": "/hooks/kofi", "kind": "hook", "lang": "en", "country": "", "referrer": "", "status": 200, "responses": "2"},
    {"route": "other", "kind": "other", "lang": "en", "country": "NL", "referrer": "", "status": 404, "responses": "9"},
]
FEEDS = [
    {"feed": "", "responses": "4", "subscribers": 0},
    {"feed": "feeds/canada/pending.xml", "responses": "30", "subscribers": 12},
    {"feed": "feeds/prov/BC/approved.xml", "responses": "6", "subscribers": 3.0},
]


class FakeHttp:
    """Stands in for requests.Session. Answers the SQL API per day from `days`
    (day -> (kinds, counts, feeds); a day not listed has no data points) and
    the Bluesky profile from `profile`. `fail` replaces every SQL answer."""

    def __init__(self, days: dict | None = None, *, fail: FakeResponse | Exception | None = None,
                 profile: FakeResponse | Exception | None = None) -> None:
        self.days = {YESTERDAY: (KINDS, COUNTS, FEEDS)} if days is None else days
        self.fail = fail
        self.profile = profile or FakeResponse(200, {"did": "did:plc:x", "handle": "lmiawatch.ca", "followersCount": 57})
        self.posts: list[dict] = []
        self.gets: list[dict] = []
        self.closed = False

    def post(self, url, data=None, headers=None, timeout=None):
        sql = data.decode("utf-8")
        self.posts.append({"url": url, "sql": sql, "headers": headers or {}})
        if isinstance(self.fail, Exception):
            raise self.fail
        if self.fail is not None:
            return self.fail
        # The start bound names the day (its end bound is the next day's start).
        day = next((d for d in self.days if f">= toDateTime({vr.day_bounds(d)[0]})" in sql), None)
        kinds, counts, feeds = self.days.get(day, ([], [], []))
        if "blob7 AS feed" in sql:
            return answer(feeds)
        if "GROUP BY kind " in sql:
            return answer(kinds)
        return answer(counts)

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers or {}})
        if isinstance(self.profile, Exception):
            raise self.profile
        return self.profile

    def close(self):
        self.closed = True


def read_csv(path) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    return list(reader.fieldnames or []), list(reader)


def roll(tmp_path, http: FakeHttp | None = None, **kw) -> str:
    return vr.run(tmp_path, env=kw.pop("env", ENV), session=http if http is not None else FakeHttp(), now=NOW, **kw)


@pytest.fixture(autouse=True)
def site(monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")


# -- SQL ----------------------------------------------------------------------


def test_the_sql_for_a_day_covers_exactly_that_utc_day():
    assert vr.day_bounds(YESTERDAY) == (START, START + 86_400)
    assert vr.counts_sql(YESTERDAY) == (
        "SELECT blob1 AS route, blob2 AS kind, blob3 AS lang, blob4 AS country, blob5 AS referrer, "
        "double1 AS status, SUM(_sample_interval) AS responses FROM lmia_watch_views "
        f"WHERE timestamp >= toDateTime({START}) AND timestamp < toDateTime({START + 86_400}) "
        "GROUP BY route, kind, lang, country, referrer, status ORDER BY responses DESC LIMIT 10000 FORMAT JSON"
    )
    assert vr.kinds_sql(YESTERDAY) == (
        "SELECT blob2 AS kind, SUM(_sample_interval) AS responses FROM lmia_watch_views "
        f"WHERE timestamp >= toDateTime({START}) AND timestamp < toDateTime({START + 86_400}) "
        "GROUP BY kind ORDER BY kind FORMAT JSON"
    )
    feeds = vr.feeds_sql(YESTERDAY)
    assert "blob7 AS feed" in feeds and "MAX(double2) AS subscribers" in feeds and "blob2 = 'feed'" in feeds
    assert f"toDateTime({START})" in feeds and f"toDateTime({START + 86_400})" in feeds
    # Sampled counts are summed, never counted.
    for sql in (vr.counts_sql(YESTERDAY), vr.kinds_sql(YESTERDAY), feeds):
        assert "COUNT(" not in sql.upper() and "SUM(_sample_interval)" in sql


def test_each_query_is_a_post_with_the_sql_as_body_and_the_token_only_in_the_header(tmp_path):
    http = FakeHttp()
    assert roll(tmp_path, http, day=YESTERDAY) == "rolled up"
    assert [p["sql"] for p in http.posts] == [vr.kinds_sql(YESTERDAY), vr.counts_sql(YESTERDAY), vr.feeds_sql(YESTERDAY)]
    for p in http.posts:
        assert p["url"] == f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/analytics_engine/sql"
        assert p["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert p["headers"]["User-Agent"] == config.USER_AGENT
        assert TOKEN not in p["url"] and TOKEN not in p["sql"]
    assert not http.closed  # a session handed in belongs to the caller


# -- the files ----------------------------------------------------------------


def test_the_day_file_holds_the_total_the_kinds_every_count_and_every_feed(tmp_path):
    assert roll(tmp_path) == "rolled up"
    header, rows = read_csv(tmp_path / "2026-10-21.csv")
    assert header == vr.DAY_HEADER == ["date", "section", "route", "kind", "lang", "country", "referrer", "status",
                                       "feed", "responses", "subscribers"]
    assert {r["date"] for r in rows} == {"2026-10-21"}
    sections = [r["section"] for r in rows]
    assert sections == ["total"] + ["kind"] * 7 + ["count"] * 9 + ["feed"] * 3
    assert rows[0]["responses"] == "206" and rows[0]["route"] == "" and rows[0]["subscribers"] == ""
    assert {r["kind"]: r["responses"] for r in rows if r["section"] == "kind"} == {
        "api": "30", "download": "4", "feed": "40", "form": "1", "hook": "2", "other": "9", "page": "120"}
    first = rows[8]
    assert (first["route"], first["kind"], first["lang"], first["country"], first["referrer"], first["status"],
            first["responses"]) == ("/employers/:id", "page", "en", "CA", "news.example.org", "200", "70")
    feeds = {r["feed"]: (r["route"], r["kind"], r["responses"], r["subscribers"]) for r in rows if r["section"] == "feed"}
    assert feeds == {
        "": ("/data/feeds/:file", "feed", "4", "0"),
        "feeds/canada/pending.xml": ("/data/feeds/:file", "feed", "30", "12"),
        "feeds/prov/BC/approved.xml": ("/data/feeds/:file", "feed", "6", "3"),
    }
    assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == "2026-10-21\n"
    assert not list(tmp_path.glob("*.partial"))


def test_a_value_the_worker_would_never_write_is_blanked_before_it_is_stored(tmp_path):
    odd = [
        {"route": "/someone@example.com/profile?x=1", "kind": "page", "lang": "de",
         "country": "Canada", "referrer": "https://news.example.org/story?id=7", "status": 200, "responses": "3"},
        {"route": "/", "kind": "Mozilla/5.0 (X11; Linux x86_64)", "lang": "en", "country": "203.0.113.42",
         "referrer": "UPPER.example", "status": "nan", "responses": "2"},
    ]
    feeds = [{"feed": "feeds/../../etc/passwd.xml", "responses": "1", "subscribers": "inf"}]
    kinds = [{"kind": "page", "responses": "5"}]
    assert roll(tmp_path, FakeHttp({YESTERDAY: (kinds, odd, feeds)})) == "rolled up"
    text = (tmp_path / "2026-10-21.csv").read_text(encoding="utf-8")
    for leaked in ("someone@example.com", "?x=1", "Canada", "/story", "id=7", "Mozilla", "203.0.113.42", "UPPER",
                   "passwd", "inf", "nan", "de,"):
        assert leaked not in text, leaked
    _, rows = read_csv(tmp_path / "2026-10-21.csv")
    counts = [(r["route"], r["kind"], r["lang"], r["country"], r["referrer"], r["status"], r["responses"])
              for r in rows if r["section"] == "count"]
    assert counts == [("other", "page", "", "", "", "200", "3"), ("/", "other", "en", "", "", "", "2")]
    assert [(r["feed"], r["subscribers"]) for r in rows if r["section"] == "feed"] == [("", "0")]


def test_the_summary_gets_one_row_per_day_and_a_re_run_replaces_it_in_place(tmp_path):
    summary = tmp_path / vr.SUMMARY
    summary.write_text(
        ",".join(vr.SUMMARY_HEADER) + "\n"
        "2026-10-19,100,80,10,5,1,4,0,6,50,/ 60\n"
        "2026-10-20,110,90,10,5,1,4,0,6,55,/ 61\n", encoding="utf-8")
    assert roll(tmp_path) == "rolled up"
    header, rows = read_csv(summary)
    assert header == vr.SUMMARY_HEADER == ["date", "responses", "pages", "api", "downloads", "forms", "feeds", "other",
                                           "feed_subscribers", "bluesky_followers", "top_routes"]
    assert [r["date"] for r in rows] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert rows[0]["top_routes"] == "/ 60"  # earlier rows are kept as they were
    new = rows[-1]
    assert {k: new[k] for k in vr.SUMMARY_HEADER} == {
        "date": "2026-10-21", "responses": "206", "pages": "120", "api": "30", "downloads": "4", "forms": "1",
        "feeds": "40", "other": "11", "feed_subscribers": "15", "bluesky_followers": "57",
        "top_routes": "/employers/:id 70; / 50; /data/feeds/:file 36; /api/stats 30; /downloads/employers.csv 4",
    }

    # The same night again (a manual re-run): still one row for the day, and a
    # follower count that could not be read this time keeps the one it had.
    again = FakeHttp(profile=FakeResponse(503, None, "unavailable"))
    assert roll(tmp_path, again) == "rolled up"
    _, rows = read_csv(summary)
    assert [r["date"] for r in rows] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert rows[-1]["bluesky_followers"] == "57" and rows[-1]["responses"] == "206"


def test_a_summary_that_cannot_be_read_safely_is_never_replaced(tmp_path):
    summary = tmp_path / vr.SUMMARY
    bad = [
        "",  # an empty download
        "date,responses,visitors_ip\n2026-10-20,5,x\n",  # a column this code does not know
        ",".join(vr.SUMMARY_HEADER) + "\nnot-a-date,1,1,0,0,0,0,0,0,,\n",
        ",".join(vr.SUMMARY_HEADER) + "\n2026-13-45,1,1,0,0,0,0,0,0,,\n",
        ",".join(vr.SUMMARY_HEADER) + "\n2026-10-20,1,1,0,0,0,0,0,0,,,extra\n",
    ]
    for text in bad:
        summary.write_text(text, encoding="utf-8")
        http = FakeHttp()
        assert roll(tmp_path, http) == "failed", text
        assert summary.read_text(encoding="utf-8") == text
        assert http.posts == []
        assert not (tmp_path / "2026-10-21.csv").exists()
        assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == ""


# -- outcomes -----------------------------------------------------------------


def test_without_a_token_nothing_is_asked_and_nothing_written(tmp_path, caplog):
    (tmp_path / vr.ROLLED_UP).write_text("2026-10-01\n", encoding="utf-8")  # left by an earlier run
    http = FakeHttp()
    caplog.set_level("INFO")
    assert roll(tmp_path, http, env={vr.ACCOUNT_ENV: ACCOUNT}) == "no token"
    assert roll(tmp_path, http, env={vr.TOKEN_ENV: "  ", vr.ACCOUNT_ENV: ACCOUNT}) == "no token"
    assert "no analytics token; nothing rolled up" in caplog.text
    assert http.posts == [] and http.gets == []
    assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == ""
    assert not (tmp_path / vr.SUMMARY).exists()


@pytest.mark.parametrize("fail", [
    FakeResponse(500, None, "internal error"),
    FakeResponse(401, {"errors": [{"message": "Authentication error"}]}),
    FakeResponse(200, {"errors": []}),  # no rows
    FakeResponse(200, {"data": "not rows"}),
    FakeResponse(200, None, "<html>"),
    requests.ConnectionError("connection reset"),
])
def test_an_api_failure_is_failed_and_leaves_every_file_as_it_was(tmp_path, fail, caplog):
    summary = tmp_path / vr.SUMMARY
    summary.write_text(",".join(vr.SUMMARY_HEADER) + "\n2026-10-20,1,1,0,0,0,0,0,0,,/ 1\n", encoding="utf-8")
    before = summary.read_text(encoding="utf-8")
    assert roll(tmp_path, FakeHttp(fail=fail)) == "failed"
    assert summary.read_text(encoding="utf-8") == before
    assert not (tmp_path / "2026-10-21.csv").exists()
    assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == ""
    assert TOKEN not in caplog.text


def test_a_failure_part_way_through_a_catch_up_writes_nothing(tmp_path):
    summary = tmp_path / vr.SUMMARY
    summary.write_text(",".join(vr.SUMMARY_HEADER) + "\n2026-10-19,1,1,0,0,0,0,0,0,,/ 1\n", encoding="utf-8")

    class FailsLater(FakeHttp):
        def post(self, url, data=None, headers=None, timeout=None):
            if len(self.posts) >= 3:
                self.posts.append({"url": url, "sql": data.decode(), "headers": headers})
                return FakeResponse(502, None, "bad gateway")
            return super().post(url, data=data, headers=headers, timeout=timeout)

    days = {date(2026, 10, 20): (KINDS, COUNTS, FEEDS), YESTERDAY: (KINDS, COUNTS, FEEDS)}
    assert roll(tmp_path, FailsLater(days)) == "failed"
    assert not list(tmp_path.glob("2026-*.csv"))
    assert summary.read_text(encoding="utf-8").count("\n") == 2


def test_missing_days_are_caught_up_and_empty_days_are_not_written(tmp_path):
    summary = tmp_path / vr.SUMMARY
    summary.write_text(",".join(vr.SUMMARY_HEADER) + "\n2026-10-17,1,1,0,0,0,0,0,0,,/ 1\n", encoding="utf-8")
    days = {date(2026, 10, 18): (KINDS, COUNTS, FEEDS), YESTERDAY: (KINDS, COUNTS, FEEDS)}
    http = FakeHttp(days)
    assert roll(tmp_path, http) == "rolled up"
    asked = [p["sql"] for p in http.posts if "GROUP BY kind " in p["sql"]]
    assert asked == [vr.kinds_sql(date(2026, 10, d)) for d in (18, 19, 20, 21)]
    # An empty day costs one question, not three.
    assert len(http.posts) == 4 + 2 * 2
    assert sorted(p.name for p in tmp_path.glob("2026-*.csv")) == ["2026-10-18.csv", "2026-10-21.csv"]
    assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == "2026-10-18\n2026-10-21\n"
    _, rows = read_csv(summary)
    assert [(r["date"], r["bluesky_followers"]) for r in rows] == [
        ("2026-10-17", ""), ("2026-10-18", ""), ("2026-10-21", "57")]
    assert len(http.gets) == 1  # the follower count is read once, for yesterday


def test_the_first_night_asks_for_all_three_months_analytics_engine_keeps(tmp_path):
    early = date(2026, 10, 9)
    http = FakeHttp({early: (KINDS, COUNTS, FEEDS), YESTERDAY: (KINDS, COUNTS, FEEDS)})
    assert roll(tmp_path, http) == "rolled up"
    asked = [p["sql"] for p in http.posts if "GROUP BY kind " in p["sql"]]
    assert len(asked) == vr.RETENTION_DAYS
    assert asked[0] == vr.kinds_sql(YESTERDAY - timedelta(days=vr.RETENTION_DAYS - 1))
    assert asked[-1] == vr.kinds_sql(YESTERDAY)
    _, rows = read_csv(tmp_path / vr.SUMMARY)
    assert [r["date"] for r in rows] == ["2026-10-09", "2026-10-21"]


def test_days_due():
    assert vr.days_to_roll(["2026-10-20"], YESTERDAY) == [YESTERDAY]
    # Already rolled up tonight: yesterday again, in place.
    assert vr.days_to_roll(["2026-10-19", "2026-10-21"], YESTERDAY) == [YESTERDAY]
    assert vr.days_to_roll(["2026-10-18"], YESTERDAY) == [date(2026, 10, 19), date(2026, 10, 20), YESTERDAY]
    # Never further back than the retention, however old the newest row.
    long_ago = vr.days_to_roll(["2025-01-01"], YESTERDAY)
    assert len(long_ago) == vr.RETENTION_DAYS and long_ago[-1] == YESTERDAY


def test_no_data_points_at_all_is_no_data(tmp_path):
    http = FakeHttp({})
    assert vr.run(tmp_path, day=YESTERDAY, env=ENV, session=http, now=NOW) == "no data"
    assert len(http.posts) == 1
    assert not (tmp_path / vr.SUMMARY).exists()
    assert (tmp_path / vr.ROLLED_UP).read_text(encoding="utf-8") == ""


def test_a_day_asked_for_by_hand_must_be_over_and_still_held(tmp_path):
    for day in (NOW.date(), NOW.date() + timedelta(days=3), YESTERDAY - timedelta(days=vr.RETENTION_DAYS)):
        http = FakeHttp()
        assert vr.run(tmp_path, day=day, env=ENV, session=http, now=NOW) == "failed", day
        assert http.posts == []
    oldest = YESTERDAY - timedelta(days=vr.RETENTION_DAYS - 1)
    http = FakeHttp({oldest: (KINDS, COUNTS, FEEDS)})
    assert vr.run(tmp_path, day=oldest, env=ENV, session=http, now=NOW) == "rolled up"
    assert (tmp_path / f"{oldest.isoformat()}.csv").exists()
    assert http.gets == []  # not yesterday, so no follower reading is attached


def test_a_malformed_account_id_is_failed_before_any_request(tmp_path):
    http = FakeHttp()
    assert roll(tmp_path, http, env={vr.TOKEN_ENV: TOKEN, vr.ACCOUNT_ENV: "abc/../../zones"}) == "failed"
    assert roll(tmp_path, http, env={vr.TOKEN_ENV: TOKEN}) == "failed"
    assert http.posts == []


# -- Bluesky ------------------------------------------------------------------


def test_the_bluesky_follower_count_is_read_from_the_public_profile():
    assert vr.parse_followers({"followersCount": 12, "followsCount": 3}) == 12
    assert vr.parse_followers({"followersCount": 0}) == 0
    for odd in ({"followersCount": "12"}, {"followersCount": -1}, {"followersCount": True},
                {"followersCount": 1.5}, {}, [], None, "12"):
        assert vr.parse_followers(odd) is None, odd

    http = FakeHttp()
    assert vr.bluesky_followers(http, "lmiawatch.ca") == 57
    (get,) = http.gets
    parts = urlsplit(get["url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == vr.BSKY_PROFILE_URL
    assert parse_qs(parts.query) == {"actor": ["lmiawatch.ca"]}
    assert "Authorization" not in get["headers"]

    assert vr.bluesky_followers(FakeHttp(profile=FakeResponse(400, {"error": "InvalidRequest"})), "x.example") is None
    assert vr.bluesky_followers(FakeHttp(profile=requests.Timeout("slow")), "lmiawatch.ca") is None
    assert vr.bluesky_followers(FakeHttp(profile=FakeResponse(200, {"handle": "lmiawatch.ca"})), "lmiawatch.ca") is None
    assert vr.bluesky_followers(FakeHttp(), "") is None


def test_the_handle_comes_from_the_secret_else_the_site_domain(monkeypatch):
    assert vr.bluesky_handle({"BSKY_HANDLE": " @lmiawatch.ca "}) == "lmiawatch.ca"
    assert vr.bluesky_handle({}) == "lmiawatch.ca"
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.example")
    assert vr.bluesky_handle({}) == ""


def test_a_bluesky_outage_never_fails_the_roll_up(tmp_path):
    assert roll(tmp_path, FakeHttp(profile=requests.ConnectionError("down"))) == "rolled up"
    _, rows = read_csv(tmp_path / vr.SUMMARY)
    assert rows[-1]["bluesky_followers"] == ""


# -- the command and the run status -------------------------------------------


def test_the_command_exits_1_only_when_the_roll_up_failed(tmp_path, monkeypatch):
    monkeypatch.delenv(vr.TOKEN_ENV, raising=False)
    assert cli.main(["rollup-views", "--out", str(tmp_path)]) == 0

    fake = FakeHttp(fail=FakeResponse(500, None, "boom"))
    monkeypatch.setattr(requests, "Session", lambda: fake)
    monkeypatch.setenv(vr.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(vr.ACCOUNT_ENV, ACCOUNT)
    assert cli.main(["rollup-views", "--out", str(tmp_path)]) == 1
    assert fake.closed and fake.posts

    good = FakeHttp({date(2026, 9, 1): (KINDS, COUNTS, FEEDS)})
    monkeypatch.setattr(requests, "Session", lambda: good)
    monkeypatch.setattr(vr, "previous_day", lambda now=None: date(2026, 9, 2))
    assert cli.main(["rollup-views", "--out", str(tmp_path), "--day", "2026-09-01"]) == 0
    assert (tmp_path / "2026-09-01.csv").exists()


def test_the_run_status_carries_the_roll_up(tmp_path):
    db = tmp_path / "none.sqlite"
    assert nightly.run_status(db, None, None, None, {}, views="failed")["views_rollup"] == "failed"
    assert nightly.run_status(db, None, None, None, {})["views_rollup"] == "not run"
    (tmp_path / "views.txt").write_text("no token\n", encoding="utf-8")
    out = tmp_path / "status.json"
    assert nightly.main(["status", "--db", str(db), "--views-outcome", str(tmp_path / "views.txt"),
                         "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["views_rollup"] == "no token"
