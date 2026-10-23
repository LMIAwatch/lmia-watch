"""US FMCSA Company Census: motor carriers with a Canadian address, joined to employers.

Source: "Company Census File", Federal Motor Carrier Safety Administration,
data.transportation.gov dataset az4n-8mr2 (Socrata), a work of the United
States government in the public domain (the catalogue gives its rights as
public). The census holds every carrier with a USDOT number, 4.4 million
rows, updated daily; a Canadian carrier needs a number to haul into the
United States.

Read once a month (CHECK_EVERY_DAYS; the date lives in the database): only
rows whose physical country is CA, through the API's $where filter, paged
PAGE_SIZE at a time, and only the columns in FIELDS, through $select, so the
company officers, phone, cell phone, fax and email address are never even
downloaded. Kept: carriers whose normalized legal or DBA name is the name of
an employer in the same province. Dropped: business organization INDIVIDUAL
(sole proprietors) and any legal name that reads as a person
(matching.is_person_name); a DBA name that reads as a person is not kept.

Matching (every night; rules in matching.py): the legal name normalizes to
the employer's name and the postal code equals one on the employer's
records: exact; the name and province agree but not the postal code (many
older records give only CANADA): probable, and not for a common name; a DBA
name with the postal code: probable. The profile shows power units, drivers,
the safety rating and the record's date (the MCS-150 date, the carrier's
latest update of its census record).

Nothing here feeds the indicators.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from urllib.parse import quote, urlencode

from ..db import hours_since, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import PROVINCE_CODES, norm_name, to_int
from . import matching

log = logging.getLogger(__name__)

DATASET = "az4n-8mr2"
API = f"https://data.transportation.gov/resource/{DATASET}.json"
# The columns read, and the only ones requested. COMPANY_OFFICER_1 and _2,
# PHONE, CELL_PHONE, FAX and EMAIL_ADDRESS are left out on purpose.
FIELDS = (
    "dot_number", "legal_name", "dba_name", "phy_city", "phy_state", "phy_zip", "phy_country", "power_units",
    "total_drivers", "safety_rating", "safety_rating_date", "status_code", "mcs150_date", "add_date",
    "business_org_desc", "carrier_operation",
)
PAGE_SIZE = 50_000
MAX_PAGES = 40
LOADED_KEY = "fmcsa_loaded_at"
CHECK_EVERY_DAYS = 30
CHUNK = 5000
MATCH_TABLE = "fmcsa_matches"
COLUMNS = ("dot_number", "legal_name", "norm_name", "dba_name", "dba_norm", "city", "province", "postal_code", "status",
           "power_units", "drivers", "safety_rating", "safety_rating_date", "record_date", "added_on",
           "carrier_operation", "loaded_at")
RATINGS = {"S", "C", "U"}
NAME_PLACEHOLDERS = {"", "na", "n a", "none", "no", "owner", "not applicable"}


def page_url(offset: int) -> str:
    params = {
        "$select": ",".join(FIELDS),
        "$where": "phy_country='CA'",
        "$order": "dot_number",
        "$limit": str(PAGE_SIZE),
        "$offset": str(offset),
    }
    return f"{API}?{urlencode(params, quote_via=quote, safe=',')}"


def _date(raw: object) -> str | None:
    """'20260421 0000' or '20260421' -> '2026-04-21'."""
    m = re.match(r"^\s*(\d{4})(\d{2})(\d{2})", str(raw or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _name(raw: object) -> str | None:
    text = matching.first_language(raw)
    return text if norm_name(text) not in NAME_PLACEHOLDERS else None


def parse_rows(records: list, wanted: set[tuple[str, str]], stamp: str) -> tuple[list[tuple], dict[str, int]]:
    """Rows for fmcsa_carriers from the API's records, limited to (name, province) pairs of employers."""
    counts = {"read": 0, "persons": 0, "kept": 0}
    kept: dict[int, tuple] = {}
    for rec in records:
        if not isinstance(rec, dict):
            raise ValueError("a census record is not an object")
        counts["read"] += 1
        dot = to_int(rec.get("dot_number"))
        legal = _name(rec.get("legal_name"))
        province = (rec.get("phy_state") or "").strip().upper()
        if dot is None or legal is None or province not in PROVINCE_CODES:
            continue
        norm = norm_name(legal)
        dba_raw = _name(rec.get("dba_name"))
        dba_norm = norm_name(dba_raw) if dba_raw else ""
        if (norm, province) not in wanted and (dba_norm, province) not in wanted:
            continue
        if (rec.get("business_org_desc") or "").strip().upper() == "INDIVIDUAL" or matching.is_person_name(legal):
            counts["persons"] += 1
            continue
        dba = matching.business_name(dba_raw)
        rating = (rec.get("safety_rating") or "").strip().upper()
        kept[dot] = (
            dot, legal, norm, dba, norm_name(dba) if dba else None, matching.first_language(rec.get("phy_city")) or None,
            province, matching.postal_code(rec.get("phy_zip")), (rec.get("status_code") or "").strip().upper() or None,
            to_int(rec.get("power_units")), to_int(rec.get("total_drivers")), rating if rating in RATINGS else None,
            _date(rec.get("safety_rating_date")), _date(rec.get("mcs150_date")), _date(rec.get("add_date")),
            (rec.get("carrier_operation") or "").strip().upper() or None, stamp,
        )
    counts["kept"] = len(kept)
    return [kept[d] for d in sorted(kept)], counts


def fetch_canadian(client: PoliteClient) -> list:
    """Every Canadian record, page by page; raises ValueError when the answer is not a list of records."""
    records: list = []
    for page in range(MAX_PAGES):
        url = page_url(page * PAGE_SIZE)
        body = client.get_json(url, timeout=300)
        if not isinstance(body, list):
            raise ValueError("the census API did not answer with a list of records")
        records.extend(body)
        if len(body) < PAGE_SIZE:
            return records
    raise ValueError(f"more than {MAX_PAGES} pages of Canadian carriers; the filter may have stopped working")


def load(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
         force: bool = False) -> int | None:
    """Fetch and load the Canadian carriers once a month; returns carriers kept, None when skipped."""
    stamp = now or now_iso()
    age = hours_since(conn, LOADED_KEY, now=stamp)
    if not force and age is not None and age < CHECK_EVERY_DAYS * 24:
        return None
    records = fetch_canadian(client)
    if not records:
        raise ValueError("the census API returned no Canadian carrier")
    wanted = {(r[0], r[1]) for r in conn.execute(
        "SELECT DISTINCT norm_name, province FROM employers WHERE norm_name != '' AND province IS NOT NULL")}
    rows, counts = parse_rows(records, wanted, stamp)
    conn.execute("DELETE FROM fmcsa_carriers")
    marks = ", ".join("?" * len(COLUMNS))
    for i in range(0, len(rows), CHUNK):
        conn.executemany(f"INSERT INTO fmcsa_carriers ({', '.join(COLUMNS)}) VALUES ({marks})", rows[i:i + CHUNK])
    set_meta(conn, LOADED_KEY, stamp)
    conn.commit()
    # Only the count of carriers left out as people is logged, never a name.
    log.info("fmcsa: %d Canadian records read, %d kept, %d individuals left out",
             counts["read"], counts["kept"], counts["persons"])
    return len(rows)


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Rebuild fmcsa_matches from the stored carriers; returns the matches written."""
    stamp = now or now_iso()
    pairs = conn.execute(
        """
        SELECT e.id, 'legal' AS kind, f.dot_number, f.norm_name AS norm, f.province, f.postal_code
        FROM fmcsa_carriers f JOIN employers e ON e.norm_name = f.norm_name AND e.province = f.province
        UNION ALL
        SELECT e.id, 'other', f.dot_number, f.dba_norm, f.province, f.postal_code
        FROM fmcsa_carriers f JOIN employers e ON e.norm_name = f.dba_norm AND e.province = f.province
        WHERE f.dba_norm IS NOT NULL AND f.dba_norm != f.norm_name
        """
    ).fetchall()
    places = matching.employer_places(conn, {p[0] for p in pairs})
    found: dict[tuple[str, int], tuple[str, str]] = {}
    for eid, kind, dot, norm, province, postal in pairs:
        place = places.get(eid) or matching.Places()
        strong = bool(postal) and postal in place.postals
        g = matching.grade(kind, strong, province == place.province, norm)
        if not g:
            continue
        basis = ("name_postal_code" if strong else "name_province") if kind == "legal" else "dba_postal_code"
        current = found.get((eid, dot))
        if current is None or matching.GRADE_RANK[g] < matching.GRADE_RANK[current[0]]:
            found[(eid, dot)] = (g, basis)
    rows = [(eid, dot, g, basis) for (eid, dot), (g, basis) in sorted(found.items())]
    return matching.replace_matches(conn, MATCH_TABLE, "dot_number", rows, stamp)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    # A request that fails is recorded as a failed stage and tried again the
    # next night; the carriers already loaded stay matched.
    problem = None
    try:
        loaded = load(conn, client, now=now)
    except FetchError as exc:
        log.warning("fmcsa: %s", exc)
        loaded, problem = None, str(exc)
    total = conn.execute("SELECT COUNT(*) FROM fmcsa_carriers").fetchone()[0]
    matched = match(conn, now=now)
    detail = f"carriers={total} loaded_now={'skipped' if loaded is None else loaded} matched={matched}"
    if problem:
        detail = f"{detail} download failed: {problem}"
    log_run(conn, "fmcsa", detail=detail[:900], rows_in=total, rows_new=matched, ok=problem is None)
    return matched
