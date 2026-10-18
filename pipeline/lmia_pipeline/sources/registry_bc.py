"""BC corporate registry through OrgBook BC (public API, no key).

Only BC employers are looked up. A match is graded, never assumed: the
posting usually carries a trade name and the registry a legal name, so the
raw strings are kept and the grade is shown on the profile.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from .. import config
from ..db import log_run, now_iso
from ..http import FetchError, PoliteClient
from ..normalize import iso_date, norm_name

log = logging.getLogger(__name__)

REGISTRY = "bc_orgbook"
RECHECK_DAYS = 30


def search(client: PoliteClient, name: str) -> list[dict]:
    url = f"{config.ORGBOOK_SEARCH}?{urlencode({'q': name, 'inactive': 'false'})}"
    data = client.get_json(url)
    return list(data.get("results") or [])


def grade(norm_employer: str, legal_name: str) -> str:
    legal = norm_name(legal_name)
    if not legal or not norm_employer:
        return "possible"
    if legal == norm_employer:
        return "exact"
    if legal.startswith(norm_employer) or norm_employer.startswith(legal) \
            or legal in norm_employer or norm_employer in legal:
        return "probable"
    return "possible"


def pick_match(norm_employer: str, results: list[dict]) -> dict | None:
    """Best result: an exact normalized-name match if any, else the first hit."""
    best = None
    best_rank = 3
    rank = {"exact": 0, "probable": 1, "possible": 2}
    for r in results[:10]:
        names = [n.get("text") for n in (r.get("names") or []) if n.get("text")]
        if not names:
            continue
        for legal in names:
            g = grade(norm_employer, legal)
            if rank[g] < best_rank:
                best_rank = rank[g]
                best = {"result": r, "legal_name": legal, "grade": g}
        if best_rank == 0:
            break
    return best


def _attrs(result: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in result.get("attributes") or []:
        if a.get("type") and a.get("value") is not None:
            out[a["type"]] = str(a["value"])
    return out


def run(
    conn: sqlite3.Connection,
    client: PoliteClient,
    *,
    budget: int = 300,
    now: str | None = None,
) -> int:
    stamp = now or now_iso()
    cutoff = (datetime.fromisoformat(stamp.replace("Z", "+00:00")) - timedelta(days=RECHECK_DAYS))
    cutoff_iso = cutoff.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = conn.execute(
        """
        SELECT e.id, e.display_name, e.norm_name FROM employers e
        WHERE e.province = 'BC'
          AND e.id NOT IN (SELECT employer_id FROM registry_checks WHERE registry = ? AND checked_at > ?)
        ORDER BY e.updated_at DESC LIMIT ?
        """,
        (REGISTRY, cutoff_iso, budget),
    ).fetchall()
    matched = 0
    for row in rows:
        try:
            results = search(client, row["display_name"])
        except FetchError as exc:
            log.warning("orgbook %s: %s", row["display_name"], exc)
            continue
        best = pick_match(row["norm_name"], results)
        if best is not None:
            r = best["result"]
            attrs = _attrs(r)
            conn.execute(
                """
                INSERT INTO registry_matches (employer_id, registry, registry_id, legal_name,
                  entity_type, status, registered_on, grade, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employer_id, registry, registry_id) DO UPDATE SET
                  legal_name = excluded.legal_name, entity_type = excluded.entity_type,
                  status = excluded.status, registered_on = excluded.registered_on,
                  grade = excluded.grade, checked_at = excluded.checked_at
                """,
                (
                    row["id"], REGISTRY, str(r.get("source_id") or ""), best["legal_name"],
                    attrs.get("entity_type"), attrs.get("entity_status"),
                    iso_date(attrs.get("registration_date")), best["grade"], stamp,
                ),
            )
            matched += 1
        conn.execute(
            "INSERT INTO registry_checks (employer_id, registry, checked_at) VALUES (?, ?, ?) "
            "ON CONFLICT(employer_id, registry) DO UPDATE SET checked_at = excluded.checked_at",
            (row["id"], REGISTRY, stamp),
        )
        conn.commit()
    log_run(conn, "registry", detail=f"checked={len(rows)} matched={matched}", rows_in=len(rows), rows_new=matched)
    return matched
