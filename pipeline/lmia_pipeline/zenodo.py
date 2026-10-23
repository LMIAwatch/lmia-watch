"""Citable releases: one Zenodo record whose versions follow the ESDC quarters.

When a new ESDC quarter has been loaded (meta esdc_latest_period differs from
the quarter last deposited), or no record exists yet, the nightly run makes a
new version of one concept record, uploads the Open Government Licence files,
sets the metadata, and publishes. Zenodo mints a DOI for each version and one
concept DOI for the series; both go into meta, and export_static copies the
production ones into stats.json for the "How to cite" block.

Why a direct deposit and not Zenodo's GitHub integration: that archives the
repository's source at a release, not the data files, and stops working once
the repository is private.

Which files: only those derived from ESDC's lists alone, which are published
under the Open Government Licence, Canada. employers.csv and indicators.csv
mix in Job Bank observations, IRCC findings and registry matches (the Quebec
register is CC BY-NC-SA), and pending_observations.csv and findings.csv are
Job Bank and IRCC material reproduced under canada.ca's terms, so none of
those four is deposited.

Why the sandbox keys: ZENODO_SANDBOX=true sends everything to
sandbox.zenodo.org, whose test DOIs do not resolve. Its record ids live under
their own meta keys, so a sandbox trial never becomes the production record
and never reaches the site.

A published version cannot be deleted, only superseded by the next one, so
nothing is published until every file has uploaded and the metadata is set.
A failure on the way discards the draft and reports "failed"; the quarter is
not recorded, so the next night tries again.

Meta can miss a version Zenodo did publish: a publish whose answer was lost
(a timeout or a 5xx after the publish went through, when the discard is
refused), or a deposit followed by a failed database save, after which the
next run restores the night before's database. So before any draft is made
the run asks Zenodo what is already published. With a record in meta it
reads the newest version of that series; with none it lists the token's
depositions, all versions, and keeps the published ones with this TITLE. A
published version whose metadata version is the quarter is adopted: its ids
and DOIs go into meta as a fresh deposit's would, and the outcome is
"already deposited". Without meta, a published version of another quarter
is the record the new version builds on, so a lost database never starts a
second concept record. Drafts are never adopted; a leftover draft of a new
version is the one Zenodo hands back for the next version. When Zenodo
cannot answer, nothing is deposited that night and the outcome is "failed",
because a deposit made without the check could publish the quarter twice.
Never raises.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config
from .db import get_meta, set_meta

log = logging.getLogger(__name__)

PRODUCTION_API = "https://zenodo.org/api"
SANDBOX_API = "https://sandbox.zenodo.org/api"
DOI_URL = "https://doi.org/"
TOKEN_ENV = "ZENODO_TOKEN"
SANDBOX_ENV = "ZENODO_SANDBOX"
# Zenodo's licence vocabulary uses lower-case SPDX identifiers.
LICENSE = "ogl-canada-2.0"
TITLE = "LMIA Watch: ESDC positive and negative LMIA employer lists, derived files"
# The files deposited, in the order the description lists them; the first must
# hold the quarter being deposited.
FILES: dict[str, str] = {
    "approved_quarterly.csv": "every row of ESDC's positive LMIA employer lists, one row per employer, location and occupation per period, with the source file's resource id",
    "refused_quarterly.csv": "every row of ESDC's negative LMIA employer lists, in the same layout",
    "esdc_resources.csv": "the ESDC source files loaded: period, title, download address, publication date, SHA-256 checksum, size and rows loaded",
}
README = "README.txt"
ESDC_SOURCES = [
    "https://open.canada.ca/data/en/dataset/90fed587-1364-4f33-a9ee-208181dc0b97",
    "https://open.canada.ca/data/en/dataset/f82f66f2-a22b-4511-bccf-e1d74db39ae5",
]
KEYWORDS = [
    "Labour Market Impact Assessment", "LMIA", "temporary foreign workers", "Temporary Foreign Worker Program",
    "employers", "Canada", "ESDC", "open government data",
]
UPLOAD_TIMEOUT = (30, 900)
TIMEOUT = 60
# The deposition listing, read when meta holds no record. The project's
# account holds a handful of depositions, so a listing longer than this is an
# answer that cannot be trusted, and the check fails rather than deposit.
LIST_PAGE_SIZE = 100
LIST_MAX_PAGES = 50


def meta_keys(sandbox: bool) -> dict[str, str]:
    prefix = "zenodo_sandbox_" if sandbox else "zenodo_"
    return {name: prefix + name for name in ("period", "record_id", "concept_recid", "doi", "concept_doi", "published")}


def citation_from_meta(meta: Mapping[str, str | None]) -> dict | None:
    """What stats.json carries for the "How to cite" block: the production
    record only, and nothing until it has a concept DOI."""
    k = meta_keys(False)
    concept = meta.get(k["concept_doi"])
    if not concept:
        return None
    return {
        "title": TITLE,
        "concept_doi": concept,
        "doi": meta.get(k["doi"]) or None,
        "version": meta.get(k["period"]) or None,
        "published": meta.get(k["published"]) or None,
    }


# -- the files ----------------------------------------------------------------


@dataclass
class DepositFile:
    name: str
    path: Path
    rows: int
    bytes: int
    sha256: str
    columns: list[str]


def prepare(csv_dir: Path, period: str) -> tuple[list[DepositFile], list[str]]:
    """Read every file once for its row count, checksum and header. Problems
    are returned, not raised: a missing file, an empty one, or a positive-list
    file that does not hold the quarter about to be deposited."""
    files: list[DepositFile] = []
    problems: list[str] = []
    for i, name in enumerate(FILES):
        path = csv_dir / name
        if not path.is_file():
            problems.append(f"{name} is missing from {csv_dir}")
            continue
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        rows = 0
        holds_period = False
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            columns = next(reader, [])
            at = columns.index("period") if "period" in columns else None
            for row in reader:
                rows += 1
                if i == 0 and at is not None and not holds_period and at < len(row) and row[at] == period:
                    holds_period = True
        if not rows:
            problems.append(f"{name} has no rows")
        if i == 0 and rows and not holds_period:
            problems.append(f"{name} holds no row for {period}, so it predates the quarter")
        files.append(DepositFile(name, path, rows, path.stat().st_size, digest.hexdigest(), columns))
    return files, problems


def readme(files: list[DepositFile], period: str) -> str:
    site = config.SITE_URL.rstrip("/")
    lines = [
        TITLE,
        f"Version {period}",
        "",
        f"Derived by LMIA Watch ({site}) from Employment and Social Development Canada's quarterly",
        "lists of employers that received a positive or a negative Labour Market Impact Assessment.",
        f"This version holds every list published up to {period}. Each row is one row of an ESDC",
        "file, with the province as a two-letter code, the city and the postal code (A1A 1A1)",
        "parsed from ESDC's address field, an employer id added by LMIA Watch (a hash of the",
        "normalized name and province) and the resource id of the ESDC file the row came from.",
        "",
        "Sources:",
        *(f"  {url}" for url in ESDC_SOURCES),
        f"Method: {site}/methodology",
        "",
        "Licence: Open Government Licence - Canada",
        "  https://open.canada.ca/en/open-government-licence-canada",
        "Contains information licensed under the Open Government Licence - Canada.",
        "",
        "Job Bank observations, IRCC findings and business registry details shown on the site",
        "are not in this deposit, because they are published under different terms.",
        "",
        "Files:",
    ]
    for f in files:
        lines.append(f"  {f.name}: {FILES[f.name]}.")
        lines.append(f"    {f.rows:,} rows, {f.bytes:,} bytes, SHA-256 {f.sha256}")
        lines.append(f"    Columns: {', '.join(f.columns)}")
    lines.append("")
    return "\n".join(lines)


def metadata(files: list[DepositFile], period: str, today: str) -> dict:
    site = config.SITE_URL.rstrip("/")
    items = "".join(f"<li>{f.name}: {FILES[f.name]} ({f.rows:,} rows).</li>" for f in files)
    description = (
        "<p>Derived files from Employment and Social Development Canada's quarterly lists of employers that "
        "received a positive or a negative Labour Market Impact Assessment (LMIA), as loaded by "
        f'<a href="{site}">LMIA Watch</a>. This version holds every list published up to {period}.</p>'
        f"<ul>{items}</ul>"
        f"<p>{README} lists each file's columns, row count and SHA-256 checksum. The method is described at "
        f'<a href="{site}/methodology">{site}/methodology</a>.</p>'
        "<p>Job Bank observations, IRCC findings and business registry details shown on the site are not in this "
        "deposit, because they are published under different terms.</p>"
        "<p>Contains information licensed under the Open Government Licence - Canada.</p>"
    )
    return {
        "upload_type": "dataset",
        "title": TITLE,
        "creators": [{"name": "LMIA Watch"}],
        "description": description,
        "access_right": "open",
        "license": LICENSE,
        "keywords": KEYWORDS,
        "version": period,
        "publication_date": today,
        "language": "eng",
        "related_identifiers": [
            {"identifier": site, "relation": "isSupplementTo"},
            {"identifier": f"{site}/methodology", "relation": "isDocumentedBy"},
            *({"identifier": url, "relation": "isDerivedFrom"} for url in ESDC_SOURCES),
        ],
    }


# -- the API ------------------------------------------------------------------


class DepositError(Exception):
    pass


def _body(resp: Any) -> str:
    try:
        return re.sub(r"\s+", " ", str(resp.text))[:300]
    except Exception:
        return "(no body)"


def _latest_id(dep: Mapping) -> str | None:
    """The record id in links.latest, which points at the newest published
    version of the deposition's series; None when Zenodo does not say."""
    links = dep.get("links")
    m = re.search(r"/records/(\d+)$", str((links if isinstance(links, dict) else {}).get("latest") or ""))
    return m.group(1) if m else None


def _published(dep: Mapping) -> bool:
    # submitted is Zenodo's "has been published" flag. state is "done", or
    # "inprogress" while the owner edits a published version on the web page;
    # either way the version and its DOI exist.
    return dep.get("submitted") is True and dep.get("state") in ("done", "inprogress")


def _holds(dep: Mapping, period: str) -> bool:
    """A published version whose metadata version is the quarter."""
    meta = dep.get("metadata")
    return _published(dep) and isinstance(meta, dict) and str(meta.get("version") or "") == period


def _is_ours(dep: Any) -> bool:
    """A published version of this series, as the deposition listing shows it."""
    if not isinstance(dep, dict) or not str(dep.get("id") or "").isdigit():
        return False
    meta = dep.get("metadata")
    return _published(dep) and isinstance(meta, dict) and meta.get("title") == TITLE


class Client:
    """The legacy deposit API, which Zenodo still serves for scripted uploads.
    The token goes in a header, so no URL logged here carries it, and only to
    the API host itself: a link the API returns that points elsewhere is refused."""

    def __init__(self, base: str, token: str, session: Any) -> None:
        self.base = base.rstrip("/")
        self.origin = re.match(r"https://[^/]+", self.base).group(0)  # type: ignore[union-attr]
        self.http = session
        self.headers = {"Authorization": f"Bearer {token}", "User-Agent": config.USER_AGENT}

    def __repr__(self) -> str:  # keep the token out of any log line or traceback
        return f"Client({self.base})"

    def _url(self, url: str) -> str:
        if not url.startswith(self.origin + "/"):
            raise DepositError(f"the API returned a link outside {self.origin}")
        return url

    def _call(self, method: str, url: str, *, ok: tuple[int, ...] = (200, 201, 202), json_body: Any = None,
              data: Any = None, timeout: Any = TIMEOUT, what: str = "") -> Any:
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/octet-stream"
        try:
            resp = self.http.request(method, self._url(url), json=json_body, data=data, headers=headers, timeout=timeout)
        except DepositError:
            raise
        except Exception as exc:
            raise DepositError(f"{what}: request failed ({type(exc).__name__}): {str(exc)[:200]}") from None
        status = int(getattr(resp, "status_code", 0) or 0)
        if status not in ok:
            raise DepositError(f"{what}: HTTP {status}: {_body(resp)}")
        if status == 204:
            return None
        try:
            return resp.json()
        except Exception:
            return None

    def deposition(self, dep_id: str) -> dict:
        body = self._call("GET", f"{self.base}/deposit/depositions/{dep_id}", what="read the deposition")
        if not isinstance(body, dict):
            raise DepositError("read the deposition: no JSON body")
        return body

    def create(self) -> dict:
        body = self._call("POST", f"{self.base}/deposit/depositions", json_body={}, what="create the record")
        if not isinstance(body, dict) or "id" not in body:
            raise DepositError("create the record: no deposition in the answer")
        return body

    def latest(self, record_id: str) -> str:
        """The newest published version of the record's series, which differs
        from the one recorded when a version was published by hand on the web
        page. The recorded id when Zenodo does not say."""
        try:
            return _latest_id(self.deposition(record_id)) or record_id
        except DepositError as exc:
            log.warning("zenodo: %s; versioning from record %s", exc, record_id)
            return record_id

    def newest(self, record_id: str) -> dict:
        """The newest published version of the record's series, read in full.
        Unlike latest, a failure raises: the answer decides whether tonight's
        quarter is deposited at all. Only the record id is taken from the link,
        so the request still goes to the API host."""
        dep = self.deposition(record_id)
        latest = _latest_id(dep)
        return self.deposition(latest) if latest and latest != str(dep.get("id")) else dep

    def depositions(self) -> list[dict]:
        """Every deposition the token can see, every version of each, page by page."""
        found: list[dict] = []
        for page in range(1, LIST_MAX_PAGES + 1):
            body = self._call("GET", f"{self.base}/deposit/depositions?size={LIST_PAGE_SIZE}&page={page}"
                              "&all_versions=true", what="list the depositions")
            if not isinstance(body, list):
                raise DepositError("list the depositions: the answer is not a list")
            found.extend(d for d in body if isinstance(d, dict))
            if len(body) < LIST_PAGE_SIZE:
                return found
        raise DepositError(f"list the depositions: still more after {LIST_MAX_PAGES} pages")

    def new_version(self, record_id: str) -> dict:
        record_id = self.latest(record_id)
        # The answer is the published version, not the draft: the draft is at links.latest_draft.
        body = self._call("POST", f"{self.base}/deposit/depositions/{record_id}/actions/newversion",
                          what="start a new version")
        draft = ((body or {}).get("links") or {}).get("latest_draft") if isinstance(body, dict) else None
        if not draft:
            raise DepositError("start a new version: no draft link in the answer")
        found = self._call("GET", draft, what="read the new draft")
        if not isinstance(found, dict) or "id" not in found:
            raise DepositError("read the new draft: no deposition in the answer")
        return found

    def clear_files(self, dep_id: str) -> None:
        """A new version starts with the previous version's files; remove them so
        the version holds exactly tonight's set."""
        listing = self._call("GET", f"{self.base}/deposit/depositions/{dep_id}/files", what="list the draft's files")
        for f in listing if isinstance(listing, list) else []:
            if isinstance(f, dict) and f.get("id"):
                self._call("DELETE", f"{self.base}/deposit/depositions/{dep_id}/files/{f['id']}", ok=(200, 204),
                           what=f"remove {f.get('filename', 'a file')} from the draft")

    def upload(self, bucket: str, name: str, payload: Any) -> None:
        self._call("PUT", f"{bucket.rstrip('/')}/{name}", data=payload, timeout=UPLOAD_TIMEOUT, ok=(200, 201),
                   what=f"upload {name}")

    def set_metadata(self, dep_id: str, meta: dict) -> None:
        self._call("PUT", f"{self.base}/deposit/depositions/{dep_id}", json_body={"metadata": meta},
                   what="set the metadata")

    def publish(self, dep_id: str) -> dict:
        body = self._call("POST", f"{self.base}/deposit/depositions/{dep_id}/actions/publish", what="publish")
        return body if isinstance(body, dict) else {}

    def discard(self, dep_id: str) -> None:
        try:
            self._call("DELETE", f"{self.base}/deposit/depositions/{dep_id}", ok=(200, 201, 204),
                       what="discard the draft")
        except DepositError as exc:
            log.warning("zenodo: %s; the next run reuses or replaces it", exc)


# -- the run ------------------------------------------------------------------


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def check(client: Client, record_id: str | None, period: str) -> tuple[dict | None, str | None]:
    """What Zenodo already holds, asked before any draft is made. Returns the
    published version that holds the period, when one does, and the record
    the new version builds on (None to create the first record). Raises
    DepositError when Zenodo cannot answer."""
    if record_id:
        newest = client.newest(record_id)
        return (newest if _holds(newest, period) else None), record_id
    # No record in meta: a first deposit, or a database restored from before
    # one. The listing shows every version, so a version of the quarter is
    # found even when a newer one exists; the newest wins any tie.
    ours = sorted((d for d in client.depositions() if _is_ours(d)), key=lambda d: int(d["id"]), reverse=True)
    held = next((d for d in ours if _holds(d, period)), None)
    return held, (str(ours[0]["id"]) if ours else None)


def _record(conn: sqlite3.Connection, keys: dict[str, str], period: str, dep: Mapping, fallback_id: str,
            published_on: str) -> None:
    set_meta(conn, keys["period"], period)
    set_meta(conn, keys["record_id"], str(dep.get("record_id") or dep.get("id") or fallback_id))
    set_meta(conn, keys["published"], published_on)
    for key, field in (("doi", "doi"), ("concept_doi", "conceptdoi"), ("concept_recid", "conceptrecid")):
        value = dep.get(field)
        if value:
            set_meta(conn, keys[key], str(value))
    conn.commit()


def run(
    conn: sqlite3.Connection,
    csv_dir: Path | None = None,
    *,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    session: Any | None = None,
    echo: Callable[[str], None] = print,
    now: datetime | None = None,
) -> str:
    """Deposit tonight's files when a new quarter is loaded. Returns the outcome,
    one of "deposited", "already deposited" (Zenodo held the quarter and meta
    now records it), "no new quarter", "no data", "no token", "dry run" and
    "failed"; never raises."""
    try:
        return _run(conn, csv_dir or (config.OUT_DIR / "csv"), dry_run=dry_run, env=env, session=session,
                    echo=echo, now=now)
    except Exception as exc:
        log.error("zenodo: deposit failed (%s): %s", type(exc).__name__, str(exc)[:200])
        return "failed"


def _run(conn: sqlite3.Connection, csv_dir: Path, *, dry_run: bool, env: Mapping[str, str] | None,
         session: Any | None, echo: Callable[[str], None], now: datetime | None) -> str:
    source = os.environ if env is None else env
    sandbox = _truthy(source.get(SANDBOX_ENV))
    where = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    keys = meta_keys(sandbox)
    period = get_meta(conn, "esdc_latest_period")
    if not period:
        log.info("zenodo: no ESDC quarter loaded yet; nothing to deposit")
        return "no data"
    record_id = get_meta(conn, keys["record_id"])
    if record_id and get_meta(conn, keys["period"]) == period:
        log.info("zenodo: %s is already deposited on %s; nothing to do", period, where)
        return "no new quarter"

    files, problems = prepare(csv_dir, period)
    if problems:
        log.error("zenodo: not deposited: %s", "; ".join(problems))
        return "failed"
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    meta = metadata(files, period, today)
    notes = readme(files, period).encode("utf-8")

    if dry_run:
        action = f"a new version of record {record_id}" if record_id else "a new record"
        echo(f"Would deposit {period} on {where} as {action}:")
        for f in files:
            echo(f"  {f.name}: {f.rows:,} rows, {f.bytes:,} bytes")
        echo(f"  {README}: {len(notes):,} bytes")
        return "dry run"

    token = (source.get(TOKEN_ENV) or "").strip()
    if not token:
        log.info("zenodo: %s is not set; nothing deposited", TOKEN_ENV)
        return "no token"
    if session is None:
        try:
            import requests
        except ImportError:
            log.error("zenodo: requests is not installed; nothing deposited")
            return "failed"
        session = requests.Session()
    client = Client(SANDBOX_API if sandbox else PRODUCTION_API, token, session)

    # Meta can miss a version Zenodo published (a lost publish answer, a lost
    # database save), and a second version of a quarter is permanent, so
    # Zenodo's own record decides before any draft is made.
    try:
        held, base = check(client, record_id, period)
    except DepositError as exc:
        log.error("zenodo: %s not deposited on %s: what is already published could not be checked: %s",
                  period, where, exc)
        return "failed"
    if held is not None:
        published_on = str((held.get("metadata") or {}).get("publication_date") or today)
        _record(conn, keys, period, held, str(held.get("id")), published_on)
        log.info("zenodo: %s is already published on %s as record %s (%s%s); recorded it, nothing deposited",
                 period, where, get_meta(conn, keys["record_id"]), DOI_URL, held.get("doi") or "?")
        return "already deposited"
    if base and base != record_id:
        log.info("zenodo: no record in meta; record %s on %s carries this title, so %s goes up as a new "
                 "version of its series", base, where, period)
    record_id = base

    draft_id: str | None = None
    try:
        draft = client.new_version(record_id) if record_id else client.create()
        draft_id = str(draft["id"])
        bucket = (draft.get("links") or {}).get("bucket")
        if not bucket:
            raise DepositError("the draft has no file bucket link")
        if record_id:
            client.clear_files(draft_id)
        for f in files:
            with f.path.open("rb") as fh:
                client.upload(bucket, f.name, fh)
        client.upload(bucket, README, notes)
        client.set_metadata(draft_id, meta)
        log.info("zenodo: publishing %s on %s (draft %s)", period, where, draft_id)
        published = client.publish(draft_id)
    except DepositError as exc:
        log.error("zenodo: %s not deposited on %s: %s", period, where, exc)
        if draft_id:
            client.discard(draft_id)
        return "failed"

    # Published, so record it even if the answer is thin: a second deposit of
    # the same quarter would be a second permanent version.
    if not published.get("doi"):
        try:
            published = client.deposition(draft_id)
        except DepositError as exc:
            log.warning("zenodo: published, but %s", exc)
    _record(conn, keys, period, published, str(draft_id), today)
    doi = published.get("doi")
    if doi:
        log.info("zenodo: deposited %s on %s as %s%s (all versions: %s%s)", period, where, DOI_URL, doi, DOI_URL,
                 published.get("conceptdoi") or "?")
    else:
        log.warning("zenodo: deposited %s on %s as record %s; the answer carried no DOI", period, where,
                    get_meta(conn, keys["record_id"]))
    return "deposited"
