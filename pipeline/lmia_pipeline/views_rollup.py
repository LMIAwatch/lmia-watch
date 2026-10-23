"""Nightly roll-up of the Worker's audience counts into files kept in R2.

Why: Workers Analytics Engine keeps a data point for three months, so the
counts the Worker writes (site/src/views.ts, dataset lmia_watch_views) would
be gone a quarter after they were taken. Once a night this asks the SQL API
for each finished UTC day the summary does not hold yet (normally only
yesterday) and keeps the answer: one CSV per day (`<day>.csv`) and one row
per day in `summary.csv`. The workflow uploads both under `views/` in R2.

What a stored row can hold: only what the Worker writes, which is the route
template, the kind of request, the page language, the country code
Cloudflare's edge attaches, the referring site's host name, the status, and
for an Atom feed the file name and the subscriber count a feed reader stated.
The Worker never writes an IP address, a user agent, a cookie, a full
referrer or a raw path, so no query can read one back. Each value read is
checked against the shape the Worker writes before it reaches a file, so a
row cannot carry more than that even if the dataset ever did.

Why a day is caught up rather than only yesterday: a night whose query fails
leaves a gap, and nothing should need a manual step to fill it. Each night
rolls up every day after the newest one in the summary, back to the three
months Analytics Engine still holds (all of them on the first night, which
keeps the counts written before the roll-up existed). A day with no data
points at all is not written: an empty day means the counting failed, not
that nobody came, and the next night asks again.

Why "failed" never stops the run: the counts are a record of the audience,
not part of the data refresh. The step reports the outcome in the run status
and the next night catches up.

Bluesky: the summary row for yesterday also carries the account's follower
count, read from the public profile endpoint with no token. X is left out:
reading a profile there costs credits under its pay-per-use API.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit

from . import config

log = logging.getLogger(__name__)

SQL_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql"
DATASET = "lmia_watch_views"
TOKEN_ENV = "CLOUDFLARE_ANALYTICS_TOKEN"
ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
BSKY_PROFILE_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"

# Analytics Engine keeps data points for three months; asking for an older
# day returns nothing, and on a re-run would replace a kept row with zeros.
RETENTION_DAYS = 90
# Grouped rows per day. A day of this site's traffic has a few hundred; the
# cap keeps one answer bounded, and the per-kind totals (a separate query)
# stay exact if it is ever reached.
MAX_ROWS = 10_000

SUMMARY = "summary.csv"
# The days written by the last run, one per line, for the workflow's upload loop.
ROLLED_UP = "rolled_up.txt"

DAY_HEADER = ["date", "section", "route", "kind", "lang", "country", "referrer", "status", "feed",
              "responses", "subscribers"]
SUMMARY_HEADER = ["date", "responses", "pages", "api", "downloads", "forms", "feeds", "other",
                  "feed_subscribers", "bluesky_followers", "top_routes"]
# Summary columns by the kind the Worker records; every other kind is "other".
KIND_COLUMNS = {"page": "pages", "api": "api", "download": "downloads", "form": "forms", "feed": "feeds"}
KINDS = {"page", "api", "download", "form", "hook", "file", "feed", "other"}
TOP_ROUTES = 5

# The shapes site/src/views.ts writes. Anything else is blanked (or "other"
# for a route), never stored as read.
ROUTE_RE = re.compile(r"^(?:other|/[A-Za-z0-9._:/-]{0,99})$")
COUNTRY_RE = re.compile(r"^[A-Z0-9]{2}$")
HOST_RE = re.compile(r"^[a-z0-9.-]{1,100}$")
FEED_RE = re.compile(r"^feeds/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.xml$")
ACCOUNT_RE = re.compile(r"^[0-9A-Fa-f]{16,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class QueryError(Exception):
    """The SQL API did not answer with rows."""


class SummaryError(Exception):
    """The summary file exists but cannot be read safely, so it is never replaced."""


# -- SQL ----------------------------------------------------------------------


def day_bounds(day: date) -> tuple[int, int]:
    """Unix seconds of the day's first instant and of the next day's, in UTC."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    return start, start + 86_400


def _where(day: date) -> str:
    # Absolute unix bounds, so the server's time zone setting cannot move the day.
    start, end = day_bounds(day)
    return f"timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})"


# Analytics Engine samples at high volume, so every count is SUM(_sample_interval).
def kinds_sql(day: date) -> str:
    return (f"SELECT blob2 AS kind, SUM(_sample_interval) AS responses FROM {DATASET} "
            f"WHERE {_where(day)} GROUP BY kind ORDER BY kind FORMAT JSON")


def counts_sql(day: date) -> str:
    return ("SELECT blob1 AS route, blob2 AS kind, blob3 AS lang, blob4 AS country, blob5 AS referrer, "
            f"double1 AS status, SUM(_sample_interval) AS responses FROM {DATASET} WHERE {_where(day)} "
            "GROUP BY route, kind, lang, country, referrer, status "
            f"ORDER BY responses DESC LIMIT {MAX_ROWS} FORMAT JSON")


def feeds_sql(day: date) -> str:
    # blob7 is the feed file and double2 the subscriber count a reader stated
    # (0 when it stated none); the largest of the day is the figure kept.
    return (f"SELECT blob7 AS feed, SUM(_sample_interval) AS responses, MAX(double2) AS subscribers "
            f"FROM {DATASET} WHERE blob2 = 'feed' AND {_where(day)} GROUP BY feed ORDER BY feed FORMAT JSON")


# -- the API ------------------------------------------------------------------


def _status(resp: Any) -> int:
    return int(getattr(resp, "status_code", 0) or 0)


def _body(resp: Any) -> str:
    try:
        return re.sub(r"\s+", " ", str(resp.text))[:300]
    except Exception:
        return "(no body)"


def query(http: Any, account: str, token: str, sql: str, timeout: float = 60) -> list[dict[str, Any]]:
    """The rows of one SQL API answer. Raises QueryError for anything else.

    The token travels only in the Authorization header, never in a URL, so
    no error message or log line can carry it."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": config.USER_AGENT, "Content-Type": "text/plain"}
    try:
        resp = http.post(SQL_URL.format(account=account), data=sql.encode("utf-8"), headers=headers, timeout=timeout)
    except Exception as exc:
        raise QueryError(f"request failed ({type(exc).__name__}): {str(exc)[:200]}") from None
    status = _status(resp)
    if not 200 <= status < 300:
        raise QueryError(f"HTTP {status}: {_body(resp)}")
    try:
        rows = resp.json()["data"]
    except Exception:
        raise QueryError(f"HTTP {status} without rows: {_body(resp)}") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise QueryError(f"HTTP {status}: data is not a list of rows")
    return rows


def _number(value: Any) -> float:
    """A count as the API gives it. JSON output quotes 64-bit integers, so
    "12" and 12 are both read; anything else is 0."""
    if isinstance(value, bool):
        return 0.0
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n and n not in (float("inf"), float("-inf")) and n >= 0 else 0.0


def _count(value: Any) -> int:
    return int(round(_number(value)))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


# -- one day ------------------------------------------------------------------


@dataclass
class Day:
    day: date
    kinds: dict[str, int] = field(default_factory=dict)
    counts: dict[tuple[str, str, str, str, str, int], int] = field(default_factory=dict)
    feeds: dict[str, tuple[int, int]] = field(default_factory=dict)  # feed -> (fetches, most subscribers)
    truncated: bool = False

    @property
    def total(self) -> int:
        return sum(self.kinds.values())


def clean_kind(value: Any) -> str:
    kind = _text(value)
    return kind if kind in KINDS else "other"


def clean_count_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, int]:
    """(route, kind, lang, country, referrer, status), each in the shape the Worker writes."""
    route = _text(row.get("route"))
    lang = _text(row.get("lang"))
    country = _text(row.get("country"))
    referrer = _text(row.get("referrer"))
    status = _count(row.get("status"))
    return (
        route if ROUTE_RE.match(route) else "other",
        clean_kind(row.get("kind")),
        lang if lang in ("en", "fr") else "",
        country if COUNTRY_RE.match(country) else "",
        referrer if HOST_RE.match(referrer) else "",
        status if 100 <= status <= 599 else 0,
    )


def build_day(day: date, kinds: list[dict], counts: list[dict], feeds: list[dict]) -> Day:
    """One day from the three answers. Rows that clean to the same key are added together."""
    out = Day(day)
    for row in kinds:
        kind = clean_kind(row.get("kind"))
        out.kinds[kind] = out.kinds.get(kind, 0) + _count(row.get("responses"))
    for row in counts:
        key = clean_count_key(row)
        out.counts[key] = out.counts.get(key, 0) + _count(row.get("responses"))
    out.truncated = len(counts) >= MAX_ROWS
    for row in feeds:
        name = _text(row.get("feed"))
        name = name if len(name) <= 120 and FEED_RE.match(name) else ""
        fetches, most = out.feeds.get(name, (0, 0))
        out.feeds[name] = (fetches + _count(row.get("responses")), max(most, _count(row.get("subscribers"))))
    return out


def day_rows(d: Day) -> list[dict[str, Any]]:
    """The day file's rows: the total, the total per kind, every grouped count, every feed."""
    stamp = d.day.isoformat()
    blank = dict.fromkeys(DAY_HEADER, "")
    rows: list[dict[str, Any]] = [dict(blank, date=stamp, section="total", responses=d.total)]
    for kind in sorted(d.kinds):
        rows.append(dict(blank, date=stamp, section="kind", kind=kind, responses=d.kinds[kind]))
    for (route, kind, lang, country, referrer, status), n in sorted(d.counts.items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append(dict(blank, date=stamp, section="count", route=route, kind=kind, lang=lang, country=country,
                         referrer=referrer, status=status or "", responses=n))
    for name in sorted(d.feeds):
        fetches, most = d.feeds[name]
        rows.append(dict(blank, date=stamp, section="feed", route="/data/feeds/:file", kind="feed", feed=name,
                         responses=fetches, subscribers=most))
    return rows


def top_routes(d: Day, n: int = TOP_ROUTES) -> str:
    """The n route templates with the most responses below status 400, as short text."""
    by_route: dict[str, int] = {}
    for (route, _kind, _lang, _country, _referrer, status), count in d.counts.items():
        if 0 < status < 400:
            by_route[route] = by_route.get(route, 0) + count
    best = sorted(by_route.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return "; ".join(f"{route} {count}" for route, count in best)


def summary_row(d: Day, followers: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(SUMMARY_HEADER, 0)
    row["date"] = d.day.isoformat()
    row["responses"] = d.total
    for kind, n in d.kinds.items():
        row[KIND_COLUMNS.get(kind, "other")] += n
    # A person who follows two feeds counts twice, and a feed read through two
    # services counts only the larger figure; the column says what readers stated.
    row["feed_subscribers"] = sum(most for name, (_fetches, most) in d.feeds.items() if name)
    row["bluesky_followers"] = "" if followers is None else followers
    row["top_routes"] = top_routes(d)
    return row


# -- files --------------------------------------------------------------------


def _write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    """Write through a temporary file, so a run stopped part way never leaves half a file to upload."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(buf.getvalue(), encoding="utf-8")
    partial.replace(path)


def write_day(folder: Path, d: Day) -> Path:
    path = folder / f"{d.day.isoformat()}.csv"
    _write_csv(path, DAY_HEADER, day_rows(d))
    return path


def read_summary(path: Path) -> list[dict[str, str]]:
    """The summary's rows; none when the file does not exist (the first night).

    Raises SummaryError when the file exists but is empty, unreadable, has a
    column this code does not know, or a row without a date: replacing it
    then would lose the history it holds, so the run fails instead."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SummaryError(f"{path.name} cannot be read: {exc}") from None
    if not text.strip():
        raise SummaryError(f"{path.name} is empty")
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    unknown = [c for c in header if c not in SUMMARY_HEADER]
    if "date" not in header or unknown:
        raise SummaryError(f"{path.name} has an unexpected header: {','.join(header)[:200]}")
    rows = []
    for row in reader:
        stamp = row.get("date") or ""
        try:
            ok = None not in row and bool(DATE_RE.match(stamp)) and date.fromisoformat(stamp) is not None
        except ValueError:
            ok = False
        if not ok:
            raise SummaryError(f"{path.name} has a malformed row near {stamp[:20]!r}")
        rows.append({k: (row.get(k) or "") for k in SUMMARY_HEADER})
    return rows


def merge_summary(rows: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows with each new row added, or put in place of the row for its date, sorted by date.

    A follower count is a reading taken on the night, so a day rolled up
    again without one keeps the count it had."""
    by_date = {r["date"]: r for r in rows}
    for row in new:
        old = by_date.get(row["date"])
        merged = dict(row)
        if old and merged.get("bluesky_followers") in ("", None):
            merged["bluesky_followers"] = old.get("bluesky_followers", "")
        by_date[row["date"]] = merged
    return [by_date[k] for k in sorted(by_date)]


def update_summary(path: Path, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = merge_summary(read_summary(path), new)
    _write_csv(path, SUMMARY_HEADER, rows)
    return rows


# -- Bluesky ------------------------------------------------------------------


def parse_followers(payload: Any) -> int | None:
    """followersCount from a getProfile answer, when it is a whole number."""
    n = payload.get("followersCount") if isinstance(payload, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return None
    return n


def bluesky_handle(env: Mapping[str, str]) -> str:
    """BSKY_HANDLE, else the site's host name: the account's handle is its domain."""
    handle = (env.get("BSKY_HANDLE") or "").strip().lstrip("@")
    if handle:
        return handle
    host = urlsplit(config.SITE_URL).hostname or ""
    return "" if host.endswith(".example") else host


def bluesky_followers(http: Any, handle: str, timeout: float = 30) -> int | None:
    """The account's follower count, or None. The endpoint is public, so no token is sent."""
    if not handle:
        return None
    url = BSKY_PROFILE_URL + "?" + urlencode({"actor": handle})
    try:
        resp = http.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
        status = _status(resp)
        if not 200 <= status < 300:
            log.warning("views: Bluesky profile HTTP %s; no follower count: %s", status, _body(resp))
            return None
        n = parse_followers(resp.json())
    except Exception as exc:
        log.warning("views: Bluesky profile not readable (%s); no follower count", type(exc).__name__)
        return None
    if n is None:
        log.warning("views: the Bluesky profile carries no follower count")
    return n


# -- the run ------------------------------------------------------------------


def previous_day(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date() - timedelta(days=1)


def days_to_roll(held: list[str], yesterday: date) -> list[date]:
    """Every day after the newest one held, back to the retention limit, and
    always yesterday (rolled up again in place on a re-run)."""
    oldest = yesterday - timedelta(days=RETENTION_DAYS - 1)
    newest = max((date.fromisoformat(d) for d in held), default=None)
    start = oldest if newest is None else max(newest + timedelta(days=1), oldest)
    start = min(start, yesterday)
    return [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]


def check_day(day: date, now: datetime | None = None) -> str | None:
    """Why a day asked for by hand cannot be rolled up, or None."""
    yesterday = previous_day(now)
    if day > yesterday:
        return f"{day} is not over yet (UTC)"
    if day < yesterday - timedelta(days=RETENTION_DAYS - 1):
        return f"{day} is older than the {RETENTION_DAYS} days Analytics Engine keeps"
    return None


def roll_day(http: Any, account: str, token: str, day: date) -> Day | None:
    """One day's counts, or None when the dataset holds no point for it."""
    kinds = query(http, account, token, kinds_sql(day))
    if sum(_count(r.get("responses")) for r in kinds) == 0:
        return None
    d = build_day(day, kinds, query(http, account, token, counts_sql(day)), query(http, account, token, feeds_sql(day)))
    if d.truncated:
        log.warning("views: %s has more than %d grouped rows; the smallest are left out of the day file "
                    "(the totals are exact)", day, MAX_ROWS)
    return d


def run(out_dir: Path | None = None, *, day: date | None = None, env: Mapping[str, str] | None = None,
        session: Any | None = None, now: datetime | None = None) -> str:
    """Roll up the days due (or one day given by hand). Returns "rolled up",
    "no data" (no day had a data point), "no token" or "failed"; never raises."""
    try:
        return _run(out_dir, day=day, env=env, session=session, now=now)
    except Exception as exc:
        log.error("views: roll-up failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return "failed"


def _run(out_dir: Path | None, *, day: date | None, env: Mapping[str, str] | None, session: Any | None,
         now: datetime | None) -> str:
    source = os.environ if env is None else env
    folder = out_dir or (config.OUT_DIR / "views")
    folder.mkdir(parents=True, exist_ok=True)
    # Cleared first, so the workflow never uploads days listed by an earlier run.
    (folder / ROLLED_UP).write_text("", encoding="utf-8")
    token = (source.get(TOKEN_ENV) or "").strip()
    if not token:
        log.info("no analytics token; nothing rolled up")
        return "no token"
    account = (source.get(ACCOUNT_ENV) or "").strip()
    if not ACCOUNT_RE.match(account):
        log.error("views: %s is missing or malformed; nothing rolled up", ACCOUNT_ENV)
        return "failed"
    if day is not None:
        problem = check_day(day, now)
        if problem:
            log.error("views: %s; nothing rolled up", problem)
            return "failed"

    try:
        held = read_summary(folder / SUMMARY)
    except SummaryError as exc:
        log.error("views: %s; nothing rolled up, and the summary is left as it is", exc)
        return "failed"
    yesterday = previous_day(now)
    days = [day] if day is not None else days_to_roll([r["date"] for r in held], yesterday)

    if session is None:
        import requests
        http: Any = requests.Session()
    else:
        http = session
    try:
        rolled: list[Day] = []
        for d in days:
            try:
                result = roll_day(http, account, token, d)
            except QueryError as exc:
                log.error("views: the SQL API failed for %s: %s", d, exc)
                return "failed"
            if result is None:
                log.info("views: no data points for %s; nothing written for it", d)
                continue
            rolled.append(result)
        followers = bluesky_followers(http, bluesky_handle(source)) if any(d.day == yesterday for d in rolled) else None
    finally:
        if session is None:
            http.close()

    if not rolled:
        log.info("views: no data points in %d day(s) asked; nothing rolled up", len(days))
        return "no data"
    for d in rolled:
        path = write_day(folder, d)
        log.info("views: %s: %d responses, %d grouped rows, %d feeds -> %s", d.day, d.total, len(d.counts),
                 len(d.feeds), path.name)
    update_summary(folder / SUMMARY, [summary_row(d, followers if d.day == yesterday else None) for d in rolled])
    (folder / ROLLED_UP).write_text("".join(f"{d.day.isoformat()}\n" for d in rolled), encoding="utf-8")
    return "rolled up"
