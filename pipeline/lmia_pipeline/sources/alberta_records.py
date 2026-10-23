"""Alberta Employer Records: workers' compensation injury figures, joined to Alberta employers.

Source: "Employer Records", Alberta Jobs, Economy, Trade and Immigration,
https://open.alberta.ca/opendata/employer-records, Open Government Licence,
Alberta (https://open.alberta.ca/licence). One workbook a year (the
2020-2024 file is 53 MB, dated 2025-12-16): for each employer required to
hold a Workers' Compensation Board account, the legal name, trade name, city,
WCB industry, person-years (full-time equivalents), lost-time claims,
disabling injuries and fatalities with their rates, and the certificate of
recognition year, for each of five years. Only the sheet whose name starts
with "Injury" is read; the workbook's other sheets (orders, penalties,
tickets, convictions, acceptances, approvals, investigations) are not.

The listing is read at most every CHECK_EVERY_DAYS; the workbook is
downloaded when its resource is new or changed, and otherwise when the last
load is REFRESH_DAYS old, so an Alberta employer first seen since then is
matched within a quarter. Kept: accounts whose normalized legal or trade name
is an Alberta employer's name. Dropped: an account whose legal name reads as
a person (sole proprietors register under their own name, and the file has
no legal-form column), and with it the account's other names; a trade name
that reads as a person is not kept. The 2020-2024 file leaves TRADE_NAME and
COR_YEAR empty on every row; both are read in case a later file fills them.
Instead it lists some accounts under two names for the same year, with the
same figures (1,394 account-years: a numbered company and the name it
operates under, or a former name and the current one); each name is kept as
a row of its own and matched.

Matching (every night, Alberta employers only; rules in matching.py): the
legal name normalizes to the employer's name and the city agrees with a city
on the employer's records: exact; the name agrees but the city differs or is
blank (22 percent of rows give none): probable, and not for a common name; a
trade name with the city: probable. The profile shows the latest year of the
best accounts, under the name that matched.

Nothing here feeds the indicators.
"""

from __future__ import annotations

import io
import logging
import math
import sqlite3

from openpyxl import load_workbook

from ..db import get_meta, hours_since, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import norm_name, to_int
from . import matching

log = logging.getLogger(__name__)

PACKAGE = "employer-records"
LISTING = f"https://open.alberta.ca/api/3/action/package_show?id={PACKAGE}"
CHECKED_KEY = "alberta_checked_at"
LOADED_KEY = "alberta_loaded_at"
RESOURCE_KEY = "alberta_resource"
CHECK_EVERY_DAYS = 30
REFRESH_DAYS = 91
PROVINCE = "AB"
CHUNK = 5000
MATCH_TABLE = "alberta_matches"
REQUIRED = ("EMP_KEY", "EMPLOYER_NAME", "CITY_NAME", "YEAR_NO", "PERSON_YEARS_COUNT", "LOST_TIME_CLAIM_COUNT",
            "ANNUAL_FATALITY_COUNT", "ANNUAL_DISABLING_INJURIES_COUNT")
COLUMNS = ("emp_key", "year", "employer_name", "norm_name", "trade_name", "trade_norm", "city", "industry",
           "industry_code", "person_years", "lost_time_claims", "lost_time_rate", "disabling_injuries",
           "disabling_rate", "fatalities", "cor_year", "resource_id")


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _text(value: object) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def newest_workbook(package: dict) -> dict | None:
    resources = package.get("result", {}).get("resources", [])
    books = [r for r in resources
             if (r.get("format") or "").upper() == "XLSX" or (r.get("url") or "").lower().endswith(".xlsx")]
    books.sort(key=lambda r: (str(r.get("last_modified") or r.get("created") or ""), r.get("id") or ""), reverse=True)
    return books[0] if books else None


def parse_workbook(data: bytes, wanted: set[str], resource_id: str) -> tuple[list[tuple], dict[str, int]]:
    """Rows for alberta_employer_records, limited to the wanted names; raises ValueError on another layout."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = next((ws for ws in wb.worksheets if ws.title.strip().lower().startswith("injury")), None)
        if sheet is None:
            raise ValueError("no Injury sheet in the Alberta workbook")
        rows = sheet.iter_rows(values_only=True)
        header = [str(h).strip().upper() if h is not None else "" for h in next(rows, ())]
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ValueError(f"Alberta workbook lacks columns: {', '.join(missing)}")
        at = {h: i for i, h in enumerate(header) if h}

        def cell(row: tuple, name: str) -> object:
            i = at.get(name)
            return row[i] if i is not None and i < len(row) else None

        counts = {"read": 0, "persons": 0, "kept": 0}
        # Every name each account is listed under, so an account is dropped
        # whole when any of its names reads as a person.
        names: dict[str, set[str]] = {}
        kept: dict[tuple[str, int, str], tuple] = {}
        for row in rows:
            counts["read"] += 1
            key = _text(cell(row, "EMP_KEY"))
            name = _text(cell(row, "EMPLOYER_NAME"))
            year = to_int(cell(row, "YEAR_NO"))
            if not key or not name or year is None:
                continue
            names.setdefault(key, set()).add(name)
            norm = norm_name(name)
            trade_raw = _text(cell(row, "TRADE_NAME"))
            trade_norm = norm_name(trade_raw) if trade_raw else ""
            if norm not in wanted and trade_norm not in wanted:
                continue
            trade = matching.business_name(trade_raw)
            record = (
                key, year, name, norm, trade, norm_name(trade) if trade else None, _text(cell(row, "CITY_NAME")),
                _text(cell(row, "WCB_INDUSTRY_NAME")), _text(cell(row, "WCB_INDUSTRY_CODE")),
                _num(cell(row, "PERSON_YEARS_COUNT")), to_int(cell(row, "LOST_TIME_CLAIM_COUNT")),
                _num(cell(row, "LOST_TIME_CLAIM_RATE")), to_int(cell(row, "ANNUAL_DISABLING_INJURIES_COUNT")),
                _num(cell(row, "DISABLING_INJURIES_RATE")), to_int(cell(row, "ANNUAL_FATALITY_COUNT")),
                to_int(cell(row, "COR_YEAR")), resource_id,
            )
            # The same name written twice for one year ("S.Q.I" and
            # "S.Q.I.") is one row; the first stands.
            kept.setdefault((key, year, norm), record)
    finally:
        wb.close()
    persons = {k for k in {k[0] for k in kept} if any(matching.is_person_name(n) for n in names[k])}
    counts["persons"] = len(persons)
    rows_out = [kept[k] for k in sorted(kept) if k[0] not in persons]
    counts["kept"] = len(rows_out)
    return rows_out, counts


def load(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
         force: bool = False) -> int | None:
    """Check the listing and load the workbook when due; returns rows kept, None when nothing was loaded."""
    stamp = now or now_iso()
    have = conn.execute("SELECT COUNT(*) FROM alberta_employer_records").fetchone()[0]
    checked = hours_since(conn, CHECKED_KEY, now=stamp)
    if not force and have and checked is not None and checked < CHECK_EVERY_DAYS * 24:
        return None
    try:
        package = client.get_json(LISTING, cache=True, max_age_s=3600)
        res = newest_workbook(package)
    except (ValueError, AttributeError):
        client.forget(LISTING)  # an error page cached as the listing is not reused
        raise
    if res is None:
        raise ValueError("the Alberta listing names no workbook")
    marker = f"{res.get('id')}:{res.get('last_modified') or res.get('created') or ''}"
    loaded = hours_since(conn, LOADED_KEY, now=stamp)
    due = force or marker != get_meta(conn, RESOURCE_KEY) or loaded is None or loaded >= REFRESH_DAYS * 24
    if not due:
        set_meta(conn, CHECKED_KEY, stamp)
        conn.commit()
        return None
    data = client.get(res["url"], timeout=600)
    rows, counts = parse_workbook(data, matching.employer_names(conn, PROVINCE), str(res.get("id") or ""))
    if counts["read"] == 0:
        raise ValueError("the Alberta workbook held no rows")
    conn.execute("DELETE FROM alberta_employer_records")
    marks = ", ".join("?" * len(COLUMNS))
    for i in range(0, len(rows), CHUNK):
        conn.executemany(f"INSERT INTO alberta_employer_records ({', '.join(COLUMNS)}) VALUES ({marks})",
                         rows[i:i + CHUNK])
    set_meta(conn, RESOURCE_KEY, marker)
    set_meta(conn, LOADED_KEY, stamp)
    set_meta(conn, CHECKED_KEY, stamp)
    conn.commit()
    # Only the count of accounts left out as people is logged, never a name.
    log.info("alberta records: %d rows read, %d kept, %d accounts of individuals left out",
             counts["read"], counts["kept"], counts["persons"])
    return len(rows)


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Rebuild alberta_matches from the stored accounts; returns the matches written."""
    stamp = now or now_iso()
    pairs = conn.execute(
        """
        SELECT DISTINCT e.id, 'legal' AS kind, a.emp_key, a.norm_name AS norm, a.city, a.employer_name
        FROM alberta_employer_records a JOIN employers e ON e.norm_name = a.norm_name AND e.province = 'AB'
        UNION
        SELECT DISTINCT e.id, 'other', a.emp_key, a.trade_norm, a.city, a.employer_name
        FROM alberta_employer_records a JOIN employers e ON e.norm_name = a.trade_norm AND e.province = 'AB'
        WHERE a.trade_norm IS NOT NULL AND a.trade_norm != a.norm_name
        ORDER BY 1, 3, 6
        """
    ).fetchall()
    places = matching.employer_places(conn, {p[0] for p in pairs})
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    for eid, kind, key, norm, city, account_name in pairs:
        place = places.get(eid) or matching.Places()
        strong = bool(city) and matching.fold_city(city) in place.cities
        # Every record and every employer here is in Alberta.
        g = matching.grade(kind, strong, True, norm)
        if not g:
            continue
        basis = ("name_city" if strong else "name_province") if kind == "legal" else "trade_name_city"
        current = found.get((eid, key))
        if current is None or matching.GRADE_RANK[g] < matching.GRADE_RANK[current[0]]:
            found[(eid, key)] = (g, basis, account_name)
    conn.execute(f"DELETE FROM {MATCH_TABLE}")
    conn.executemany(
        f"INSERT INTO {MATCH_TABLE} (employer_id, emp_key, account_name, grade, basis, matched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(eid, key, name, g, basis, stamp) for (eid, key), (g, basis, name) in sorted(found.items())],
    )
    conn.commit()
    return len(found)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    # A listing or download that fails is recorded as a failed stage and
    # tried again the next night; the accounts already loaded stay matched.
    problem = None
    try:
        loaded = load(conn, client, now=now)
    except FetchError as exc:
        log.warning("alberta records: %s", exc)
        loaded, problem = None, str(exc)
    total = conn.execute("SELECT COUNT(*) FROM alberta_employer_records").fetchone()[0]
    matched = match(conn, now=now)
    detail = f"rows={total} loaded_now={'skipped' if loaded is None else loaded} matched={matched}"
    if problem:
        detail = f"{detail} download failed: {problem}"
    log_run(conn, "alberta_records", detail=detail[:900], rows_in=total, rows_new=matched, ok=problem is None)
    return matched
