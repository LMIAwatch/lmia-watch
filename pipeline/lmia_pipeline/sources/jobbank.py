"""Job Bank: postings that carry an LMIA flag.

Two search facets exist: 101010 (LMIA requested) and 101020 (approved LMIA).
The requested facet marks each result with a flag span; the approved facet's
results carry no marker at all, so the flag value comes from the facet that
returned the posting, never from the article markup.

Each run pages both facets completely. That is the only way to notice that a
posting's flag disappeared, which is what happens when a decision lands.
Posting pages are fetched only for postings never fetched before, within a
per-run budget, so the first backfill spreads over several nights inside the
five-second crawl delay. Nothing about how to apply, and no contact detail,
is ever read from a posting.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .. import config
from ..db import log_run, now_iso, set_meta, upsert_employer
from ..exclusions import is_private_household
from ..http import PoliteClient
from ..normalize import POSTAL_RE, format_postal, parse_jobbank_date, parse_salary_text

log = logging.getLogger(__name__)

FACETS: dict[str, str] = {"101010": "requested", "101020": "approved"}
ARTICLE_ID_RE = re.compile(r"article-(\d+)")
LOCATION_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2})\)\s*$", re.S)
VACANCY_RE = re.compile(r"(\d+)\s+vacanc", re.I)
NOC_TEXT_RE = re.compile(r"\bNOC\s+(\d{4,5})\b")


@dataclass
class ListItem:
    posting_id: int
    title: str | None
    employer: str | None
    city: str | None
    province: str | None
    date_posted: str | None
    salary_text: str | None


@dataclass
class DetailFields:
    title: str | None = None
    employer: str | None = None
    street: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    wage_min: float | None = None
    wage_max: float | None = None
    wage_unit: str | None = None
    vacancies: int | None = None
    date_posted: str | None = None
    valid_through: str | None = None
    noc_code: str | None = None
    status_text: str | None = None


@dataclass
class RunStats:
    pages: int = 0
    listed: int = 0
    excluded: int = 0
    new_postings: int = 0
    details_fetched: int = 0
    marked_gone: int = 0


def search_url(facet: str, page: int) -> str:
    return (
        f"{config.JOBBANK_BASE}/jobsearch/jobsearch?searchstring=&locationstring="
        f"&sort=D&fskl={facet}&page={page}"
    )


def posting_url(posting_id: int) -> str:
    return f"{config.JOBBANK_BASE}/jobsearch/jobposting/{posting_id}"


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


# -- parsing ----------------------------------------------------------------


def parse_search_page(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ListItem] = []
    for article in soup.find_all("article", id=ARTICLE_ID_RE):
        m = ARTICLE_ID_RE.search(article.get("id", ""))
        if not m:
            continue
        title = article.select_one(".noctitle")
        business = article.select_one(".business")
        date_el = article.select_one(".date")
        salary = article.select_one(".salary")
        location = article.select_one(".location")
        city = province = None
        if location is not None:
            for hidden in location.select(".wb-inv"):
                hidden.decompose()
            loc_text = _clean(location.get_text(" ")) or ""
            lm = LOCATION_RE.match(loc_text)
            if lm:
                city, province = _clean(lm.group(1)), lm.group(2)
            else:
                city = loc_text or None
        salary_text = None
        if salary is not None:
            salary_text = _clean(re.sub(r"^\s*Salary\s*", "", salary.get_text(" "), flags=re.I))
        items.append(
            ListItem(
                posting_id=int(m.group(1)),
                title=_clean(title.get_text(" ")) if title else None,
                employer=_clean(business.get_text(" ")) if business else None,
                city=city,
                province=province,
                date_posted=parse_jobbank_date(date_el.get_text(" ")) if date_el else None,
                salary_text=salary_text,
            )
        )
    return items


def _prop(soup: BeautifulSoup, name: str) -> str | None:
    el = soup.find(attrs={"property": name})
    if el is None:
        return None
    # Accessibility-only text ("This link will open in a new window") sits
    # inside the same element as the value.
    for hidden in el.select(".wb-inv"):
        hidden.decompose()
    return _clean(el.get_text(" "))


def parse_detail_page(html: str) -> DetailFields:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all(["script", "style"]):
        script.decompose()
    f = DetailFields()
    f.title = _prop(soup, "title")
    f.employer = _prop(soup, "hiringOrganization")
    f.street = _prop(soup, "streetAddress")
    f.city = _prop(soup, "addressLocality")
    f.province = _prop(soup, "addressRegion")
    postal = _prop(soup, "postalCode")
    if postal:
        pm = POSTAL_RE.search(postal)
        f.postal_code = format_postal(pm.group(1), pm.group(2)) if pm else postal.upper()
    min_v, max_v = _prop(soup, "minValue"), _prop(soup, "maxValue")
    try:
        f.wage_min = float(min_v.replace(",", "")) if min_v else None
        f.wage_max = float(max_v.replace(",", "")) if max_v else f.wage_min
    except ValueError:
        f.wage_min = f.wage_max = None
    f.wage_unit = _prop(soup, "unitText")
    f.date_posted = parse_jobbank_date(_prop(soup, "datePosted"))
    valid = _prop(soup, "validThrough")
    if valid:
        vm = re.search(r"\d{4}-\d{2}-\d{2}", valid)
        f.valid_through = vm.group(0) if vm else parse_jobbank_date(valid)
    text = soup.get_text(" ")
    vm2 = VACANCY_RE.search(text)
    f.vacancies = int(vm2.group(1)) if vm2 else None
    nm = NOC_TEXT_RE.search(text)
    f.noc_code = nm.group(1) if nm else None
    lowered = text.lower()
    if "currently under review" in lowered:
        f.status_text = "under review"
    elif "approved labour market impact assessment" in lowered:
        f.status_text = "approved"
    return f


# -- run --------------------------------------------------------------------


def run(
    conn: sqlite3.Connection,
    client: PoliteClient,
    *,
    limit: int | None = None,
    detail_budget: int = 600,
    now: str | None = None,
) -> RunStats:
    stamp = now or now_iso()
    stats = RunStats()
    seen: set[int] = set()

    for facet, flag in FACETS.items():
        page = 1
        while True:
            if limit is not None and page > limit:
                break
            html = client.get_text(search_url(facet, page))
            items = parse_search_page(html)
            if not items:
                break
            stats.pages += 1
            for item in items:
                stats.listed += 1
                if is_private_household(item.employer, item.title):
                    stats.excluded += 1
                    continue
                if not item.employer:
                    continue
                seen.add(item.posting_id)
                if _upsert_listing(conn, item, flag, facet, stamp):
                    stats.new_postings += 1
            conn.commit()
            page += 1

    # A capped dev run has not seen the whole feed, so it must not declare
    # everything it missed as gone.
    if limit is None and seen:
        placeholders = ",".join("?" * len(seen))
        cur = conn.execute(
            f"UPDATE jobbank_postings SET flag_current = 'gone', updated_at = ? "
            f"WHERE flag_current != 'gone' AND posting_id NOT IN ({placeholders})",
            (stamp, *seen),
        )
        stats.marked_gone = cur.rowcount
        conn.commit()

    stats.details_fetched = _fetch_details(conn, client, detail_budget, stamp)
    set_meta(conn, "jobbank_last_run", stamp)
    log_run(
        conn,
        "jobbank",
        detail=(
            f"pages={stats.pages} listed={stats.listed} new={stats.new_postings} "
            f"details={stats.details_fetched} gone={stats.marked_gone}"
        ),
        rows_in=stats.listed,
        rows_new=stats.new_postings,
        excluded=stats.excluded,
    )
    return stats


def _upsert_listing(
    conn: sqlite3.Connection, item: ListItem, flag: str, facet: str, stamp: str
) -> bool:
    eid = upsert_employer(
        conn, item.employer or "", item.province, source="jobbank", city=item.city, now=stamp
    )
    wage_min, wage_max, wage_unit = parse_salary_text(item.salary_text)
    existing = conn.execute(
        "SELECT posting_id FROM jobbank_postings WHERE posting_id = ?", (item.posting_id,)
    ).fetchone()
    conn.execute(
        """
        INSERT INTO jobbank_postings (
          posting_id, employer_id, employer_raw, title, city, province,
          wage_min, wage_max, wage_unit, date_posted, first_seen, last_seen,
          flag_current, flag_first, approved_seen_at, url, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(posting_id) DO UPDATE SET
          last_seen = excluded.last_seen,
          title = COALESCE(excluded.title, jobbank_postings.title),
          employer_raw = excluded.employer_raw,
          employer_id = excluded.employer_id,
          city = COALESCE(jobbank_postings.city, excluded.city),
          province = COALESCE(jobbank_postings.province, excluded.province),
          wage_min = COALESCE(jobbank_postings.wage_min, excluded.wage_min),
          wage_max = COALESCE(jobbank_postings.wage_max, excluded.wage_max),
          wage_unit = COALESCE(jobbank_postings.wage_unit, excluded.wage_unit),
          date_posted = COALESCE(jobbank_postings.date_posted, excluded.date_posted),
          flag_current = excluded.flag_current,
          approved_seen_at = COALESCE(jobbank_postings.approved_seen_at, excluded.approved_seen_at),
          updated_at = excluded.updated_at
        """,
        (
            item.posting_id, eid, item.employer, item.title, item.city, item.province,
            wage_min, wage_max, wage_unit, item.date_posted, stamp, stamp,
            flag, flag, stamp if flag == "approved" else None, posting_url(item.posting_id), stamp,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO jobbank_observations (posting_id, observed_at, flag, facet) "
        "VALUES (?, ?, ?, ?)",
        (item.posting_id, stamp, flag, facet),
    )
    return existing is None


def _fetch_details(
    conn: sqlite3.Connection, client: PoliteClient, budget: int, stamp: str
) -> int:
    if budget <= 0:
        return 0
    rows = conn.execute(
        """
        SELECT posting_id, employer_id FROM jobbank_postings
        WHERE detail_fetched_at IS NULL AND flag_current != 'gone'
        ORDER BY date_posted DESC, posting_id DESC LIMIT ?
        """,
        (budget,),
    ).fetchall()
    fetched = 0
    for row in rows:
        try:
            html = client.get_text(posting_url(row["posting_id"]))
        except Exception as exc:  # one missing page must not stop the run
            log.warning("posting %s: %s", row["posting_id"], exc)
            conn.execute(
                "UPDATE jobbank_postings SET detail_fetched_at = ?, updated_at = ? WHERE posting_id = ?",
                (stamp, stamp, row["posting_id"]),
            )
            conn.commit()
            continue
        f = parse_detail_page(html)
        conn.execute(
            """
            UPDATE jobbank_postings SET
              title = COALESCE(?, title), street = ?, city = COALESCE(?, city),
              province = COALESCE(?, province), postal_code = ?,
              wage_min = COALESCE(?, wage_min), wage_max = COALESCE(?, wage_max),
              wage_unit = COALESCE(?, wage_unit), vacancies = ?,
              date_posted = COALESCE(?, date_posted), valid_through = ?,
              noc_code = ?, detail_fetched_at = ?, updated_at = ?
            WHERE posting_id = ?
            """,
            (
                f.title, f.street, f.city, f.province, f.postal_code,
                f.wage_min, f.wage_max, f.wage_unit, f.vacancies,
                f.date_posted, f.valid_through, f.noc_code, stamp, stamp, row["posting_id"],
            ),
        )
        if f.postal_code or f.street:
            conn.execute(
                """
                UPDATE employers SET
                  postal_code = COALESCE(postal_code, :postal),
                  -- a posting page outranks an IRCC finding as the source of a street
                  street_source = CASE WHEN :street IS NOT NULL AND (street IS NULL OR street_source = 'ircc')
                                       THEN 'jobbank' ELSE street_source END,
                  street = CASE WHEN :street IS NOT NULL AND (street IS NULL OR street_source = 'ircc')
                                THEN :street ELSE street END,
                  city = COALESCE(city, :city),
                  updated_at = :stamp
                WHERE id = :id
                """,
                {"postal": f.postal_code, "street": f.street, "city": f.city, "stamp": stamp,
                 "id": row["employer_id"]},
            )
        fetched += 1
        conn.commit()
    return fetched
