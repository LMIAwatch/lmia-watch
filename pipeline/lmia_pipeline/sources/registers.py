"""Published lists of designated employers: the Atlantic Immigration Program and the two community pilots.

An employer must be designated (AIP) or recommended through a community's
list (Rural Community Immigration Pilot, Francophone Community Immigration
Pilot) before its job offer can support a permanent-residence application
under those programs, and no LMIA is involved. The provinces and the pilot
communities publish their lists; IRCC keeps none. REGISTERS below records
every list found on 2026-10-25 with its address, format and terms. None of
them is under an open licence: the provincial lists sit under each
government's website terms, the community lists under their sites'
copyright. The site shows a matched employer's listing as a public record
with a link to the list, and the counts per list; it does not republish the
lists.

Reading (each night, one request per list): HTML lists are parsed with the
selector recorded for them, the North Bay list from the JSON its page loads,
and PDF lists with pypdf (pure Python) in its layout mode, which keeps a
table's columns apart by runs of spaces: each line is split into cells and
the employer's name taken by the list's PDF rule (a bulleted line, a table
row and its name column, one name per line, or two names per line). A PDF
whose file name changes with each revision is found on its page by
link_pattern. A list that cannot be fetched is failing; one that reads to
fewer than MIN_ROWS rows, or loses more than MAX_DROP of its last good read,
is a layout problem; either way the last good rows stay. A site that answers
with a bot challenge page instead of the list is "blocked": it is tried once
a night and read again the night the block is lifted, and nothing is done to
get past it. A PDF pypdf cannot read at all is "not yet readable". Names that
read as a person are never stored (project rule 3).

A copy loaded by hand (Register.snapshot; objects registers/<key>.csv and
registers/<key>.json in the site's private R2 bucket, uploaded by
scripts/load_register_snapshot.py and never committed, since the site does
not republish the lists): for a list whose server does not answer the
runner, though it opens from an ordinary machine. When the live read fails,
the copy's rows become the list's current rows (state "snapshot"), unless a
live read made after the copy was loaded is newer; a live read that succeeds
takes precedence. No copy in R2 (or no R2 access) leaves the list as any
failed read leaves it; a copy that does not read is an item needing
attention. Every night the list's page is
read for its file's link and the file itself is asked for: a link other than
the copy's, or a file whose ETag, Last-Modified or size differ from the
copy's, is an item needing attention (load the new edition by hand), and the
result is in the stage's summary and status.json's registers.

A host that leaves an intermediate certificate out of its TLS handshake
(Register.tls_intermediate) has that certificate trusted for that host only,
in the stage's own client (make_client).

Notices (information, never an item needing attention: status.json,
LAST_RUN.md and the daily check's email; the run stays ok), on a change of
state only: a list the night it stops being read and the night it is read
again, a list the night its copy loaded by hand comes into use, and the set
of lists not yet readable whenever it changes. Every night the lists in each
state are in the stage's summary (LAST_RUN.md) and in status.json's
registers, without a notice.

Matching (every night, rules in matching.py, never across provinces): the
list's name normalizes to an employer's in the list's province, with the
row's location (or the pilot community) agreeing with a city on the
employer's records: exact; the name and province only: probable, and not for
a common name; a trade name ("o/a") with the place: probable.
"""

from __future__ import annotations

import csv
import email.utils
import hashlib
import io
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .. import config
from ..db import get_meta, log_run, now_iso, set_meta
from ..http import AbortRun, FetchError, PoliteClient, decode_text
from ..normalize import PROVINCE_NAMES, norm_name, split_trade_name
from . import matching

log = logging.getLogger(__name__)

PROGRAMS = {
    "AIP": "Atlantic Immigration Program",
    "RCIP": "Rural Community Immigration Pilot",
    "FCIP": "Francophone Community Immigration Pilot",
}
# The terms each list is published under (the site names them in both languages).
TERMS_URLS = {
    "nb_disclaimer": "https://www.gnb.ca/en/admin/disclaimer.html",
    "ns_crown": "https://liveinnovascotia.com/atlantic-immigration-program",
    "pe_policy": ("https://www.princeedwardisland.ca/en/information/executive-council-office/"
                  "website-disclaimer-and-copyright-policy"),
    "nl_disclaimer": "https://www.gov.nl.ca/disclaimer/",
    "community_site": None,
}
NOTICE_SEP = " | "
FAILED_STATES = ("failing", "layout", "blocked")
# Copies of lists loaded by hand live in the site's private R2 bucket under this
# prefix, never in the repository (the site does not republish the lists). The
# intermediate certificates a host leaves out are public and ship as package data.
SNAPSHOT_PREFIX = "registers/"
CERT_DIR = config.PACKAGE_DATA / "certs"
SNAPSHOT_FIELDS = ("name", "location", "designated_on")
# The meta key of a list's latest newer-edition check (a JSON object), by list key.
EDITION_META = "register_edition:"
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# "Boyuk Towing \u2013 2591519 Ontario Inc.": a list that joins a trade name and the
# legal name with a dash, which split_trade_name (o/a, dba) does not read.
DASH_JOIN_RE = re.compile(r"\s+[\u2013\u2014]\s+")
LEGAL_FORM_RE = re.compile(r"\b(inc|ltd|ltée|ltee|limited|limitée|corp|corporation|incorporated|llp|ulc|co)\b\.?|\d{4,}", re.I)
# Attempts per request for this stage's own client: the lists are small pages
# on many hosts, and a host that is down tonight is tried again tomorrow.
CLIENT_ATTEMPTS = 2
# A read with fewer rows than MIN_ROWS, or with less than (1 - MAX_DROP) of the
# last good read, is taken as a changed layout, not a shorter list.
MIN_ROWS = 5
MAX_DROP = 0.6
MAX_NAME = 200
MAX_PDF_PAGES = 80
STATUS_NOTE_RE = re.compile(
    r"\s*[\(\[][^)\]]*\b(?:not\s+(?:currently\s+)?hiring|hiring|effective|currently|ne\s+recrute\s+pas)[^)\]]*[\)\]]\s*$"
    r"|\s+[\u2013\u2014-]\s+(?:not\s+)?(?:currently\s+)?hiring\b[^\u2013\u2014]*$", re.I)
# PDF layout text: columns are runs of three or more spaces apart; a bullet
# opens an item.
CELL_SPLIT_RE = re.compile(r"\s{3,}|\t")
BULLET_RE = re.compile(r"[\u2022\u25aa\u25cf\u25a0\u2023\u25e6\u2043]\s*")
# Cells that are a column heading or a page's furniture, never a name.
PDF_HEADER_RE = re.compile(
    r"^(?:#|priority\s*s\s?ectors?|employers?|employer.s legal business name|business legal name|"
    r"legal business.*name|operating as name|pilot designated|under|list of designated employers:?|"
    r"designated employers?(?: list)?|page \d+( of \d+)?|\d+\s*/\s*\d+)$", re.I)
PDF_JUNK_RE = re.compile(r"@|www\.|https?://|\|\s|\b\d{3}[.\- ]\d{3}[.\- ]\d{4}\b")
CHALLENGE_RE = re.compile(r"radware|captcha|are you a robot|challenge-platform|cf-chl|access denied", re.I)
DATE_TEXT_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                          r"\s+(\d{1,2}),?\s+(\d{4})", re.I)


@dataclass(frozen=True)
class Register:
    key: str
    program: str                    # AIP | RCIP | FCIP
    jurisdiction: str               # province code
    community: str | None
    page_url: str                   # where a reader finds the list (linked on the site)
    data_url: str | None            # the file read; None means page_url itself
    format: str                     # html | json | pdf
    terms: str                      # a TERMS_URLS key
    # html: the CSS selector of one listed employer (an element, or a table row with kind "table")
    selector: str | None = None
    kind: str = "items"             # items | table | json
    name_selector: str | None = None
    location_selector: str | None = None
    keep: str | None = None         # a regex an item's text must match to count
    after: str | None = None        # the items are the <li> of the first `selector` element after this heading text
    split: str | None = None        # how a location rides on the name: "comma" (name, place), "dash" (name - sector)
                                    # or "dash_place" (name - place)
    date_selector: str | None = None
    link_pattern: str | None = None  # pdf: the regex of the list's file on page_url, when its name changes
    # pdf: how a line holds a name. "bullet": the text after a bullet; "table": a
    # row of cells, the name at pdf_name_cell; "lines": one name a line; "columns":
    # every cell of a line of two or more cells is a name.
    pdf_mode: str = "table"
    pdf_name_cell: int = 0
    pdf_trade_cell: int | None = None   # a cell with the name the employer operates under ("o/a")
    pdf_location_cell: int | None = None
    pdf_min_cells: int = 1
    pdf_keep_last: str | None = None    # a regex the row's last cell must match (a status, a pilot, an address)
    pdf_numbered: bool = False          # rows start with a row number, which is dropped
    pdf_join_wrapped: bool = False      # a lone cell before a row is the start of that row's wrapped name
    # A copy loaded by hand (R2 objects registers/<key>.csv and .json), used when the live read fails.
    snapshot: bool = False
    # A PEM file in data/certs/: the intermediate certificate the list's host leaves out of its
    # TLS handshake, trusted for that host only (make_client).
    tls_intermediate: str | None = None

    @property
    def source_url(self) -> str:
        return self.data_url or self.page_url

    @property
    def title(self) -> str:
        """'Nova Scotia' for a provincial list, 'Brandon (RCIP)' for a community's."""
        if self.community:
            return f"{self.community} ({self.program})"
        return PROVINCE_NAMES.get(self.jurisdiction, self.jurisdiction)


COMMUNITY = "community_site"
REGISTERS: tuple[Register, ...] = (
    # -- Atlantic Immigration Program, one list per province -------------------
    Register("aip_nb", "AIP", "NB", None,
             "https://www.gnb.ca/content/dam/GNB3/t/fhc-fmc/immigration/docs/designated-employers-employeurs-designes.pdf",
             None, "pdf", "nb_disclaimer", pdf_mode="bullet"),
    # The file's host refuses the runner's addresses (the page itself answers), so
    # the copy loaded by hand stands in while the live read fails.
    Register("aip_ns", "AIP", "NS", None, "https://liveinnovascotia.com/atlantic-immigration-program",
             "https://liveinnovascotia.com/sites/default/files/2024-07/Designated_AIP_employers.pdf", "pdf", "ns_crown",
             link_pattern=r"[^\"']*Designated[^\"']*employers[^\"']*\.pdf", pdf_mode="bullet", snapshot=True),
    Register("aip_pe", "AIP", "PE", None,
             "https://www.princeedwardisland.ca/en/information/office-of-immigration/atlantic-immigration-program-designated-employers",
             None, "html", "pe_policy", selector="div.field--name-body li", date_selector="div.date"),
    Register("aip_nl", "AIP", "NL", None,
             "https://www.gov.nl.ca/immigration/immigrating-to-newfoundland-and-labrador/atlantic-immigration-program/designated-employers/",
             None, "html", "nl_disclaimer", selector="table.dataTable", kind="table"),
    # -- Rural Community Immigration Pilot ---------------------------------------
    Register("rcip_pictou_county", "RCIP", "NS", "Pictou County", "https://pcrcip.ca/employers/",
             "https://pcrcip.ca/wp-content/uploads/PC_RCIP_Designated_Employers_July_2026.pdf", "pdf", COMMUNITY,
             link_pattern=r"[^\"']*Designated_Employers[^\"']*\.pdf", pdf_min_cells=2, pdf_keep_last=r"recruiting"),
    Register("rcip_north_bay", "RCIP", "ON", "North Bay", "https://nbrcip.ca/designated-employers/",
             "https://nbrcip.ca/wp-admin/admin-ajax.php?action=load_monday_data", "json", COMMUNITY, kind="json"),
    Register("rcip_sudbury", "RCIP", "ON", "Sudbury", "https://investsudbury.ca/why-sudbury/newcomers/rcipfcip/", None,
             "html", COMMUNITY, selector="div.rcip_employer_boxes div.employer_box_container", name_selector="h5",
             location_selector="p"),
    Register("rcip_timmins", "RCIP", "ON", "Timmins",
             "https://timminsedc.com/wp-content/uploads/2026/10/Designated-Employer-List-Timmins-Regional-RCIP-FCIP.pdf",
             None, "pdf", COMMUNITY, pdf_name_cell=-2, pdf_min_cells=2, pdf_keep_last=r"^RCIP(/FCIP)?$"),
    Register("rcip_sault_ste_marie", "RCIP", "ON", "Sault Ste. Marie", "https://welcometossm.com/designated-employers/",
             None, "html", COMMUNITY, selector="div.fl-rich-text p",
             keep=r"^(?!.*(?:©|rights reserved|please note|designation of employers|employer login)).{2,120}$"),
    Register("rcip_thunder_bay", "RCIP", "ON", "Thunder Bay",
             "https://gotothunderbay.ca/wp-content/uploads/2026/09/As-of-September-25-2026.pdf", None, "pdf", COMMUNITY,
             pdf_min_cells=2, pdf_keep_last=r"\d", pdf_location_cell=-1, pdf_join_wrapped=True, split="hyphen_trade"),
    Register("rcip_steinbach", "RCIP", "MB", "Steinbach",
             "https://steinbachedc.com/wp-content/uploads/2026/10/RCIP-Designated-Employers-2.pdf", None, "pdf", COMMUNITY,
             pdf_mode="lines"),
    Register("rcip_altona_rhineland", "RCIP", "MB", "Altona/Rhineland", "https://ared-rpga.com/immigration/rcip-employers/",
             None, "html", COMMUNITY, selector="table[id^=eael-data-table] td"),
    # The host sends only its own certificate; OpenSSL (the runner) cannot reach a root without
    # the intermediate, which a Windows client takes from its own store.
    Register("rcip_brandon", "RCIP", "MB", "Brandon",
             "https://economicdevelopmentbrandon.com/rcip/rcip-list-of-designated-employers", None, "html", COMMUNITY,
             selector="table", kind="table", tls_intermediate="globalsign_gcc_r6_alphassl_ca_2025.pem"),
    Register("rcip_moose_jaw", "RCIP", "SK", "Moose Jaw", "https://rcip.mjchamber.com/candidates/",
             "https://rcip.mjchamber.com/wp-content/uploads/2026/08/designated-employer-list-AUG-26.pdf", "pdf", COMMUNITY,
             link_pattern=r"[^\"']*designated-employer-list[^\"']*\.pdf", pdf_mode="columns"),
    Register("rcip_claresholm", "RCIP", "AB", "Claresholm", "https://claresholm-rcip.ca/", None, "html", COMMUNITY,
             selector="div.wpb_wrapper ul li", keep=r"[\u2013\u2014-]\s*(?:not\s+)?hiring\s*$", split="dash"),
    Register("rcip_west_kootenay", "RCIP", "BC", "West Kootenay", "https://westkootenayimmigration.ca/designated-employers/",
             None, "html", COMMUNITY, selector="table.has-fixed-layout td", split="comma"),
    Register("rcip_north_okanagan_shuswap", "RCIP", "BC", "North Okanagan Shuswap",
             "https://rcipnorthokanaganshuswap.com/resources-and-policies/",
             "https://rcipnorthokanaganshuswap.com/wp-content/uploads/2026/10/"
             "RCIP-North-Okanagan-Shuswap-Designated-Employers-List-Sep-30-2026-updated.pdf", "pdf", COMMUNITY,
             link_pattern=r"[^\"']*Designated-Employers-List[^\"']*\.pdf", pdf_name_cell=-1, pdf_min_cells=2,
             # A row opens with its priority sector (a NOC broad category); the intro's lines do not.
             keep=r"^\s*(?:Legislative|Business|Natural|Health|Education|Art|Sales|Trades|Occupations|Manufacturing)\b"),
    Register("rcip_peace_liard", "RCIP", "BC", "Peace Liard",
             "https://www.nebcimmigration.ca/_files/ugd/c6258b_049cc44adc8b452f82bbb0a2f5f20019.pdf", None, "pdf",
             COMMUNITY, pdf_numbered=True, pdf_trade_cell=1),
    # -- Francophone Community Immigration Pilot -----------------------------------
    Register("fcip_acadian_peninsula", "FCIP", "NB", "Acadian Peninsula",
             "https://inspirepeninsuleacadienne.ca/wp-content/uploads/2026/08/Liste-des-employeurs-designes-PPICF-12-aout-2026.pdf",
             None, "pdf", COMMUNITY, pdf_mode="lines", keep=r"\s-\s", split="dash_place"),
    Register("fcip_sudbury", "FCIP", "ON", "Sudbury", "https://investsudbury.ca/why-sudbury/newcomers/rcipfcip/", None,
             "html", COMMUNITY, selector="div.fcip_employer_boxes div.employer_box_container", name_selector="h5",
             location_selector="p"),
    Register("fcip_timmins", "FCIP", "ON", "Timmins",
             "https://timminsedc.com/wp-content/uploads/2026/10/Designated-Employer-List-Timmins-Regional-RCIP-FCIP.pdf",
             None, "pdf", COMMUNITY, pdf_name_cell=-2, pdf_min_cells=2, pdf_keep_last=r"FCIP$"),
    Register("fcip_superior_east", "FCIP", "ON", "Superior East",
             "https://superioreastcfdc.ca/superioreastcfdc.ca/index.php/fcip/fcip-employers", None, "html", COMMUNITY,
             selector="ul", after=r"^\s*Designated Employers\s*$"),
    Register("fcip_st_pierre_jolys", "FCIP", "MB", "St. Pierre-Jolys",
             "https://stpierre2021.municipalwebsites.ca/ckfinder/connector?command=Proxy&lang=en&type=Files&currentFolder=%2F"
             "&hash=c245c263ce0eced480effe66bbede6b4d46c15ae&fileName=Designated%20Employers%20V3(1).pdf",
             None, "pdf", COMMUNITY, pdf_mode="bullet"),
    Register("fcip_kelowna", "FCIP", "BC", "Kelowna", "https://www.sdecb.com/en/pilot-program/", None, "html", COMMUNITY,
             selector="div.designated-employers__list li"),
)


@dataclass
class Row:
    name: str
    location: str | None = None
    designated_on: str | None = None


class ParseProblem(ValueError):
    """The body did not read as the list."""


class Blocked(ParseProblem):
    """The site answered with a bot challenge page instead of the list."""


def is_challenge(raw: bytes) -> bool:
    """A body that is a bot challenge or block page (never a PDF)."""
    return not is_pdf(raw) and bool(CHALLENGE_RE.search(decode_text(raw[:20000])))


def is_pdf(raw: bytes) -> bool:
    return b"%PDF-" in raw[:1024]


# -- parsing ----------------------------------------------------------------------


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_name(text: str) -> str:
    """The name as listed, without a status note ("(not hiring at the moment)", " \u2013 NOT HIRING")."""
    name = _clean(text)
    for _ in range(3):
        stripped = STATUS_NOTE_RE.sub("", name).strip()
        if stripped == name:
            break
        name = stripped
    return name.strip(" ,;:-–—")[:MAX_NAME]


def _date_text(text: str) -> str | None:
    m = DATE_TEXT_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def _row_date(text: str) -> str | None:
    """'23-Sep-22' (the Newfoundland and Labrador list's form) or an ISO date; None otherwise."""
    text = _clean(text)
    for fmt in ("%d-%b-%y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _split(reg: Register, text: str) -> tuple[str, str | None]:
    if reg.split == "hyphen_trade":
        # "1164309 Ontario LTD- Furniture Recycle": a legal name, a hyphen, the name it trades under.
        parts = re.split(r"\s*-\s+|\s+-\s*", text, maxsplit=1)
        if len(parts) == 2 and LEGAL_FORM_RE.search(parts[0]) and parts[1].strip():
            return f"{parts[0].strip()} o/a {parts[1].strip()}", None
        return text, None
    if reg.split in ("dash", "dash_place"):
        parts = re.split(r"\s+[\u2013\u2014-]\s+", text, maxsplit=1)
        if reg.split == "dash_place" and len(parts) == 2:
            # "Dixie Lee - Neguac (ne recrute pas pour le moment)": the place, without the note or a run-on column.
            return parts[0], re.split(r"\s:\s|NB\s*:", parts[1])[0]
        return parts[0], None
    if reg.split == "comma" and ", " in text:
        head, rest = text.split(", ", 1)
        if len(head) >= 2:
            return head, rest
    return text, None


def parse_html(reg: Register, html: str) -> tuple[list[Row], str | None]:
    """(rows, the list's own date when it states one). Raises ParseProblem when nothing reads as the list."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["script", "style", "noscript"]):
        el.decompose()
    list_date = None
    if reg.date_selector:
        el = soup.select_one(reg.date_selector)
        list_date = _date_text(el.get_text(" ")) if el is not None else None
    if list_date is None:
        found = soup.find(string=re.compile(r"(last updated|updated as of|as of|published date)", re.I))
        if found is not None:
            list_date = _date_text(str(found.parent.get_text(" ") if found.parent else found))
    rows: list[Row] = []
    if reg.kind == "table":
        rows = _table_rows(soup, reg)
    else:
        keep = re.compile(reg.keep, re.I) if reg.keep else None
        for el in _items(soup, reg):
            name_el = el.select_one(reg.name_selector) if reg.name_selector else el
            text = _clean(name_el.get_text(" ") if name_el is not None else "")
            if not text or (keep and not keep.search(text)):
                continue
            if text.lower() in ("employer name", "designated employers", "employer"):
                continue
            head, place = _split(reg, text)
            loc_el = el.select_one(reg.location_selector) if reg.location_selector else None
            location = _clean(loc_el.get_text(" ")) if loc_el is not None else place
            name = clean_name(head)
            if name:
                rows.append(Row(name, location or None))
    if not rows:
        if CHALLENGE_RE.search(html[:20000]):
            raise Blocked("the site answered with a bot challenge page, not the list")
        raise ParseProblem("no employer rows found (the page layout changed?)")
    return _dedupe(rows), list_date


def _items(soup: BeautifulSoup, reg: Register) -> list:
    """The elements that each hold one listed employer."""
    if not reg.after:
        return soup.select(reg.selector or "")
    anchor = soup.find(string=re.compile(reg.after, re.I))
    container = anchor.find_next(reg.selector or "ul") if anchor is not None else None
    return container.find_all("li") if container is not None else []


def _table_rows(soup: BeautifulSoup, reg: Register) -> list[Row]:
    for table in soup.select(reg.selector or "table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [_clean(c.get_text(" ")).lower() for c in trs[0].find_all(["th", "td"])]
        name_col = next((i for i, h in enumerate(header) if "employer" in h), None)
        if name_col is None:
            continue
        loc_col = next((i for i, h in enumerate(header) if any(w in h for w in ("location", "community", "city"))), None)
        date_col = next((i for i, h in enumerate(header) if "date" in h), None)
        rows: list[Row] = []
        for tr in trs[1:]:
            cells = [_clean(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if name_col >= len(cells) or not cells[name_col]:
                continue
            name = clean_name(cells[name_col])
            if not name:
                continue
            rows.append(Row(
                name,
                cells[loc_col] if loc_col is not None and loc_col < len(cells) and cells[loc_col] else None,
                _row_date(cells[date_col]) if date_col is not None and date_col < len(cells) else None,
            ))
        if rows:
            return rows
    return []


def parse_json(body: str) -> list[Row]:
    """The North Bay list: a JSON array of {name, color (the sector), status}."""
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ParseProblem(f"the list is not JSON ({exc})") from exc
    if not isinstance(data, list):
        raise ParseProblem("the list is not a JSON array")
    rows = [Row(clean_name(str(item.get("name") or ""))) for item in data if isinstance(item, dict)]
    rows = [r for r in rows if r.name]
    if not rows:
        raise ParseProblem("the JSON list holds no employer names")
    return _dedupe(rows)


class Unreadable(ValueError):
    """pypdf could not read the file at all (not a PDF, encrypted, no text layer)."""


def pdf_lines(data: bytes) -> list[str]:
    """The text of each page in pypdf's layout mode, as lines. Raises Unreadable when pypdf cannot read it."""
    import io

    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Unreadable("the PDF is encrypted")
        lines: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            lines.extend((page.extract_text(extraction_mode="layout") or "").splitlines())
    except Unreadable:
        raise
    except Exception as exc:  # pypdf raises many kinds on a damaged or odd file
        raise Unreadable(f"pypdf could not read the file ({type(exc).__name__}: {str(exc)[:120]})") from exc
    if not any(line.strip() for line in lines):
        raise Unreadable("the PDF holds no text (a scan?)")
    return lines


def _cells(line: str) -> list[str]:
    return [c.strip() for c in CELL_SPLIT_RE.split(line.strip()) if c.strip()]


def _name_ok(name: str) -> bool:
    return (sum(ch.isalpha() for ch in name) >= 2 and len(name) <= 150 and not PDF_HEADER_RE.match(name)
            and not PDF_JUNK_RE.search(name))


def parse_pdf(reg: Register, data: bytes) -> tuple[list[Row], str | None]:
    """(rows, the list's date when its text states one) from a PDF list, by the list's PDF rule.

    Tolerant by design: a line that does not fit the rule is skipped, so a
    heading, a footer or a wrapped line costs nothing; the row-count checks in
    read_one catch a layout the rule no longer fits.
    """
    lines = pdf_lines(data)
    text = "\n".join(lines)
    list_date = None
    found = re.search(r"(?:as of|updated|last update|current as of)[^\n]{0,40}", text, re.I)
    if found:
        list_date = _date_text(found.group(0))
    keep_line = re.compile(reg.keep, re.I) if reg.keep else None
    keep_last = re.compile(reg.pdf_keep_last, re.I) if reg.pdf_keep_last else None
    rows: list[Row] = []
    pending = ""

    def add(name: str, location: str | None = None, trade: str | None = None) -> None:
        head, place = _split(reg, name)
        clean = clean_name(head)
        if trade:
            trade_clean = clean_name(trade)
            if trade_clean and trade_clean.lower() != clean.lower():
                clean = f"{clean} o/a {trade_clean}"
        loc = clean_name(location or place or "") or None
        if clean and _name_ok(clean):
            rows.append(Row(clean[:MAX_NAME], loc))

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if reg.pdf_mode == "bullet":
            m = None
            for m in BULLET_RE.finditer(line):
                pass
            if m is None:
                continue
            cells = _cells(line[m.end():])
            if cells:
                add(cells[0])
            continue
        if keep_line and not keep_line.search(line):
            continue
        cells = _cells(line)
        if reg.pdf_mode == "lines":
            if cells:
                add(cells[0])
            continue
        if reg.pdf_mode == "columns":
            if len(cells) >= 2:
                for cell in cells:
                    add(cell)
            continue
        # table
        if reg.pdf_numbered:
            if not cells or not re.fullmatch(r"\d{1,5}", cells[0].split()[0]):
                continue
            first = cells[0].split(None, 1)
            cells = ([first[1]] if len(first) > 1 else []) + cells[1:]
        if len(cells) < reg.pdf_min_cells or (keep_last and not keep_last.search(cells[-1])):
            if reg.pdf_join_wrapped and len(cells) == 1 and _name_ok(cells[0]):
                pending = cells[0]
            continue
        try:
            name = cells[reg.pdf_name_cell]
        except IndexError:
            continue
        if pending:
            name, pending = f"{pending} {name}", ""
        location = cells[reg.pdf_location_cell] if reg.pdf_location_cell is not None and len(cells) > 1 else None
        trade = None
        if reg.pdf_trade_cell is not None and len(cells) > reg.pdf_trade_cell:
            trade = cells[reg.pdf_trade_cell]
        add(name, location, trade)
    return _dedupe(rows), list_date


def _dedupe(rows: list[Row]) -> list[Row]:
    out: dict[str, Row] = {}
    for r in rows:
        out.setdefault(r.name, r)
    return list(out.values())


def find_pdf_link(reg: Register, html: str) -> str | None:
    """The list's current file on its page, made absolute; None when the page no longer links one."""
    if not reg.link_pattern:
        return None
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.I):
        if re.fullmatch(reg.link_pattern, href, re.I):
            return urljoin(reg.page_url, href.replace("&amp;", "&"))
    return None


def parse_body(reg: Register, raw: bytes) -> tuple[list[Row], str | None]:
    """(rows, the list's date) from a fetched body, by the list's format. Raises Unreadable or ParseProblem."""
    if reg.format == "pdf":
        return parse_pdf(reg, raw)
    if reg.kind == "json":
        return parse_json(decode_text(raw)), None
    return parse_html(reg, decode_text(raw))


# -- copies loaded by hand ---------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """A copy of a list loaded by hand: its rows and the file they were read from."""

    key: str
    source_url: str
    etag: str | None
    last_modified: str | None
    size: int | None
    sha256: str | None
    list_date: str
    loaded_on: str
    rows: tuple[Row, ...]

    @property
    def stamp(self) -> str:
        """The read time its rows carry: the day it was loaded, at midnight UTC."""
        return f"{self.loaded_on}T00:00:00Z"


def snapshot_keys(key: str) -> tuple[str, str]:
    """The copy's two objects in the site's private R2 bucket: the rows (CSV) and the record (JSON)."""
    return f"{SNAPSHOT_PREFIX}{key}.csv", f"{SNAPSHOT_PREFIX}{key}.json"


class SnapshotStore(Protocol):
    """Where the copies live: resilience.R2Rest in the run, a dictionary in the tests."""

    def get_bytes(self, key: str) -> bytes | None: ...


@dataclass
class CopyRead:
    """The outcome of reading a list's copy: ok (snap set), missing (no object), unavailable
    (no R2 access tonight, or R2 did not answer) or malformed (the objects do not read)."""

    snap: Snapshot | None
    outcome: str
    detail: str = ""


def parse_snapshot(key: str, csv_bytes: bytes, meta_bytes: bytes) -> Snapshot:
    """A copy from its two objects. Raises ValueError saying what does not read."""
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""))
        rows = tuple(Row(r["name"].strip(), (r.get("location") or "").strip() or None,
                         (r.get("designated_on") or "").strip() or None)
                     for r in reader if (r.get("name") or "").strip())
    except (UnicodeDecodeError, ValueError, KeyError, AttributeError, csv.Error) as exc:
        raise ValueError(f"the copy does not read ({type(exc).__name__}: {str(exc)[:100]})") from None
    if not isinstance(meta, dict):
        raise ValueError("the copy's record is not a JSON object")
    loaded_on, list_date, source_url = meta.get("loaded_on"), meta.get("list_date"), meta.get("source_url")
    problems = [what for what, bad in (
        ("loaded_on is not a date", not (isinstance(loaded_on, str) and ISO_DATE_RE.fullmatch(loaded_on))),
        # The site names the list's date wherever the copy's rows are shown.
        ("list_date is not a date", not (isinstance(list_date, str) and ISO_DATE_RE.fullmatch(list_date))),
        ("source_url is not https", not (isinstance(source_url, str) and source_url.startswith("https://"))),
        ("the record is for another list", meta.get("key") not in (None, key)),
        ("no rows", not rows),
    ) if bad]
    if problems:
        raise ValueError("the copy is not usable: " + "; ".join(problems))

    def text(name: str) -> str | None:
        value = meta.get(name)
        return value if isinstance(value, str) and value else None

    size = meta.get("size")
    return Snapshot(key, str(source_url), text("etag"), text("last_modified"),
                    size if isinstance(size, int) and not isinstance(size, bool) else None, text("sha256"),
                    str(list_date), str(loaded_on), rows)


def read_snapshot(reg: Register, store: SnapshotStore | None) -> CopyRead:
    """The list's copy loaded by hand, from the store; never raises."""
    if store is None:
        return CopyRead(None, "unavailable", "no R2 access in this run (CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID)")
    csv_key, meta_key = snapshot_keys(reg.key)
    try:
        meta_raw = store.get_bytes(meta_key)
        csv_raw = store.get_bytes(csv_key) if meta_raw is not None else None
    except Exception as exc:  # R2Error or a transport fault: never a reason to stop the stage
        return CopyRead(None, "unavailable", f"R2 did not answer ({str(exc)[:160]})")
    if meta_raw is None or csv_raw is None:
        return CopyRead(None, "missing", f"no copy in R2 ({meta_key if meta_raw is None else csv_key} is missing)")
    try:
        return CopyRead(parse_snapshot(reg.key, csv_raw, meta_raw), "ok")
    except ValueError as exc:
        return CopyRead(None, "malformed", str(exc))


def snapshot_objects(reg: Register, rows: list[Row], *, source_url: str, etag: str | None, last_modified: str | None,
                     size: int, sha256: str, list_date: str, loaded_on: str) -> tuple[bytes, bytes, dict]:
    """A copy loaded by hand as its two objects (CSV rows, JSON record) and the record itself.

    Names that read as a person are left out here as well as at load, so the
    stored copy never holds one (project rule 3)."""
    kept = [r for r in rows if not matching.is_person_name(r.name)]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(SNAPSHOT_FIELDS)
    writer.writerows([r.name, r.location or "", r.designated_on or ""] for r in kept)
    meta = {
        "key": reg.key,
        "source_url": source_url,
        "etag": etag,
        "last_modified": last_modified,
        "size": size,
        "sha256": sha256,
        "list_date": list_date,
        "loaded_on": loaded_on,
        "loaded_by": "hand",
        "parser": "lmia_pipeline.sources.registers.parse_body",
        "rows_read": len(rows),
        "rows_left_out_as_person": len(rows) - len(kept),
        "rows": len(kept),
    }
    meta_bytes = (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return buf.getvalue().encode("utf-8"), meta_bytes, meta


def r2_snapshots() -> SnapshotStore | None:
    """The site's private bucket through the run's token; None without one (a dev machine)."""
    from ..resilience import r2_from_env

    try:
        return r2_from_env()
    except Exception as exc:
        log.warning("designated lists: R2 cannot be reached for the copies (%s)", type(exc).__name__)
        return None


@dataclass
class Probe:
    """What a night's live read saw of a list: its page, the file's link on it, and the file."""

    page_read: bool = False
    link: str | None = None          # the list's file as linked on its page
    url: str | None = None           # the address fetched
    pdf: bool = False                # the body fetched is a PDF
    etag: str | None = None
    last_modified: str | None = None
    size: int | None = None


def _http_time(value: str | None) -> datetime | None:
    try:
        return email.utils.parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError, IndexError):
        return None


def _modified_differs(theirs: str, ours: str) -> bool:
    a, b = _http_time(theirs), _http_time(ours)
    return a != b if a is not None and b is not None else theirs.strip() != ours.strip()


def check_edition(reg: Register, snap: Snapshot, probe: Probe, state: str, stamp: str) -> dict:
    """Whether the publisher has an edition other than the copy loaded by hand.

    "newer": the page links another file, or the file answers with another
    ETag, Last-Modified or size (an item needing attention: load it by hand);
    "unchanged": the file answers as the copy, or the page links the copy's file
    while the file itself does not answer; "unknown": neither could be read;
    "read live": the live read succeeded, so the copy is not in use."""
    base = {"key": reg.key, "checked_at": stamp, "list_date": snap.list_date, "loaded_on": snap.loaded_on,
            "copy_url": snap.source_url}
    modified = _http_time(probe.last_modified) if probe.pdf else None
    modified_on = modified.date().isoformat() if modified is not None else None
    if state == "ok":
        return {**base, "result": "read live", "url": probe.url or snap.source_url, "modified": modified_on,
                "detail": "the list was read live; the copy loaded by hand is not in use", "attention": None}
    changes: list[str] = []
    if probe.link and probe.link != snap.source_url:
        changes.append(f"the page links {probe.link}")
    if probe.pdf:
        if probe.etag and snap.etag and probe.etag != snap.etag:
            changes.append(f"ETag {probe.etag} (copy {snap.etag})")
        if probe.last_modified and snap.last_modified and _modified_differs(probe.last_modified, snap.last_modified):
            changes.append(f"Last-Modified {probe.last_modified} (copy {snap.last_modified})")
        if probe.size is not None and snap.size is not None and probe.size != snap.size:
            changes.append(f"size {probe.size} (copy {snap.size})")
    url = probe.link or probe.url or snap.source_url
    if changes:
        result, detail = "newer", "; ".join(changes)
    elif probe.pdf:
        result, detail = "unchanged", "the file answers with the copy's ETag, Last-Modified and size"
    elif probe.link:
        result, detail = "unchanged", "the page links the copy's file; the file itself did not answer"
    elif probe.page_read:
        result, detail = "unknown", "the page links no file the list's pattern matches, and the file did not answer"
    else:
        result, detail = "unknown", "neither the page nor the file answered"
    attention = None
    if result == "newer":
        when = f"modified {modified_on}" if modified_on else "modification date not known"
        attention = (f"{reg.title} designated-employer list: a newer edition is published at {url} ({when}); "
                     f"load it by hand")
    return {**base, "result": result, "url": url, "modified": modified_on, "detail": detail, "attention": attention}


def edition_summary(check: dict) -> str:
    """One check as a clause of the stage's summary line."""
    if check.get("result") == "no copy":
        return f"{check.get('key')}: copy loaded by hand not used, {check.get('detail')}"
    if check.get("result") == "read live":
        return f"{check.get('key')}: read live, the copy loaded by hand not in use"
    head = f"{check.get('key')} copy loaded by hand {check.get('loaded_on')}"
    if check.get("list_date"):
        head += f" (list dated {check['list_date']})"
    result = check.get("result")
    if result == "newer":
        when = f"modified {check['modified']}" if check.get("modified") else "modification date not known"
        tail = f"a newer edition is published at {check.get('url')} ({when}), load it by hand"
    elif result == "unchanged":
        tail = f"no newer edition ({check.get('detail')})"
    elif result == "read live":
        tail = "not in use, the list was read live"
    else:
        tail = f"newer edition not checked ({check.get('detail')})"
    return f"{head}: {tail}"


def edition_checks(conn: sqlite3.Connection, registers: tuple[Register, ...] = ()) -> dict[str, dict]:
    """The latest newer-edition check of each list that carries a copy loaded by hand, by key.

    Reads meta by position, so it works on the plain connection the run status opens."""
    out: dict[str, dict] = {}
    for reg in registers or REGISTERS:
        if not reg.snapshot:
            continue
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (EDITION_META + reg.key,)).fetchone()
        try:
            check = json.loads(row[0]) if row and row[0] else None
        except ValueError:
            continue
        if isinstance(check, dict):
            out[reg.key] = check
    return out


def attention_items(conn: sqlite3.Connection) -> list[str]:
    """Items needing attention from the latest checks: a newer edition to load by hand, or a copy that does not read."""
    return [c["attention"] for c in edition_checks(conn).values()
            if c.get("result") in ("newer", "no copy") and isinstance(c.get("attention"), str)]


# -- run ----------------------------------------------------------------------------


def _state(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM designated_lists WHERE key = ?", (key,)).fetchone()


def _save_state(conn: sqlite3.Connection, reg: Register, *, state: str, stamp: str, source_url: str | None = None,
                rows: int | None = None, list_date: str | None = None, ok: bool = False, detail: str | None = None,
                sha256: str | None = None, ok_at: str | None = None, streak: int | None = None) -> None:
    """Record a list's state. ok_at sets the time its current rows carry without a good live read
    (a copy loaded by hand); streak, when given, is kept as it stands."""
    prev = _state(conn, reg.key)
    if streak is None:
        streak = 0 if ok or state == "unreadable" else (prev["fail_streak"] if prev else 0) + 1
    conn.execute(
        """
        INSERT INTO designated_lists (key, program, jurisdiction, community, source_url, format, state, rows, list_date,
                                      last_ok_at, last_attempt_at, fail_streak, detail, sha256)
        VALUES (:key, :program, :jur, :community, :url, :format, :state, COALESCE(:rows, 0), :list_date,
                :ok_at, :stamp, :streak, :detail, :sha)
        ON CONFLICT(key) DO UPDATE SET
          program = excluded.program, jurisdiction = excluded.jurisdiction, community = excluded.community,
          source_url = COALESCE(:url, designated_lists.source_url), format = excluded.format, state = excluded.state,
          rows = COALESCE(:rows, designated_lists.rows), list_date = COALESCE(:list_date, designated_lists.list_date),
          last_ok_at = COALESCE(:ok_at, designated_lists.last_ok_at), last_attempt_at = excluded.last_attempt_at,
          fail_streak = excluded.fail_streak, detail = excluded.detail,
          sha256 = COALESCE(:sha, designated_lists.sha256)
        """,
        {"key": reg.key, "program": reg.program, "jur": reg.jurisdiction, "community": reg.community,
         "url": source_url or (prev["source_url"] if prev else reg.source_url), "format": reg.format, "state": state, "rows": rows,
         "list_date": list_date, "ok_at": ok_at or (stamp if ok else None), "stamp": stamp, "streak": streak,
         "detail": (detail or "")[:400] or None, "sha": sha256},
    )


def split_names(name: str) -> tuple[str, str | None]:
    """(legal name, trade name or None). "X o/a Y" and "X dba Y" as split_trade_name reads
    them; "Trade \u2013 Legal Inc." or "Legal Inc. \u2013 Trade" with the part carrying a legal form
    or a company number taken as the legal name."""
    legal, trade = split_trade_name(name)
    if trade or not DASH_JOIN_RE.search(name):
        return legal, trade
    first, second = DASH_JOIN_RE.split(name, maxsplit=1)
    if LEGAL_FORM_RE.search(second) and not LEGAL_FORM_RE.search(first):
        return second.strip(), first.strip()
    return first.strip(), second.strip()


def _store_rows(conn: sqlite3.Connection, reg: Register, rows: list[Row], stamp: str) -> tuple[int, int]:
    """Upsert the listed rows; (stored, left out as a person)."""
    stored = persons = 0
    for r in rows:
        if matching.is_person_name(r.name):
            persons += 1
            continue
        legal, trade = split_names(r.name)
        trade_name = matching.business_name(trade) if trade else None
        conn.execute(
            """
            INSERT INTO designated_employers (list_key, employer_name, norm_name, trade_name, trade_norm, location,
                                              designated_on, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(list_key, employer_name) DO UPDATE SET
              location = COALESCE(excluded.location, designated_employers.location),
              designated_on = COALESCE(excluded.designated_on, designated_employers.designated_on),
              norm_name = excluded.norm_name, trade_name = excluded.trade_name, trade_norm = excluded.trade_norm,
              last_seen = excluded.last_seen
            """,
            (reg.key, r.name, norm_name(legal or r.name), trade_name, norm_name(trade_name) if trade_name else None,
             r.location, r.designated_on, stamp, stamp),
        )
        stored += 1
    return stored, persons


def read_one(conn: sqlite3.Connection, client: PoliteClient, reg: Register, stamp: str,
             probe: Probe | None = None) -> str:
    """Read one list and record its state; returns the state. Raises AbortRun only.

    probe, when given, is filled with what the read saw of the page and the
    file (the newer-edition check of a list with a copy loaded by hand)."""
    probe = probe if probe is not None else Probe()
    prev = _state(conn, reg.key)
    url = reg.source_url
    if reg.format == "pdf" and reg.link_pattern:
        # The file's name changes with each revision: its current address is on its page.
        try:
            page = client.get_text(reg.page_url, cache=True, max_age_s=20 * 3600)
            probe.page_read = True
            found = find_pdf_link(reg, page)
        except FetchError:
            found = None
        probe.link = found
        if found:
            url = found
        elif prev is not None:
            url = prev["source_url"]
    probe.url = url
    try:
        raw = client.get(url, cache=True, max_age_s=20 * 3600)
    except FetchError as exc:
        _save_state(conn, reg, state="failing", stamp=stamp, source_url=url, detail=f"not fetched: {exc}")
        return "failing"
    if is_pdf(raw):
        headers = client.cached_headers(url)
        probe.pdf, probe.size = True, len(raw)
        probe.etag, probe.last_modified = headers.get("etag"), headers.get("last_modified")
    try:
        rows, list_date = parse_body(reg, raw)
    except (Unreadable, ParseProblem) as exc:
        # A bot challenge in place of the list: blocked, tried again tomorrow, never worked around.
        if isinstance(exc, Blocked) or is_challenge(raw):
            client.forget(url)
            _save_state(conn, reg, state="blocked", stamp=stamp, source_url=url,
                        detail="the site answered with a bot challenge page, not the list")
            return "blocked"
        if isinstance(exc, Unreadable):
            _save_state(conn, reg, state="unreadable", stamp=stamp, source_url=url, detail=str(exc))
            return "unreadable"
        client.forget(url)
        _save_state(conn, reg, state="layout", stamp=stamp, source_url=url, detail=str(exc))
        return "layout"
    # The floor is a check on the parse, so it counts every row read; the drop
    # compares the rows kept with the rows the last good read kept.
    persons = sum(1 for r in rows if matching.is_person_name(r.name))
    kept = len(rows) - persons
    last_good = prev["rows"] if prev is not None and prev["last_ok_at"] else 0
    problem = None
    if len(rows) < MIN_ROWS:
        problem = f"{len(rows)} rows read, fewer than {MIN_ROWS} (the layout changed?); last rows kept"
    elif last_good and kept < (1 - MAX_DROP) * last_good:
        problem = f"{kept} rows read, down from {last_good} (the layout changed?); last rows kept"
    if problem:
        client.forget(url)
        _save_state(conn, reg, state="layout", stamp=stamp, source_url=url, detail=problem)
        return "layout"
    stored, persons = _store_rows(conn, reg, rows, stamp)
    detail = f"{stored} rows" + (f", {persons} names read as a person left out" if persons else "")
    _save_state(conn, reg, state="ok", stamp=stamp, source_url=url, rows=stored, list_date=list_date,
                ok=True, detail=detail, sha256=hashlib.sha256(raw).hexdigest())
    return "ok"


def use_snapshot(conn: sqlite3.Connection, reg: Register, snap: Snapshot, stamp: str, live_state: str) -> str:
    """After a failed live read, the copy loaded by hand becomes the list's current rows; returns the state.

    A live read made after the copy was loaded is at least as new, so its
    rows stay and the failed state stands. The copy's rows carry the day it
    was loaded (Snapshot.stamp), so reloading it each night changes nothing,
    and the names that read as a person are left out as on any read."""
    prev = _state(conn, reg.key)
    if prev is not None and (prev["last_ok_at"] or "") > snap.stamp:
        return live_state
    why = (prev["detail"] if prev is not None else None) or "no detail"
    stored, persons = _store_rows(conn, reg, list(snap.rows), snap.stamp)
    # The copy first, so a notice cut short keeps it; the live failure after.
    detail = (f"{stored} rows from the copy of the list dated {snap.list_date} loaded by hand on {snap.loaded_on}"
              + (f", {persons} names read as a person left out" if persons else "")
              + f"; live read {live_state}: {why[:200]}")
    _save_state(conn, reg, state="snapshot", stamp=stamp, source_url=snap.source_url, rows=stored,
                list_date=snap.list_date, ok_at=snap.stamp, detail=detail, sha256=snap.sha256,
                streak=prev["fail_streak"] if prev is not None else 1)
    return "snapshot"


def make_client() -> PoliteClient:
    """The stage's own client: fewer retries (CLIENT_ATTEMPTS) and, for a host that leaves an
    intermediate certificate out of its handshake, that certificate trusted for that host only.

    A certificate file that cannot be read is logged and skipped: that list
    then fails to connect as it would without it, and the others are unchanged."""
    client = PoliteClient(max_attempts=CLIENT_ATTEMPTS)
    for reg in REGISTERS:
        if not reg.tls_intermediate:
            continue
        try:
            pem = (CERT_DIR / reg.tls_intermediate).read_text(encoding="ascii")
            for host in sorted({urlsplit(u).hostname for u in (reg.page_url, reg.source_url)} - {None}):
                client.trust_intermediate(str(host), pem)
        except (OSError, ValueError) as exc:  # ssl.SSLError is an OSError
            log.warning("designated list %s: certificate %s not loaded (%s)", reg.key, reg.tls_intermediate, exc)
    return client


def match(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Rebuild designated_matches from every stored row; returns the matches written."""
    stamp = now or now_iso()
    regs = {r.key: r for r in REGISTERS}
    pairs = conn.execute(
        """
        SELECT e.id, 'legal' AS kind, d.list_key, d.employer_name, d.norm_name AS norm, d.location, l.jurisdiction
        FROM designated_employers d JOIN designated_lists l ON l.key = d.list_key
        JOIN employers e ON e.norm_name = d.norm_name AND e.province = l.jurisdiction
        UNION
        SELECT e.id, 'other', d.list_key, d.employer_name, d.trade_norm, d.location, l.jurisdiction
        FROM designated_employers d JOIN designated_lists l ON l.key = d.list_key
        JOIN employers e ON e.norm_name = d.trade_norm AND e.province = l.jurisdiction
        WHERE d.trade_norm IS NOT NULL AND d.trade_norm != d.norm_name
        ORDER BY 1, 3, 4
        """
    ).fetchall()
    places = matching.employer_places(conn, {p[0] for p in pairs})
    found: dict[tuple[str, str, str], tuple[str, str]] = {}
    for eid, kind, key, name, norm, location, _jur in pairs:
        place = places.get(eid) or matching.Places()
        towns = {matching.fold_city(location)} if location else set()
        # A street address ("2266 Lasalle Blvd, Greater Sudbury, ON") carries the city as one of its parts.
        towns |= {matching.fold_city(part) for part in (location or "").split(",")}
        community = regs[key].community if key in regs else None
        if community:
            towns |= {matching.fold_city(c) for c in re.split(r"[/,]| and ", community)}
        towns.discard("")
        strong = bool(towns & place.cities)
        g = matching.grade(kind, strong, True, norm)
        if not g:
            continue
        basis = ("name_city" if strong else "name_province") if kind == "legal" else "trade_name_city"
        current = found.get((eid, key, name))
        if current is None or matching.GRADE_RANK[g] < matching.GRADE_RANK[current[0]]:
            found[(eid, key, name)] = (g, basis)
    conn.execute("DELETE FROM designated_matches")
    conn.executemany(
        "INSERT INTO designated_matches (employer_id, list_key, employer_name, grade, basis, matched_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(eid, key, name, g, basis, stamp) for (eid, key, name), (g, basis) in sorted(found.items())],
    )
    conn.commit()
    return len(found)


def _notices(conn: sqlite3.Connection, before: dict[str, str], states: dict[str, str]) -> list[str]:
    """Notices on a change of state only: a list the night it stops being read and the night it is
    read again, and the set of lists not yet readable when it changes. Nothing on a night like the last."""
    out: list[str] = []
    details = {r[0]: r[1] for r in conn.execute("SELECT key, detail FROM designated_lists")}
    stopped = [k for k, s in states.items() if s in FAILED_STATES and before.get(k) not in FAILED_STATES]
    copied = [k for k, s in states.items() if s == "snapshot" and before.get(k) != "snapshot"]
    recovered = [k for k, s in states.items() if s == "ok" and before.get(k) in FAILED_STATES + ("snapshot",)]
    if stopped:
        out.append("Designated-employer lists not read from tonight (their last good rows are kept): "
                   + "; ".join(f"{k} ({(details.get(k) or 'no detail')[:90]})" for k in stopped))
    if copied:
        out.append("Designated-employer lists not read live from tonight, their copy loaded by hand in use: "
                   + "; ".join(f"{k} ({(details.get(k) or 'no detail')[:160]})" for k in copied))
    if recovered:
        out.append("Designated-employer lists read again: " + ", ".join(recovered))
    unreadable = sorted(k for k, s in states.items() if s == "unreadable")
    signature = ",".join(unreadable)
    old = get_meta(conn, "registers_unreadable_sig") or ""
    if signature != old:
        if unreadable:
            out.append(f"Designated-employer lists not yet readable (pypdf could not read the PDF): {signature}")
        elif all(states.get(k) == "ok" for k in old.split(",") if k in states):
            # A list that left the set for its copy loaded by hand is not readable again.
            out.append("Every designated-employer list is readable again")
    set_meta(conn, "registers_unreadable_sig", signature)
    return out


@dataclass
class RegisterStats:
    states: dict[str, str]
    matched: int
    rows: int
    # The newer-edition check of each list with a copy loaded by hand (check_edition), by key.
    editions: dict[str, dict] = field(default_factory=dict)

    def by_state(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, s in sorted(self.states.items()):
            out.setdefault(s, []).append(key)
        return out

    def summary(self) -> str:
        """The night's line for LAST_RUN.md: counts per state, which lists are not read, and the edition checks."""
        groups = self.by_state()
        parts = ", ".join(f"{len(keys)} {s}" for s, keys in sorted(groups.items()))
        line = f"{len(self.states)} lists ({parts}), {self.rows} current rows, {self.matched} employer matches"
        not_read = [f"{s}: {', '.join(keys)}" for s, keys in sorted(groups.items()) if s != "ok"]
        not_read += [edition_summary(c) for _, c in sorted(self.editions.items())]
        return line + (f"; {'; '.join(not_read)}" if not_read else "")


def run(conn: sqlite3.Connection, client: PoliteClient, *, now: str | None = None,
        registers: tuple[Register, ...] = REGISTERS, snapshots: SnapshotStore | None = None) -> RegisterStats:
    """Read every list, match, and log one row with the notices. Never raises for a list or a site.

    The command line gives this stage a client of its own (make_client) with
    fewer retries, so a small site that is down costs seconds, and its
    failures never count toward another stage's circuit breaker; and the
    site's private R2 bucket (r2_snapshots) for the copies loaded by hand,
    read only for a list whose live read failed. Without R2 access, or with
    no copy there, the list is as any list whose live read failed."""
    stamp = now or now_iso()
    states: dict[str, str] = {}
    editions: dict[str, dict] = {}
    before = {r[0]: r[1] for r in conn.execute("SELECT key, state FROM designated_lists")}
    for reg in registers:
        probe = Probe()
        try:
            state = read_one(conn, client, reg, stamp, probe)
        except AbortRun as exc:
            # The circuit breaker counts failures across hosts, and each list
            # is a host of its own: a run of small sites that are down must
            # not stop the lists after them.
            client.reset_failures()
            _save_state(conn, reg, state="failing", stamp=stamp, detail=f"not fetched: {exc}")
            state = "failing"
        if reg.snapshot:
            if state == "ok":
                editions[reg.key] = {"key": reg.key, "checked_at": stamp, "result": "read live",
                                     "url": probe.url, "attention": None,
                                     "detail": "the list was read live; the copy loaded by hand is not in use"}
            else:
                copy = read_snapshot(reg, snapshots)
                if copy.snap is not None:
                    state = use_snapshot(conn, reg, copy.snap, stamp, state)
                    editions[reg.key] = check_edition(reg, copy.snap, probe, state, stamp)
                else:
                    # A missing copy (or no R2 access) leaves the list as any failed
                    # read leaves it; only a copy that is there and does not read
                    # needs someone.
                    csv_key, meta_key = snapshot_keys(reg.key)
                    attention = (f"{reg.title} designated-employer list: the copy loaded by hand in R2 ({csv_key} "
                                 f"and {meta_key}) does not read ({copy.detail[:160]}); load it again"
                                 if copy.outcome == "malformed" else None)
                    editions[reg.key] = {"key": reg.key, "checked_at": stamp, "result": "no copy",
                                         "copy": copy.outcome, "detail": copy.detail, "attention": attention}
            set_meta(conn, EDITION_META + reg.key, json.dumps(editions[reg.key], ensure_ascii=False))
        states[reg.key] = state
        conn.commit()
    matched = match(conn, now=stamp)
    rows = conn.execute(
        "SELECT COUNT(*) FROM designated_employers d JOIN designated_lists l ON l.key = d.list_key "
        "WHERE d.last_seen = l.last_ok_at").fetchone()[0]
    stats = RegisterStats(states, matched, rows, editions)
    notices = _notices(conn, before, states)
    conn.commit()
    # One row, its notices joined by NOTICE_SEP; the run status splits them
    # into one notice each (nightly._notices).
    log_run(conn, "registers", detail=stats.summary(), rows_in=rows, rows_new=matched,
            notice=NOTICE_SEP.join(notices) if notices else None)
    return stats


# -- export ---------------------------------------------------------------------------


def export_rows(conn: sqlite3.Connection) -> list[dict]:
    """Each list's state for the site: program, place, address, terms, current rows and matched employers."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "designated_lists" not in tables:
        return []
    states = {r["key"]: r for r in conn.execute("SELECT * FROM designated_lists")}
    current = {r[0]: r[1] for r in conn.execute(
        "SELECT d.list_key, COUNT(*) FROM designated_employers d JOIN designated_lists l ON l.key = d.list_key "
        "WHERE d.last_seen = l.last_ok_at GROUP BY d.list_key")}
    matched = {r[0]: r[1] for r in conn.execute(
        "SELECT list_key, COUNT(DISTINCT employer_id) FROM designated_matches GROUP BY list_key")}
    out = []
    for reg in REGISTERS:
        s = states.get(reg.key)
        # The copy in use, from the list's own record: its date, and the day it was loaded.
        in_copy = s is not None and s["state"] == "snapshot" and s["list_date"] and s["last_ok_at"]
        out.append({
            "key": reg.key,
            "program": reg.program,
            "jurisdiction": reg.jurisdiction,
            "community": reg.community,
            "page_url": reg.page_url,
            "source_url": s["source_url"] if s is not None else reg.source_url,
            "format": reg.format,
            "terms": reg.terms,
            "terms_url": TERMS_URLS.get(reg.terms),
            "state": s["state"] if s is not None else "not_read",
            "rows": current.get(reg.key, 0),
            "list_date": s["list_date"] if s is not None else None,
            "last_ok": (s["last_ok_at"] or "")[:10] or None if s is not None else None,
            "matched": matched.get(reg.key, 0),
            # The copy loaded by hand when its rows are the list's current rows, else null.
            "snapshot": {"list_date": s["list_date"], "loaded_on": s["last_ok_at"][:10]} if in_copy else None,
        })
    return out


def profile_rows(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """Each employer's matched designated-employer listings, best grade first.

    A row that is current only through a list's copy loaded by hand carries
    "snapshot" (the list's date and the day the copy was loaded), so the
    profile says so; other rows have no such key."""
    marks = ",".join("?" * len(ids))
    regs = {r.key: r for r in REGISTERS}
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        f"""
        SELECT m.employer_id, m.list_key, m.employer_name, m.grade, m.basis, d.location, d.designated_on,
               d.first_seen, d.last_seen, l.last_ok_at, l.source_url, l.state, l.list_date
        FROM designated_matches m
        JOIN designated_employers d ON d.list_key = m.list_key AND d.employer_name = m.employer_name
        JOIN designated_lists l ON l.key = m.list_key
        WHERE m.employer_id IN ({marks})
        ORDER BY m.employer_id, CASE m.grade WHEN 'exact' THEN 0 ELSE 1 END, m.list_key, m.employer_name
        """, ids):
        reg = regs.get(r["list_key"])
        if reg is None:
            continue
        current = bool(r["last_ok_at"]) and r["last_seen"] == r["last_ok_at"]
        row = {
            "list": r["list_key"],
            "program": reg.program,
            "jurisdiction": reg.jurisdiction,
            "community": reg.community,
            "name": r["employer_name"],
            "location": r["location"],
            "designated_on": r["designated_on"],
            "first_seen": (r["first_seen"] or "")[:10],
            "last_seen": (r["last_seen"] or "")[:10],
            "current": current,
            "url": reg.page_url,
            "grade": r["grade"],
            "basis": r["basis"],
        }
        if current and r["state"] == "snapshot":
            row["snapshot"] = {"list_date": r["list_date"], "loaded_on": (r["last_ok_at"] or "")[:10]}
        out.setdefault(r["employer_id"], []).append(row)
    return out
