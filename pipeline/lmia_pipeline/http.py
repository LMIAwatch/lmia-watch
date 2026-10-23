"""Polite HTTP client shared by every source.

Why a custom client: Job Bank publishes a crawl delay of five seconds in its
robots.txt, the open-data files should be fetched once and revalidated rather
than re-downloaded, and a run must stop rather than keep hitting a host that
is failing.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import config

# A host that asks for a pause (429 or 503 with Retry-After) gets it, up to
# this long; a longer request ends the attempt instead of retrying early.
MAX_RETRY_AFTER_S = 300.0
# The read timeout applies between bytes, so a server that trickles a body
# could hold a request open indefinitely. A body must arrive within this many
# seconds, or four read timeouts when that is longer.
MIN_BODY_SECONDS = 900.0
# Opening a connection takes well under a second when a host is up; waiting
# the full read timeout for one only delays the news that it is not.
CONNECT_TIMEOUT_S = 20.0
# Attempts per request on a host in config.CONNECT_FAIL_FAST when the
# connection itself fails.
CONNECT_ATTEMPTS = 2
CHUNK_BYTES = 1 << 16


def decode_text(data: bytes) -> str:
    """UTF-8 when it is valid, else Windows-1252; government pages use both."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds asked for by a Retry-After header (a number of seconds or an HTTP
    date); None when the header is absent or unreadable."""
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


class FetchError(Exception):
    """One request failed in a way that retries did not fix."""


class AbortRun(Exception):
    """Too many requests failed in a row; the run stops to protect the host."""


class _SlowBody(Exception):
    """The body did not finish arriving within the request's time limit."""


@dataclass
class _CacheEntry:
    path_bin: Path
    path_meta: Path
    meta: dict[str, Any]

    @property
    def content(self) -> bytes:
        return self.path_bin.read_bytes()

    def fresh(self, max_age_s: float) -> bool:
        return (time.time() - float(self.meta.get("fetched_at", 0))) < max_age_s

    def touch(self) -> None:
        self.meta["fetched_at"] = time.time()
        self.path_meta.write_text(json.dumps(self.meta), encoding="utf-8")


class PoliteClient:
    """GET with per-host spacing, retries, a failure circuit breaker and a disk cache."""

    def __init__(
        self,
        *,
        session: Any | None = None,
        cache_dir: Path | None = None,
        delays: dict[str, float] | None = None,
        default_delay: float | None = None,
        max_consecutive_failures: int = 5,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        user_agent: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.cache_dir = Path(cache_dir) if cache_dir else config.CACHE_DIR
        self.delays = dict(config.CRAWL_DELAY if delays is None else delays)
        self.default_delay = config.DEFAULT_DELAY if default_delay is None else default_delay
        self.max_consecutive_failures = max_consecutive_failures
        self.max_attempts = max_attempts
        self.connect_fail_fast = dict(config.CONNECT_FAIL_FAST)
        self._connect_failures: dict[str, int] = {}
        self.user_agent = user_agent or config.USER_AGENT
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._consecutive_failures = 0
        self.requests_made = 0

    # -- public -------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        cache: bool = False,
        max_age_s: float = 86400,
        timeout: float = 60,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        host = urlsplit(url).hostname or ""
        entry = self._cache_entry(url) if cache else None
        if entry is not None and entry.fresh(max_age_s):
            return entry.content

        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)
        if entry is not None:
            if entry.meta.get("etag"):
                req_headers["If-None-Match"] = entry.meta["etag"]
            if entry.meta.get("last_modified"):
                req_headers["If-Modified-Since"] = entry.meta["last_modified"]

        body_limit = max(MIN_BODY_SECONDS, 4 * timeout)
        attempt = 0
        while True:
            attempt += 1
            self._wait_for_host(host)
            started = self._clock()
            try:
                resp = self.session.get(url, headers=req_headers, timeout=(min(CONNECT_TIMEOUT_S, timeout), timeout),
                                        stream=True)
            except requests.RequestException as exc:
                self._mark(host)
                # ConnectTimeout is a ConnectionError too: the host took no
                # connection at all, which a read timeout does not mean.
                self._retry_or_fail(url, attempt, repr(exc), host=host,
                                    connect=isinstance(exc, requests.ConnectionError))
                continue
            self._mark(host)
            # Any answer means the host is taking connections again.
            self._connect_failures.pop(host, None)
            self.requests_made += 1

            if resp.status_code == 304 and entry is not None:
                _close(resp)
                entry.touch()
                self._consecutive_failures = 0
                return entry.content
            if resp.status_code >= 500 or resp.status_code == 429:
                wait = retry_after_seconds(_header(resp, "Retry-After"))
                _close(resp)
                self._retry_or_fail(url, attempt, f"HTTP {resp.status_code}", wait)
                continue
            if resp.status_code >= 400:
                _close(resp)
                # A missing resource is a data fact, not a host problem, so it
                # does not count toward the circuit breaker.
                raise FetchError(f"HTTP {resp.status_code} for {url}")

            try:
                content = self._read_body(resp, started, body_limit)
            except (requests.RequestException, _SlowBody) as exc:
                # A body cut short (the length check or the chunked framing
                # fails) or one that trickles past the limit is retried, and
                # never cached.
                _close(resp)
                self._mark(host)
                self._retry_or_fail(url, attempt, repr(exc))
                continue
            self._mark(host)
            self._consecutive_failures = 0
            if cache:
                self._store(url, resp, content)
            return content

    def download(self, url: str, dest: Path, *, timeout: float = 600) -> int:
        """Stream a large file to dest with the same spacing, retries and breaker as get().

        Why: the grants disclosure is 2.3 GB, which get() would hold in
        memory. Nothing is cached (the file is read once and deleted), the
        body goes to dest + '.part' and is renamed only when complete, and the
        byte count is returned.
        """
        host = urlsplit(url).hostname or ""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        body_limit = max(MIN_BODY_SECONDS, 4 * timeout)
        attempt = 0
        while True:
            attempt += 1
            self._wait_for_host(host)
            started = self._clock()
            try:
                resp = self.session.get(url, headers={"User-Agent": self.user_agent},
                                        timeout=(min(CONNECT_TIMEOUT_S, timeout), timeout), stream=True)
            except requests.RequestException as exc:
                self._mark(host)
                self._retry_or_fail(url, attempt, repr(exc), host=host,
                                    connect=isinstance(exc, requests.ConnectionError))
                continue
            self._mark(host)
            self._connect_failures.pop(host, None)
            self.requests_made += 1
            if resp.status_code >= 500 or resp.status_code == 429:
                wait = retry_after_seconds(_header(resp, "Retry-After"))
                _close(resp)
                self._retry_or_fail(url, attempt, f"HTTP {resp.status_code}", wait)
                continue
            if resp.status_code >= 400:
                _close(resp)
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            try:
                size = self._write_body(resp, part, started, body_limit)
            except (requests.RequestException, _SlowBody, OSError) as exc:
                _close(resp)
                part.unlink(missing_ok=True)
                self._mark(host)
                self._retry_or_fail(url, attempt, repr(exc))
                continue
            self._mark(host)
            self._consecutive_failures = 0
            part.replace(dest)
            return size

    def get_text(self, url: str, **kwargs: Any) -> str:
        return decode_text(self.get(url, **kwargs))

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return json.loads(self.get(url, **kwargs).decode("utf-8"))

    def forget(self, url: str) -> None:
        """Drop a cached response, so a body that turned out unusable is fetched again."""
        for path in self._cache_paths(url):
            path.unlink(missing_ok=True)

    # -- internals ----------------------------------------------------------

    def _wait_for_host(self, host: str) -> None:
        delay = self.delays.get(host, self.default_delay)
        last = self._last_request.get(host)
        if last is None:
            return
        remaining = delay - (self._clock() - last)
        if remaining > 0:
            self._sleep(remaining)

    def _mark(self, host: str) -> None:
        self._last_request[host] = self._clock()

    def _read_body(self, resp: Any, started: float, limit: float) -> bytes:
        chunks = getattr(resp, "iter_content", None)
        if chunks is None:  # a stand-in response that holds its body already
            return resp.content
        parts: list[bytes] = []
        for chunk in chunks(chunk_size=CHUNK_BYTES):
            if chunk:
                parts.append(chunk)
            if self._clock() - started > limit:
                raise _SlowBody(f"body still arriving after {limit:.0f} s")
        return b"".join(parts)

    def _write_body(self, resp: Any, path: Path, started: float, limit: float) -> int:
        chunks = getattr(resp, "iter_content", None)
        size = 0
        with path.open("wb") as fh:
            if chunks is None:  # a stand-in response that holds its body already
                fh.write(resp.content)
                return len(resp.content)
            for chunk in chunks(chunk_size=CHUNK_BYTES):
                if chunk:
                    fh.write(chunk)
                    size += len(chunk)
                if self._clock() - started > limit:
                    raise _SlowBody(f"body still arriving after {limit:.0f} s")
        return size

    def _retry_or_fail(self, url: str, attempt: int, reason: str, wait: float | None = None, *,
                       host: str | None = None, connect: bool = False) -> None:
        fail_fast = self.connect_fail_fast.get(host or "") if connect else None
        attempts = min(self.max_attempts, CONNECT_ATTEMPTS) if fail_fast else self.max_attempts
        # The host's own Retry-After wins over the backoff when it is longer;
        # one longer than MAX_RETRY_AFTER_S is not retried early at all.
        if attempt < attempts and (wait is None or wait <= MAX_RETRY_AFTER_S):
            self._sleep(max(min(2**attempt, 60), wait or 0.0))
            return
        if wait is not None and wait > MAX_RETRY_AFTER_S:
            reason += f" (Retry-After {wait:.0f} s)"
        if fail_fast and host:
            self._connect_failures[host] = self._connect_failures.get(host, 0) + 1
            if self._connect_failures[host] >= fail_fast:
                raise AbortRun(
                    f"{host} stopped accepting connections: {self._connect_failures[host]} requests in a row "
                    f"could not connect; last {reason} ({url})"
                )
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_consecutive_failures:
            raise AbortRun(
                f"{self._consecutive_failures} requests failed in a row; last {reason} ({url})"
            )
        raise FetchError(f"{url}: {reason} after {attempt} attempts")

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _cache_entry(self, url: str) -> _CacheEntry | None:
        path_bin, path_meta = self._cache_paths(url)
        if not (path_bin.exists() and path_meta.exists()):
            return None
        try:
            meta = json.loads(path_meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return _CacheEntry(path_bin, path_meta, meta)

    def _store(self, url: str, resp: Any, content: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path_bin, path_meta = self._cache_paths(url)
        path_bin.write_bytes(content)
        meta = {
            "url": url,
            "etag": _header(resp, "ETag"),
            "last_modified": _header(resp, "Last-Modified"),
            "fetched_at": time.time(),
        }
        path_meta.write_text(json.dumps(meta), encoding="utf-8")


def _header(resp: Any, name: str) -> str | None:
    headers = getattr(resp, "headers", None) or {}
    value = headers.get(name)
    if value is None:  # a plain dict in a test is case-sensitive; requests' headers are not
        lowered = name.lower()
        value = next((v for k, v in headers.items() if str(k).lower() == lowered), None)
    return value


def _close(resp: Any) -> None:
    """Release a streamed response's connection without reading the rest of it."""
    close = getattr(resp, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass
