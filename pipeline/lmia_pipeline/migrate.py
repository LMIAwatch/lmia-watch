"""Re-derive employer ids after a change to name normalization.

An employer id is sha1(norm_name, province), so a change to normalize.norm_name
moves records to other ids: spellings that differed only by a trade-name
suffix ("X Ltd. o/a Y"), abbreviation dots or accents now share one, and a
few spellings that used to share one now differ. This module rebuilds the
employers table from the records themselves:

* each Job Bank posting and ESDC row goes to employer_id(norm_name(its raw
  employer name), the province its old employer had);
* each IRCC finding is linked again, legal name first, as sources/ircc.py
  links a new finding;
* each name seen follows the records of the employer it was recorded under,
  and an operating name split off a raw spelling is added beside it;
* registry matches and indicators follow the old employer's main new id (the
  one its display name maps to, else the one most of its records went to).
  A BC Registry check is kept only where the id did not change, so a renamed
  employer is looked up again under its legal name. Bulk registries (the
  federal and Quebec extracts) are re-normalized and matched again;
* an employer row keeps the earliest first_seen and any location field one
  of its merged rows had; counts, status and display names are recomputed by
  status.recompute.

The pipeline runs this once, when meta.normalize_version is older than
normalize.NORMALIZE_VERSION. Running it again on a migrated database changes
nothing. The site's own tables in D1 (employer_responses, corrections) keep
the ids they were written with; there were none when version 2 shipped. A
paid-plan D1 copy needs a full re-export (run --export --d1 --full) after a
migration, because ids disappear.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from . import status
from .db import get_meta, log_run, now_iso, set_meta
from .normalize import NORMALIZE_VERSION, employer_id, norm_name, parse_address, split_trade_name
from .sources import ircc, registry_bc, registry_federal, registry_quebec

log = logging.getLogger(__name__)

META_KEY = "normalize_version"
# Registries matched offline from a bulk extract: their rows are dropped and
# rebuilt by the module's own match() after the extract is re-normalized.
BULK_REGISTRIES = {
    registry_federal.REGISTRY: registry_federal,
    registry_quebec.REGISTRY: registry_quebec,
}


@dataclass
class Report:
    employers_before: int = 0
    employers_after: int = 0
    ids_changed: int = 0       # old ids that no longer exist
    merge_groups: int = 0      # new ids built from two or more old employers
    merged: int = 0            # old employers that went into such a group
    split: int = 0             # old employers whose records went to two or more ids
    dropped: int = 0           # old employers left with no record
    findings_relinked: int = 0
    registry_renormalized: int = 0
    names_added: int = 0
    streets_added: int = 0

    def __str__(self) -> str:
        return " ".join(f"{k}={v}" for k, v in asdict(self).items())


def current_version(conn: sqlite3.Connection) -> int:
    try:
        return int(get_meta(conn, META_KEY) or 1)
    except ValueError:
        return 1


def ensure_current(conn: sqlite3.Connection, *, now: str | None = None) -> Report | None:
    """Migrate when the database predates the code's normalization; None when nothing to do."""
    if current_version(conn) >= NORMALIZE_VERSION:
        return None
    report = rederive(conn, now=now)
    set_meta(conn, META_KEY, NORMALIZE_VERSION)
    conn.commit()
    log_run(conn, "migrate", detail=f"normalize_version={NORMALIZE_VERSION} {report}"[:900],
            rows_in=report.employers_before, rows_new=report.employers_after)
    return report


def rederive(conn: sqlite3.Connection, *, now: str | None = None) -> Report:
    stamp = now or now_iso()
    report = Report()
    old_rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employers")}
    report.employers_before = len(old_rows)
    prov = {eid: row["province"] for eid, row in old_rows.items()}

    norms: dict[str, str] = {}

    def norm(raw: str | None) -> str:
        key = raw or ""
        if key not in norms:
            norms[key] = norm_name(key)
        return norms[key]

    def new_id(raw: str | None, old: str) -> str:
        return employer_id(norm(raw), prov.get(old))

    targets: dict[str, Counter] = defaultdict(Counter)   # old id -> new id -> records sent there
    members: dict[str, set[str]] = defaultdict(set)      # new id -> old ids that sent records
    identity: dict[str, tuple[str, str | None]] = {}     # new id -> (norm_name, province)
    first_raw: dict[str, str] = {}                       # new id -> a raw name that maps to it

    def send(old: str, nid: str, count: int, norm_value: str, province: str | None, raw: str) -> None:
        targets[old][nid] += count
        members[nid].add(old)
        identity.setdefault(nid, (norm_value, province))
        first_raw.setdefault(nid, raw)

    postings: list[tuple[int, str]] = []
    for r in conn.execute("SELECT posting_id, employer_id, employer_raw FROM jobbank_postings"):
        nid = new_id(r["employer_raw"], r["employer_id"])
        send(r["employer_id"], nid, 1, norm(r["employer_raw"]), prov.get(r["employer_id"]), r["employer_raw"])
        if nid != r["employer_id"]:
            postings.append((r["posting_id"], nid))

    esdc: list[tuple[str, str, str]] = []
    for r in conn.execute(
        "SELECT employer_id, employer_raw, COUNT(*) AS n FROM esdc_records GROUP BY employer_id, employer_raw"
    ):
        nid = new_id(r["employer_raw"], r["employer_id"])
        send(r["employer_id"], nid, r["n"], norm(r["employer_raw"]), prov.get(r["employer_id"]), r["employer_raw"])
        if nid != r["employer_id"]:
            esdc.append((r["employer_id"], r["employer_raw"], nid))

    # Findings are linked the way the IRCC stage links a new one, against the
    # employers that hold records; failing that, they get an employer of their own.
    known = set(members)
    created: dict[str, str] = {}
    findings: list[tuple[int, str]] = []
    for r in conn.execute(
        "SELECT id, employer_id, operating_name, legal_name, address FROM findings "
        "WHERE employer_id IS NOT NULL ORDER BY id"
    ):
        old = r["employer_id"]
        _, province, _ = parse_address(r["address"])
        nid = next((c for c in ircc.candidate_ids(r["operating_name"], r["legal_name"], province) if c in known), None)
        name = ircc.creation_name(r["operating_name"], r["legal_name"])
        if nid is None and name and norm(name):
            nid = employer_id(norm(name), province)
            created.setdefault(nid, name)
        if nid is None:
            # Nothing to link by: the finding stays with the employer it has.
            nid, name, province = old, (old_rows.get(old) or {}).get("display_name") or "", prov.get(old)
            identity.setdefault(nid, ((old_rows.get(old) or {}).get("norm_name") or "", province))
        known.add(nid)
        send(old, nid, 1, norm(name), province, name or "")
        if nid != old:
            findings.append((r["id"], nid))
    report.findings_relinked = len(findings)

    primary: dict[str, str] = {}
    for old, row in old_rows.items():
        sent = targets.get(old)
        if not sent:
            report.dropped += 1
            continue
        if len(sent) > 1:
            report.split += 1
        own = new_id(row["display_name"], old)
        primary[old] = own if own in sent else max(sorted(sent), key=lambda n: sent[n])
    report.ids_changed = sum(1 for old in old_rows if old not in known)
    groups = [olds for olds in members.values() if len(olds) > 1]
    report.merge_groups = len(groups)
    report.merged = sum(len(olds) for olds in groups)

    new_rows = {nid: _merged_row(nid, members[nid], old_rows, identity[nid], created.get(nid),
                                 first_raw.get(nid), new_id, stamp) for nid in known}

    names: set[tuple[str, str, str]] = set()
    for r in conn.execute("SELECT employer_id, raw_name, source FROM employer_names"):
        old = r["employer_id"]
        nid = new_id(r["raw_name"], old)
        if nid not in targets.get(old, ()):
            nid = primary.get(old)
            if nid is None:
                continue
        names.add((nid, r["raw_name"], r["source"]))
        operating = split_trade_name(r["raw_name"])[1]
        if operating:
            names.add((nid, operating, r["source"]))

    matches: dict[tuple[str, str, str], dict] = {}
    for r in conn.execute("SELECT * FROM registry_matches"):
        nid = primary.get(r["employer_id"])
        if r["registry"] in BULK_REGISTRIES or nid is None:
            continue
        row = dict(r)
        row["employer_id"] = nid
        if r["registry"] == registry_bc.REGISTRY and r["legal_name"]:
            row["grade"] = registry_bc.grade(identity[nid][0], r["legal_name"])
        key = (nid, r["registry"], r["registry_id"])
        if key not in matches or (row["checked_at"] or "") > (matches[key]["checked_at"] or ""):
            matches[key] = row

    changed = {old: primary.get(old) for old in old_rows if primary.get(old) != old}
    _write(conn, old_rows, new_rows, postings, esdc, findings, names, matches, changed, stamp)
    report.employers_after = len(new_rows)

    for module in BULK_REGISTRIES.values():
        report.registry_renormalized += module.renormalize(conn)
        module.match(conn, now=stamp)
    report.names_added, report.streets_added = ircc.enrich_employers(conn, now=stamp)
    status.recompute(conn, now=stamp)
    log.info("migration: %s", report)
    return report


def _merged_row(nid: str, olds: set[str], old_rows: dict[str, dict], ident: tuple[str, str | None],
                created_name: str | None, raw: str | None, new_id, stamp: str) -> dict:
    """The employer row for a new id, from the old rows whose records went there."""
    order = sorted(
        (o for o in olds if o in old_rows),
        key=lambda o: (o != nid, -_sortable(old_rows[o]["last_seen"]), o),
    )
    if not order:
        base: dict = {"id": nid, "current_status": "none", "pending_count": 0, "approved_lmias": 0,
                      "approved_positions": 0, "refused_lmias": 0, "refused_positions": 0,
                      "finding_count": 0, "indicator_count": 0, "registry_grade": "none"}
    else:
        base = dict(old_rows[order[0]])
    row = dict(base)
    row["id"] = nid
    row["norm_name"], row["province"] = ident
    if created_name:
        row["display_name"] = created_name
    elif not order or new_id(base.get("display_name"), order[0]) != nid:
        row["display_name"] = raw or base.get("display_name") or ""
    for field in ("city", "postal_code"):
        row[field] = next((old_rows[o][field] for o in order if old_rows[o][field]), None)
    with_street = next((o for o in order if old_rows[o]["street"]), None)
    row["street"] = old_rows[with_street]["street"] if with_street else None
    if "street_source" in row:
        row["street_source"] = old_rows[with_street].get("street_source") if with_street else None
    firsts = [old_rows[o]["first_seen"] for o in order if old_rows[o]["first_seen"]]
    lasts = [old_rows[o]["last_seen"] for o in order if old_rows[o]["last_seen"]]
    row["first_seen"] = min(firsts) if firsts else None
    row["last_seen"] = max(lasts) if lasts else None
    previous = old_rows.get(nid)
    unchanged = previous is not None and set(order) == {nid} and all(
        previous.get(k) == v for k, v in row.items() if k != "updated_at")
    row["updated_at"] = previous["updated_at"] if unchanged else stamp
    return row


def _sortable(date_text: str | None) -> int:
    digits = "".join(ch for ch in (date_text or "") if ch.isdigit())[:8]
    return int(digits) if digits else 0


def _write(conn: sqlite3.Connection, old_rows: dict[str, dict], new_rows: dict[str, dict],
           postings: list[tuple[int, str]], esdc: list[tuple[str, str, str]], findings: list[tuple[int, str]],
           names: set[tuple[str, str, str]], matches: dict[tuple[str, str, str], dict],
           changed: dict[str, str | None], stamp: str) -> None:
    """Apply the new identities in one transaction, parents before children."""
    columns = [r["name"] for r in conn.execute("PRAGMA table_info(employers)")]
    marks = ", ".join("?" * len(columns))
    sets = ", ".join(f"{c} = ?" for c in columns if c != "id")
    conn.commit()
    try:
        conn.execute("BEGIN")
        inserts = [tuple(row.get(c) for c in columns) for nid, row in new_rows.items() if nid not in old_rows]
        conn.executemany(f"INSERT INTO employers ({', '.join(columns)}) VALUES ({marks})", inserts)
        updates = [
            tuple(row.get(c) for c in columns if c != "id") + (nid,)
            for nid, row in new_rows.items()
            if nid in old_rows and any(old_rows[nid].get(c) != row.get(c) for c in columns)
        ]
        conn.executemany(f"UPDATE employers SET {sets} WHERE id = ?", updates)

        conn.executemany("UPDATE jobbank_postings SET employer_id = ? WHERE posting_id = ?",
                         [(nid, pid) for pid, nid in postings])
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS esdc_map (old TEXT, raw TEXT, new TEXT, PRIMARY KEY (old, raw))")
        conn.execute("DELETE FROM esdc_map")
        conn.executemany("INSERT INTO esdc_map (old, raw, new) VALUES (?, ?, ?)", esdc)
        # One statement, so every row is read against the old ids.
        conn.execute(
            """
            UPDATE esdc_records SET employer_id = (
              SELECT m.new FROM esdc_map m WHERE m.old = esdc_records.employer_id AND m.raw = esdc_records.employer_raw)
            WHERE EXISTS (
              SELECT 1 FROM esdc_map m WHERE m.old = esdc_records.employer_id AND m.raw = esdc_records.employer_raw)
            """
        )
        conn.executemany("UPDATE findings SET employer_id = ? WHERE id = ?", [(nid, fid) for fid, nid in findings])

        conn.execute("DELETE FROM employer_names")
        conn.executemany("INSERT INTO employer_names (employer_id, raw_name, source) VALUES (?, ?, ?)", sorted(names))

        conn.execute("DELETE FROM registry_matches")
        if matches:
            match_cols = list(next(iter(matches.values())).keys())
            conn.executemany(
                f"INSERT INTO registry_matches ({', '.join(match_cols)}) VALUES ({', '.join('?' * len(match_cols))})",
                [tuple(m[c] for c in match_cols) for m in matches.values()],
            )

        conn.execute("CREATE TEMP TABLE IF NOT EXISTS id_map (old TEXT PRIMARY KEY, new TEXT)")
        conn.execute("DELETE FROM id_map")
        conn.executemany("INSERT INTO id_map (old, new) VALUES (?, ?)", list(changed.items()))
        bulk = list(BULK_REGISTRIES)
        conn.execute(f"DELETE FROM registry_checks WHERE registry IN ({', '.join('?' * len(bulk))})", bulk)
        conn.execute("DELETE FROM registry_checks WHERE employer_id IN (SELECT old FROM id_map)")
        # Indicators move to the main new id; where that id kept its own rows,
        # those win. indicators.compute rewrites them all on the next pass.
        conn.execute("DROP TABLE IF EXISTS temp.moved_indicators")
        conn.execute(
            """
            CREATE TEMP TABLE moved_indicators AS
            SELECT m.new AS employer_id, i.indicator, i.state, i.basis, i.rule_version, i.computed_at
            FROM indicators i JOIN id_map m ON m.old = i.employer_id WHERE m.new IS NOT NULL
            """
        )
        conn.execute("DELETE FROM indicators WHERE employer_id IN (SELECT old FROM id_map)")
        conn.execute(
            "INSERT OR IGNORE INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
            "SELECT employer_id, indicator, state, basis, rule_version, computed_at FROM moved_indicators"
        )

        gone = [(old,) for old in old_rows if old not in new_rows]
        conn.executemany("DELETE FROM employers WHERE id = ?", gone)
        # Retired ids point at the id that took their records; older aliases follow along.
        conn.execute(
            "UPDATE employer_aliases SET new_id = (SELECT m.new FROM id_map m WHERE m.old = employer_aliases.new_id) "
            "WHERE new_id IN (SELECT old FROM id_map WHERE new IS NOT NULL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO employer_aliases (old_id, new_id, normalize_version, created_at) VALUES (?, ?, ?, ?)",
            [(old, new, NORMALIZE_VERSION, stamp) for old, new in changed.items() if new and old not in new_rows],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
