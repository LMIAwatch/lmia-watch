"""Occupation and place pages: one small JSON file per page.

Why: job seekers, consultants and reporters look up LMIA records by job and by
town, and the search page canonicalises every filtered view onto /search, so
no such view can be found from a search engine. Each page here carries its
own figures (approvals and refusals by quarter, the change since the previous
quarter, the stream mix, posted wages against the Job Bank median and against
Statistics Canada's offered wage for the same occupation and region), so it
is more than a list of rows. The Worker renders one file per request, and
every file stays far below the 300 KB a request may parse.

Output tree (under data/out/static):
  occupations/index.json       every NOC 2021 unit group with records, with counts
  occupations/<noc>.json       one occupation
  places/index.json            provinces, census metropolitan areas, the largest cities per province
  places/<pp>.json             one province (two-letter code, lower case), with all its city pages listed
  places/<pp>/<slug>.json      one census metropolitan area ('<name>-cma') or city

Occupations use NOC 2021 only: ESDC's lists carry five-digit NOC 2021 codes
from 2024 Q2 on (the first quarter is found in the data), and the four-digit
NOC 2011 codes before that do not map one to one onto them. Places use every
year. A city is the city as written on the records, folded for case, accents,
punctuation and "Saint"/"St"; it gets a page at THRESHOLD records or more. A
census metropolitan area is found from each record's postal area through
fsa_regions. A page under THRESHOLD records is marked noindex by the site and
left out of the sitemap.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .normalize import POSTAL_RE, PRUID_PROVINCE, fold_accents, period_end_date

THRESHOLD = 20
TOP_EMPLOYERS = 20
TOP_ROWS = 15
STREAM_QUARTERS = 4
CITIES_PER_PROVINCE_INDEX = 25
OCCUPATION_FLOOR = "2023Q1"
PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
PROVINCE_PRUID = {v: k for k, v in PRUID_PROVINCE.items()}
STREAM_ALIASES = {"Talent mondial": "Global Talent Stream", "Global Talent": "Global Talent Stream"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# -- names and slugs -------------------------------------------------------------

def slugify(text: str | None) -> str:
    """'Saint-Hyacinthe' and 'St Hyacinthe' -> 'st-hyacinthe'; 'Montréal' -> 'montreal'."""
    folded = fold_accents(text or "").lower().replace("'", "").replace("’", "")
    tokens = [t for t in re.split(r"[^a-z0-9]+", folded) if t]
    tokens = ["st" if t == "saint" else "ste" if t == "sainte" else t for t in tokens]
    return "-".join(tokens)[:80].strip("-")


def display_name(spellings: Counter) -> str:
    """The most frequent spelling, preferring one in mixed case over all capitals."""
    ranked = sorted(spellings.items(), key=lambda kv: (-(kv[0] != kv[0].upper() and kv[0] != kv[0].lower()), -kv[1], kv[0]))
    name = ranked[0][0].strip() if ranked else ""
    return name.title() if name and (name == name.upper() or name == name.lower()) else name


def _fsa(*texts: str | None) -> str | None:
    for text in texts:
        if text:
            m = POSTAL_RE.search(text)
            if m:
                return m.group(1).upper()
    return None


def _stream(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return STREAM_ALIASES.get(text, text) or None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


# -- aggregation -----------------------------------------------------------------

class Agg:
    """Running totals for one page."""

    __slots__ = ("records", "ar", "ap", "rr", "rp", "pending", "postings", "quarters", "streams", "employers",
                 "esdc_recent", "post_recent", "regions", "provinces", "occupations", "wages", "ers", "cmas",
                 "spellings", "prov_votes", "updated")

    def __init__(self) -> None:
        self.records = self.ar = self.ap = self.rr = self.rp = self.pending = self.postings = 0
        self.quarters: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        self.streams: dict[str | None, list[int]] = defaultdict(lambda: [0, 0])
        self.employers: set[str] = set()
        self.esdc_recent: list[dict] = []
        self.post_recent: list[dict] = []
        self.regions: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])      # er -> records, approved positions, refused rows
        self.provinces: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        self.occupations: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        self.wages: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"HOUR": [], "YEAR": []})
        self.ers: Counter = Counter()
        self.cmas: Counter = Counter()
        self.spellings: Counter = Counter()
        self.prov_votes: Counter = Counter()
        self.updated = ""

    def seen(self, date: str | None) -> None:
        if date and date > self.updated:
            self.updated = date


class Model:
    """Everything the pages need, computed in one pass over the records."""

    def __init__(self) -> None:
        self.occ: dict[str, Agg] = defaultdict(Agg)
        self.prov: dict[str, Agg] = defaultdict(Agg)
        self.cma: dict[str, Agg] = defaultdict(Agg)
        self.city: dict[tuple[str, str], Agg] = defaultdict(Agg)
        self.national: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        self.occ_from: str | None = None
        self.latest: str = ""
        self.periods: list[str] = []
        self.stream_periods: set[str] = set()
        self.updated = ""
        self.cma_names: dict[str, str] = {}
        self.er_names: dict[str, str] = {}


def _places_for(m: Model, prov: str | None, city: str | None, fsa: str | None,
                regions: dict[str, tuple]) -> list[tuple[Agg, str]]:
    """The place aggregates a record belongs to, with each one's kind."""
    if prov not in PROVINCE_PRUID:
        return []
    out = [(m.prov[prov], "prov")]
    area = regions.get(fsa) if fsa else None
    if area and area[2]:
        out.append((m.cma[area[2]], "cma"))
    slug = slugify(city)
    if slug:
        out.append((m.city[(prov, slug)], "city"))
    return out


def build(conn: sqlite3.Connection) -> Model:
    m = Model()
    regions = {r["fsa"]: (r["er_uid"], r["er_name"], r["cma_uid"], r["cma_name"])
               for r in conn.execute("SELECT fsa, er_uid, er_name, cma_uid, cma_name FROM fsa_regions")}
    for er, er_name, cma, cma_name in regions.values():
        if er and er_name:
            m.er_names[er] = er_name
        if cma and cma_name:
            m.cma_names[cma] = cma_name
    published = {r["resource_id"]: r["published"] for r in conn.execute("SELECT resource_id, published FROM esdc_resources")}
    m.periods = sorted({r[0] for r in conn.execute("SELECT DISTINCT period FROM esdc_records")})
    m.latest = m.periods[-1] if m.periods else ""
    quarterly = [p for p in m.periods if re.fullmatch(r"\d{4}Q[1-4]", p)]
    m.stream_periods = set(quarterly[-STREAM_QUARTERS:])
    first5 = conn.execute(
        "SELECT MIN(period) FROM esdc_records WHERE length(noc_code) = 5 AND period >= ?", (OCCUPATION_FLOOR,)).fetchone()[0]
    m.occ_from = first5

    rows = conn.execute(
        "SELECT id, list, period, employer_id, employer_raw, province, stream, city, postal_code, noc_code, noc_title, "
        "positions, resource_id FROM esdc_records ORDER BY period DESC, id DESC")
    for r in rows:
        positive = r["list"] == "positive"
        period = r["period"]
        positions = int(r["positions"] or 0)
        nat = m.national[period]
        nat[0 if positive else 2] += 1
        nat[1 if positive else 3] += positions
        date = period_end_date(period) or ""
        changed = (published.get(r["resource_id"]) or date)[:10]
        m.updated = max(m.updated, changed)
        fsa = _fsa(r["postal_code"])
        area = regions.get(fsa) if fsa else None
        noc = r["noc_code"] if r["noc_code"] and len(r["noc_code"]) == 5 and r["noc_code"].isdigit() else None
        if noc and period < OCCUPATION_FLOOR:
            noc = None
        recent = {"id": r["employer_id"], "name": r["employer_raw"], "city": r["city"], "prov": r["province"],
                  "date": date, "period": period, "status": "approved" if positive else "refused",
                  "positions": positions, "noc": noc}
        scopes = _places_for(m, r["province"], r["city"], fsa, regions)
        if noc:
            scopes.append((m.occ[noc], "occ"))
        stream = _stream(r["stream"])
        for agg, kind in scopes:
            agg.records += 1
            q = agg.quarters[period]
            if positive:
                agg.ar += 1
                agg.ap += positions
                q[0] += 1
                q[1] += positions
                if period in m.stream_periods:
                    s = agg.streams[stream]
                    s[0] += 1
                    s[1] += positions
            else:
                agg.rr += 1
                agg.rp += positions
                q[2] += 1
                q[3] += positions
            agg.seen(changed)
            if r["employer_id"] not in agg.employers:
                agg.employers.add(r["employer_id"])
                if len(agg.esdc_recent) < TOP_EMPLOYERS:
                    agg.esdc_recent.append(recent)
            if area and area[0]:
                agg.ers[area[0]] += 1
            if kind == "occ":
                if area and area[0]:
                    reg = agg.regions[area[0]]
                    reg[0] += 1
                    reg[1 if positive else 2] += positions if positive else 1
                if r["province"]:
                    pv = agg.provinces[r["province"]]
                    pv[0] += 1
                    pv[1 if positive else 2] += positions if positive else 1
            else:
                if noc:
                    oc = agg.occupations[noc]
                    oc[0] += 1
                    oc[1 if positive else 2] += positions if positive else 1
                if kind == "city":
                    agg.spellings[(r["city"] or "").strip()] += 1
                    if area and area[2]:
                        agg.cmas[area[2]] += 1
                elif kind == "cma":
                    agg.prov_votes[r["province"]] += 1

    for p in conn.execute(
        "SELECT posting_id, employer_id, employer_raw, title, noc_code, street, city, province, postal_code, wage_min, "
        "wage_max, wage_unit, vacancies, date_posted, first_seen, flag_current FROM jobbank_postings ORDER BY posting_id"):
        fsa = _fsa(p["postal_code"], p["city"], p["street"], p["province"])
        area = regions.get(fsa) if fsa else None
        noc = p["noc_code"] if p["noc_code"] and re.fullmatch(r"\d{5}", p["noc_code"]) else None
        date = p["date_posted"] or (p["first_seen"] or "")[:10]
        first_seen = (p["first_seen"] or "")[:10]
        m.updated = max(m.updated, first_seen)
        status = {"requested": "pending", "approved": "approved"}.get(p["flag_current"], "lapsed")
        posted = p["wage_min"] if p["wage_min"] is not None else p["wage_max"]
        unit = (p["wage_unit"] or "").upper()
        wage = posted if posted is not None and posted > 0 and unit in ("HOUR", "YEAR") else None
        recent = {"id": p["employer_id"], "name": p["employer_raw"], "city": p["city"], "prov": p["province"],
                  "date": date, "period": None, "status": status, "positions": p["vacancies"], "noc": noc,
                  "posting": p["posting_id"]}
        scopes = _places_for(m, p["province"], p["city"], fsa, regions)
        if noc:
            scopes.append((m.occ[noc], "occ"))
        for agg, kind in scopes:
            agg.records += 1
            agg.postings += 1
            agg.pending += status == "pending"
            agg.seen(first_seen)
            agg.employers.add(p["employer_id"])
            agg.post_recent.append(recent)
            if area and area[0]:
                agg.ers[area[0]] += 1
            if kind == "occ":
                if area and area[0]:
                    agg.regions[area[0]][0] += 1
                    if wage is not None:
                        agg.wages[area[0]][unit].append(wage)
                if wage is not None:
                    agg.wages["00"][unit].append(wage)
                if p["province"]:
                    agg.provinces[p["province"]][0] += 1
            else:
                if noc:
                    agg.occupations[noc][0] += 1
                    if wage is not None:
                        agg.wages[noc][unit].append(wage)
                if kind == "city":
                    agg.spellings[(p["city"] or "").strip()] += 1
                    if area and area[2]:
                        agg.cmas[area[2]] += 1
                elif kind == "cma":
                    agg.prov_votes[p["province"]] += 1
    return m


# -- reference figures -----------------------------------------------------------

class References:
    """Job Bank medians (newest table), Statistics Canada vacancies, NOC titles and LFS rates."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        table = conn.execute(
            "SELECT resource_id, revision_date, name FROM wage_tables ORDER BY revision_date DESC, resource_id DESC LIMIT 1"
        ).fetchone()
        self.wage_table = {"revision": table["revision_date"], "name": table["name"]} if table else None
        self.medians: dict[tuple[str, str], tuple[float, int, str | None]] = {}
        if table:
            for r in conn.execute("SELECT noc_code, area_code, median, annual, reference_period FROM jobbank_wages "
                                  "WHERE resource_id = ?", (table["resource_id"],)):
                self.medians[(r["noc_code"], r["area_code"])] = (float(r["median"]), int(r["annual"]), r["reference_period"])
        self.vacancies: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        self.area_names: dict[str, str] = {}
        for r in conn.execute("SELECT noc_code, area_code, ref_quarter, area_name, combined, vacancies, vacancies_quality, "
                              "offered_wage, offered_wage_quality FROM statcan_vacancies ORDER BY ref_quarter"):
            self.vacancies[(r["noc_code"], r["area_code"])].append(
                (r["ref_quarter"], r["vacancies"], r["vacancies_quality"], r["offered_wage"], r["offered_wage_quality"]))
            self.area_names[r["area_code"]] = r["area_name"]
        self.latest_quarter = conn.execute("SELECT MAX(ref_quarter) FROM statcan_vacancies").fetchone()[0]
        self.titles = {r["noc_code"]: (r["title_en"], r["title_fr"], r["definition_en"], r["definition_fr"])
                       for r in conn.execute("SELECT noc_code, title_en, title_fr, definition_en, definition_fr FROM noc_titles")}
        self.lfs: dict[str, tuple[str, float]] = {}
        for r in conn.execute("SELECT cma_uid, ref_month, rate FROM lfs_unemployment ORDER BY ref_month"):
            self.lfs[r["cma_uid"]] = (r["ref_month"], float(r["rate"]))

    @staticmethod
    def chain(area: str | None) -> list[tuple[str, str]]:
        """Area codes to try, narrowest first: economic region, province, Canada."""
        out: list[tuple[str, str]] = []
        if area and len(area) == 4:
            out.append((area, "region"))
        if area and len(area) >= 2 and area != "00":
            out.append((area[:2], "province"))
        out.append(("00", "canada"))
        return out

    def jobbank(self, noc: str, area: str | None) -> dict | None:
        for code, level in self.chain(area):
            hit = self.medians.get((noc, code))
            if hit:
                return {"median": hit[0], "annual": hit[1], "level": level, "area": code, "reference": hit[2]}
        return None

    def statcan(self, noc: str, area: str | None) -> dict | None:
        """The newest published wage and vacancy count at the narrowest area that has either."""
        for code, level in self.chain(area):
            series = self.vacancies.get((noc, code))
            if not series:
                continue
            wage = next(((q, w, wq) for q, _v, _vq, w, wq in reversed(series) if w is not None), None)
            vac = next(((q, v, vq) for q, v, vq, _w, _wq in reversed(series) if v is not None), None)
            if wage is None and vac is None:
                continue
            out = {"level": level, "area": code, "name": self.area_names.get(code)}
            if wage:
                out.update(wage_quarter=wage[0], wage=wage[1], wage_quality=wage[2])
            if vac:
                out.update(vac_quarter=vac[0], vacancies=vac[1], vac_quality=vac[2])
                year_before = _shift(vac[0], 4)
                prior = next((v for q, v, _vq, _w, _wq in series if q == year_before and v is not None), None)
                if prior is not None:
                    out["vacancies_year_before"] = prior
            return out
        return None

    def series(self, noc: str, area: str) -> list[list]:
        return [[q, v, vq, w, wq] for q, v, vq, w, wq in self.vacancies.get((noc, area), [])]


def _shift(quarter: str, back: int) -> str:
    year, q = quarter.split("Q")
    index = int(year) * 4 + int(q) - 1 - back
    return f"{index // 4}Q{index % 4 + 1}"


def _posted(samples: dict[str, list[float]] | None) -> dict:
    samples = samples or {"HOUR": [], "YEAR": []}
    return {"hourly": _median(samples["HOUR"]), "hourly_n": len(samples["HOUR"]),
            "annual": _median(samples["YEAR"]), "annual_n": len(samples["YEAR"])}


# -- page assembly ---------------------------------------------------------------

def _quarters(agg: Agg, periods: list[str]) -> list[list]:
    return [[p, *agg.quarters[p]] if p in agg.quarters else [p, 0, 0, 0, 0] for p in periods]


def _streams(agg: Agg) -> list[list]:
    rows = [[k, v[0], v[1]] for k, v in agg.streams.items()]
    rows.sort(key=lambda r: (-r[2], -r[1], r[0] or ""))
    return rows


def _recent(agg: Agg, names: dict[str, tuple]) -> list[dict]:
    """The employers with the most recent records, newest first, one row each."""
    merged = sorted(agg.post_recent, key=lambda r: (r["date"] or "", r.get("posting") or 0), reverse=True)[:TOP_EMPLOYERS * 3]
    merged += agg.esdc_recent
    merged.sort(key=lambda r: r["date"] or "", reverse=True)
    out: list[dict] = []
    seen: set[str] = set()
    for r in merged:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        row = dict(r)
        known = names.get(r["id"])
        if known:
            row["name"] = known[0]
        row.pop("posting", None)
        out.append(row)
        if len(out) == TOP_EMPLOYERS:
            break
    return out


def _title(refs: References, noc: str, fallback: dict[str, str]) -> dict:
    t = refs.titles.get(noc)
    if t:
        return {"en": t[0], "fr": t[1]}
    name = fallback.get(noc) or noc
    return {"en": name, "fr": name}


def _national_latest(m: Model) -> dict:
    nat = m.national.get(m.latest, [0, 0, 0, 0])
    return {"period": m.latest, "approved": nat[0], "positions": nat[1], "refused": nat[2]}


def occupation_page(m: Model, refs: References, noc: str, agg: Agg, names: dict, fallback: dict, periods: list[str]) -> dict:
    regions = sorted(agg.regions.items(), key=lambda kv: (-kv[1][0], kv[0]))[:TOP_ROWS]
    t = refs.titles.get(noc)
    return {
        "noc": noc,
        "title": _title(refs, noc, fallback),
        "definition": {"en": t[2], "fr": t[3]} if t else None,
        "category": noc[0],
        "category_title": _title(refs, noc[0], {}) if noc[0] in refs.titles else None,
        "teer": noc[1],
        "from": m.occ_from,
        "latest": m.latest,
        "updated": agg.updated or None,
        "totals": _totals(agg),
        "quarters": _quarters(agg, periods),
        "streams": _streams(agg),
        "stream_periods": sorted(m.stream_periods),
        "provinces": sorted(([p, *v] for p, v in agg.provinces.items()), key=lambda r: (-r[1], r[0]))[:14],
        "national": {
            "posted": _posted(agg.wages.get("00")),
            "jobbank": refs.jobbank(noc, "00"),
            "statcan": refs.statcan(noc, "00"),
        },
        "statcan_series": refs.series(noc, "00"),
        "regions": [
            {
                "er": er, "name": m.er_names.get(er) or refs.area_names.get(er) or er, "prov": PRUID_PROVINCE.get(er[:2]),
                "records": v[0], "positions": v[1], "refused": v[2],
                "posted": _posted(agg.wages.get(er)),
                "jobbank": refs.jobbank(noc, er),
                "statcan": refs.statcan(noc, er),
            }
            for er, v in regions
        ],
        "national_latest": _national_latest(m),
        "employers": _recent(agg, names),
        "wage_table": refs.wage_table,
        "statcan_latest": refs.latest_quarter,
        "threshold": THRESHOLD,
    }


def _totals(agg: Agg) -> dict:
    return {"records": agg.records, "approved": agg.ar, "positions": agg.ap, "refused": agg.rr,
            "refused_positions": agg.rp, "pending": agg.pending, "postings": agg.postings, "employers": len(agg.employers)}


def place_page(m: Model, refs: References, kind: str, prov: str, slug: str, name: str, agg: Agg, names: dict,
               fallback: dict, extra: dict) -> dict:
    """A province, census metropolitan area or city."""
    region = agg.ers.most_common(1)[0][0] if kind != "province" and agg.ers else None
    ref_area = region or PROVINCE_PRUID.get(prov)
    occupations = sorted(agg.occupations.items(), key=lambda kv: (-kv[1][0], kv[0]))[:TOP_ROWS]
    page = {
        "kind": kind,
        "prov": prov,
        "slug": slug,
        "name": name,
        "latest": m.latest,
        "occ_from": m.occ_from,
        "updated": agg.updated or None,
        "totals": _totals(agg),
        "quarters": _quarters(agg, m.periods),
        "streams": _streams(agg),
        "stream_periods": sorted(m.stream_periods),
        "region": {"er": region, "name": m.er_names.get(region) or refs.area_names.get(region) or region} if region else None,
        "occupations": [
            {
                "noc": noc, "title": _title(refs, noc, fallback), "records": v[0], "positions": v[1], "refused": v[2],
                "posted": _posted(agg.wages.get(noc)),
                "jobbank": refs.jobbank(noc, ref_area),
                "statcan": refs.statcan(noc, ref_area),
            }
            for noc, v in occupations
        ],
        "context": refs.statcan("total", ref_area),
        "statcan_series": refs.series("total", ref_area) if ref_area else [],
        "national_latest": _national_latest(m),
        "employers": _recent(agg, names),
        "wage_table": refs.wage_table,
        "statcan_latest": refs.latest_quarter,
        "threshold": THRESHOLD,
    }
    page.update(extra)
    return page


def _employer_names(conn: sqlite3.Connection, ids: set[str]) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    ordered = sorted(ids)
    for i in range(0, len(ordered), 500):
        chunk = ordered[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT id, display_name FROM employers WHERE id IN ({marks})", chunk):
            out[r["id"]] = (r["display_name"],)
    return out


class Catalog:
    """The pages to write, with their counts; shared by the writer and the sitemap."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.model = build(conn)
        m = self.model
        self.occupations = sorted(m.occ)
        self.provinces = [p for p in PROVINCES if p in m.prov and m.prov[p].records]
        self.cmas: dict[str, tuple[str, str, str]] = {}            # cma uid -> (prov, slug, name)
        for uid, agg in m.cma.items():
            prov = agg.prov_votes.most_common(1)[0][0] if agg.prov_votes else None
            name = m.cma_names.get(uid) or uid
            if prov in PROVINCE_PRUID and slugify(name):
                self.cmas[uid] = (prov, f"{slugify(name)}-cma", name)
        taken = {(p, s) for p, s, _ in self.cmas.values()}
        self.cities: dict[tuple[str, str], str] = {}               # (prov, slug) -> name
        for (prov, slug), agg in m.city.items():
            if agg.records >= THRESHOLD and SLUG_RE.match(slug) and (prov, slug) not in taken:
                self.cities[(prov, slug)] = display_name(agg.spellings) or slug

    def entries(self) -> list[tuple[str, str | None]]:
        """(path, lastmod) for every page at or above the threshold, and the two index pages."""
        m = self.model
        out: list[tuple[str, str | None]] = []
        occ = [(f"/occupations/{noc}", m.occ[noc].updated or None) for noc in self.occupations if m.occ[noc].records >= THRESHOLD]
        if occ:
            out.append(("/occupations", max((d for _, d in occ if d), default=None)))
            out += occ
        places = [(f"/places/{p.lower()}", m.prov[p].updated or None) for p in self.provinces if m.prov[p].records >= THRESHOLD]
        places += sorted((f"/places/{prov.lower()}/{slug}", m.cma[uid].updated or None)
                         for uid, (prov, slug, _n) in self.cmas.items() if m.cma[uid].records >= THRESHOLD)
        places += sorted((f"/places/{prov.lower()}/{slug}", m.city[(prov, slug)].updated or None)
                         for (prov, slug) in self.cities)
        if places:
            out.append(("/places", max((d for _, d in places if d), default=None)))
            out += places
        return out


_CACHE: dict[str, object] = {}


def _fingerprint(conn: sqlite3.Connection) -> tuple:
    return (
        THRESHOLD, id(conn), conn.total_changes,
        tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM esdc_records").fetchone()),
        tuple(conn.execute("SELECT COUNT(*), MAX(updated_at) FROM jobbank_postings").fetchone()),
        conn.execute("SELECT COUNT(*) FROM fsa_regions").fetchone()[0],
    )


def catalog(conn: sqlite3.Connection) -> Catalog:
    """Built once per export: the writer and the sitemap read the same pages."""
    key = _fingerprint(conn)
    if _CACHE.get("key") != key:
        _CACHE["key"] = key
        _CACHE["value"] = Catalog(conn)
    return _CACHE["value"]  # type: ignore[return-value]


def sitemap_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    return catalog(conn).entries()


def _dump(path: Path, obj: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def write_places(conn: sqlite3.Connection, out: Path) -> dict[str, int]:
    """Write every occupation and place file; returns counts for the run log."""
    cat = catalog(conn)
    m = cat.model
    refs = References(conn)
    fallback = {r["noc_code"]: r["noc_title"] for r in conn.execute(
        "SELECT noc_code, MAX(noc_title) AS noc_title FROM esdc_records WHERE length(noc_code) = 5 GROUP BY noc_code")}
    for r in conn.execute("SELECT noc_code, MAX(noc_title) AS noc_title FROM jobbank_postings WHERE noc_code IS NOT NULL GROUP BY noc_code"):
        fallback.setdefault(r["noc_code"], r["noc_title"])
    wanted: set[str] = set()
    aggs = [m.occ[n] for n in cat.occupations] + [m.prov[p] for p in cat.provinces] + \
        [m.cma[u] for u in cat.cmas] + [m.city[k] for k in cat.cities]
    for agg in aggs:
        wanted.update(r["id"] for r in agg.esdc_recent)
        wanted.update(r["id"] for r in sorted(agg.post_recent, key=lambda r: r["date"] or "", reverse=True)[:TOP_EMPLOYERS * 3])
    names = _employer_names(conn, wanted)
    files = 0
    total_bytes = 0
    largest = 0

    def dump(rel: str, obj: object) -> None:
        nonlocal files, total_bytes, largest
        n = _dump(out / rel, obj)
        files += 1
        total_bytes += n
        largest = max(largest, n)

    occ_periods = [p for p in m.periods if m.occ_from and p >= m.occ_from]
    index_rows = []
    for noc in cat.occupations:
        agg = m.occ[noc]
        dump(f"occupations/{noc}.json", occupation_page(m, refs, noc, agg, names, fallback, occ_periods))
        latest = agg.quarters.get(m.latest, [0, 0, 0, 0])
        index_rows.append({"noc": noc, "title": _title(refs, noc, fallback), "records": agg.records,
                           "approved": agg.ar, "positions": agg.ap, "refused": agg.rr, "pending": agg.pending,
                           "latest_positions": latest[1], "indexed": agg.records >= THRESHOLD})
    categories = {c: _title(refs, c, {}) for c in sorted({n[0] for n in cat.occupations}) if c in refs.titles}
    dump("occupations/index.json", {"from": m.occ_from, "latest": m.latest, "threshold": THRESHOLD,
                                    "categories": categories, "rows": index_rows, "updated": m.updated or None})

    cities_by_prov: dict[str, list[dict]] = defaultdict(list)
    for (prov, slug), name in cat.cities.items():
        agg = m.city[(prov, slug)]
        cities_by_prov[prov].append({"slug": slug, "name": name, "records": agg.records})
    for rows in cities_by_prov.values():
        rows.sort(key=lambda r: (-r["records"], r["slug"]))
    cmas_by_prov: dict[str, list[dict]] = defaultdict(list)
    for uid, (prov, slug, name) in cat.cmas.items():
        agg = m.cma[uid]
        cmas_by_prov[prov].append({"slug": slug, "name": name, "uid": uid, "records": agg.records,
                                   "indexed": agg.records >= THRESHOLD})
    for rows in cmas_by_prov.values():
        rows.sort(key=lambda r: (-r["records"], r["slug"]))
    cma_by_uid = {uid: {"slug": s, "name": n, "prov": p} for uid, (p, s, n) in cat.cmas.items()}

    prov_rows = []
    for prov in cat.provinces:
        agg = m.prov[prov]
        extra = {"cmas": cmas_by_prov.get(prov, []), "cities": cities_by_prov.get(prov, [])}
        dump(f"places/{prov.lower()}.json", place_page(m, refs, "province", prov, prov.lower(), prov, agg, names, fallback, extra))
        latest = agg.quarters.get(m.latest, [0, 0, 0, 0])
        prov_rows.append({"prov": prov, "records": agg.records, "positions": agg.ap, "latest_positions": latest[1],
                          "indexed": agg.records >= THRESHOLD, "cities": len(cities_by_prov.get(prov, [])),
                          "top_cities": cities_by_prov.get(prov, [])[:CITIES_PER_PROVINCE_INDEX],
                          "cmas": cmas_by_prov.get(prov, [])})
    for uid, (prov, slug, name) in cat.cmas.items():
        agg = m.cma[uid]
        lfs = refs.lfs.get(uid)
        extra = {"cma_uid": uid, "lfs": {"month": lfs[0], "rate": lfs[1]} if lfs else None}
        dump(f"places/{prov.lower()}/{slug}.json", place_page(m, refs, "cma", prov, slug, name, agg, names, fallback, extra))
    for (prov, slug), name in cat.cities.items():
        agg = m.city[(prov, slug)]
        cma_uid = agg.cmas.most_common(1)[0][0] if agg.cmas else None
        cma = cma_by_uid.get(cma_uid) if cma_uid else None
        lfs = refs.lfs.get(cma_uid) if cma_uid else None
        extra = {"cma": cma, "lfs": {"month": lfs[0], "rate": lfs[1]} if lfs and cma else None}
        dump(f"places/{prov.lower()}/{slug}.json", place_page(m, refs, "city", prov, slug, name, agg, names, fallback, extra))
    dump("places/index.json", {"latest": m.latest, "threshold": THRESHOLD, "provinces": prov_rows,
                               "updated": m.updated or None})

    indexed = cat.entries()
    return {
        "place_files": files,
        "place_bytes": total_bytes,
        "place_largest": largest,
        "occupation_pages": len(cat.occupations),
        "occupation_indexed": sum(1 for p, _ in indexed if p.startswith("/occupations/")),
        "place_pages": len(cat.provinces) + len(cat.cmas) + len(cat.cities),
        "place_indexed": sum(1 for p, _ in indexed if p.startswith("/places/")),
    }
