"""IRCC's high-wage list: the parser on the saved page, the committed fallback, and the nightly adoption."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

import pytest

from lmia_pipeline import intl, nightly, resilience
from lmia_pipeline.http import FetchError
from lmia_pipeline.sources import high_wage

NOW = "2026-10-26T00:10:00Z"


def page(fixtures) -> str:
    return (fixtures / "ircc_high_wage.html").read_text(encoding="utf-8")


@pytest.fixture
def fake_client(fake_client):
    """Each night's client with a cache of its own (the page is revalidated after 20 hours)."""
    made = []

    def make(mapping, **kwargs):
        client = fake_client(mapping, **kwargs)
        made.append(client)
        client.cache_dir = client.cache_dir.parent / f"cache-{len(made)}"
        return client

    return make


def without(html: str, noc: str) -> str:
    """The page with one code's row taken out."""
    return re.sub(rf"<tr>\s*<td[^>]*>{noc}</td>.*?</tr>", "", html, count=1, flags=re.S)


# -- the parser and the committed fallback ---------------------------------------------------


def test_the_page_lists_186_occupations_in_three_tiers(fixtures):
    occupations, modified = high_wage.parse_page(page(fixtures))
    assert len(occupations) == 186 and modified == "2026-10-16"
    by_points = {p: sum(1 for o in occupations if o.points == p) for p in (100, 70, 50)}
    assert by_points == {100: 31, 70: 89, 50: 66}
    points = {o.noc: o.points for o in occupations}
    assert points["00011"] == 100 and points["21220"] == 70 and points["00010"] == 50
    assert "60030" not in points
    assert all(int(o.noc[1]) <= 3 for o in occupations)


def test_the_committed_fallback_is_the_page_it_was_built_from(fixtures):
    occupations, _ = high_wage.parse_page(page(fixtures))
    doc = high_wage.load_list()
    assert doc["sha256"] == high_wage.fingerprint({o.noc: o.points for o in occupations})
    assert high_wage.points_by_noc() == {o.noc: o.points for o in occupations}
    assert doc["read_on"] == "2026-10-25" and doc["page_modified"] == "2026-10-16"
    assert high_wage.list_version()["count"] == 186


def test_the_build_script_writes_the_same_file_from_the_saved_page(fixtures, tmp_path):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_high_wage_list.py"
    spec = importlib.util.spec_from_file_location("build_high_wage_list", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "list.json"
    assert mod.main(["--from", str(fixtures / "ircc_high_wage.html"), "--out", str(out), "--read-on", "2026-10-25"]) == 0
    assert out.read_bytes() == high_wage.LIST_PATH.read_bytes()


@pytest.mark.parametrize("change, message", [
    (lambda h: h.replace("<caption", "<p", 1).replace("</caption>", "</p>", 1), "three tier tables"),
    (lambda h: re.sub(r"(<caption[^>]*>[^<]*?)twice", r"\g<1>2.5 times", h, count=1), "ratio of 2.5"),
    (lambda h: "<html><body><p>Moved.</p></body></html>", "three tier tables"),
])
def test_a_page_that_fails_the_checks_is_an_error(fixtures, change, message):
    with pytest.raises(ValueError, match=message):
        high_wage.parse_page(change(page(fixtures)))


def test_a_code_in_two_tiers_is_an_error(fixtures):
    html = page(fixtures)
    at = html.index("at least 1.5 times")
    row = "<tr><td>00011</td><td>Senior government managers and officials</td></tr>"
    tbody = html.index("<tbody>", at) + len("<tbody>")
    with pytest.raises(ValueError, match="two tiers"):
        high_wage.parse_page(html[:tbody] + row + html[tbody:])


CAPTIONS = {100: "NOCs with a median wage at least twice the average median wage",
            70: "NOCs with a median wage at least 1.5 times, but less than twice, the average median wage",
            50: "NOCs with a median wage at least 1.3 times, but less than 1.5 times, the average median wage"}


def page_of(counts: dict[int, int]) -> str:
    """A page in the list's form with this many codes per tier."""
    tables, n = [], 10000
    for points, count in counts.items():
        rows = "".join(f"<tr><td>{n + i:05d}</td><td>Occupation {n + i}</td></tr>" for i in range(count))
        tables.append(f"<table><caption>{CAPTIONS[points]}</caption><tbody>{rows}</tbody></table>")
        n += count
    return "<html><body>" + "".join(tables) + "</body></html>"


@pytest.mark.parametrize("counts, ok", [
    ({100: 40, 70: 40, 50: 39}, False),     # 119
    ({100: 40, 70: 40, 50: 40}, True),      # 120
    ({100: 150, 70: 150, 50: 100}, True),   # 400
    ({100: 150, 70: 150, 50: 101}, False),  # 401
])
def test_the_count_must_be_120_to_400(counts, ok):
    total = sum(counts.values())
    if ok:
        assert len(high_wage.parse_page(page_of(counts))[0]) == total
    else:
        with pytest.raises(ValueError, match=f"{total} occupations read, outside 120 to 400"):
            high_wage.parse_page(page_of(counts))


def test_every_tier_must_be_present():
    with pytest.raises(ValueError, match="three tier tables"):
        high_wage.parse_page(page_of({100: 100, 70: 100}))


def test_the_adoption_notice_names_the_codes():
    diff = high_wage.compare({"00011": 100, "21220": 70, "00010": 50}, {"00011": 100, "21220": 100, "11100": 50})
    assert diff == {"added": ["11100"], "removed": ["00010"], "moved": ["21220"]}
    assert high_wage.adoption_notice(diff, "2026-11-04") == (
        "IRCC high-wage list changed and was adopted for grading from 2026-11-04: 1 added (11100); 1 removed (00010); "
        "1 moved (21220) between tiers")


# -- the nightly read and adoption ----------------------------------------------------------------


def test_an_unchanged_page_adopts_nothing_and_raises_no_notice(conn, fixtures, fake_client):
    diff = high_wage.run(conn, fake_client({high_wage.SOURCE_URL: page(fixtures).encode()}), now=NOW)
    assert diff == {"added": [], "removed": [], "moved": []}
    row = conn.execute("SELECT ok, notice, detail FROM sources_log WHERE source = 'high_wage'").fetchone()
    assert (row["ok"], row["notice"]) == (1, None) and "live=186 in_use=186" in row["detail"]
    assert conn.execute("SELECT COUNT(*) FROM high_wage_editions").fetchone()[0] == 0
    assert high_wage.list_version(conn)["read_on"] == "2026-10-25"   # the committed version


def test_a_changed_page_is_adopted_used_for_grading_at_once_and_reported_once(conn, fixtures, fake_client):
    # A posting in an occupation the page drops tonight: graded A on the committed list.
    conn.execute(
        "INSERT INTO jobbank_intl_postings (posting_id, employer_raw, noc_code, first_seen, last_seen, found_by, audience, lmia, "
        "full_time, permanent, detail_fetched_at, url, updated_at) VALUES (1, 'X Inc', '21220', ?, ?, 'feed', 'international', "
        "'none', 1, 1, ?, 'u', ?)", (NOW, NOW, NOW, NOW))
    intl.regrade(conn, now=NOW)
    assert conn.execute("SELECT grade FROM jobbank_intl_postings").fetchone()[0] == "A"
    changed = without(page(fixtures), "21220")
    diff = high_wage.run(conn, fake_client({high_wage.SOURCE_URL: changed.encode()}), now="2026-11-04T00:10:00Z")
    assert diff == {"added": [], "removed": ["21220"], "moved": []}
    notice = conn.execute("SELECT notice FROM sources_log WHERE source = 'high_wage'").fetchone()[0]
    assert notice == "IRCC high-wage list changed and was adopted for grading from 2026-11-04: 0 added; 1 removed (21220)"
    # Adopted: the version in use, its date, and the grade, from tonight.
    assert "21220" not in high_wage.points_by_noc(conn) and len(high_wage.points_by_noc(conn)) == 185
    version = high_wage.list_version(conn)
    assert (version["read_on"], version["count"], version["stale"]) == ("2026-11-04", 185, False)
    assert conn.execute("SELECT grade FROM jobbank_intl_postings").fetchone()[0] == "B"
    # The same page the next night: nothing new.
    assert high_wage.run(conn, fake_client({high_wage.SOURCE_URL: changed.encode()}), now="2026-11-05T00:10:00Z") == {
        "added": [], "removed": [], "moved": []}
    assert conn.execute("SELECT notice FROM sources_log WHERE source = 'high_wage' ORDER BY id DESC").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM high_wage_editions").fetchone()[0] == 1
    # The committed file is untouched: it stays the fallback.
    assert "21220" in high_wage.points_by_noc()


def test_a_page_that_cannot_be_read_is_a_notice_on_change_only_and_grading_carries_on(conn, fixtures, fake_client):
    nights = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    bodies = [None, b"<html><body>Page moved</body></html>", None, page(fixtures).encode()]
    notices = []
    for night, body in zip(nights, bodies):
        mapping = {} if body is None else {high_wage.SOURCE_URL: body}
        result = high_wage.run(conn, fake_client(mapping), now=f"{night}T00:10:00Z")
        notices.append(conn.execute("SELECT notice FROM sources_log WHERE source = 'high_wage' ORDER BY id DESC").fetchone()[0])
        if night != nights[-1]:
            assert result is None
            assert high_wage.list_version(conn)["stale"] is True
            assert len(high_wage.points_by_noc(conn)) == 186     # the last good version
    assert notices[0].startswith("IRCC high-wage list could not be read or failed its checks")
    assert "grading continues on the version read 2026-10-25" in notices[0]
    assert notices[1] is None and notices[2] is None
    assert notices[3] == "IRCC high-wage list is readable again"
    assert high_wage.list_version(conn)["stale"] is False
    # Never a failed stage.
    assert {r[0] for r in conn.execute("SELECT ok FROM sources_log WHERE source = 'high_wage'")} == {1}


def test_without_any_version_the_live_page_is_adopted(conn, fixtures, fake_client, tmp_path):
    missing = tmp_path / "nothing.json"
    assert high_wage.points_by_noc(path=missing) == {}
    high_wage.run(conn, fake_client({high_wage.SOURCE_URL: page(fixtures).encode()}), now=NOW, list_path=missing)
    assert len(high_wage.points_by_noc(conn, missing)) == 186
    assert "186 added" in conn.execute("SELECT notice FROM sources_log WHERE source = 'high_wage'").fetchone()[0]


def test_the_adoption_notice_reaches_the_run_status_and_leaves_the_run_ok(conn, fixtures, fake_client, tmp_path):
    changed = without(page(fixtures), "21220")
    high_wage.run(conn, fake_client({high_wage.SOURCE_URL: changed.encode()}), now=NOW)
    db = tmp_path / "status.sqlite"
    disk = sqlite3.connect(str(db))
    conn.backup(disk)
    disk.close()
    status = nightly.run_status(db, "2026-01-01T00:00:00Z", {"problems": []}, None, {"deploy": "success"})
    notice = conn.execute("SELECT notice FROM sources_log WHERE source = 'high_wage'").fetchone()[0]
    assert status["ok"] is True
    assert status["notices"] == [{"source": "high_wage", "detail": notice}]
    # Information, never an item needing attention.
    assert resilience.attention_items(status) == []
    assert resilience.notice_items(status) == [f"high_wage: {notice}"]
    assert resilience.gate(status, date.fromisoformat(status["run_at"][:10]))[0] is True


def test_the_nightly_log_line_reads_as_a_sentence(conn, fixtures, fake_client, caplog):
    assert high_wage.summary({"added": [], "removed": [], "moved": []}, 186) == "IRCC high-wage list unchanged (186 codes)"
    assert high_wage.summary({"added": ["11100"], "removed": ["00010", "21220"], "moved": []}, 185) == (
        "IRCC high-wage list changed: 1 added, 2 removed, 0 moved")
    assert high_wage.summary(None, 186) == "IRCC high-wage list not read; grading keeps the version in use (186 codes)"
    # Through the stage runner, in place of the dictionary's repr.
    from lmia_pipeline import cli
    client = fake_client({high_wage.SOURCE_URL: page(fixtures).encode()})
    with caplog.at_level("INFO", logger="lmia_pipeline"):
        assert cli._stage(conn, "high_wage", lambda: high_wage.run(conn, client, now=NOW),
                          describe=lambda diff: high_wage.summary(diff, len(high_wage.points_by_noc(conn)))) is True
    lines = [r.getMessage() for r in caplog.records if r.name == "lmia_pipeline"]
    assert lines == ["IRCC high-wage list unchanged (186 codes)"]


def test_a_log_line_that_cannot_be_written_falls_back_to_the_result(conn, caplog):
    from lmia_pipeline import cli
    with caplog.at_level("INFO", logger="lmia_pipeline"):
        assert cli._stage(conn, "x", lambda: {"a": 1}, "result", describe=lambda r: r["missing"]) is True
    assert "x result: {'a': 1}" in [r.getMessage() for r in caplog.records]


def test_a_fetch_error_is_caught(conn, fake_client):
    client = fake_client({})

    def fail(url, **kwargs):
        raise FetchError("HTTP 503")

    client.get_text = fail
    assert high_wage.run(conn, client, now=NOW) is None


def test_a_damaged_edition_falls_back_to_the_committed_file(conn):
    conn.execute("INSERT INTO high_wage_editions (sha256, read_on, source_url, count, occupations, adopted_at) "
                 "VALUES ('x', '2026-11-04', 'u', 1, 'not json', ?)", (NOW,))
    assert len(high_wage.points_by_noc(conn)) == 186
    assert json.loads(json.dumps(high_wage.list_version(conn)))["read_on"] == "2026-10-25"
