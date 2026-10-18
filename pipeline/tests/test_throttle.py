from lmia_pipeline.cli import jobbank_allowed
from lmia_pipeline.db import hours_since, set_meta


def test_hours_since(conn):
    assert hours_since(conn, "jobbank_last_run") is None
    set_meta(conn, "jobbank_last_run", "2026-10-13T00:00:00Z")
    assert hours_since(conn, "jobbank_last_run", now="2026-10-13T06:30:00Z") == 6.5
    set_meta(conn, "jobbank_last_run", "not a date")
    assert hours_since(conn, "jobbank_last_run") is None


def test_jobbank_runs_once_a_day(conn, monkeypatch):
    import lmia_pipeline.cli as cli
    import lmia_pipeline.db as db

    monkeypatch.setattr(db, "now_iso", lambda: "2026-10-13T06:00:00Z")
    assert jobbank_allowed(conn) == (True, "ok")
    set_meta(conn, "jobbank_last_run", "2026-10-13T00:00:00Z")
    allowed, reason = jobbank_allowed(conn)
    assert allowed is False and "already happened" in reason
    assert jobbank_allowed(conn, force=True) == (True, "forced")
    monkeypatch.setattr(db, "now_iso", lambda: "2026-10-14T00:05:00Z")
    assert jobbank_allowed(conn)[0] is True
    assert cli.JOBBANK_MIN_HOURS == 20.0
