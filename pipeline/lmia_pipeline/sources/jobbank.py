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
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable

from bs4 import BeautifulSoup

from .. import config
from ..db import get_meta, log_run, now_iso, set_meta, upsert_employer
from ..exclusions import is_private_household
from ..http import AbortRun, FetchError, PoliteClient
from ..normalize import (
    POSTAL_RE, PROVINCE_CODES, format_postal, parse_jobbank_date, parse_salary_text, province_code,
)

log = logging.getLogger(__name__)

FACETS: dict[str, str] = {"101010": "requested", "101020": "approved"}
ARTICLE_ID_RE = re.compile(r"article-(\d+)")
LOCATION_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2})\)\s*$", re.S)
VACANCY_RE = re.compile(r"(\d[\d,]*)\s+vacanc", re.I)
NOC_TEXT_RE = re.compile(r"\bNOC\s+(\d{4,5})\b")
RESULTS_COUNT_RE = re.compile(r'id="results-count"[^>]*>\s*([\d,\s]+?)\s*<')

# Bounds on one pass, so a changed or failing site ends the stage with a
# logged outcome instead of running into the job's time limit. A results page
# lists 25 postings, so the page cap is 25,000 postings a facet, about four
# times the whole feed in 2026. The time budgets are several times a normal
# night (list pages about 25 minutes, 400 posting pages about 35).
MAX_PAGES = 1000
LIST_BUDGET_S = 3 * 3600.0
DETAIL_BUDGET_S = 4 * 3600.0
# A facet's sweep counts as complete when it ends on an empty page and has
# listed at least this share of the result count shown on its first page
# (postings come and go during the sweep, so the two never match exactly).
COMPLETE_SHARE = 0.9
MAX_VACANCIES = 1_000_000


@dataclass
class ListItem:
    posting_id: int
    title: str | None
    employer: str | None
    city: str | None
    province: str | None
    date_posted: str | None
    salary_text: str | None
    postal_code: str | None = None


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
    locations_fixed: int = 0    # stored provinces repair_locations turned into a code
    complete: bool = True       # every facet swept to its end; only then is anything marked gone
    problems: list[str] = field(default_factory=list)


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


def _date(raw: str | None) -> str | None:
    """parse_jobbank_date, with an impossible date ("February 30") read as no date."""
    try:
        return parse_jobbank_date(raw)
    except ValueError:
        return None


def parse_results_count(html: str) -> int | None:
    """The result count a search page states above its list ("5,883 results"); None when absent."""
    m = RESULTS_COUNT_RE.search(html)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def _province(text: str | None) -> str | None:
    """normalize.province_code kept to the thirteen codes: a Job Bank posting is in Canada,
    and any other value would be repaired again every night by repair_locations."""
    code = province_code(text)
    return code if code in PROVINCE_CODES else None


def _take_postal(text: str) -> tuple[str, str | None]:
    """(the text without its postal code, the postal code in 'A1A 1A1' form or None)."""
    pm = POSTAL_RE.search(text)
    if not pm:
        return text, None
    return _clean(text[: pm.start()] + " " + text[pm.end():]) or "", format_postal(pm.group(1), pm.group(2))


def split_region(raw: str | None) -> tuple[str | None, str | None]:
    """A posting page's addressRegion text as (province code, postal code), each None when absent.

    Some posting pages hold the comma before the province, and sometimes the
    postal code after it, inside the region element: ", ON", ", AB T2C 2Z2".
    Stored as read, that text replaced the listing's code (the posting-page
    update outranks the listing) and split the province filters, the place
    pages and the search database's province column.
    """
    text = _clean(raw)
    if not text:
        return None, None
    text, postal = _take_postal(text)
    parts = [p for p in (_clean(s) for s in text.split(",")) if p]
    return (_province(parts[-1].strip(" .()")) if parts else None), postal


def split_location(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """A search result's location as (city, province code, postal code).

    Job Bank writes "Sept-Îles (QC)". The comma form ("Sudbury, ON", with or
    without a postal code) is read as well, so that neither the comma nor a
    postal code can reach the province or stay in the city.
    """
    text = _clean(raw)
    if not text:
        return None, None, None
    text, postal = _take_postal(text)
    lm = LOCATION_RE.match(text)
    if lm:
        return _clean(lm.group(1)), _province(lm.group(2)), postal
    head, sep, tail = text.rpartition(",")
    province = _province(tail.strip(" .()")) if sep else None
    if province and _clean(head):
        return _clean(head), province, postal
    return text or None, None, postal


def parse_search_page(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ListItem] = []
    for article in soup.find_all("article", id=ARTICLE_ID_RE):
        m = ARTICLE_ID_RE.search(article.get("id", ""))
        # Posting ids are eight digits; anything past fifteen would not fit
        # the database's integer column.
        if not m or len(m.group(1)) > 15:
            continue
        title = article.select_one(".noctitle")
        business = article.select_one(".business")
        date_el = article.select_one(".date")
        salary = article.select_one(".salary")
        location = article.select_one(".location")
        city = province = postal_code = None
        if location is not None:
            for hidden in location.select(".wb-inv"):
                hidden.decompose()
            city, province, postal_code = split_location(location.get_text(" "))
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
                date_posted=_date(date_el.get_text(" ")) if date_el else None,
                salary_text=salary_text,
                postal_code=postal_code,
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
    f.province, region_postal = split_region(_prop(soup, "addressRegion"))
    postal = _prop(soup, "postalCode")
    if postal:
        pm = POSTAL_RE.search(postal)
        f.postal_code = format_postal(pm.group(1), pm.group(2)) if pm else postal.upper()
    if f.postal_code is None:
        f.postal_code = region_postal
    min_v, max_v = _prop(soup, "minValue"), _prop(soup, "maxValue")
    try:
        f.wage_min = float(min_v.replace(",", "")) if min_v else None
        f.wage_max = float(max_v.replace(",", "")) if max_v else f.wage_min
    except ValueError:
        f.wage_min = f.wage_max = None
    # "Infinity" and "1e999" parse as floats; an infinite wage would be written
    # into the site's JSON as a token no browser can read.
    if not all(v is None or math.isfinite(v) for v in (f.wage_min, f.wage_max)):
        f.wage_min = f.wage_max = None
    f.wage_unit = _prop(soup, "unitText")
    f.date_posted = _date(_prop(soup, "datePosted"))
    valid = _prop(soup, "validThrough")
    if valid:
        vm = re.search(r"\d{4}-\d{2}-\d{2}", valid)
        f.valid_through = vm.group(0) if vm else _date(valid)
    text = soup.get_text(" ")
    vm2 = VACANCY_RE.search(text)
    f.vacancies = int(vm2.group(1).replace(",", "")) if vm2 else None
    if f.vacancies is not None and f.vacancies > MAX_VACANCIES:
        f.vacancies = None  # not a count a posting could carry; also past the integer column
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
    clock: Callable[[], float] = time.monotonic,
) -> RunStats:
    """One pass over both facets, then posting pages within the budget.

    Never raises for a failing or changed site: a page that cannot be
    fetched, a pager that repeats itself or never ends, a layout the parser
    no longer reads, or a host that stops answering ends the sweep where it
    is, records the reason, and leaves every posting it did not see as it
    was. Only a complete sweep marks postings gone and records the pass as
    the day's (jobbank_last_run), which is what the daily digest counts.
    """
    stamp = now or now_iso()
    started = clock()
    stats = RunStats()
    seen: set[int] = set()
    aborted = False
    # Before the sweep, so rows stored by an older parser are repaired even
    # on a night Job Bank does not answer.
    repaired = repair_locations(conn, now=stamp)
    stats.locations_fixed = repaired["postings"]

    for facet, flag in FACETS.items():
        if aborted:
            stats.complete = False
            break
        facet_ids: set[int] = set()
        no_employer = 0
        expected: int | None = None
        ended = False
        page = 1
        while True:
            if limit is not None and page > limit:
                break
            if page > MAX_PAGES:
                stats.problems.append(f"{flag}: stopped at the {MAX_PAGES}-page cap")
                break
            if clock() - started > LIST_BUDGET_S:
                stats.problems.append(f"{flag}: list pages stopped at page {page}, past the {LIST_BUDGET_S / 3600:.0f} h budget")
                break
            try:
                html = client.get_text(search_url(facet, page))
            except AbortRun as exc:
                stats.problems.append(f"{flag} page {page}: {exc}")
                aborted = True
                break
            except FetchError as exc:
                stats.problems.append(f"{flag} page {page}: {exc}")
                break
            if page == 1:
                expected = parse_results_count(html)
            items = parse_search_page(html)
            if not items:
                ended = True
                break
            if all(item.posting_id in facet_ids for item in items):
                stats.problems.append(f"{flag}: page {page} repeats earlier results")
                break
            stats.pages += 1
            for item in items:
                facet_ids.add(item.posting_id)
                stats.listed += 1
                if is_private_household(item.employer, item.title):
                    stats.excluded += 1
                    continue
                if not item.employer:
                    no_employer += 1
                    continue
                seen.add(item.posting_id)
                if _upsert_listing(conn, item, flag, facet, stamp):
                    stats.new_postings += 1
            conn.commit()
            page += 1

        if limit is not None:
            continue
        listed = len(facet_ids)
        if not ended:
            stats.complete = False
        elif expected == 0:
            pass
        elif listed == 0:
            stats.complete = False
            stats.problems.append(f"{flag}: the first results page listed no postings (page layout changed?)")
        elif expected is not None and listed < COMPLETE_SHARE * expected:
            stats.complete = False
            stats.problems.append(f"{flag}: listed {listed} of the {expected} results the search reported")
        if listed and no_employer * 2 > listed:
            stats.complete = False
            stats.problems.append(f"{flag}: no employer name on {no_employer} of {listed} results (page layout changed?)")

    full_pass = limit is None and stats.complete and not aborted
    # A capped dev run, or a sweep that stopped short, has not seen the whole
    # feed, so it must not declare everything it missed as gone.
    if full_pass and seen:
        stats.marked_gone = _mark_gone(conn, seen, stamp)

    if not aborted:
        stats.details_fetched, problem = _fetch_details(
            conn, client, detail_budget, stamp, deadline=started + DETAIL_BUDGET_S, clock=clock,
        )
        if problem:
            stats.problems.append(problem)
    if limit is not None or full_pass:
        # The daily digest counts every posting first seen since the previous
        # complete pass, so what a sweep that stopped short stored rolls into
        # the next night's post instead of never being counted.
        previous = get_meta(conn, "jobbank_last_run")
        if previous and previous != stamp:
            set_meta(conn, "jobbank_prev_run", previous)
        set_meta(conn, "jobbank_last_run", stamp)
    detail = (
        f"pages={stats.pages} listed={stats.listed} new={stats.new_postings} "
        f"details={stats.details_fetched} gone={stats.marked_gone}"
    )
    if repaired["postings"]:
        detail += f" provinces_fixed={repaired['postings']} postal_codes_moved={repaired['postal_codes']}"
    if repaired["employers_not_codes"]:
        detail += f" employer_provinces_not_codes={repaired['employers_not_codes']}"
    if stats.problems:
        detail += " problems=" + "; ".join(stats.problems)[:700]
    log_run(
        conn,
        "jobbank",
        detail=detail,
        rows_in=stats.listed,
        rows_new=stats.new_postings,
        excluded=stats.excluded,
        ok=not stats.problems,
    )
    return stats


def repair_locations(conn: sqlite3.Connection, *, now: str | None = None) -> dict[str, int]:
    """Turn every stored posting province that is not a two-letter code into one.

    Idempotent, like esdc.remove_summary_rows: the jobbank stage runs it before
    every pass, and once each province is a code (or NULL) it finds nothing.
    The values came from posting pages whose region text held the comma and
    sometimes the postal code (split_region). A postal code found there fills
    the posting's blank postal code, and its employer's, as the posting page
    would have. When the text holds no province, the employer's code stands
    in: it came from the search listing, which only ever wrote a code.

    Employers are never re-keyed here. An employer id hashes its province, and
    upsert_employer only ever received the listing's code, so a value in the
    employers table that is not a code did not come from this fault; those
    are counted (employers_not_codes) and left alone.
    """
    stamp = now or now_iso()
    codes = sorted(PROVINCE_CODES)
    marks = ",".join("?" * len(codes))
    rows = conn.execute(
        "SELECT p.posting_id, p.province, p.postal_code, p.employer_id, e.province AS employer_province "
        "FROM jobbank_postings p LEFT JOIN employers e ON e.id = p.employer_id "
        f"WHERE p.province IS NOT NULL AND p.province NOT IN ({marks})",
        codes,
    ).fetchall()
    moved = 0
    for r in rows:
        code, found = split_region(r["province"])
        if code is None and r["employer_province"] in PROVINCE_CODES:
            code = r["employer_province"]
        fill = found if found and not r["postal_code"] else None
        conn.execute(
            "UPDATE jobbank_postings SET province = ?, postal_code = COALESCE(postal_code, ?), updated_at = ? "
            "WHERE posting_id = ?",
            (code, fill, stamp, r["posting_id"]),
        )
        if fill:
            moved += 1
            conn.execute(
                "UPDATE employers SET postal_code = ?, updated_at = ? WHERE id = ? AND postal_code IS NULL",
                (fill, stamp, r["employer_id"]),
            )
    # 'XX' (head office outside Canada) is a code ESDC's lists use.
    odd = conn.execute(
        f"SELECT COUNT(*) FROM employers WHERE province IS NOT NULL AND province != 'XX' AND province NOT IN ({marks})",
        codes,
    ).fetchone()[0]
    conn.commit()
    return {"postings": len(rows), "postal_codes": moved, "employers_not_codes": odd}


def _mark_gone(conn: sqlite3.Connection, seen: set[int], stamp: str) -> int:
    # Through a temporary table rather than NOT IN (?, ?, ...): SQLite caps the
    # number of bound parameters, and the feed only grows.
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS jobbank_seen (posting_id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM jobbank_seen")
    conn.executemany("INSERT OR IGNORE INTO jobbank_seen (posting_id) VALUES (?)", ((i,) for i in seen))
    cur = conn.execute(
        "UPDATE jobbank_postings SET flag_current = 'gone', updated_at = ? "
        "WHERE flag_current != 'gone' AND posting_id NOT IN (SELECT posting_id FROM jobbank_seen)",
        (stamp,),
    )
    conn.execute("DELETE FROM jobbank_seen")
    conn.commit()
    return cur.rowcount


def _upsert_listing(
    conn: sqlite3.Connection, item: ListItem, flag: str, facet: str, stamp: str
) -> bool:
    eid = upsert_employer(
        conn, item.employer or "", item.province, source="jobbank", city=item.city,
        postal_code=item.postal_code, now=stamp,
    )
    wage_min, wage_max, wage_unit = parse_salary_text(item.salary_text)
    existing = conn.execute(
        "SELECT posting_id FROM jobbank_postings WHERE posting_id = ?", (item.posting_id,)
    ).fetchone()
    conn.execute(
        """
        INSERT INTO jobbank_postings (
          posting_id, employer_id, employer_raw, title, city, province, postal_code,
          wage_min, wage_max, wage_unit, date_posted, first_seen, last_seen,
          flag_current, flag_first, approved_seen_at, url, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(posting_id) DO UPDATE SET
          last_seen = excluded.last_seen,
          title = COALESCE(excluded.title, jobbank_postings.title),
          employer_raw = excluded.employer_raw,
          employer_id = excluded.employer_id,
          city = COALESCE(jobbank_postings.city, excluded.city),
          province = COALESCE(jobbank_postings.province, excluded.province),
          postal_code = COALESCE(jobbank_postings.postal_code, excluded.postal_code),
          wage_min = COALESCE(jobbank_postings.wage_min, excluded.wage_min),
          wage_max = COALESCE(jobbank_postings.wage_max, excluded.wage_max),
          wage_unit = COALESCE(jobbank_postings.wage_unit, excluded.wage_unit),
          date_posted = COALESCE(jobbank_postings.date_posted, excluded.date_posted),
          flag_current = excluded.flag_current,
          approved_seen_at = COALESCE(jobbank_postings.approved_seen_at, excluded.approved_seen_at),
          updated_at = excluded.updated_at
        """,
        (
            item.posting_id, eid, item.employer, item.title, item.city, item.province, item.postal_code,
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
    conn: sqlite3.Connection, client: PoliteClient, budget: int, stamp: str,
    *, deadline: float = float("inf"), clock: Callable[[], float] = time.monotonic,
) -> tuple[int, str | None]:
    """Posting pages fetched, and why the loop stopped early (None when it did not)."""
    if budget <= 0:
        return 0, None
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
        if clock() > deadline:
            return fetched, f"posting pages stopped after {fetched}, past the {DETAIL_BUDGET_S / 3600:.0f} h budget"
        try:
            html = client.get_text(posting_url(row["posting_id"]))
        except AbortRun as exc:
            # The host stopped answering: stop asking. The posting is left
            # unfetched so a later night tries it again.
            return fetched, f"posting pages stopped after {fetched}: {exc}"
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
              province = COALESCE(?, province), postal_code = COALESCE(?, postal_code),
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
    return fetched, None
