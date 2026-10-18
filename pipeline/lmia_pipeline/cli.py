"""Command line: `python -m lmia_pipeline run`, `mark-synced` and `post-digest`."""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from pathlib import Path

from . import config, export, export_static, indicators, social, status
from .db import connect, hours_since, log_run
from .http import AbortRun, PoliteClient
from .sources import esdc, ircc, jobbank, registry_bc, registry_federal

log = logging.getLogger("lmia_pipeline")
STAGES = ["esdc", "ircc", "jobbank", "registry", "indicators", "export"]

# Job Bank is crawled once a day and no more. A re-run of a failed night, or a
# run started by hand, must not send a second pass; the guard is in the
# pipeline so no scheduler or operator mistake can bypass it without --force.
JOBBANK_MIN_HOURS = 20.0


def jobbank_allowed(conn: sqlite3.Connection, *, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "forced"
    hours = hours_since(conn, "jobbank_last_run")
    if hours is not None and hours < JOBBANK_MIN_HOURS:
        return False, f"last Job Bank pass was {hours:.1f} h ago; the daily pass has already happened"
    return True, "ok"


def load_fsa_centroids(conn: sqlite3.Connection, path: Path | None = None) -> int:
    src = path or (config.PACKAGE_DATA / "fsa_centroids.csv")
    if not src.exists():
        return 0
    n = 0
    with src.open(encoding="utf-8") as fh:
        rows = [line for line in fh if not line.startswith("#")]
    for row in csv.DictReader(rows):
        try:
            conn.execute(
                "INSERT OR REPLACE INTO fsa_centroids (fsa, province, lat, lon) VALUES (?, ?, ?, ?)",
                (row["fsa"].strip().upper(), row["province"].strip().upper(), float(row["lat"]), float(row["lon"])),
            )
            n += 1
        except (KeyError, ValueError):
            continue
    conn.commit()
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lmia_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="collect, merge, compute and export")
    for stage in STAGES:
        run.add_argument(f"--{stage}", action="store_true", help=f"run only the {stage} stage (combinable)")
    run.add_argument("--d1", action="store_true", help="also write D1 batches (the paid-plan path)")
    run.add_argument("--full", action="store_true", help="with --d1: export every row, with a reset")
    run.add_argument("--limit", type=int, default=None, help="Job Bank list pages per facet (dev runs)")
    run.add_argument("--force", action="store_true", help="crawl Job Bank even if a pass ran in the last 20 hours (dev only)")
    run.add_argument("--detail-budget", type=int, default=600, help="Job Bank posting pages per run")
    run.add_argument("--registry-budget", type=int, default=300, help="registry lookups per run")
    run.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")

    ms = sub.add_parser("mark-synced", help="record that the exported D1 batches were applied")
    ms.add_argument("--manifest", default=None)
    ms.add_argument("--db", default=None)

    pd = sub.add_parser("post-digest", help="post the daily digest of new postings to X")
    pd.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")
    pd.add_argument("--dry-run", action="store_true", help="print the post and send nothing")
    pd.add_argument("--link", action="store_true", help="include the site link (X bills a post with a link at thirteen times the rate)")
    pd.add_argument("--no-image", action="store_true", help="post the text without the card image")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    conn = connect(args.db)

    if args.command == "mark-synced":
        n = export.mark_synced(conn, Path(args.manifest) if args.manifest else None)
        log.info("recorded %d high-water marks", n)
        return 0

    if args.command == "post-digest":
        outcome = social.run(conn, dry_run=args.dry_run, link=args.link, image=not args.no_image)
        log.info("post-digest: %s", outcome)
        # The outcome is written for the workflow to record, and a failure exits 1
        # so the step shows red in the run; the workflow itself carries on, since
        # the post is optional and the data save is not.
        out = config.OUT_DIR / "social"
        out.mkdir(parents=True, exist_ok=True)
        (out / "last_outcome.txt").write_text(outcome + "\n", encoding="utf-8")
        return 1 if outcome in ("failed", "no credentials") else 0

    selected = [s for s in STAGES if getattr(args, s)]
    stages = selected or STAGES
    client = PoliteClient()
    failed = False

    log.info("fsa centroids loaded: %d", load_fsa_centroids(conn))

    if "esdc" in stages:
        try:
            log.info("esdc: %s", esdc.run(conn, client))
        except AbortRun as exc:
            failed = True
            log.error("esdc aborted: %s", exc)
            log_run(conn, "esdc", detail=str(exc), ok=False)
    if "ircc" in stages:
        try:
            log.info("ircc: %d new findings", ircc.run(conn, client))
        except Exception as exc:  # the list is small; a failure must not stop the night
            failed = True
            log.error("ircc failed: %s", exc)
            log_run(conn, "ircc", detail=str(exc), ok=False)
    if "jobbank" in stages:
        allowed, reason = jobbank_allowed(conn, force=args.force)
        if not allowed:
            log.info("jobbank skipped: %s", reason)
            log_run(conn, "jobbank", detail=f"skipped: {reason}")
            stages = [s for s in stages if s != "jobbank"]
    if "jobbank" in stages:
        try:
            log.info("jobbank: %s", jobbank.run(conn, client, limit=args.limit, detail_budget=args.detail_budget))
        except AbortRun as exc:
            failed = True
            log.error("jobbank aborted: %s", exc)
            log_run(conn, "jobbank", detail=str(exc), ok=False)
    if "registry" in stages:
        try:
            log.info("registry bc: %d matches", registry_bc.run(conn, client, budget=args.registry_budget))
        except AbortRun as exc:
            failed = True
            log.error("registry aborted: %s", exc)
            log_run(conn, "registry", detail=str(exc), ok=False)
        try:
            log.info("registry federal: %d matches", registry_federal.run(conn, client))
        except Exception as exc:  # a 260 MB download can fail; the rest of the night still runs
            failed = True
            log.error("registry federal failed: %s", exc)
            log_run(conn, "registry_federal", detail=str(exc), ok=False)
    if "indicators" in stages or "export" in stages or not selected:
        log.info("indicators changed: %d", indicators.compute(conn))
        log.info("employers updated: %d", status.recompute(conn))
    if "export" in stages:
        log.info("csv rows: %s", export.export_csv(conn))
        log.info("mirror files: %d", export.export_mirror(conn))
        log.info("static files: %s", export_static.export_static(conn))
        if args.d1:
            manifest = export.export_d1(conn, full=args.full)
            log.info("d1 files: %d rows: %s", len(manifest["files"]), manifest["row_counts"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
