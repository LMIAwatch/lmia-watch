"""The Zenodo deposit, against a stub of the deposit API: nothing here reaches the network."""

import csv
import json
import logging
import re

import pytest

from lmia_pipeline import cli, config, export_static, zenodo
from lmia_pipeline.db import connect, get_meta, set_meta
from test_social import FakeJSON

TOKEN = "zenodo-token-value"
PROD = zenodo.PRODUCTION_API
SANDBOX = zenodo.SANDBOX_API


class FakeZenodo:
    """A small in-memory deposit API: depositions, their files, versions and publishing.
    `fail` maps a call name (create, newversion, list, delete_file, upload, metadata,
    publish, discard, read for one deposition, depositions for the listing) to an HTTP
    status or an exception to answer with instead. publish_lost publishes and then
    answers with the status or raises the exception, as when the answer is lost on the
    way back. Like Zenodo, it refuses to delete a published deposition."""

    def __init__(self, base: str = PROD, *, fail: dict | None = None, thin_publish: bool = False) -> None:
        self.base = base
        self.fail = fail or {}
        self.thin_publish = thin_publish
        self.deps: dict[int, dict] = {}
        self.next_id = 100
        self.calls: list[tuple[str, str]] = []
        self.auth: set[str] = set()

    def _new(self, concept: int | None, files: list[str]) -> dict:
        self.next_id += 1
        dep_id = self.next_id
        dep = {"id": dep_id, "submitted": False, "state": "unsubmitted", "concept": concept or dep_id,
               "files": {f"f{dep_id}-{i}": name for i, name in enumerate(files)}, "metadata": {}, "uploads": {}}
        self.deps[dep_id] = dep
        return dep

    def _view(self, dep: dict) -> dict:
        view = {
            "id": dep["id"], "submitted": dep["submitted"], "state": dep["state"], "metadata": dict(dep["metadata"]),
            "links": {"bucket": f"{self.base}/files/bucket-{dep['id']}", "latest_draft": dep.get("latest_draft")},
        }
        series = [d["id"] for d in self.deps.values() if d["concept"] == dep["concept"] and d["submitted"]]
        if series:
            view["links"]["latest"] = f"{self.base}/records/{max(series)}"
        if dep["submitted"]:
            view.update({"record_id": dep["id"], "doi": f"10.5281/zenodo.{dep['id']}",
                         "conceptdoi": f"10.5281/zenodo.{dep['concept']}", "conceptrecid": str(dep["concept"])})
        return view

    def _answer(self, name: str, ok: FakeJSON) -> FakeJSON:
        if name in self.fail:
            how = self.fail[name]
            if isinstance(how, Exception):
                raise how
            return FakeJSON(how, {"status": how, "message": f"{name} refused"})
        return ok

    def request(self, method, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append((method, url))
        self.auth.add((headers or {}).get("Authorization", ""))
        path = url[len(self.base):] if url.startswith(self.base) else url
        if method == "POST" and path == "/deposit/depositions":
            if "create" in self.fail:
                return self._answer("create", FakeJSON(201, {}))
            return FakeJSON(201, self._view(self._new(None, [])))
        if method == "GET" and path.partition("?")[0] == "/deposit/depositions":
            query = dict(p.split("=", 1) for p in path.partition("?")[2].split("&") if "=" in p)
            listed = sorted(self.deps.values(), key=lambda d: -d["id"])
            if query.get("all_versions") not in ("true", "1"):
                newest = {}
                for d in listed:
                    newest.setdefault(d["concept"], d)
                listed = list(newest.values())
            size, page = int(query.get("size", 10)), int(query.get("page", 1))
            page_of = [self._view(d) for d in listed[(page - 1) * size:page * size]]
            return self._answer("depositions", FakeJSON(200, page_of))
        m = re.fullmatch(r"/deposit/depositions/(\d+)(/.*)?", path)
        b = re.fullmatch(r"/files/bucket-(\d+)/(.+)", path)
        if b:
            dep = self.deps[int(b.group(1))]
            body = data.read() if hasattr(data, "read") else data
            answer = self._answer("upload", FakeJSON(201, {"key": b.group(2)}))
            if answer.status_code < 300:
                dep["uploads"][b.group(2)] = body
            return answer
        assert m, f"unexpected call {method} {url}"
        dep = self.deps[int(m.group(1))]
        rest = m.group(2) or ""
        if method == "GET" and rest == "":
            return self._answer("read", FakeJSON(200, self._view(dep)))
        if method == "PUT" and rest == "":
            answer = self._answer("metadata", FakeJSON(200, self._view(dep)))
            if answer.status_code < 300:
                dep["metadata"] = json["metadata"]
            return answer
        if method == "DELETE" and rest == "":
            if dep["submitted"]:
                return FakeJSON(403, {"status": 403, "message": "a published deposition cannot be deleted"})
            answer = self._answer("discard", FakeJSON(201, None, text=""))
            if answer.status_code < 300:
                del self.deps[dep["id"]]
            return answer
        if method == "POST" and rest == "/actions/newversion":
            existing = [d for d in self.deps.values() if d["concept"] == dep["concept"] and not d["submitted"]]
            if existing:
                draft = existing[0]
            else:
                # Zenodo starts the new version with the previous one's files and metadata.
                draft = self._new(dep["concept"], list(dep["uploads"]))
                draft["metadata"] = dict(dep["metadata"])
            dep["latest_draft"] = f"{self.base}/deposit/depositions/{draft['id']}"
            return self._answer("newversion", FakeJSON(201, self._view(dep)))
        if method == "GET" and rest == "/files":
            files = [{"id": fid, "filename": name} for fid, name in dep["files"].items()]
            return self._answer("list", FakeJSON(200, files))
        f = re.fullmatch(r"/files/(.+)", rest)
        if method == "DELETE" and f:
            answer = self._answer("delete_file", FakeJSON(204, None, text=""))
            if answer.status_code < 300:
                dep["files"].pop(f.group(1))
            return answer
        if method == "POST" and rest == "/actions/publish":
            answer = self._answer("publish", FakeJSON(202, {}))
            if answer.status_code < 300:
                dep["submitted"], dep["state"] = True, "done"
                if "publish_lost" in self.fail:
                    return self._answer("publish_lost", answer)
                if not self.thin_publish:
                    return FakeJSON(202, self._view(dep))
            return answer
        raise AssertionError(f"unexpected call {method} {url}")

    def published(self) -> list[dict]:
        return [d for d in self.deps.values() if d["submitted"]]

    def add_published(self, concept: int | None = None, **metadata) -> dict:
        """A version published outside the pipeline: by hand on the web page, or another dataset."""
        dep = self._new(concept, [])
        dep.update(submitted=True, state="done", metadata=metadata)
        return dep


def write_csvs(folder, period="2026Q1"):
    folder.mkdir(parents=True, exist_ok=True)
    rows = {
        "approved_quarterly.csv": [["period", "employer_id", "employer", "approved_positions"],
                                   ["2025Q4", "emp-a", "Acme Farms Ltd", "4"], [period, "emp-b", "Ferme Exemple", "2"]],
        "refused_quarterly.csv": [["period", "employer_id", "employer", "requested_positions"], ["2025Q4", "emp-c", "Sample Inc", "1"]],
        "esdc_resources.csv": [["resource_id", "dataset", "period", "sha256"], ["r1", "positive", period, "ab" * 32]],
    }
    for name, table in rows.items():
        with (folder / name).open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(table)
    # The files that are never deposited, present in the same folder.
    (folder / "findings.csv").write_text("employer_id,legal_name\nx,y\n", encoding="utf-8")
    (folder / "pending_observations.csv").write_text("posting_id\n1\n", encoding="utf-8")
    return folder


@pytest.fixture
def csvs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://lmiawatch.ca")
    return write_csvs(tmp_path / "csv")


def env(**extra):
    return {"ZENODO_TOKEN": TOKEN, **extra}


def test_first_deposit_creates_the_record_with_only_the_ogl_files(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (dep,) = api.published()
    assert sorted(dep["uploads"]) == ["README.txt", "approved_quarterly.csv", "esdc_resources.csv", "refused_quarterly.csv"]
    assert dep["uploads"]["approved_quarterly.csv"] == (csvs / "approved_quarterly.csv").read_bytes()
    meta = dep["metadata"]
    assert meta["upload_type"] == "dataset" and meta["access_right"] == "open"
    assert meta["license"] == "ogl-canada-2.0" and meta["version"] == "2026Q1"
    assert meta["creators"] == [{"name": "LMIA Watch"}] and meta["title"] == zenodo.TITLE
    assert {"identifier": "https://lmiawatch.ca", "relation": "isSupplementTo"} in meta["related_identifiers"]
    assert {"identifier": zenodo.ESDC_SOURCES[0], "relation": "isDerivedFrom"} in meta["related_identifiers"]
    assert "Open Government Licence - Canada" in meta["description"]
    readme = dep["uploads"]["README.txt"].decode("utf-8")
    assert "Version 2026Q1" in readme and "approved_quarterly.csv" in readme and "2 rows" in readme
    assert "Contains information licensed under the Open Government Licence - Canada." in readme
    for text in (readme, meta["description"], json.dumps(meta)):
        assert chr(0x2014) not in text
    assert get_meta(conn, "zenodo_period") == "2026Q1"
    assert get_meta(conn, "zenodo_record_id") == str(dep["id"])
    assert get_meta(conn, "zenodo_doi") == f"10.5281/zenodo.{dep['id']}"
    assert get_meta(conn, "zenodo_concept_doi") == f"10.5281/zenodo.{dep['id']}"
    assert api.auth == {f"Bearer {TOKEN}"}


def test_the_same_quarter_is_never_deposited_twice(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "no new quarter"
    assert len(api.calls) == calls and len(api.published()) == 1


def test_a_new_quarter_is_a_new_version_of_the_same_concept(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    first = get_meta(conn, "zenodo_record_id")
    write_csvs(csvs, period="2026Q2")
    set_meta(conn, "esdc_latest_period", "2026Q2")
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    old, new = api.published()
    assert new["concept"] == old["concept"] == int(first)
    assert new["metadata"]["version"] == "2026Q2"
    # The draft started with the previous version's files; they were removed before tonight's went up.
    assert new["files"] == {} and sorted(new["uploads"]) == sorted(old["uploads"])
    assert any(m == "DELETE" and "/files/" in u for m, u in api.calls)
    assert get_meta(conn, "zenodo_period") == "2026Q2"
    assert get_meta(conn, "zenodo_record_id") == str(new["id"])
    assert get_meta(conn, "zenodo_concept_doi") == f"10.5281/zenodo.{first}"
    assert get_meta(conn, "zenodo_doi") == f"10.5281/zenodo.{new['id']}"


@pytest.mark.parametrize("step", ["create", "upload", "metadata", "publish"])
def test_a_failure_before_publishing_discards_the_draft_and_records_nothing(conn, csvs, step, caplog):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo(fail={step: 500})
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert api.published() == [] and api.deps == {}
    assert get_meta(conn, "zenodo_period") is None and get_meta(conn, "zenodo_record_id") is None
    assert "zenodo: " in caplog.text and TOKEN not in caplog.text
    # The next night tries again and succeeds.
    assert zenodo.run(conn, csvs, env=env(), session=FakeZenodo()) == "deposited"


def test_a_network_fault_or_a_failed_discard_is_still_only_an_outcome(conn, csvs, caplog):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo(fail={"upload": ConnectionError("unreachable"), "discard": 500})
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert "the next run reuses or replaces it" in caplog.text and TOKEN not in caplog.text


def test_a_leftover_draft_is_reused_by_the_next_version(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    set_meta(conn, "esdc_latest_period", "2026Q2")
    write_csvs(csvs, period="2026Q2")
    api.fail = {"publish": 504, "discard": 500}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert len([d for d in api.deps.values() if not d["submitted"]]) == 1
    api.fail = {}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    assert len(api.published()) == 2 and not [d for d in api.deps.values() if not d["submitted"]]


def test_a_version_published_by_hand_is_the_one_versioned_next(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    first = int(get_meta(conn, "zenodo_record_id"))
    # The owner corrected the record on the web page: a newer version the database does not know of.
    by_hand = api._new(api.deps[first]["concept"], [])
    by_hand["submitted"] = True
    set_meta(conn, "esdc_latest_period", "2026Q2")
    write_csvs(csvs, period="2026Q2")
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    assert ("POST", f"{PROD}/deposit/depositions/{by_hand['id']}/actions/newversion") in api.calls
    assert ("POST", f"{PROD}/deposit/depositions/{first}/actions/newversion") not in api.calls


def test_a_thin_publish_answer_is_completed_from_the_record(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo(thin_publish=True)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (dep,) = api.published()
    assert get_meta(conn, "zenodo_doi") == f"10.5281/zenodo.{dep['id']}"


def test_files_that_predate_the_quarter_or_are_missing_are_not_deposited(conn, csvs, tmp_path):
    set_meta(conn, "esdc_latest_period", "2026Q2")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert api.calls == []
    set_meta(conn, "esdc_latest_period", "2026Q1")
    (csvs / "refused_quarterly.csv").unlink()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    files, problems = zenodo.prepare(tmp_path / "nowhere", "2026Q1")
    assert files == [] and len(problems) == 3


def test_skips_without_a_token_or_a_quarter(conn, csvs):
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "no data"
    set_meta(conn, "esdc_latest_period", "2026Q1")
    assert zenodo.run(conn, csvs, env={}, session=api) == "no token"
    assert zenodo.run(conn, csvs, env={"ZENODO_TOKEN": "  "}, session=api) == "no token"
    assert api.calls == []


def test_dry_run_checks_the_files_and_calls_nothing(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    printed: list[str] = []
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, dry_run=True, env={}, session=api, echo=printed.append) == "dry run"
    assert api.calls == [] and printed[0] == "Would deposit 2026Q1 on zenodo.org as a new record:"
    assert len(printed) == 5 and get_meta(conn, "zenodo_period") is None


def test_the_sandbox_keeps_its_own_record_and_never_reaches_the_site(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo(base=SANDBOX)
    assert zenodo.run(conn, csvs, env=env(ZENODO_SANDBOX="true"), session=api) == "deposited"
    assert all(url.startswith(SANDBOX) for _, url in api.calls)
    assert get_meta(conn, "zenodo_sandbox_period") == "2026Q1"
    assert get_meta(conn, "zenodo_period") is None and get_meta(conn, "zenodo_record_id") is None
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    assert zenodo.citation_from_meta(meta) is None
    # Production then starts its own record rather than versioning the sandbox one.
    prod = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(ZENODO_SANDBOX="false"), session=prod) == "deposited"
    assert ("POST", f"{PROD}/deposit/depositions") in prod.calls


def test_a_link_to_another_host_never_receives_the_token(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    original = api._view
    api._view = lambda dep: {**original(dep), "links": {"bucket": "https://elsewhere.example/files/x"}}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert not any("elsewhere.example" in url for _, url in api.calls)
    assert repr(zenodo.Client(PROD, TOKEN, api)) == f"Client({PROD})"


def test_citation_reaches_stats_json_only_from_production(conn, tmp_path):
    out = tmp_path / "static"
    out.mkdir()
    stats = export_static.write_stats(conn, out, "2026Q1", {})
    assert stats["citation"] is None
    set_meta(conn, "zenodo_sandbox_concept_doi", "10.5072/zenodo.1")
    assert export_static.write_stats(conn, out, "2026Q1", {})["citation"] is None
    for key, value in (("zenodo_concept_doi", "10.5281/zenodo.101"), ("zenodo_doi", "10.5281/zenodo.105"),
                       ("zenodo_period", "2026Q1"), ("zenodo_published", "2026-10-19")):
        set_meta(conn, key, value)
    conn.commit()
    export_static.write_stats(conn, out, "2026Q1", {})
    written = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert written["citation"] == {"title": zenodo.TITLE, "concept_doi": "10.5281/zenodo.101", "doi": "10.5281/zenodo.105",
                                   "version": "2026Q1", "published": "2026-10-19"}


def test_cli_writes_the_outcome_and_exits_1_only_on_failure(tmp_path, monkeypatch):
    db = tmp_path / "lmia.sqlite"
    c = connect(db)
    set_meta(c, "esdc_latest_period", "2026Q1")
    c.commit()
    c.close()
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    write_csvs(tmp_path / "csv")
    outcome = tmp_path / "out" / "zenodo" / "last_outcome.txt"
    assert cli.main(["deposit-zenodo", "--db", str(db), "--csv-dir", str(tmp_path / "csv")]) == 0
    assert outcome.read_text(encoding="utf-8").strip() == "no token"
    assert cli.main(["deposit-zenodo", "--db", str(db), "--csv-dir", str(tmp_path / "missing")]) == 1
    assert outcome.read_text(encoding="utf-8").strip() == "failed"
    assert cli.main(["deposit-zenodo", "--db", str(db), "--csv-dir", str(tmp_path / "csv"), "--dry-run"]) == 0
    assert outcome.read_text(encoding="utf-8").strip() == "dry run"


# -- a version Zenodo published that meta does not know of ---------------------


def zenodo_meta(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'zenodo%'")}


def lose_meta(conn, restore: dict | None = None) -> None:
    """The night's database save failed, so the next run starts from an older copy."""
    conn.execute("DELETE FROM meta WHERE key LIKE 'zenodo%'")
    for key, value in (restore or {}).items():
        set_meta(conn, key, value)
    conn.commit()


def versions_of(api: FakeZenodo, period: str) -> list[dict]:
    return [d for d in api.published() if d["metadata"].get("version") == period]


def assert_recorded(conn, dep: dict) -> None:
    """Meta holds the version as a fresh deposit of it would have left it."""
    assert get_meta(conn, "zenodo_period") == dep["metadata"]["version"]
    assert get_meta(conn, "zenodo_record_id") == str(dep["id"])
    assert get_meta(conn, "zenodo_doi") == f"10.5281/zenodo.{dep['id']}"
    assert get_meta(conn, "zenodo_concept_doi") == f"10.5281/zenodo.{dep['concept']}"
    assert get_meta(conn, "zenodo_concept_recid") == str(dep["concept"])
    assert get_meta(conn, "zenodo_published") == dep["metadata"]["publication_date"]


@pytest.mark.parametrize("answer", [504, TimeoutError("read timed out")], ids=["504", "timeout"])
@pytest.mark.parametrize("quarter", ["first", "next"])
def test_a_publish_whose_answer_was_lost_is_adopted_the_next_night(conn, csvs, quarter, answer, caplog):
    caplog.set_level(logging.INFO, logger="lmia_pipeline.zenodo")
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    if quarter == "next":
        assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
        set_meta(conn, "esdc_latest_period", "2026Q2")
        write_csvs(csvs, period="2026Q2")
    period = get_meta(conn, "esdc_latest_period")
    before = zenodo_meta(conn)
    api.fail = {"publish_lost": answer}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    # Zenodo published it and refused the discard; meta knows nothing of it.
    (dep,) = versions_of(api, period)
    assert zenodo_meta(conn) == before
    assert "the next run reuses or replaces it" in caplog.text
    api.fail = {}
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "already deposited"
    assert versions_of(api, period) == [dep] and len(api.published()) == (1 if quarter == "first" else 2)
    assert {m for m, _ in api.calls[calls:]} == {"GET"}
    assert_recorded(conn, dep)
    assert "is already published on zenodo.org" in caplog.text and TOKEN not in caplog.text
    assert zenodo.run(conn, csvs, env=env(), session=api) == "no new quarter"


@pytest.mark.parametrize("restore", [True, False], ids=["older-meta", "no-meta"])
def test_a_deposit_whose_database_save_was_lost_is_adopted_not_repeated(conn, csvs, restore):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    night_before = zenodo_meta(conn)
    set_meta(conn, "esdc_latest_period", "2026Q2")
    write_csvs(csvs, period="2026Q2")
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (q2,) = versions_of(api, "2026Q2")
    lose_meta(conn, night_before if restore else None)
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "already deposited"
    assert len(api.published()) == 2 and versions_of(api, "2026Q2") == [q2]
    assert {m for m, _ in api.calls[calls:]} == {"GET"}
    assert_recorded(conn, q2)


def test_a_first_deposit_whose_database_save_was_lost_starts_no_second_record(conn, csvs, monkeypatch):
    monkeypatch.setattr(zenodo, "LIST_PAGE_SIZE", 2)
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (dep,) = api.published()
    # Newer depositions of other datasets, one with the same version string,
    # push ours to a later page of the listing.
    for i in range(3):
        api.add_published(title=f"Another dataset {i}", version="2026Q1", publication_date="2026-10-01")
    lose_meta(conn)
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "already deposited"
    pages = [url for _, url in api.calls[calls:]]
    assert len(pages) == 3 and all("/deposit/depositions?" in u and "all_versions=true" in u for u in pages)
    assert len({d["concept"] for d in api.published() if d["metadata"].get("title") == zenodo.TITLE}) == 1
    assert_recorded(conn, dep)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "no new quarter"


@pytest.mark.parametrize("known", ["adopted", "by-title"])
def test_a_new_quarter_after_a_lost_record_is_a_new_version_of_the_same_concept(conn, csvs, known):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    first = int(get_meta(conn, "zenodo_record_id"))
    lose_meta(conn)
    if known == "adopted":
        assert zenodo.run(conn, csvs, env=env(), session=api) == "already deposited"
    set_meta(conn, "esdc_latest_period", "2026Q2")
    write_csvs(csvs, period="2026Q2")
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    old, new = api.published()
    assert new["concept"] == old["concept"] == first and new["metadata"]["version"] == "2026Q2"
    assert ("POST", f"{PROD}/deposit/depositions") not in api.calls[calls:]
    assert ("POST", f"{PROD}/deposit/depositions/{first}/actions/newversion") in api.calls[calls:]
    assert new["files"] == {}
    assert_recorded(conn, new)


@pytest.mark.parametrize("quarter", ["first", "next"])
def test_a_leftover_draft_holding_the_quarter_is_never_adopted(conn, csvs, quarter):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    if quarter == "next":
        assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
        set_meta(conn, "esdc_latest_period", "2026Q2")
        write_csvs(csvs, period="2026Q2")
    period = get_meta(conn, "esdc_latest_period")
    api.fail = {"publish": 500, "discard": 500}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    (draft,) = [d for d in api.deps.values() if not d["submitted"]]
    assert draft["metadata"]["version"] == period
    lose_meta(conn)
    api.fail = {}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (dep,) = versions_of(api, period)
    # A first record cannot be versioned, so a new one is made as before; a
    # new version's leftover draft is the one Zenodo hands back.
    assert (dep["id"] == draft["id"]) == (quarter == "next")
    assert_recorded(conn, dep)


def test_a_version_being_edited_on_the_web_page_still_counts_as_published(conn, csvs):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    (dep,) = api.published()
    dep["state"] = "inprogress"
    lose_meta(conn)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "already deposited"
    assert api.published() == [dep]


@pytest.mark.parametrize("fault", [500, ConnectionError("unreachable"), 200], ids=["refused", "unreachable", "not-a-list"])
def test_a_first_deposit_whose_check_fails_deposits_nothing(conn, csvs, fault, caplog):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo(fail={"depositions": fault})
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert api.deps == {} and [m for m, _ in api.calls] == ["GET"]
    assert zenodo_meta(conn) == {}
    assert "could not be checked" in caplog.text and TOKEN not in caplog.text
    api.fail = {}
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"


def test_a_new_version_whose_check_fails_deposits_nothing(conn, csvs, caplog):
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    assert zenodo.run(conn, csvs, env=env(), session=api) == "deposited"
    first = get_meta(conn, "zenodo_record_id")
    before = zenodo_meta(conn)
    set_meta(conn, "esdc_latest_period", "2026Q2")
    write_csvs(csvs, period="2026Q2")
    api.fail = {"read": 503}
    calls = len(api.calls)
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert api.calls[calls:] == [("GET", f"{PROD}/deposit/depositions/{first}")]
    assert len(api.deps) == 1 and zenodo_meta(conn) == before
    assert "could not be checked" in caplog.text and "HTTP 503" in caplog.text and TOKEN not in caplog.text


def test_a_listing_that_never_ends_is_a_failed_check(conn, csvs, monkeypatch):
    monkeypatch.setattr(zenodo, "LIST_PAGE_SIZE", 1)
    monkeypatch.setattr(zenodo, "LIST_MAX_PAGES", 2)
    set_meta(conn, "esdc_latest_period", "2026Q1")
    api = FakeZenodo()
    for i in range(3):
        api.add_published(title=f"Another dataset {i}", version="1")
    assert zenodo.run(conn, csvs, env=env(), session=api) == "failed"
    assert [m for m, _ in api.calls] == ["GET", "GET"] and len(api.deps) == 3


def test_already_deposited_exits_0_and_is_written_as_the_outcome(tmp_path, monkeypatch):
    db = tmp_path / "lmia.sqlite"
    connect(db).close()
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(zenodo, "run", lambda *args, **kwargs: "already deposited")
    assert cli.main(["deposit-zenodo", "--db", str(db)]) == 0
    assert (tmp_path / "out" / "zenodo" / "last_outcome.txt").read_text(encoding="utf-8").strip() == "already deposited"
