"""BC corporate registry through OrgBook BC (public API, no key).

Only BC employers are looked up. A match is graded, never assumed: the
posting usually carries a trade name and the registry a legal name, so the
raw strings are kept and the grade is shown on the profile.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlencode

from .. import config
from ..db import log_run, now_iso
from ..http import FetchError, PoliteClient
from ..normalize import iso_date, norm_name, period_sort_key, split_trade_name

log = logging.getLogger(__name__)

REGISTRY = "bc_orgbook"
RECHECK_DAYS = 180
# OrgBook publishes no crawl delay, so the client's default of one request a
# second applies. Measured 2026-10-17, a search answers in about 0.3 s, so a
# lookup takes about 1.3 s with the spacing and 15 minutes hold about 700. The
# time cap is the binding limit when the API is slow.
DEFAULT_BUDGET = 700
MAX_SECONDS = 15 * 60


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


def candidates(conn: sqlite3.Connection, *, budget: int, cutoff_iso: str) -> list[sqlite3.Row]:
    """BC employers not checked since the cutoff, the most useful first.

    Tier 0 has a pending Job Bank posting, tier 1 a record on the latest ESDC
    quarter, tier 2 an IRCC finding, tier 3 is everyone else; within a tier the
    most recently seen come first.
    """
    periods = [r["period"] for r in conn.execute("SELECT DISTINCT period FROM esdc_resources")]
    latest = max(periods, key=period_sort_key) if periods else ""
    return conn.execute(
        """
        SELECT e.id, e.display_name, e.norm_name,
          CASE
            WHEN EXISTS (SELECT 1 FROM jobbank_postings p WHERE p.employer_id = e.id AND p.flag_current = 'requested') THEN 0
            WHEN EXISTS (SELECT 1 FROM esdc_records r WHERE r.employer_id = e.id AND r.period = :latest) THEN 1
            WHEN EXISTS (SELECT 1 FROM findings f WHERE f.employer_id = e.id) THEN 2
            ELSE 3
          END AS tier
        FROM employers e
        WHERE e.province = 'BC' AND e.norm_name != ''
          AND e.id NOT IN (SELECT employer_id FROM registry_checks WHERE registry = :registry AND checked_at > :cutoff)
        ORDER BY tier, e.last_seen DESC, e.id
        LIMIT :budget
        """,
        {"latest": latest, "registry": REGISTRY, "cutoff": cutoff_iso, "budget": budget},
    ).fetchall()


def run(
    conn: sqlite3.Connection,
    client: PoliteClient,
    *,
    budget: int = DEFAULT_BUDGET,
    max_seconds: float = MAX_SECONDS,
    now: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    stamp = now or now_iso()
    cutoff = (datetime.fromisoformat(stamp.replace("Z", "+00:00")) - timedelta(days=RECHECK_DAYS))
    cutoff_iso = cutoff.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = candidates(conn, budget=budget, cutoff_iso=cutoff_iso)
    started = clock()
    matched = checked = 0
    for row in rows:
        if clock() - started > max_seconds:
            log.info("orgbook: time cap reached after %d lookups", checked)
            break
        # The query is the legal name: a trade name after "dba" or "o/a" only
        # adds noise to OrgBook's search.
        query = split_trade_name(row["display_name"])[0] or row["display_name"]
        checked += 1
        try:
            results = search(client, query)
        except FetchError as exc:
            log.warning("orgbook %s: %s", query, exc)
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
    log_run(conn, "registry", detail=f"checked={checked} matched={matched} queued={len(rows)}",
            rows_in=checked, rows_new=matched)
    return matched
