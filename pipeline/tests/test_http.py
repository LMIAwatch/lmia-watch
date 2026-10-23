import pytest

from conftest import FakeResponse, FakeSession
from lmia_pipeline.http import AbortRun, FetchError, PoliteClient


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def make(mapping, tmp_path, **kw):
    clock = Clock()
    session = FakeSession(mapping)
    client = PoliteClient(session=session, cache_dir=tmp_path / "c", sleep=clock.sleep, clock=clock.now, **kw)
    return client, session, clock


def test_spacing_per_host(tmp_path):
    client, session, clock = make({
        "https://www.jobbank.gc.ca/a": b"a", "https://www.jobbank.gc.ca/b": b"b", "https://other.example/c": b"c",
    }, tmp_path)
    client.get("https://www.jobbank.gc.ca/a")
    client.get("https://other.example/c")
    client.get("https://www.jobbank.gc.ca/b")
    assert client.requests_made == 3
    # The second Job Bank request waited the full crawl delay; the other host did not.
    assert max(clock.sleeps) == pytest.approx(8.0)
    assert client.user_agent.startswith("LMIAWatch/")
    assert all(h["User-Agent"] == client.user_agent for _, h in session.calls)


def test_retries_then_succeeds(tmp_path):
    class Flaky:
        def __init__(self) -> None:
            self.n = 0
            self.calls = []

        def get(self, url, headers=None, timeout=None, stream=False):
            self.n += 1
            return FakeResponse(503) if self.n < 3 else FakeResponse(200, b"ok")

    clock = Clock()
    client = PoliteClient(session=Flaky(), cache_dir=tmp_path, sleep=clock.sleep, clock=clock.now)
    assert client.get("https://x.example/y") == b"ok"


def test_404_raises_without_tripping_breaker(tmp_path):
    client, _, _ = make({}, tmp_path)
    for _ in range(6):
        with pytest.raises(FetchError):
            client.get("https://x.example/missing")


def test_breaker_aborts_after_repeated_failures(tmp_path):
    class Down:
        def get(self, url, headers=None, timeout=None, stream=False):
            return FakeResponse(500)

    clock = Clock()
    client = PoliteClient(session=Down(), cache_dir=tmp_path, sleep=clock.sleep, clock=clock.now,
                          max_attempts=1, max_consecutive_failures=3)
    with pytest.raises(FetchError):
        client.get("https://x.example/1")
    with pytest.raises(FetchError):
        client.get("https://x.example/2")
    with pytest.raises(AbortRun):
        client.get("https://x.example/3")


def test_cache_and_revalidation(tmp_path):
    url = "https://open.example/file.csv"
    client, session, clock = make({url: FakeResponse(200, b"v1", {"ETag": "abc"})}, tmp_path)
    assert client.get(url, cache=True) == b"v1"
    assert client.get(url, cache=True, max_age_s=3600) == b"v1"
    assert len(session.calls) == 1
    session.mapping[url] = FakeResponse(304)
    assert client.get(url, cache=True, max_age_s=0) == b"v1"
    assert session.calls[-1][1]["If-None-Match"] == "abc"
    session.mapping[url] = FakeResponse(200, b"v2", {"ETag": "def"})
    assert client.get(url, cache=True, max_age_s=0) == b"v2"


def test_forget_drops_a_cached_body(tmp_path):
    url = "https://open.example/layer.json"
    client, session, clock = make({url: FakeResponse(200, b"bad")}, tmp_path)
    assert client.get(url, cache=True, max_age_s=float("inf")) == b"bad"
    client.forget(url)
    session.mapping[url] = FakeResponse(200, b"good")
    assert client.get(url, cache=True, max_age_s=float("inf")) == b"good"
    assert len(session.calls) == 2
    client.forget("https://open.example/never-fetched")  # nothing cached: no error


def test_download_streams_to_a_file_retries_and_caches_nothing(tmp_path):
    class Chunked(FakeResponse):
        def iter_content(self, chunk_size=0):
            yield b"head,"
            yield b"body\n"

    class Flaky:
        def __init__(self) -> None:
            self.n = 0
            self.calls = []

        def get(self, url, headers=None, timeout=None, stream=False):
            self.n += 1
            self.calls.append((url, headers or {}))
            return FakeResponse(503) if self.n < 2 else Chunked(200)

    clock = Clock()
    session = Flaky()
    client = PoliteClient(session=session, cache_dir=tmp_path / "c", sleep=clock.sleep, clock=clock.now)
    dest = tmp_path / "work" / "big.csv"
    assert client.download("https://open.example/big.csv", dest) == 10
    assert dest.read_bytes() == b"head,body\n" and session.n == 2
    assert not (tmp_path / "work" / "big.csv.part").exists() and not (tmp_path / "c").exists()
    assert session.calls[0][1]["User-Agent"] == client.user_agent
    with pytest.raises(FetchError):
        make({}, tmp_path)[0].download("https://open.example/missing.csv", tmp_path / "x.csv")
    assert not (tmp_path / "x.csv").exists()
