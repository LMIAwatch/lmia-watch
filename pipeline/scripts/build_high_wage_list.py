"""Build lmia_pipeline/data/high_wage_nocs.json, IRCC's list of high-wage occupations for Express Entry.

Source: "High-wage occupations and how we assess them", Immigration, Refugees
and Citizenship Canada (canada.ca terms of use):
https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/high-wage.html
The page lists NOC 2021 unit groups in three HTML tables, one per tier (100,
70 and 50 points), and nothing else machine-readable. The parser is the one
the nightly check uses (lmia_pipeline.sources.high_wage.parse_page), so a page
this script reads is a page the check reads the same way.

The nightly run adopts a changed list by itself (a notice, never an item
needing attention); the committed file is only the fallback before any
edition is stored, so refreshing it is optional: look at the diff of the
file this writes and commit it.

Usage: python scripts/build_high_wage_list.py [--from PATH] [--out PATH] [--read-on YYYY-MM-DD]
  --from PATH      read a saved copy of the page instead of downloading it
  --read-on DATE   the date to record as the day the list was read (default: today, UTC)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from lmia_pipeline import config
from lmia_pipeline.http import decode_text
from lmia_pipeline.sources.high_wage import LIST_PATH, SOURCE_URL, build_document, parse_page, write_document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", help="a saved copy of the IRCC page to read instead of downloading")
    parser.add_argument("--out", default=str(LIST_PATH))
    parser.add_argument("--read-on", default=None, help="the read date to record (default today, UTC)")
    args = parser.parse_args(argv)
    if args.source:
        html = decode_text(Path(args.source).read_bytes())
    else:
        resp = requests.get(SOURCE_URL, headers={"User-Agent": config.USER_AGENT}, timeout=60)
        resp.raise_for_status()
        html = decode_text(resp.content)
    try:
        occupations, modified = parse_page(html)
    except ValueError as exc:
        print(f"the page does not read as the list: {exc}", file=sys.stderr)
        return 1
    read_on = args.read_on or datetime.now(timezone.utc).date().isoformat()
    doc = build_document(occupations, modified, read_on)
    write_document(doc, Path(args.out))
    tiers = ", ".join(f"{t['count']} at {t['points']} points" for t in doc["tiers"])
    print(f"{doc['count']} occupations ({tiers}); page modified {modified or 'unknown'}; written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
