"""The HTTP client against a host that misbehaves: pauses, slow or cut bodies, loops."""

from datetime import datetime, timezone

import pytest
import requests

from conftest import FakeResponse
from lmia_pipeline.http import MAX_RETRY_AFTER_S, FetchError, PoliteClient, retry_after_seconds


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


class Scripted:
    """Answers each call with the next item: a FakeResponse, bytes, or an exception to raise."""

    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.calls = 0

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else FakeResponse(500)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return FakeResponse(200, answer)
        return answer


def client_for(answers, **kw):
    clock = Clock()
    session = Scripted(answers)
    client = PoliteClient(session=session, cache_dir=kw.pop("cache_dir", None), sleep=clock.sleep, clock=clock.now, **kw)
    return client, session, clock


def test_retry_after_reads_seconds_and_dates():
    now = datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc)
    assert retry_after_seconds("120") == 120.0
    assert retry_after_seconds("Sun, 18 Oct 2026 00:02:00 GMT", now=now) == 120.0
    assert retry_after_seconds("Sun, 18 Oct 2026 00:00:00 GMT", now=now + (now - now)) == 0.0
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("soon") is None
    assert retry_after_seconds("") is None


def test_429_waits_as_long_as_the_host_asks(tmp_path):
    client, session, clock = client_for(
        [FakeResponse(429, headers={"Retry-After": "90"}), FakeResponse(503, headers={"retry-after": "30"}), b"ok"],
        cache_dir=tmp_path,
    )
    assert client.get("https://www.jobbank.gc.ca/a") == b"ok"
    # Backoff alone would have waited 2 and 4 seconds.
    assert 90.0 in clock.sleeps and 30.0 in clock.sleeps


def test_a_pause_longer_than_the_cap_is_not_retried_early(tmp_path):
    client, session, clock = client_for(
        [FakeResponse(429, headers={"Retry-After": str(int(MAX_RETRY_AFTER_S) + 1)})], cache_dir=tmp_path,
    )
    with pytest.raises(FetchError, match="Retry-After"):
        client.get("https://www.jobbank.gc.ca/a")
    assert session.calls == 1


def test_503_without_retry_after_backs_off_then_gives_up(tmp_path):
    client, session, clock = client_for([FakeResponse(503)] * 4, cache_dir=tmp_path, max_attempts=4)
    with pytest.raises(FetchError, match="HTTP 503 after 4 attempts"):
        client.get("https://x.example/y")
    assert session.calls == 4
    assert clock.sleeps == [2, 4, 8]


def test_410_is_a_data_fact_raised_once(tmp_path):
    client, session, _ = client_for([FakeResponse(410)], cache_dir=tmp_path)
    with pytest.raises(FetchError, match="HTTP 410"):
        client.get("https://www.jobbank.gc.ca/jobsearch/jobposting/1")
    assert session.calls == 1


def test_redirect_loop_and_connection_errors_are_retried_then_fail(tmp_path):
    client, session, _ = client_for([requests.TooManyRedirects("loop")] * 4, cache_dir=tmp_path)
    with pytest.raises(FetchError, match="TooManyRedirects"):
        client.get("https://x.example/loop")
    assert session.calls == 4


class Trickle(FakeResponse):
    """A body that arrives one chunk at a time, each taking `step` seconds on the fake clock."""

    def __init__(self, clock: Clock, chunks: int, step: float) -> None:
        super().__init__(200, b"")
        self.clock, self.chunks, self.step = clock, chunks, step
        self.closed = False

    def iter_content(self, chunk_size=1):
        for _ in range(self.chunks):
            self.clock.t += self.step
            yield b"x"

    def close(self):
        self.closed = True


def test_a_body_that_trickles_past_the_limit_is_abandoned(tmp_path):
    clock = Clock()
    slow = [Trickle(clock, chunks=100, step=20.0) for _ in range(2)]
    session = Scripted(slow)
    client = PoliteClient(session=session, cache_dir=tmp_path, sleep=clock.sleep, clock=clock.now, max_attempts=2)
    with pytest.raises(FetchError, match="body still arriving"):
        client.get("https://x.example/slow", timeout=60)
    assert all(r.closed for r in slow)
    # 900 seconds per attempt at most, not the 2,000 the trickle would take.
    assert clock.t < 2 * 1000


def test_a_body_cut_short_is_retried_and_never_cached(tmp_path):
    clock = Clock()

    class Cut(FakeResponse):
        def iter_content(self, chunk_size=1):
            yield b"partial"
            raise requests.exceptions.ChunkedEncodingError("connection broken")

    session = Scripted([Cut(200, b""), FakeResponse(200, b"complete body", {"ETag": '"e1"'})])
    client = PoliteClient(session=session, cache_dir=tmp_path, sleep=clock.sleep, clock=clock.now)
    assert client.get("https://x.example/file", cache=True) == b"complete body"
    assert session.calls == 2
    entry = client._cache_entry("https://x.example/file")
    assert entry is not None and entry.content == b"complete body" and entry.meta["etag"] == '"e1"'


def test_a_streamed_body_is_read_in_full(tmp_path):
    clock = Clock()

    class Chunks(FakeResponse):
        def iter_content(self, chunk_size=1):
            yield from (b"ab", b"", b"cd")

    client = PoliteClient(session=Scripted([Chunks(200, b"")]), cache_dir=tmp_path, sleep=clock.sleep, clock=clock.now)
    assert client.get("https://x.example/ok") == b"abcd"
