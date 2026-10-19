"""The daily Bluesky post, against a stub session: nothing here reaches the network."""

import pytest
import requests

from lmia_pipeline import bluesky, cli, config, social
from lmia_pipeline.db import connect, get_meta, set_meta
from lmia_pipeline.social import Digest, EmployerLine
from test_social import CREDS as X_CREDS, EARLIER, LATEST, FakeJSON, add_posting, seed

CREDS = {"BSKY_HANDLE": "lmiawatch.ca", "BSKY_APP_PASSWORD": "abcd-efgh-ijkl-mnop"}
LINK = "https://lmiawatch.ca/search?date=7d"
DID = "did:plc:abc123example"
BLOB = {"$type": "blob", "ref": {"$link": "bafkreiexample"}, "mimeType": "image/png", "size": 70000}


class FakeBsky:
    """Stands in for requests.Session: records each request, answers per endpoint or raises."""

    def __init__(self, *, session: FakeJSON | Exception | None = None, upload: FakeJSON | Exception | None = None,
                 record: FakeJSON | Exception | None = None) -> None:
        self.answers = {
            bluesky.SESSION_URL: session or FakeJSON(200, {"accessJwt": "access-jwt-value", "refreshJwt": "r", "did": DID,
                                                            "handle": "lmiawatch.ca"}),
            bluesky.UPLOAD_URL: upload or FakeJSON(200, {"blob": BLOB}),
            bluesky.RECORD_URL: record or FakeJSON(200, {"uri": f"at://{DID}/app.bsky.feed.post/3kexample", "cid": "bafy"}),
        }
        self.calls: list[dict] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data, "headers": headers or {}})
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def urls(self) -> list[str]:
        return [c["url"] for c in self.calls]

    def record(self) -> dict:
        return next(c for c in self.calls if c["url"] == bluesky.RECORD_URL)["json"]["record"]


@pytest.fixture(autouse=True)
def site(monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")


def test_text_carries_the_link_and_a_facet_over_its_exact_bytes(conn, tmp_path):
    seed(conn)
    fake = FakeBsky()
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "posted"
    assert fake.urls() == [bluesky.SESSION_URL, bluesky.UPLOAD_URL, bluesky.RECORD_URL]
    record = fake.record()
    text = record["text"]
    assert text.startswith('Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 6 postings, at least 77 positions.')
    assert text.endswith(LINK)
    (facet,) = record["facets"]
    raw = text.encode("utf-8")
    assert raw[facet["index"]["byteStart"]:facet["index"]["byteEnd"]].decode("utf-8") == LINK
    assert facet["features"] == [{"$type": "app.bsky.richtext.facet#link", "uri": LINK}]
    assert record["$type"] == "app.bsky.feed.post" and record["langs"] == ["en"]
    assert record["createdAt"].endswith("Z")
    image = record["embed"]["images"][0]
    assert record["embed"]["$type"] == "app.bsky.embed.images"
    assert image["image"] == BLOB and image["aspectRatio"] == {"width": 1200, "height": 675}
    assert image["alt"].startswith("LMIA Watch daily card. Job Bank, 2026-10-17")
    # Signed in with the handle and app password; later calls carry the session token, never the password.
    sign_in, upload, create = fake.calls
    assert sign_in["json"] == {"identifier": "lmiawatch.ca", "password": "abcd-efgh-ijkl-mnop"}
    assert upload["headers"]["Authorization"] == "Bearer access-jwt-value"
    assert upload["headers"]["Content-Type"] == "image/png" and upload["data"][:8] == b"\x89PNG\r\n\x1a\n"
    assert create["json"]["repo"] == DID and create["json"]["collection"] == "app.bsky.feed.post"
    assert "abcd-efgh" not in str(create) and "abcd-efgh" not in str(upload)
    assert create["headers"]["User-Agent"].startswith("LMIAWatch/")
    assert get_meta(conn, "bsky_last_post_date") == "2026-10-17"
    assert get_meta(conn, "bsky_last_post_uri") == f"at://{DID}/app.bsky.feed.post/3kexample"
    assert (tmp_path / "2026-10-17.bluesky.txt").read_text(encoding="utf-8").strip() == text
    assert (tmp_path / "2026-10-17.png").exists()


def test_one_pass_is_posted_once_and_independently_of_x(conn, tmp_path):
    seed(conn)
    # X already posted this pass; Bluesky keeps its own record and still posts once.
    set_meta(conn, "x_last_post_date", "2026-10-17")
    fake = FakeBsky()
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "posted"
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "already posted"
    assert fake.urls().count(bluesky.RECORD_URL) == 1
    # And X is unaffected by Bluesky's record.
    assert get_meta(conn, "x_last_post_date") == "2026-10-17"


def test_the_same_guards_as_x(conn, tmp_path):
    fake = FakeBsky()
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "no pass"
    add_posting(conn, 10, "Acme Greenhouses Inc", "ON", "Leamington", 30)
    set_meta(conn, "jobbank_last_run", LATEST)
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "first pass"
    add_posting(conn, 1, "Old Posting Ltd", "MB", "Brandon", 9, first_seen=EARLIER)
    for i in range(social.MAX_NEW_POSTINGS):
        add_posting(conn, 100 + i, f"Employer {i} Ltd", "ON", "Toronto", 1)
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "bulk pass"
    conn.execute("DELETE FROM jobbank_postings WHERE first_seen = ?", (LATEST,))
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "no new postings"
    assert fake.calls == [] and get_meta(conn, "bsky_last_post_date") is None


def test_text_fits_300_graphemes_and_drops_employers_first():
    long_names = [EmployerLine("Long Employer Name " * 5, "Somewhere", "ON", n) for n in (40, 30, 20)]
    d = Digest("2026-10-17", postings=9, positions=90, positions_known=9,
               provinces=["AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK"], employers=long_names)
    text = bluesky.compose(d, LINK)
    assert bluesky.bsky_length(text) <= 300 and text.endswith(LINK)
    assert "\nIn AB, BC" in text
    assert 0 < text.count("Long Employer Name") < 15
    # Bluesky counts the link in full, so the same digest may keep fewer lines than on X.
    assert bluesky.bsky_length(LINK) == len(LINK)


def test_grapheme_bound_never_undercounts():
    # A flag is two code points and one grapheme; an accent may be one or two code points.
    assert bluesky.bsky_length("\U0001F1E8\U0001F1E6") == 2
    assert bluesky.bsky_length("Saint-Rémi") == len("Saint-Rémi")
    assert bluesky.bsky_length("東京") == 2


def test_facet_offsets_count_utf8_bytes():
    text = "Ferme Exemple, Saint-Rémi QC: 4 été\n" + LINK
    facet = bluesky.link_facet(text, LINK)
    start = facet["index"]["byteStart"]
    assert start == len(text[: text.index(LINK)].encode("utf-8")) and start > text.index(LINK)
    assert text.encode("utf-8")[start:facet["index"]["byteEnd"]] == LINK.encode("utf-8")
    assert bluesky.link_facet("no link here", LINK) is None


def test_upload_failure_or_oversize_card_posts_the_text_alone(conn, tmp_path, monkeypatch):
    seed(conn)
    for fake in (FakeBsky(upload=FakeJSON(500, {"error": "InternalServerError"})),
                 FakeBsky(upload=RuntimeError("boom")),
                 FakeBsky(upload=FakeJSON(200, None, text="<html>bad gateway</html>"))):
        assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "posted"
        assert "embed" not in fake.record() and fake.record()["facets"]
        conn.execute("DELETE FROM meta WHERE key LIKE 'bsky_%'"); conn.commit()
    monkeypatch.setattr(bluesky, "MAX_IMAGE_BYTES", 10)
    fake = FakeBsky()
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "posted"
    assert bluesky.UPLOAD_URL not in fake.urls() and "embed" not in fake.record()


@pytest.mark.parametrize("fake", [
    FakeBsky(session=FakeJSON(401, {"error": "AuthenticationRequired", "message": "Invalid identifier or password"})),
    FakeBsky(session=requests.ConnectionError("unreachable")),
    FakeBsky(session=FakeJSON(200, {"unexpected": True})),
    FakeBsky(record=FakeJSON(400, {"error": "InvalidRequest"})),
    FakeBsky(record=RuntimeError("anything at all")),
])
def test_a_failed_sign_in_or_post_is_logged_not_raised(conn, tmp_path, fake, caplog):
    seed(conn)
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "failed"
    assert get_meta(conn, "bsky_last_post_date") is None
    assert "bluesky: " in caplog.text
    assert "abcd-efgh-ijkl-mnop" not in caplog.text and "access-jwt-value" not in caplog.text


def test_a_post_created_without_a_readable_uri_is_still_recorded(conn, tmp_path):
    seed(conn)
    fake = FakeBsky(record=FakeJSON(200, None, text="<html>ok</html>"))
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=fake) == "posted"
    assert get_meta(conn, "bsky_last_post_date") == "2026-10-17"
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=FakeBsky()) == "already posted"


def test_missing_credentials_skip_and_never_show_the_password(conn, tmp_path):
    seed(conn)
    fake = FakeBsky()
    assert bluesky.run(conn, out_dir=tmp_path, env={"BSKY_HANDLE": "lmiawatch.ca"}, session=fake) == "no credentials"
    assert bluesky.run(conn, out_dir=tmp_path, env=X_CREDS, session=fake) == "no credentials"
    assert fake.calls == []
    assert repr(bluesky.credentials_from_env(CREDS)) == "Credentials(****)"
    assert bluesky.credentials_from_env({"BSKY_HANDLE": "@lmiawatch.ca", "BSKY_APP_PASSWORD": "x"}).handle == "lmiawatch.ca"


def test_dry_run_prints_the_text_with_its_link_and_sends_nothing(conn, tmp_path):
    seed(conn)
    fake = FakeBsky()
    printed: list[str] = []
    assert bluesky.run(conn, dry_run=True, out_dir=tmp_path, env=CREDS, session=fake, echo=printed.append) == "dry run"
    assert fake.calls == [] and printed[0].endswith(LINK)
    assert get_meta(conn, "bsky_last_post_date") is None


def test_an_unexpected_fault_is_an_outcome(conn, tmp_path, monkeypatch):
    seed(conn)
    monkeypatch.setattr(social, "collect", lambda c: (_ for _ in ()).throw(RuntimeError("broken")))
    assert bluesky.run(conn, out_dir=tmp_path, env=CREDS, session=FakeBsky()) == "failed"


def test_cli_writes_the_outcome_and_exits_1_on_failure(tmp_path, monkeypatch):
    db = tmp_path / "lmia.sqlite"
    c = connect(db)
    seed(c)
    c.close()
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    for name, value in CREDS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(bluesky, "send_post", lambda *a, **k: None)
    assert cli.main(["post-bluesky", "--db", str(db), "--no-image"]) == 1
    assert (tmp_path / "out" / "social" / "bluesky_outcome.txt").read_text(encoding="utf-8").strip() == "failed"
    monkeypatch.setattr(bluesky, "send_post", lambda *a, **k: "at://did:plc:x/app.bsky.feed.post/1")
    assert cli.main(["post-bluesky", "--db", str(db), "--no-image"]) == 0
    assert (tmp_path / "out" / "social" / "bluesky_outcome.txt").read_text(encoding="utf-8").strip() == "posted"
    # The X outcome file is X's alone.
    assert not (tmp_path / "out" / "social" / "last_outcome.txt").exists()
