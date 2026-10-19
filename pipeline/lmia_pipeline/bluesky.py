"""Daily Bluesky post: the same digest and card as the X post, with the link.

Why the AT Protocol over plain HTTPS rather than a client library: three
calls cover it (createSession, uploadBlob, createRecord), and requests is
already a dependency. The account signs in with an app password, which the
owner can revoke from the account settings at any time without touching the
account password.

Why the link: posting to Bluesky is free, so the post carries the search link
that X would bill at a higher rate. A Bluesky client links only the byte
ranges a post's facets name, so the link gets a facet; nothing else in the
text (an employer named "Example.com Inc", an "@" in a name) becomes a link
or a mention.

Why it never raises, and the meta key: as in social.py. The date of the Job
Bank pass last posted is stored under its own key, so the X and Bluesky posts
each go out at most once per pass, independently of each other.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config, social
from .db import get_meta, set_meta
from .social_card import HEIGHT, WIDTH

log = logging.getLogger(__name__)

SERVICE = "https://bsky.social"
SESSION_URL = f"{SERVICE}/xrpc/com.atproto.server.createSession"
UPLOAD_URL = f"{SERVICE}/xrpc/com.atproto.repo.uploadBlob"
RECORD_URL = f"{SERVICE}/xrpc/com.atproto.repo.createRecord"
# app.bsky.feed.post allows 300 graphemes of text; an image blob may be at most 1,000,000 bytes.
MAX_GRAPHEMES = 300
MAX_IMAGE_BYTES = 1_000_000
LAST_POST_KEY = "bsky_last_post_date"
LAST_POST_URI_KEY = "bsky_last_post_uri"
CREDENTIAL_ENV = ("BSKY_HANDLE", "BSKY_APP_PASSWORD")


@dataclass(frozen=True, repr=False)
class Credentials:
    handle: str
    app_password: str

    def __repr__(self) -> str:  # keep the password out of any log line or traceback
        return "Credentials(****)"


def credentials_from_env(env: Mapping[str, str] | None = None) -> Credentials | None:
    source = os.environ if env is None else env
    handle = (source.get("BSKY_HANDLE") or "").strip().lstrip("@")
    password = (source.get("BSKY_APP_PASSWORD") or "").strip()
    if not handle or not password:
        return None
    return Credentials(handle, password)


# -- composition ------------------------------------------------------------


def bsky_length(text: str) -> int:
    """An upper bound on the graphemes Bluesky counts: code points after NFC.
    Every grapheme holds at least one code point, so a text within the limit
    by this count is within it by Bluesky's; an emoji sequence only counts
    long, which drops a line early rather than having the post refused."""
    return len(unicodedata.normalize("NFC", text))


def compose(d: social.Digest, link: str) -> str:
    """The X text with the link at the end, cut to fit 300 graphemes the same way."""
    return social.compose(d, link=link, limit=MAX_GRAPHEMES, measure=bsky_length)


def link_facet(text: str, link: str) -> dict | None:
    """A link facet over the last occurrence of link in text. Offsets are UTF-8
    byte positions, end exclusive, as the richtext lexicon defines them."""
    at = text.rfind(link)
    if at < 0:
        return None
    start = len(text[:at].encode("utf-8"))
    return {
        "index": {"byteStart": start, "byteEnd": start + len(link.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
    }


def post_record(text: str, link: str, *, blob: dict | None, alt: str | None, now: datetime | None = None) -> dict:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "langs": ["en"],
    }
    facet = link_facet(text, link)
    if facet:
        record["facets"] = [facet]
    if blob:
        record["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": [{"alt": alt or "", "image": blob, "aspectRatio": {"width": WIDTH, "height": HEIGHT}}],
        }
    return record


# -- posting ----------------------------------------------------------------


def _status(resp: Any) -> int:
    return int(getattr(resp, "status_code", 0) or 0)


def _body(resp: Any) -> str:
    try:
        return re.sub(r"\s+", " ", str(resp.text))[:300]
    except Exception:
        return "(no body)"


def send_post(text: str, link: str, creds: Credentials, *, session: Any | None = None, timeout: float = 30,
              image: bytes | None = None, alt: str | None = None) -> str | None:
    """Sign in, upload the card, create the post. The new post's at:// URI, or
    None when the sign-in or the post failed. A failed upload posts the text alone."""
    try:
        import requests
    except ImportError:
        log.error("bluesky: requests is not installed; nothing posted")
        return None
    http = session if session is not None else requests.Session()
    headers = {"User-Agent": config.USER_AGENT}

    try:
        resp = http.post(SESSION_URL, json={"identifier": creds.handle, "password": creds.app_password},
                         headers=headers, timeout=timeout)
    except Exception as exc:
        log.error("bluesky: sign-in request failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return None
    status = _status(resp)
    if not 200 <= status < 300:
        log.error("bluesky: sign-in refused, HTTP %s (check BSKY_HANDLE and BSKY_APP_PASSWORD): %s", status, _body(resp))
        return None
    try:
        session_data = resp.json()
        token = str(session_data["accessJwt"])
        did = str(session_data["did"])
    except Exception:
        log.error("bluesky: sign-in answered HTTP %s without a usable session", status)
        return None
    auth = dict(headers, Authorization=f"Bearer {token}")

    blob = _upload(http, auth, image, timeout) if image else None
    record = post_record(text, link, blob=blob, alt=alt)
    try:
        resp = http.post(RECORD_URL, json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                         headers=auth, timeout=timeout)
    except Exception as exc:
        log.error("bluesky: post request failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return None
    status = _status(resp)
    if not 200 <= status < 300:
        log.error("bluesky: post refused, HTTP %s: %s", status, _body(resp))
        return None
    try:
        return str(resp.json()["uri"])
    except Exception:
        # The post exists (2xx); record it so a re-run does not post it again.
        log.warning("bluesky: HTTP %s without a readable post URI: %s", status, _body(resp))
        return "unknown"


def _upload(http: Any, auth: dict, image: bytes, timeout: float) -> dict | None:
    if len(image) > MAX_IMAGE_BYTES:
        log.error("bluesky: card is %d bytes, over the %d an image may be; posting without it", len(image), MAX_IMAGE_BYTES)
        return None
    try:
        resp = http.post(UPLOAD_URL, data=image, headers=dict(auth, **{"Content-Type": "image/png"}), timeout=timeout)
        status = _status(resp)
        if not 200 <= status < 300:
            log.error("bluesky: image upload HTTP %s, posting without the image: %s", status, _body(resp))
            return None
        blob = resp.json()["blob"]
        if not isinstance(blob, dict):
            raise ValueError("blob is not an object")
        return blob
    except Exception as exc:
        log.error("bluesky: image upload failed (%s), posting without the image: %s", type(exc).__name__, str(exc)[:200])
        return None


def run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    image: bool = True,
    out_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    session: Any | None = None,
    echo: Callable[[str], None] = print,
) -> str:
    """Compose, save and (unless dry_run) post the digest. Returns the outcome for the log; never raises."""
    try:
        return _run(conn, dry_run=dry_run, image=image, out_dir=out_dir, env=env, session=session, echo=echo)
    except Exception as exc:
        log.error("bluesky: digest failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return "failed"


def _run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool,
    image: bool,
    out_dir: Path | None,
    env: Mapping[str, str] | None,
    session: Any | None,
    echo: Callable[[str], None],
) -> str:
    digest = social.collect(conn)
    skip = social.screen(digest, "bluesky")
    if skip or digest is None:
        return skip or "no pass"

    link = social.search_link()
    text = compose(digest, link)
    folder = out_dir or (config.OUT_DIR / "social")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{digest.data_date}.bluesky.txt").write_text(text + "\n", encoding="utf-8")
    png, alt = social.draw_card(digest, folder, "bluesky") if image else (None, None)

    if dry_run:
        echo(text)
        return "dry run"
    log.info("bluesky: post for %s (%d of %d graphemes at most):\n%s", digest.data_date, bsky_length(text),
             MAX_GRAPHEMES, text)

    last = get_meta(conn, LAST_POST_KEY)
    if last and last >= digest.data_date:
        log.info("bluesky: already posted for the Job Bank pass of %s; nothing posted", last)
        return "already posted"
    creds = credentials_from_env(env)
    if creds is None:
        log.info("bluesky: credentials not set (%s); nothing posted", ", ".join(CREDENTIAL_ENV))
        return "no credentials"
    uri = send_post(text, link, creds, session=session, image=png, alt=alt)
    if uri is None:
        return "failed"
    set_meta(conn, LAST_POST_KEY, digest.data_date)
    set_meta(conn, LAST_POST_URI_KEY, uri)
    conn.commit()
    log.info("bluesky: posted %s for the Job Bank pass of %s", uri, digest.data_date)
    return "posted"
