"""Indicator rules, version 0.1.

Each rule is a mechanical test over the records and writes a state plus a
plain sentence. A triggered indicator says a pattern is present. It says
nothing about intent, and the Methodology page lists each rule's known false
positives. Rows are rewritten only when the state or basis changed, so the
export can ship just the deltas.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .db import log_run, now_iso
from .normalize import period_quarters, period_sort_key, period_start_date

RULES_VERSION = "0.1"
INDICATORS = [
    "newly_incorporated",
    "repeat_applicant",
    "wage_at_floor",
    "low_wage_high_unemployment",
    "high_volume",
    "refused_then_reposted",
]
NEW_INCORPORATION_DAYS = 365
REPEAT_QUARTERS = 3
HIGH_VOLUME_POSITIONS = 50
HIGH_VOLUME_MULTIPLE = 10
REPOST_WINDOW_DAYS = 90
GRADE_RANK = {"exact": 0, "probable": 1, "possible": 2}


def _d(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _quarter_index(year: int, q: int) -> int:
    return year * 4 + (q - 1)


def _longest_run(indices: set[int]) -> tuple[int, int | None, int | None]:
    best = 0
    best_start = best_end = None
    for start in sorted(indices):
        if start - 1 in indices:
            continue
        end = start
        while end + 1 in indices:
            end += 1
        if end - start + 1 > best:
            best, best_start, best_end = end - start + 1, start, end
    return best, best_start, best_end


def _label(index: int) -> str:
    return f"{index // 4}Q{index % 4 + 1}"


def compute(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    employer_ids = [r["id"] for r in conn.execute("SELECT id FROM employers")]

    registry: dict[str, sqlite3.Row] = {}
    for r in conn.execute("SELECT employer_id, registered_on, legal_name, grade FROM registry_matches"):
        current = registry.get(r["employer_id"])
        if current is None or GRADE_RANK.get(r["grade"], 3) < GRADE_RANK.get(current["grade"], 3):
            registry[r["employer_id"]] = r

    earliest_pending: dict[str, str] = {}
    for r in conn.execute(
        "SELECT employer_id, MIN(COALESCE(date_posted, substr(first_seen, 1, 10))) AS d "
        "FROM jobbank_postings WHERE flag_current = 'requested' GROUP BY employer_id"
    ):
        if r["d"]:
            earliest_pending[r["employer_id"]] = r["d"]

    posting_dates: dict[str, list[date]] = defaultdict(list)
    for r in conn.execute("SELECT employer_id, first_seen FROM jobbank_postings"):
        d = _d(r["first_seen"])
        if d:
            posting_dates[r["employer_id"]].append(d)

    positive_by_noc: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    positions_by_period: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latest_positive_period: dict[str, str] = {}
    for r in conn.execute(
        "SELECT employer_id, period, noc_code, SUM(COALESCE(positions, 0)) AS positions "
        "FROM esdc_records WHERE list = 'positive' GROUP BY employer_id, period, noc_code"
    ):
        eid, period = r["employer_id"], r["period"]
        for year, q in period_quarters(period):
            positive_by_noc[eid][r["noc_code"] or "?"].add(_quarter_index(year, q))
        positions_by_period[eid][period] += int(r["positions"] or 0)
        current = latest_positive_period.get(eid)
        if current is None or period_sort_key(period) > period_sort_key(current):
            latest_positive_period[eid] = period

    refusals: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT r.employer_id, r.period, res.published FROM esdc_records r "
        "LEFT JOIN esdc_resources res ON res.resource_id = r.resource_id WHERE r.list = 'negative'"
    ):
        refusals[r["employer_id"]].append((r["period"], r["published"]))

    low_wage = {
        r["employer_id"]
        for r in conn.execute("SELECT DISTINCT employer_id FROM esdc_records WHERE lower(stream) LIKE '%low%'")
    }

    existing: dict[tuple[str, str], tuple[str, str]] = {
        (r["employer_id"], r["indicator"]): (r["state"], r["basis"])
        for r in conn.execute("SELECT employer_id, indicator, state, basis FROM indicators")
    }

    changed: list[tuple[str, str, str, str, str, str]] = []
    for eid in employer_ids:
        results = {
            "newly_incorporated": _newly_incorporated(
                registry.get(eid), earliest_pending.get(eid), latest_positive_period.get(eid)
            ),
            "repeat_applicant": _repeat_applicant(positive_by_noc.get(eid)),
            "high_volume": _high_volume(positions_by_period.get(eid)),
            "refused_then_reposted": _refused_then_reposted(refusals.get(eid), posting_dates.get(eid)),
            "wage_at_floor": ("not_evaluated", "Prevailing wage table not yet loaded."),
            "low_wage_high_unemployment": (
                ("not_evaluated", "Regional unemployment table not yet loaded.")
                if eid in low_wage
                else ("not_applicable", "No low-wage stream records.")
            ),
        }
        for name, (state, basis) in results.items():
            if existing.get((eid, name)) != (state, basis):
                changed.append((eid, name, state, basis, RULES_VERSION, stamp))

    conn.executemany(
        "INSERT OR REPLACE INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        changed,
    )
    conn.commit()
    log_run(conn, "indicators", detail=f"employers={len(employer_ids)} changed={len(changed)}",
            rows_in=len(employer_ids), rows_new=len(changed))
    return len(changed)


def _newly_incorporated(reg: sqlite3.Row | None, earliest_pending: str | None,
                        latest_period: str | None) -> tuple[str, str]:
    if reg is None or not reg["registered_on"]:
        return "not_evaluated", "No registry match yet."
    registered = _d(reg["registered_on"])
    ref = _d(earliest_pending) or (_d(period_start_date(latest_period)) if latest_period else None)
    if registered is None or ref is None:
        return "not_applicable", "No pending posting or list record to compare against."
    days = (ref - registered).days
    if 0 <= days < NEW_INCORPORATION_DAYS:
        return "triggered", f"Registered {registered.isoformat()}, first record {ref.isoformat()} ({days} days)."
    if days < 0:
        return "not_triggered", f"Registered {registered.isoformat()}, after the first record ({ref.isoformat()})."
    return "not_triggered", f"Registered {registered.isoformat()}, {days} days before the first record."


def _repeat_applicant(by_noc: dict[str, set[int]] | None) -> tuple[str, str]:
    if not by_noc:
        return "not_applicable", "No positive-list rows."
    best = (0, None, None, "?")
    for noc, quarters in by_noc.items():
        run, start, end = _longest_run(quarters)
        if run > best[0]:
            best = (run, start, end, noc)
    run, start, end, noc = best
    if run >= REPEAT_QUARTERS and start is not None and end is not None:
        return "triggered", f"NOC {noc}: positive list in {run} consecutive quarters ({_label(start)} to {_label(end)})."
    return "not_triggered", f"Longest run of consecutive quarters for one occupation: {run}."


def _high_volume(by_period: dict[str, int] | None) -> tuple[str, str]:
    if not by_period:
        return "not_applicable", "No positive-list rows."
    period, top = max(by_period.items(), key=lambda kv: kv[1])
    if top >= HIGH_VOLUME_POSITIONS:
        return "triggered", f"{top} positions approved in {period}."
    if len(by_period) >= 2:
        median = statistics.median(by_period.values())
        if median > 0 and top >= HIGH_VOLUME_MULTIPLE * median:
            return "triggered", f"{top} positions in {period}, against a median quarter of {median:g}."
    return "not_triggered", f"Largest quarter: {top} positions ({period})."


def _refused_then_reposted(refs: list[tuple[str, str | None]] | None,
                           postings: list[date] | None) -> tuple[str, str]:
    if not refs:
        return "not_applicable", "No negative-list rows."
    for period, published in refs:
        pub = _d(published)
        if pub is None:
            continue
        for seen in postings or []:
            if pub < seen <= pub + timedelta(days=REPOST_WINDOW_DAYS):
                return "triggered", (
                    f"Refused in {period} (list published {pub.isoformat()}); "
                    f"new posting observed {seen.isoformat()}."
                )
    return "not_triggered", (
        f"{len(refs)} refusal record(s), no new posting within {REPOST_WINDOW_DAYS} days of publication."
    )
