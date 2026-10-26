"""Government notices: IRCC and ESDC news items on Canada.ca that name the programs behind the records.

Source: the Canada.ca news API (api.io.canada.ca), one Atom feed per
department and language, each asked for the last 12 months (FEEDS). The
feeds carry news releases, backgrounders, statements, speeches and media
advisories. Titles and summaries are Crown copyright, reproduced under the
canada.ca terms (non-commercial reproduction with attribution); the site
links each title to the department's page and adds nothing to the text.

Each night (one request per feed, through this stage's own client so a
failing host never counts toward another stage's circuit breaker):
  * every feed is parsed; an item is kept when its title or summary, in
    either language, contains one of KEYWORDS (word boundaries, case and
    apostrophe folded);
  * the English and French items of a department are paired on the feed's
    timestamp, which the two languages share to the second (their URLs do
    not: each slug is translated). Items with the same timestamp pair by
    type, then by their order in the feed, which both languages keep;
  * the dateline that opens a release's summary (the date, a dash, the place
    and a dash: "Le 16 octobre 2026 – Kitchener (Ontario) – ") is left out,
    since the date is shown beside the item;
  * a matched item is stored in gov_notices under a stable id from its
    canada.ca URL (English, else French). An item with no pair keeps the
    other language empty and the site shows the one it has, with a note.

Resilience (the designated-employer pattern): a feed that cannot be read or
parsed keeps the items already stored, and the other language of its
department still updates its own fields. Notices are information, never an
item needing attention: they reach status.json, LAST_RUN.md and the daily
check's email, and the run stays ok. A feed is a notice on a change of state
only (the night it stops being read and the night it is read again). Every
item first stored tonight is a notice of its own ("Government notice: <date>
<title> <url>", the full title and link), at most NEW_NOTICES_SHOWN a night
and as many whole notices as fit the log row (db.NOTICE_MAX_CHARS), with a
count for the rest; the night of the first read is the baseline and lists
its items in one line instead.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ..db import NOTICE_MAX_CHARS, get_meta, log_run, now_iso, set_meta
from ..http import AbortRun, FetchError, PoliteClient, decode_text

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
NOTICE_SEP = " | "
# Attempts per request for this stage's client: a feed that fails tonight is read again tomorrow.
CLIENT_ATTEMPTS = 2
# Items announced one by one on the night they are first stored; the rest are counted.
NEW_NOTICES_SHOWN = 5
# Room kept in the log row for the line that counts the items not shown.
COUNT_LINE_ROOM = 100
MAX_TITLE = 500
MAX_SUMMARY = 2000
WINDOW_LABEL = "12 months"

DEPARTMENTS = ("ircc", "esdc")


@dataclass(frozen=True)
class Feed:
    key: str          # ircc_en | ircc_fr | esdc_en | esdc_fr
    department: str   # ircc | esdc
    lang: str         # en | fr
    dept_param: str   # the API's name for the department
    pick: int         # the most items the feed returns
    title: str        # the feed's atomtitle, URL-encoded

    def url(self, since: str) -> str:
        """The feed's address for the 12 months from `since` (YYYY-MM-DD)."""
        return (f"https://api.io.canada.ca/io-server/gc/news/{self.lang}/v2?dept={self.dept_param}"
                f"&sort=publishedDate&orderBy=desc&publishedDate%3E={since}&pick={self.pick}&format=atom"
                f"&atomtitle={self.title}")


# The addresses the approved prototype read on 2026-10-25, with the window's
# first day filled in each night. pick bounds the items a feed returns: the
# 12 months to 2026-10-25 held 80 IRCC and 226 ESDC items.
_IRCC = "departmentofcitizenshipandimmigration"
_ESDC = "departmentofemploymentandsocialdevelopment"
FEEDS: tuple[Feed, ...] = (
    Feed("ircc_en", "ircc", "en", _IRCC, 300, "Immigration,%20Refugees%20and%20Citizenship%20Canada"),
    Feed("ircc_fr", "ircc", "fr", _IRCC, 300, "Immigration,%20R%C3%A9fugi%C3%A9s%20et%20Citoyennet%C3%A9%20Canada"),
    Feed("esdc_en", "esdc", "en", _ESDC, 500, "Employment%20and%20Social%20Development%20Canada"),
    Feed("esdc_fr", "esdc", "fr", _ESDC, 500, "Emploi%20et%20D%C3%A9veloppement%20social%20Canada"),
)

# The keyword set of the approved prototype: (term as matched, label shown, its language).
# The singular "travailleur étranger temporaire" is shown under its plural, and
# a label takes the typographic apostrophe (matching folds both forms).
KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("lmia", "LMIA", "en"),
    ("labour market impact assessment", "labour market impact assessment", "en"),
    ("temporary foreign worker", "Temporary Foreign Worker", "en"),
    ("tfwp", "TFWP", "en"),
    ("express entry", "Express Entry", "en"),
    ("work permit", "work permit", "en"),
    ("job bank", "Job Bank", "en"),
    ("wage threshold", "wage threshold", "en"),
    ("refusal to process", "refusal to process", "en"),
    ("international mobility program", "International Mobility Program", "en"),
    ("permanent residence job offer", "permanent residence job offer", "en"),
    ("eimt", "EIMT", "fr"),
    ("étude d'impact sur le marché du travail", "étude d’impact sur le marché du travail", "fr"),
    ("travailleurs étrangers temporaires", "travailleurs étrangers temporaires", "fr"),
    ("travailleur étranger temporaire", "travailleurs étrangers temporaires", "fr"),
    ("entrée express", "Entrée express", "fr"),
    ("permis de travail", "permis de travail", "fr"),
    ("guichet-emplois", "Guichet-Emplois", "fr"),
)

# The feeds' category terms, in either language, and the type each names.
TYPES = {
    "news releases": "news_release", "communiqués de presse": "news_release",
    "backgrounders": "backgrounder", "documents d'information": "backgrounder",
    "statements": "statement", "déclarations": "statement",
    "speeches": "speech", "discours": "speech",
    "media advisories": "media_advisory", "avis aux médias": "media_advisory",
}

# A release opens on a dateline: the date, an em-dash, the place, an em-dash
# ("October 16, 2026", "Kitchener, Ontario"; in French with en dashes, "Le 16
# octobre 2026 – Kitchener (Ontario) – "). The date is shown beside the item,
# so the dateline is left out, and with it the feed's em-dashes.
DATELINE_RE = re.compile(
    r"^(?:[A-Z][a-z]+ \d{1,2}, \d{4}|Le \d{1,2}(?:er)? \w+ \d{4})\s*[\u2014\u2013-]\s*[^\u2014\u2013]{1,60}?\s*[\u2014\u2013-]\s*"
)
TAG_RE = re.compile(r"<[^>]+>")
CANADA_CA_RE = re.compile(r"^https://www\.canada\.ca/(?:en|fr)/[A-Za-z0-9/._%-]+$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").replace("\u00ad", "").replace("\u2019", "'").lower()
    return re.sub(r"\s+", " ", s)


_PATTERNS = [(re.compile(r"(?<![\w])" + re.escape(_norm(k)) + r"(?![\w])"), label) for k, label, _ in KEYWORDS]


def matched_terms(title: str | None, summary: str | None) -> list[str]:
    """The labels of the keywords the title or summary contains, in KEYWORDS order, each once."""
    text = _norm(f"{title or ''} {summary or ''}")
    out: list[str] = []
    for rx, label in _PATTERNS:
        if label not in out and rx.search(text):
            out.append(label)
    return out


def term_labels() -> list[dict[str, str]]:
    """Each label once with its language, for the page's list of terms."""
    out: list[dict[str, str]] = []
    for _k, label, lang in KEYWORDS:
        if all(t["label"] != label for t in out):
            out.append({"label": label, "lang": lang})
    return out


def strip_dateline(summary: str) -> str:
    return DATELINE_RE.sub("", summary or "").strip()


def _clean(text: str | None, limit: int) -> str:
    """Text as published: markup and entities removed, whitespace collapsed."""
    plain = html.unescape(TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", plain).strip()[:limit]


def one_year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


def notice_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# -- parsing ----------------------------------------------------------------------------


class FeedProblem(Exception):
    """A feed was fetched but is not an Atom feed this stage can read."""


@dataclass
class Item:
    lang: str
    title: str
    summary: str
    url: str
    published_at: str        # the timestamp as the feed gives it
    instant: datetime        # the same, comparable across offsets
    item_type: str
    order: int               # position in the feed

    @property
    def terms(self) -> list[str]:
        return matched_terms(self.title, self.summary)


def parse_feed(raw: bytes, lang: str) -> list[Item]:
    """The feed's items. Raises FeedProblem when the body is not a readable Atom feed."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FeedProblem(f"not XML ({exc})") from exc
    if root.tag != ATOM + "feed":
        raise FeedProblem(f"not an Atom feed (root {root.tag[:60]})")
    items: list[Item] = []
    for n, e in enumerate(root.findall(ATOM + "entry")):
        link = e.find(ATOM + "link")
        url = ((link.get("href") if link is not None else None) or e.findtext(ATOM + "id") or "").strip()
        stamp = (e.findtext(ATOM + "updated") or e.findtext(ATOM + "published") or "").strip()
        title = _clean(e.findtext(ATOM + "title"), MAX_TITLE)
        if not (url and stamp and title) or not CANADA_CA_RE.match(url):
            log.info("notices: an entry without a canada.ca link, a date or a title is skipped (%s)", url[:120])
            continue
        try:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            log.info("notices: an entry with an unreadable date is skipped (%s)", stamp[:40])
            continue
        if instant.tzinfo is None or not re.match(r"\d{4}-\d{2}-\d{2}", stamp):
            continue
        category = e.find(ATOM + "category")
        term = (category.get("term") if category is not None else "") or ""
        items.append(Item(
            lang=lang, title=title, summary=strip_dateline(_clean(e.findtext(ATOM + "summary"), MAX_SUMMARY)),
            url=url, published_at=stamp, instant=instant, item_type=TYPES.get(term.strip().lower(), "other"), order=n,
        ))
    if not items:
        raise FeedProblem("the feed has no entries")
    return items


def pair(english: list[Item], french: list[Item]) -> list[tuple[Item | None, Item | None]]:
    """Pair a department's English and French items on their timestamp.

    Items with the same timestamp pair by type first, then in feed order.
    Returns (english, french) pairs; an item with no partner has None beside it.
    """
    by_instant: dict[datetime, list[Item]] = {}
    for f in sorted(french, key=lambda i: i.order):
        by_instant.setdefault(f.instant, []).append(f)
    out: list[tuple[Item | None, Item | None]] = []
    for e in sorted(english, key=lambda i: i.order):
        candidates = by_instant.get(e.instant, [])
        same = [f for f in candidates if f.item_type == e.item_type]
        chosen = (same or candidates or [None])[0]
        if chosen is not None:
            candidates.remove(chosen)
        out.append((e, chosen))
    out.extend((None, f) for rest in by_instant.values() for f in rest)
    return out


# -- storing ----------------------------------------------------------------------------


def _store(conn: sqlite3.Connection, department: str, en: Item | None, fr: Item | None, stamp: str) -> str | None:
    """Upsert one matched pair; returns its id when the row is new tonight, else None.

    A language absent tonight keeps what is stored. A French-only row stored on
    an earlier night is folded into the row its English item now gives.
    """
    base = en or fr
    assert base is not None
    rid = notice_id(base.url)
    first_seen = stamp
    new = conn.execute("SELECT 1 FROM gov_notices WHERE id = ?", (rid,)).fetchone() is None
    if en is not None and fr is not None:
        old = conn.execute("SELECT id, first_seen FROM gov_notices WHERE url_fr = ? AND id != ?", (fr.url, rid)).fetchall()
        for row in old:
            first_seen = min(first_seen, row["first_seen"])
            new = False
            conn.execute("DELETE FROM gov_notices WHERE id = ?", (row["id"],))

    def side(item: Item | None) -> tuple:
        if item is None:
            return (None, None, None, None)
        return (item.title, item.summary, item.url, json.dumps(item.terms, ensure_ascii=False))

    # The English category decides the type; the French one when the English is absent or unknown.
    kinds = [i.item_type for i in (en, fr) if i is not None and i.item_type != "other"]
    item_type = kinds[0] if kinds else "other"

    conn.execute(
        """
        INSERT INTO gov_notices (id, department, item_type, published_at, published,
                                 title_en, summary_en, url_en, terms_en, title_fr, summary_fr, url_fr, terms_fr,
                                 first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          item_type = excluded.item_type, published_at = excluded.published_at, published = excluded.published,
          title_en = COALESCE(excluded.title_en, gov_notices.title_en),
          summary_en = COALESCE(excluded.summary_en, gov_notices.summary_en),
          url_en = COALESCE(excluded.url_en, gov_notices.url_en),
          terms_en = COALESCE(excluded.terms_en, gov_notices.terms_en),
          title_fr = COALESCE(excluded.title_fr, gov_notices.title_fr),
          summary_fr = COALESCE(excluded.summary_fr, gov_notices.summary_fr),
          url_fr = COALESCE(excluded.url_fr, gov_notices.url_fr),
          terms_fr = COALESCE(excluded.terms_fr, gov_notices.terms_fr),
          first_seen = MIN(gov_notices.first_seen, excluded.first_seen),
          last_seen = excluded.last_seen
        """,
        (rid, department, item_type, base.published_at, base.published_at[:10], *side(en), *side(fr), first_seen, stamp),
    )
    return rid if new else None


def _save_feed(conn: sqlite3.Connection, feed: Feed, stamp: str, *, ok: bool, entries: int = 0, detail: str = "") -> None:
    conn.execute(
        """
        INSERT INTO gov_notice_feeds (key, state, checked_at, last_ok_at, entries, detail) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          state = excluded.state, checked_at = excluded.checked_at,
          last_ok_at = COALESCE(excluded.last_ok_at, gov_notice_feeds.last_ok_at),
          entries = CASE WHEN excluded.state = 'ok' THEN excluded.entries ELSE gov_notice_feeds.entries END,
          detail = excluded.detail
        """,
        (feed.key, "ok" if ok else "failing", stamp, stamp if ok else None, entries, detail[:300]),
    )


def read_feed(client: PoliteClient, feed: Feed, since: str) -> tuple[list[Item] | None, str]:
    """(items, detail); items is None when the feed could not be read. Never raises."""
    url = feed.url(since)
    try:
        raw = client.get(url, timeout=60)
    except (FetchError, AbortRun) as exc:
        client.reset_failures()
        return None, f"not fetched: {exc}"
    try:
        items = parse_feed(raw, feed.lang)
    except FeedProblem as exc:
        return None, f"not read: {exc}; the body opens {' '.join(decode_text(raw[:80]).split())!r}"
    detail = f"{len(items)} items"
    if len(items) >= feed.pick:
        detail += " (the feed is full; older items may be cut)"
    return items, detail


# -- notices ----------------------------------------------------------------------------


def item_notice(published: str, title: str, url: str) -> str:
    """'Government notice: <date> <title> <url>', with the full title and link on one line."""
    # The run status splits a stage's notices on NOTICE_SEP, so a title must not carry it.
    title = " ".join(title.replace(NOTICE_SEP, " / ").split())
    return f"Government notice: {published} {title} {url}"


def new_item_notices(conn: sqlite3.Connection, ids: list[str], room: int = NOTICE_MAX_CHARS) -> list[str]:
    """One whole notice per item first stored tonight, newest first: at most
    NEW_NOTICES_SHOWN, and fewer when their full text would pass `room`
    characters of the log row; a count for the rest."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT published, published_at, COALESCE(title_en, title_fr) AS title, COALESCE(url_en, url_fr) AS url "
        f"FROM gov_notices WHERE id IN ({marks})", ids).fetchall()
    rows = sorted(rows, key=lambda r: (r["published"], r["published_at"], r["url"]), reverse=True)
    out: list[str] = []
    used = 0
    for r in rows[:NEW_NOTICES_SHOWN]:
        line = item_notice(r["published"], r["title"], r["url"])
        cost = len(line) + len(NOTICE_SEP)
        if out and used + cost + COUNT_LINE_ROOM > room:
            break
        out.append(line)
        used += cost
    rest = len(rows) - len(out)
    if rest > 0:
        out.append(f"Government notices: {rest} more first listed tonight, on the Notices page")
    return out


def _state_notices(before: dict[str, str], states: dict[str, str], details: dict[str, str]) -> list[str]:
    out: list[str] = []
    stopped = [k for k, s in states.items() if s == "failing" and before.get(k) != "failing"]
    recovered = [k for k, s in states.items() if s == "ok" and before.get(k) == "failing"]
    if stopped:
        out.append("Government notice feeds not read from tonight (their items are kept): "
                   + "; ".join(f"{k} ({details.get(k, '')[:120]})" for k in stopped))
    if recovered:
        out.append("Government notice feeds read again: " + ", ".join(recovered))
    return out


# -- the stage ---------------------------------------------------------------------------


@dataclass
class NoticeStats:
    states: dict[str, str]
    listed: int
    new: int
    baseline: bool = False

    def summary(self) -> str:
        """The night's line for LAST_RUN.md and status.json."""
        line = f"{self.listed} listed, {self.new} new tonight"
        if self.baseline:
            line += " (first read)"
        failing = sorted(k for k, s in self.states.items() if s != "ok")
        return line + (f"; not read: {', '.join(failing)}" if failing else "")


def window_start(today: date) -> str:
    return one_year_before(today).isoformat()


def listed_count(conn: sqlite3.Connection, today: date) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM gov_notices WHERE published >= ?", (window_start(today),)).fetchone()[0])


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
        feeds: tuple[Feed, ...] = FEEDS) -> NoticeStats:
    """Read every feed, store the matched items, and log one row with the notices. Never raises for a feed."""
    stamp = now or now_iso()
    today = date.fromisoformat(stamp[:10])
    since = window_start(today)
    before = {r["key"]: r["state"] for r in conn.execute("SELECT key, state FROM gov_notice_feeds")}
    baseline = get_meta(conn, "notices_baseline") is None
    read: dict[str, list[Item] | None] = {}
    states: dict[str, str] = {}
    details: dict[str, str] = {}
    for feed in feeds:
        items, detail = read_feed(client, feed, since)
        read[feed.key] = items
        states[feed.key] = "ok" if items is not None else "failing"
        details[feed.key] = detail
        _save_feed(conn, feed, stamp, ok=items is not None, entries=len(items or []), detail=detail)
    new_ids: list[str] = []
    for dept in DEPARTMENTS:
        en = read.get(f"{dept}_en")
        fr = read.get(f"{dept}_fr")
        if en is None and fr is None:
            continue
        for e, f in pair(en or [], fr or []):
            if not ((e is not None and e.terms) or (f is not None and f.terms)):
                continue
            if e is None and en is None and f is not None:
                # The English feed failed tonight: a row that already holds this
                # French item is refreshed; any other is stored French-only and
                # folded into its English row on a night both feeds are read.
                row = conn.execute("SELECT id FROM gov_notices WHERE url_fr = ?", (f.url,)).fetchone()
                if row is not None:
                    _update_side(conn, row["id"], f, stamp)
                    continue
            rid = _store(conn, dept, e, f, stamp)
            if rid:
                new_ids.append(rid)
    ok_any = any(s == "ok" for s in states.values())
    notices = _state_notices(before, states, details)
    listed = listed_count(conn, today)
    if baseline and ok_any:
        set_meta(conn, "notices_baseline", stamp[:10])
        notices.append(f"Government notices read for the first time: {listed} listed from the last {WINDOW_LABEL} "
                       f"(no notice per item on the first night)")
    elif new_ids:
        room = NOTICE_MAX_CHARS - len(NOTICE_SEP.join(notices)) - len(NOTICE_SEP)
        notices.extend(new_item_notices(conn, new_ids, room))
    set_meta(conn, "notices_last_run", stamp)
    conn.commit()
    stats = NoticeStats(states, listed, len(new_ids), baseline=baseline and ok_any)
    log_run(conn, "gov_notices", detail=stats.summary()[:900], rows_in=listed, rows_new=len(new_ids),
            notice=NOTICE_SEP.join(notices) if notices else None)
    return stats


def _update_side(conn: sqlite3.Connection, rid: str, item: Item, stamp: str) -> None:
    """Refresh one language of a stored row (its other feed failed tonight)."""
    col = item.lang
    conn.execute(
        f"UPDATE gov_notices SET title_{col} = ?, summary_{col} = ?, url_{col} = ?, terms_{col} = ?, last_seen = ? "
        f"WHERE id = ?",
        (item.title, item.summary, item.url, json.dumps(item.terms, ensure_ascii=False), stamp, rid),
    )


# -- export -----------------------------------------------------------------------------


def _terms(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return [t for t in parsed if isinstance(t, str)] if isinstance(parsed, list) else []


def export_doc(conn: sqlite3.Connection, as_of: str | None) -> dict | None:
    """notices.json for the site; None before the first read."""
    last_run = get_meta(conn, "notices_last_run")
    if not last_run:
        return None
    today = date.fromisoformat((as_of or last_run)[:10])
    since = window_start(today)
    rows = conn.execute("SELECT * FROM gov_notices WHERE published >= ?", (since,)).fetchall()
    # Offsets differ between items (EST, EDT), so the instant decides the order.
    rows = sorted(rows, key=lambda r: (_instant(r["published_at"]), r["id"]), reverse=True)
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "department": r["department"],
            "type": r["item_type"],
            "published": r["published"],
            "title": {"en": r["title_en"], "fr": r["title_fr"]},
            "summary": {"en": r["summary_en"], "fr": r["summary_fr"]},
            "url": {"en": r["url_en"], "fr": r["url_fr"]},
            "terms": {"en": _terms(r["terms_en"]), "fr": _terms(r["terms_fr"])},
            "first_seen": (r["first_seen"] or "")[:10],
        })
    states = {r["key"]: r for r in conn.execute("SELECT * FROM gov_notice_feeds")}
    feeds = []
    for feed in FEEDS:
        s = states.get(feed.key)
        feeds.append({
            "key": feed.key,
            "department": feed.department,
            "lang": feed.lang,
            "state": s["state"] if s is not None else "not_read",
            "checked": (s["checked_at"] or "")[:10] or None if s is not None else None,
            "last_ok": (s["last_ok_at"] or "")[:10] or None if s is not None else None,
        })
    dates = [i["published"] for i in items]
    return {
        "as_of": today.isoformat(),
        "last_checked": last_run[:10],
        "window_from": since,
        "count": len(items),
        "first": min(dates) if dates else None,
        "last": max(dates) if dates else None,
        "terms": term_labels(),
        "feeds": feeds,
        "items": items,
    }


def _instant(stamp: str) -> datetime:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def write_all(conn: sqlite3.Connection, out: Path, as_of: str | None) -> dict[str, int]:
    """Write notices.json (an optional export section); nothing before the first read."""
    from ..export_static import _dump  # export_static imports this module

    doc = export_doc(conn, as_of)
    if doc is None:
        return {"notices_files": 0}
    _dump(out / "notices.json", doc)
    return {"notices_files": 1, "notices_listed": doc["count"]}


def sitemap_lastmod(conn: sqlite3.Connection, as_of: str | None) -> str | None:
    """The day the list last gained an item, for the sitemap; None when it lists nothing."""
    doc_since = window_start(date.fromisoformat((as_of or get_meta(conn, "notices_last_run") or now_iso())[:10]))
    row = conn.execute("SELECT MAX(first_seen) FROM gov_notices WHERE published >= ?", (doc_since,)).fetchone()
    return (row[0] or "")[:10] or None


def status_summary(conn: sqlite3.Connection, started: str | None) -> dict:
    """What status.json says about the notices: listed, new tonight, last checked, each feed's state.

    Reads with positional rows (the run status opens the file without a row
    factory); {} before the first read.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'notices_last_run'").fetchone()
    if not row or not row[0]:
        return {}
    last_run = str(row[0])
    listed = listed_count(conn, date.fromisoformat(last_run[:10]))
    new = 0
    if started:
        new = int(conn.execute("SELECT COUNT(*) FROM gov_notices WHERE first_seen >= ?", (started,)).fetchone()[0])
    feeds = {k: s for k, s in conn.execute("SELECT key, state FROM gov_notice_feeds ORDER BY key")}
    return {"listed": listed, "new_tonight": new, "summary": f"{listed} listed, {new} new tonight",
            "last_checked": last_run, "feeds": feeds}
