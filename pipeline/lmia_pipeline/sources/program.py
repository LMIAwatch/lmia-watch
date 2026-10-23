"""Program conditions: what the Temporary Foreign Worker Program's own pages say is in force.

Three pages on canada.ca, each published by Employment and Social Development
Canada and reproduced under the canada.ca terms and conditions (non-commercial
reproduction with attribution, https://www.canada.ca/en/transparency/terms.html):

  processing_times  LMIA processing times by stream, the average business days
                    Service Canada took to decide the LMIAs it processed in the
                    month named in the table's caption. Updated monthly, about
                    five weeks after that month began. The minimum advertising
                    period before an application (14 days to 8 weeks) is not
                    counted in them; the page says so.
  cma_refusal       the unemployment rate ESDC applies to each census
                    metropolitan area for low-wage applications. A CMA at or
                    above the stated cut-off (6 percent) has its low-wage
                    applications refused for processing while that column is in
                    force. The table carries the current period and the two
                    before it; ESDC replaces a column every three months.
  wage_thresholds   the hourly wage threshold for each province and territory
                    (the median hourly wage plus 20 percent), which decides
                    whether an LMIA goes in the high-wage or the low-wage stream.
                    The table carries the edition in force and the one before.

Each page is read at most once a day (CHECK_EVERY_HOURS, kept in the database
because the nightly runner starts with an empty download cache), so a re-run of
a failed night asks canada.ca for nothing more.

An edition is one table column (or, for the processing times, the one table):
the period it covers, the dates it states, and its figures. Editions are never
overwritten. A read that finds the figures stored for a period adds nothing; a
read that finds them changed adds a new edition beside the old one, so the
history keeps what the page said and the day it was first read. A page whose
layout no longer matches raises ValueError: the stage is recorded as failed,
the stored editions stay as they were, and the rest of the night goes on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from bs4 import BeautifulSoup, Tag

from ..db import hours_since, log_run, now_iso, set_meta
from ..http import PoliteClient, decode_text

log = logging.getLogger(__name__)

CHECK_EVERY_HOURS = 20

TIMES = "processing_times"
CMA = "cma_refusal"
THRESHOLDS = "wage_thresholds"

# ESDC's own words for the streams on the processing-times page, folded to
# lower case. A stream not listed here is kept under a key made from its name,
# so a new row on the page is stored rather than dropped.
STREAM_KEYS = {
    "global talent stream": "global_talent",
    "agricultural stream": "agricultural",
    "seasonal agricultural worker program": "sawp",
    "high-wage stream": "high_wage",
    "low-wage stream": "low_wage",
    "permanent resident stream": "permanent_resident",
}

PROVINCE_CODES = {
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB",
    "newfoundland and labrador": "NL", "northwest territories": "NT", "nova scotia": "NS", "nunavut": "NU",
    "ontario": "ON", "prince edward island": "PE", "quebec": "QC", "québec": "QC", "saskatchewan": "SK", "yukon": "YT",
}
ALL_PROVINCES = frozenset(PROVINCE_CODES.values())

# 2021 Census CMA codes by the name the refusal table writes before the comma.
# Most rows link to Statistics Canada's map with the CMA's DGUID, which is read
# first; Ottawa-Gatineau has no link (Statistics Canada maps its two parts
# separately), and a row may lose its link in a later edit of the page.
CMA_CODES = {
    "St. John's": "001", "Halifax": "205", "Moncton": "305", "Saint John": "310", "Fredericton": "320",
    "Saguenay": "408", "Québec": "421", "Sherbrooke": "433", "Trois-Rivières": "442", "Drummondville": "447",
    "Montréal": "462", "Ottawa-Gatineau": "505", "Kingston": "521", "Belleville - Quinte West": "522",
    "Peterborough": "529", "Oshawa": "532", "Toronto": "535", "Hamilton": "537", "St. Catharines-Niagara": "539",
    "Kitchener-Cambridge-Waterloo": "541", "Brantford": "543", "Guelph": "550", "London": "555", "Windsor": "559",
    "Barrie": "568", "Greater Sudbury": "580", "Thunder Bay": "595", "Winnipeg": "602", "Regina": "705",
    "Saskatoon": "725", "Lethbridge": "810", "Calgary": "825", "Red Deer": "830", "Edmonton": "835",
    "Kelowna": "915", "Kamloops": "925", "Chilliwack": "930", "Abbotsford-Mission": "932", "Vancouver": "933",
    "Victoria": "935", "Nanaimo": "938",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
DATE_RE = re.compile(r"\b([A-Z][a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\b")
MONTH_YEAR_RE = re.compile(r"\b([A-Z][a-z]+)\s+(\d{4})\b")
DGUID_RE = re.compile(r"\d{4}S0503(\d{3})")
NUMBER_RE = re.compile(r"^\$?\s*(\d{1,4}(?:\.\d+)?)\s*%?$")
# A CMA list must name most of the 41 areas, or the table is not the one we know.
MIN_CMA_ROWS = 20
MIN_STREAMS = 3


@dataclass
class Figure:
    key: str
    label: str
    value: float


@dataclass
class Edition:
    period: str                    # 'YYYY-MM' for processing times, else the ISO date the edition took effect
    in_force_to: str | None        # the last day the page states, or None when it states none
    figures: list[Figure] = field(default_factory=list)
    threshold: float | None = None  # the cut-off the page states (the CMA list's 6 percent)

    def digest(self) -> str:
        # Labels stay out: a respelled stream or area name is not a new edition.
        body = {
            "period": self.period,
            "to": self.in_force_to,
            "threshold": self.threshold,
            "figures": sorted((f.key, f.value) for f in self.figures),
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass
class Page:
    editions: list[Edition]
    published: str | None          # the date the page gives for its last update


@dataclass
class Source:
    series: str
    stage: str
    url: str
    url_fr: str
    parse: Callable[[str], Page]


# -- helpers ---------------------------------------------------------------------

def _text(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ") if el is not None else "").strip()


def iso_date(text: str) -> str | None:
    """'July 17, 2026' -> '2026-07-17'; None when the text holds no such date."""
    m = DATE_RE.search(text or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, day, year = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def all_dates(text: str) -> list[str]:
    out = []
    for m in DATE_RE.finditer(text or ""):
        d = iso_date(m.group(0))
        if d:
            out.append(d)
    return out


def number(text: str) -> float | None:
    m = NUMBER_RE.match((text or "").replace(",", "").strip())
    return float(m.group(1)) if m else None


def page_modified(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", attrs={"name": "dcterms.modified"})
    if meta and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get("content") or "").strip()):
        return str(meta["content"]).strip()
    stamp = soup.find("gcds-date-modified")
    text = _text(stamp)
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def _find_table(soup: BeautifulSoup, test: Callable[[Tag], bool]) -> Tag | None:
    for table in soup.find_all("table"):
        if test(table):
            return table
    return None


def _header_cells(table: Tag) -> list[str]:
    head = table.find("thead")
    row = head.find("tr") if head else table.find("tr")
    return [_text(c) for c in row.find_all(["th", "td"])] if row else []


def _body_rows(table: Tag) -> list[Tag]:
    body = table.find("tbody")
    rows = (body or table).find_all("tr")
    return [r for r in rows if r.find("td")]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "row"


# -- the three parsers -------------------------------------------------------------

def parse_processing_times(html: str) -> Page:
    """One edition: the month in the caption and each stream's business days."""
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table(soup, lambda t: "processing time" in _text(t.find("caption")).lower())
    if table is None:
        raise ValueError("processing times: no table captioned with processing times")
    caption = _text(table.find("caption"))
    # The figures are business days; a caption that says otherwise is a
    # different measure, and storing it beside the old ones would mislead.
    if "business days" not in caption.lower():
        raise ValueError(f"processing times: the caption no longer says business days: {caption!r}")
    month = None
    for m in MONTH_YEAR_RE.finditer(caption):
        if m.group(1).lower() in MONTHS:
            month = f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
    if month is None:
        raise ValueError(f"processing times: no month in the caption {caption!r}")
    figures: list[Figure] = []
    seen: set[str] = set()
    for row in _body_rows(table):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = _text(cells[0])
        value = number(_text(cells[1]))
        if not label or value is None:
            continue  # a stream shown without a figure ("N/A") has nothing to store
        folded = re.sub(r"[‐-―]", "-", label.lower())
        key = STREAM_KEYS.get(folded, _slug(label))
        if key in seen:
            continue
        seen.add(key)
        figures.append(Figure(key, label, value))
    if len(figures) < MIN_STREAMS:
        raise ValueError(f"processing times: {len(figures)} streams with a figure, fewer than {MIN_STREAMS}")
    return Page([Edition(month, None, figures)], page_modified(soup))


def _cma_key(cell: Tag, label: str) -> str:
    link = cell.find("a")
    if link is not None:
        m = DGUID_RE.search(str(link.get("href") or ""))
        if m:
            return m.group(1)
    name = label.rsplit(",", 1)[0].strip() if "," in label else label
    return CMA_CODES.get(name) or f"name:{_slug(name)}"


def parse_cma_refusal(html: str) -> Page:
    """One edition per column: the dates it is in force and each CMA's rate."""
    soup = BeautifulSoup(html, "html.parser")

    def is_rates(table: Tag) -> bool:
        heads = " ".join(_header_cells(table)).lower()
        return "unemployment rate" in heads and "metropolitan" in heads

    table = _find_table(soup, is_rates)
    if table is None:
        raise ValueError("CMA list: no table of unemployment rates by census metropolitan area")
    found = re.search(r"unemployment rate of (\d+(?:\.\d+)?)\s*%\s*or higher", _text(soup), re.I)
    if not found:
        raise ValueError("CMA list: the page no longer states the unemployment rate at which processing stops")
    threshold = float(found.group(1))
    columns: list[Edition] = []
    for head in _header_cells(table)[1:]:
        dates = all_dates(head)
        if not dates:
            raise ValueError(f"CMA list: no date in the column heading {head!r}")
        columns.append(Edition(dates[0], dates[1] if len(dates) > 1 else None, threshold=threshold))
    if not columns:
        raise ValueError("CMA list: the table has no period columns")
    rows = 0
    for row in _body_rows(table):
        cells = row.find_all(["th", "td"])
        label = _text(cells[0]) if cells else ""
        if not label:
            continue
        key = _cma_key(cells[0], label)
        rows += 1
        for edition, cell in zip(columns, cells[1:]):
            value = number(_text(cell))
            # A rate ESDC does not publish leaves the area out of that column,
            # which is how the page treats it: eligible for processing.
            if value is not None and all(f.key != key for f in edition.figures):
                edition.figures.append(Figure(key, label, value))
    for edition in columns:
        if len(edition.figures) < MIN_CMA_ROWS:
            raise ValueError(f"CMA list: the column from {edition.period} has {len(edition.figures)} rates")
    updated = None
    for li in soup.find_all("li"):
        text = _text(li)
        if text.lower().startswith("last updated"):
            updated = iso_date(text)
            break
    return Page(columns, updated or page_modified(soup))


def parse_wage_thresholds(html: str) -> Page:
    """One edition per column: the date it took effect and the thirteen hourly thresholds."""
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table(soup, lambda t: "wage threshold" in _text(t.find("caption")).lower())
    if table is None:
        raise ValueError("wage thresholds: no table captioned with the hourly wage threshold")
    columns: list[Edition] = []
    for head in _header_cells(table)[1:]:
        dates = all_dates(head)
        lowered = head.lower()
        if len(dates) == 2 and "between" in lowered:
            columns.append(Edition(dates[0], dates[1]))
        elif len(dates) == 1 and any(word in lowered for word in ("as of", "from", "since", "on or after")):
            columns.append(Edition(dates[0], None))
        else:
            raise ValueError(f"wage thresholds: cannot read the dates in the column heading {head!r}")
    if not columns:
        raise ValueError("wage thresholds: the table has no period columns")
    for row in _body_rows(table):
        cells = row.find_all(["th", "td"])
        label = _text(cells[0])
        code = PROVINCE_CODES.get(label.lower())
        if code is None:
            continue
        for edition, cell in zip(columns, cells[1:]):
            value = number(_text(cell))
            if value is not None and all(f.key != code for f in edition.figures):
                edition.figures.append(Figure(code, label, value))
    for edition in columns:
        have = {f.key for f in edition.figures}
        if have != ALL_PROVINCES:
            missing = ", ".join(sorted(ALL_PROVINCES - have))
            raise ValueError(f"wage thresholds: the column from {edition.period} lacks {missing}")
    return Page(columns, page_modified(soup))


SOURCES: dict[str, Source] = {
    TIMES: Source(
        TIMES, "program_times",
        "https://www.canada.ca/en/employment-social-development/services/foreign-workers/"
        "labour-market-impact-assessment-processing-times.html",
        "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/"
        "delais-traitement-demandes-evaluation-impact-marche-travail.html",
        parse_processing_times,
    ),
    CMA: Source(
        CMA, "program_cma",
        "https://www.canada.ca/en/employment-social-development/services/foreign-workers/refusal.html",
        "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/refus.html",
        parse_cma_refusal,
    ),
    THRESHOLDS: Source(
        THRESHOLDS, "program_thresholds",
        "https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage.html",
        "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/salaire-moyen.html",
        parse_wage_thresholds,
    ),
}


# -- storage ------------------------------------------------------------------------

def store(conn: sqlite3.Connection, series: str, page: Page, *, source_url: str,
          now: str | None = None) -> tuple[int, int]:
    """Add each edition whose figures differ from the newest stored for its period.

    Returns (editions added, of which revisions of a period already stored).
    """
    stamp = now or now_iso()
    added = revised = 0
    for edition in page.editions:
        digest = edition.digest()
        last = conn.execute(
            "SELECT sha256 FROM program_editions WHERE series = ? AND period = ? ORDER BY id DESC LIMIT 1",
            (series, edition.period),
        ).fetchone()
        if last is not None and last["sha256"] == digest:
            continue
        cur = conn.execute(
            "INSERT INTO program_editions (series, period, in_force_to, threshold, published, source_url, read_at, "
            "sha256, items) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (series, edition.period, edition.in_force_to, edition.threshold, page.published, source_url, stamp,
             digest, len(edition.figures)),
        )
        conn.executemany(
            "INSERT INTO program_figures (edition_id, key, label, value) VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, f.key, f.label, f.value) for f in edition.figures],
        )
        added += 1
        if last is not None:
            revised += 1
            log.info("%s: the page revised the edition for %s", series, edition.period)
    return added, revised


def run(conn: sqlite3.Connection, client: PoliteClient, series: str, *, now: str | None = None) -> int:
    """Read one page and store what changed; returns editions added."""
    src = SOURCES[series]
    stamp = now or now_iso()
    checked_key = f"program_{series}_checked_at"
    have = conn.execute("SELECT COUNT(*) FROM program_editions WHERE series = ?", (series,)).fetchone()[0]
    hours = hours_since(conn, checked_key, now=stamp)
    if have and hours is not None and hours < CHECK_EVERY_HOURS:
        log_run(conn, src.stage, detail=f"skipped: checked {hours:.0f} h ago; editions={have}", rows_in=have)
        return 0
    # Always asked again (with the cached copy's ETag): how often the page is
    # read is decided above, from the database, not by the cache's age.
    data = client.get(src.url, cache=True, max_age_s=0)
    try:
        page = src.parse(decode_text(data))
    except Exception:
        # Drop the cached body so the next night downloads the page again
        # rather than revalidating a copy that could not be read.
        client.forget(src.url)
        raise
    added, revised = store(conn, series, page, source_url=src.url, now=stamp)
    set_meta(conn, checked_key, stamp)
    conn.commit()
    total, newest = conn.execute(
        "SELECT COUNT(*), MAX(period) FROM program_editions WHERE series = ?", (series,)
    ).fetchone()
    log_run(conn, src.stage,
            detail=f"editions={total} newest={newest} added_now={added} revised={revised} published={page.published}",
            rows_in=total, rows_new=added)
    return added


def run_times(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    return run(conn, client, TIMES, now=now)


def run_cma(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    return run(conn, client, CMA, now=now)


def run_thresholds(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    return run(conn, client, THRESHOLDS, now=now)


# -- reading back -----------------------------------------------------------------------

def editions(conn: sqlite3.Connection, series: str) -> list[dict]:
    """The newest edition of each period, newest period first, with its figures.

    `revisions` counts the earlier editions of the same period (a figure the
    page later changed); they stay in the database and are not shown.
    """
    rows = conn.execute(
        "SELECT id, period, in_force_to, threshold, published, source_url, read_at FROM program_editions "
        "WHERE series = ? ORDER BY period DESC, id DESC",
        (series,),
    ).fetchall()
    out: list[dict] = []
    seen: dict[str, dict] = {}
    for r in rows:
        if r["period"] in seen:
            seen[r["period"]]["revisions"] += 1
            continue
        figures = [
            {"key": f["key"], "label": f["label"], "value": f["value"]}
            for f in conn.execute("SELECT key, label, value FROM program_figures WHERE edition_id = ? ORDER BY rowid",
                                  (r["id"],))
        ]
        entry = {
            "period": r["period"],
            "to": r["in_force_to"],
            "threshold": r["threshold"],
            "published": r["published"],
            "source": r["source_url"],
            "read": (r["read_at"] or "")[:10],
            "figures": figures,
            "revisions": 0,
        }
        seen[r["period"]] = entry
        out.append(entry)
    return out
