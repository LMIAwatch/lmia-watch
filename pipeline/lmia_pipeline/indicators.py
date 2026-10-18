"""Indicator rules, version 0.2.

Each rule is a mechanical test over the records and writes a state plus a
plain sentence. A triggered indicator says a pattern is present. It says
nothing about intent, and the Methodology page lists each rule's known false
positives. Rows are rewritten only when the state or basis changed, so the
export can ship just the deltas.
"""

from __future__ import annotations

import re
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .db import log_run, now_iso
from .normalize import (
    POSTAL_RE, PROVINCE_NAMES, PRUID_PROVINCE, period_quarters, period_sort_key, period_start_date,
)

RULES_VERSION = "0.2"
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
WAGE_FLOOR_TOLERANCE = 0.01
# ESDC refuses to process low-wage applications submitted on or after
# 2024-09-26 in census metropolitan areas at or above this rate. Rows are
# taken from the first full quarter after that date.
UNEMPLOYMENT_THRESHOLD = 6.0
LOW_WAGE_FROM = (2025, 1)


@dataclass
class Area:
    er_uid: str | None
    er_name: str | None
    cma_uid: str | None
    cma_name: str | None


@dataclass
class WageTables:
    tables: list[tuple[str, str]]                      # (resource_id, revision_date), oldest first
    medians: dict[tuple[str, str, str], tuple[float, int]]  # (resource_id, noc, area_code) -> (median, annual)

    def in_force(self, on: str | None) -> tuple[str, str]:
        chosen = self.tables[0]
        for table in self.tables:
            if on is None or (table[1] or "") <= on:
                chosen = table
        return chosen


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
    low_wage_rows: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT employer_id, period, postal_code FROM esdc_records WHERE list = 'positive' AND lower(stream) LIKE '%low%'"
    ):
        low_wage_rows[r["employer_id"]].append((r["period"], r["postal_code"]))

    areas = {
        r["fsa"]: Area(r["er_uid"], r["er_name"], r["cma_uid"], r["cma_name"])
        for r in conn.execute("SELECT fsa, er_uid, er_name, cma_uid, cma_name FROM fsa_regions")
    }
    wage_tables = WageTables(
        [(r["resource_id"], r["revision_date"] or "") for r in
         conn.execute("SELECT resource_id, revision_date FROM wage_tables ORDER BY revision_date, resource_id")],
        {(r["resource_id"], r["noc_code"], r["area_code"]): (float(r["median"]), int(r["annual"])) for r in
         conn.execute("SELECT resource_id, noc_code, area_code, median, annual FROM jobbank_wages")},
    )
    rates: dict[tuple[str, str], float] = {}
    cma_names: dict[str, str] = {}
    for r in conn.execute("SELECT cma_uid, ref_month, rate, cma_name FROM lfs_unemployment ORDER BY ref_month"):
        rates[(r["cma_uid"], r["ref_month"])] = float(r["rate"])
        cma_names[r["cma_uid"]] = r["cma_name"]

    postings: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(
        "SELECT posting_id, employer_id, noc_code, wage_min, wage_max, wage_unit, postal_code, city, street, "
        "province, date_posted, first_seen FROM jobbank_postings"
    ):
        postings[r["employer_id"]].append(r)

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
            "wage_at_floor": _wage_at_floor(postings.get(eid), wage_tables, areas),
            "low_wage_high_unemployment": _low_wage_high_unemployment(
                eid in low_wage, low_wage_rows.get(eid), areas, rates, cma_names
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


# -- wage at the prevailing-wage floor -------------------------------------------

WAGE_REASONS = [
    "No posting page parsed yet, so the occupation is unknown.",
    "No posting has a postal code that places it in an economic region.",
    "No Job Bank median for NOC {noc}.",
    "No posted wage matches the hourly or yearly unit of the Job Bank median.",
]


def _posting_fsa(p: sqlite3.Row) -> str | None:
    # A few postings carry the postal code inside the city or province text.
    for text in (p["postal_code"], p["city"], p["street"], p["province"]):
        if text:
            m = POSTAL_RE.search(text)
            if m:
                return m.group(1).upper()
    return None


def _money(value: float, annual: bool) -> str:
    return f"{value:,.0f}" if annual else f"{value:.2f}"


def _compare_posting(p: sqlite3.Row, tables: WageTables, areas: dict[str, Area]) -> tuple[int, dict]:
    """How far a posting gets through the inputs: 0 no occupation, 1 not placed,
    2 no median, 3 unit mismatch, 4 compared (with the figures)."""
    noc = (p["noc_code"] or "").strip()
    if not re.fullmatch(r"\d{5}", noc):
        return 0, {}
    fsa = _posting_fsa(p)
    area = areas.get(fsa) if fsa else None
    if area is None or not area.er_uid:
        return 1, {}
    table_id, revision = tables.in_force(p["date_posted"] or (p["first_seen"] or "")[:10] or None)
    province = PRUID_PROVINCE.get(area.er_uid[:2], "")
    prov_name = PROVINCE_NAMES.get(province, province)
    # ESDC: the economic region's median, else the province's, else Canada's.
    choices = [
        (area.er_uid, f"the {area.er_name or area.er_uid} economic region ({prov_name})"),
        (area.er_uid[:2], f"{prov_name} (provincial figure)"),
        ("00", "Canada (national figure)"),
    ]
    for code, label in choices:
        hit = tables.medians.get((table_id, noc, code))
        if hit:
            break
    else:
        return 2, {"noc": noc}
    median, annual = hit
    posted = p["wage_min"] if p["wage_min"] is not None else p["wage_max"]
    if posted is None or posted <= 0 or (p["wage_unit"] or "").upper() != ("YEAR" if annual else "HOUR"):
        return 3, {"noc": noc}
    return 4, {
        "posting_id": int(p["posting_id"]),
        "gap": round(abs(posted - median) / median, 9),
        "posted": _money(posted, bool(annual)),
        "median": _money(median, bool(annual)),
        "unit": "yr" if annual else "h",
        "noc": noc,
        "area": label,
        "date": revision,
    }


def _wage_at_floor(postings: list[sqlite3.Row] | None, tables: WageTables,
                   areas: dict[str, Area]) -> tuple[str, str]:
    if not postings:
        return "not_applicable", "No Job Bank posting."
    if not tables.tables:
        return "not_evaluated", "Prevailing wage table not yet loaded."
    compared: list[dict] = []
    furthest: tuple[int, dict] = (0, {})
    for p in postings:
        stage, info = _compare_posting(p, tables, areas)
        if stage == 4:
            compared.append(info)
        elif stage >= furthest[0]:
            furthest = (stage, info)
    if not compared:
        stage, info = furthest
        return "not_evaluated", WAGE_REASONS[stage].format(**info)
    best = min(compared, key=lambda c: (c["gap"], -c["posting_id"]))
    posted = f"${best['posted']}/{best['unit']}"
    median = f"${best['median']}/{best['unit']}"
    where = f"NOC {best['noc']} in {best['area']}, wage table dated {best['date']}."
    if best["gap"] <= WAGE_FLOOR_TOLERANCE:
        return "triggered", (
            f"Posting {best['posting_id']}: posted minimum {posted} is within 1 percent of the "
            f"Job Bank median {median} for {where}"
        )
    return "not_triggered", (
        f"Closest of {len(compared)} posting(s) compared: posting {best['posting_id']}, posted minimum "
        f"{posted} against the Job Bank median {median} for {where}"
    )


# -- low-wage stream in a high-unemployment area ----------------------------------

def _reference_month(year: int, q: int) -> str:
    """Last month of the three-month window in force when the quarter began."""
    return f"{year - 1}-12" if q == 1 else f"{year}-{3 * (q - 1):02d}"


def _low_wage_high_unemployment(any_low_wage: bool, rows: list[tuple[str, str | None]] | None,
                                areas: dict[str, Area], rates: dict[tuple[str, str], float],
                                cma_names: dict[str, str]) -> tuple[str, str]:
    if not any_low_wage:
        return "not_applicable", "No low-wage stream records."
    start = _quarter_index(*LOW_WAGE_FROM)
    start_label = f"{LOW_WAGE_FROM[0]}Q{LOW_WAGE_FROM[1]}"
    in_scope: list[tuple[str, int, int, str | None]] = []
    for period, postal in rows or []:
        quarters = period_quarters(period)
        if len(quarters) == 1 and _quarter_index(*quarters[0]) >= start:
            in_scope.append((period, quarters[0][0], quarters[0][1], postal))
    if not in_scope:
        return "not_applicable", f"No low-wage approvals from {start_label} on."
    if not rates:
        return "not_evaluated", "Regional unemployment table not yet loaded."
    placed = 0
    best: tuple[tuple[int, float], str, Area, str, float, str, float] | None = None
    for period, year, q, postal in in_scope:
        fsa = postal.strip().upper()[:3] if postal else None
        area = areas.get(fsa) if fsa else None
        if area is None or not area.er_uid:
            continue
        if not area.cma_uid:
            placed += 1
            continue
        # The list gives the decision quarter, not the submission date, so the
        # rate must have been at the threshold in the window in force when the
        # quarter began and in the one before it.
        index = _quarter_index(year, q) - 1
        month_before = _reference_month(index // 4, index % 4 + 1)
        month = _reference_month(year, q)
        rate_before = rates.get((area.cma_uid, month_before))
        rate = rates.get((area.cma_uid, month))
        if rate is None or rate_before is None:
            continue
        placed += 1
        if rate >= UNEMPLOYMENT_THRESHOLD and rate_before >= UNEMPLOYMENT_THRESHOLD:
            key = (_quarter_index(year, q), min(rate, rate_before))
            if best is None or key > best[0]:
                best = (key, period, area, month_before, rate_before, month, rate)
    if best is not None:
        _, period, area, month_before, rate_before, month, rate = best
        name = cma_names.get(area.cma_uid or "") or area.cma_name or area.cma_uid
        return "triggered", (
            f"Low Wage stream approval in {period}; the {name} CMA unemployment rate was {rate_before:.1f} percent "
            f"for the three months ending {month_before} and {rate:.1f} percent for the three months ending "
            f"{month} (Statistics Canada LFS)."
        )
    if placed:
        return "not_triggered", (
            f"{placed} low-wage positive-list row(s) from {start_label} on; none in a census metropolitan area "
            f"at or above 6 percent in both three-month periods checked."
        )
    return "not_evaluated", "The low-wage approvals could not be placed in an area with a published unemployment rate."
