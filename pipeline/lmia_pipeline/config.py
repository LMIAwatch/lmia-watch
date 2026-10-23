"""Paths, hosts and identifiers shared by every stage."""

from __future__ import annotations

import os
from pathlib import Path

from . import __version__

# pipeline/lmia_pipeline/config.py -> repo root is two levels up from the package
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = RAW_DIR / "cache"
OUT_DIR = DATA_DIR / "out"
DEFAULT_DB = DATA_DIR / "lmia.sqlite"
SCHEMA_PATH = REPO_ROOT / "pipeline" / "schema.sql"
# The hosted search database (D1 lmia-watch-search) has its own schema; see search_db.py.
SEARCH_SCHEMA_PATH = REPO_ROOT / "pipeline" / "search_schema.sql"
PACKAGE_DATA = Path(__file__).resolve().parent / "data"

# The contact in the user agent is a URL (the site's corrections form), so the
# project needs no mailbox; set both from the workflow's variables.
SITE_URL = os.environ.get("LMIAWATCH_SITE_URL", "https://lmiawatch.example")
CONTACT = os.environ.get("LMIAWATCH_CONTACT", f"{SITE_URL}/corrections")
USER_AGENT = f"LMIAWatch/{__version__} (+{SITE_URL}; {CONTACT})"

# robots.txt on jobbank.gc.ca sets Crawl-delay: 5. Everything else gets one
# request per second, which is well under what the open-data hosts expect.
# Job Bank's robots.txt asks for 5 seconds between requests. The crawler waits
# 8: from a cloud runner the site's firewall stopped answering partway through
# a sweep at the published pace (2026-10-20), and a slower one asks less of it.
CRAWL_DELAY: dict[str, float] = {"www.jobbank.gc.ca": 8.0, "jobbank.gc.ca": 8.0}
# Hosts where a refused or timed-out connection means the host has stopped
# taking requests from this address: each request is tried twice, and this
# many requests in a row failing that way end the run for the host (AbortRun)
# instead of retrying for twenty minutes.
CONNECT_FAIL_FAST: dict[str, int] = {"www.jobbank.gc.ca": 2, "jobbank.gc.ca": 2}
DEFAULT_DELAY = 1.0

JOBBANK_BASE = "https://www.jobbank.gc.ca"
CKAN_PACKAGE_SHOW = "https://open.canada.ca/data/api/action/package_show?id={dataset}"
ESDC_DATASETS = {
    "positive": "90fed587-1364-4f33-a9ee-208181dc0b97",
    "negative": "f82f66f2-a22b-4511-bccf-e1d74db39ae5",
}
IRCC_NONCOMPLIANT_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "work-canada/employers-non-compliant.html"
)
ORGBOOK_SEARCH = "https://orgbook.gov.bc.ca/api/v4/search/topic"
