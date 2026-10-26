"""IRCC's list of high-wage occupations for Express Entry, read each night and adopted when it changes.

Source: "High-wage occupations and how we assess them", Immigration, Refugees
and Citizenship Canada, canada.ca (terms: canada.ca/en/transparency/terms).
From 2026-11-03 a job offer earns Express Entry points by its occupation's
tier on this list: 100 points where the occupation's median wage is at least
twice the average median wage, 70 at 1.5 to under 2 times, 50 at 1.3 to under
1.5 times. The tier follows the offer's NOC 2021 code alone; the offered wage
plays no part. On 2026-10-25 the page listed 186 unit groups (31, 89 and 66)
in three HTML tables, one per tier, each with a caption naming its ratio.

No person has to act when IRCC changes the list. Each night the stage reads
the page (revalidated with its ETag); when it parses cleanly and passes the
sanity checks (MIN_CODES to MAX_CODES five-digit codes, exactly the three
tiers 100, 70 and 50, no code in two tiers) and differs from the version in
use, it is adopted: stored as a new edition in high_wage_editions with the
date it was first read, used for grading from that night (the grades are
recomputed at once), published with that date, and reported in one notice
naming the codes added, removed and moved. The committed file
data/high_wage_nocs.json (pipeline/scripts/build_high_wage_list.py) is the
fallback before any edition is stored. A page that cannot be read or fails the
checks is a notice the night that starts and the night it ends, never a failed
stage; grading carries on with the last good version meanwhile.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup

from .. import config
from ..db import get_meta, log_run, now_iso, set_meta
from ..http import FetchError, PoliteClient

log = logging.getLogger(__name__)

SOURCE_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/"
    "express-entry/check-score/high-wage.html"
)
SOURCE_URL_FR = (
    "https://www.canada.ca/fr/immigration-refugies-citoyennete/services/immigrer-canada/"
    "entree-express/verifier-note/salaire-eleve.html"
)
LIST_PATH = config.PACKAGE_DATA / "high_wage_nocs.json"
# The ratio each caption names, and the points IRCC gives an offer in that tier.
POINTS_BY_RATIO = {2.0: 100, 1.5: 70, 1.3: 50}
TIER_POINTS = (100, 70, 50)
CAPTION_RE = re.compile(r"at\s+least\s+(twice|\d+(?:\.\d+)?\s*times)", re.I)
NOC_RE = re.compile(r"^\d{5}$")
# A read outside these bounds is not adopted: 186 codes in 2026.
MIN_CODES = 120
MAX_CODES = 400
# The page is a few tens of kilobytes and changes rarely; revalidated each night.
MAX_AGE_S = 20 * 3600
STATE_KEY = "high_wage_state"          # ok | failing: the last read, for notices on a change only


@dataclass(frozen=True)
class Occupation:
    noc: str
    title: str
    points: int


def _ratio(caption: str) -> float | None:
    m = CAPTION_RE.search(" ".join(caption.split()))
    if not m:
        return None
    word = m.group(1).lower()
    if word == "twice":
        return 2.0
    number = re.match(r"\d+(?:\.\d+)?", word)
    return float(number.group(0)) if number else None


def parse_page(html: str) -> tuple[list[Occupation], str | None]:
    """The occupations listed and the page's own modified date.

    Raises ValueError when the page fails the sanity checks: not exactly the
    three tier tables, a caption naming a ratio no tier has, a code in two
    tiers, or a count outside MIN_CODES to MAX_CODES.
    """
    soup = BeautifulSoup(html, "html.parser")
    modified = None
    meta = soup.find("meta", attrs={"name": "dcterms.modified"})
    content = str(meta.get("content") or "").strip() if meta is not None else ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", content):
        modified = content
    found: dict[str, Occupation] = {}
    tiers_seen: set[int] = set()
    for table in soup.find_all("table"):
        caption = table.find("caption")
        ratio = _ratio(caption.get_text(" ")) if caption is not None else None
        if ratio is None:
            continue
        points = POINTS_BY_RATIO.get(ratio)
        if points is None:
            raise ValueError(f"a high-wage table names a ratio of {ratio:g}, which no tier has")
        tiers_seen.add(points)
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2 or not NOC_RE.match(cells[0]):
                continue
            if cells[0] in found and found[cells[0]].points != points:
                raise ValueError(f"NOC {cells[0]} is listed in two tiers")
            found[cells[0]] = Occupation(cells[0], " ".join(cells[1].split()), points)
    if tiers_seen != set(TIER_POINTS):
        raise ValueError(f"expected three tier tables, found {sorted(tiers_seen, reverse=True) or 'none'}")
    if not MIN_CODES <= len(found) <= MAX_CODES:
        raise ValueError(f"{len(found)} occupations read, outside {MIN_CODES} to {MAX_CODES}")
    return sorted(found.values(), key=lambda o: (-o.points, o.noc)), modified


def fingerprint(points: dict[str, int]) -> str:
    """sha256 over the sorted code:points pairs (titles left out, so a retitled row is not a change)."""
    text = "\n".join(f"{noc}:{p}" for noc, p in sorted(points.items()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_document(occupations: list[Occupation], modified: str | None, read_on: str) -> dict:
    """The committed file's content (and an edition's)."""
    points = {o.noc: o.points for o in occupations}
    tiers = [{"points": p, "count": sum(1 for o in occupations if o.points == p)} for p in TIER_POINTS]
    return {
        "source_url": SOURCE_URL,
        "source_url_fr": SOURCE_URL_FR,
        "page_modified": modified,
        "read_on": read_on,
        "count": len(occupations),
        "tiers": tiers,
        "sha256": fingerprint(points),
        "occupations": [{"noc": o.noc, "title": o.title, "points": o.points} for o in occupations],
    }


def write_document(doc: dict, path: Path | None = None) -> None:
    target = path or LIST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_list(path: Path | None = None) -> dict:
    """The committed fallback. A missing or unreadable file reads as an empty list."""
    try:
        doc = _load(str(path or LIST_PATH))
        if not isinstance(doc, dict):
            raise ValueError("not an object")
        return doc
    except (OSError, ValueError):
        return {"occupations": [], "count": 0, "tiers": [], "read_on": None, "page_modified": None,
                "source_url": SOURCE_URL, "source_url_fr": SOURCE_URL_FR, "sha256": None}


def latest_edition(conn: sqlite3.Connection | None) -> dict | None:
    """The newest adopted edition as a document like the committed file; None before any."""
    if conn is None:
        return None
    try:
        r = conn.execute("SELECT read_on, page_modified, sha256, occupations FROM high_wage_editions "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    if r is None:
        return None
    try:
        occupations = json.loads(r[3])
    except ValueError:
        return None
    rows = [o for o in occupations if isinstance(o, dict)]
    tiers = [{"points": p, "count": sum(1 for o in rows if o.get("points") == p)} for p in TIER_POINTS]
    return {"source_url": SOURCE_URL, "source_url_fr": SOURCE_URL_FR, "read_on": r[0], "page_modified": r[1],
            "sha256": r[2], "count": len(rows), "tiers": tiers, "occupations": rows, "adopted": True}


def current(conn: sqlite3.Connection | None = None, path: Path | None = None) -> dict:
    """The version in use: the newest adopted edition, else the committed file."""
    return latest_edition(conn) or load_list(path)


def _points(doc: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in doc.get("occupations") or []:
        if isinstance(o, dict) and NOC_RE.match(str(o.get("noc") or "")) and o.get("points") in TIER_POINTS:
            out[str(o["noc"])] = int(o["points"])
    return out


def points_by_noc(conn: sqlite3.Connection | None = None, path: Path | None = None) -> dict[str, int]:
    """NOC code -> points for the version in use."""
    return _points(current(conn, path))


def list_version(conn: sqlite3.Connection | None = None, path: Path | None = None) -> dict:
    """What the site states about the list in use: when it was read, the page's date, the counts."""
    doc = current(conn, path)
    return {
        "read_on": doc.get("read_on"),
        "page_modified": doc.get("page_modified"),
        "count": len(_points(doc)),
        "tiers": [t for t in doc.get("tiers") or [] if isinstance(t, dict)],
        "source_url": SOURCE_URL,
        "source_url_fr": SOURCE_URL_FR,
        # The last read of IRCC's page failed; grading uses this version meanwhile.
        "stale": bool(conn is not None and get_meta(conn, STATE_KEY) == "failing"),
    }


def compare(committed: dict[str, int], live: dict[str, int]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(live) - set(committed)),
        "removed": sorted(set(committed) - set(live)),
        "moved": sorted(n for n in set(live) & set(committed) if live[n] != committed[n]),
    }


def adoption_notice(diff: dict[str, list[str]], read_on: str) -> str:
    """The one notice for a list adopted tonight."""
    def codes(key: str) -> str:
        items = diff[key]
        shown = ", ".join(items[:15]) + (f" and {len(items) - 15} more" if len(items) > 15 else "")
        return f"{len(items)} {key}" + (f" ({shown})" if items else "")
    parts = [codes("added"), codes("removed")]
    if diff["moved"]:
        parts.append(codes("moved") + " between tiers")
    return f"IRCC high-wage list changed and was adopted for grading from {read_on}: {'; '.join(parts)}"


def summary(diff: dict[str, list[str]] | None, count: int) -> str:
    """The nightly log line for the stage: unchanged with the code count, or the size of each change."""
    if diff is None:
        return f"IRCC high-wage list not read; grading keeps the version in use ({count} codes)"
    if not any(diff.values()):
        return f"IRCC high-wage list unchanged ({count} codes)"
    return (f"IRCC high-wage list changed: {len(diff['added'])} added, {len(diff['removed'])} removed, "
            f"{len(diff['moved'])} moved")


def adopt(conn: sqlite3.Connection, occupations: list[Occupation], modified: str | None, read_on: str,
          stamp: str) -> None:
    doc = build_document(occupations, modified, read_on)
    conn.execute(
        "INSERT INTO high_wage_editions (sha256, read_on, page_modified, source_url, count, occupations, adopted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc["sha256"], read_on, modified, SOURCE_URL, doc["count"], json.dumps(doc["occupations"], ensure_ascii=False),
         stamp),
    )
    conn.commit()


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
        list_path: Path | None = None) -> dict[str, list[str]] | None:
    """Read IRCC's page; adopt it when it changed and passes the checks.

    Returns the difference from the version in use (empty lists when the page
    matches it), or None when the page could not be read or failed the checks.
    Never raises for the page, and never fails the stage: both outcomes are
    logged, with a notice only when something changed.
    """
    stamp = now or now_iso()
    in_use = current(conn, list_path)
    in_use_points = _points(in_use)
    previous_state = get_meta(conn, STATE_KEY)
    try:
        html = client.get_text(SOURCE_URL, cache=True, max_age_s=MAX_AGE_S)
        occupations, modified = parse_page(html)
    except (FetchError, ValueError) as exc:
        if isinstance(exc, ValueError):
            client.forget(SOURCE_URL)  # an unreadable body is fetched afresh next time
        log.warning("high wage: %s", exc)
        set_meta(conn, STATE_KEY, "failing")
        conn.commit()
        notice = None
        if previous_state != "failing":
            notice = (f"IRCC high-wage list could not be read or failed its checks ({exc}); grading continues on the "
                      f"version read {in_use.get('read_on') or 'unknown'}")[:900]
        log_run(conn, "high_wage", detail=f"the IRCC page could not be adopted: {exc}"[:900], notice=notice)
        return None
    live = {o.noc: o.points for o in occupations}
    diff = compare(in_use_points, live)
    notices = []
    if previous_state == "failing":
        notices.append("IRCC high-wage list is readable again")
    if any(diff.values()) or not in_use_points:
        read_on = stamp[:10]
        adopt(conn, occupations, modified, read_on, stamp)
        notices.append(adoption_notice(diff, read_on))
        # Grades follow the adopted list from tonight, whatever stage runs next.
        from .. import intl
        intl.regrade(conn, live, now=stamp)
    set_meta(conn, STATE_KEY, "ok")
    set_meta(conn, "high_wage_checked_at", stamp)
    if modified:
        set_meta(conn, "high_wage_page_modified", modified)
    conn.commit()
    detail = (f"live={len(live)} in_use={len(in_use_points)} added={len(diff['added'])} "
              f"removed={len(diff['removed'])} moved={len(diff['moved'])}")
    if modified:
        detail += f" page_modified={modified}"
    log_run(conn, "high_wage", detail=detail, rows_in=len(live), notice=" | ".join(notices) or None)
    return diff
