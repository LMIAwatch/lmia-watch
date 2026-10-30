"""Designated-employer lists the runner cannot read as published: a copy loaded by hand
kept in the site's private R2 bucket, with a nightly newer-edition check (Nova Scotia),
a site that blocks automated readers (Prince Edward Island), and a host that leaves an
intermediate certificate out (Brandon).

The live Nova Scotia file stands in as the one-page New Brunswick fixture: both
lists are bulleted PDFs read by the same rule. R2 is a dictionary (FakeStore), or
resilience.R2Rest over a fake HTTP session for the REST calls themselves.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import ssl
import sys
import tomllib
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from conftest import FakeResponse
from lmia_pipeline import nightly, resilience
from lmia_pipeline.db import upsert_employer
from lmia_pipeline.http import ContextAdapter, PoliteClient
from lmia_pipeline.sources import registers as R
from lmia_pipeline.sources.registers import REGISTERS, Row

PIPELINE = Path(__file__).resolve().parents[1]
BY_KEY = {r.key: r for r in REGISTERS}
NS = BY_KEY["aip_ns"]
PE = BY_KEY["aip_pe"]
CSV_KEY, META_KEY = "registers/aip_ns.csv", "registers/aip_ns.json"
COPY_URL = "https://liveinnovascotia.com/sites/default/files/2024-07/Designated_AIP_employers.pdf"
NEWER_URL = "https://liveinnovascotia.com/sites/default/files/2026-11/Designated_AIP_employers_November.pdf"
PAGE = b'<a href="/sites/default/files/2024-07/Designated_AIP_employers.pdf">Designated employers (PDF)</a>'
NEWER_PAGE = b'<a href="/sites/default/files/2026-11/Designated_AIP_employers_November.pdf">Designated employers</a>'
ETAG = '"713d2-6562d15681934"'
MODIFIED = "Thu, 09 Jul 2026 12:51:32 GMT"
NOT_A_PDF_TEXT = b"%PDF-1.4 the file pypdf cannot read"
COPY_ROWS = [Row(f"Harbour Fisheries {i} Limited") for i in range(8)] + [Row("Lunenburg Marine Works Inc.", "Lunenburg")]
NIGHT = "2026-11-02T00:10:00Z"


class FakeStore:
    """The bucket as a dictionary of objects; an exception set as `fail` is raised by every read."""

    def __init__(self, objects=None, fail=None):
        self.objects = dict(objects or {})
        self.fail = fail
        self.reads, self.uploads = [], []

    def get_bytes(self, key):
        self.reads.append(key)
        if self.fail is not None:
            raise self.fail
        return self.objects.get(key)

    def upload(self, key, data, content_type):
        self.uploads.append((key, content_type))
        self.objects[key] = data


def copy_objects(rows=COPY_ROWS, **record):
    fields = dict(source_url=COPY_URL, etag=ETAG, last_modified=MODIFIED, size=463826, sha256="0" * 64,
                  list_date="2026-07-01", loaded_on="2026-10-30")
    fields.update(record)
    csv_bytes, meta_bytes, _ = R.snapshot_objects(NS, rows, **fields)
    return {CSV_KEY: csv_bytes, META_KEY: meta_bytes}


@pytest.fixture
def fake_client(fake_client):
    """Each night's client with a cache of its own, as in test_registers."""
    made = []

    def make(mapping, **kwargs):
        client = fake_client(mapping, **kwargs)
        made.append(client)
        client.cache_dir = client.cache_dir.parent / f"cache-{len(made)}"
        return client

    return make


@pytest.fixture
def store():
    """The copy of the Nova Scotia list loaded by hand on 2026-10-30, as the loader script uploads it."""
    return FakeStore(copy_objects())


def night(conn, client, store, when=NIGHT, regs=(NS,)):
    return R.run(conn, client, now=when, registers=regs, snapshots=store)


def state(conn, key="aip_ns"):
    return conn.execute("SELECT * FROM designated_lists WHERE key = ?", (key,)).fetchone()


def current_names(conn, key="aip_ns"):
    return sorted(r[0] for r in conn.execute(
        "SELECT d.employer_name FROM designated_employers d JOIN designated_lists l ON l.key = d.list_key "
        "WHERE d.list_key = ? AND d.last_seen = l.last_ok_at", (key,)))


def last_notice(conn):
    return conn.execute("SELECT notice FROM sources_log WHERE source = 'registers' ORDER BY id DESC").fetchone()[0]


def pdf(body: bytes, etag: str | None = ETAG, modified: str | None = MODIFIED) -> FakeResponse:
    headers = {k: v for k, v in (("ETag", etag), ("Last-Modified", modified)) if v}
    return FakeResponse(200, body, headers)


# -- where the copy lives ----------------------------------------------------------------------------


def test_the_copy_is_never_in_the_repository_and_the_certificate_is_package_data():
    pyproject = tomllib.loads((PIPELINE / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["lmia_pipeline"]
    assert not any("registers" in p for p in patterns)
    assert not (R.config.PACKAGE_DATA / "registers").exists()
    gitignore = (PIPELINE.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "pipeline/lmia_pipeline/data/registers/" in gitignore
    pem = R.CERT_DIR / BY_KEY["rcip_brandon"].tls_intermediate
    rel = pem.relative_to(R.config.PACKAGE_DATA.parent).as_posix()
    assert pem.exists() and any(fnmatch.fnmatch(rel, p) and rel.count("/") == p.count("/") for p in patterns)


def test_only_nova_scotia_carries_a_copy_and_only_brandon_a_certificate():
    assert [r.key for r in REGISTERS if r.snapshot] == ["aip_ns"]
    assert [r.key for r in REGISTERS if r.tls_intermediate] == ["rcip_brandon"]
    assert R.snapshot_keys("aip_ns") == (CSV_KEY, META_KEY)


def test_the_objects_leave_out_persons_and_read_back_with_their_record():
    objects = copy_objects(COPY_ROWS + [Row("Jane Example", "Halifax")])
    meta = json.loads(objects[META_KEY])
    assert meta == {
        "key": "aip_ns", "source_url": COPY_URL, "etag": ETAG, "last_modified": MODIFIED, "size": 463826,
        "sha256": "0" * 64, "list_date": "2026-07-01", "loaded_on": "2026-10-30", "loaded_by": "hand",
        "parser": "lmia_pipeline.sources.registers.parse_body", "rows_read": 10, "rows_left_out_as_person": 1,
        "rows": 9,
    }
    assert objects[CSV_KEY].decode("utf-8").splitlines()[:2] == ["name,location,designated_on", "Harbour Fisheries 0 Limited,,"]
    snap = R.parse_snapshot("aip_ns", objects[CSV_KEY], objects[META_KEY])
    assert (snap.list_date, snap.loaded_on, snap.stamp, snap.size, snap.etag) == (
        "2026-07-01", "2026-10-30", "2026-10-30T00:00:00Z", 463826, ETAG)
    assert len(snap.rows) == 9 and "Jane Example" not in {r.name for r in snap.rows}


@pytest.mark.parametrize("objects, outcome, detail", [
    ({}, "missing", "no copy in R2 (registers/aip_ns.json is missing)"),
    ({META_KEY: copy_objects()[META_KEY]}, "missing", "registers/aip_ns.csv is missing"),
    ({**copy_objects(), META_KEY: b"{not json"}, "malformed", "the copy does not read"),
    ({**copy_objects(), META_KEY: json.dumps({"loaded_on": "October 30"}).encode()}, "malformed", "loaded_on is not a date"),
    ({**copy_objects(), CSV_KEY: b"name\n"}, "malformed", "no rows"),
])
def test_reading_the_copy_says_what_is_wrong(objects, outcome, detail):
    copy = R.read_snapshot(NS, FakeStore(objects))
    assert copy.snap is None and copy.outcome == outcome and detail in copy.detail


def test_without_r2_the_copy_is_unavailable_never_an_error():
    assert R.read_snapshot(NS, None).outcome == "unavailable"
    copy = R.read_snapshot(NS, FakeStore(fail=resilience.R2Error("the download answered HTTP 500")))
    assert copy.outcome == "unavailable" and "HTTP 500" in copy.detail


# -- R2 through the REST API ---------------------------------------------------------------------------

ACCOUNT = "abc123abc123abc123abc123abc123ab"
TOKEN = "tok-deploy-secret-value"
OBJECTS = f"/client/v4/accounts/{ACCOUNT}/r2/buckets/lmia-watch-data/objects"


class RestResp:
    def __init__(self, status, body=b"", json_data=None):
        self.status_code, self._body, self._json = status, body, json_data

    def json(self):
        if self._json is None:
            raise ValueError("not JSON")
        return self._json

    def iter_content(self, size):
        yield self._body

    def close(self):
        pass


class RestHttp:
    """The REST API's object calls: GET answers from `objects`, PUT stores; records every call."""

    def __init__(self, objects=None, bucket_missing=False):
        self.objects, self.bucket_missing, self.calls = dict(objects or {}), bucket_missing, []

    def _key(self, url):
        parts = urlsplit(url)
        assert parts.netloc == "api.cloudflare.com" and parts.path.startswith(OBJECTS + "/")
        return unquote(parts.path[len(OBJECTS) + 1:])

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append(("GET", url, dict(headers or {})))
        if self.bucket_missing:
            return RestResp(404, json_data={"success": False, "errors": [{"code": 10006, "message": "bucket"}]})
        key = self._key(url)
        if key not in self.objects:
            return RestResp(404, json_data={"success": False, "errors": [{"code": 10007, "message": "not found"}]})
        return RestResp(200, self.objects[key])

    def put(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("PUT", url, dict(headers or {})))
        self.objects[self._key(url)] = data
        return RestResp(200, json_data={"success": True})


def test_r2_reads_a_small_object_and_tells_a_missing_key_from_a_failure():
    http = RestHttp({CSV_KEY: b"name\nX Ltd\n"})
    r2 = resilience.R2Rest(http, ACCOUNT, TOKEN, "lmia-watch-data")
    assert r2.get_bytes(CSV_KEY) == b"name\nX Ltd\n"
    assert r2.get_bytes(META_KEY) is None
    assert http.calls[0][2]["Authorization"] == f"Bearer {TOKEN}"
    with pytest.raises(resilience.R2Error) as err:
        resilience.R2Rest(RestHttp(bucket_missing=True), ACCOUNT, TOKEN, "lmia-watch-data").get_bytes(CSV_KEY)
    assert TOKEN not in str(err.value)


def test_r2_uploads_an_object_with_its_type():
    http = RestHttp()
    resilience.R2Rest(http, ACCOUNT, TOKEN, "lmia-watch-data").upload(META_KEY, b"{}", "application/json")
    method, url, headers = http.calls[0]
    assert method == "PUT" and url.endswith("/objects/registers/aip_ns.json")
    assert headers["Content-Type"] == "application/json" and http.objects[META_KEY] == b"{}"


def test_r2_from_env_needs_the_token_and_the_account(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    assert resilience.r2_from_env() is None and R.r2_snapshots() is None
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.delenv("BUCKET", raising=False)
    r2 = resilience.r2_from_env()
    assert (r2.account, r2.bucket) == (ACCOUNT, "lmia-watch-data")


# -- the copy in use -----------------------------------------------------------------------------------


def test_when_the_live_read_fails_the_copy_becomes_the_current_rows(conn, fake_client, store):
    # The page answers and links the copy's file; the file itself does not answer.
    stats = night(conn, fake_client({NS.page_url: PAGE}), store)
    assert stats.states == {"aip_ns": "snapshot"}
    s = state(conn)
    assert (s["state"], s["rows"], s["list_date"], s["last_ok_at"], s["source_url"]) == (
        "snapshot", 9, "2026-07-01", "2026-10-30T00:00:00Z", COPY_URL)
    assert s["detail"].startswith("9 rows from the copy of the list dated 2026-07-01 loaded by hand on 2026-10-30; "
                                  "live read failing: not fetched")
    assert current_names(conn) == sorted(r.name for r in COPY_ROWS)
    assert stats.rows == 9
    assert last_notice(conn).startswith(
        "Designated-employer lists not read live from tonight, their copy loaded by hand in use: aip_ns (9 rows from "
        "the copy of the list dated 2026-07-01 loaded by hand on 2026-10-30; live read failing")
    # The next night changes nothing: no notice, the same rows, first seen the day the copy was loaded.
    stats = night(conn, fake_client({NS.page_url: PAGE}), store, "2026-11-03T00:10:00Z")
    assert stats.states == {"aip_ns": "snapshot"} and last_notice(conn) is None
    assert {r[0] for r in conn.execute("SELECT first_seen FROM designated_employers")} == {"2026-10-30T00:00:00Z"}
    assert "aip_ns copy loaded by hand 2026-10-30 (list dated 2026-07-01): no newer edition" in stats.summary()


def test_a_name_that_reads_as_a_person_in_a_copy_is_left_out_at_load(conn, fake_client, store):
    store.objects[CSV_KEY] += b"Jane Example,Halifax,\n"
    night(conn, fake_client({NS.page_url: PAGE}), store)
    assert "Jane Example" not in current_names(conn) and len(current_names(conn)) == 9
    assert "1 names read as a person left out" in state(conn)["detail"]


def test_a_missing_copy_leaves_the_list_as_a_failed_read_with_no_rows_and_no_item(conn, fake_client):
    store = FakeStore()
    stats = night(conn, fake_client({NS.page_url: PAGE, COPY_URL: NOT_A_PDF_TEXT}), store)
    assert stats.states == {"aip_ns": "unreadable"}
    assert (state(conn)["rows"], state(conn)["last_ok_at"], current_names(conn)) == (0, None, [])
    c = R.edition_checks(conn)["aip_ns"]
    assert (c["result"], c["copy"], c["attention"]) == ("no copy", "missing", None)
    assert R.attention_items(conn) == []
    assert "aip_ns: copy loaded by hand not used, no copy in R2" in stats.summary()
    # Without R2 access at all, the same.
    stats = night(conn, fake_client({NS.page_url: PAGE}), None, "2026-11-03T00:10:00Z")
    assert stats.states == {"aip_ns": "failing"} and R.attention_items(conn) == []


def test_a_copy_that_does_not_read_is_an_item_and_the_failed_state_stands(conn, fake_client, store):
    store.objects[META_KEY] = b"{not json"
    stats = night(conn, fake_client({NS.page_url: PAGE}), store)
    assert stats.states == {"aip_ns": "failing"}
    [item] = R.attention_items(conn)
    assert item.startswith("Nova Scotia designated-employer list: the copy loaded by hand in R2 "
                           "(registers/aip_ns.csv and registers/aip_ns.json) does not read (")
    assert item.endswith("; load it again")


def test_a_live_read_takes_precedence_over_the_copy_and_r2_is_not_read(conn, fixtures, fake_client, store):
    live = (fixtures / "register_aip_nb.pdf").read_bytes()
    stats = night(conn, fake_client({NS.page_url: PAGE, COPY_URL: pdf(live)}), store)
    assert stats.states == {"aip_ns": "ok"} and store.reads == []
    names = current_names(conn)
    assert len(names) == 29 and not set(names) & {r.name for r in COPY_ROWS}
    assert stats.editions["aip_ns"]["result"] == "read live" and R.attention_items(conn) == []
    assert "aip_ns: read live, the copy loaded by hand not in use" in stats.summary()
    assert {r["key"]: r for r in R.export_rows(conn)}["aip_ns"]["snapshot"] is None
    # The live read fails the next night: the live rows, newer than the copy, stay.
    stats = night(conn, fake_client({NS.page_url: PAGE}), store, "2026-11-03T00:10:00Z")
    assert stats.states == {"aip_ns": "failing"}
    assert current_names(conn) == names and state(conn)["last_ok_at"] == NIGHT


def test_a_copy_loaded_after_the_last_live_read_replaces_it(conn, fixtures, fake_client, store):
    live = (fixtures / "register_aip_nb.pdf").read_bytes()
    night(conn, fake_client({NS.page_url: PAGE, COPY_URL: pdf(live)}), store, "2026-10-20T00:10:00Z")
    assert len(current_names(conn)) == 29
    stats = night(conn, fake_client({NS.page_url: PAGE}), store)
    assert stats.states == {"aip_ns": "snapshot"} and current_names(conn) == sorted(r.name for r in COPY_ROWS)
    # Back from the copy to a live read: "read again".
    night(conn, fake_client({NS.page_url: PAGE, COPY_URL: pdf(live)}), store, "2026-11-03T00:10:00Z")
    assert last_notice(conn) == "Designated-employer lists read again: aip_ns"


def test_leaving_the_unreadable_set_for_the_copy_is_not_called_readable_again(conn, fake_client, store):
    nb = BY_KEY["aip_nb"]
    mapping = {NS.page_url: PAGE, COPY_URL: NOT_A_PDF_TEXT, nb.source_url: NOT_A_PDF_TEXT}
    # Before the copy was in R2 the file read as an unreadable PDF.
    night(conn, fake_client(mapping), FakeStore(), "2026-10-29T00:10:00Z", regs=(NS, nb))
    assert "not yet readable (pypdf could not read the PDF): aip_nb,aip_ns" in last_notice(conn)
    night(conn, fake_client(mapping), store, regs=(NS, nb))
    notice = last_notice(conn)
    assert "readable again" not in notice
    assert "not yet readable (pypdf could not read the PDF): aip_nb" in notice
    assert "their copy loaded by hand in use: aip_ns" in notice


# -- the newer-edition check ------------------------------------------------------------------------------


def check(conn):
    return R.edition_checks(conn)["aip_ns"]


def test_an_unchanged_link_and_an_unreachable_file_raise_no_item(conn, fake_client, store):
    night(conn, fake_client({NS.page_url: PAGE}), store)
    c = check(conn)
    assert (c["result"], c["url"], c["attention"]) == ("unchanged", COPY_URL, None)
    assert c["detail"] == "the page links the copy's file; the file itself did not answer"
    assert R.attention_items(conn) == []


def test_a_file_that_answers_as_the_copy_is_unchanged(conn, fake_client):
    store = FakeStore(copy_objects(size=len(NOT_A_PDF_TEXT)))
    night(conn, fake_client({NS.page_url: PAGE, COPY_URL: pdf(NOT_A_PDF_TEXT)}), store)
    c = check(conn)
    assert (c["result"], c["attention"]) == ("unchanged", None)
    assert c["detail"] == "the file answers with the copy's ETag, Last-Modified and size"
    assert state(conn)["state"] == "snapshot"


def test_a_changed_link_is_an_item_needing_attention(conn, fake_client, store):
    stats = night(conn, fake_client({NS.page_url: NEWER_PAGE}), store)
    c = check(conn)
    assert c["result"] == "newer" and c["url"] == NEWER_URL
    expected = (f"Nova Scotia designated-employer list: a newer edition is published at {NEWER_URL} "
                f"(modification date not known); load it by hand")
    assert c["attention"] == expected and R.attention_items(conn) == [expected]
    # The copy's rows still stand in meanwhile.
    assert stats.states == {"aip_ns": "snapshot"} and len(current_names(conn)) == 9
    assert f"a newer edition is published at {NEWER_URL}" in stats.summary()


def test_a_changed_etag_is_an_item_naming_the_modification_date(conn, fake_client, store):
    newer = pdf(NOT_A_PDF_TEXT, etag='"80000-1234"', modified="Mon, 02 Nov 2026 14:00:00 GMT")
    night(conn, fake_client({NS.page_url: PAGE, COPY_URL: newer}), store)
    c = check(conn)
    assert c["result"] == "newer" and c["modified"] == "2026-11-02"
    assert c["detail"].startswith('ETag "80000-1234" (copy "713d2-6562d15681934")')
    assert c["attention"] == (f"Nova Scotia designated-employer list: a newer edition is published at {COPY_URL} "
                              f"(modified 2026-11-02); load it by hand")


def test_a_page_that_does_not_answer_leaves_the_edition_unknown(conn, fake_client, store):
    night(conn, fake_client({}), store)
    c = check(conn)
    assert (c["result"], c["attention"]) == ("unknown", None)
    assert R.attention_items(conn) == []


def test_a_challenge_page_in_place_of_the_file_is_not_an_edition(conn, fake_client, store):
    # The host answers the runner with a block page: no headers of the file to compare.
    page = FakeResponse(200, b"<html><title>Access Denied</title></html>", {"ETag": '"other"'})
    stats = night(conn, fake_client({NS.page_url: PAGE, COPY_URL: page}), store)
    assert stats.states == {"aip_ns": "snapshot"} and check(conn)["result"] == "unchanged"


def test_the_item_reaches_the_attention_step_and_leaves_the_run_ok(conn, fake_client, store, tmp_path):
    night(conn, fake_client({NS.page_url: NEWER_PAGE}), store)
    db = tmp_path / "status.sqlite"
    disk = sqlite3.connect(str(db))
    conn.backup(disk)
    disk.close()
    status = nightly.run_status(db, "2026-01-01T00:00:00Z", {"problems": []}, None, {"deploy": "success"})
    item = R.attention_items(conn)[0]
    assert status["ok"] is True
    assert status["registers"]["attention"] == [item]
    assert status["registers"]["editions"]["aip_ns"]["result"] == "newer"
    assert status["registers"]["not_read"] == {"snapshot": ["aip_ns"]}
    assert item in resilience.attention_items(status)
    # Not a notice, and no retry of the night (the gate reads ok).
    assert item not in " ".join(resilience.notice_items(status))
    assert resilience.gate(status, date.fromisoformat(status["run_at"][:10]))[0] is True


def test_attention_items_ignore_a_malformed_registers_block():
    assert resilience.attention_items({"registers": {"attention": "not a list"}}) == []
    assert resilience.attention_items({"registers": {"attention": ["x", 3, ""]}}) == ["x"]


# -- export ------------------------------------------------------------------------------------------------


def test_export_and_profile_rows_say_the_copy_was_loaded_by_hand(conn, fake_client, store):
    eid = upsert_employer(conn, "Lunenburg Marine Works Inc.", "NS", source="esdc_positive", city="Lunenburg",
                          now=NIGHT)
    night(conn, fake_client({NS.page_url: PAGE}), store)
    rows = {r["key"]: r for r in R.export_rows(conn)}
    ns = rows["aip_ns"]
    assert (ns["state"], ns["rows"], ns["list_date"], ns["last_ok"]) == ("snapshot", 9, "2026-07-01", "2026-10-30")
    assert ns["snapshot"] == {"list_date": "2026-07-01", "loaded_on": "2026-10-30"}
    assert rows["aip_nb"]["snapshot"] is None
    profile = R.profile_rows(conn, [eid])[eid][0]
    assert profile["snapshot"] == {"list_date": "2026-07-01", "loaded_on": "2026-10-30"}
    assert (profile["current"], profile["first_seen"], profile["grade"]) == (True, "2026-10-30", "exact")


# -- loading a new edition by hand ---------------------------------------------------------------------------


@pytest.fixture
def loader():
    sys.path.insert(0, str(PIPELINE / "scripts"))
    try:
        import load_register_snapshot
        yield load_register_snapshot
    finally:
        sys.path.remove(str(PIPELINE / "scripts"))


def test_the_loader_parses_locally_and_uploads_both_objects(loader, fixtures, capsys):
    store = FakeStore()
    code = loader.main(["aip_ns", "--from", str(fixtures / "register_aip_nb.pdf"), "--url", COPY_URL,
                        "--etag", ETAG, "--last-modified", MODIFIED, "--loaded-on", "2026-10-30",
                        "--list-date", "2026-07-01"], store=store)
    assert code == 0
    assert store.uploads == [(CSV_KEY, "text/csv; charset=utf-8"), (META_KEY, "application/json")]
    meta = json.loads(store.objects[META_KEY])
    assert (meta["source_url"], meta["etag"], meta["last_modified"], meta["loaded_by"]) == (COPY_URL, ETAG, MODIFIED, "hand")
    assert meta["rows"] == 29 and meta["size"] == (fixtures / "register_aip_nb.pdf").stat().st_size
    assert R.read_snapshot(NS, store).outcome == "ok"
    assert "uploaded to R2 as registers/aip_ns.csv and registers/aip_ns.json" in capsys.readouterr().out


def test_the_loader_never_writes_into_the_repository(loader, fixtures, tmp_path):
    args = ["aip_ns", "--from", str(fixtures / "register_aip_nb.pdf"), "--list-date", "2026-07-01"]
    assert loader.main(args + ["--out", str(PIPELINE / "lmia_pipeline" / "data" / "registers")]) == 1
    assert not (PIPELINE / "lmia_pipeline" / "data" / "registers").exists()
    assert loader.main(args + ["--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["aip_ns.csv", "aip_ns.json"]
    # A list without a copy, or no date, is refused.
    assert loader.main(["aip_nb", "--from", str(fixtures / "register_aip_nb.pdf"), "--out", str(tmp_path)]) == 1
    assert loader.main(["aip_ns", "--from", str(fixtures / "register_aip_nb.pdf"), "--out", str(tmp_path / "x")]) == 1


# -- a site that blocks automated readers ---------------------------------------------------------


CHALLENGE = b"<html><head><script src='/radware/bot-manager.js'></script></head><body>Please wait</body></html>"


def test_a_challenge_page_is_blocked_with_no_rows_and_no_retry_beyond_the_night(conn, fixtures, fake_client):
    client = fake_client({PE.source_url: CHALLENGE})
    stats = R.run(conn, client, now=NIGHT, registers=(PE,))
    assert stats.states == {"aip_pe": "blocked"}
    s = state(conn, "aip_pe")
    assert (s["state"], s["rows"], s["last_ok_at"]) == ("blocked", 0, None)
    assert s["detail"] == "the site answered with a bot challenge page, not the list"
    # One request a night, none to get past the challenge.
    assert [u for u, _ in client.fake_session.calls] == [PE.source_url]
    assert "blocked: aip_pe" in stats.summary()
    exported = {r["key"]: r for r in R.export_rows(conn)}["aip_pe"]
    assert (exported["state"], exported["rows"], exported["last_ok"]) == ("blocked", 0, None)


def test_blocked_is_a_notice_only_when_the_state_changes(conn, fixtures, fake_client):
    good = (fixtures / "register_aip_pe.html").read_bytes()   # six rows, as archived before the challenge
    notices = []
    for n, body in enumerate([CHALLENGE, CHALLENGE, good, CHALLENGE, b"<html><p>moved</p></html>", CHALLENGE], 1):
        R.run(conn, fake_client({PE.source_url: body}), now=f"2026-11-{n:02d}T00:10:00Z", registers=(PE,))
        notices.append(last_notice(conn))
    assert notices[0].startswith("Designated-employer lists not read from tonight") and "aip_pe (the site answered" in notices[0]
    assert notices[1] is None
    assert notices[2] == "Designated-employer lists read again: aip_pe"
    assert notices[3].startswith("Designated-employer lists not read from tonight")
    # From blocked to a changed layout and back: both are "not read", so no notice.
    assert notices[4] is None and notices[5] is None
    # The rows of the good read stay current while the site blocks.
    assert state(conn, "aip_pe")["state"] == "blocked" and state(conn, "aip_pe")["rows"] > 0


def test_a_challenge_in_place_of_a_pdf_is_blocked():
    nb = BY_KEY["aip_nb"]
    assert R.is_challenge(CHALLENGE) and not R.is_challenge(b"%PDF-1.7 radware")
    with pytest.raises(R.Unreadable):
        R.parse_body(nb, CHALLENGE)


def test_a_pdf_list_answered_by_a_challenge_is_blocked(conn, fake_client):
    nb = BY_KEY["aip_nb"]
    stats = R.run(conn, fake_client({nb.source_url: CHALLENGE}), now=NIGHT, registers=(nb,))
    assert stats.states == {"aip_nb": "blocked"}


# -- the intermediate certificate Brandon leaves out -----------------------------------------------


BRANDON = BY_KEY["rcip_brandon"]
BRANDON_URL = "https://economicdevelopmentbrandon.com/rcip/rcip-list-of-designated-employers"


def test_the_stage_client_trusts_the_intermediate_for_brandon_only():
    client = R.make_client()
    adapter = client.session.get_adapter(BRANDON_URL)
    assert isinstance(adapter, ContextAdapter)
    ctx = adapter.context
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "GlobalSign GCC R6 AlphaSSL CA 2025" in subjects
    # The roots requests trusts are all still there: one certificate added, nothing taken away.
    assert len(subjects) > 100
    # Every other list's host keeps the default adapter, and so does a look-alike host.
    for reg in REGISTERS:
        for url in (reg.page_url, reg.source_url):
            if reg.key != "rcip_brandon":
                assert not isinstance(client.session.get_adapter(url), ContextAdapter), url
    assert not isinstance(client.session.get_adapter("https://economicdevelopmentbrandon.com.example.org/"), ContextAdapter)
    assert not isinstance(client.session.get_adapter("https://www.economicdevelopmentbrandon.com/"), ContextAdapter)
    assert not isinstance(client.session.get_adapter("http://economicdevelopmentbrandon.com/"), ContextAdapter)
    assert client.max_attempts == R.CLIENT_ATTEMPTS


def test_the_default_session_is_untouched():
    R.make_client()
    other = PoliteClient()
    assert sorted(other.session.adapters) == ["http://", "https://"]
    assert not any(isinstance(a, ContextAdapter) for a in other.session.adapters.values())


def test_a_certificate_that_does_not_load_leaves_the_client_as_it_was(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "CERT_DIR", tmp_path)
    client = R.make_client()
    assert not isinstance(client.session.get_adapter(BRANDON_URL), ContextAdapter)
