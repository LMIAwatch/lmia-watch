"""Quebec enterprise register: the Registraire des entreprises' open-data extract.

Source: Registraire des entreprises du Québec, « Registre des entreprises »,
Données Québec (https://www.donneesquebec.ca/recherche/dataset/registre-des-entreprises),
licence CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/).
One ZIP (JeuDonnees.zip, 269 MB, about 990 MB unzipped, 2026-10-16) refreshed
twice a month. Two of its CSV files are read: Entreprise.csv (NEQ, status,
legal form, registration date, domicile address) and Nom.csv (every name an
enterprise has used, with its type: the legal name, its other-language
version, and other names it operates under).

Loaded at most once a week (meta quebec_extract_loaded_at). Only names that
normalize like a Quebec employer's name are kept, so the table holds a few
tens of thousands of rows instead of the 2.9 million enterprises, and the
database the nightly run carries to and from storage stays small; an employer
first seen after a load is matched at the next one. Kept: the current names of
registered enterprises, and the names in force on the day an enterprise was
struck off, when that was on or after STRUCK_OFF_SINCE (the lists start in
2014). Skipped entirely: sole proprietorships (legal form IND), whose name can
be a person's name; the publisher's terms make it an offence to identify a
natural person from the data, and this project stores no private individuals.

Matching mirrors registry_federal: Quebec employers only, on the normalized
name. Exact when the name is the enterprise's legal name and its domicile
postal code or province agrees with the employer's; probable when only the
name agrees or the name is one the enterprise operates under.
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
import zipfile

from ..db import get_meta, hours_since, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient
from ..normalize import POSTAL_RE, format_postal, norm_name

log = logging.getLogger(__name__)

REGISTRY = "quebec_req"
URL = ("https://www.registreentreprises.gouv.qc.ca/RQAnonymeGR/GR/GR03/"
       "GR03A2_22A_PIU_RecupDonnPub_PC/FichierDonneesOuvertes.aspx")
DATASET_URL = "https://www.donneesquebec.ca/recherche/dataset/registre-des-entreprises"
LOADED_KEY = "quebec_extract_loaded_at"
MAX_AGE_HOURS = 7 * 24
CHUNK = 5000
STRUCK_OFF_SINCE = "2012-01-01"
SKIP_FORMS = {"IND"}
STATUS = {"IM": "Active", "RO": "Struck off", "RX": "Struck off", "RD": "Struck off"}
STATUS_RANK = {"Active": 0, "Struck off": 1}
LEGAL_TYPES = {"N", "M"}   # N a worded name, M a numbered one ("9000-0084 QUÉBEC INC.")
OTHER_TYPES = {"A"}        # another name the enterprise operates under
# First letter of a postal code -> province, for the domicile address.
POSTAL_PROVINCE = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC", "K": "ON", "L": "ON",
    "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB", "V": "BC", "X": "NT", "Y": "YT",
}


def _rows(zf: zipfile.ZipFile, member: str):
    with zf.open(member) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""))


def _postal(*lines: str | None) -> str | None:
    for line in lines:
        m = POSTAL_RE.search(line or "")
        if m:
            return format_postal(m.group(1), m.group(2))
    return None


def _name_rows(rec: dict) -> list[str]:
    return [n for n in ((rec.get("NOM_ASSUJ") or "").strip(), (rec.get("NOM_ASSUJ_LANG_ETRNG") or "").strip()) if n]


def parse_extract(data: bytes, wanted: set[str] | None = None) -> list[tuple]:
    """Rows for quebec_enterprises from the ZIP's bytes, limited to names in `wanted` when given.

    Three passes keep memory small: the names that could match, then the
    enterprises behind them, then those enterprises' legal names.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    # Pass 1: names in force now, or that ended on or after the cut-off.
    candidates: list[tuple[str, str, str, str, str]] = []   # neq, name, norm, kind, end date
    for rec in _rows(zf, "Nom.csv"):
        kind = (rec.get("TYP_NOM_ASSUJ") or "").strip()
        state = (rec.get("STAT_NOM") or "").strip()
        end = (rec.get("DAT_FIN_NOM_ASSUJ") or "")[:10]
        if kind not in LEGAL_TYPES and kind not in OTHER_TYPES:
            continue
        if state != "V" and not (state == "A" and end >= STRUCK_OFF_SINCE):
            continue
        for name in _name_rows(rec):
            norm = norm_name(name)
            if norm and (wanted is None or norm in wanted):
                candidates.append(((rec.get("NEQ") or "").strip(), name, norm, kind, "" if state == "V" else end))
    neqs = {c[0] for c in candidates}

    # Pass 2: status, form, dates and domicile of those enterprises.
    enterprises: dict[str, tuple] = {}
    for rec in _rows(zf, "Entreprise.csv"):
        neq = (rec.get("NEQ") or "").strip()
        if neq not in neqs:
            continue
        status = STATUS.get((rec.get("COD_STAT_IMMAT") or "").strip())
        form = (rec.get("COD_FORME_JURI") or "").strip()
        struck_on = (rec.get("DAT_STAT_IMMAT") or "")[:10]
        if status is None or form in SKIP_FORMS or (status != "Active" and struck_on < STRUCK_OFF_SINCE):
            continue
        postal = _postal(*(rec.get(f"ADR_DOMCL_LIGN{i}_ADR") for i in (4, 3, 2, 1)))
        enterprises[neq] = (status, form or None, (rec.get("DAT_IMMAT") or "")[:10] or None, postal,
                            POSTAL_PROVINCE.get(postal[0]) if postal else None,
                            "" if status == "Active" else struck_on)

    def in_force(neq: str, end: str) -> bool:
        # A registered enterprise's names in force now; a struck-off one's on that day.
        struck_on = enterprises[neq][5]
        return end == "" or (bool(struck_on) and end == struck_on)

    # Pass 3: each kept enterprise's legal name, by the same rule.
    legal: dict[str, str] = {}
    for rec in _rows(zf, "Nom.csv"):
        neq = (rec.get("NEQ") or "").strip()
        if neq not in enterprises or neq in legal or (rec.get("TYP_NOM_ASSUJ") or "").strip() not in LEGAL_TYPES:
            continue
        state = (rec.get("STAT_NOM") or "").strip()
        end = "" if state == "V" else (rec.get("DAT_FIN_NOM_ASSUJ") or "")[:10]
        names = _name_rows(rec)
        if names and in_force(neq, end):
            legal[neq] = names[0]

    out: list[tuple] = []
    seen: set[tuple[str, str]] = set()
    for neq, name, norm, kind, end in candidates:
        if neq not in enterprises or not in_force(neq, end) or (neq, norm) in seen:
            continue
        seen.add((neq, norm))
        status, form, registered_on, postal, province, _ = enterprises[neq]
        label = "legal" if kind in LEGAL_TYPES else "other"
        out.append((neq, name, norm, label, legal.get(neq, name), status, form, registered_on, postal, province))
    return out


def load_extract(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
                 force: bool = False) -> int | None:
    """Download and load the register once a week; returns names loaded, None when skipped."""
    stamp = now or now_iso()
    age = hours_since(conn, LOADED_KEY, now=stamp)
    if not force and age is not None and age < MAX_AGE_HOURS:
        return None
    try:
        data = client.get(URL, timeout=900)
    except FetchError as exc:
        log.warning("quebec register: %s", exc)
        return None
    wanted = {r[0] for r in conn.execute("SELECT DISTINCT norm_name FROM employers WHERE province = 'QC' "
                                         "AND norm_name != ''")}
    rows = parse_extract(data, wanted)
    conn.execute("DELETE FROM quebec_enterprises")
    for i in range(0, len(rows), CHUNK):
        conn.executemany(
            "INSERT OR REPLACE INTO quebec_enterprises (neq, name, norm_name, name_kind, legal_name, status, form, "
            "registered_on, postal_code, province) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows[i:i + CHUNK],
        )
    # Every Quebec employer was just looked up against the whole register.
    conn.execute(
        "INSERT INTO registry_checks (employer_id, registry, checked_at) "
        "SELECT id, ?, ? FROM employers WHERE province = 'QC' "
        "ON CONFLICT(employer_id, registry) DO UPDATE SET checked_at = excluded.checked_at",
        (REGISTRY, stamp),
    )
    set_meta(conn, LOADED_KEY, stamp)
    conn.commit()
    log.info("quebec register: %d names kept for %d employer names", len(rows), len(wanted))
    return len(rows)


def renormalize(conn: sqlite3.Connection) -> int:
    """The kept names were chosen under the old normalization: drop them and load again next run."""
    n = conn.execute("SELECT COUNT(*) FROM quebec_enterprises").fetchone()[0]
    conn.execute("DELETE FROM quebec_enterprises")
    conn.execute("DELETE FROM meta WHERE key = ?", (LOADED_KEY,))
    conn.commit()
    return n


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Join Quebec employers to the kept names on the normalized name; keep the best per employer."""
    stamp = now or now_iso()
    if get_meta(conn, LOADED_KEY) is None:
        return 0
    best: dict[str, tuple] = {}
    for r in conn.execute(
        """
        SELECT e.id AS employer_id, e.postal_code AS e_postal, q.neq, q.name_kind, q.legal_name, q.status, q.form,
               q.registered_on, q.postal_code AS q_postal, q.province AS q_prov
        FROM employers e JOIN quebec_enterprises q ON q.norm_name = e.norm_name
        WHERE e.province = 'QC' AND e.norm_name != ''
        """
    ):
        place = (r["e_postal"] and r["e_postal"] == r["q_postal"]) or r["q_prov"] == "QC"
        grade = "exact" if r["name_kind"] == "legal" and place else "probable"
        rank = (0 if grade == "exact" else 1, STATUS_RANK.get(r["status"] or "", 2),
                -(int((r["registered_on"] or "0")[:4]) or 0), r["neq"])
        current = best.get(r["employer_id"])
        if current is None or rank < current[0]:
            best[r["employer_id"]] = (rank, r["neq"], r["legal_name"], r["form"], r["status"], r["registered_on"], grade)
    conn.executemany(
        """
        INSERT INTO registry_matches (employer_id, registry, registry_id, legal_name, entity_type, status,
          registered_on, grade, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(employer_id, registry, registry_id) DO UPDATE SET
          legal_name = excluded.legal_name, entity_type = excluded.entity_type, status = excluded.status,
          registered_on = excluded.registered_on, grade = excluded.grade, checked_at = excluded.checked_at
        """,
        [(eid, REGISTRY, v[1], v[2], v[3], v[4], v[5], v[6], stamp) for eid, v in best.items()],
    )
    conn.commit()
    return len(best)


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> int:
    loaded = load_extract(conn, client, now=now)
    total = conn.execute("SELECT COUNT(*) FROM quebec_enterprises").fetchone()[0]
    matched = match(conn, now=now)
    log_run(conn, "registry_quebec",
            detail=f"names={total} loaded_now={'skipped' if loaded is None else loaded} matched={matched}",
            rows_in=total, rows_new=matched)
    return matched
