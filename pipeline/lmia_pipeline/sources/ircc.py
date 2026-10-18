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
from ..db import log_run, now_iso, upsert_employer
from ..http import PoliteClient
from ..normalize import employer_id, norm_name, parse_address

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
        name = row["operating_name"] or row["legal_name"]
        eid = None
        if name:
            # Prefer an employer we already know under either name; otherwise
            # create one so the finding is searchable on its own profile.
            for candidate in (row["operating_name"], row["legal_name"]):
                if not candidate:
                    continue
                cid = employer_id(norm_name(candidate), province)
                if conn.execute("SELECT 1 FROM employers WHERE id = ?", (cid,)).fetchone():
                    eid = cid
                    break
            if eid is None:
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
    log_run(conn, "ircc", detail=f"rows={len(rows)} new={inserted}", rows_in=len(rows), rows_new=inserted)
    return inserted
