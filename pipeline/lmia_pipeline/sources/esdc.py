"""ESDC quarterly lists of employers with positive and negative LMIAs.

Resources are discovered through the CKAN API so a new quarter loads itself.
File shapes changed over the years: CSV with varying headers up to 2020 Q3,
XLSX with a title row and footnotes from 2020 Q4 on. Headers are matched by
keyword rather than exact text, and the file type comes from the URL because
the CKAN format field is wrong on some rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import sqlite3

import openpyxl

from .. import config
from ..db import log_run, now_iso, upsert_employer
from ..http import FetchError, PoliteClient
from ..normalize import iso_date, parse_address, parse_noc, period_from_text, province_code, to_int

log = logging.getLogger(__name__)

# Order matters: a header such as "Approved LMIA Positions" must land on
# positions, so positions is tested before lmias.
HEADER_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("province", ("province", "territor")),
    ("stream", ("stream",)),
    ("employer", ("employer", "employeur")),
    ("address", ("address", "adresse")),
    ("occupation", ("occupation", "noc", "cnp", "profession")),
    ("incorporate", ("incorporat",)),
    ("positions", ("position", "poste")),
    ("lmias", ("lmia", "eimt")),
]


def map_headers(headers: list[object]) -> dict[str, int]:
    out: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        if raw is None:
            continue
        key = str(raw).strip().lower()
        if not key:
            continue
        for field, words in HEADER_KEYWORDS:
            if field in out:
                continue
            if any(w in key for w in words):
                out[field] = idx
                break
    return out


def is_header_row(row: list[object]) -> bool:
    fields = map_headers(row)
    return "employer" in fields and ("occupation" in fields or "positions" in fields)


def _rows_from_iter(rows: list[list[object]]) -> tuple[list[object], list[list[object]]]:
    for i, row in enumerate(rows):
        if is_header_row(row):
            data = [r for r in rows[i + 1:] if any(v not in (None, "") for v in r)]
            return list(row), data
    raise ValueError("no header row found")


def parse_xlsx(data: bytes) -> tuple[list[object], list[list[object]]]:
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return _rows_from_iter(rows)


def decode_csv_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_csv(data: bytes) -> tuple[list[object], list[list[object]]]:
    text = decode_csv_bytes(data)
    # Some files end lines with \r\r\n; collapse every variant to \n first.
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    rows = [list(r) for r in csv.reader(io.StringIO(text))]
    return _rows_from_iter(rows)


def parse_resource(data: bytes, ext: str) -> tuple[list[object], list[list[object]]]:
    if ext in ("xlsx", "xls", "xlsm"):
        try:
            return parse_xlsx(data)
        except Exception as exc:  # some .xls URLs serve CSV text
            if data[:2] == b"PK":
                raise
            log.info("falling back to csv parser: %s", exc)
    return parse_csv(data)


def normalize_row(fields: dict[str, int], row: list[object]) -> dict | None:
    def get(key: str) -> str | None:
        idx = fields.get(key)
        if idx is None or idx >= len(row):
            return None
        value = row[idx]
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    employer = get("employer")
    if not employer:
        return None
    province_raw = get("province")
    address = get("address")
    city, prov_from_addr, postal = parse_address(address)
    province = province_code(province_raw) or prov_from_addr
    noc_code, noc_title = parse_noc(get("occupation"))
    return {
        "employer_raw": employer,
        "province": province,
        "province_raw": province_raw,
        "stream": get("stream"),
        "address_raw": address,
        "city": city,
        "postal_code": postal,
        "noc_code": noc_code,
        "noc_title": noc_title,
        "incorporate_status": get("incorporate"),
        "lmias": to_int(get("lmias")),
        "positions": to_int(get("positions")),
    }


def row_hash(list_name: str, resource_id: str, row: list[object]) -> str:
    payload = json.dumps(["" if v is None else str(v) for v in row], ensure_ascii=False)
    return hashlib.sha1(f"{list_name}|{resource_id}|{payload}".encode("utf-8")).hexdigest()


def english_resources(package: dict) -> list[dict]:
    resources = package.get("result", {}).get("resources", [])
    out = [r for r in resources if "en" in (r.get("language") or [])]
    out.sort(key=lambda r: (r.get("created") or "", r.get("name") or ""))
    return out


def resource_period(res: dict) -> str | None:
    return period_from_text(res.get("name") or "") or period_from_text(res.get("url") or "")


class DuplicateFile(Exception):
    """A resource whose file is byte for byte one published earlier under another resource."""


def _earlier_twin(conn: sqlite3.Connection, res: dict, sha: str) -> sqlite3.Row | None:
    """The loaded resource with the same file that was published first, when that is not this one."""
    mine = (iso_date(res.get("created")) or "9999-12-31", res["id"])
    for row in conn.execute(
        "SELECT resource_id, period, published FROM esdc_resources WHERE sha256 = ? AND resource_id != ?",
        (sha, res["id"]),
    ):
        if (row["published"] or "9999-12-31", row["resource_id"]) < mine:
            return row
    return None


def load_resource(
    conn: sqlite3.Connection,
    list_name: str,
    res: dict,
    data: bytes,
    *,
    now: str | None = None,
) -> int:
    """Parse one resource file into esdc_records. Returns rows inserted."""
    stamp = now or now_iso()
    url = res["url"]
    ext = url.lower().rsplit(".", 1)[-1]
    period = resource_period(res) or "unknown"
    sha = hashlib.sha256(data).hexdigest()
    twin = _earlier_twin(conn, res, sha)
    if twin is not None:
        # The same bytes were published earlier under another resource: a
        # second copy, not a second quarter. Loading it would count every row
        # twice and date the copy to the later period, so its rows are kept
        # out (and removed if an earlier run loaded them).
        conn.execute("DELETE FROM esdc_records WHERE resource_id = ?", (res["id"],))
        conn.execute("DELETE FROM esdc_resources WHERE resource_id = ?", (res["id"],))
        conn.commit()
        raise DuplicateFile(f"same file as {twin['period']} (resource {twin['resource_id']})")
    existing = conn.execute(
        "SELECT sha256 FROM esdc_resources WHERE resource_id = ?", (res["id"],)
    ).fetchone()
    if existing and existing["sha256"] == sha:
        return 0
    if existing:
        # ESDC revises files in place; reload the resource from scratch.
        conn.execute("DELETE FROM esdc_records WHERE resource_id = ?", (res["id"],))

    headers, rows = parse_resource(data, ext)
    fields = map_headers(headers)
    inserted = 0
    section_province: str | None = None
    for row in rows:
        # The 2014 file repeats its header under each province and names the
        # province on a line of its own instead of in a column.
        if is_header_row(row):
            continue
        non_empty = [v for v in row if v not in (None, "")]
        if len(non_empty) == 1:
            code = province_code(str(non_empty[0]))
            if code:
                section_province = code
                continue
        rec = normalize_row(fields, row)
        if rec is None:
            continue
        if rec["province"] is None:
            rec["province"] = section_province
        h = row_hash(list_name, res["id"], row)
        if conn.execute("SELECT 1 FROM esdc_records WHERE row_hash = ?", (h,)).fetchone():
            continue
        eid = upsert_employer(
            conn, rec["employer_raw"], rec["province"], source=f"esdc_{list_name}",
            city=rec["city"], postal_code=rec["postal_code"], now=stamp,
        )
        conn.execute(
            """
            INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, province_raw,
              stream, address_raw, city, postal_code, noc_code, noc_title, incorporate_status,
              lmias, positions, resource_id, row_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                list_name, period, eid, rec["employer_raw"], rec["province"], rec["province_raw"],
                rec["stream"], rec["address_raw"], rec["city"], rec["postal_code"], rec["noc_code"],
                rec["noc_title"], rec["incorporate_status"], rec["lmias"], rec["positions"],
                res["id"], h,
            ),
        )
        inserted += 1
    conn.execute(
        """
        INSERT INTO esdc_resources (resource_id, dataset, period, name, url, published, sha256, bytes,
          rows_loaded, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(resource_id) DO UPDATE SET
          period = excluded.period, name = excluded.name, url = excluded.url,
          published = excluded.published, sha256 = excluded.sha256, bytes = excluded.bytes,
          rows_loaded = excluded.rows_loaded, loaded_at = excluded.loaded_at
        """,
        (
            res["id"], list_name, period, res.get("name") or "", url,
            iso_date(res.get("created")), sha, len(data), inserted, stamp,
        ),
    )
    conn.commit()
    return inserted


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None) -> dict[str, int]:
    stamp = now or now_iso()
    totals: dict[str, int] = {}
    failures: list[str] = []
    duplicates: list[str] = []
    for list_name, dataset_id in config.ESDC_DATASETS.items():
        listing = config.CKAN_PACKAGE_SHOW.format(dataset=dataset_id)
        # A portal outage, or a maintenance page served with HTTP 200, costs
        # this list one night: the quarters already loaded stay as they are.
        try:
            package = client.get_json(listing, cache=True, max_age_s=0)
            resources = english_resources(package)
        except (FetchError, ValueError, AttributeError) as exc:
            client.forget(listing)
            failures.append(f"{list_name} listing: {exc}"[:300])
            totals[list_name] = 0
            continue
        if not resources:
            failures.append(f"{list_name} listing: no English resources")
        loaded = 0
        for res in resources:
            url = res.get("url") or ""
            ext = url.lower().rsplit(".", 1)[-1]
            if ext not in ("csv", "xlsx", "xls", "xlsm"):
                log.info("skip %s (%s)", res.get("name"), ext)
                continue
            try:
                data = client.get(url, cache=True, max_age_s=7 * 86400)
            except FetchError as exc:
                failures.append(f"{res.get('name')}: {exc}")
                continue
            try:
                n = load_resource(conn, list_name, res, data, now=stamp)
            except DuplicateFile as exc:
                # An upstream copy, noted rather than failed: it would otherwise
                # raise an alert every night for a file nobody here can fix.
                duplicates.append(f"{resource_period(res) or res.get('id')} {list_name}: {exc}")
                log.warning("resource %s skipped: %s", res.get("name"), exc)
                continue
            except Exception as exc:  # keep loading the other quarters
                conn.rollback()
                # Fetch it again next time; the file may be fixed upstream.
                client.forget(url)
                failures.append(f"{res.get('name')}: {exc}")
                log.warning("resource %s failed: %s", res.get("name"), exc)
                continue
            loaded += n
            if n:
                log.info("%s %s: %d rows", list_name, resource_period(res), n)
        totals[list_name] = loaded
    detail = f"positive={totals.get('positive', 0)} negative={totals.get('negative', 0)}"
    if duplicates:
        detail += " duplicates=" + "; ".join(duplicates)[:400]
    if failures:
        detail += " failures=" + "; ".join(failures)[:900]
    log_run(conn, "esdc", detail=detail, rows_new=sum(totals.values()), ok=not failures)
    return totals
