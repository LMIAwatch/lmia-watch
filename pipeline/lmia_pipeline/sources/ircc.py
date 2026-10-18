"""IRCC list of employers found non-compliant.

The canada.ca page renders its table from a JSON document
(/content/dam/ircc/documents/json/non_compliant.json) whose rows carry the
operating and legal names, an address with <br> breaks, reason codes that
point at a numbered legend on the page, the decision date, the penalty and
the current status. The legend text is read from the HTML so the stored
reason is readable on its own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3

from bs4 import BeautifulSoup

from .. import config
from ..db import log_run, now_iso, record_names, upsert_employer
from ..http import PoliteClient
from ..normalize import (
    employer_id, fold_accents, has_legal_form, is_numbered_company, norm_name, parse_address, parse_street,
)

log = logging.getLogger(__name__)

JSON_URL = "https://www.canada.ca/content/dam/ircc/documents/json/non_compliant.json"


def _text(html_fragment: str | None) -> str | None:
    if not html_fragment:
        return None
    text = re.sub(r"<br\s*/?>", ", ", html_fragment, flags=re.I)
    text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text or None


def parse_legend(html: str) -> dict[str, str]:
    """Reason code -> legend sentence, from elements with id 'list<N>'."""
    soup = BeautifulSoup(html, "html.parser")
    legend: dict[str, str] = {}
    for el in soup.find_all(id=re.compile(r"^list\d+$")):
        code = el.get("id")[4:]
        text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
        if text:
            legend[code] = text
    return legend


def parse_rows(data: dict, legend: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    for entry in data.get("list") or []:
        codes = re.findall(r">(\d+)<", entry.get("reason") or "") or re.findall(r"\d+", entry.get("reason") or "")
        reasons = "; ".join(f"{c}: {legend[c]}" if c in legend else c for c in codes) or _text(entry.get("reason"))
        address = _text(entry.get("bn_address_en"))
        rows.append(
            {
                "operating_name": _text(entry.get("bn_operating")),
                "legal_name": _text(entry.get("bn_legal")),
                "address": address,
                "reasons": reasons,
                "decision_date": (entry.get("date") or "")[:10] or None,
                "penalty": _text(entry.get("penalty_en")),
                "status": _text(entry.get("status_en")),
                "row_hash": hashlib.sha1(
                    json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
        )
    return rows


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    html = client.get_text(config.IRCC_NONCOMPLIANT_URL, cache=True, max_age_s=0)
    legend = parse_legend(html)
    data = client.get_json(JSON_URL, cache=True, max_age_s=0)
    rows = parse_rows(data, legend)
    inserted = 0
    for row in rows:
        if conn.execute("SELECT 1 FROM findings WHERE row_hash = ?", (row["row_hash"],)).fetchone():
            continue
        city, province, postal = parse_address(row["address"])
        # Prefer an employer we already know under either name, the legal name
        # first; otherwise create one so the finding has a profile of its own.
        eid = next(
            (cid for cid in candidate_ids(row["operating_name"], row["legal_name"], province)
             if conn.execute("SELECT 1 FROM employers WHERE id = ?", (cid,)).fetchone()),
            None,
        )
        name = creation_name(row["operating_name"], row["legal_name"])
        if eid is None and name:
            eid = upsert_employer(conn, name, province, source="ircc", city=city,
                                  postal_code=postal, now=stamp)
        conn.execute(
            """
            INSERT INTO findings (employer_id, operating_name, legal_name, address, reasons,
              decision_date, penalty, status, row_hash, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eid, row["operating_name"], row["legal_name"], row["address"], row["reasons"],
                row["decision_date"], row["penalty"], row["status"], row["row_hash"], stamp,
            ),
        )
        inserted += 1
    conn.commit()
    names, streets = enrich_employers(conn, now=stamp)
    log_run(conn, "ircc", detail=f"rows={len(rows)} new={inserted} names={names} streets={streets}",
            rows_in=len(rows), rows_new=inserted)
    return inserted


def candidate_ids(operating: str | None, legal: str | None, province: str | None) -> list[str]:
    """Employer ids a finding could belong to, the legal name's first."""
    out: list[str] = []
    for name in (legal, operating):
        norm = norm_name(name)
        if norm and (cid := employer_id(norm, province)) not in out:
            out.append(cid)
    return out


def creation_name(operating: str | None, legal: str | None) -> str | None:
    """The name a finding's own employer is created under.

    The legal name when it reads as a company (a legal form or a company
    number), so the identity lines up with the lists and the registries; the
    operating name otherwise, because a sole proprietor's legal name is a
    person's name and a profile is never titled with one.
    """
    if legal and (has_legal_form(legal) or is_numbered_company(legal)):
        return legal
    return operating or legal


def _place_key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", fold_accents((text or "").casefold()))


def enrich_employers(conn: sqlite3.Connection, *, now: str | None = None) -> tuple[int, int]:
    """Copy what linked findings know onto their employers; returns (names added, streets added).

    Each finding's operating and legal names become names seen (source
    'ircc'). An employer with no street takes the street of its newest finding
    that has one, provided the city and postal code do not contradict what the
    employer row already holds; street_source records that it came from IRCC.
    """
    stamp = now or now_iso()
    names = streets = 0
    filled: set[str] = set()
    rows = conn.execute(
        """
        SELECT f.employer_id, f.operating_name, f.legal_name, f.address, e.street, e.city, e.postal_code
        FROM findings f JOIN employers e ON e.id = f.employer_id
        ORDER BY f.decision_date DESC, f.id DESC
        """
    ).fetchall()
    for r in rows:
        eid = r["employer_id"]
        names += record_names(conn, eid, "ircc", r["operating_name"], r["legal_name"])
        if r["street"] is not None or eid in filled:
            continue
        street = parse_street(r["address"])
        if not street:
            continue
        city, _, postal = parse_address(r["address"])
        if r["city"] and city and _place_key(r["city"]) != _place_key(city):
            continue
        if r["postal_code"] and postal and r["postal_code"] != postal:
            continue
        conn.execute(
            """
            UPDATE employers SET street = ?, street_source = 'ircc', city = COALESCE(city, ?),
              postal_code = COALESCE(postal_code, ?), updated_at = ?
            WHERE id = ? AND street IS NULL
            """,
            (street, city, postal, stamp, eid),
        )
        filled.add(eid)
        streets += 1
    conn.commit()
    return names, streets
