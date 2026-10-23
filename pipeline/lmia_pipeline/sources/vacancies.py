"""Statistics Canada job vacancies and offered wages by occupation and economic region.

Source: table 14-10-0444-01, "Job vacancies and average offered hourly wage by
occupation (unit group), quarterly, unadjusted for seasonality", from the Job
Vacancy and Wage Survey, under the Statistics Canada Open Licence
(https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410044401). The full
table is one zipped CSV (URL below): about 100 MB, 1.2 GB unzipped, six million
rows from 2015 on for Canada, the provinces and the economic regions, every NOC
2021 level, and two statistics. The keyless WDS API would need one request per
few hundred series (137,000 series), so the zip is read instead, once a month
at most: the date of the last check is kept in the database, because the
nightly runner starts with an empty download cache, and an unchanged file
(same SHA-256) is not parsed again. The survey publishes a quarter about
eleven weeks after it ends (2026 Q2 on 2026-09-15).

Only the five-digit unit groups and the all-occupations total are kept, for
the newest eight quarters in the file, so every occupation and region keeps
at most its newest eight quarters. The file is sorted by reference month, and
the metadata file inside the archive gives the last one, so older lines are
skipped before they are parsed. Values Statistics Canada suppresses (quality
F, confidential "x", not available "..") are left out; a quality letter A to E
comes with each published value. Seven pairs of small economic regions are
published only together; such a figure is stored under both member regions'
codes, so a lookup by a postal area's economic region finds it.

The NOC 2021 Version 1.0 classification structure (English and French CSVs,
Statistics Canada Open Licence, https://www.statcan.gc.ca/en/subjects/standard/noc/2021/indexV1)
supplies occupation titles and definitions in both languages. A classification
version never changes, so it is read once.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import re
import sqlite3
import zipfile

from ..db import get_meta, hours_since, log_run, now_iso, set_meta
from ..http import PoliteClient
from ..normalize import PRUID_PROVINCE

log = logging.getLogger(__name__)

URL = "https://www150.statcan.gc.ca/n1/tbl/csv/14100444-eng.zip"
TABLE = "14-10-0444-01"
NOC_URLS = {
    "en": "https://www.statcan.gc.ca/en/subjects/standard/noc/2021/indexV1/noc-2021-v1.0-classification-structure.csv",
    "fr": "https://www.statcan.gc.ca/fr/sujets/norme/cnp/2021/indexV1/cnp-2021-v1.0-structure-classification.csv",
}
CHECK_EVERY_HOURS = 30 * 24
KEEP_QUARTERS = 8
TOTAL = "total"
# NOC 2021 has 516 unit groups; far fewer means the file is not the structure file.
MIN_UNIT_GROUPS = 100

# DGUID prefixes in the table: Canada, a province (two-digit code follows), an
# economic region (four-digit code follows).
CANADA_DGUID = "2021A000011124"
PROVINCE_PREFIX = "2021A0002"
REGION_PREFIX = "2021S0500"

# Regions the survey combines to publish reliable estimates; their rows carry
# no DGUID, so they are recognised by name (the text before the province).
COMBINED_REGIONS: dict[str, tuple[str, ...]] = {
    "South Coast-Burin Peninsula and Notre Dame-Central Bonavista Bay": ("1020", "1040"),
    "Côte-Nord and Nord-du-Québec": ("2480", "2490"),
    "South Central and North Central": ("4620", "4640"),
    "Parklands and North": ("4670", "4680"),
    "Prince Albert and Northern": ("4750", "4760"),
    "Banff-Jasper-Rocky Mountain House and Athabasca-Grande Prairie-Peace River": ("4840", "4870"),
    "North Coast and Nechako": ("5960", "5970"),
}
PROVINCE_NAMES_EN = {
    "Newfoundland and Labrador", "Prince Edward Island", "Nova Scotia", "New Brunswick", "Quebec", "Ontario",
    "Manitoba", "Saskatchewan", "Alberta", "British Columbia", "Yukon", "Northwest Territories", "Nunavut",
}
STATISTICS = {"Job vacancies": "vacancies", "Average offered hourly wage": "wage"}
QUALITY = set("ABCDE")
UNIT_GROUP_RE = re.compile(r"\[(\d{5})\]\s*$")


def quarter_of(ref_date: str) -> str | None:
    """'2026-04' -> '2026Q2'; the table dates a quarter by its first month."""
    m = re.match(r"^(\d{4})-(\d{2})", ref_date or "")
    if not m or m.group(2) not in ("01", "04", "07", "10"):
        return None
    return f"{m.group(1)}Q{(int(m.group(2)) - 1) // 3 + 1}"


def _first_month(quarter: str) -> str:
    year, q = quarter.split("Q")
    return f"{year}-{3 * (int(q) - 1) + 1:02d}"


def _shift(quarter: str, back: int) -> str:
    year, q = quarter.split("Q")
    index = int(year) * 4 + int(q) - 1 - back
    return f"{index // 4}Q{index % 4 + 1}"


def _areas(dguid: str, geo: str) -> tuple[list[str], str, int] | None:
    """(area codes, name without the province, combined flag), or None for a row to skip."""
    name = geo.strip()
    head, _, tail = name.rpartition(", ")
    if head and tail in PROVINCE_NAMES_EN:
        name = head
    if dguid == CANADA_DGUID:
        return ["00"], name, 0
    if dguid.startswith(PROVINCE_PREFIX) and len(dguid) == len(PROVINCE_PREFIX) + 2:
        code = dguid[len(PROVINCE_PREFIX):]
        return ([code], name, 0) if code in PRUID_PROVINCE else None
    if dguid.startswith(REGION_PREFIX) and len(dguid) == len(REGION_PREFIX) + 4:
        return [dguid[len(REGION_PREFIX):]], name, 0
    if not dguid and name in COMBINED_REGIONS:
        return list(COMBINED_REGIONS[name]), name, 1
    return None


def _last_month(zf: zipfile.ZipFile) -> str | None:
    """The table's last reference month from the metadata file ('2026-04'), if readable."""
    names = [n for n in zf.namelist() if "metadata" in n.lower()]
    if not names:
        return None
    try:
        text = zf.read(names[0]).decode("utf-8-sig", errors="replace")
        rows = csv.reader(io.StringIO(text))
        header = next(rows)
        first = next(rows)
        col = next(i for i, h in enumerate(header) if h.strip().lower() == "end reference period")
        m = re.match(r"^(\d{4}-\d{2})", first[col])
        return m.group(1) if m else None
    except (StopIteration, IndexError, ValueError, csv.Error):
        return None


def parse_table(data: bytes, keep: int = KEEP_QUARTERS) -> list[tuple]:
    """Rows (noc, area_code, quarter, area_name, combined, vacancies, vac_quality, wage, wage_quality)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv") and "metadata" not in n.lower()]
        if not names:
            raise ValueError("no data CSV in the vacancy archive")
        last = _last_month(zf)
        cutoff = _first_month(_shift(quarter_of(last) or "0000Q1", keep - 1)) if last and quarter_of(last) else ""
        merged: dict[tuple[str, str, str], list] = {}
        with zf.open(names[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            header = next(csv.reader([text.readline()]))
            col = {h.strip(): i for i, h in enumerate(header)}
            need = ["REF_DATE", "GEO", "DGUID", "National Occupational Classification", "Statistics", "VALUE", "STATUS"]
            missing = [h for h in need if h not in col]
            if missing:
                raise ValueError(f"vacancy table lacks columns: {', '.join(missing)}")
            i_ref, i_geo, i_dguid, i_noc, i_stat, i_value, i_status = (col[h] for h in need)
            width = max(i_ref, i_geo, i_dguid, i_noc, i_stat, i_value, i_status)

            def recent(lines):
                # Lines start with the quoted reference month; an older one is
                # skipped without parsing (five of six million lines).
                for line in lines:
                    if cutoff and line.startswith('"') and line[8:9] == '"' and line[1:8] < cutoff:
                        continue
                    yield line

            for rec in csv.reader(recent(text)):
                if len(rec) <= width:
                    continue
                stat = STATISTICS.get(rec[i_stat].strip())
                quarter = quarter_of(rec[i_ref])
                value = rec[i_value].strip()
                if stat is None or quarter is None or not value:
                    continue
                label = rec[i_noc].strip()
                m = UNIT_GROUP_RE.search(label)
                noc = m.group(1) if m else (TOTAL if label == "Total, all occupations" else None)
                if noc is None:
                    continue
                where = _areas(rec[i_dguid].strip(), rec[i_geo])
                if where is None:
                    continue
                try:
                    number = float(value)
                except ValueError:
                    continue
                # "NaN" and "inf" are floats too; a cell holding one is no value.
                if not math.isfinite(number):
                    continue
                quality = rec[i_status].strip()
                codes, name, combined = where
                for code in codes:
                    row = merged.setdefault((noc, code, quarter), [name, combined, None, None, None, None])
                    if stat == "vacancies":
                        row[2], row[3] = int(round(number)), quality if quality in QUALITY else None
                    else:
                        row[4], row[5] = round(number, 2), quality if quality in QUALITY else None
    quarters = sorted({k[2] for k in merged}, reverse=True)[:keep]
    kept = set(quarters)
    return [(noc, code, q, *vals) for (noc, code, q), vals in sorted(merged.items()) if q in kept]


def parse_titles(en: bytes, fr: bytes) -> list[tuple]:
    """Rows (code, level, title_en, title_fr, definition_en, definition_fr) from the two structure files."""
    def read(data: bytes) -> dict[str, tuple[int, str, str]]:
        out: dict[str, tuple[int, str, str]] = {}
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        next(reader, None)
        for rec in reader:
            if len(rec) < 4 or not rec[0].strip().isdigit():
                continue
            code = rec[2].strip()
            if not re.fullmatch(r"\d{1,5}", code):
                continue
            out[code] = (int(rec[0]), rec[3].strip(), rec[4].strip() if len(rec) > 4 else "")
        return out

    english, french = read(en), read(fr)
    rows = [
        (code, level, title, french[code][1] or title, definition or None, french[code][2] or None)
        for code, (level, title, definition) in sorted(english.items())
        if code in french and title
    ]
    if sum(1 for r in rows if r[1] == 5) < MIN_UNIT_GROUPS:
        raise ValueError("the NOC structure files hold too few unit groups")
    return rows


def load_titles(conn: sqlite3.Connection, client: PoliteClient) -> int:
    bodies: dict[str, bytes] = {}
    for lang, url in NOC_URLS.items():
        bodies[lang] = client.get(url, cache=True, max_age_s=3600, timeout=120)
    try:
        rows = parse_titles(bodies["en"], bodies["fr"])
    except Exception:
        for url in NOC_URLS.values():
            client.forget(url)
        raise
    conn.execute("DELETE FROM noc_titles")
    conn.executemany(
        "INSERT INTO noc_titles (noc_code, level, title_en, title_fr, definition_en, definition_fr) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def load_table(conn: sqlite3.Connection, client: PoliteClient) -> int:
    """Download and load the vacancy table; 0 when the file is the one already loaded."""
    data = client.get(URL, cache=True, max_age_s=3600, timeout=600)
    sha = hashlib.sha256(data).hexdigest()
    have = conn.execute("SELECT COUNT(*) FROM statcan_vacancies").fetchone()[0]
    if have and get_meta(conn, "vacancies_sha") == sha:
        return 0
    try:
        rows = parse_table(data)
        if not rows:
            raise ValueError("the vacancy table held no unit-group figures")
    except Exception:
        # Drop the cached body so the next check downloads it again rather
        # than revalidating a broken copy against its own ETag.
        client.forget(URL)
        raise
    conn.execute("DELETE FROM statcan_vacancies")
    conn.executemany(
        "INSERT INTO statcan_vacancies (noc_code, area_code, ref_quarter, area_name, combined, vacancies, "
        "vacancies_quality, offered_wage, offered_wage_quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    set_meta(conn, "vacancies_sha", sha)
    conn.commit()
    return len(rows)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    have = conn.execute("SELECT COUNT(*) FROM statcan_vacancies").fetchone()[0]
    titles = conn.execute("SELECT COUNT(*) FROM noc_titles").fetchone()[0]
    hours = hours_since(conn, "vacancies_checked_at", now=stamp)
    if have and titles and hours is not None and hours < CHECK_EVERY_HOURS:
        log_run(conn, "vacancies", detail=f"skipped: checked {hours / 24:.0f} days ago; rows={have}", rows_in=have)
        return 0
    failures: list[str] = []
    if not titles:
        try:
            titles = load_titles(conn, client)
            log.info("noc titles: %d", titles)
        except Exception as exc:  # the vacancy figures still load without titles
            conn.rollback()
            failures.append(f"titles: {type(exc).__name__}: {exc}")
    loaded = 0
    try:
        loaded = load_table(conn, client)
        if loaded:
            log.info("vacancies: %d rows", loaded)
    except Exception as exc:  # a failed download or a changed layout keeps the previous table
        conn.rollback()
        failures.append(f"table: {type(exc).__name__}: {exc}")
    if not failures:
        set_meta(conn, "vacancies_checked_at", stamp)
        conn.commit()
    total, latest = conn.execute("SELECT COUNT(*), MAX(ref_quarter) FROM statcan_vacancies").fetchone()
    detail = f"table={TABLE} rows={total} latest={latest} loaded_now={loaded} titles={titles}"
    if failures:
        detail += " failures=" + "; ".join(failures)[:800]
    log_run(conn, "vacancies", detail=detail, rows_in=total, rows_new=loaded, ok=not failures)
    return loaded
