"""Daily X post: a factual digest of the postings first seen on the latest Job Bank pass.

collect, screen, compose and draw_card are shared with bluesky.py, which
posts the same digest and card to Bluesky.

Why OAuth 1.0a user context: the job posts as one account, its own. The four
values from the developer console never expire, so they sit in four repository
secrets and nothing has to be refreshed or written back between runs. OAuth 2.0
user tokens last two hours and need a refresh token stored somewhere the next
run can update, which a scheduled workflow cannot do with its own secrets.

Why it never raises: the post is optional and the data refresh is not. Every
failure (missing credentials, a network error, an HTTP error, a missing
library) is logged and reported as an outcome, so the workflow carries on to
save the database.

Why the meta table: the date of the Job Bank pass last posted is stored there,
so a re-run of a night, or a second run on the same data, posts nothing.

Why the post is looked for after a server error: X can answer 5xx, or not at
all, to a post it has published (it did on 2026-10-24). Calling that a failure
leaves the date unrecorded, and a re-run would post the digest twice. So the
account's newest posts are read once and the answer decides; when they cannot
be read either, the date is recorded and the outcome is "unverified".
"""

from __future__ import annotations

import html
import logging
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config
from .db import get_meta, set_meta
from .social_card import CARD_EMPLOYERS, CardData, CardEmployer, alt_text, render_card

log = logging.getLogger(__name__)

POST_URL = "https://api.x.com/2/tweets"
# Simple upload (images only, multipart with raw bytes) and the alt-text call.
UPLOAD_URL = "https://api.x.com/2/media/upload"
METADATA_URL = "https://api.x.com/2/media/metadata"
# Read only after a post X answered 5xx or not at all, to see whether it went out.
ME_URL = "https://api.x.com/2/users/me"
TIMELINE_URL = "https://api.x.com/2/users/{id}/tweets"
LOOKUP_COUNT = 5  # the endpoint's minimum; the post is the newest unless something else posted since
# The post can take a moment to show on the account's timeline after X's own
# timeout, and a lookup that misses it would read as a failure.
LOOKUP_DELAY = 10.0
# send_post's answer when the post's fate is unknown: X answered 5xx or not at
# all and the account's posts could not be read. The date is recorded anyway.
UNVERIFIED = "unverified"
TCO_RE = re.compile(r"https?://t\.co/\S*", re.I)
MAX_CHARS = 280
# X wraps every link in t.co and counts it as this many characters, whatever its length.
URL_CHARS = 23
TOP_EMPLOYERS = 3
# A normal day brings well under this many new postings. A pass that sees more
# is a rebuild (a fresh or restored database re-reading the whole feed), and a
# digest of it would read as one day's applications when it is the backlog.
MAX_NEW_POSTINGS = 500
# The pass runs at 00:00 UTC, which is the evening before across Canada, so
# the post carries the Eastern-time date of the day readers just lived through.
LOCAL_TZ = ZoneInfo("America/Toronto")
# A previous pass further back than this means a night was missed, and the
# postings are "since" that date rather than one day's.
GAP_HOURS = 36
WEEK_DAYS = 7
LAST_POST_KEY = "x_last_post_date"
LAST_POST_ID_KEY = "x_last_post_id"
CREDENTIAL_ENV = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")

# A scheme URL, or a bare domain that X would turn into a link (an employer
# named "Example.com Inc" gets one). Overcounting a false match only drops a
# line early; undercounting would make X refuse the post.
URL_RE = re.compile(r"https?://\S+|(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?", re.I)
# @name, #word and $TICKER at the start of a word become mentions, hashtags and
# cashtags on X. An automated account must not mention people unasked, so a
# space goes after the sign. A hashtag or cashtag needs a letter; "#1" stays.
SIGIL_RE = re.compile(r"(?<![A-Za-z0-9_])(?:[@\uFF20](?=\w)|[#$\uFF03](?=\w*[^\W\d_]))")


@dataclass(frozen=True, repr=False)
class Credentials:
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str

    def __repr__(self) -> str:  # keep secrets out of any log line or traceback
        return "Credentials(****)"


@dataclass
class EmployerLine:
    name: str
    city: str | None
    province: str | None
    positions: int


@dataclass
class Digest:
    data_date: str              # UTC date of the Job Bank pass, from jobbank_last_run
    postings: int               # new postings with the LMIA requested flag
    positions: int              # sum of the vacancies the postings state
    positions_known: int        # postings whose page gave a vacancy count
    provinces: list[str] = field(default_factory=list)
    employers: list[EmployerLine] = field(default_factory=list)       # the text's top employers
    first_pass: bool = False    # no posting predates this pass, so all of them look new
    province_counts: dict[str, int] = field(default_factory=dict)     # for the card
    top_employers: list[EmployerLine] = field(default_factory=list)   # the card's longer list
    since_date: str | None = None   # set when the previous pass was more than GAP_HOURS earlier
    week_postings: int = 0          # posted on Job Bank in the last 7 days, by its own posting date
    week_positions: int = 0
    week_known: int = 0
    # New postings open to international candidates with no LMIA requested
    # (sources/jobbank_intl.digest_count); None leaves the line out.
    intl_no_lmia: int | None = None


PROVINCE_RE = re.compile(r"\b(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b")


def province_code(value: str | None) -> str | None:
    """The two-letter code inside a province field, or None. A field can carry
    an address fragment when a posting's location was oddly formatted."""
    m = PROVINCE_RE.search((value or "").upper())
    return m.group(1) if m else None


# -- dates ------------------------------------------------------------------


def _parse(stamp: str) -> datetime:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_date(stamp: str) -> str:
    """The Eastern-time date of a UTC stamp."""
    return _parse(stamp).astimezone(LOCAL_TZ).date().isoformat()


# -- composition ------------------------------------------------------------


def x_length(text: str) -> int:
    """Length as X counts it: links are 23, most scripts 1 per character, others 2."""
    text = unicodedata.normalize("NFC", text)
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += _weighted(text[pos:m.start()]) + URL_CHARS
        pos = m.end()
    return total + _weighted(text[pos:])


def _weighted(text: str) -> int:
    # Ranges X weighs as one character (its twitter-text v3 configuration);
    # everything else, CJK and emoji included, counts as two.
    n = 0
    for ch in text:
        cp = ord(ch)
        if cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247:
            n += 1
        else:
            n += 2
    return n


def search_link() -> str:
    return f"{config.SITE_URL.rstrip('/')}/search?date=7d"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _defuse(name: str) -> str:
    return SIGIL_RE.sub(lambda m: m.group(0) + " ", re.sub(r"\s+", " ", name).strip())


def _lead(d: Digest) -> str:
    when = f"since {d.since_date}" if d.since_date else d.data_date
    return f'Newly flagged "LMIA requested" on Job Bank, {when}'


def _card_title(d: Digest) -> str:
    return f"Job Bank, since {d.since_date}" if d.since_date else f"Job Bank, {d.data_date}"


def _positions_line(positions: int, known: int, postings: int) -> str | None:
    # Vacancy counts come from posting pages, fetched within a nightly budget, so
    # a count missing from some postings makes the total a floor. With fewer than
    # half the postings counted the floor understates the day too much to print.
    if not known or known * 2 < postings:
        return None
    prefix = "" if known == postings else "at least "
    return f"{prefix}{_plural(positions, 'position')}"


def _headline(d: Digest) -> str:
    text = f"{_lead(d)}: {_plural(d.postings, 'posting')}"
    line = _positions_line(d.positions, d.positions_known, d.postings)
    if line:
        text += f", {line}"
    return text + "."


def _employer_line(e: EmployerLine) -> str:
    place = " ".join(p for p in (e.city, e.province) if p)
    name = _defuse(e.name)
    label = f"{name}, {_defuse(place)}" if place else name
    return f"{label}: {e.positions:,}"


def _intl_line(d: Digest) -> str | None:
    if not d.intl_no_lmia:
        return None
    return f"{_plural(d.intl_no_lmia, 'new posting')} open to international candidates, no LMIA"


def _join(head: str, provinces: str | None, employers: list[str], link: str | None, intl_line: str | None = None) -> str:
    lines = [head]
    if provinces:
        lines.append(provinces)
    if intl_line:
        lines.append(intl_line)
    if employers:
        lines.append("Most positions:")
        lines.extend(employers)
    if link:
        lines.append(link)
    return "\n".join(lines)


def compose(d: Digest, *, link: str | None, limit: int = MAX_CHARS,
            measure: Callable[[str], int] = x_length) -> str:
    """The post text. When it runs long, employers go from the end of the list first, then the line on
    postings open to international candidates, then the province line.

    measure is the platform's own length rule (X's by default; bluesky.py passes Bluesky's)."""
    head = _headline(d)
    provinces = f"In {', '.join(d.provinces)}" if d.provinces else None
    employers = [_employer_line(e) for e in d.employers]
    intl_line = _intl_line(d)
    rungs = [(provinces, intl_line, employers[:n]) for n in range(len(employers), -1, -1)]
    rungs.append((provinces, None, []))
    rungs.append((None, None, []))
    for prov_line, intl, emp_lines in rungs:
        text = _join(head, prov_line, emp_lines, link, intl)
        if measure(text) <= limit:
            return text
    # The headline holds a date and two numbers, so this is unreachable at 280.
    return _join(head, None, [], link)


# -- data -------------------------------------------------------------------


def collect(conn: sqlite3.Connection) -> Digest | None:
    """Postings first seen since the previous completed Job Bank pass; None before any pass.

    jobbank.run stamps first_seen and jobbank_last_run with the same value and
    writes jobbank_last_run only when a pass completes, keeping the one before as
    jobbank_prev_run. Counting from that previous complete pass takes in what a
    sweep that stopped short stored in between, so a broken night rolls into the
    next post. A database from before jobbank_prev_run counts this pass alone.
    """
    stamp = get_meta(conn, "jobbank_last_run")
    if not stamp:
        return None
    start = get_meta(conn, "jobbank_prev_run")
    if start and start >= stamp:
        start = None
    columns = "SELECT posting_id, employer_id, employer_raw, city, province, vacancies FROM jobbank_postings "
    if start:
        rows = conn.execute(columns + "WHERE first_seen > ? AND first_seen <= ? AND flag_first = 'requested'",
                            (start, stamp)).fetchall()
        earlier = conn.execute("SELECT 1 FROM jobbank_postings WHERE first_seen <= ? LIMIT 1", (start,)).fetchone()
        prev = start
    else:
        rows = conn.execute(columns + "WHERE first_seen = ? AND flag_first = 'requested'", (stamp,)).fetchall()
        earlier = conn.execute("SELECT 1 FROM jobbank_postings WHERE first_seen < ? LIMIT 1", (stamp,)).fetchone()
        # Every posting a pass sees gets last_seen = its stamp, so the latest earlier
        # last_seen is the previous pass, whether or not it found anything new.
        prev = conn.execute("SELECT MAX(last_seen) FROM jobbank_postings WHERE last_seen < ?", (stamp,)).fetchone()[0]
    since = None
    if prev and (_parse(stamp) - _parse(prev)) > timedelta(hours=GAP_HOURS):
        since = local_date(prev)
    day = local_date(stamp)
    # The flag appears while a posting is live, often weeks after its posting
    # date, so the week is counted by first sightings of the flag. A rebuild
    # pass inside the window (every posting "new" at once) is left out.
    window = (_parse(stamp) - timedelta(days=WEEK_DAYS)).isoformat().replace("+00:00", "Z")
    seen = conn.execute(
        "SELECT first_seen, vacancies FROM jobbank_postings WHERE flag_first = 'requested' AND first_seen > ? AND first_seen <= ?",
        (window, stamp),
    ).fetchall()
    per_pass: dict[str, int] = defaultdict(int)
    for r in seen:
        per_pass[r["first_seen"]] += 1
    bulk = {s for s, n in per_pass.items() if n > MAX_NEW_POSTINGS}
    week = [r for r in seen if r["first_seen"] not in bulk]
    week_known = [r["vacancies"] for r in week if r["vacancies"] is not None]

    known = [r for r in rows if r["vacancies"] is not None]
    province_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        code = province_code(r["province"])
        if code:
            province_counts[code] += 1
    provinces = sorted(province_counts)

    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in known:
        groups[r["employer_id"]].append(r)
    employers: list[EmployerLine] = []
    for group in groups.values():
        positions = sum(int(r["vacancies"]) for r in group)
        if positions <= 0:
            continue
        # One employer can post in several places; name the place with the most vacancies.
        lead = max(group, key=lambda r: (int(r["vacancies"]), r["posting_id"]))
        employers.append(EmployerLine(lead["employer_raw"], lead["city"], province_code(lead["province"]), positions))
    employers.sort(key=lambda e: (-e.positions, e.name.casefold()))

    return Digest(
        data_date=day,
        postings=len(rows),
        positions=sum(int(r["vacancies"]) for r in known),
        positions_known=len(known),
        provinces=provinces,
        employers=employers[:TOP_EMPLOYERS],
        first_pass=earlier is None,
        province_counts=dict(province_counts),
        top_employers=employers[:CARD_EMPLOYERS],
        since_date=since,
        week_postings=len(week),
        week_positions=sum(int(v) for v in week_known),
        week_known=len(week_known),
        intl_no_lmia=_intl_count(conn),
    )


def _intl_count(conn: sqlite3.Connection) -> int | None:
    """The digest's line on postings open to international candidates; a fault costs the line, never the post."""
    try:
        from .sources.jobbank_intl import digest_count
        return digest_count(conn)
    except Exception as exc:
        log.warning("digest: the international-candidates count could not be read (%s)", type(exc).__name__)
        return None


def card_for(d: Digest) -> CardData:
    """The card's data: the same facts as the text, with the longer employer list."""
    week_line = _positions_line(d.week_positions, d.week_known, d.week_postings)
    context = None
    if d.week_postings:
        context = f"Last {WEEK_DAYS} days: {_plural(d.week_postings, 'posting')}"
        if week_line:
            context += f", {week_line}"
    return CardData(
        date=d.data_date,
        title=_card_title(d),
        postings=d.postings,
        positions_line=_positions_line(d.positions, d.positions_known, d.postings),
        context=context,
        province_counts=dict(d.province_counts),
        employers=[CardEmployer(_defuse(e.name), _defuse(" ".join(p for p in (e.city, e.province) if p)), e.positions)
                   for e in d.top_employers],
        site=re.sub(r"^https?://", "", config.SITE_URL).rstrip("/"),
    )


# -- posting ----------------------------------------------------------------


def credentials_from_env(env: Mapping[str, str] | None = None) -> Credentials | None:
    source = os.environ if env is None else env
    values = [(source.get(name) or "").strip() for name in CREDENTIAL_ENV]
    if not all(values):
        return None
    return Credentials(*values)


def send_post(text: str, creds: Credentials, *, session: Any | None = None, timeout: float = 30,
              image: bytes | None = None, alt: str | None = None) -> str | None:
    """POST /2/tweets as the account that owns the access token, with the card attached
    when its upload succeeds. The new post id ("unknown" when X accepted it without a
    readable one), UNVERIFIED when X answered 5xx or not at all and the account's posts
    could not be read, or None when the post failed. A 4xx is a refusal and final."""
    try:
        import requests
        from requests_oauthlib import OAuth1
    except ImportError as exc:
        log.error("x: %s is not installed; nothing posted", exc.name)
        return None
    http = session if session is not None else requests.Session()
    auth = OAuth1(creds.api_key, creds.api_secret, creds.access_token, creds.access_token_secret)
    headers = {"User-Agent": config.USER_AGENT}

    payload: dict[str, Any] = {"text": text}
    if image:
        # The image is optional in a way the text is not: an upload failure
        # downgrades to a text-only post rather than skipping the day.
        media_id = _upload(http, auth, headers, image, timeout)
        if media_id:
            payload["media"] = {"media_ids": [media_id]}
            if alt:
                _alt_text(http, auth, headers, media_id, alt, timeout)
    try:
        resp = http.post(POST_URL, json=payload, auth=auth, timeout=timeout, headers=headers)
    except Exception as exc:  # network, TLS, signing: never a failed run
        # A timeout or a dropped connection can come after X has made the post.
        log.error("x: request failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return _find_post(http, auth, headers, text, timeout)
    status = int(getattr(resp, "status_code", 0) or 0)
    if not 200 <= status < 300:
        log.error("x: HTTP %s: %s", status, _body(resp))
        return _find_post(http, auth, headers, text, timeout) if status >= 500 else None
    try:
        return str(resp.json()["data"]["id"])
    except Exception:
        # The post exists (2xx) even if the body is unreadable; report success so
        # the date is recorded and a re-run does not post it again.
        log.warning("x: HTTP %s without a readable post id: %s", status, _body(resp))
        return "unknown"


def _comparable(text: str) -> str:
    # X returns a post's text with every link rewritten as t.co, a t.co link
    # appended for an attached image, and &, < and > escaped.
    return " ".join(html.unescape(TCO_RE.split(text, maxsplit=1)[0]).split())


def _find_post(http: Any, auth: Any, headers: dict, text: str, timeout: float) -> str | None:
    """After a 5xx or no answer, look for the post among the account's newest. Its id
    when listed, None when the list is read and it is not there, UNVERIFIED when the
    list cannot be read. A listed post is this one when it starts with the text's
    first line, which holds the pass's date and counts."""
    lead = _comparable(text.split("\n", 1)[0])
    try:
        time.sleep(LOOKUP_DELAY)
        me = http.get(ME_URL, auth=auth, timeout=timeout, headers=headers)
        status = int(getattr(me, "status_code", 0) or 0)
        if not 200 <= status < 300:
            raise ValueError(f"users/me HTTP {status}: {_body(me)}")
        user_id = str(me.json()["data"]["id"])
        if not user_id.isdigit():
            raise ValueError("users/me gave no numeric id")
        resp = http.get(TIMELINE_URL.format(id=user_id), params={"max_results": LOOKUP_COUNT, "tweet.fields": "created_at"},
                        auth=auth, timeout=timeout, headers=headers)
        status = int(getattr(resp, "status_code", 0) or 0)
        if not 200 <= status < 300:
            raise ValueError(f"timeline HTTP {status}: {_body(resp)}")
        body = resp.json()
        posts = body.get("data", [])
        # An account with no posts answers without "data"; errors without it are no answer.
        if not isinstance(posts, list) or (not posts and body.get("errors")):
            raise ValueError(f"timeline without a list of posts: {_body(resp)}")
    except Exception as exc:
        log.error("x: the account's posts could not be read to look for the post (%s): %s",
                  type(exc).__name__, str(exc)[:200])
        return UNVERIFIED
    for post in posts:
        if isinstance(post, dict) and lead and _comparable(str(post.get("text") or "")).startswith(lead):
            post_id = str(post.get("id") or "unknown")
            log.warning("x: the post went out despite the error: listed as %s, created %s",
                        post_id, post.get("created_at") or "at an unknown time")
            return post_id
    log.error("x: the post is not among the account's %d newest, so it failed", len(posts))
    return None


def _upload(http: Any, auth: Any, headers: dict, image: bytes, timeout: float) -> str | None:
    try:
        resp = http.post(
            UPLOAD_URL, files={"media": ("card.png", image, "image/png")}, data={"media_category": "tweet_image"},
            auth=auth, timeout=timeout, headers=headers,
        )
        status = int(getattr(resp, "status_code", 0) or 0)
        if not 200 <= status < 300:
            log.error("x: media upload HTTP %s, posting without the image: %s", status, _body(resp))
            return None
        return str(resp.json()["data"]["id"])
    except Exception as exc:
        log.error("x: media upload failed (%s), posting without the image: %s", type(exc).__name__, str(exc)[:200])
        return None


def _alt_text(http: Any, auth: Any, headers: dict, media_id: str, alt: str, timeout: float) -> None:
    try:
        resp = http.post(METADATA_URL, json={"id": media_id, "metadata": {"alt_text": {"text": alt}}},
                         auth=auth, timeout=timeout, headers=headers)
        status = int(getattr(resp, "status_code", 0) or 0)
        if not 200 <= status < 300:
            log.warning("x: alt text HTTP %s, image posted without it: %s", status, _body(resp))
    except Exception as exc:
        log.warning("x: alt text failed (%s), image posted without it", type(exc).__name__)


def _body(resp: Any) -> str:
    try:
        return re.sub(r"\s+", " ", str(resp.text))[:300]
    except Exception:
        return "(no body)"


def screen(digest: Digest | None, tag: str) -> str | None:
    """Why this pass must not be posted, as an outcome, or None when it may be.
    Shared by every platform so all of them refuse the same nights."""
    if digest is None:
        log.info("%s: no Job Bank pass recorded yet; nothing to post", tag)
        return "no pass"
    if digest.postings == 0:
        log.info("%s: the Job Bank pass of %s found no new postings with an LMIA requested; nothing posted",
                 tag, digest.data_date)
        return "no new postings"
    if digest.first_pass:
        # A fresh database (first run, or a failed restore) sees every posting as new.
        log.info("%s: the Job Bank pass of %s is the first in this database, so every posting is new; nothing posted",
                 tag, digest.data_date)
        return "first pass"
    if digest.postings > MAX_NEW_POSTINGS:
        log.info("%s: the Job Bank pass of %s saw %d new postings, more than a day brings; treated as a rebuild, nothing posted",
                 tag, digest.data_date, digest.postings)
        return "bulk pass"
    return None


def draw_card(digest: Digest, folder: Path, tag: str) -> tuple[bytes | None, str | None]:
    """The card PNG and its alt text, saved beside the text as <date>.png. A
    drawing fault costs the picture, not the post: (None, None)."""
    try:
        card = card_for(digest)
        png = render_card(card)
        alt = alt_text(card)
        (folder / f"{digest.data_date}.png").write_bytes(png)
        return png, alt
    except Exception as exc:
        log.error("%s: card not drawn (%s): %s", tag, type(exc).__name__, str(exc)[:200])
        return None, None


def run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    link: bool = False,
    image: bool = True,
    out_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    session: Any | None = None,
    echo: Callable[[str], None] = print,
) -> str:
    """Compose, save and (unless dry_run) post the digest. Returns the outcome for the log; never raises."""
    try:
        return _run(conn, dry_run=dry_run, link=link, image=image, out_dir=out_dir, env=env, session=session, echo=echo)
    except Exception as exc:
        log.error("x: digest failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return "failed"


def _run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool,
    link: bool,
    image: bool,
    out_dir: Path | None,
    env: Mapping[str, str] | None,
    session: Any | None,
    echo: Callable[[str], None],
) -> str:
    digest = collect(conn)
    skip = screen(digest, "x")
    if skip or digest is None:
        return skip or "no pass"

    text = compose(digest, link=search_link() if link else None)
    folder = out_dir or (config.OUT_DIR / "social")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{digest.data_date}.txt").write_text(text + "\n", encoding="utf-8")
    png, alt = draw_card(digest, folder, "x") if image else (None, None)

    if dry_run:
        echo(text)
        return "dry run"
    log.info("x: post for %s (%d characters as X counts them):\n%s", digest.data_date, x_length(text), text)

    last = get_meta(conn, LAST_POST_KEY)
    if last and last >= digest.data_date:
        log.info("x: already posted for the Job Bank pass of %s; nothing posted", last)
        return "already posted"
    creds = credentials_from_env(env)
    if creds is None:
        log.info("x: credentials not set (%s); nothing posted", ", ".join(CREDENTIAL_ENV))
        return "no credentials"
    post_id = send_post(text, creds, session=session, image=png, alt=alt)
    if post_id is None:
        return "failed"
    set_meta(conn, LAST_POST_KEY, digest.data_date)
    set_meta(conn, LAST_POST_ID_KEY, post_id)
    conn.commit()
    if post_id == UNVERIFIED:
        log.warning("x: the Job Bank pass of %s is recorded as posted so a re-run cannot post it twice, "
                    "but nothing confirms the post; check the account", digest.data_date)
        return "unverified"
    log.info("x: posted %s for the Job Bank pass of %s", post_id, digest.data_date)
    return "posted"
