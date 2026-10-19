"""Command line: `python -m lmia_pipeline run`, `mark-synced`, `post-digest`, `post-bluesky` and `deposit-zenodo`."""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from . import bluesky, config, export, export_static, indicators, migrate, social, status, zenodo
from .db import connect, hours_since, log_run
from .http import PoliteClient
from .sources import esdc, geography, ircc, jobbank, lfs, registry_bc, registry_federal, registry_quebec, wages
from .sources import vacancies

log = logging.getLogger("lmia_pipeline")
STAGES = ["esdc", "ircc", "jobbank", "registry", "wages", "lfs", "vacancies", "geography", "indicators", "export"]

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
    run.add_argument("--registry-budget", type=int, default=registry_bc.DEFAULT_BUDGET,
                     help="OrgBook lookups per run (also capped at 15 minutes)")
    run.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")

    ms = sub.add_parser("mark-synced", help="record that the exported D1 batches were applied")
    ms.add_argument("--manifest", default=None)
    ms.add_argument("--db", default=None)

    pd = sub.add_parser("post-digest", help="post the daily digest of new postings to X")
    pd.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")
    pd.add_argument("--dry-run", action="store_true", help="print the post and send nothing")
    pd.add_argument("--link", action="store_true", help="include the site link (X bills a post with a link at thirteen times the rate)")
    pd.add_argument("--no-image", action="store_true", help="post the text without the card image")

    pb = sub.add_parser("post-bluesky", help="post the daily digest of new postings to Bluesky")
    pb.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")
    pb.add_argument("--dry-run", action="store_true", help="print the post and send nothing")
    pb.add_argument("--no-image", action="store_true", help="post the text without the card image")

    dz = sub.add_parser("deposit-zenodo", help="deposit the OGL files on Zenodo when a new ESDC quarter is loaded")
    dz.add_argument("--db", default=None, help="SQLite path (default data/lmia.sqlite)")
    dz.add_argument("--csv-dir", default=None, help="the CSV export (default data/out/csv)")
    dz.add_argument("--dry-run", action="store_true", help="check the files and print what would be deposited")
    return parser


def _outcome_file(folder: str, name: str, outcome: str) -> None:
    out = config.OUT_DIR / folder
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(outcome + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    # Every stage reports its own failure; this catches what is left (a
    # database that will not open, a full disk) so the workflow always gets an
    # exit code and a log line rather than a traceback from the interpreter.
    try:
        return _main(args)
    except Exception:
        log.exception("%s stopped", args.command)
        return 2


def _main(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        return _command(conn, args)
    finally:
        # Closing folds the write-ahead log into the database file, which is
        # the file the workflow compresses and saves.
        conn.close()


def _command(conn: sqlite3.Connection, args: argparse.Namespace) -> int:

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

    # Same shape as post-digest. "failed" is written first and replaced by the
    # real outcome at the end, so a step the workflow kills part way (its time
    # limit) still reads as failed in the run status.
    if args.command == "post-bluesky":
        _outcome_file("social", "bluesky_outcome.txt", "failed")
        outcome = bluesky.run(conn, dry_run=args.dry_run, image=not args.no_image)
        log.info("post-bluesky: %s", outcome)
        _outcome_file("social", "bluesky_outcome.txt", outcome)
        return 1 if outcome in ("failed", "no credentials") else 0

    if args.command == "deposit-zenodo":
        _outcome_file("zenodo", "last_outcome.txt", "failed")
        outcome = zenodo.run(conn, Path(args.csv_dir) if args.csv_dir else None, dry_run=args.dry_run)
        log.info("deposit-zenodo: %s", outcome)
        _outcome_file("zenodo", "last_outcome.txt", outcome)
        return 1 if outcome == "failed" else 0

    selected = [s for s in STAGES if getattr(args, s)]
    stages = selected or STAGES
    client = PoliteClient()
    ok = True

    # Employer ids are derived from normalized names; when the normalization
    # changed since this database was built, re-derive them once before any
    # stage writes under the new rules.
    report = migrate.ensure_current(conn)
    if report is not None:
        log.info("employer ids re-derived: %s", report)

    log.info("fsa centroids loaded: %d", load_fsa_centroids(conn))

    if "esdc" in stages:
        ok &= _stage(conn, "esdc", lambda: esdc.run(conn, client))
    if "ircc" in stages:
        ok &= _stage(conn, "ircc", lambda: ircc.run(conn, client), "new findings")
    if "jobbank" in stages:
        allowed, reason = jobbank_allowed(conn, force=args.force)
        if not allowed:
            log.info("jobbank skipped: %s", reason)
            log_run(conn, "jobbank", detail=f"skipped: {reason}")
            stages = [s for s in stages if s != "jobbank"]
    if "jobbank" in stages:
        ok &= _stage(
            conn, "jobbank", lambda: jobbank.run(conn, client, limit=args.limit, detail_budget=args.detail_budget),
            failed_when=lambda stats: bool(stats.problems),
        )
    if "registry" in stages:
        ok &= _stage(conn, "registry", lambda: registry_bc.run(conn, client, budget=args.registry_budget), "matches")
        # A 260 MB download can fail; the rest of the night still runs.
        ok &= _stage(conn, "registry_federal", lambda: registry_federal.run(conn, client), "matches")
        # Same for the 270 MB Quebec extract.
        ok &= _stage(conn, "registry_quebec", lambda: registry_quebec.run(conn, client), "matches")
    # The reference tables for the wage and unemployment indicators. Each is
    # cached: wages and the LFS table are revalidated at most once a month,
    # the boundary files never after the first load. A failure leaves the
    # previous table in place and the indicators say what is missing.
    if "wages" in stages:
        ok &= _stage(conn, "wages", lambda: wages.run(conn, client), "rows loaded")
    if "lfs" in stages:
        ok &= _stage(conn, "lfs", lambda: lfs.run(conn, client), "rows loaded")
    if "vacancies" in stages:
        ok &= _stage(conn, "vacancies", lambda: vacancies.run(conn, client), "rows loaded")
    if "geography" in stages:
        # The boundary service answers some requests with HTTP 500 and the
        # next attempt succeeds, so this client retries more before giving up.
        ok &= _stage(conn, "geography", lambda: geography.run(conn, PoliteClient(max_attempts=geography.MAX_ATTEMPTS)),
                     "areas placed")
    # A failure here leaves the previous indicator states and statuses in the
    # database, which are consistent with each other, so the export still runs
    # and the site keeps its last good figures for them.
    if "indicators" in stages or "export" in stages or not selected:
        ok &= _stage(conn, "indicators", lambda: indicators.compute(conn), "changed")
        ok &= _stage(conn, "status", lambda: status.recompute(conn), "employers updated")
    if "export" in stages:
        ok &= _stage(conn, "export_csv", lambda: export.export_csv(conn), "csv rows")
        ok &= _stage(conn, "export_mirror", lambda: export.export_mirror(conn), "mirror files")
        ok &= _stage(conn, "export", lambda: export_static.export_static(conn), "static files")
        if args.d1:
            ok &= _stage(conn, "export_d1", lambda: export.export_d1(conn, full=args.full)["row_counts"], "d1 rows")
    return 0 if ok else 1


def _stage(
    conn: sqlite3.Connection,
    source: str,
    fn: Callable[[], Any],
    label: str = "",
    *,
    failed_when: Callable[[Any], bool] | None = None,
) -> bool:
    """Run one stage. Any exception is logged, recorded in sources_log (which
    is what the run status reports) and returned as False, so the stages after
    it still run and nothing propagates out of main. Work the stage left
    uncommitted is rolled back rather than committed by the log row."""
    try:
        result = fn()
    except Exception as exc:
        log.exception("%s failed", source)
        try:
            conn.rollback()
            log_run(conn, source, detail=f"{type(exc).__name__}: {exc}"[:900], ok=False)
        except sqlite3.Error as db_exc:
            log.error("%s: the failure could not be recorded: %s", source, db_exc)
        return False
    log.info("%s%s: %s", source, f" {label}" if label else "", result)
    return not (failed_when and failed_when(result))


if __name__ == "__main__":
    sys.exit(main())
