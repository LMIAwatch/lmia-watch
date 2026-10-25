"""IndexNow: the key file, which pages a night sends, how the submission
answers become outcomes, the command's files and exit codes, and the run
status field."""

import json
import re
from pathlib import Path

import pytest

from lmia_pipeline import config, indexnow, nightly, resilience, status
from lmia_pipeline.db import connect, upsert_employer

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://lmiawatch.example"
KEY = indexnow.INDEXNOW_KEY
BEFORE = "2026-10-23T00:04:10Z"
START = "2026-10-24T00:04:10Z"
FIXED = [f"{BASE}/", f"{BASE}/search", f"{BASE}/trends", f"{BASE}/occupations", f"{BASE}/places",
         f"{BASE}/releases", f"{BASE}/program"]


class Resp:
    def __init__(self, status):
        self.status_code = status


class FakeHttp:
    """Answers POSTs from a queue (the last answer repeats); an exception in
    the queue is raised. Records every call with its decoded body."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.closed = False

    def post(self, url, data=None, headers=None, timeout=None, **kwargs):
        self.calls.append({"url": url, "body": json.loads(data), "headers": dict(headers or {}), "timeout": timeout,
                           "kwargs": kwargs})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return Resp(answer)

    def close(self):
        self.closed = True


class KeyFileHttp(FakeHttp):
    """A FakeHttp that also answers GET for the key file."""

    def __init__(self, key_status, key_text, *answers):
        super().__init__(*answers)
        self.key_status, self.key_text, self.gets = key_status, key_text, []

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.gets.append(url)
        r = Resp(self.key_status)
        r.text = self.key_text
        return r


def send(http, urls, **kwargs):
    waits = []
    record = indexnow.submit(http, urls, key=KEY, host="lmiawatch.example", key_location=f"{BASE}/{KEY}.txt",
                             sleep=waits.append, **kwargs)
    return record, waits


def employer(conn, name, stamp):
    return upsert_employer(conn, name, "BC", source="esdc", now=stamp)


def urls_of(n):
    return [f"{BASE}/employers/emp-{i:010x}" for i in range(n)]


# -- the key file ----------------------------------------------------------------


def test_the_key_file_at_the_site_root_holds_exactly_the_key():
    assert re.fullmatch(r"[0-9a-f]{32}", KEY)
    key_file = ROOT / "site" / "public" / f"{KEY}.txt"
    assert key_file.is_file()
    # The whole content, with no newline: an engine compares it with the key.
    assert key_file.read_bytes() == KEY.encode("ascii")


# -- which pages ------------------------------------------------------------------


def test_the_fixed_pages_then_the_employers_changed_since_the_start(conn):
    old = employer(conn, "Old Farms Ltd", BEFORE)
    new = employer(conn, "New Farms Ltd", START)
    later = employer(conn, "Later Farms Ltd", "2026-10-24T02:30:00Z")
    conn.commit()
    urls = indexnow.changed_urls(conn, START, BASE + "/")
    assert urls == FIXED + [f"{BASE}/employers/{later}", f"{BASE}/employers/{new}"]
    assert f"{BASE}/employers/{old}" not in urls


def test_the_start_may_be_written_in_any_iso_form(conn):
    eid = employer(conn, "New Farms Ltd", START)
    conn.commit()
    for since in (START, "2026-10-24T00:04:10+00:00", "2026-10-23T17:04:10-07:00", "2026-10-24T00:04:10"):
        assert indexnow.changed_urls(conn, since, BASE)[-1] == f"{BASE}/employers/{eid}"
    assert indexnow.normalize_since("2026-10-24") == "2026-10-24T00:00:00Z"
    for bad in ("", None, "yesterday"):
        with pytest.raises(ValueError):
            indexnow.normalize_since(bad)


def test_employers_the_status_stage_rewrote_are_selected_and_unchanged_ones_are_not(conn):
    a = employer(conn, "Alpha Farms Ltd", BEFORE)
    b = employer(conn, "Beta Farms Ltd", BEFORE)
    conn.commit()
    status.recompute(conn, now=BEFORE)
    conn.execute(
        "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, lmias, positions, resource_id, row_hash) "
        "VALUES ('positive', '2026Q1', ?, 'Alpha Farms Ltd', 'BC', 1, 4, 'res', 'h1')", (a,))
    conn.commit()
    assert status.recompute(conn, now=START) == 1
    urls = indexnow.changed_urls(conn, START, BASE)
    assert f"{BASE}/employers/{a}" in urls and f"{BASE}/employers/{b}" not in urls


def test_order_is_newest_change_first_with_ties_by_id_whatever_the_insert_order(conn):
    stamp = "2026-10-24T01:00:00Z"
    ids = [employer(conn, name, stamp) for name in ("Zeta Ltd", "Eta Ltd", "Theta Ltd", "Iota Ltd")]
    newest = employer(conn, "Kappa Ltd", "2026-10-24T03:00:00Z")
    conn.commit()
    urls = indexnow.changed_urls(conn, START, BASE)
    assert urls[len(FIXED):] == [f"{BASE}/employers/{e}" for e in [newest] + sorted(ids)]
    assert indexnow.changed_urls(conn, START, BASE) == urls


def test_no_url_is_sent_twice(conn):
    eid = employer(conn, "New Farms Ltd", START)
    conn.commit()
    pages = ["/", "/search", "/search", f"/employers/{eid}"]
    urls = indexnow.changed_urls(conn, START, BASE, pages=pages)
    assert urls == [f"{BASE}/", f"{BASE}/search", f"{BASE}/employers/{eid}"]
    assert len(set(urls)) == len(urls)


def test_the_cap_keeps_the_fixed_pages_and_the_most_recent_changes(conn):
    stamps = [f"2026-10-24T0{h}:00:00Z" for h in range(1, 6)]
    ids = [employer(conn, f"Employer {h} Ltd", s) for h, s in enumerate(stamps)]
    conn.commit()
    urls = indexnow.changed_urls(conn, START, BASE, cap=10)
    assert len(urls) == 10
    assert urls == FIXED + [f"{BASE}/employers/{e}" for e in reversed(ids[2:])]
    assert indexnow.CAP == 20_000
    assert len(indexnow.changed_urls(conn, START, BASE, cap=3)) == 3


# -- the submission ---------------------------------------------------------------


def test_one_request_per_ten_thousand_urls_with_the_documented_body(monkeypatch):
    http = FakeHttp(200, 202, 200)
    urls = urls_of(25_000)
    record, waits = send(http, urls)
    assert record["outcome"] == "submitted 25000 URLs"
    assert (record["urls"], record["accepted"], record["batches"], record["sent"]) == (25_000, 25_000, 3, 3)
    assert [len(c["body"]["urlList"]) for c in http.calls] == [10_000, 10_000, 5_000]
    assert [u for c in http.calls for u in c["body"]["urlList"]] == urls
    first = http.calls[0]
    assert first["url"] == "https://api.indexnow.org/indexnow"
    assert set(first["body"]) == {"host", "key", "keyLocation", "urlList"}
    assert first["body"]["host"] == "lmiawatch.example"
    assert first["body"]["key"] == KEY
    assert first["body"]["keyLocation"] == f"{BASE}/{KEY}.txt"
    assert first["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert first["headers"]["User-Agent"] == config.USER_AGENT
    assert first["timeout"] == 30
    assert waits == []


@pytest.mark.parametrize("answer", [200, 202])
def test_200_and_202_are_accepted(answer):
    record, _ = send(FakeHttp(answer), urls_of(3))
    assert record["outcome"] == "submitted 3 URLs" and record["accepted"] == 3
    one, _ = send(FakeHttp(answer), urls_of(1))
    assert one["outcome"] == "submitted 1 URL"


@pytest.mark.parametrize("answer", [400, 403, 422])
def test_a_rejection_stops_at_once(answer):
    http = FakeHttp(answer)
    record, waits = send(http, urls_of(25_000))
    assert record["outcome"] == f"rejected ({answer})"
    assert len(http.calls) == 1 and waits == [] and record["accepted"] == 0
    assert record["detail"] == f"batch 1 of 3 answered {answer}; nothing more sent"


@pytest.mark.parametrize("answer", [403, 422])
def test_a_refusal_with_a_correct_key_file_is_not_verified_yet(answer):
    http = KeyFileHttp(200, KEY, answer)
    record, _ = send(http, urls_of(25_000))
    assert record["outcome"] == f"not verified ({answer})"
    assert http.gets == [f"{BASE}/{KEY}.txt"]
    assert len(http.calls) == 1 and record["accepted"] == 0
    assert "although the key file answers correctly" in record["detail"]


@pytest.mark.parametrize("key_status, key_text", [(404, ""), (200, "someone-else"), (200, "")])
def test_a_refusal_with_a_wrong_key_file_is_rejected(key_status, key_text):
    http = KeyFileHttp(key_status, key_text, 403)
    record, _ = send(http, urls_of(5))
    assert record["outcome"] == "rejected (403)"


def test_a_bad_request_is_rejected_without_checking_the_key_file():
    http = KeyFileHttp(200, KEY, 400)
    record, _ = send(http, urls_of(5))
    assert record["outcome"] == "rejected (400)" and http.gets == []


def test_a_rejection_after_an_accepted_batch_sends_no_further_batches():
    http = FakeHttp(200, 422, 200)
    record, _ = send(http, urls_of(25_000))
    assert record["outcome"] == "rejected (422)"
    assert len(http.calls) == 2 and record["accepted"] == 10_000 and record["sent"] == 2
    assert record["answers"] == ["HTTP 200", "HTTP 422"]


def test_429_is_rate_limited_and_stops():
    http = FakeHttp(429)
    record, waits = send(http, urls_of(15_000))
    assert record["outcome"] == "rate limited"
    assert len(http.calls) == 1 and waits == []


def test_a_server_error_is_tried_once_more_after_ten_seconds():
    http = FakeHttp(503, 200)
    record, waits = send(http, urls_of(5))
    assert record["outcome"] == "submitted 5 URLs"
    assert len(http.calls) == 2 and waits == [10.0]
    assert http.calls[0]["body"] == http.calls[1]["body"]


def test_no_answer_twice_is_failed():
    http = FakeHttp(ConnectionError("refused"))
    record, waits = send(http, urls_of(5))
    assert record["outcome"] == "failed"
    assert len(http.calls) == 2 and waits == [10.0]
    assert record["detail"] == "batch 1 of 1: no answer (ConnectionError) on the retry as well"
    twice, _ = send(FakeHttp(503), urls_of(5))
    assert twice["outcome"] == "failed" and twice["detail"] == "batch 1 of 1: HTTP 503 on the retry as well"


def test_an_unexpected_answer_is_failed_without_a_retry():
    http = FakeHttp(404)
    record, waits = send(http, urls_of(5))
    assert record["outcome"] == "failed" and len(http.calls) == 1 and waits == []


def test_nothing_to_send_sends_nothing():
    http = FakeHttp(200)
    record, _ = send(http, [])
    assert record["outcome"] == "nothing to send" and http.calls == []


def test_the_submission_never_raises():
    class Broken:
        def post(self, *args, **kwargs):
            return object()  # no status_code at all
    record, waits = send(Broken(), urls_of(2))
    assert record["outcome"] == "failed" and waits == [10.0]


# -- the command ------------------------------------------------------------------


@pytest.fixture
def night(tmp_path):
    db = tmp_path / "lmia.sqlite"
    conn = connect(db)
    employer(conn, "Old Farms Ltd", BEFORE)
    changed = [employer(conn, f"New Farms {i} Ltd", START) for i in range(3)]
    conn.commit()
    conn.close()
    return db, tmp_path / "indexnow", changed


def command(db, out, *extra, since=START):
    return nightly.main(["indexnow", "--db", str(db), "--since", since, "--site-url", BASE, "--out-dir", str(out), *extra])


def test_the_command_sends_and_writes_the_outcome_and_the_list(night, monkeypatch):
    db, out, changed = night
    http = FakeHttp(200)
    monkeypatch.setattr(nightly, "_session", lambda: http)
    assert command(db, out) == 0
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == "submitted 10 URLs\n"
    sent = (out / "urls.txt").read_text(encoding="utf-8").splitlines()
    assert sent == FIXED + [f"{BASE}/employers/{e}" for e in sorted(changed)]
    assert http.calls[0]["body"]["urlList"] == sent and http.closed


@pytest.mark.parametrize("answer, code, outcome", [
    (403, 1, "rejected (403)"),
    (422, 1, "rejected (422)"),
    (429, 0, "rate limited"),
    (404, 0, "failed"),
])
def test_only_a_rejection_exits_1(night, monkeypatch, answer, code, outcome):
    db, out, _ = night
    monkeypatch.setattr(nightly, "_session", lambda: FakeHttp(answer))
    assert command(db, out) == code
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == outcome + "\n"


def test_an_outage_reads_failed_and_exits_0(night, monkeypatch):
    db, out, _ = night
    monkeypatch.setattr(indexnow, "RETRY_S", 0)
    monkeypatch.setattr(nightly, "_session", lambda: FakeHttp(ConnectionError("down")))
    assert command(db, out) == 0
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == "failed\n"


def test_a_dry_run_lists_the_urls_and_sends_nothing(night, monkeypatch):
    db, out, _ = night

    def no_session():
        raise AssertionError("a dry run opened a session")

    monkeypatch.setattr(nightly, "_session", no_session)
    assert command(db, out, "--dry-run") == 0
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == "dry run (10 URLs)\n"
    assert len((out / "urls.txt").read_text(encoding="utf-8").splitlines()) == 10


@pytest.mark.parametrize("since", ["", "not a time"])
def test_a_missing_start_time_is_failed_and_sends_nothing(night, monkeypatch, since):
    db, out, _ = night
    monkeypatch.setattr(nightly, "_session", lambda: pytest.fail("sent without a start time"))
    assert command(db, out, since=since) == 0
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == "failed\n"
    assert (out / "urls.txt").read_text(encoding="utf-8") == ""


def test_a_missing_database_is_failed_and_not_created(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly, "_session", lambda: pytest.fail("sent without a database"))
    out = tmp_path / "indexnow"
    assert command(tmp_path / "missing.sqlite", out) == 0
    assert (out / "last_outcome.txt").read_text(encoding="utf-8") == "failed\n"
    assert not (tmp_path / "missing.sqlite").exists()


# -- the run status and the workflow ----------------------------------------------


def test_the_run_status_carries_the_outcome_and_only_a_rejection_needs_attention(night):
    db, out, _ = night
    clean = nightly.run_status(db, None, None, None, {})
    assert clean["indexnow"] == "not run"
    for outcome, items in (("submitted 613 URLs", []), ("rate limited", []), ("failed", []), ("off", []),
                           ("rejected (403)", ["IndexNow: rejected; check the key file"])):
        record = nightly.run_status(db, "2000-01-01T00:00:00Z", {"problems": []}, "posted", {"deploy": "success"},
                                    indexnow_outcome=outcome)
        assert record["indexnow"] == outcome
        assert [i for i in resilience.attention_items(record) if i.startswith("IndexNow")] == items
        # Reported beside the stages: a submission never marks the refresh failed.
        assert record["ok"] is True
    out.mkdir(parents=True)
    (out / "last_outcome.txt").write_text("rejected (422)\n", encoding="utf-8")
    written = out / "status.json"
    assert nightly.main(["status", "--db", str(db), "--indexnow-outcome", str(out / "last_outcome.txt"),
                         "--out", str(written)]) == 0
    assert json.loads(written.read_text(encoding="utf-8"))["indexnow"] == "rejected (422)"


def test_the_workflow_runs_it_after_the_smoke_test_and_records_it():
    text = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    names = re.findall(r"^      - name: (.+)$", text, re.MULTILINE)
    step = names.index("Tell IndexNow which pages changed")
    assert names.index("Check the live site") < step < next(i for i, n in enumerate(names) if n.startswith("Post the daily digest to X"))
    block = text.split("- name: Tell IndexNow which pages changed", 1)[1].split("\n      - ", 1)[0]
    assert "if: ${{ !cancelled() && steps.deploy.outcome == 'success' && steps.smoke.outputs.verdict != 'broken' }}" in block
    assert "continue-on-error: true" in block and "timeout-minutes: 10" in block
    assert "secrets." not in block
    assert "since=$(cat data/out/run_started.txt" in block
    assert ('python -m lmia_pipeline.nightly indexnow --db data/lmia.sqlite --since "$since" \\\n'
            '            --site-url "${LMIAWATCH_SITE_URL:-https://lmiawatch.ca}"\n') in block
    assert ("--views-outcome data/out/views/last_outcome.txt \\\n"
            "            --indexnow-outcome data/out/indexnow/last_outcome.txt \\\n") in text
    # Not a --step: a failed submission must never make the retry gate run the night again.
    assert "--step \"indexnow=" not in text
    assert 'echo "IndexNow: $(cat data/out/indexnow/last_outcome.txt)" >> LAST_RUN.md' in text
