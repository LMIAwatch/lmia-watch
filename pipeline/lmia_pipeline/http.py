"""Polite HTTP client shared by every source.

Why a custom client: Job Bank publishes a crawl delay of five seconds in its
robots.txt, the open-data files should be fetched once and revalidated rather
than re-downloaded, and a run must stop rather than keep hitting a host that
is failing.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import config


def decode_text(data: bytes) -> str:
    """UTF-8 when it is valid, else Windows-1252; government pages use both."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


class FetchError(Exception):
    """One request failed in a way that retries did not fix."""


class AbortRun(Exception):
    """Too many requests failed in a row; the run stops to protect the host."""


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

        attempt = 0
        while True:
            attempt += 1
            self._wait_for_host(host)
            try:
                resp = self.session.get(url, headers=req_headers, timeout=timeout)
            except requests.RequestException as exc:
                self._mark(host)
                self._retry_or_fail(url, attempt, repr(exc))
                continue
            self._mark(host)
            self.requests_made += 1

            if resp.status_code == 304 and entry is not None:
                entry.touch()
                self._consecutive_failures = 0
                return entry.content
            if resp.status_code >= 500 or resp.status_code == 429:
                self._retry_or_fail(url, attempt, f"HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                # A missing resource is a data fact, not a host problem, so it
                # does not count toward the circuit breaker.
                raise FetchError(f"HTTP {resp.status_code} for {url}")

            self._consecutive_failures = 0
            if cache:
                self._store(url, resp)
            return resp.content

    def get_text(self, url: str, **kwargs: Any) -> str:
        return decode_text(self.get(url, **kwargs))

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return json.loads(self.get(url, **kwargs).decode("utf-8"))

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

    def _retry_or_fail(self, url: str, attempt: int, reason: str) -> None:
        if attempt < self.max_attempts:
            self._sleep(min(2**attempt, 60))
            return
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

    def _store(self, url: str, resp: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path_bin, path_meta = self._cache_paths(url)
        path_bin.write_bytes(resp.content)
        meta = {
            "url": url,
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "fetched_at": time.time(),
        }
        path_meta.write_text(json.dumps(meta), encoding="utf-8")
