"""Job Bank postings open to international candidates (search facet fglo=1).

Employers posting on Job Bank choose the posting's intended applicants:
"Canadians and authorized workers" (fcan=1) or "Canadians and international
candidates" (fglo=1). On 2026-10-25 the second facet held 8,032 of about
68,000 postings, 1,086 of them with an LMIA requested. From 2026-11-03 a job
offer used for Express Entry needs no LMIA, so these postings are where such
offers can still be seen (intl.py grades them; signals, never findings).

Each night, after the LMIA crawl and through the same polite client:
  1. the facet's first search page, for the counts it states (the whole
     facet, with an LMIA requested or approved, posted in the last 48 hours
     or 30 days, and the authorized-workers facet beside it), one row per
     count and day in jobbank_facet_counts. The page must show the filter as
     applied; when it does not (the parameter was renamed or ignored) the
     stage stops there and fails, so a whole-site result is never read as
     the facet;
  2. the facet's Atom feed of the last 48 hours (fage=2, rows=100), each
     entry giving the posting id, title, employer, place and salary. A feed
     that comes back full is followed by the last-48-hours search pages, so
     a busy day is not cut at 100;
  3. once a week (and on the first night, which sets the baseline date), a
     sweep of every page of the facet. A sweep that ends on an empty page and
     lists at least COMPLETE_SHARE of the stated count is complete; only then
     are postings it did not list marked gone (in_facet = 0), the way the LMIA
     crawl marks a flag gone. A sweep that stops short is tried again the next
     night;
  4. posting pages for postings not read yet, newest first, within a nightly
     budget: the "Who can apply" block (international, authorized workers,
     Canadians only, or unknown), the LMIA marker, the NOC code, the terms of
     employment, and phrases in the posting's own text (Express Entry,
     permanent-residence support, "LMIA exempt" or "not required"), each kept
     as matched for audit. Job Bank's own boilerplate (the LMIA notice, the
     audience block, dialogs) is removed before the text is searched.

Then the LMIA marker is joined from the LMIA crawl (a posting seen there keeps
"requested" or "approved"), employer ids are resolved against existing
employers only, and every grade is recomputed. Private households are
dropped before anything is written and counted only (project rule 3). Like
the LMIA crawl, the stage runs at most once in 20 hours and never raises for
a failing or changed site: a page that cannot be fetched, a layout the parser
no longer reads or a host that stops answering ends the step where it is and
fails the stage with the reason.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from bs4 import BeautifulSoup

from .. import config, intl
from ..db import get_meta, hours_since, log_run, now_iso, set_meta
from ..exclusions import is_private_household
from ..http import AbortRun, FetchError, PoliteClient
from ..normalize import employer_id, norm_name, parse_salary_text
from . import jobbank

log = logging.getLogger(__name__)

FEED_ROWS = 100
RECENT_MAX_PAGES = 12
MAX_PAGES = 1000
SWEEP_DAYS = 7
# Same rule as the LMIA crawl: a sweep is complete when it ends on an empty
# page and listed at least this share of the count its first page stated.
COMPLETE_SHARE = jobbank.COMPLETE_SHARE
SWEEP_BUDGET_S = 2 * 3600.0
DETAIL_BUDGET_S = 90 * 60.0
# 400 pages at the crawl delay is about 55 minutes, inside DETAIL_BUDGET_S.
DEFAULT_DETAIL_BUDGET = 400
MIN_HOURS = 20.0
MAX_PHRASES = 5
PHRASE_CHARS = 140
POSTING_ID_RE = re.compile(r"/jobposting/(\d{1,15})")
ATOM = "{http://www.w3.org/2005/Atom}"

# Labels on the facet's first page whose badge is a count worth keeping.
FACET_LABELS: dict[str, str] = {
    "LMIA requested": "lmia_requested",
    "Approved LMIA": "lmia_approved",
    "Last 48 hours": "last_48h",
    "Last 30 days": "last_30d",
    "Canadians and authorized workers": "authorized",
}
INTL_LABEL = "Canadians and international candidates"

# Phrases searched in the posting's own text. Each pattern is a signal the
# methodology names; the matched text is stored as it reads.
EE_PATTERNS = [
    re.compile(r"\bexpress[\s-]*entry\b", re.I),
    re.compile(r"\bentr[ée]e[\s-]+express\b", re.I),
    re.compile(r"\bcomprehensive\s+ranking\s+system\b", re.I),
    re.compile(r"\bCRS\s+(?:points?|scores?)\b"),
]
PR_PATTERNS = [
    re.compile(r"\b(?:PR|permanent\s+residen(?:ce|cy))\b(?:\W+\w+){0,6}?\W+(?:support\w*|sponsor\w*|pathway\w*|path|assist\w*|help\w*|nominat\w*|application)\b",
               re.I),
    re.compile(r"\b(?:support\w*|sponsor\w*|pathway\w*|assist\w*|help\w*)\b(?:\W+\w+){0,6}?\W+(?:PR|permanent\s+residen(?:ce|cy))\b", re.I),
]
EXEMPT_PATTERNS = [
    re.compile(r"\bLMIA[\s-]*(?:exempt\w*|free)\b", re.I),
    re.compile(r"\bLMIA\s+(?:is\s+)?not\s+(?:required|needed)\b", re.I),
    re.compile(r"\bno\s+LMIA\s+(?:is\s+)?(?:required|needed)\b", re.I),
    re.compile(r"\bwithout\s+(?:an?\s+)?LMIA\b", re.I),
    re.compile(r"\bexempt(?:ion)?\s+from\s+(?:the\s+|an?\s+)?LMIA\b", re.I),
]
# Job Bank's own text on a posting page, removed before the phrases are searched:
# the LMIA notice ("Canadian citizens and permanent residents are still
# encouraged"), the audience block, dialogs, the apply section, the common notice.
BOILERPLATE = (".disclaimer", ".job-audience", ".modal-dialog", ".mfp-hide", "#seekeractions", "#applynow",
               ".job-posting-detail-common", ".wb-inv", "nav", "header", "footer")


def feed_url() -> str:
    return f"{config.JOBBANK_BASE}/jobsearch/feed/jobSearchRSSfeed?fage=2&fglo=1&sort=D&rows={FEED_ROWS}"


def search_url(page: int, *, recent: bool = False) -> str:
    age = "&fage=2" if recent else ""
    return f"{config.JOBBANK_BASE}/jobsearch/jobsearch?searchstring=&locationstring=&sort=D&fglo=1{age}&page={page}"


@dataclass
class FeedItem:
    posting_id: int
    title: str | None
    employer: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    salary_text: str | None
    date_posted: str | None


@dataclass
class IntlFields:
    audience: str = "unknown"
    audience_text: str | None = None
    lmia: str = "none"
    employment_terms: str | None = None
    full_time: int | None = None
    permanent: int | None = None
    ee: list[str] = field(default_factory=list)
    pr: list[str] = field(default_factory=list)
    exempt: list[str] = field(default_factory=list)


@dataclass
class IntlStats:
    counts: dict[str, int] = field(default_factory=dict)
    feed_entries: int = 0
    recent_pages: int = 0
    listed: int = 0
    excluded: int = 0
    new_postings: int = 0
    sweep: str = "not due"          # not due | complete | incomplete | skipped
    sweep_pages: int = 0
    marked_gone: int = 0
    details_fetched: int = 0
    grades: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        g = self.grades
        text = (f"facet {self.counts.get('total', 'unknown')} live, feed {self.feed_entries}, new {self.new_postings}, "
                f"pages read {self.details_fetched}, sweep {self.sweep}"
                f"{f' ({self.marked_gone} gone)' if self.sweep == 'complete' else ''}, "
                f"grades A {g.get('A', 0)} B {g.get('B', 0)} C {g.get('C', 0)}")
        return text + (f"; problems: {'; '.join(self.problems)}" if self.problems else "")


# -- parsing ----------------------------------------------------------------------


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_feed(xml: str) -> list[FeedItem]:
    """Entries of the facet's Atom feed; ValueError when the body is not an Atom feed."""
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError as exc:
        raise ValueError(f"the feed is not XML ({exc})") from exc
    if root.tag != f"{ATOM}feed":
        raise ValueError(f"the feed's root is {root.tag}, not an Atom feed")
    items: list[FeedItem] = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.find(f"{ATOM}link")
        m = POSTING_ID_RE.search(link.get("href", "") if link is not None else "")
        if not m:
            continue
        fields: dict[str, str] = {}
        summary = entry.findtext(f"{ATOM}summary") or ""
        for part in re.split(r"<br\s*/?>", summary, flags=re.I):
            text = BeautifulSoup(part, "html.parser").get_text(" ")
            key, sep, value = text.partition(":")
            if sep:
                fields[_clean(key).lower() if _clean(key) else ""] = _clean(value) or ""
        city, province, postal = jobbank.split_location(fields.get("location"))
        updated = entry.findtext(f"{ATOM}updated") or ""
        day = updated[:10] if re.match(r"\d{4}-\d{2}-\d{2}", updated) else None
        items.append(FeedItem(
            posting_id=int(m.group(1)),
            title=_clean(entry.findtext(f"{ATOM}title")),
            employer=fields.get("employer") or None,
            city=city, province=province, postal_code=postal,
            salary_text=fields.get("salary") or None,
            date_posted=day,
        ))
    return items


def _badge(label) -> int | None:
    badge = label.select_one(".badge")
    if badge is None:
        return None
    for hidden in badge.select(".wb-inv"):
        hidden.decompose()
    digits = re.sub(r"[^\d-]", "", badge.get_text(""))
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def parse_facet_page(html: str) -> tuple[dict[str, int], bool]:
    """(counts, whether the international-candidates filter shows as applied) for the facet's first page."""
    soup = BeautifulSoup(html, "html.parser")
    counts: dict[str, int] = {}
    total = jobbank.parse_results_count(html)
    if total is not None:
        counts["total"] = total
    applied = False
    for label in soup.select("label.labelControl"):
        text = _clean(label.get_text(" ")) or ""
        name = re.sub(r"\s*\d[\d,\s-]*(jobs found)?\s*$", "", text).strip()
        for prefix, key in FACET_LABELS.items():
            if name.startswith(prefix) and key not in counts:
                value = _badge(label)
                if value is not None and value >= 0:
                    counts[key] = value
        if name.startswith(INTL_LABEL):
            box = soup.find("input", id=label.get("for")) if label.get("for") else None
            applied = applied or bool(box is not None and box.has_attr("checked"))
    return counts, applied


def parse_audience(soup: BeautifulSoup) -> tuple[str, str | None]:
    """The posting page's "Who can apply" as (audience, the list items joined by ' | ')."""
    block = soup.select_one("div.job-audience")
    if block is None:
        return "unknown", None
    items = [t for t in (_clean(li.get_text(" ")) for li in block.select("li")) if t]
    text = " ".join(items).lower()
    joined = " | ".join(items) or None
    if "other candidates" in text or "with or without a valid canadian work permit" in text:
        return "international", joined
    if "work permit" in text or "temporary resident" in text or "authorized" in text:
        return "authorized", joined
    if items and ("citizen" in text or "permanent resident" in text):
        return "canadians", joined
    return "unknown", joined


def parse_terms(soup: BeautifulSoup) -> tuple[str | None, int | None, int | None]:
    """(terms as read, full_time, permanent) from the page's employmentType; Nones when absent."""
    el = soup.find(attrs={"property": "employmentType"})
    if el is None:
        return None, None, None
    text = _clean(el.get_text(" ")) or ""
    low = text.lower()
    permanent = 1 if "permanent" in low else 0
    full_time = 1 if "full time" in low and "part time" not in low else 0
    return text or None, full_time, permanent


def posting_text(soup: BeautifulSoup) -> str:
    """The posting's own words: the JobPosting block without Job Bank's boilerplate."""
    main = soup.find(attrs={"typeof": "JobPosting"}) or soup
    for selector in BOILERPLATE:
        for el in main.select(selector):
            el.decompose()
    return re.sub(r"\s+", " ", main.get_text(" ")).strip()


def find_phrases(text: str, patterns: list[re.Pattern]) -> list[str]:
    """The distinct matched phrases, in order of appearance, at most MAX_PHRASES.

    Two patterns can match overlapping text ("support your permanent residence
    application"); the earlier match stands and the overlapping one is dropped.
    """
    hits: list[tuple[int, int, str]] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            hits.append((m.start(), m.end(), re.sub(r"\s+", " ", m.group(0)).strip()[:PHRASE_CHARS]))
    out: list[str] = []
    end = -1
    for start, stop, phrase in sorted(hits):
        if start < end:
            continue
        end = stop
        if phrase.lower() not in (p.lower() for p in out):
            out.append(phrase)
    return out[:MAX_PHRASES]


def parse_intl_detail(html: str) -> IntlFields:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["script", "style"]):
        el.decompose()
    f = IntlFields()
    f.audience, f.audience_text = parse_audience(soup)
    flag = soup.select_one("h1 .jobLMIAflag") or soup.select_one(".disclaimer.tfw")
    if flag is not None:
        f.lmia = "approved" if "approved" in flag.get_text(" ").lower() else "requested"
    f.employment_terms, f.full_time, f.permanent = parse_terms(soup)
    text = posting_text(soup)
    f.ee = find_phrases(text, EE_PATTERNS)
    f.pr = find_phrases(text, PR_PATTERNS)
    f.exempt = find_phrases(text, EXEMPT_PATTERNS)
    return f


# -- storing ----------------------------------------------------------------------


def _upsert(conn: sqlite3.Connection, *, posting_id: int, title: str | None, employer: str, city: str | None,
            province: str | None, postal_code: str | None, salary_text: str | None, date_posted: str | None,
            lmia_flag: str | None, found_by: str, stamp: str) -> bool:
    wage_min, wage_max, wage_unit = parse_salary_text(salary_text)
    existing = conn.execute("SELECT 1 FROM jobbank_intl_postings WHERE posting_id = ?", (posting_id,)).fetchone()
    conn.execute(
        """
        INSERT INTO jobbank_intl_postings (
          posting_id, employer_raw, title, city, province, postal_code, wage_min, wage_max, wage_unit, date_posted,
          first_seen, last_seen, found_by, in_facet, lmia, url, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(posting_id) DO UPDATE SET
          last_seen = excluded.last_seen,
          in_facet = 1,
          gone_at = NULL,
          title = COALESCE(jobbank_intl_postings.title, excluded.title),
          city = COALESCE(jobbank_intl_postings.city, excluded.city),
          province = COALESCE(jobbank_intl_postings.province, excluded.province),
          postal_code = COALESCE(jobbank_intl_postings.postal_code, excluded.postal_code),
          wage_min = COALESCE(jobbank_intl_postings.wage_min, excluded.wage_min),
          wage_max = COALESCE(jobbank_intl_postings.wage_max, excluded.wage_max),
          wage_unit = COALESCE(jobbank_intl_postings.wage_unit, excluded.wage_unit),
          date_posted = COALESCE(jobbank_intl_postings.date_posted, excluded.date_posted),
          lmia = CASE WHEN jobbank_intl_postings.lmia IN ('requested', 'approved') THEN jobbank_intl_postings.lmia
                      WHEN excluded.lmia IN ('requested', 'approved') THEN excluded.lmia
                      ELSE jobbank_intl_postings.lmia END,
          updated_at = excluded.updated_at
        """,
        (posting_id, employer, title, city, province, postal_code, wage_min, wage_max, wage_unit, date_posted,
         stamp, stamp, found_by, lmia_flag or "unknown", jobbank.posting_url(posting_id), stamp),
    )
    return existing is None


def _store(conn: sqlite3.Connection, stats: IntlStats, item, found_by: str, stamp: str, lmia_flag: str | None = None) -> None:
    stats.listed += 1
    if is_private_household(item.employer, item.title):
        stats.excluded += 1
        return
    if not item.employer:
        return
    if _upsert(conn, posting_id=item.posting_id, title=item.title, employer=item.employer, city=item.city,
               province=item.province, postal_code=item.postal_code, salary_text=item.salary_text,
               date_posted=item.date_posted, lmia_flag=lmia_flag, found_by=found_by, stamp=stamp):
        stats.new_postings += 1


def _mark_gone(conn: sqlite3.Connection, seen: set[int], stamp: str) -> int:
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS intl_seen (posting_id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM intl_seen")
    conn.executemany("INSERT OR IGNORE INTO intl_seen (posting_id) VALUES (?)", ((i,) for i in seen))
    cur = conn.execute(
        "UPDATE jobbank_intl_postings SET in_facet = 0, gone_at = ?, updated_at = ? "
        "WHERE in_facet = 1 AND posting_id NOT IN (SELECT posting_id FROM intl_seen)",
        (stamp, stamp),
    )
    conn.execute("DELETE FROM intl_seen")
    conn.commit()
    return cur.rowcount


def join_lmia(conn: sqlite3.Connection) -> int:
    """A posting the LMIA crawl saw keeps its marker: requested, or approved once Job Bank showed it approved."""
    cur = conn.execute(
        """
        UPDATE jobbank_intl_postings SET lmia = (
          SELECT CASE WHEN p.flag_first = 'approved' OR p.approved_seen_at IS NOT NULL THEN 'approved' ELSE 'requested' END
          FROM jobbank_postings p WHERE p.posting_id = jobbank_intl_postings.posting_id)
        WHERE posting_id IN (SELECT posting_id FROM jobbank_postings)
          AND lmia != (SELECT CASE WHEN p.flag_first = 'approved' OR p.approved_seen_at IS NOT NULL THEN 'approved' ELSE 'requested' END
                       FROM jobbank_postings p WHERE p.posting_id = jobbank_intl_postings.posting_id)
        """
    )
    conn.commit()
    return cur.rowcount


def resolve_employers(conn: sqlite3.Connection) -> int:
    """employer_id for each posting whose employer identity (name and province) names an existing employer.

    The id is computed as upsert_employer computes it, but no employer row is
    ever created here: a posting open to international candidates is not an
    LMIA record.
    """
    existing = {r[0] for r in conn.execute("SELECT id FROM employers")}
    changes = []
    for r in conn.execute("SELECT posting_id, employer_raw, province, employer_id FROM jobbank_intl_postings"):
        norm = norm_name((r["employer_raw"] or "").strip())
        eid = employer_id(norm, r["province"]) if norm else None
        eid = eid if eid in existing else None
        if eid != r["employer_id"]:
            changes.append((eid, r["posting_id"]))
    conn.executemany("UPDATE jobbank_intl_postings SET employer_id = ? WHERE posting_id = ?", changes)
    conn.commit()
    return len(changes)


def _store_detail(conn: sqlite3.Connection, posting_id: int, html: str, stamp: str) -> bool:
    """Write one posting page's fields; False when the page names a private household (the row is dropped)."""
    d = jobbank.parse_detail_page(html)
    f = parse_intl_detail(html)
    if is_private_household(d.employer, d.title):
        conn.execute("DELETE FROM jobbank_intl_postings WHERE posting_id = ?", (posting_id,))
        conn.commit()
        return False
    conn.execute(
        """
        UPDATE jobbank_intl_postings SET
          title = COALESCE(?, title), employer_raw = COALESCE(?, employer_raw), city = COALESCE(?, city),
          province = COALESCE(?, province), postal_code = COALESCE(?, postal_code),
          wage_min = COALESCE(?, wage_min), wage_max = COALESCE(?, wage_max), wage_unit = COALESCE(?, wage_unit),
          date_posted = COALESCE(?, date_posted), valid_through = ?, noc_code = COALESCE(?, noc_code),
          audience = ?, audience_text = ?,
          lmia = CASE WHEN lmia IN ('requested', 'approved') THEN lmia ELSE ? END,
          employment_terms = ?, full_time = ?, permanent = ?,
          ee_phrases = ?, pr_phrases = ?, exempt_phrases = ?,
          detail_fetched_at = ?, updated_at = ?
        WHERE posting_id = ?
        """,
        (d.title, d.employer, d.city, d.province, d.postal_code, d.wage_min, d.wage_max, d.wage_unit,
         d.date_posted, d.valid_through, d.noc_code, f.audience, f.audience_text, f.lmia,
         f.employment_terms, f.full_time, f.permanent,
         json.dumps(f.ee) if f.ee else None, json.dumps(f.pr) if f.pr else None,
         json.dumps(f.exempt) if f.exempt else None, stamp, stamp, posting_id),
    )
    conn.commit()
    return True


# -- run ----------------------------------------------------------------------------


def allowed(conn: sqlite3.Connection, *, force: bool = False, now: str | None = None) -> tuple[bool, str]:
    if force:
        return True, "forced"
    hours = hours_since(conn, "intl_last_run", now=now)
    if hours is not None and hours < MIN_HOURS:
        return False, f"last international-candidates pass was {hours:.1f} h ago"
    return True, "ok"


def sweep_due(conn: sqlite3.Connection, now: str | None = None) -> bool:
    hours = hours_since(conn, "intl_sweep_at", now=now)
    # A few hours of slack, so a run that starts a little earlier than last week's still sweeps.
    return hours is None or hours >= SWEEP_DAYS * 24 - 4


def run(
    conn: sqlite3.Connection,
    client: PoliteClient,
    *,
    detail_budget: int = DEFAULT_DETAIL_BUDGET,
    limit: int | None = None,
    force_sweep: bool = False,
    now: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> IntlStats:
    """One night's pass (see the module docstring). Never raises for the site; the reasons go to the stats and the log row."""
    stamp = now or now_iso()
    day = stamp[:10]
    started = clock()
    stats = IntlStats()
    aborted = False
    page_one: str | None = None

    try:
        page_one = client.get_text(search_url(1))
    except AbortRun as exc:
        stats.problems.append(f"facet page: {exc}")
        aborted = True
    except FetchError as exc:
        stats.problems.append(f"facet page: {exc}")
    applied = False
    if page_one is not None:
        stats.counts, applied = parse_facet_page(page_one)
        if not applied or "total" not in stats.counts:
            stats.problems.append("the search page did not show the international-candidates filter as applied "
                                  "(the fglo parameter changed?); nothing read from the facet tonight")
        else:
            conn.executemany(
                "INSERT INTO jobbank_facet_counts (day, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(day, key) DO UPDATE SET value = excluded.value",
                [(day, k, v) for k, v in sorted(stats.counts.items())],
            )
            conn.commit()
    facet_ok = page_one is not None and applied and "total" in stats.counts

    if facet_ok and not aborted:
        aborted = _read_feed(conn, client, stats, stamp)

    due = force_sweep or sweep_due(conn, stamp)
    if facet_ok and not aborted and (due or limit is not None):
        aborted = _sweep(conn, client, stats, stamp, page_one, limit=limit, started=started, clock=clock)
    elif due:
        stats.sweep = "skipped"

    if not aborted and detail_budget > 0:
        aborted = _read_details(conn, client, stats, stamp, detail_budget, deadline=clock() + DETAIL_BUDGET_S, clock=clock)

    join_lmia(conn)
    resolve_employers(conn)
    stats.grades = dict(intl.regrade(conn, now=stamp))
    if not aborted and facet_ok:
        previous = get_meta(conn, "intl_last_run")
        if previous and previous != stamp:
            set_meta(conn, "intl_prev_run", previous)
        set_meta(conn, "intl_last_run", stamp)
        conn.commit()
    log_run(conn, "jobbank_intl", detail=stats.summary()[:900], rows_in=stats.listed, rows_new=stats.new_postings,
            excluded=stats.excluded, ok=not stats.problems)
    return stats


def _read_feed(conn: sqlite3.Connection, client: PoliteClient, stats: IntlStats, stamp: str) -> bool:
    """Read the 48-hour feed (and the 48-hour pages when it is full). Returns True when the host stopped answering."""
    try:
        items = parse_feed(client.get_text(feed_url()))
    except AbortRun as exc:
        stats.problems.append(f"feed: {exc}")
        return True
    except (FetchError, ValueError) as exc:
        stats.problems.append(f"feed: {exc}")
        return False
    stats.feed_entries = len(items)
    for item in items:
        _store(conn, stats, item, "feed", stamp)
    conn.commit()
    if not items and stats.counts.get("last_48h", 0) > 0:
        stats.problems.append(f"the feed listed no entries while the search states {stats.counts['last_48h']} "
                              f"postings in the last 48 hours (feed changed?)")
    if len(items) < FEED_ROWS:
        return False
    # A full feed may have cut the day short: the 48-hour search pages hold the rest.
    for page in range(1, RECENT_MAX_PAGES + 1):
        try:
            listing = jobbank.parse_search_page(client.get_text(search_url(page, recent=True)))
        except AbortRun as exc:
            stats.problems.append(f"48-hour page {page}: {exc}")
            return True
        except FetchError as exc:
            stats.problems.append(f"48-hour page {page}: {exc}")
            return False
        if not listing:
            break
        stats.recent_pages += 1
        for item in listing:
            _store(conn, stats, item, "recent", stamp, item.lmia_flag)
        conn.commit()
    return False


def _sweep(conn: sqlite3.Connection, client: PoliteClient, stats: IntlStats, stamp: str, page_one: str | None, *,
           limit: int | None, started: float, clock: Callable[[], float]) -> bool:
    """Every page of the facet; marks postings gone only after a complete sweep. True when the host stopped answering."""
    seen: set[int] = set()
    expected = stats.counts.get("total")
    ended = False
    aborted = False
    page = 1
    while True:
        if limit is not None and page > limit:
            break
        if page > MAX_PAGES:
            stats.problems.append(f"sweep stopped at the {MAX_PAGES}-page cap")
            break
        if clock() - started > SWEEP_BUDGET_S:
            stats.problems.append(f"sweep stopped at page {page}, past the {SWEEP_BUDGET_S / 3600:.0f} h budget")
            break
        if page == 1 and page_one is not None:
            html = page_one
        else:
            try:
                html = client.get_text(search_url(page))
            except AbortRun as exc:
                stats.problems.append(f"sweep page {page}: {exc}")
                aborted = True
                break
            except FetchError as exc:
                stats.problems.append(f"sweep page {page}: {exc}")
                break
        items = jobbank.parse_search_page(html)
        if not items:
            ended = True
            break
        if all(item.posting_id in seen for item in items):
            stats.problems.append(f"sweep page {page} repeats earlier results")
            break
        stats.sweep_pages += 1
        for item in items:
            seen.add(item.posting_id)
            _store(conn, stats, item, "sweep", stamp, item.lmia_flag)
        conn.commit()
        page += 1
    complete = limit is None and ended and bool(seen) and not aborted and (
        expected is None or len(seen) >= COMPLETE_SHARE * expected)
    if limit is None and ended and expected and len(seen) < COMPLETE_SHARE * expected:
        stats.problems.append(f"sweep listed {len(seen)} of the {expected} results the search reported")
    if complete:
        stats.marked_gone = _mark_gone(conn, seen, stamp)
        set_meta(conn, "intl_sweep_at", stamp)
        if not get_meta(conn, "intl_baseline"):
            set_meta(conn, "intl_baseline", stamp[:10])
        conn.commit()
        stats.sweep = "complete"
    else:
        stats.sweep = "incomplete" if limit is None else "limited"
    return aborted


def _read_details(conn: sqlite3.Connection, client: PoliteClient, stats: IntlStats, stamp: str, budget: int, *,
                  deadline: float, clock: Callable[[], float]) -> bool:
    """Posting pages not read yet, newest first: by first sighting, then the feed's finds before the
    weekly sweep's on the same night, then Job Bank's posting date. So a posting that appears tonight
    is graded tonight, and the backlog of the first sweep fills in behind it. True when the host stopped
    answering."""
    rows = conn.execute(
        "SELECT posting_id FROM jobbank_intl_postings WHERE detail_fetched_at IS NULL AND in_facet = 1 "
        "ORDER BY first_seen DESC, CASE found_by WHEN 'sweep' THEN 1 ELSE 0 END, date_posted DESC, posting_id DESC "
        "LIMIT ?", (budget,)).fetchall()
    for row in rows:
        if clock() > deadline:
            stats.problems.append(f"posting pages stopped after {stats.details_fetched}, past the "
                                  f"{DETAIL_BUDGET_S / 60:.0f} min budget")
            return False
        try:
            html = client.get_text(jobbank.posting_url(row["posting_id"]))
        except AbortRun as exc:
            stats.problems.append(f"posting pages stopped after {stats.details_fetched}: {exc}")
            return True
        except Exception as exc:  # one missing page must not stop the pass
            log.warning("intl posting %s: %s", row["posting_id"], exc)
            conn.execute("UPDATE jobbank_intl_postings SET detail_fetched_at = ?, updated_at = ? WHERE posting_id = ?",
                         (stamp, stamp, row["posting_id"]))
            conn.commit()
            continue
        if not _store_detail(conn, row["posting_id"], html, stamp):
            stats.excluded += 1
        stats.details_fetched += 1
    return False


def digest_count(conn: sqlite3.Connection) -> int | None:
    """New postings since the previous pass, open to international candidates and with no LMIA requested.

    For the daily post. The weekly sweep's finds are left out (on its first
    night it is the whole facet), and so is a pass that found more than a
    rebuild's worth; None when there is nothing to say.
    """
    last = get_meta(conn, "intl_last_run")
    if not last:
        return None
    prev = get_meta(conn, "intl_prev_run")
    if prev and prev < last:
        where, args = "first_seen > ? AND first_seen <= ?", (prev, last)
    else:
        where, args = "first_seen = ?", (last,)
    n = conn.execute(
        f"SELECT COUNT(*) FROM jobbank_intl_postings WHERE {where} AND found_by IN ('feed', 'recent') "
        "AND lmia = 'none' AND audience = 'international'", args).fetchone()[0]
    return n if 0 < n <= 2000 else None
