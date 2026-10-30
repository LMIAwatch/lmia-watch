"""Google Search Console figures for the audience record, kept in R2.

Why: Search Console keeps 16 months of search data and no longer, and the
growth record must outlive that window. Once a night, when the repository
secret GSC_SERVICE_ACCOUNT_JSON exists, this asks the Search Analytics API
for every day after the newest one already stored and appends one row per
day to `search_console.csv`: clicks, impressions, click-through rate,
average position, and the day's top 50 queries. The workflow keeps the file
as `views/search_console.csv` in R2.

The secret is the JSON key of a Google service account that has been added
as a user of the Search Console property (docs/search-engines.md section 6
says how). The property defaults to the domain property of the site's host
(`sc-domain:lmiawatch.ca`); the variable GSC_SITE overrides it. Without the
secret nothing is asked and the outcome is "no credentials".

Signing: the API takes an OAuth access token, which Google exchanges for a
JWT signed with the service account's RSA key (RS256). The key is loaded and
the JWT signed with the `cryptography` package (PKCS #1 v1.5 padding over
SHA-256). The key is read from the secret, used, and never written or
logged.

Only data marked final is asked for (Search Console's dataState "final"), so
a stored day never changes later; the newest two or three days arrive on
later nights. A day with no impressions has no row in Search Console's
answer and none here. At most MAX_DAYS days are fetched a night (the first
night could find 16 months); the next night goes on from there.

What a row can hold: Search Console's figures and the query texts it
reports. Google leaves out queries made by very few people, and the file is
not published.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from . import config

log = logging.getLogger(__name__)

SECRET_ENV = "GSC_SERVICE_ACCOUNT_JSON"
SITE_ENV = "GSC_SITE"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
QUERY_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"

FILE = "search_console.csv"
HEADER = ["date", "clicks", "impressions", "ctr", "position", "top_queries"]
# Search Console keeps 16 months.
HISTORY_DAYS = 486
MAX_DAYS = 120
TOP_QUERIES = 50
QUERY_MAX_CHARS = 200

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

NO_CREDENTIALS = "no credentials"
UP_TO_DATE = "up to date"
FAILED = "failed"


class SearchConsoleError(Exception):
    """An answer from Google that is not what was asked for."""


class FileError(Exception):
    """The stored file exists but cannot be read safely, so it is never replaced."""


# -- RS256 -------------------------------------------------------------------


def load_key(pem: str) -> Any:
    """The RSA private key from a PEM string (Google issues PKCS #8). Raises
    ValueError, never echoing the key."""
    try:
        from cryptography.exceptions import UnsupportedAlgorithm
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise ValueError("the cryptography package is not installed (pip install -e ./pipeline)") from None
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise ValueError("the key is not a readable, unencrypted PEM private key") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("the key is not an RSA key")
    if key.key_size < 2048:
        raise ValueError("the RSA key is shorter than 2048 bits")
    return key


def rs256(message: bytes, key: Any) -> bytes:
    """RSASSA-PKCS1-v1_5 signature with SHA-256, the JWT algorithm RS256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    return key.sign(message, padding.PKCS1v15(), hashes.SHA256())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# -- the service account -------------------------------------------------------


@dataclass(frozen=True, repr=False)
class Account:
    email: str
    key_id: str
    key: Any  # cryptography's RSAPrivateKey

    def __repr__(self) -> str:  # keeps the key out of any log line or traceback
        return f"Account({self.email})"


def parse_account(text: str) -> Account:
    """The service account from the secret's JSON. Raises ValueError, never echoing the key."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(f"{SECRET_ENV} is not JSON") from None
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise ValueError(f"{SECRET_ENV} is not a service account key")
    email, key = data.get("client_email"), data.get("private_key")
    if not isinstance(email, str) or "@" not in email or not isinstance(key, str):
        raise ValueError(f"{SECRET_ENV} lacks client_email or private_key")
    key_id = data.get("private_key_id")
    return Account(email.strip(), key_id if isinstance(key_id, str) else "", load_key(key))


def assertion(account: Account, now: int) -> str:
    """The signed JWT Google exchanges for an access token (an hour's validity)."""
    header = {"alg": "RS256", "typ": "JWT"}
    if account.key_id:
        header["kid"] = account.key_id
    claims = {"iss": account.email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
    signing_input = (b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
                     + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    return signing_input + "." + b64url(rs256(signing_input.encode("ascii"), account.key))


def _status(resp: Any) -> int:
    return int(getattr(resp, "status_code", 0) or 0)


def _body(resp: Any) -> str:
    try:
        return re.sub(r"\s+", " ", str(resp.text))[:300]
    except Exception:
        return "(no body)"


def access_token(http: Any, account: Account, now: int, timeout: float = 30) -> str:
    """An access token for the read-only Search Console scope. Raises SearchConsoleError."""
    try:
        resp = http.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                          "assertion": assertion(account, now)},
                         headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
    except Exception as exc:
        raise SearchConsoleError(f"token request failed ({type(exc).__name__})") from None
    status = _status(resp)
    if not 200 <= status < 300:
        # Google's error body names the problem (invalid_grant, a disabled key) and never echoes the assertion.
        raise SearchConsoleError(f"token request HTTP {status}: {_body(resp)}")
    try:
        token = resp.json()["access_token"]
    except Exception:
        raise SearchConsoleError(f"token answer HTTP {status} without a token") from None
    if not isinstance(token, str) or not token:
        raise SearchConsoleError("token answer without a token")
    return token


def site_property(env: Mapping[str, str]) -> str:
    """GSC_SITE, else the domain property of the site's host; "" when neither is known."""
    explicit = (env.get(SITE_ENV) or "").strip()
    if explicit:
        return explicit
    host = urlsplit(config.SITE_URL).hostname or ""
    return "" if not host or host.endswith(".example") else f"sc-domain:{host}"


def search(http: Any, token: str, site: str, body: dict[str, Any], timeout: float = 60) -> list[dict[str, Any]]:
    """The rows of one Search Analytics answer. Raises SearchConsoleError."""
    url = QUERY_URL.format(site=quote(site, safe=""))
    try:
        resp = http.post(url, json=body, headers={"Authorization": f"Bearer {token}", "User-Agent": config.USER_AGENT},
                         timeout=timeout)
    except Exception as exc:
        raise SearchConsoleError(f"query failed ({type(exc).__name__})") from None
    status = _status(resp)
    if status == 403:
        raise SearchConsoleError(f"HTTP 403: the service account cannot read {site}; add it as a user of the property")
    if not 200 <= status < 300:
        raise SearchConsoleError(f"query HTTP {status}: {_body(resp)}")
    try:
        payload = resp.json()
    except Exception:
        raise SearchConsoleError(f"query HTTP {status} without JSON") from None
    if not isinstance(payload, dict):
        raise SearchConsoleError("query answer is not an object")
    rows = payload.get("rows", [])  # no rows key: no data in the range
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise SearchConsoleError("query answer rows are not a list of objects")
    return rows


def _figure(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n and n not in (float("inf"), float("-inf")) and n >= 0 else 0.0


def _key(row: dict[str, Any]) -> str:
    keys = row.get("keys")
    return keys[0] if isinstance(keys, list) and keys and isinstance(keys[0], str) else ""


def day_rows(rows: list[dict[str, Any]], start: date, end: date) -> dict[str, dict[str, Any]]:
    """The answer grouped by date: date -> figures, for dates inside the range asked."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        stamp = _key(row)
        try:
            day = date.fromisoformat(stamp) if DATE_RE.match(stamp) else None
        except ValueError:
            day = None
        if day is None or not start <= day <= end:
            continue
        out[stamp] = {
            "date": stamp,
            "clicks": int(round(_figure(row.get("clicks")))),
            "impressions": int(round(_figure(row.get("impressions")))),
            "ctr": round(_figure(row.get("ctr")), 4),
            "position": round(_figure(row.get("position")), 2),
        }
    return out


def top_queries(rows: list[dict[str, Any]]) -> str:
    """The day's queries as compact JSON: [[query, clicks, impressions, position], ...], most clicks first."""
    out = []
    for row in rows:
        text = CONTROL_RE.sub(" ", _key(row)).strip()[:QUERY_MAX_CHARS]
        if not text:
            continue
        out.append([text, int(round(_figure(row.get("clicks")))), int(round(_figure(row.get("impressions")))),
                    round(_figure(row.get("position")), 1)])
    out.sort(key=lambda q: (-q[1], -q[2], q[0]))
    return json.dumps(out[:TOP_QUERIES], separators=(",", ":"), ensure_ascii=False)


# -- the file ------------------------------------------------------------------


def read_file(path: Path) -> list[dict[str, str]]:
    """The stored rows; none when the file does not exist (the first night).

    Raises FileError when the file exists but is empty, unreadable, has a
    header this code does not know, or a row without a date."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FileError(f"{path.name} cannot be read: {exc}") from None
    if not text.strip():
        raise FileError(f"{path.name} is empty")
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    if header != HEADER:
        raise FileError(f"{path.name} has an unexpected header: {','.join(header)[:200]}")
    rows = []
    for row in reader:
        stamp = row.get("date") or ""
        try:
            ok = None not in row and bool(DATE_RE.match(stamp)) and date.fromisoformat(stamp) is not None
        except ValueError:
            ok = False
        if not ok:
            raise FileError(f"{path.name} has a malformed row near {stamp[:20]!r}")
        rows.append({k: (row.get(k) or "") for k in HEADER})
    return rows


def write_file(path: Path, rows: list[dict[str, Any]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda r: r["date"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(buf.getvalue(), encoding="utf-8")
    partial.replace(path)


# -- the run -------------------------------------------------------------------


def date_range(held: list[dict[str, str]], today: date) -> tuple[date, date]:
    """From the day after the newest stored (or 16 months back) to yesterday, UTC."""
    end = today - timedelta(days=1)
    oldest = today - timedelta(days=HISTORY_DAYS)
    newest = max((date.fromisoformat(r["date"]) for r in held), default=None)
    start = oldest if newest is None else max(newest + timedelta(days=1), oldest)
    return start, end


def run(out_dir: Path | None = None, *, env: Mapping[str, str] | None = None, session: Any | None = None,
        now: datetime | None = None) -> str:
    """Import the days due. Returns "imported <n> days", "up to date", "no credentials" or "failed"; never raises."""
    try:
        return _run(out_dir, env=env, session=session, now=now)
    except Exception as exc:
        log.error("search console: import failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return FAILED


def _run(out_dir: Path | None, *, env: Mapping[str, str] | None, session: Any | None, now: datetime | None) -> str:
    source = os.environ if env is None else env
    folder = out_dir or (config.OUT_DIR / "search_console")
    folder.mkdir(parents=True, exist_ok=True)
    secret = (source.get(SECRET_ENV) or "").strip()
    if not secret:
        log.info("search console: no credentials; nothing imported")
        return NO_CREDENTIALS
    try:
        account = parse_account(secret)
    except ValueError as exc:
        log.error("search console: %s; nothing imported", exc)
        return FAILED
    site = site_property(source)
    if not site:
        log.error("search console: no property to read (set %s); nothing imported", SITE_ENV)
        return FAILED
    try:
        held = read_file(folder / FILE)
    except FileError as exc:
        log.error("search console: %s; nothing imported, and the file is left as it is", exc)
        return FAILED

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start, end = date_range(held, current.date())
    if start > end:
        return UP_TO_DATE

    if session is None:
        import requests
        http: Any = requests.Session()
    else:
        http = session
    try:
        token = access_token(http, account, int(current.timestamp()))
        base = {"type": "web", "dataState": "final"}
        days = day_rows(search(http, token, site, {**base, "startDate": start.isoformat(), "endDate": end.isoformat(),
                                                   "dimensions": ["date"], "rowLimit": 25000}), start, end)
        new = []
        for stamp in sorted(days)[:MAX_DAYS]:
            queries = search(http, token, site, {**base, "startDate": stamp, "endDate": stamp,
                                                 "dimensions": ["query"], "rowLimit": TOP_QUERIES})
            new.append({**days[stamp], "top_queries": top_queries(queries)})
    except SearchConsoleError as exc:
        log.error("search console: %s; nothing imported", exc)
        return FAILED
    finally:
        if session is None:
            http.close()

    if not new:
        log.info("search console: no final data between %s and %s yet", start, end)
        return UP_TO_DATE
    write_file(folder / FILE, held + new)
    if len(days) > MAX_DAYS:
        log.info("search console: %d days due; the first %d imported, the rest follow next run", len(days), MAX_DAYS)
    log.info("search console: %d days imported, %s to %s", len(new), new[0]["date"], new[-1]["date"])
    return f"imported {len(new)} day{'s' if len(new) != 1 else ''}"
