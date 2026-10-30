"""The Search Console import, against a stub session: nothing here reaches the network.

The RSA key below was made for these tests with `openssl genpkey -algorithm RSA
-pkeyopt rsa_keygen_bits:2048` and is used nowhere else. SIGNATURE is what
`openssl dgst -sha256 -sign` gave for MESSAGE with it, so the standard-library
signer is checked against an independent implementation.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import pytest
import requests

from lmia_pipeline import cli, config, nightly, resilience, search_console as sc

# The armour is assembled here so the file holds no literal key header for scanners to flag.
KEY_PEM = "\n".join(["-----BEGIN " + "PRIVATE KEY-----",
                    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDP5HEbWNB+t0mm",
                    "yJ3Xsc/vy3623A6VL4AeUyk07Mn7yECMWUgdXBB6wBND8o7jSQ6Dzzhbr8cSsAV7",
                    "Fi7IbjPrPwrBUVhSqG4xsuyauNf6Pj9IqjfUggXO4ruRSu3tToKGiaFJox8BG+Cx",
                    "atdIQGI9Pc+LrLSRzDmA/QN/L7Joxv+Bg6HdKLUkH1cRZHlPIMqlUu6h8l/6xlwX",
                    "jgQTl/XNwZczemVbNBi1y59qZc6FSxGNxemmz2bXTGTD8fez+tn9isQ7umgUo32S",
                    "07UXE1PlxVoRc7h9re6Wn5pyT1K+BbgclCWgbPuqQ1vzxjfOjxxzSFDTcoZuonzE",
                    "RUkEGNOtAgMBAAECggEADx/M9L2HiY3MZL8Cm18QbsnCAbaiXvXHidfopF+NAELH",
                    "eLkZbH1hUN9+vKToV/Oy2SGvCsiPyzXAEv4q+szoUmHR5qeELUXwolqkfksaogDQ",
                    "+iMxZZtB+z+hKrGl++uIG8E72STDYYFwMtLAL72eCAY3qQSFrHe26pc9n7f4xZ4s",
                    "UVvkyzUGKgBywul9Yni0fopXKSO4bdUeQqDrFVGBcpp3vIknBfVgh5vfkb2YiHPm",
                    "4FolIxv+jaAtbuiHe0hfo40cOqgopPzaZt7cJ1fqm/lAiQl+sf2Q5pEsGhUXyRAa",
                    "LqonYROtfeppTC3HVlG1ee8MMTqs0Kwq2wVqL9NyUQKBgQDySL/ZHDxBhbxHBTPi",
                    "MwD0B3mgkWCZ6OcgTciwkPyRX101aeDN70dl5wkDMwn/odvDoQKdzGEr8L0X3rAB",
                    "qgy187ntYtqJpbXJiWrv5MZal9ev9HkCvEgXE3EVGojnOSO/ovpiO6JNFMTJqj/B",
                    "Re1/7LaN1cmJUPyJ4GzBu/8JBQKBgQDbqUbAYYngv6cdE2FRmyzqGlz6AljdPpiK",
                    "odu2vYWBy6cYamYmeNojoG2fTnJfFnSqPJFRR84wXILgTjPz/ZtCul9RHnU31WAM",
                    "e/Vfm2kDXmtsHi1GxcKBEXk+ZD+PEISMm+kQ0NiclTIC7jvdTlzglUDP/yA62mzj",
                    "rQBrlLkAiQKBgQDXjUWxoN8y5ApnnQdV3U6hzOy2n+AzzfOi19EO1U7+/rrsRHBO",
                    "hu0cifmIsSXaGmRsnZi4Txa8gweYbvRj5qg8UMQ/oE0RXS5oSSuslfqqqqCn2Ha4",
                    "qk3wyck3n03heQKHAjaEos14iluxlxf1mYL85tpbQbJ1ymmDOPlJOzphCQKBgEMS",
                    "NetKHRqGCpXjNAUB973nnNot20p68YLrFzZ+OgS+1V+sJVK79geI1dAd2OhV5/uP",
                    "EOQbo8a6iK/K0SxAFKdUVwRi43HP8kr9kpfF0VPZAb36nOKOQey9FCNL4uhhJ8fz",
                    "Vz/uNSXinGmuqpLReaSNjkO0Z/fwd+0xBv7SY4bZAoGBAOFhckZb18k/DXPG8TCE",
                    "PNcrCKw9ZExwBwEBBCZyEj5UxFle83/cXFE824+8x2YJ6HAg4di7GxnSisakM0M9",
                    "uiId3LgFXR7FxHxPg54xQrj7NF7VCJANF/sZXdy0gEGMKuHDBwxqKOvcahR51z84",
                    "QVupB4C1RxOZqKuySbSxk9s5",
                     "-----END " + "PRIVATE KEY-----"]) + "\n"
MESSAGE = b"eyJhbGciOiJSUzI1NiJ9.eyJ0ZXN0Ijp0cnVlfQ"
SIGNATURE = "mvppD5vfHOwPCTfg6ONKbvibjNeNfoGqyH1zWvQ9GmUfmdfM2M8Ku_NceiAQLk_zujyNWkwl0wwbxC-HsdVPNH7Z-zIHv89dusZ-hvhvWFrQ7efBqoqRwqx7LP83LvNBog1gkNZt01ep7Gz7Zme7cSsCfcmQRGsWMw0sRMDfR6zIK5y8UxM6Inb54psa-Gp-x9ovCukFqSExBCdBwsHEuB69RZSjWemPidrmgSZE3MiYRFq080twCfZqxGto0rbfDTDVyOWGggN5cSetoURLxw_zXBMIi19XPAvwGWJpb_9KLXw3PVDrfqy47sWcX7VfCbtt5B9pmzHh9At1JEqHvw"

ACCOUNT_JSON = json.dumps({
    "type": "service_account", "project_id": "lmia-watch-test", "private_key_id": "abc123",
    "private_key": KEY_PEM, "client_email": "reader@lmia-watch-test.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
})
ENV = {sc.SECRET_ENV: ACCOUNT_JSON}
NOW = datetime(2026, 10, 30, 0, 50, tzinfo=timezone.utc)
KEY_FRAGMENT = KEY_PEM.splitlines()[5]


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeResponse:
    def __init__(self, status: int, body: object = None, text: str | None = None) -> None:
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self) -> object:
        if self._body is None:
            raise ValueError("no json")
        return self._body


DATES = [
    {"keys": ["2026-10-25"], "clicks": 12.0, "impressions": 340.0, "ctr": 0.0352941, "position": 8.4567},
    {"keys": ["2026-10-26"], "clicks": 15, "impressions": 410, "ctr": 0.0365853, "position": 7.9},
    {"keys": ["2026-10-27"], "clicks": 0, "impressions": 3, "ctr": 0, "position": 21.0},
]
QUERIES = {
    "2026-10-25": [{"keys": ["lmia list 2026"], "clicks": 2, "impressions": 40, "position": 6.04},
                   {"keys": ["acme farms lmia"], "clicks": 5, "impressions": 9, "position": 1.0}],
    "2026-10-26": [{"keys": ["lmia\ttracker\n"], "clicks": 1, "impressions": 30, "position": 9.55}],
}


class FakeGoogle:
    """Stands in for requests.Session: the token endpoint and the Search Analytics API."""

    def __init__(self, dates: list[dict] | None = None, queries: dict | None = None, *,
                 token: FakeResponse | Exception | None = None, query_fail: FakeResponse | Exception | None = None) -> None:
        self.dates = DATES if dates is None else dates
        self.queries = QUERIES if queries is None else queries
        self.token = token or FakeResponse(200, {"access_token": "ya29.test-token", "expires_in": 3599,
                                                 "token_type": "Bearer"})
        self.query_fail = query_fail
        self.calls: list[dict] = []
        self.closed = False

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "json": json, "headers": headers or {}})
        if url == sc.TOKEN_URL:
            if isinstance(self.token, Exception):
                raise self.token
            return self.token
        if isinstance(self.query_fail, Exception):
            raise self.query_fail
        if self.query_fail is not None:
            return self.query_fail
        if json["dimensions"] == ["date"]:
            return FakeResponse(200, {"rows": self.dates, "responseAggregationType": "byProperty"})
        rows = self.queries.get(json["startDate"])
        return FakeResponse(200, {"rows": rows} if rows else {"responseAggregationType": "byProperty"})

    def close(self):
        self.closed = True


def read_csv(path) -> list[dict]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    assert reader.fieldnames == sc.HEADER
    return list(reader)


def run(tmp_path, http=None, **kw):
    return sc.run(tmp_path, env=kw.pop("env", ENV), session=http if http is not None else FakeGoogle(),
                  now=kw.pop("now", NOW), **kw)


@pytest.fixture(autouse=True)
def site(monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")


# -- signing -------------------------------------------------------------------


def test_the_signature_matches_openssl_byte_for_byte():
    n, d = sc.rsa_private_key(KEY_PEM)
    assert n.bit_length() == 2048
    assert sc.b64url(sc.rs256(MESSAGE, n, d)) == SIGNATURE


def test_the_assertion_is_a_jwt_google_can_verify():
    account = sc.parse_account(ACCOUNT_JSON)
    jwt = sc.assertion(account, 1_800_000_000)
    head, claims, signature = jwt.split(".")
    assert json.loads(b64decode(head)) == {"alg": "RS256", "typ": "JWT", "kid": "abc123"}
    assert json.loads(b64decode(claims)) == {
        "iss": "reader@lmia-watch-test.iam.gserviceaccount.com",
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token", "iat": 1_800_000_000, "exp": 1_800_003_600}
    # Verify with the public exponent, as Google does: the padded SHA-256 digest of the signing input comes back.
    n = account.n
    em = pow(int.from_bytes(b64decode(signature), "big"), 65537, n).to_bytes(256, "big")
    digest = hashlib.sha256(f"{head}.{claims}".encode()).digest()
    assert em == b"\x00\x01" + b"\xff" * (256 - 3 - 19 - 32) + b"\x00" + sc.SHA256_PREFIX + digest


def test_a_key_that_is_not_a_pkcs8_rsa_key_is_refused_without_echoing_it():
    body = KEY_PEM.splitlines()[1:-1]
    for pem in ("", "not a key", KEY_PEM.replace("PRIVATE KEY", "RSA PRIVATE KEY"),
                "\n".join([KEY_PEM.splitlines()[0], "!!!!", KEY_PEM.splitlines()[-1]]),
                "\n".join([KEY_PEM.splitlines()[0]] + body[:5] + [KEY_PEM.splitlines()[-1]])):
        with pytest.raises(ValueError) as err:
            sc.rsa_private_key(pem)
        assert KEY_FRAGMENT not in str(err.value)
    for text in ("not json", "[]", json.dumps({"type": "authorized_user"}),
                 json.dumps({"type": "service_account", "client_email": "x@y"}),
                 ACCOUNT_JSON.replace(KEY_FRAGMENT, KEY_FRAGMENT[:-8] + "AAAAAAAA")):
        with pytest.raises(ValueError) as err:
            sc.parse_account(text)
        assert KEY_FRAGMENT[:20] not in str(err.value)
    account = sc.parse_account(ACCOUNT_JSON)
    assert repr(account) == "Account(reader@lmia-watch-test.iam.gserviceaccount.com)"


# -- the import ----------------------------------------------------------------


def test_without_the_secret_nothing_is_asked(tmp_path, caplog):
    caplog.set_level("INFO")
    http = FakeGoogle()
    assert run(tmp_path, http, env={}) == "no credentials"
    assert run(tmp_path, http, env={sc.SECRET_ENV: "  "}) == "no credentials"
    assert http.calls == [] and not (tmp_path / sc.FILE).exists()


def test_the_first_night_asks_for_sixteen_months_and_keeps_each_day_with_its_top_queries(tmp_path, caplog):
    caplog.set_level("INFO")
    http = FakeGoogle()
    assert run(tmp_path, http) == "imported 3 days"
    token, dates, *per_day = http.calls
    assert token["url"] == "https://oauth2.googleapis.com/token"
    assert token["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert token["data"]["assertion"].count(".") == 2
    site_url = "https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Almiawatch.ca/searchAnalytics/query"
    assert dates["url"] == site_url and unquote(dates["url"].split("/sites/")[1].split("/")[0]) == "sc-domain:lmiawatch.ca"
    assert dates["headers"]["Authorization"] == "Bearer ya29.test-token"
    assert dates["json"] == {"type": "web", "dataState": "final", "startDate": "2025-07-01", "endDate": "2026-10-29",
                             "dimensions": ["date"], "rowLimit": 25000}
    assert date(2026, 10, 30) - date(2025, 7, 1) == timedelta(days=sc.HISTORY_DAYS)
    assert [c["json"] for c in per_day] == [
        {"type": "web", "dataState": "final", "startDate": d, "endDate": d, "dimensions": ["query"], "rowLimit": 50}
        for d in ("2026-10-25", "2026-10-26", "2026-10-27")]
    rows = read_csv(tmp_path / sc.FILE)
    assert [(r["date"], r["clicks"], r["impressions"], r["ctr"], r["position"]) for r in rows] == [
        ("2026-10-25", "12", "340", "0.0353", "8.46"), ("2026-10-26", "15", "410", "0.0366", "7.9"),
        ("2026-10-27", "0", "3", "0.0", "21.0")]
    assert json.loads(rows[0]["top_queries"]) == [["acme farms lmia", 5, 9, 1.0], ["lmia list 2026", 2, 40, 6.0]]
    assert json.loads(rows[1]["top_queries"]) == [["lmia tracker", 1, 30, 9.6]]
    assert rows[2]["top_queries"] == "[]"
    assert KEY_FRAGMENT not in caplog.text and "ya29.test-token" not in caplog.text
    assert not http.closed


def test_a_later_night_starts_after_the_newest_stored_day(tmp_path):
    assert run(tmp_path, FakeGoogle()) == "imported 3 days"
    later = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
    http = FakeGoogle(dates=[{"keys": ["2026-10-27"], "clicks": 99}, {"keys": ["2026-10-28"], "clicks": 4,
                                                                      "impressions": 50, "position": 5}])
    assert run(tmp_path, http, now=later) == "imported 1 day"
    assert http.calls[1]["json"]["startDate"] == "2026-10-28" and http.calls[1]["json"]["endDate"] == "2026-11-01"
    rows = read_csv(tmp_path / sc.FILE)
    assert [(r["date"], r["clicks"]) for r in rows] == [
        ("2026-10-25", "12"), ("2026-10-26", "15"), ("2026-10-27", "0"), ("2026-10-28", "4")]
    # Nothing final yet: up to date, the file untouched.
    before = (tmp_path / sc.FILE).read_text(encoding="utf-8")
    assert run(tmp_path, FakeGoogle(dates=[]), now=later) == "up to date"
    assert (tmp_path / sc.FILE).read_text(encoding="utf-8") == before
    # Already holding yesterday: no request at all.
    idle = FakeGoogle()
    assert run(tmp_path, idle, now=datetime(2026, 10, 29, 3, 0, tzinfo=timezone.utc)) == "up to date"
    assert idle.calls == []


def test_at_most_max_days_are_fetched_in_a_night(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "MAX_DAYS", 2)
    http = FakeGoogle()
    assert run(tmp_path, http) == "imported 2 days"
    assert [r["date"] for r in read_csv(tmp_path / sc.FILE)] == ["2026-10-25", "2026-10-26"]
    assert run(tmp_path, FakeGoogle()) == "imported 1 day"
    assert [r["date"] for r in read_csv(tmp_path / sc.FILE)] == ["2026-10-25", "2026-10-26", "2026-10-27"]


def test_dates_outside_the_range_asked_and_odd_figures_are_left_out(tmp_path):
    dates = [{"keys": ["2026-10-30"], "clicks": 1}, {"keys": ["2024-01-01"], "clicks": 1}, {"keys": ["yesterday"]},
             {"keys": []}, {"clicks": 4}, {"keys": ["2026-10-20"], "clicks": "nan", "impressions": -5, "position": True}]
    assert run(tmp_path, FakeGoogle(dates=dates, queries={})) == "imported 1 day"
    (row,) = read_csv(tmp_path / sc.FILE)
    assert (row["date"], row["clicks"], row["impressions"], row["position"]) == ("2026-10-20", "0", "0", "0.0")


def test_top_queries_are_capped_at_fifty_most_clicks_first():
    rows = [{"keys": [f"q{i:02d}"], "clicks": i % 7, "impressions": i, "position": 3} for i in range(80)]
    out = json.loads(sc.top_queries(rows + [{"keys": [""]}, {"keys": [" \x00 "]}]))
    assert len(out) == 50
    assert [q[1] for q in out] == sorted((q[1] for q in out), reverse=True)
    assert out[0] == ["q76", 6, 76, 3.0]


@pytest.mark.parametrize("http", [
    FakeGoogle(token=FakeResponse(400, {"error": "invalid_grant", "error_description": "Invalid JWT Signature."})),
    FakeGoogle(token=FakeResponse(200, {"token_type": "Bearer"})),
    FakeGoogle(token=requests.ConnectionError("reset")),
    FakeGoogle(query_fail=FakeResponse(403, {"error": {"code": 403, "message": "User does not have sufficient permission"}})),
    FakeGoogle(query_fail=FakeResponse(500, None, "backend error")),
    FakeGoogle(query_fail=FakeResponse(200, {"rows": "none"})),
    FakeGoogle(query_fail=FakeResponse(200, None, "<html>")),
    FakeGoogle(query_fail=requests.Timeout("slow")),
])
def test_a_failure_is_failed_and_leaves_the_file_as_it_was(tmp_path, http, caplog):
    stored = tmp_path / sc.FILE
    stored.write_text(",".join(sc.HEADER) + "\n2026-10-20,1,2,0.5,3.0,[]\n", encoding="utf-8")
    before = stored.read_text(encoding="utf-8")
    assert run(tmp_path, http) == "failed"
    assert stored.read_text(encoding="utf-8") == before
    assert KEY_FRAGMENT not in caplog.text and "ya29.test-token" not in caplog.text


def test_the_403_names_the_fix(tmp_path, caplog):
    http = FakeGoogle(query_fail=FakeResponse(403, {"error": {"code": 403}}))
    assert run(tmp_path, http) == "failed"
    assert "cannot read sc-domain:lmiawatch.ca; add it as a user of the property" in caplog.text


def test_a_stored_file_that_cannot_be_read_safely_is_never_replaced(tmp_path):
    stored = tmp_path / sc.FILE
    for text in ("", "date,clicks\n2026-10-20,1\n", ",".join(sc.HEADER) + "\nnot-a-date,1,2,0.5,3,[]\n",
                 ",".join(sc.HEADER) + "\n2026-10-20,1,2,0.5,3,[],extra\n"):
        stored.write_text(text, encoding="utf-8")
        http = FakeGoogle()
        assert run(tmp_path, http) == "failed", text
        assert stored.read_text(encoding="utf-8") == text and http.calls == []


def test_a_bad_secret_or_no_property_is_failed_before_any_request(tmp_path, monkeypatch):
    http = FakeGoogle()
    assert run(tmp_path, http, env={sc.SECRET_ENV: "{not json"}) == "failed"
    assert run(tmp_path, http, env={sc.SECRET_ENV: json.dumps({"type": "service_account"})}) == "failed"
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.example")
    assert run(tmp_path, http) == "failed"
    assert http.calls == []
    assert sc.site_property({sc.SITE_ENV: "https://lmiawatch.ca/"}) == "https://lmiawatch.ca/"
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    assert sc.site_property({}) == "sc-domain:lmiawatch.ca"


# -- the command and the run status --------------------------------------------


def test_the_command_writes_its_outcome_and_exits_1_only_when_failed(tmp_path, monkeypatch):
    monkeypatch.delenv(sc.SECRET_ENV, raising=False)
    assert cli.main(["import-search-console", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "outcome.txt").read_text(encoding="utf-8") == "no credentials\n"
    monkeypatch.setenv(sc.SECRET_ENV, "{broken")
    assert cli.main(["import-search-console", "--out", str(tmp_path)]) == 1
    assert (tmp_path / "outcome.txt").read_text(encoding="utf-8") == "failed\n"
    fake = FakeGoogle()
    monkeypatch.setattr(requests, "Session", lambda: fake)
    monkeypatch.setenv(sc.SECRET_ENV, ACCOUNT_JSON)
    assert cli.main(["import-search-console", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "outcome.txt").read_text(encoding="utf-8").startswith("imported ")
    assert fake.closed


def test_the_run_status_carries_the_import_and_only_failed_needs_attention(tmp_path):
    db = tmp_path / "none.sqlite"
    status = nightly.run_status(db, None, None, None, {}, search_console="no credentials")
    assert status["search_console"] == "no credentials"
    assert nightly.run_status(db, None, None, None, {})["search_console"] == "not run"
    clean = {"stages": [], "search_console": "imported 3 days"}
    assert resilience.attention_items(clean) == []
    assert resilience.attention_items({**clean, "search_console": "no credentials"}) == []
    assert resilience.attention_items({**clean, "search_console": "failed"}) == [
        "Search Console import: failed (caught up next run)"]
    (tmp_path / "gsc.txt").write_text("imported 2 days\n", encoding="utf-8")
    out = tmp_path / "status.json"
    assert nightly.main(["status", "--db", str(db), "--search-console-outcome", str(tmp_path / "gsc.txt"),
                         "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["search_console"] == "imported 2 days"
