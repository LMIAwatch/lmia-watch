"""Load a designated-employer list by hand into the site's private R2 bucket.

For a list whose server does not answer the nightly run but opens from an
ordinary machine (Register.snapshot in lmia_pipeline/sources/registers.py).
The rows are read here by the parser the nightly run uses
(registers.parse_body), names that read as a person are left out (project
rule 3), and two objects go to R2: registers/<key>.csv (name, location,
designated_on) and registers/<key>.json (the file's address, ETag,
Last-Modified, size and SHA-256, the list's own date, the day it was loaded,
loaded_by "hand", the parser and the counts). The nightly run reads them
with its own token, compares the published file with the record, and raises
an item needing attention when they differ; loading the new edition with
this script clears it.

Nothing is written to the repository: the site does not republish the
lists, and the repository is public. Never commit the PDF or the objects.

Uploading uses the deploy token, CLOUDFLARE_API_TOKEN and
CLOUDFLARE_ACCOUNT_ID in the environment (R2 edit on the project account),
and the bucket in BUCKET (default lmia-watch-data). Run it only from the
project's own machine, never from a personal one.

Usage:
  python scripts/load_register_snapshot.py KEY --from PATH --etag ETAG --last-modified DATE [--url URL]
      read a file saved by hand; give the headers the server sent with it
      (curl -sI URL shows them) and the address it came from when it differs
      from the registered one
  python scripts/load_register_snapshot.py KEY
      download the list's current file (its link on the list's page, else the
      registered address) and record the response's headers
Options:
  --loaded-on DATE   the day to record as the load date (default: today, UTC)
  --list-date DATE   the list's date when its text does not state one
  --out DIR          write the two objects to DIR instead of uploading them
                     (a folder outside the repository)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from lmia_pipeline import config, resilience
from lmia_pipeline.http import decode_text
from lmia_pipeline.sources import registers as R

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None, *, store: resilience.R2Rest | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("key", help="the list's key in registers.REGISTERS, e.g. aip_ns")
    parser.add_argument("--from", dest="source", help="a saved copy of the list's file")
    parser.add_argument("--url", help="the address the saved copy came from (default: the registered address)")
    parser.add_argument("--etag", help="the ETag the server sent with the file")
    parser.add_argument("--last-modified", help="the Last-Modified the server sent with the file")
    parser.add_argument("--loaded-on", help="the load date to record (default today, UTC)")
    parser.add_argument("--list-date", help="the list's date, when its text does not state one")
    parser.add_argument("--out", default=None, help="write the objects to this folder instead of uploading them")
    args = parser.parse_args(argv)
    reg = {r.key: r for r in R.REGISTERS}.get(args.key)
    if reg is None or not reg.snapshot:
        print(f"no list with the key {args.key!r} takes a copy loaded by hand (Register.snapshot)", file=sys.stderr)
        return 1
    out = Path(args.out).resolve() if args.out else None
    if out is not None and (out == REPO_ROOT or REPO_ROOT in out.parents):
        print("--out must be a folder outside the repository: the copy is never committed", file=sys.stderr)
        return 1
    if out is None and store is None:
        store = resilience.r2_from_env()
        if store is None:
            print("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are not set; use --out to write the objects locally",
                  file=sys.stderr)
            return 1
    if args.source:
        raw = Path(args.source).read_bytes()
        url, etag, modified = args.url or reg.source_url, args.etag, args.last_modified
        if not (etag and modified):
            print("warning: without --etag and --last-modified the nightly check compares the size only",
                  file=sys.stderr)
    else:
        headers = {"User-Agent": config.USER_AGENT}
        url = reg.source_url
        if reg.link_pattern:
            page = requests.get(reg.page_url, headers=headers, timeout=60)
            page.raise_for_status()
            url = R.find_pdf_link(reg, decode_text(page.content)) or url
        resp = requests.get(url, headers=headers, timeout=120)
        resp.raise_for_status()
        raw, etag, modified = resp.content, resp.headers.get("ETag"), resp.headers.get("Last-Modified")
    try:
        rows, list_date = R.parse_body(reg, raw)
    except (R.Unreadable, R.ParseProblem) as exc:
        print(f"the file does not read as the list: {exc}", file=sys.stderr)
        return 1
    list_date = args.list_date or list_date
    if not list_date:
        # The site names the list's date wherever the copy's rows are shown.
        print("the list states no date: give it with --list-date", file=sys.stderr)
        return 1
    loaded_on = args.loaded_on or datetime.now(timezone.utc).date().isoformat()
    csv_bytes, meta_bytes, meta = R.snapshot_objects(
        reg, rows, source_url=url, etag=etag, last_modified=modified, size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(), list_date=list_date, loaded_on=loaded_on)
    # The objects must read back as the nightly run reads them.
    R.parse_snapshot(reg.key, csv_bytes, meta_bytes)
    csv_key, meta_key = R.snapshot_keys(reg.key)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        targets = [out / Path(csv_key).name, out / Path(meta_key).name]
        targets[0].write_bytes(csv_bytes)
        targets[1].write_bytes(meta_bytes)
        where = f"written to {targets[0]} and {targets[1]} (upload them as {csv_key} and {meta_key})"
    else:
        assert store is not None
        # The rows first: if the record's upload then fails, the old record still
        # differs from the published file, so the item stays open until both are in.
        store.upload(csv_key, csv_bytes, "text/csv; charset=utf-8")
        store.upload(meta_key, meta_bytes, "application/json")
        back = R.read_snapshot(reg, store)
        if back.snap is None or len(back.snap.rows) != meta["rows"]:
            print(f"uploaded, but the copy does not read back from R2 ({back.outcome}: {back.detail})", file=sys.stderr)
            return 1
        where = f"uploaded to R2 as {csv_key} and {meta_key}"
    print(f"{meta['rows_read']} rows read, {meta['rows_left_out_as_person']} left out as a person, "
          f"{meta['rows']} kept; list dated {list_date}, loaded {loaded_on}; {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
