"""Employer rollups, the status lifecycle, and the meta counters.

Runs after every source so the employers table always reflects the records.
A row is rewritten only when something changed, so updated_at doubles as the
high-water mark for the incremental D1 export.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

from . import indicators
from .db import log_run, now_iso, set_meta, today_iso
from .normalize import period_end_date, period_sort_key, period_start_date

GRADE_RANK = {"exact": 0, "probable": 1, "possible": 2}
LAPSE_LISTS = 2


def _date(text: str | None) -> str | None:
    return text[:10] if text else None


def recompute(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    stamp = now or now_iso()
    today = stamp[:10] if now else today_iso()

    postings: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(
        "SELECT employer_id, employer_raw, date_posted, first_seen, last_seen, flag_current, "
        "flag_first, approved_seen_at, valid_through FROM jobbank_postings"
    ):
        postings[r["employer_id"]].append(r)

    esdc: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(
        "SELECT employer_id, employer_raw, list, period, lmias, positions FROM esdc_records"
    ):
        esdc[r["employer_id"]].append(r)

    findings: dict[str, list[str | None]] = defaultdict(list)
    for r in conn.execute("SELECT employer_id, decision_date FROM findings WHERE employer_id IS NOT NULL"):
        findings[r["employer_id"]].append(r["decision_date"])

    triggered = {
        r["employer_id"]: r["n"]
        for r in conn.execute(
            "SELECT employer_id, COUNT(*) AS n FROM indicators WHERE state = 'triggered' GROUP BY employer_id"
        )
    }
    grades: dict[str, str] = {}
    for r in conn.execute("SELECT employer_id, grade FROM registry_matches"):
        if GRADE_RANK.get(r["grade"], 3) < GRADE_RANK.get(grades.get(r["employer_id"], ""), 3):
            grades[r["employer_id"]] = r["grade"]

    positive_published = [
        r["published"]
        for r in conn.execute("SELECT published FROM esdc_resources WHERE dataset = 'positive' AND published IS NOT NULL")
    ]

    existing = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, display_name, current_status, first_seen, last_seen, pending_count, approved_lmias, "
            "approved_positions, refused_lmias, refused_positions, finding_count, indicator_count, registry_grade "
            "FROM employers"
        )
    }

    updates = 0
    for eid, row in existing.items():
        p_rows = postings.get(eid, [])
        e_rows = esdc.get(eid, [])
        pending_count = sum(1 for p in p_rows if p["flag_current"] == "requested")
        approved_lmias = sum(int(e["lmias"] or 0) for e in e_rows if e["list"] == "positive")
        approved_positions = sum(int(e["positions"] or 0) for e in e_rows if e["list"] == "positive")
        refused_lmias = sum(int(e["lmias"] or 0) for e in e_rows if e["list"] == "negative")
        refused_positions = sum(int(e["positions"] or 0) for e in e_rows if e["list"] == "negative")
        finding_count = len(findings.get(eid, []))
        indicator_count = int(triggered.get(eid, 0))
        grade = grades.get(eid, "none")

        dates: list[str] = []
        for p in p_rows:
            for d in (p["date_posted"], _date(p["first_seen"]), _date(p["approved_seen_at"])):
                if d:
                    dates.append(d)
        for e in e_rows:
            for d in (period_start_date(e["period"]), period_end_date(e["period"])):
                if d:
                    dates.append(d)
        dates.extend(d for d in findings.get(eid, []) if d)
        first_seen = min(dates) if dates else None
        last_seen = max(dates) if dates else None

        status = _status(p_rows, e_rows, pending_count, today, positive_published)
        display_name = _display_name(p_rows, e_rows) or row["display_name"]

        new = (display_name, status, first_seen, last_seen, pending_count, approved_lmias, approved_positions,
               refused_lmias, refused_positions, finding_count, indicator_count, grade)
        old = (row["display_name"], row["current_status"], row["first_seen"], row["last_seen"],
               row["pending_count"], row["approved_lmias"], row["approved_positions"], row["refused_lmias"],
               row["refused_positions"], row["finding_count"], row["indicator_count"], row["registry_grade"])
        if new == old:
            continue
        conn.execute(
            """
            UPDATE employers SET display_name = ?, current_status = ?, first_seen = ?, last_seen = ?,
              pending_count = ?, approved_lmias = ?, approved_positions = ?, refused_lmias = ?,
              refused_positions = ?, finding_count = ?, indicator_count = ?, registry_grade = ?,
              status_changed_at = CASE WHEN current_status != ? THEN ? ELSE status_changed_at END,
              updated_at = ?
            WHERE id = ?
            """,
            (*new, status, stamp, stamp, eid),
        )
        updates += 1
    conn.commit()
    _write_meta(conn, today)
    log_run(conn, "status", detail=f"employers={len(existing)} updated={updates}", rows_in=len(existing), rows_new=updates)
    return updates


def _display_name(p_rows: list[sqlite3.Row], e_rows: list[sqlite3.Row]) -> str | None:
    if p_rows:
        latest = max(p_rows, key=lambda p: p["last_seen"] or "")
        return latest["employer_raw"]
    if e_rows:
        latest = max(e_rows, key=lambda e: period_sort_key(e["period"]))
        return latest["employer_raw"]
    return None


def _status(p_rows: list[sqlite3.Row], e_rows: list[sqlite3.Row], pending_count: int,
            today: str, positive_published: list[str]) -> str:
    if pending_count > 0:
        return "pending"
    events: list[tuple[str, str]] = []
    for p in p_rows:
        if p["approved_seen_at"]:
            events.append((_date(p["approved_seen_at"]) or "", "approved"))
    for e in e_rows:
        end = period_end_date(e["period"]) or ""
        events.append((end, "approved" if e["list"] == "positive" else "refused"))
    for p in p_rows:
        if p["flag_first"] == "requested" and p["flag_current"] == "gone" and not p["approved_seen_at"]:
            closed = p["valid_through"] or _date(p["last_seen"]) or ""
            lists_since = sum(1 for pub in positive_published if pub and pub > closed)
            if closed and closed < today and lists_since >= LAPSE_LISTS:
                events.append((closed, "lapsed"))
    if not events:
        return "none"
    # On a tie an approval outranks a refusal, which outranks a lapse.
    order = {"approved": 0, "refused": 1, "lapsed": 2}
    events.sort(key=lambda ev: (ev[0], -order[ev[1]]))
    return events[-1][1]


def _write_meta(conn: sqlite3.Connection, today: str) -> None:
    set_meta(conn, "data_as_of", today)
    set_meta(conn, "rules_version", indicators.RULES_VERSION)
    periods = [r["period"] for r in conn.execute("SELECT DISTINCT period FROM esdc_resources WHERE dataset = 'positive'")]
    latest = max(periods, key=period_sort_key) if periods else None
    if latest:
        set_meta(conn, "esdc_latest_period", latest)
        pub = conn.execute(
            "SELECT MAX(published) AS p FROM esdc_resources WHERE dataset = 'positive' AND period = ?", (latest,)
        ).fetchone()["p"]
        if pub:
            set_meta(conn, "esdc_latest_published", pub)
    pending = conn.execute("SELECT COUNT(*) AS n FROM jobbank_postings WHERE flag_current = 'requested'").fetchone()["n"]
    set_meta(conn, "count_pending", pending)
    if latest:
        pos = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(positions), 0) AS p FROM esdc_records WHERE list = 'positive' AND period = ?",
            (latest,),
        ).fetchone()
        set_meta(conn, "count_approved_records", pos["n"])
        set_meta(conn, "count_approved_positions", pos["p"])
        neg = conn.execute(
            "SELECT COUNT(*) AS n FROM esdc_records WHERE list = 'negative' AND period = ?", (latest,)
        ).fetchone()["n"]
        set_meta(conn, "count_refused_records", neg)
    set_meta(conn, "count_findings", conn.execute("SELECT COUNT(*) AS n FROM findings").fetchone()["n"])
    conn.commit()
