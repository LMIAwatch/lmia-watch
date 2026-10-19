"""Atom feeds of new records, written as static files by the nightly export.

Why static files: a feed reader, a Slack or Teams channel or a feed-to-email
service polls a feed every few minutes to hours. Served from /data/feeds/ as
static assets, a poll never reaches the Worker, costs nothing and counts
against no daily allowance. The site never learns who subscribes and holds no
reader address.

Four events, each its own feed:
  pending    a Job Bank posting first seen with "LMIA requested"
  approved   a Job Bank posting first seen with the "Approved LMIA" flag
  findings   a row of IRCC's list of employers found non-compliant, first seen by the pipeline
  quarters   an ESDC quarterly release, one entry per period with the scope's counts

Scopes: Canada (always written), province, ESDC stream (releases only, since
no other record carries a stream), NOC 2021 major group (postings with an
occupation code, and list rows coded in NOC 2021; the older four-digit NOC 2011
codes group differently and are left out), and census metropolitan area
(fsa_regions maps the postal area to its CMA). A scoped feed whose newest entry
is older than FRESH_DAYS is not written; releases come three to four months
apart, so their feeds use QUARTER_FRESH_DAYS instead, or every scoped release
feed would vanish between releases.

Entries are bilingual. One feed per scope and event keeps the file count near
300, where a feed per language would pass 500. An entry's title is the
employer's name and place as recorded; its summary is an English line and a
French line. Ids are tag URIs built from the source's own identifiers (Job
Bank posting id, IRCC row hash, ESDC period), so a rebuilt database gives the
same ids and a reader never sees an old entry twice.

Output (under data/out/static/feeds):
  index.json                  every feed written, for the site's /feeds page
  canada/<event>.xml
  prov/<P>/<event>.xml
  stream/<slug>/quarters.xml
  noc/<NN>/<event>.xml
  cma/<uid>/<event>.xml

Every file is written deterministically (no wall-clock time), so a feed with
no new entry keeps its bytes and the deploy skips it.
"""

from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from . import config
from .normalize import parse_address

ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS)
# Fixed, not derived from SITE_URL: an entry id must never change, whatever
# address the site is served from.
TAG = "tag:lmiawatch.ca,2026:"
SITE_NAME = "LMIA Watch"

MAX_ENTRIES = 50
FRESH_DAYS = 90
QUARTER_FRESH_DAYS = 400

EVENTS = ["pending", "approved", "findings", "quarters"]
PROVINCE_RE = re.compile(r"\b(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\b")
POSITIVE_DATASET = "90fed587-1364-4f33-a9ee-208181dc0b97"
IRCC_PAGE = config.IRCC_NONCOMPLIANT_URL

PROVINCE_NAME = {
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "MB": ("Manitoba", "Manitoba"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
    "ON": ("Ontario", "Ontario"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "QC": ("Quebec", "Québec"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "YT": ("Yukon", "Yukon"),
    "XX": ("Head office outside Canada", "Siège social à l’extérieur du Canada"),
}

# ESDC's stream names as published (the site's search filter values), with the
# slug used in the feed's path and the French name the site shows. One French
# spelling has turned up in the English files; it counts as its stream.
STREAMS = {
    "High Wage": ("high-wage", "Haut salaire"),
    "Low Wage": ("low-wage", "Bas salaire"),
    "Primary Agriculture": ("primary-agriculture", "Agriculture primaire"),
    "Global Talent Stream": ("global-talent", "Volet des talents mondiaux"),
    "Permanent Resident Only": ("permanent-resident", "Résidence permanente seulement"),
}
STREAM_ALIASES = {"Talent mondial": "Global Talent Stream"}

EVENT_NAME = {
    "pending": ("New pending postings", "Nouvelles offres en attente"),
    "approved": ("New Approved LMIA flags", "Nouvelles mentions « EIMT approuvée »"),
    "findings": ("New IRCC non-compliance findings", "Nouveaux constats de non-conformité d’IRCC"),
    "quarters": ("ESDC quarterly lists", "Listes trimestrielles d’EDSC"),
}
EVENT_ABOUT = {
    "pending": (
        "Job Bank postings first seen with the \"LMIA requested\" flag, newest first.",
        "Offres du Guichet-Emplois vues pour la première fois avec la mention « EIMT demandée », les plus récentes en premier.",
    ),
    "approved": (
        "Job Bank postings first seen with the \"Approved LMIA\" flag, newest first.",
        "Offres du Guichet-Emplois vues pour la première fois avec la mention « EIMT approuvée », les plus récentes en premier.",
    ),
    "findings": (
        "Rows of IRCC's list of employers found non-compliant, newest first by the date LMIA Watch first recorded them.",
        "Lignes de la liste d’IRCC des employeurs jugés non conformes, les plus récentes en premier selon la date où LMIA Watch les a relevées.",
    ),
    "quarters": (
        "One entry per ESDC quarterly release, with the approved and refused records it holds for the feed's area or group.",
        "Une entrée par publication trimestrielle d’EDSC, avec les dossiers approuvés et refusés qu’elle contient pour la région ou le groupe du fil.",
    ),
}
RIGHTS = {
    "jobbank": (
        "Job Bank postings: Government of Canada content, reproduced with attribution.",
        "Offres du Guichet-Emplois : contenu du gouvernement du Canada reproduit avec attribution.",
    ),
    "ircc": (
        "IRCC list of employers found non-compliant: Government of Canada content, reproduced with attribution.",
        "Liste d’IRCC des employeurs jugés non conformes : contenu du gouvernement du Canada reproduit avec attribution.",
    ),
    "esdc": (
        "ESDC positive and negative LMIA employer lists: Open Government Licence, Canada.",
        "Listes des employeurs ayant reçu une EIMT positive ou négative d’EDSC : Licence du gouvernement ouvert, Canada.",
    ),
}
EVENT_RIGHTS = {"pending": "jobbank", "approved": "jobbank", "findings": "ircc", "quarters": "esdc"}

# French sets a narrow no-break space before a colon, as the site's dictionary does.
FR_COLON = " :"
# Characters XML 1.0 forbids; a name scraped with one would make the whole feed unreadable.
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


@dataclass(frozen=True)
class Scope:
    kind: str          # canada | prov | stream | noc | cma
    key: str           # '' for Canada, a province code, a stream slug, a two-digit group, a CMA code
    en: str
    fr: str
    search: tuple[tuple[str, str], ...] = ()   # the site's search filter for the scope
    name: str | None = None                    # the published name (stream, CMA) for the /feeds page

    @property
    def folder(self) -> str:
        return "canada" if self.kind == "canada" else f"{self.kind}/{self.key}"


CANADA = Scope("canada", "", "Canada", "Canada")


@dataclass
class Entry:
    id: str
    updated: str                 # RFC 3339
    title: str
    summary: str
    link: str                    # site path, profile or search
    via: str | None = None       # the source record
    sort: tuple = ()
    scopes: list[Scope] = field(default_factory=list)


# -- small helpers ------------------------------------------------------------------


def _clean(text: object) -> str:
    return _XML_BAD.sub("", str(text or "")).strip()


def rfc3339(value: str | None) -> str | None:
    """An ISO date or datetime as an RFC 3339 instant in UTC, or None."""
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T00:00:00Z"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def decision_date(value: str | None) -> str | None:
    """IRCC's decision date as an ISO date; the list mixes 2026-10-08 with 2/29/2019."""
    text = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def province_code(*values: str | None) -> str | None:
    """The first clean two-letter code among the values. A Job Bank province
    field sometimes carries an address fragment (', AB T2C 2Z2')."""
    for value in values:
        text = (value or "").strip().upper()
        if text in PROVINCE_NAME:
            return text
        m = PROVINCE_RE.search(text)
        if m:
            return m.group(1)
    return None


def fsa_of(*postals: str | None) -> str | None:
    for postal in postals:
        text = (postal or "").strip().upper()
        if re.match(r"^[A-Z]\d[A-Z]", text):
            return text[:3]
    return None


def noc_group(code: str | None) -> str | None:
    """The NOC 2021 major group (two digits) of a five-digit code."""
    text = (code or "").strip()
    return text[:2] if re.fullmatch(r"\d{5}", text) else None


def fmt_int(n: int, lang: str) -> str:
    s = f"{int(n):,}"
    return s.replace(",", " ") if lang == "fr" else s


def period_label(period: str, lang: str) -> str:
    """'2026Q1' as the site writes it: 2026 Q1, T1 2026; a range as 2017 Q1 to Q2."""
    m = re.fullmatch(r"(\d{4})Q(\d)(?:-Q(\d))?", period)
    if not m:
        return period
    y, q, q2 = m.groups()
    if q2:
        return f"T{q} à T{q2} {y}" if lang == "fr" else f"{y} Q{q} to Q{q2}"
    return f"T{q} {y}" if lang == "fr" else f"{y} Q{q}"


def _place(city: str | None, prov: str | None) -> str:
    return ", ".join(p for p in (_clean(city), prov or "") if p)


def _headline(name: str, city: str | None, prov: str | None) -> str:
    place = _place(city, prov)
    return f"{name}, {place}" if place else name


def _both(en: str, fr: str) -> str:
    return f"{en} / {fr}"


def _search_path(params: tuple[tuple[str, str], ...]) -> str:
    return "/search" + (f"?{urlencode(params)}" if params else "")


# -- scopes -------------------------------------------------------------------------


def province_scope(code: str) -> Scope:
    en, fr = PROVINCE_NAME[code]
    return Scope("prov", code, en, fr, (("province", code),))


def stream_scope(stream: str) -> Scope | None:
    stream = STREAM_ALIASES.get(stream, stream)
    if stream not in STREAMS:
        return None
    slug, fr = STREAMS[stream]
    return Scope("stream", slug, stream, fr, (("stream", stream),), name=stream)


def noc_scope(group: str) -> Scope:
    return Scope("noc", group, f"NOC major group {group}", f"grand groupe {group} de la CNP", (("noc", group),))


def cma_scope(uid: str, name: str) -> Scope:
    name = _clean(name)
    return Scope("cma", uid, f"{name} (CMA)", f"{name} (RMR)", name=name)


def cma_lookup(conn: sqlite3.Connection) -> dict[str, Scope]:
    """Postal area -> its census metropolitan area's scope."""
    out: dict[str, Scope] = {}
    scopes: dict[str, Scope] = {}
    for r in conn.execute("SELECT fsa, cma_uid, cma_name FROM fsa_regions WHERE cma_uid IS NOT NULL ORDER BY fsa"):
        uid = str(r["cma_uid"])
        if not re.fullmatch(r"\d{3}", uid):
            continue
        if uid not in scopes:
            scopes[uid] = cma_scope(uid, r["cma_name"] or uid)
        out[r["fsa"]] = scopes[uid]
    return out


# -- entries ------------------------------------------------------------------------


def posting_entries(conn: sqlite3.Connection, cmas: dict[str, Scope]) -> tuple[list[Entry], list[Entry]]:
    """(pending, approved) entries, newest first."""
    pending: list[Entry] = []
    approved: list[Entry] = []
    rows = conn.execute(
        "SELECT p.posting_id, p.employer_id, p.employer_raw, p.title, p.noc_code, p.city, p.province, p.postal_code, "
        "p.first_seen, p.approved_seen_at, p.flag_first, p.url, e.city AS e_city, e.province AS e_province, "
        "e.postal_code AS e_postal FROM jobbank_postings p LEFT JOIN employers e ON e.id = p.employer_id"
    )
    for r in rows:
        prov = province_code(r["province"], r["e_province"])
        city = r["city"] or r["e_city"]
        scopes = [CANADA]
        if prov:
            scopes.append(province_scope(prov))
        group = noc_group(r["noc_code"])
        if group:
            scopes.append(noc_scope(group))
        cma = cmas.get(fsa_of(r["postal_code"], r["e_postal"]) or "")
        if cma:
            scopes.append(cma)
        name = _clean(r["employer_raw"]) or r["employer_id"]
        title = _headline(name, city, prov)
        job_en = f" ({_clean(r['title'])})" if _clean(r["title"]) else ""
        pid = r["posting_id"]
        link = f"/employers/{r['employer_id']}"
        if r["flag_first"] == "requested" and (stamp := rfc3339(r["first_seen"])):
            day = stamp[:10]
            pending.append(Entry(
                id=f"{TAG}jobbank/{pid}/requested",
                updated=stamp,
                title=title,
                summary=_both(
                    f"{title}: Job Bank posting {pid}{job_en} first seen on {day} with the \"LMIA requested\" flag. Source: Job Bank.",
                    f"{title}{FR_COLON} offre {pid} du Guichet-Emplois{job_en} vue pour la première fois le {day} avec la mention "
                    f"« EIMT demandée ». Source{FR_COLON} Guichet-Emplois.",
                ),
                link=link, via=r["url"], sort=(stamp, pid), scopes=scopes,
            ))
        if stamp := rfc3339(r["approved_seen_at"]):
            day = stamp[:10]
            approved.append(Entry(
                id=f"{TAG}jobbank/{pid}/approved",
                updated=stamp,
                title=title,
                summary=_both(
                    f"{title}: Job Bank posting {pid}{job_en} first seen on {day} with the \"Approved LMIA\" flag. Source: Job Bank.",
                    f"{title}{FR_COLON} offre {pid} du Guichet-Emplois{job_en} vue pour la première fois le {day} avec la mention "
                    f"« EIMT approuvée ». Source{FR_COLON} Guichet-Emplois.",
                ),
                link=link, via=r["url"], sort=(stamp, pid), scopes=scopes,
            ))
    pending.sort(key=lambda e: e.sort, reverse=True)
    approved.sort(key=lambda e: e.sort, reverse=True)
    return pending, approved


def finding_entries(conn: sqlite3.Connection, cmas: dict[str, Scope]) -> list[Entry]:
    out: list[Entry] = []
    rows = conn.execute(
        "SELECT f.row_hash, f.employer_id, f.operating_name, f.legal_name, f.address, f.decision_date, f.penalty, f.status, "
        "f.fetched_at, e.display_name, e.city, e.province, e.postal_code FROM findings f "
        "LEFT JOIN employers e ON e.id = f.employer_id"
    )
    for r in rows:
        stamp = rfc3339(r["fetched_at"])
        if not stamp:
            continue
        a_city, a_prov, a_postal = parse_address(r["address"])
        prov = province_code(r["province"], a_prov)
        city = r["city"] or a_city
        scopes = [CANADA]
        if prov:
            scopes.append(province_scope(prov))
        cma = cmas.get(fsa_of(r["postal_code"], a_postal) or "")
        if cma:
            scopes.append(cma)
        name = _clean(r["display_name"] or r["operating_name"] or r["legal_name"]) or "?"
        title = _headline(name, city, prov)
        decided = decision_date(r["decision_date"])
        details = "; ".join(_clean(x) for x in (r["penalty"], r["status"]) if _clean(x))
        tail_en = f"; {details}" if details else ""
        dated_en = f", decision dated {decided}" if decided else ""
        dated_fr = f", décision du {decided}" if decided else ""
        out.append(Entry(
            id=f"{TAG}ircc/{r['row_hash'][:20]}",
            updated=stamp,
            title=title,
            summary=_both(
                f"{title}: on IRCC's list of employers found non-compliant{dated_en}{tail_en}. Source: IRCC.",
                f"{title}{FR_COLON} sur la liste d’IRCC des employeurs jugés non conformes{dated_fr}{tail_en}. Source{FR_COLON} IRCC.",
            ),
            link=f"/employers/{r['employer_id']}" if r["employer_id"] else "",
            via=IRCC_PAGE,
            sort=(stamp, decided or "", r["row_hash"]),
            scopes=scopes,
        ))
    out.sort(key=lambda e: e.sort, reverse=True)
    return out


def quarter_entries(conn: sqlite3.Connection, cmas: dict[str, Scope]) -> dict[Scope, list[Entry]]:
    """Per scope, one entry per release that holds rows in it, newest first."""
    released: dict[str, str] = {}
    for r in conn.execute("SELECT period, MAX(published) AS published, MAX(loaded_at) AS loaded FROM esdc_resources GROUP BY period"):
        stamp = rfc3339(r["published"]) or rfc3339(r["loaded"])
        if stamp:
            released[r["period"]] = stamp
    # (period, scope) -> [approved rows, approved positions, refused rows]
    tally: dict[tuple[str, Scope], list[int]] = defaultdict(lambda: [0, 0, 0])
    rows = conn.execute(
        "SELECT r.period, r.list, r.province, r.stream, r.noc_code, "
        "UPPER(SUBSTR(COALESCE(r.postal_code, e.postal_code), 1, 3)) AS fsa, COUNT(*) AS n, "
        "SUM(COALESCE(r.positions, 0)) AS positions FROM esdc_records r LEFT JOIN employers e ON e.id = r.employer_id "
        "GROUP BY r.period, r.list, r.province, r.stream, r.noc_code, fsa"
    )
    for r in rows:
        if r["period"] not in released:
            continue
        scopes = [CANADA]
        if r["province"] in PROVINCE_NAME:
            scopes.append(province_scope(r["province"]))
        if r["stream"] and (s := stream_scope(r["stream"].strip())):
            scopes.append(s)
        if group := noc_group(r["noc_code"]):
            scopes.append(noc_scope(group))
        if cma := cmas.get(r["fsa"] or ""):
            scopes.append(cma)
        for scope in scopes:
            t = tally[(r["period"], scope)]
            if r["list"] == "positive":
                t[0] += r["n"]
                t[1] += r["positions"] or 0
            else:
                t[2] += r["n"]
    out: dict[Scope, list[Entry]] = defaultdict(list)
    for (period, scope), (pos, positions, neg) in tally.items():
        stamp = released[period]
        day = stamp[:10]
        en_p, fr_p = period_label(period, "en"), period_label(period, "fr")
        out[scope].append(Entry(
            id=f"{TAG}esdc/{period}/{scope.folder}",
            updated=stamp,
            title=_both(f"ESDC lists for {en_p}", f"Listes d’EDSC du {fr_p}"),
            summary=_both(
                f"{scope.en}: {fmt_int(pos, 'en')} approved records ({fmt_int(positions, 'en')} positions) and "
                f"{fmt_int(neg, 'en')} refused records in ESDC's {en_p} lists, published {day}. Source: ESDC.",
                f"{scope.fr}{FR_COLON} {fmt_int(pos, 'fr')} dossiers approuvés ({fmt_int(positions, 'fr')} postes) et "
                f"{fmt_int(neg, 'fr')} dossiers refusés dans les listes d’EDSC du {fr_p}, publiées le {day}. Source{FR_COLON} EDSC.",
            ),
            link=_search_path(scope.search),
            via=f"https://open.canada.ca/data/en/dataset/{POSITIVE_DATASET}",
            sort=(stamp, period),
        ))
    for entries in out.values():
        entries.sort(key=lambda e: e.sort, reverse=True)
    return out


# -- writing ------------------------------------------------------------------------


def _el(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ATOM_NS}}}{tag}", {k.rstrip("_"): v for k, v in attrs.items()})
    if text is not None:
        el.text = _clean(text)
    return el


def feed_document(scope: Scope, event: str, entries: list[Entry], base: str, fallback_updated: str) -> bytes:
    rel = f"feeds/{scope.folder}/{event}.xml"
    ev_en, ev_fr = EVENT_NAME[event]
    about_en, about_fr = EVENT_ABOUT[event]
    rights_en, rights_fr = RIGHTS[EVENT_RIGHTS[event]]
    status = {"pending": "pending", "approved": "approved"}.get(event)
    page = _search_path(scope.search + ((("status", status),) if status else ()))

    root = ET.Element(f"{{{ATOM_NS}}}feed")
    _el(root, "id", f"{TAG}feeds/{scope.folder}/{event}")
    _el(root, "title", f"{SITE_NAME}: {ev_en}, {scope.en} / {ev_fr}, {scope.fr}")
    _el(root, "subtitle", _both(about_en, about_fr))
    _el(root, "updated", entries[0].updated if entries else fallback_updated)
    _el(root, "link", rel="self", type="application/atom+xml", href=f"{base}/data/{rel}")
    _el(root, "link", rel="alternate", type="text/html", href=f"{base}{page}")
    _el(root, "link", rel="related", type="text/html", href=f"{base}/feeds")
    author = _el(root, "author")
    _el(author, "name", SITE_NAME)
    _el(author, "uri", f"{base}/")
    _el(root, "rights", _both(rights_en, rights_fr))
    _el(root, "icon", f"{base}/apple-touch-icon.png")
    for e in entries:
        entry = _el(root, "entry")
        _el(entry, "id", e.id)
        _el(entry, "title", e.title)
        _el(entry, "updated", e.updated)
        if e.link:
            sep = "&" if "?" in e.link else "?"
            _el(entry, "link", rel="alternate", type="text/html", hreflang="en", href=f"{base}{e.link}")
            _el(entry, "link", rel="alternate", type="text/html", hreflang="fr", href=f"{base}{e.link}{sep}lang=fr")
        else:
            _el(entry, "link", rel="alternate", type="text/html", href=e.via or f"{base}/")
        if e.via and e.link:
            _el(entry, "link", rel="via", href=e.via)
        _el(entry, "summary", e.summary)
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8", xml_declaration=False) + b"\n"


def _fresh(entries: list[Entry], cutoff: str) -> bool:
    return bool(entries) and entries[0].updated[:10] >= cutoff


def write_feeds(conn: sqlite3.Connection, out: Path, *, today: date | None = None,
                base_url: str | None = None, max_entries: int = MAX_ENTRIES) -> dict[str, int]:
    """Write every feed and feeds/index.json under `out`; return counts for the export log."""
    base = (base_url or config.SITE_URL).rstrip("/")
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta WHERE key = 'data_as_of'")}
    if today is None:
        as_of = meta.get("data_as_of") or ""
        today = date.fromisoformat(as_of) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of) else datetime.now(timezone.utc).date()
    fallback = f"{today.isoformat()}T00:00:00Z"
    cutoff = {e: (today - timedelta(days=QUARTER_FRESH_DAYS if e == "quarters" else FRESH_DAYS)).isoformat() for e in EVENTS}

    cmas = cma_lookup(conn)
    pending, approved = posting_entries(conn, cmas)
    findings = finding_entries(conn, cmas)
    by_feed: dict[tuple[Scope, str], list[Entry]] = defaultdict(list)
    for event, entries in (("pending", pending), ("approved", approved), ("findings", findings)):
        for e in entries:
            for scope in e.scopes:
                bucket = by_feed[(scope, event)]
                if len(bucket) < max_entries:
                    bucket.append(e)
    for scope, entries in quarter_entries(conn, cmas).items():
        by_feed[(scope, "quarters")] = entries[:max_entries]
    for event in EVENTS:
        by_feed.setdefault((CANADA, event), [])

    folder = out / "feeds"
    index: list[dict] = []
    written = entries_written = size = 0
    order = {"canada": 0, "prov": 1, "stream": 2, "noc": 3, "cma": 4}
    for (scope, event), entries in sorted(by_feed.items(), key=lambda kv: (order[kv[0][0].kind], kv[0][0].key, EVENTS.index(kv[0][1]))):
        if scope.kind != "canada" and not _fresh(entries, cutoff[event]):
            continue
        rel = f"feeds/{scope.folder}/{event}.xml"
        data = feed_document(scope, event, entries, base, fallback)
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written += 1
        entries_written += len(entries)
        size += len(data)
        index.append({
            "scope": scope.kind, "key": scope.key, "name": scope.name, "event": event, "path": rel,
            "entries": len(entries), "updated": entries[0].updated if entries else None,
        })
    doc = {
        "as_of": today.isoformat(), "max_entries": max_entries, "fresh_days": FRESH_DAYS,
        "quarter_fresh_days": QUARTER_FRESH_DAYS, "feeds": index,
    }
    folder.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    (folder / "index.json").write_bytes(data)
    return {"feeds": written, "feed_entries": entries_written, "feed_bytes": size + len(data)}
