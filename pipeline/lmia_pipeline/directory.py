"""The employer directory and related employers: an inbound link to every profile.

Why: a profile's only links were its sitemap entry and, for a few hundred
employers, a place page's list of recent records, so search engines had
crawled a few thousand of the 160,000 profiles. The nightly export now writes
two kinds of link to them:

- the directory: for each province and territory with a page at /places/<pp>,
  an A to Z list of every employer with a profile there, PAGE_SIZE to a page,
  at /places/<pp>/employers (page 1) and /places/<pp>/employers/<n>.
  Employers with a head office outside Canada (province XX) or with no
  province share one more, /places/other/employers. The province is the
  employer's own (employers.province), the one its id was made with.
- related employers on each profile (related()): up to RELATED_MAX other
  employers, first those in the same city (province and city folded as the
  place pages fold it), then those in the same province whose most common
  occupation code is the same. Within each group the picks are the employers
  nearest in record count, alternately one with more records and one with
  fewer. Taking the busiest employers of a city instead would send every
  profile's links to the same few: on the database of 2026-10-17 that linked
  21,370 of 168,440 profiles (one received 10,892 links), against 165,593
  (at most 14 each) for the nearest.

Output tree (under data/out/static):
  directory/index.json        every directory: code, employer count, page count, the date it last changed
  directory/<pp>/index.json   one directory: its counts, each page's first and last name, and the page
                              on which each initial starts
  directory/<pp>/<n>.json     page n (from 1): rows of id, name, city and record count

A row's record count is what the profile lists: its Job Bank postings plus its
ESDC list rows (the two lists write_profiles exports, counted the same way).
Rows sort by the normalized name (employers.norm_name, from which the id is
made, so it does not change night to night), then the id, so a page's rows
move only when an employer is added or leaves, and a page file holds only its
rows, so the totals changing does not rewrite every page.

Lastmod: the table directory_pages keeps each page's hash and the data date
on which it last changed; the sitemap lists every page with that date. A
province with no employers gets an index with no pages and no sitemap entry.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .db import today_iso
from .places import PROVINCES, slugify

PAGE_SIZE = 200
RELATED_MAX = 5
# The directory of employers with a head office outside Canada or no province.
OTHER = "other"
CODES = [p.lower() for p in PROVINCES] + [OTHER]
NOC_RE = re.compile(r"^\d{4,5}$")


def code_for(province: str | None) -> str:
    """The directory an employer's province puts it in."""
    return province.lower() if province in PROVINCES else OTHER


def page_path(code: str, page: int) -> str:
    return f"/places/{code}/employers" if page == 1 else f"/places/{code}/employers/{page}"


def initial(norm: str) -> str:
    """The letter a name files under, '#' for a digit or anything else."""
    first = norm[:1]
    return first.upper() if "a" <= first <= "z" else "#"


class Model:
    """Every employer with its directory, record count and most common occupation code, built once per export."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.employers: dict[str, sqlite3.Row] = {
            r["id"]: r for r in conn.execute("SELECT id, display_name, norm_name, province, city FROM employers")}
        self.records: Counter = Counter()
        for table in ("esdc_records", "jobbank_postings"):
            for eid, n in conn.execute(f"SELECT employer_id, COUNT(*) FROM {table} GROUP BY employer_id"):
                self.records[eid] += n
        codes: dict[str, Counter] = defaultdict(Counter)
        for table in ("esdc_records", "jobbank_postings"):
            for eid, noc, n in conn.execute(
                    f"SELECT employer_id, noc_code, COUNT(*) FROM {table} WHERE noc_code IS NOT NULL GROUP BY employer_id, noc_code"):
                if NOC_RE.match(noc.strip()):
                    codes[eid][noc.strip()] += n
        # Ties go to a NOC 2021 code (five digits, the newer classification),
        # then to the lower code, so the choice does not change between runs.
        self.noc: dict[str, str] = {
            eid: min(c.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0] for eid, c in codes.items()}

    def order(self, eid: str) -> tuple[str, str]:
        return (self.employers[eid]["norm_name"] or "", eid)

    def rank(self, eid: str) -> tuple[int, str, str]:
        """Most records first, then the directory's order."""
        return (-self.records[eid], *self.order(eid))


# -- the directory ---------------------------------------------------------------


def pages(m: Model) -> dict[str, list[list[dict]]]:
    """Each directory's pages of rows, for every code (an empty list where it has no employer)."""
    members: dict[str, list[str]] = {code: [] for code in CODES}
    for eid, e in m.employers.items():
        members[code_for(e["province"])].append(eid)
    out: dict[str, list[list[dict]]] = {}
    for code, ids in members.items():
        ids.sort(key=m.order)
        rows = []
        for eid in ids:
            e = m.employers[eid]
            row = {"id": eid, "name": e["display_name"], "city": e["city"], "records": m.records[eid]}
            # The other directory mixes head offices outside Canada with
            # employers whose records give no province; the row says which.
            if code == OTHER:
                row["prov"] = e["province"]
            rows.append(row)
        out[code] = [rows[i:i + PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
    return out


def page_hash(rows: list[dict]) -> str:
    text = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _dump(path: Path, obj: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def _record(conn: sqlite3.Connection, written: dict[str, tuple[str, int, str]], today: str) -> dict[str, str]:
    """Bring the ledger in line with tonight's pages; returns each path's changed_on."""
    held = {r["path"]: (r["hash"], r["changed_on"]) for r in conn.execute("SELECT path, hash, changed_on FROM directory_pages")}
    dates: dict[str, str] = {}
    for path, (code, page, digest) in written.items():
        old = held.get(path)
        dates[path] = old[1] if old and old[0] == digest else today
        if not old or old[0] != digest:
            conn.execute(
                "INSERT INTO directory_pages (path, code, page, hash, changed_on) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET code = excluded.code, page = excluded.page, hash = excluded.hash, "
                "changed_on = excluded.changed_on", (path, code, page, digest, today))
    gone = [(path,) for path in held if path not in written]
    conn.executemany("DELETE FROM directory_pages WHERE path = ?", gone)
    conn.commit()
    return dates


def write_all(conn: sqlite3.Connection, out: Path, data_as_of: str | None, m: Model | None = None) -> dict[str, int]:
    """Write directory/ under `out` and record each page in the ledger; returns counts for the run log."""
    m = m or Model(conn)
    today = (data_as_of or "")[:10] if re.match(r"\d{4}-\d{2}-\d{2}", data_as_of or "") else today_iso()
    by_code = pages(m)
    written: dict[str, tuple[str, int, str]] = {}
    for code, chunks in by_code.items():
        for n, rows in enumerate(chunks, start=1):
            _dump(out / "directory" / code / f"{n}.json", {"code": code, "page": n, "rows": rows})
            written[page_path(code, n)] = (code, n, page_hash(rows))
    dates = _record(conn, written, today)
    summary = []
    for code, chunks in by_code.items():
        letters: list[list] = []
        for n, rows in enumerate(chunks, start=1):
            for row in rows:
                letter = initial(m.employers[row["id"]]["norm_name"] or "")
                if not letters or all(letter != have for have, _ in letters):
                    letters.append([letter, n])
        changed = max((dates[page_path(code, n)] for n in range(1, len(chunks) + 1)), default=None)
        employers = sum(len(rows) for rows in chunks)
        _dump(out / "directory" / code / "index.json", {
            "code": code,
            "employers": employers,
            "pages": len(chunks),
            "page_size": PAGE_SIZE,
            "ranges": [[rows[0]["name"], rows[-1]["name"]] for rows in chunks],
            "letters": letters,
            "updated": changed,
        })
        summary.append({"code": code, "employers": employers, "pages": len(chunks), "updated": changed})
    _dump(out / "directory" / "index.json", {"page_size": PAGE_SIZE, "directories": summary})
    return {"directory_pages": len(written), "directory_employers": sum(s["employers"] for s in summary)}


def sitemap_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    """(path, lastmod) for every directory page the last export wrote, by directory and page."""
    order = {code: i for i, code in enumerate(CODES)}
    rows = conn.execute("SELECT path, code, page, changed_on FROM directory_pages").fetchall()
    rows = sorted(rows, key=lambda r: (order.get(r["code"], len(order)), r["code"], r["page"]))
    return [(r["path"], r["changed_on"]) for r in rows]


# -- related employers -----------------------------------------------------------


def _nearest(group: list[str], at: int, want: int, taken: set[str]) -> list[str]:
    """Up to `want` members of a ranked group nearest to position `at`, one above, then one below, skipping `taken`."""
    out: list[str] = []
    step = 1
    while len(out) < want and (at - step >= 0 or at + step < len(group)):
        for k in (at - step, at + step):
            if 0 <= k < len(group) and group[k] not in taken and len(out) < want:
                out.append(group[k])
        step += 1
    return out


def related(m: Model) -> dict[str, list[dict]]:
    """Each employer's related employers: id and name, and the city when it differs from the employer's.

    The city and occupation groups are built once, each ranked once, so an
    employer's picks are found by position, without a query per employer.
    """
    cities: dict[tuple, list[str]] = defaultdict(list)
    occupations: dict[tuple, list[str]] = defaultdict(list)
    city_key: dict[str, tuple] = {}
    for eid, e in m.employers.items():
        slug = slugify(e["city"])
        if slug:
            city_key[eid] = (e["province"], slug)
            cities[city_key[eid]].append(eid)
        if eid in m.noc:
            occupations[(e["province"], m.noc[eid])].append(eid)
    position: dict[tuple, dict[str, int]] = {}
    for groups, kind in ((cities, "city"), (occupations, "noc")):
        for key, group in groups.items():
            group.sort(key=m.rank)
            position[(kind, *key)] = {eid: i for i, eid in enumerate(group)}
    out: dict[str, list[dict]] = {}
    for eid, e in m.employers.items():
        taken = {eid}
        picks: list[str] = []
        for kind, key, groups in (("city", city_key.get(eid), cities), ("noc", (e["province"], m.noc.get(eid)), occupations)):
            if key is None or key not in groups or len(picks) >= RELATED_MAX:
                continue
            group = groups[key]
            near = _nearest(group, position[(kind, *key)][eid], RELATED_MAX - len(picks), taken)
            near.sort(key=m.rank)
            picks += near
            taken.update(near)
        if not picks:
            continue
        own = city_key.get(eid, (None, None))[1]
        rows = []
        for rid in picks:
            r = m.employers[rid]
            row = {"id": rid, "name": r["display_name"]}
            if r["city"] and slugify(r["city"]) != own:
                row["city"] = r["city"]
            rows.append(row)
        out[eid] = rows
    return out
