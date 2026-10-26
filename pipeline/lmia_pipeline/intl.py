"""Postings open to international candidates: the grades, and the files the site reads.

From 2026-11-03 a job offer used for Express Entry points, or for the Federal
Skilled Worker and Federal Skilled Trades job-offer requirement, needs no
LMIA. Such offers leave the LMIA record, and the nearest public trace is a Job
Bank posting whose employer chose "Canadians and international candidates"
and requested no LMIA (sources/jobbank_intl.py reads them). These are signals:
a posting does not show that a job offer was made, and an employer may choose
that audience for many reasons (LMIA-exempt work permits, habit, a planned
LMIA). The site separates what the employer selected from what it inferred.

Grades (grade_posting), computed each night for every posting whose page has
been read and stored with their reasons:

  A  open to international candidates, no LMIA requested, the NOC on IRCC's
     high-wage list, full-time and permanent; or explicit Express Entry
     wording on such a posting.
  B  open to international candidates, no LMIA requested, a TEER 0 to 3 NOC
     not on the list, full-time and permanent.
  C  every other posting open to international candidates without an LMIA
     request.

A posting with an LMIA requested (or approved) keeps the LMIA treatment and
gets no grade; so does one whose page has not been read yet, or whose page
no longer says international candidates may apply. The list tier follows the
NOC alone (the offered wage plays no part, as in IRCC's rule). An employer's
LMIA history is shown beside its postings as context and is never an input.

Reason keys (REASONS) are stored as a JSON list; the site renders each in
both languages and splits them into the employer's selections and the site's
inferences.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .sources import high_wage

GRADES = ("A", "B", "C")
# The day the rule changed; the page marks it on the series.
CHANGE_DATE = "2026-11-03"
# Reason keys. "selected" ones restate what the employer chose on Job Bank;
# "inferred" ones are what the site worked out from the posting.
SELECTED_REASONS = ("intl", "no_lmia", "full_time", "not_full_time", "permanent", "not_permanent")
INFERRED_REASONS = ("high_wage", "teer_listed_no", "teer_low", "no_noc", "ee_wording", "pr_wording", "exempt_wording")
REASONS = SELECTED_REASONS + INFERRED_REASONS
NOC_RE = re.compile(r"^\d{5}$")
# The recent table on the page, the per-employer rows on a profile.
RECENT_ROWS = 100
PROFILE_ROWS = 20
TOP_NOCS = 15
# The daily series reaches this many days before the baseline (the first
# night's sweep), by Job Bank's posting date. Those days undercount: a
# posting that closed before the first sweep was never seen. The page marks
# the baseline on the chart and says so.
BACKFILL_DAYS = 60


def teer(noc: str | None) -> int | None:
    """The TEER of a NOC 2021 unit group: its second digit. None for anything else."""
    return int(noc[1]) if noc and NOC_RE.match(noc) else None


def _phrases(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return [str(v) for v in parsed if v] if isinstance(parsed, list) else []
    return []


def grade_posting(p: dict | sqlite3.Row, listed: dict[str, int]) -> tuple[str | None, list[str]]:
    """(grade or None, reason keys) for one stored posting. Pure: the same row and list give the same answer.

    listed maps each NOC on IRCC's high-wage list to its points. A reason
    "high_wage:<points>" names the tier, "teer_listed_no:<teer>" a TEER 0 to 3
    code off the list, "teer_low:<teer>" a TEER 4 or 5 code.
    """
    row = dict(p)
    if row.get("lmia") in ("requested", "approved"):
        return None, ["lmia_requested"]
    if not row.get("detail_fetched_at") or row.get("audience") == "unknown":
        return None, ["not_read"]
    if row.get("audience") != "international":
        return None, ["not_intl"]
    reasons = ["intl", "no_lmia"]
    full_time = row.get("full_time") == 1
    permanent = row.get("permanent") == 1
    reasons.append("full_time" if full_time else "not_full_time")
    reasons.append("permanent" if permanent else "not_permanent")
    noc = row.get("noc_code")
    level = teer(noc)
    points = listed.get(noc or "")
    if points:
        reasons.append(f"high_wage:{points}")
    elif level is not None and level <= 3:
        reasons.append(f"teer_listed_no:{level}")
    elif level is not None:
        reasons.append(f"teer_low:{level}")
    else:
        reasons.append("no_noc")
    ee = bool(_phrases(row.get("ee_phrases")))
    if ee:
        reasons.append("ee_wording")
    if _phrases(row.get("pr_phrases")):
        reasons.append("pr_wording")
    if _phrases(row.get("exempt_phrases")):
        reasons.append("exempt_wording")
    if (points and full_time and permanent) or ee:
        return "A", reasons
    if level is not None and level <= 3 and not points and full_time and permanent:
        return "B", reasons
    return "C", reasons


def regrade(conn: sqlite3.Connection, listed: dict[str, int] | None = None, *, now: str | None = None) -> Counter:
    """Recompute every stored grade (the list may have been regenerated); returns the count per grade."""
    table = high_wage.points_by_noc(conn) if listed is None else listed
    counts: Counter = Counter()
    updates = []
    for r in conn.execute("SELECT * FROM jobbank_intl_postings"):
        g, reasons = grade_posting(r, table)
        counts[g or "none"] += 1
        text = json.dumps(reasons)
        if g != r["grade"] or text != r["grade_reasons"]:
            updates.append((g, text, now or r["updated_at"], r["posting_id"]))
    conn.executemany("UPDATE jobbank_intl_postings SET grade = ?, grade_reasons = ?, updated_at = ? WHERE posting_id = ?",
                     updates)
    conn.commit()
    return counts


# -- export ---------------------------------------------------------------------


def _row(r: sqlite3.Row, lmia_history: set[str]) -> dict:
    return {
        "id": r["posting_id"],
        "title": r["title"],
        "employer": r["employer_raw"],
        "employer_id": r["employer_id"],
        "lmia_history": bool(r["employer_id"] and r["employer_id"] in lmia_history),
        "noc": r["noc_code"],
        "city": r["city"],
        "prov": r["province"],
        "wage_min": r["wage_min"],
        "wage_max": r["wage_max"],
        "unit": r["wage_unit"],
        "date": r["date_posted"] or (r["first_seen"] or "")[:10],
        "first_seen": (r["first_seen"] or "")[:10],
        "live": bool(r["in_facet"]),
        "grade": r["grade"],
        "reasons": _phrases(r["grade_reasons"]),
        "phrases": {k: _phrases(r[f"{k}_phrases"]) for k in ("ee", "pr", "exempt") if _phrases(r[f"{k}_phrases"])},
        "url": r["url"],
    }


def _employers_with_lmia_history(conn: sqlite3.Connection) -> set[str]:
    """Employers with an LMIA record (an ESDC list row or a Job Bank LMIA posting) among those with a
    posting open to international candidates: context on each row, never a grade input."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT i.employer_id FROM jobbank_intl_postings i WHERE i.employer_id IS NOT NULL AND ("
        "EXISTS (SELECT 1 FROM esdc_records e WHERE e.employer_id = i.employer_id) OR "
        "EXISTS (SELECT 1 FROM jobbank_postings p WHERE p.employer_id = i.employer_id))")}


def _noc_titles(conn: sqlite3.Connection, codes: set[str]) -> dict[str, dict[str, str]]:
    if not codes:
        return {}
    out: dict[str, dict[str, str]] = {}
    ordered = sorted(codes)
    for i in range(0, len(ordered), 500):
        chunk = ordered[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT noc_code, title_en, title_fr FROM noc_titles WHERE noc_code IN ({marks})", chunk):
            out[r[0]] = {"en": r[1], "fr": r[2] or r[1]}
    for o in high_wage.current(conn).get("occupations") or []:
        if isinstance(o, dict) and o.get("noc") in codes and o["noc"] not in out:
            out[o["noc"]] = {"en": o.get("title") or o["noc"], "fr": o.get("title") or o["noc"]}
    return out


def _days(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)] if b >= a else []


def build_index(conn: sqlite3.Connection, data_as_of: str | None) -> dict | None:
    """international/index.json; None before the first pass (the page then says it is not published)."""
    meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'intl_%' OR key LIKE 'high_wage_%'")}
    baseline = meta.get("intl_baseline")
    last_run = meta.get("intl_last_run")
    if not last_run:
        return None
    end = (data_as_of or last_run[:10])[:10]
    anchor = baseline or last_run[:10]
    start = (date.fromisoformat(anchor) - timedelta(days=BACKFILL_DAYS)).isoformat()
    rows = conn.execute("SELECT * FROM jobbank_intl_postings").fetchall()
    history = _employers_with_lmia_history(conn)

    # Daily series by Job Bank's posting date, from BACKFILL_DAYS before the
    # baseline (earlier postings are left out): postings open to international
    # candidates, with or without an LMIA request, and the no-LMIA ones by
    # grade. A posting not yet read counts under "unread".
    daily: dict[str, Counter] = {d: Counter() for d in _days(start, end)}
    for r in rows:
        day = r["date_posted"] or (r["first_seen"] or "")[:10]
        if day not in daily:
            continue
        c = daily[day]
        c["all"] += 1
        if r["lmia"] in ("requested", "approved"):
            c["lmia"] += 1
        elif r["grade"] in GRADES:
            c[r["grade"]] += 1
        else:
            c["unread"] += 1
    series = [{"day": d, **{k: daily[d].get(k, 0) for k in ("all", "lmia", "A", "B", "C", "unread")}} for d in sorted(daily)]

    # The facet's own counts, one row a day (no posting page needed), from the baseline on.
    facet: dict[str, dict[str, int]] = defaultdict(dict)
    for r in conn.execute("SELECT day, key, value FROM jobbank_facet_counts WHERE day >= ? ORDER BY day", (anchor,)):
        facet[r[0]][r[1]] = r[2]
    facet_series = [{"day": d, **facet[d]} for d in sorted(facet)]

    # Live postings (still listed in the facet) by grade, province and NOC.
    live = [r for r in rows if r["in_facet"]]
    live_no_lmia = [r for r in live if r["lmia"] not in ("requested", "approved")]
    by_grade = Counter(r["grade"] or "unread" for r in live_no_lmia)
    by_prov: dict[str, Counter] = defaultdict(Counter)
    by_noc: dict[str, Counter] = defaultdict(Counter)
    for r in live_no_lmia:
        g = r["grade"] or "unread"
        by_prov[r["province"] or "UN"][g] += 1
        if r["noc_code"] and NOC_RE.match(r["noc_code"]):
            by_noc[r["noc_code"]][g] += 1
    listed = high_wage.points_by_noc(conn)
    top_nocs = sorted(by_noc, key=lambda k: (-sum(by_noc[k].values()), k))[:TOP_NOCS]
    titles = _noc_titles(conn, set(top_nocs))

    def counts(c: Counter) -> dict[str, int]:
        return {k: c.get(k, 0) for k in ("A", "B", "C", "unread")}

    recent = sorted(
        (r for r in rows if r["grade"] in GRADES),
        key=lambda r: (r["date_posted"] or "", r["first_seen"] or "", r["posting_id"]), reverse=True,
    )[:RECENT_ROWS]
    return {
        "as_of": end,
        # The two days the page draws as lines on the series: the first sweep
        # (bars before it undercount) and the rule change.
        "baseline": baseline,
        "change_date": CHANGE_DATE,
        "last_run": last_run,
        "sweep_at": meta.get("intl_sweep_at"),
        "high_wage": {**high_wage.list_version(conn), "checked_at": meta.get("high_wage_checked_at")},
        "totals": {
            "live": len(live),
            "live_lmia": len(live) - len(live_no_lmia),
            "live_no_lmia": len(live_no_lmia),
            "unread": by_grade.get("unread", 0),
            "seen": len(rows),
        },
        "by_grade": counts(by_grade),
        "by_province": [{"k": k, **counts(c)} for k, c in sorted(by_prov.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))],
        "by_noc": [{"k": k, "points": listed.get(k), "teer": teer(k), "title": titles.get(k, {"en": k, "fr": k}),
                    **counts(by_noc[k])} for k in top_nocs],
        "daily": series,
        "facet": facet_series,
        "recent": [_row(r, history) for r in recent],
    }


def profile_rows(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """Each employer's postings open to international candidates, newest first, at most PROFILE_ROWS."""
    marks = ",".join("?" * len(ids))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        f"SELECT * FROM jobbank_intl_postings WHERE employer_id IN ({marks}) "
        "ORDER BY employer_id, COALESCE(date_posted, substr(first_seen, 1, 10)) DESC, posting_id DESC", ids):
        eid = r["employer_id"]
        if len(out[eid]) >= PROFILE_ROWS:
            continue
        out[eid].append({
            "id": r["posting_id"],
            "title": r["title"],
            "noc": r["noc_code"],
            "city": r["city"],
            "prov": r["province"],
            "date": r["date_posted"] or (r["first_seen"] or "")[:10],
            "live": bool(r["in_facet"]),
            "lmia": r["lmia"],
            "grade": r["grade"],
            "reasons": _phrases(r["grade_reasons"]),
            "url": r["url"],
        })
    return out


def stats_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """stats.json counts: live postings open to international candidates, without an LMIA request, and graded A."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "jobbank_intl_postings" not in tables:
        return {}
    r = conn.execute(
        "SELECT COUNT(*), SUM(lmia NOT IN ('requested', 'approved')), SUM(grade = 'A') "
        "FROM jobbank_intl_postings WHERE in_facet = 1").fetchone()
    designated = 0
    if "designated_matches" in tables:
        designated = conn.execute("SELECT COUNT(DISTINCT employer_id) FROM designated_matches").fetchone()[0]
    return {"intl_live": r[0] or 0, "intl_no_lmia": r[1] or 0, "intl_grade_a": r[2] or 0,
            "designated_employers": designated}


def write_all(conn: sqlite3.Connection, out: Path, data_as_of: str | None, registers: list[dict] | None = None) -> dict[str, int]:
    """Write international/index.json (an optional export section); nothing before the first pass."""
    from .export_static import _dump  # export_static imports this module

    doc = build_index(conn, data_as_of)
    if doc is None:
        return {"intl_files": 0}
    doc["registers"] = registers or []
    _dump(out / "international" / "index.json", doc)
    return {"intl_files": 1, "intl_recent": len(doc["recent"])}
