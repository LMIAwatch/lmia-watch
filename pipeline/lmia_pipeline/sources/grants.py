"""Federal grants and contributions: the proactive disclosure, joined to employers.

Source: "Proactive Disclosure - Grants and Contributions", open.canada.ca
dataset 432527ab-7aac-45b5-81d6-7597107a7013, Open Government Licence,
Canada. Federal departments disclose their grant and contribution agreements
each quarter; the dataset is one CSV (grants.csv, 2.3 GB on 2026-10-22) with a
row per agreement and per amendment: recipient type, business number, legal
and operating name, city, province and postal code, program, agreement type,
value and dates, and the department.

Read once a quarter (CHECK_EVERY_DAYS; the date lives in the database because
the nightly runner starts with an empty cache): the file is streamed to disk,
read row by row and deleted. Kept: agreements with a Canadian recipient whose
normalized legal or operating name is an employer's name, or whose business
number is that of a federal corporation matched to an employer, so the table
holds a small share of the file; an employer first seen after a load is
matched at the next one. One row per agreement (department and reference
number), from its highest amendment, whose value is the amended total.
Dropped before anything is written: recipient type P (individuals and sole
proprietorships) and any recipient whose legal name reads as a person
(matching.is_person_name); an operating name that reads as a person is not
kept. Narrative fields (titles, descriptions, expected results) are not
read.

Matching (every night, from the stored rows; rules in matching.py):
* by business number: when the federal corporations extract gives the
  corporation matched to an employer (registry_matches) a business number
  (federal_corporations), each agreement carrying that number is joined at
  the registry match's grade, since the number is only as good as the name
  match behind it;
* by name: the recipient's legal name normalizes to the employer's name and
  the postal areas (first three characters) agree: exact; only the province
  agrees: probable, and not for a common name. An operating name with the
  postal area: probable. An agreement whose valid business number differs
  from the one the employer's corporation has is never joined by name: it is
  another business with the same name.

Nothing here feeds the indicators.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import sqlite3
from pathlib import Path

from .. import config
from ..db import hours_since, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import business_number, norm_name, province_code, to_int
from . import matching
from .registry_federal import REGISTRY as FEDERAL_REGISTRY

log = logging.getLogger(__name__)

DATASET = "432527ab-7aac-45b5-81d6-7597107a7013"
RESOURCE = "1d15a62f-5656-49ad-8c88-f40ce689d831"
URL = f"https://open.canada.ca/data/dataset/{DATASET}/resource/{RESOURCE}/download/grants.csv"
LOADED_KEY = "grants_loaded_at"
CHECK_EVERY_DAYS = 91
CHUNK = 5000
MATCH_TABLE = "grant_matches"
REQUIRED = (
    "ref_number", "amendment_number", "agreement_type", "recipient_type", "recipient_business_number",
    "recipient_legal_name", "recipient_operating_name", "recipient_country", "recipient_province",
    "recipient_city", "recipient_postal_code", "prog_name_en", "prog_name_fr", "agreement_value",
    "agreement_start_date", "agreement_end_date", "owner_org", "owner_org_title",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
COLUMNS = (
    "agreement_key", "ref_number", "amendment_number", "owner_org", "department_en", "department_fr",
    "recipient_type", "business_number", "legal_name", "norm_name", "operating_name", "operating_norm", "city",
    "province", "postal_code", "program_en", "program_fr", "agreement_type", "agreement_value", "start_date",
    "end_date", "loaded_at",
)


def _date(raw: str | None) -> str | None:
    m = DATE_RE.match((raw or "").strip())
    return m.group(0) if m else None


def _value(raw: str | None) -> float | None:
    try:
        value = float((raw or "").replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _city_and_province(city: str, province: str | None) -> tuple[str | None, str | None]:
    """Older rows write the province into the city ("Headingley, Manitoba") and leave the province blank."""
    if "," in city:
        head, tail = city.rsplit(",", 1)
        code = province_code(tail.strip())
        if code in matching.PROVINCE_CODES:
            return head.strip() or None, province or code
    return city or None, province


def parse_rows(lines: io.TextIOBase, wanted: set[str], numbers: set[str], stamp: str) -> tuple[list[tuple], dict[str, int]]:
    """Rows for federal_grants from the CSV text, limited to the wanted names and business numbers.

    Returns the rows (one per agreement, its highest amendment) and counts of
    what was read, kept and dropped. Raises ValueError when a column the
    rules need is missing, so a changed layout keeps the previous table.
    """
    reader = csv.DictReader(lines)
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"grants file lacks columns: {', '.join(missing)}")
    counts = {"read": 0, "persons": 0, "kept": 0}
    best: dict[str, tuple[int, tuple]] = {}
    for rec in reader:
        counts["read"] += 1
        kind = (rec.get("recipient_type") or "").strip().upper()
        if kind == "P":
            counts["persons"] += 1
            continue
        country = (rec.get("recipient_country") or "").strip().upper()
        if country and country != "CA":
            continue
        legal = matching.first_language(rec.get("recipient_legal_name"))
        if not legal:
            continue
        # The cheap tests first: most rows name no employer and are left
        # before the person test, which is the slow one.
        norm = norm_name(legal)
        operating_raw = matching.first_language(rec.get("recipient_operating_name"))
        operating_norm = norm_name(operating_raw) if operating_raw else ""
        number = business_number(rec.get("recipient_business_number"))
        if norm not in wanted and operating_norm not in wanted and number not in numbers:
            continue
        if matching.is_person_name(legal):
            counts["persons"] += 1
            continue
        operating = matching.business_name(operating_raw)
        postal = matching.postal_code(rec.get("recipient_postal_code"))
        city, province = _city_and_province(matching.first_language(rec.get("recipient_city")),
                                            matching.province_of(rec.get("recipient_province"), postal))
        owner = (rec.get("owner_org") or "").strip()
        ref = (rec.get("ref_number") or "").strip()
        if not owner or not ref:
            continue
        title = (rec.get("owner_org_title") or "").split("|", 1)
        amendment = to_int(rec.get("amendment_number")) or 0
        key = f"{owner},{ref}"
        row = (
            key, ref, amendment, owner, title[0].strip() or None, title[1].strip() if len(title) > 1 else None,
            kind or None, number, legal, norm, operating, norm_name(operating) if operating else None, city,
            province, postal, (rec.get("prog_name_en") or "").strip() or None,
            (rec.get("prog_name_fr") or "").strip() or None, (rec.get("agreement_type") or "").strip().upper() or None,
            _value(rec.get("agreement_value")), _date(rec.get("agreement_start_date")),
            _date(rec.get("agreement_end_date")), stamp,
        )
        # The highest amendment carries the amended value; a repeat of the
        # same amendment later in the file replaces the earlier one.
        current = best.get(key)
        if current is None or amendment >= current[0]:
            best[key] = (amendment, row)
    counts["kept"] = len(best)
    return [best[k][1] for k in sorted(best)], counts


def parse_file(path: Path, wanted: set[str], numbers: set[str], stamp: str) -> tuple[list[tuple], dict[str, int]]:
    # errors="replace": a stray byte in one name must not stop a 2 GB read.
    with path.open("rb") as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="") as text:
        return parse_rows(text, wanted, numbers, stamp)


# The business number of the corporation each employer is matched to.
MATCHED_NUMBERS = """
    SELECT m.employer_id, f.business_number, m.grade
    FROM registry_matches m JOIN federal_corporations f ON f.number = m.registry_id
    WHERE m.registry = ? AND f.business_number IS NOT NULL AND m.grade IN ('exact', 'probable')
"""


def wanted_numbers(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute(MATCHED_NUMBERS, (FEDERAL_REGISTRY,))}


def load(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None, force: bool = False,
         work_dir: Path | None = None) -> int | None:
    """Download and load the disclosure once a quarter; returns agreements kept, None when skipped."""
    stamp = now or now_iso()
    age = hours_since(conn, LOADED_KEY, now=stamp)
    if not force and age is not None and age < CHECK_EVERY_DAYS * 24:
        return None
    path = (work_dir or (config.RAW_DIR / "grants")) / "grants.csv"
    try:
        size = client.download(URL, path, timeout=600)
        rows, counts = parse_file(path, matching.employer_names(conn), wanted_numbers(conn), stamp)
    finally:
        path.unlink(missing_ok=True)
    if counts["read"] == 0:
        raise ValueError("the grants file held no agreements")
    conn.execute("DELETE FROM federal_grants")
    marks = ", ".join("?" * len(COLUMNS))
    for i in range(0, len(rows), CHUNK):
        conn.executemany(f"INSERT INTO federal_grants ({', '.join(COLUMNS)}) VALUES ({marks})", rows[i:i + CHUNK])
    set_meta(conn, LOADED_KEY, stamp)
    conn.commit()
    # Only the count of rows left out as people is logged, never a name.
    log.info("grants: %d bytes, %d rows read, %d agreements kept, %d rows of individuals left out",
             size, counts["read"], counts["kept"], counts["persons"])
    return len(rows)


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Rebuild grant_matches from the stored agreements; returns the matches written."""
    stamp = now or now_iso()
    found: dict[tuple[str, str], tuple[str, str]] = {}

    def keep(eid: str, key: str, grade: str, basis: str) -> None:
        current = found.get((eid, key))
        if current is None or matching.GRADE_RANK[grade] < matching.GRADE_RANK[current[0]]:
            found[(eid, key)] = (grade, basis)

    # The business number of the corporation each employer is matched to,
    # joined in memory: the table has no index on the number (see schema.sql).
    by_number: dict[str, list[str]] = {}
    for key, number in conn.execute(
        "SELECT agreement_key, business_number FROM federal_grants WHERE business_number IS NOT NULL"
    ):
        by_number.setdefault(number, []).append(key)
    known: dict[str, set[str]] = {}
    for eid, number, registry_grade in conn.execute(MATCHED_NUMBERS, (FEDERAL_REGISTRY,)):
        known.setdefault(eid, set()).add(number)
        for key in by_number.get(number, ()):
            keep(eid, key, registry_grade, "business_number")

    pairs = conn.execute(
        """
        SELECT e.id, 'legal' AS kind, g.agreement_key, g.norm_name AS norm, g.province, g.postal_code, g.business_number
        FROM federal_grants g JOIN employers e ON e.norm_name = g.norm_name
        UNION ALL
        SELECT e.id, 'other', g.agreement_key, g.operating_norm, g.province, g.postal_code, g.business_number
        FROM federal_grants g JOIN employers e ON e.norm_name = g.operating_norm
        WHERE g.operating_norm IS NOT NULL AND g.operating_norm != g.norm_name
        """
    ).fetchall()
    places = matching.employer_places(conn, {p[0] for p in pairs})
    for eid, kind, key, norm, province, postal, number in pairs:
        if number and known.get(eid) and number not in known[eid]:
            continue
        place = places.get(eid) or matching.Places()
        strong = bool(postal) and postal[:3] in place.areas
        weak = bool(province) and province == place.province
        g = matching.grade(kind, strong, weak, norm)
        if g:
            basis = ("name_postal_area" if strong else "name_province") if kind == "legal" else "operating_name_postal_area"
            keep(eid, key, g, basis)
    rows = [(eid, key, g, basis) for (eid, key), (g, basis) in sorted(found.items())]
    return matching.replace_matches(conn, MATCH_TABLE, "agreement_key", rows, stamp)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
        work_dir: Path | None = None) -> int:
    # A download that fails is recorded as a failed stage and tried again the
    # next night; the agreements already loaded stay and are matched.
    problem = None
    try:
        loaded = load(conn, client, now=now, work_dir=work_dir)
    except FetchError as exc:
        log.warning("grants: %s", exc)
        loaded, problem = None, str(exc)
    total = conn.execute("SELECT COUNT(*) FROM federal_grants").fetchone()[0]
    matched = match(conn, now=now)
    detail = f"agreements={total} loaded_now={'skipped' if loaded is None else loaded} matched={matched}"
    if problem:
        detail = f"{detail} download failed: {problem}"
    log_run(conn, "grants", detail=detail[:900], rows_in=total, rows_new=matched, ok=problem is None)
    return matched
