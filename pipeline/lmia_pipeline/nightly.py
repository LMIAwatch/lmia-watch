"""Checks and the run status for the nightly workflow.

The workflow calls these between its steps so that a failure anywhere never
publishes broken or empty data, never replaces a good backup with a worse
one, and always leaves a status file the site's daily check can read.

  restore   pick the database to start from: the backup, else the previous
            backup when the newest is damaged, else (only when neither
            exists) an empty one. Exits 1 when a backup exists but cannot be
            used, so the run stops before it rebuilds from nothing.
  verify    check tonight's database and export; writes db_ok and export_ok
            for the save and deploy steps (to $GITHUB_OUTPUT when set).
  status    write status.json from the run's log rows, the workflow steps'
            outcomes and the checks, whatever state the run ended in.
  pack      write the backup the save step uploads: a copy of the database
            without its secondary indexes, checked and gzipped. Exits 1 when
            the copy fails its check or the file is above the upload cap.

The R2 transfers stay in the workflow; these commands read the files it
leaves. verify and status always exit 0: what they find is in their output.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("lmia_pipeline.nightly")

BACKUP = "lmia.sqlite.gz"
PREVIOUS = "lmia.sqlite.prev.gz"
MISSING_TEXT = "specified key does not exist"

# How far a count may fall between the restored backup and tonight's database
# before the new one is held back. The pipeline never deletes postings or
# their observations; list rows shrink a little when ESDC revises a file, and
# employers when the name normalisation merges two spellings.
MIN_SHARE = {
    "jobbank_postings": 1.0,
    "jobbank_observations": 1.0,
    "esdc_records": 0.9,
    "findings": 0.9,
    "employers": 0.5,
}
# The Worker accepts 20,000 files per version (its own assets included) and
# 25 MiB per file.
MAX_FILES = 19_000
MAX_FILE_BYTES = 25 * 1024 * 1024
# A file this much older than the run's start is left over from an earlier run.
CLOCK_SLACK_S = 120
# Wrangler refuses a single-object R2 upload above 300 MiB
# (MAX_UPLOAD_SIZE_BYTES in its source), and the save step uploads one file.
MAX_UPLOAD_MIB = 300

STEP_DETAIL = {
    "restore": "the database could not be restored, so nothing else ran",
    "pipeline": "the pipeline exited with an error (see the stage rows)",
    "verify": "the checks could not run",
    "deploy": "the deploy failed; the site keeps the previous data",
    "save_db": "the database backup was not saved; R2 keeps the previous one",
    "save_files": "the public files were not all saved to R2",
}


# -- database ---------------------------------------------------------------


def _readable(path: Path) -> sqlite3.Connection | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return sqlite3.connect(str(path))


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in MIN_SHARE:
        try:
            out[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.Error:
            out[table] = 0
    return out


def check_db(path: Path, before: dict[str, int] | None = None) -> tuple[list[str], dict[str, int]]:
    """Problems with the database at path, and its table counts.

    Folds the write-ahead log into the main file first, so the file itself
    holds every committed row (the pack reads through the log as well).
    """
    conn = _readable(path)
    if conn is None:
        return ["the database file is missing or empty"], {}
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result = [r[0] for r in conn.execute("PRAGMA quick_check")]
        if result != ["ok"]:
            return [f"the database failed its integrity check: {'; '.join(result)[:200]}"], {}
        counts = table_counts(conn)
    except sqlite3.Error as exc:
        return [f"the database cannot be read: {exc}"], {}
    finally:
        conn.close()
    problems = []
    for table, share in MIN_SHARE.items():
        was = (before or {}).get(table, 0)
        if was and counts.get(table, 0) < was * share:
            problems.append(f"{table} fell from {was} to {counts.get(table, 0)} rows")
    return problems, counts


# -- restore ----------------------------------------------------------------


def _gunzip(src: Path, dest: Path) -> str | None:
    """Decompress src to dest; the reason when it is not a complete gzip file."""
    try:
        with gzip.open(src, "rb") as fin, dest.open("wb") as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
        return None
    except (OSError, EOFError) as exc:
        dest.unlink(missing_ok=True)
        return f"not a complete gzip file ({exc})"


def _download(folder: Path, key: str) -> tuple[str, str]:
    """('ok' | 'missing' | 'failed', detail) for one download the workflow attempted."""
    exit_file = folder / f"{key}.exit"
    log_text = (folder / f"{key}.log").read_text(encoding="utf-8", errors="replace") if (folder / f"{key}.log").exists() else ""
    code = exit_file.read_text(encoding="utf-8").strip() if exit_file.exists() else ""
    if code == "0" and (folder / key).exists() and (folder / key).stat().st_size > 0:
        return "ok", ""
    if MISSING_TEXT in log_text.lower():
        return "missing", ""
    tail = " ".join(log_text.split())[-200:]
    return "failed", f"download failed (exit {code or 'unknown'}): {tail}" if tail else f"download failed (exit {code or 'unknown'})"


def restore(folder: Path, db: Path) -> tuple[bool, str, str, dict[str, int]]:
    """Choose the starting database. Returns (go on, source, message, table
    counts), source being 'backup', 'previous' or 'none' (a first run)."""
    tried: list[str] = []
    states = {}
    for key, source in ((BACKUP, "backup"), (PREVIOUS, "previous")):
        state, detail = _download(folder, key)
        states[key] = state
        if state != "ok":
            if state == "failed":
                tried.append(f"{key}: {detail}")
            continue
        why = _gunzip(folder / key, db)
        if why is None:
            problems, counts = check_db(db)
            if not problems:
                return True, source, f"restored from {key}", counts
            why = problems[0]
            db.unlink(missing_ok=True)
        tried.append(f"{key}: {why}")
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    if states.get(BACKUP) == "missing" and states.get(PREVIOUS) == "missing":
        db.unlink(missing_ok=True)
        return True, "none", "no backup in R2: first run, starting from an empty database", {}
    # A backup exists (or may exist) but none could be used. Starting from an
    # empty database would rebuild the site from nothing and then replace the
    # backup with it, so the run stops here instead.
    return False, "none", "; ".join(tried) or "no backup could be used", {}


# -- export -----------------------------------------------------------------


def _parse_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_export(static: Path, started: float | None, before_employers: int = 0) -> list[str]:
    """Problems that should keep tonight's export off the site."""
    if not static.is_dir():
        return ["no export was written"]
    problems: list[str] = []
    stats_path = static / "stats.json"
    if not stats_path.exists():
        return ["stats.json is missing"]
    if started is not None and stats_path.stat().st_mtime < started - CLOCK_SLACK_S:
        problems.append("stats.json is left over from an earlier run")
    try:
        stats = _load(stats_path)
        counts = stats["counts"]
        employers = int(counts["employers"])
        if not isinstance(stats.get("data_as_of"), str):
            problems.append("stats.json has no data date")
        if employers <= 0:
            problems.append("stats.json counts no employers")
        elif before_employers and employers < before_employers * MIN_SHARE["employers"]:
            problems.append(f"stats.json counts {employers} employers, down from {before_employers}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(f"stats.json cannot be read: {exc}")
        employers = 0
    for rel, kind in (("search/first.json", list), ("search/latest/all.json", list), ("search/facets.json", dict)):
        try:
            if not isinstance(_load(static / rel), kind):
                problems.append(f"{rel} has the wrong shape")
        except (OSError, ValueError) as exc:
            problems.append(f"{rel} cannot be read: {exc}"[:200])
    if employers > 0 and not any((static / "profiles").glob("*.json")):
        problems.append("no profile files were written")
    if not (static / "sitemaps" / "index.xml").exists():
        problems.append("sitemaps/index.xml is missing")
    files = [p for p in static.rglob("*") if p.is_file()]
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files, more than the {MAX_FILES} a deploy can carry")
    too_big = [p for p in files if p.stat().st_size > MAX_FILE_BYTES]
    if too_big:
        problems.append(f"{len(too_big)} files over 25 MiB, first {too_big[0].relative_to(static).as_posix()}")
    return problems


def verify(db: Path, static: Path, started: float | None, before: dict[str, int]) -> dict[str, Any]:
    db_problems, counts = check_db(db, before)
    export_problems = check_export(static, started, before.get("employers", 0))
    return {
        "db_ok": not db_problems,
        "export_ok": not export_problems,
        "problems": db_problems + export_problems,
        "counts": counts,
    }


# -- status -----------------------------------------------------------------


def run_status(
    db: Path, started: str | None, verify_result: dict[str, Any] | None, outcome: str | None,
    steps: dict[str, str], now: datetime | None = None, *, bluesky: str | None = None,
    zenodo: str | None = None, search: str | None = None,
) -> dict[str, Any]:
    """status.json for the site's daily check. Every input may be missing: the
    status then says what is missing rather than failing to be written.

    outcome, bluesky, zenodo and search are the outcomes the X post, the
    Bluesky post, the Zenodo deposit and the search database sync wrote
    ("synced", "nothing to send" or "failed" for the sync); "not run" when
    the step did not run. They are reported beside the stages, not as
    stages, so a refused post, a failed deposit or a failed sync alerts
    without marking the data refresh failed."""
    stages: list[dict[str, Any]] = []
    for name, result in steps.items():
        if result == "failure":
            stages.append({"source": f"workflow {name}", "ok": False, "detail": STEP_DETAIL.get(name, "the step failed")})
        elif result == "cancelled":
            stages.append({"source": f"workflow {name}", "ok": False, "detail": "the step was cancelled (the job's time limit?)"})
    conn = _readable(db)
    if conn is None:
        if steps.get("restore") != "failure":
            stages.append({"source": "database", "ok": False, "detail": "no database to read the run log from"})
    else:
        try:
            if started:
                rows = conn.execute(
                    "SELECT source, ok, detail FROM sources_log WHERE run_at >= ? ORDER BY id", (started,)
                ).fetchall()
                stages.extend({"source": s, "ok": bool(ok), "detail": (d or "")[:200]} for s, ok, d in rows)
            else:
                stages.append({"source": "pipeline", "ok": False, "detail": "the run never started its stages"})
        except sqlite3.Error as exc:
            stages.append({"source": "database", "ok": False, "detail": f"the run log cannot be read: {exc}"[:200]})
        finally:
            conn.close()
    if verify_result and verify_result.get("problems"):
        stages.append({"source": "checks", "ok": False, "detail": "; ".join(verify_result["problems"])[:200]})
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "run_at": stamp,
        "stages": stages,
        "x_post": outcome or "not run",
        "bluesky_post": bluesky or "not run",
        "zenodo_deposit": zenodo or "not run",
        "search_sync": search or "not run",
        "ok": all(s["ok"] for s in stages),
    }


# -- pack -------------------------------------------------------------------

# Only plain secondary indexes: a primary key or a UNIQUE constraint is part of
# the table and stays. A commented-out line never matches.
INDEX_RE = re.compile(r'^\s*CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"?(\w+)"?', re.IGNORECASE | re.MULTILINE)


def schema_indexes(schema_path: Path | None = None) -> list[str]:
    """Names of the secondary indexes schema.sql creates."""
    return INDEX_RE.findall((schema_path or config.SCHEMA_PATH).read_text(encoding="utf-8"))


def _mib(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MiB"


def pack(db: Path, out: Path, max_mib: float = MAX_UPLOAD_MIB,
         schema_path: Path | None = None) -> tuple[bool, str, dict[str, int]]:
    """Write the backup the save step uploads. Returns (ok, message, sizes in bytes).

    Why not gzip the file as it is: the gzip outgrew most of the upload cap,
    and about a fifth of it is the secondary indexes, which db.connect
    rebuilds from schema.sql whenever a restored copy is opened (seconds). And
    a step killed at its time limit can leave committed rows in the
    write-ahead log beside the file, which a gzip of the file alone would
    lose; VACUUM INTO reads them. The copy is checked before it is
    compressed, so a backup that would not open is never uploaded.
    """
    sizes: dict[str, int] = {}
    src = _readable(db)
    if src is None:
        return False, f"{db} is missing or empty; nothing to pack", sizes
    sizes["db"] = db.stat().st_size
    wal = Path(f"{db}-wal")
    sizes["wal"] = wal.stat().st_size if wal.exists() else 0
    out.parent.mkdir(parents=True, exist_ok=True)
    copy = out.with_name(out.name + ".copy.sqlite")
    partial = out.with_name(out.name + ".partial")
    for leftover in (copy, Path(f"{copy}-journal"), partial):
        leftover.unlink(missing_ok=True)
    try:
        try:
            src.execute("VACUUM INTO ?", (str(copy),))
        finally:
            src.close()
        conn = sqlite3.connect(str(copy))
        try:
            # Rollback journal, so every change below lands in the one file
            # that is compressed.
            conn.execute("PRAGMA journal_mode = DELETE")
            names = schema_indexes(schema_path)
            for name in names:
                conn.execute(f'DROP INDEX IF EXISTS "{name}"')
            conn.commit()
            conn.execute("VACUUM")
            result = [r[0] for r in conn.execute("PRAGMA quick_check")]
        finally:
            conn.close()
        if result != ["ok"]:
            return False, f"the packed copy failed its integrity check: {'; '.join(result)[:200]}", sizes
        sizes["copy"] = copy.stat().st_size
        with copy.open("rb") as fin, gzip.open(partial, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
        sizes["gz"] = partial.stat().st_size
    except (sqlite3.Error, OSError) as exc:
        partial.unlink(missing_ok=True)
        return False, f"the database could not be packed: {exc}"[:300], sizes
    finally:
        copy.unlink(missing_ok=True)
        Path(f"{copy}-journal").unlink(missing_ok=True)
    summary = (f"{db.name} {_mib(sizes['db'])} (write-ahead log {_mib(sizes['wal'])}), copy without its "
               f"{len(names)} secondary indexes {_mib(sizes['copy'])}, {out.name} {_mib(sizes['gz'])}")
    if sizes["gz"] > max_mib * 1024 * 1024:
        # Removed, so no later step or re-run uploads a file R2 would refuse;
        # the backup already in R2 stays as it is.
        partial.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        return False, (f"{summary}: above the {max_mib:g} MiB a single upload accepts, so nothing is saved "
                       f"tonight and R2 keeps the previous backup"), sizes
    partial.replace(out)
    return True, summary, sizes


# -- command line -----------------------------------------------------------


def _read(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    return Path(path).read_text(encoding="utf-8").strip() or None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="lmia_pipeline.nightly")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--dir", required=True, help="folder holding the downloads and their .exit and .log files")
    r.add_argument("--db", required=True)
    r.add_argument("--out", required=True, help="where to write the restore record (source, counts)")
    v = sub.add_parser("verify")
    v.add_argument("--db", required=True)
    v.add_argument("--static", required=True)
    v.add_argument("--started-file", default=None)
    v.add_argument("--restore", default=None, help="the restore record, for the counts before the run")
    v.add_argument("--out", required=True)
    s = sub.add_parser("status")
    s.add_argument("--db", required=True)
    s.add_argument("--started-file", default=None)
    s.add_argument("--verify", default=None)
    s.add_argument("--outcome", default=None, help="the X post's outcome file")
    s.add_argument("--bluesky-outcome", default=None, help="the Bluesky post's outcome file")
    s.add_argument("--zenodo-outcome", default=None, help="the Zenodo deposit's outcome file")
    s.add_argument("--search-outcome", default=None, help="the search database sync's outcome file")
    s.add_argument("--step", action="append", default=[], help="name=outcome of a workflow step")
    s.add_argument("--out", required=True)
    pk = sub.add_parser("pack")
    pk.add_argument("--db", required=True)
    pk.add_argument("--out", required=True, help="the gzip file to write")
    pk.add_argument("--max-mib", type=float, default=MAX_UPLOAD_MIB,
                    help=f"fail when the gzip is larger than this (default {MAX_UPLOAD_MIB}, Wrangler's upload cap)")
    args = parser.parse_args(argv)

    if args.command == "pack":
        ok, message, _ = pack(Path(args.db), Path(args.out), args.max_mib)
        (log.info if ok else log.error)("pack: %s", message)
        return 0 if ok else 1

    if args.command == "restore":
        ok, source, message, counts = restore(Path(args.dir), Path(args.db))
        _write_json(Path(args.out), {"source": source, "message": message, "counts": counts})
        (log.info if ok else log.error)("restore: %s", message)
        return 0 if ok else 1

    if args.command == "verify":
        record = {}
        try:
            record = json.loads(_read(args.restore) or "{}")
        except ValueError:
            record = {}
        result = verify(Path(args.db), Path(args.static), _parse_time(_read(args.started_file)), record.get("counts") or {})
        _write_json(Path(args.out), result)
        for p in result["problems"]:
            log.warning("check: %s", p)
        target = os.environ.get("GITHUB_OUTPUT")
        if target:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(f"db_ok={'true' if result['db_ok'] else 'false'}\n")
                fh.write(f"export_ok={'true' if result['export_ok'] else 'false'}\n")
        log.info("verify: db_ok=%s export_ok=%s", result["db_ok"], result["export_ok"])
        return 0

    verify_result = None
    try:
        verify_result = json.loads(_read(args.verify) or "null")
    except ValueError:
        verify_result = {"problems": ["the check results could not be read"]}
    steps = dict(item.split("=", 1) for item in args.step if "=" in item)
    status = run_status(Path(args.db), _read(args.started_file), verify_result, _read(args.outcome), steps,
                        bluesky=_read(args.bluesky_outcome), zenodo=_read(args.zenodo_outcome),
                        search=_read(args.search_outcome))
    _write_json(Path(args.out), status)
    print(json.dumps(status, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
