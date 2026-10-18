import json

from lmia_pipeline import config
from lmia_pipeline.sources import ircc


def test_parse_rows_maps_reasons_and_addresses(fixtures):
    legend = ircc.parse_legend((fixtures / "ircc_legend.html").read_text(encoding="utf-8"))
    assert legend and all(k.isdigit() for k in legend)
    data = json.loads((fixtures / "ircc_sample.json").read_text(encoding="utf-8"))
    rows = ircc.parse_rows(data, legend)
    assert len(rows) == 3
    first = rows[0]
    assert first["operating_name"] and first["legal_name"]
    assert "<" not in (first["address"] or "")
    assert first["decision_date"] and len(first["decision_date"]) == 10
    assert first["penalty"].startswith("$")
    assert first["status"] in ("Eligible", "Ineligible")
    assert first["reasons"].split(":")[0].strip().isdigit()


def test_run_inserts_findings_and_links_employers(conn, fake_client, fixtures):
    mapping = {
        config.IRCC_NONCOMPLIANT_URL: (fixtures / "ircc_legend.html").read_bytes(),
        ircc.JSON_URL: (fixtures / "ircc_sample.json").read_bytes(),
    }
    client = fake_client(mapping)
    assert ircc.run(conn, client, now="2026-10-12T00:00:00Z") == 3
    assert ircc.run(conn, client, now="2026-10-13T00:00:00Z") == 0
    rows = conn.execute("SELECT * FROM findings ORDER BY id").fetchall()
    assert all(r["employer_id"] for r in rows)
    assert conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0] == 3
    emp = conn.execute("SELECT * FROM employers WHERE id = ?", (rows[1]["employer_id"],)).fetchone()
    assert emp["province"] in ("BC", "QC", "ON", "AB")
