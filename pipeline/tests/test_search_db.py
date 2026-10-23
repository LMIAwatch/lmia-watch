import dataclasses
import json
import logging
import sqlite3
from pathlib import Path

import pytest

from lmia_pipeline import cli, config, export_static, nightly, search_db
from lmia_pipeline.db import connect, get_meta, set_meta, upsert_employer

NOW = "2026-10-12T00:00:00Z"
SCHEMA = config.SEARCH_SCHEMA_PATH
QUEBEC = "Ferme Éloïse Québec Inc."


def seed(conn):
    q = upsert_employer(conn, QUEBEC, "QC", source="esdc_positive", city="Montréal", postal_code="H2X 1Y4", now=NOW)
    a = upsert_employer(conn, "O'Brien Farms Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
    b = upsert_employer(conn, "Beta Inn", "NS", source="jobbank", now=NOW)
    rows = [
        (1, "positive", "2026Q1", q, QUEBEC, "QC", "Primary Agriculture", "Montréal", "H2X 1Y4", "85101",
         "Harvesting labourers", 4, 12, "res-p26"),
        (2, "negative", "2015", a, "O'Brien Farms Ltd", "BC", None, "Kelowna", None, "8611",
         "Harvesting labourers", 1, 2, "res-n15"),
        (3, "positive", "2017Q1-Q2", a, "O'Brien Farms Ltd", "BC", "High-wage", "Kelowna", None, "6322",
         "Cooks", 1, 1, "res-p17"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO esdc_records (id, list, period, employer_id, employer_raw, province, stream, city, postal_code, "
            "noc_code, noc_title, lmias, positions, resource_id, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*r, f"h{r[0]}"))
    postings = [
        (5, b, "Beta Inn", "Cook's helper", "2026-10-06", "requested", None, None, None),
        (6, a, "O'Brien Farms Ltd", "Farm supervisor", None, "approved", 18.5, 22.0, "HOUR"),
        (7, b, "Beta Inn", "Dishwasher", "2026-09-01", "gone", None, None, None),
    ]
    for pid, eid, name, title, posted, flag, wmin, wmax, unit in postings:
        conn.execute(
            "INSERT INTO jobbank_postings (posting_id, employer_id, employer_raw, title, date_posted, first_seen, "
            "last_seen, flag_current, flag_first, wage_min, wage_max, wage_unit, url, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?)",
            (pid, eid, name, title, posted, "2026-10-01T03:00:00Z", NOW, flag, wmin, wmax, unit,
             f"https://www.jobbank.gc.ca/jobsearch/jobposting/{pid}", NOW))
    for ind in ("repeat_applicant", "high_volume"):
        conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
                     "VALUES (?, ?, 'triggered', 'b', '1', ?)", (a, ind, NOW))
    conn.execute("INSERT INTO indicators (employer_id, indicator, state, basis, rule_version, computed_at) "
                 "VALUES (?, 'wage_at_floor', 'not_triggered', 'b', '1', ?)", (b, NOW))
    conn.commit()
    return q, a, b


def fresh_target() -> sqlite3.Connection:
    """A stand-in for the D1 database: SQLite with search_schema.sql applied."""
    target = sqlite3.connect(":memory:")
    target.executescript(SCHEMA.read_text(encoding="utf-8"))
    return target


def apply(target, out_dir: Path, manifest: dict) -> None:
    for name in manifest["batches"]:
        # Bytes decoded by hand: text mode would turn a CRLF inside a value into LF.
        target.executescript((out_dir / name).read_bytes().decode("utf-8"))


def sync_once(conn, target, out_dir, **kw) -> dict:
    """One night: plan and write, apply every batch, check the count, record."""
    manifest = search_db.sync(conn, out_dir, **kw)
    target.executescript(SCHEMA.read_text(encoding="utf-8"))
    apply(target, out_dir, manifest)
    count = target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0]
    assert search_db.count_check(manifest["expected_total"], count) is None
    search_db.record_sync(conn, manifest)
    return manifest


def match(target, query: str) -> list[int]:
    return [r[0] for r in target.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ? ORDER BY rowid", (query,))]


def fts_consistent(target) -> None:
    # With rank 1, FTS5 also checks the index against the content table.
    target.execute("INSERT INTO search_fts (search_fts, rank) VALUES ('integrity-check', 1)")


# -- the schema --------------------------------------------------------------


def _schema_row(rid: int, name: str, city: str = "Montréal", h: str = "h1") -> dict:
    row = {c: None for c in search_db.COLUMNS}
    row.update(rid=rid, key=f"e:{rid // 2}", kind="esdc", ref=rid // 2, employer_id="emp-1", employer=name,
               job="Cooks", city=city, status="approved", sort_date="2026-03-31", ind="",
               name_fold=search_db.fold(name), hash=h)
    return row


def _insert(target, row: dict, verb: str = "INSERT") -> None:
    cols = ", ".join(search_db.COLUMNS)
    marks = ", ".join("?" * len(search_db.COLUMNS))
    target.execute(f"{verb} INTO search_rows ({cols}) VALUES ({marks})", [row[c] for c in search_db.COLUMNS])


def test_schema_applies_twice_and_keeps_the_index_in_step():
    target = fresh_target()
    target.executescript(SCHEMA.read_text(encoding="utf-8"))  # every statement IF NOT EXISTS
    _insert(target, _schema_row(2, QUEBEC))
    _insert(target, _schema_row(4, "O'Brien Farms Ltd", city="Kelowna"))
    # An accented name is found by its unaccented prefix, the city too.
    assert match(target, "quebec*") == [2]
    assert match(target, "eloise") == [2]
    assert match(target, "montreal") == [2]
    assert match(target, "brien") == [4]
    # A rename through the upsert the batches use: the old name is gone.
    renamed = _schema_row(4, "Gamma Orchards Ltd", city="Kelowna", h="h2")
    target.execute(search_db.upsert_statement([[renamed[c] for c in search_db.COLUMNS]]))
    assert match(target, "brien") == []
    assert match(target, "gamma") == [4]
    target.execute("UPDATE search_rows SET status = 'refused' WHERE rid = 4")  # no indexed column changed
    target.execute("DELETE FROM search_rows WHERE rid = 2")
    assert match(target, "quebec*") == []
    fts_consistent(target)
    # The index can be rebuilt from the table at any time.
    target.execute("INSERT INTO search_fts (search_fts) VALUES ('delete-all')")
    assert match(target, "gamma") == []
    target.execute("INSERT INTO search_fts (search_fts) VALUES ('rebuild')")
    assert match(target, "gamma") == [4]
    fts_consistent(target)


def test_insert_or_replace_would_leave_the_old_name_indexed():
    # Why the batches never use INSERT OR REPLACE: the row it deletes fires no
    # delete trigger, so the external-content index keeps the old text.
    target = fresh_target()
    _insert(target, _schema_row(4, "O'Brien Farms Ltd"))
    _insert(target, _schema_row(4, "Gamma Orchards Ltd", h="h2"), verb="INSERT OR REPLACE")
    assert match(target, "brien") == [4]
    with pytest.raises(sqlite3.DatabaseError):
        fts_consistent(target)
    assert "INSERT OR REPLACE" not in search_db.upsert_statement([[_schema_row(4, "x")[c] for c in search_db.COLUMNS]])


def _values(row: dict) -> list:
    return [row[c] for c in search_db.COLUMNS]


def test_a_multi_row_upsert_applied_twice_keeps_one_copy_and_the_index_right():
    target = fresh_target()
    rows = [_values(_schema_row(2 * i, f"Employer {i} Ltd", city="Kelowna")) for i in range(1, 101)]
    statement = search_db.upsert_statement(rows)
    assert statement.count(" ON CONFLICT ") == 1
    target.execute(statement)
    target.execute(statement)
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 100
    assert match(target, "employer") == [2 * i for i in range(1, 101)]
    fts_consistent(target)
    # The same statement shape renames some rows and leaves the others alone.
    changed = [_values(_schema_row(2 * i, f"Renamed {i} Inc", city="Kelowna", h="h2")) if i % 2 else rows[i - 1]
               for i in range(1, 101)]
    target.execute(search_db.upsert_statement(changed))
    target.execute(search_db.upsert_statement(changed))
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 100
    assert len(match(target, "renamed")) == 50 and len(match(target, "employer")) == 50
    fts_consistent(target)
    target.execute(next(search_db.delete_statements([f"e:{i}" for i in range(1, 101, 3)])))
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 100 - 34
    fts_consistent(target)


def test_statements_respect_their_row_key_and_byte_caps():
    target = fresh_target()
    rows = [_values(_schema_row(2 * i, f"Employer {i} Ltd")) for i in range(1, 251)]
    statements = list(search_db.upsert_statements(rows))
    assert len(statements) == 3                                  # 100 + 100 + 50
    before = 0
    for statement, want in zip(statements, (100, 100, 50)):
        assert len(statement.encode("utf-8")) <= search_db.MAX_STATEMENT_BYTES
        target.execute(statement)
        now = target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0]
        assert now - before == want
        before = now
    # Small caps: whichever binds first ends the statement.
    for max_rows, max_bytes in ((7, 10 ** 6), (100, 4000)):
        parts = list(search_db.upsert_statements(rows, max_rows=max_rows, max_bytes=max_bytes))
        sized = [len(p.encode("utf-8")) for p in parts]
        assert max(sized) <= max_bytes
        t = fresh_target()
        for p in parts:
            n0 = t.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0]
            t.execute(p)
            assert 1 <= t.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] - n0 <= max_rows
        assert t.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 250
    keys = [f"e:{i}" for i in range(1, 1201)]
    deletes = list(search_db.delete_statements(keys))
    assert len(deletes) == 3 and all(len(d.encode("utf-8")) <= search_db.MAX_STATEMENT_BYTES for d in deletes)
    assert [d.count("'e:") for d in deletes] == [500, 500, 200]
    target.executescript("\n".join(deletes))
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 0
    fts_consistent(target)


def test_long_names_never_push_a_statement_past_64_kib():
    long_name = "Très Longue Entreprise de Récolte " * 60            # about 2 KB of text, twice per row
    rows = [_values({**_schema_row(2 * i, long_name + str(i)), "job": long_name}) for i in range(1, 101)]
    statements = list(search_db.upsert_statements(rows))
    assert len(statements) > 1
    assert all(len(s.encode("utf-8")) <= 64 * 1024 for s in statements)
    target = fresh_target()
    for s in statements:
        target.execute(s)
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 100
    fts_consistent(target)
    huge = _values({**_schema_row(2, "x" * (70 * 1024))})
    with pytest.raises(ValueError, match=r"search row 'e:1': .* over the 65536-byte statement limit"):
        list(search_db.upsert_statements([huge]))


# -- the rows ----------------------------------------------------------------


def test_rows_match_the_static_export_and_leave_out_lapsed_postings(conn):
    seed(conn)
    ind = export_static.triggered_map(conn)
    expected = {("posting", p["posting_id"]): export_static.posting_row(p, ind) for p in conn.execute(
        export_static.POSTING_SQL + " WHERE flag_current IN ('requested', 'approved')")}
    expected.update({("esdc", r["id"]): export_static.esdc_row(r, ind) for r in conn.execute(export_static.ESDC_SQL)})
    rows = list(search_db.search_rows(conn))
    assert {(r["kind"], r["ref"]) for r in rows} == set(expected)
    assert ("posting", 7) not in {(r["kind"], r["ref"]) for r in rows}  # gone from Job Bank: lapsed
    for row in rows:
        want = expected[(row["kind"], row["ref"])]
        # A field added to the static rows needs a column here too.
        assert set(want) == set(search_db.ROW_FIELDS) | {"ind"}
        assert {f: row[f] for f in search_db.ROW_FIELDS} == {f: want[f] for f in search_db.ROW_FIELDS}
        assert row["ind"] == ",".join(want["ind"])
        assert set(row) == set(search_db.HASHED)
    by_key = {r["key"]: r for r in rows}
    assert by_key["e:2"]["ind"] == "high_volume,repeat_applicant"
    assert by_key["p:5"]["ind"] == ""  # not_triggered is not shown
    assert by_key["p:6"]["status"] == "approved" and by_key["p:5"]["status"] == "pending"
    assert by_key["e:2"]["status"] == "refused"


def test_rid_key_year_and_folded_name(conn):
    seed(conn)
    by_key = {r["key"]: r for r in search_db.search_rows(conn)}
    assert (by_key["e:1"]["rid"], by_key["e:3"]["rid"]) == (2, 6)
    assert (by_key["p:5"]["rid"], by_key["p:6"]["rid"]) == (11, 13)
    assert len({r["rid"] for r in by_key.values()}) == len(by_key)
    assert by_key["e:1"]["year"] == 2026
    assert by_key["e:2"]["year"] == 2015
    assert by_key["e:3"]["year"] == 2017                      # 2017Q1-Q2
    assert by_key["p:5"]["year"] == 2026                      # the posting date
    assert by_key["p:6"]["year"] == 2026                      # no posting date: the day first seen
    assert by_key["p:6"]["sort_date"] == "2026-10-01"
    assert by_key["e:1"]["name_fold"] == "ferme eloise quebec inc."
    assert by_key["e:2"]["name_fold"] == "o'brien farms ltd"
    with pytest.raises(ValueError):
        search_db.table_row({"kind": "esdc", "ref": "3"})


def test_fold_matches_search_js():
    # search.js: s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    assert search_db.fold("Société GÉNÉRALE Ñandú") == "societe generale nandu"
    assert search_db.fold("ÆON Œuvre") == "æon œuvre"   # not combining marks, kept as search.js keeps them
    assert search_db.fold(None) == ""
    assert search_db.fold("Plain ASCII") == "plain ascii"


def test_hash_changes_with_any_value_and_only_then(conn):
    seed(conn)
    row = next(r for r in search_db.search_rows(conn) if r["key"] == "p:6")
    h = search_db.row_hash(row)
    assert h == search_db.row_hash(dict(row)) and len(h) == 40
    again = next(r for r in search_db.search_rows(conn) if r["key"] == "p:6")
    assert search_db.row_hash(again) == h
    for column in search_db.HASHED:
        changed = dict(row)
        changed[column] = "changed" if row[column] != "changed" else "other"
        assert search_db.row_hash(changed) != h, column
    # None, empty and zero are three different values.
    hashes = {search_db.row_hash({**row, "street": v}) for v in (None, "", 0)}
    assert len(hashes) == 3


# -- the plan and the ledger -------------------------------------------------


def test_plan_lifecycle_first_load_then_changes_only(conn, tmp_path):
    seed(conn)
    target = fresh_target()
    first = sync_once(conn, target, tmp_path / "out")
    assert first["full"] and first["reason"].startswith("first load")
    assert first["upserts"] == first["expected_total"] == 5 and first["deletes"] == 0
    assert conn.execute("SELECT COUNT(*) FROM search_sync").fetchone()[0] == 5

    nothing = search_db.plan_sync(conn)
    assert (nothing.upserts, nothing.deletes, nothing.full, nothing.total) == ([], [], False, 5)

    conn.execute("UPDATE jobbank_postings SET title = 'Head cook' WHERE posting_id = 5")
    one = search_db.plan_sync(conn)
    assert [v[1] for v in one.upserts] == ["p:5"] and one.deletes == []
    sync_once(conn, target, tmp_path / "out")
    assert target.execute("SELECT job FROM search_rows WHERE key = 'p:5'").fetchone()[0] == "Head cook"

    conn.execute("DELETE FROM esdc_records WHERE id = 3")
    gone = search_db.plan_sync(conn)
    assert gone.upserts == [] and gone.deletes == ["e:3"] and gone.total == 4
    sync_once(conn, target, tmp_path / "out")
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM search_sync WHERE key = 'e:3'").fetchone()[0] == 0

    # A posting whose flag lapses leaves the search set like a deleted row.
    conn.execute("UPDATE jobbank_postings SET flag_current = 'gone' WHERE posting_id = 6")
    assert search_db.plan_sync(conn).deletes == ["p:6"]
    assert search_db.plan_sync(conn).full is False


def test_nothing_is_recorded_until_record_sync(conn, tmp_path):
    seed(conn)
    search_db.sync(conn, tmp_path / "out")
    assert conn.execute("SELECT COUNT(*) FROM search_sync").fetchone()[0] == 0
    # The apply failed (never recorded): the next night sends everything again.
    again = search_db.plan_sync(conn)
    assert len(again.upserts) == again.total == 5


def test_record_sync_refuses_a_manifest_planned_on_another_ledger(conn, tmp_path):
    seed(conn)
    target = fresh_target()
    sync_once(conn, target, tmp_path / "out")
    conn.execute("UPDATE jobbank_postings SET title = 'Head cook' WHERE posting_id = 5")
    stale = search_db.write_batches(search_db.plan_sync(conn), tmp_path / "out")
    conn.execute("DELETE FROM search_sync WHERE key = 'e:1'")  # the ledger moved on since
    conn.commit()
    with pytest.raises(ValueError, match="expects 5"):
        search_db.record_sync(conn, stale)
    assert conn.execute("SELECT hash FROM search_sync WHERE key = 'p:5'").fetchone()[0] != stale["record"]["upserts"][0][2]
    with pytest.raises(ValueError):
        search_db.record_sync(conn, {"batches": [], "expected_total": 0})


# -- the batch files ---------------------------------------------------------


def statements(path: Path) -> list[str]:
    """Split a batch file into statements with SQLite's own idea of where one ends."""
    out, buf = [], ""
    for line in path.read_bytes().decode("utf-8").split("\n"):
        buf += line + "\n"
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    assert buf.strip() == ""
    return out


def test_batches_respect_both_caps_and_apply_to_a_fresh_database(conn, tmp_path):
    seed(conn)
    for i in range(40):
        conn.execute(
            "INSERT INTO esdc_records (list, period, employer_id, employer_raw, province, city, noc_code, noc_title, "
            "positions, resource_id, row_hash) SELECT 'positive', '2025Q4', id, display_name || ' ' || ?, province, city, "
            "'73300', 'Truck drivers', 1, 'res', ? FROM employers WHERE province = 'NS'", (i, f"x{i}"))
    plan = search_db.plan_sync(conn)
    assert plan.full  # a first load: the reset comes first
    first = search_db.write_batches(plan, tmp_path / "first")
    assert first["batches"][0] == "batch-0001.sql"
    assert (tmp_path / "first" / "batch-0001.sql").read_text(encoding="utf-8").startswith("-- Full reload")
    plan = dataclasses.replace(plan, full=False, reason="")
    # The file caps (bytes, then statements) and the statement caps (rows,
    # then bytes), each binding in turn.
    cases = (("file-bytes", 6000, 50, 3, 10 ** 6), ("file-count", 10 ** 6, 2, 3, 10 ** 6),
             ("stmt-bytes", 10 ** 6, 50, 100, 2500))
    for name, max_bytes, max_statements, max_rows, stmt_bytes in cases:
        out = tmp_path / name
        manifest = search_db.write_batches(plan, out, max_bytes=max_bytes, max_statements=max_statements,
                                           max_rows_per_upsert=max_rows, max_statement_bytes=stmt_bytes)
        assert len(manifest["batches"]) > 1 if name != "stmt-bytes" else len(manifest["batches"]) == 1
        check = fresh_target()
        for batch in manifest["batches"]:
            parts = statements(out / batch)
            assert (out / batch).stat().st_size <= max_bytes and 1 <= len(parts) <= max_statements, batch
            for part in parts:
                assert len(part.encode("utf-8")) <= stmt_bytes
                n0 = check.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0]
                check.execute(part)
                assert 1 <= check.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] - n0 <= max_rows
        assert check.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == manifest["upserts"] == 45
    target = fresh_target()
    apply(target, out, manifest)
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == manifest["expected_total"]
    want = {r["key"]: [r[c] for c in search_db.HASHED] for r in search_db.search_rows(conn)}
    got = {r[1]: list(r[:-1]) for r in target.execute(f"SELECT {', '.join(search_db.COLUMNS)} FROM search_rows")}
    assert got == want
    assert match(target, "quebec*") == [2]
    assert len(match(target, "truck")) == 40
    fts_consistent(target)

    with pytest.raises(ValueError, match="over the 200-byte batch limit"):
        search_db.write_batches(plan, tmp_path / "small", max_bytes=200)


def test_default_caps(conn, tmp_path):
    seed(conn)
    plan = search_db.plan_sync(conn)
    many = search_db.SyncPlan(upserts=plan.upserts * 6000, deletes=[f"e:{i}" for i in range(1, 1201)], total=0)
    manifest = search_db.write_batches(many, tmp_path / "out")
    sizes = [(tmp_path / "out" / n).stat().st_size for n in manifest["batches"]]
    parts = [s for n in manifest["batches"] for s in statements(tmp_path / "out" / n)]
    counts = [len(statements(tmp_path / "out" / n)) for n in manifest["batches"]]
    assert max(sizes) <= search_db.MAX_BATCH_BYTES and max(counts) <= search_db.MAX_BATCH_STATEMENTS
    assert max(len(s.encode("utf-8")) for s in parts) <= search_db.MAX_STATEMENT_BYTES
    # 30,000 rows at 100 a statement, after 1,200 keys at 500 a statement.
    assert sum(s.startswith("INSERT") for s in parts) == 300
    assert sum(s.startswith("DELETE") for s in parts) == 3
    assert len(manifest["batches"]) >= 3


def test_text_that_could_break_a_statement_round_trips(conn, tmp_path):
    seed(conn)
    awkward = [
        "Robert'); DROP TABLE search_rows; --",
        "C:\\Farms\\New Ltd \\' backslash",
        "Two\nlines\r\nand a tab\t",
        "Café Ünïcödé 中文 🍁",
        "/* not a comment */ -- nor this; END; BEGIN",
        "$1 $$dollar$$ ?2 :name @x",
        "''''",
    ]
    for i, name in enumerate(awkward, start=10):
        conn.execute(
            "INSERT INTO esdc_records (id, list, period, employer_id, employer_raw, noc_title, resource_id, row_hash) "
            "SELECT ?, 'positive', '2026Q1', id, ?, ?, 'res', ? FROM employers WHERE province = 'NS'",
            (i, name, name, f"aw{i}"))
    target = fresh_target()
    manifest = sync_once(conn, target, tmp_path / "out")
    got = {r[0]: (r[1], r[2]) for r in target.execute("SELECT ref, employer, job FROM search_rows WHERE kind = 'esdc'")}
    for i, name in enumerate(awkward, start=10):
        assert got[i] == (name, name)
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == manifest["expected_total"]
    assert match(target, "cafe") == [26]          # esdc id 13
    fts_consistent(target)


def test_sql_literal():
    lit = search_db.sql_literal
    assert lit(None) == "NULL"
    assert lit(True) == "1" and lit(False) == "0"
    assert lit(42) == "42" and lit(-7) == "-7"
    assert lit(18.5) == "18.5" and lit(20.0) == "20.0"
    assert lit("O'Brien") == "'O''Brien'"
    assert lit("a\\b") == "'a\\b'"
    assert lit("") == "''"
    for bad in (float("nan"), float("inf"), 2 ** 63, "a\x00b"):
        with pytest.raises(ValueError):
            lit(bad)
    with pytest.raises(TypeError):
        lit(b"bytes")
    row = [None] * len(search_db.COLUMNS)
    row[1], row[5] = "e:9", "Nul\x00Corp"
    with pytest.raises(ValueError, match=r"search row 'e:9', column employer: text holds a NUL byte"):
        search_db.upsert_statement([row])


def test_a_nul_byte_stops_the_batches_before_any_file_is_trusted(conn, tmp_path):
    seed(conn)
    conn.execute("UPDATE jobbank_postings SET title = ? WHERE posting_id = 5", ("Cook" + chr(0),))
    with pytest.raises(ValueError, match="NUL"):
        search_db.write_batches(search_db.plan_sync(conn), tmp_path / "out")
    assert not (tmp_path / "out" / search_db.MANIFEST).exists()


def test_full_reload_drops_and_recreates_first(conn, tmp_path):
    seed(conn)
    target = fresh_target()
    sync_once(conn, target, tmp_path / "out")
    # Drift the D1 copy: a row no ledger knows of, and one row missing.
    _insert(target, _schema_row(998, "Stray Row Ltd"))
    target.execute("DELETE FROM search_rows WHERE key = 'p:5'")
    conn.execute("INSERT INTO search_sync (key, rid, hash) VALUES ('e:777', 1554, 'x')")
    conn.commit()
    plan = search_db.plan_sync(conn, full=True)
    assert plan.full and plan.reason == "requested" and plan.deletes == [] and len(plan.upserts) == 5
    out = tmp_path / "full"
    manifest = search_db.write_batches(plan, out)
    first = (out / manifest["batches"][0]).read_text(encoding="utf-8")
    assert first.index("DROP TABLE IF EXISTS search_fts;") < first.index("CREATE TABLE IF NOT EXISTS search_rows")
    assert "INSERT INTO search_rows" not in first
    apply(target, out, manifest)
    assert target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0] == 5
    assert match(target, "stray") == []
    fts_consistent(target)
    search_db.record_sync(conn, manifest)
    assert conn.execute("SELECT COUNT(*) FROM search_sync WHERE key = 'e:777'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM search_sync").fetchone()[0] == 5


def test_a_disagreeing_count_reloads_in_full_at_most_weekly(conn, tmp_path):
    seed(conn)
    target = fresh_target()
    sync_once(conn, target, tmp_path / "out")
    set_meta(conn, search_db.META_FULL_AT, "2026-10-10")
    search_db.request_reload(conn, "2026-10-12")
    assert search_db.plan_sync(conn, today="2026-10-13").full is False      # three days after a reload
    later = search_db.plan_sync(conn, today="2026-10-17")
    assert later.full and "disagreed on 2026-10-12" in later.reason
    # A count that matches clears the request.
    manifest = search_db.write_batches(search_db.plan_sync(conn, today="2026-10-13"), tmp_path / "out")
    search_db.record_sync(conn, manifest)
    assert get_meta(conn, search_db.META_RELOAD) is None
    assert search_db.plan_sync(conn, today="2026-12-01").full is False


def test_an_empty_ledger_resets_at_most_weekly_but_always_sends_every_row(conn, tmp_path):
    seed(conn)
    set_meta(conn, search_db.META_FULL_AT, "2026-10-11")
    plan = search_db.plan_sync(conn, today="2026-10-12")
    assert plan.full is False and len(plan.upserts) == plan.total == 5
    assert search_db.plan_sync(conn, today="2026-10-18").full is True
    # Sent again over rows D1 already holds, an upsert with the same hash writes nothing.
    target = fresh_target()
    out = tmp_path / "out"
    manifest = search_db.write_batches(plan, out)
    apply(target, out, manifest)
    before = target.total_changes
    apply(target, out, manifest)
    assert target.total_changes == before


# -- the commands ------------------------------------------------------------


def _file_db(tmp_path) -> Path:
    db = tmp_path / "lmia.sqlite"
    c = connect(db)
    seed(c)
    c.close()
    return db


def test_commands_write_record_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    db = _file_db(tmp_path)
    out = tmp_path / "out" / "search"
    outcome = out / search_db.OUTCOME
    assert cli.main(["search-sync", "--db", str(db), "--out", str(out)]) == 0
    assert "5 upserts, 0 deletes" in capsys.readouterr().out
    assert outcome.read_text(encoding="utf-8").strip() == "failed"   # until search-synced
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    target = fresh_target()
    apply(target, out, manifest)
    n = target.execute("SELECT COUNT(*) FROM search_rows").fetchone()[0]
    assert cli.main(["search-check", "--manifest", str(out / "manifest.json"), "--count", str(n)]) == 0
    assert cli.main(["search-synced", "--db", str(db), "--manifest", str(out / "manifest.json")]) == 0
    assert outcome.read_text(encoding="utf-8").strip() == "synced"

    # Nothing changed: a manifest with no batches, still exit 0.
    assert cli.main(["search-sync", "--db", str(db), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["batches"] == [] and manifest["expected_total"] == 5
    assert list(out.glob("batch-*.sql")) == []
    assert cli.main(["search-synced", "--db", str(db), "--manifest", str(out / "manifest.json")]) == 0
    assert outcome.read_text(encoding="utf-8").strip() == "nothing to send"


def test_search_check_names_both_numbers_and_asks_for_a_reload(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    db = _file_db(tmp_path)
    out = tmp_path / "out" / "search"
    assert cli.main(["search-sync", "--db", str(db), "--out", str(out)]) == 0
    manifest = str(out / "manifest.json")
    with caplog.at_level(logging.ERROR):
        assert cli.main(["search-check", "--manifest", manifest, "--count", "7"]) == 1
    assert "holds 7 rows where the manifest expects 5" in caplog.text
    c = connect(db)
    try:
        assert get_meta(c, search_db.META_RELOAD) is None   # no --db, nothing noted
    finally:
        c.close()
    assert cli.main(["search-check", "--manifest", manifest, "--count", "4", "--db", str(db)]) == 1
    c = connect(db)
    try:
        assert get_meta(c, search_db.META_RELOAD) is not None
        assert c.execute("SELECT COUNT(*) FROM search_sync").fetchone()[0] == 0
    finally:
        c.close()
    assert (out / search_db.OUTCOME).read_text(encoding="utf-8").strip() == "failed"


def test_full_flag_and_removed_d1_flags():
    parser = cli.build_parser()
    assert parser.parse_args(["search-sync", "--full"]).full is True
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--d1"])
    with pytest.raises(SystemExit):
        parser.parse_args(["mark-synced"])


def test_the_dormant_d1_ledger_is_gone(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "search_sync" in tables and "d1_sync" not in tables
    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE d1_sync (table_name TEXT PRIMARY KEY, high_water TEXT NOT NULL)")
    old.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert old.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'd1_sync'").fetchone()[0] == 0


# -- the run status ----------------------------------------------------------


def test_run_status_carries_the_search_sync(tmp_path):
    db = tmp_path / "none.sqlite"
    status = nightly.run_status(db, None, None, None, {}, search="failed")
    assert status["search_sync"] == "failed"
    assert nightly.run_status(db, None, None, None, {})["search_sync"] == "not run"
    (tmp_path / "search.txt").write_text("nothing to send\n", encoding="utf-8")
    out = tmp_path / "status.json"
    assert nightly.main(["status", "--db", str(db), "--search-outcome", str(tmp_path / "search.txt"),
                         "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["search_sync"] == "nothing to send"
