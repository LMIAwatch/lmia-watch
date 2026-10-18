import json

import pytest

from lmia_pipeline.cli import load_fsa_centroids
from lmia_pipeline.sources import geography
from lmia_pipeline.sources.geography import Shape, contains, english, interior_point, layer_url

from conftest import FakeResponse


@pytest.fixture
def manitoba(fixtures) -> dict[str, bytes]:
    """The service's answers for Manitoba (trimmed); every other province is a 404."""
    pieces = json.loads((fixtures / "geography_mb.json").read_text(encoding="utf-8"))
    return {layer_url(layer, "46"): json.dumps(piece).encode() for layer, piece in pieces.items()}


def region(conn, fsa):
    return conn.execute("SELECT er_uid, er_name, cma_uid, cma_name, method FROM fsa_regions WHERE fsa = ?",
                        (fsa,)).fetchone()


def test_winnipeg_and_rural_manitoba(conn, fake_client, manitoba):
    load_fsa_centroids(conn)
    geography.run(conn, fake_client(manitoba))
    # R2H (St. Boniface): GeoNames centroid inside its own boundary, in the city.
    assert tuple(region(conn, "R2H")) == ("4650", "Winnipeg", "602", "Winnipeg", "centroid")
    assert tuple(region(conn, "R3T"))[:3] == ("4650", "Winnipeg", "602")
    # Rural areas: an economic region, no census metropolitan area.
    assert tuple(region(conn, "R0G"))[:4] == ("4620", "South Central", None, None)
    assert tuple(region(conn, "R0C"))[:4] == ("4680", "North", None, None)
    # Ontario was not served, so its areas have no region, and the run says so.
    assert region(conn, "M5V")["er_uid"] is None
    log = conn.execute("SELECT detail, ok FROM sources_log WHERE source = 'geography'").fetchone()
    assert log["ok"] == 0 and "fsa:35" in log["detail"]


def test_a_centroid_outside_its_own_area_is_replaced(conn, fake_client, manitoba):
    load_fsa_centroids(conn)
    # Put R2H's centroid in a rural area; the 2021 boundary wins.
    conn.execute("UPDATE fsa_centroids SET lat = 49.4394, lon = -98.0869 WHERE fsa = 'R2H'")
    geography.run(conn, fake_client(manitoba))
    row = region(conn, "R2H")
    assert (row["er_uid"], row["cma_uid"], row["method"]) == ("4650", "602", "boundary")


def test_built_once_then_no_requests_until_the_centroids_change(conn, fake_client, manitoba):
    load_fsa_centroids(conn)
    # Every other province answers with no features, so the build is complete.
    for layer in geography.LAYERS:
        for pruid in geography.PRUIDS:
            manitoba.setdefault(layer_url(layer, pruid), b'{"features": []}')
    client = fake_client(manitoba)
    assert geography.run(conn, client) > 0
    calls = len(client.fake_session.calls)
    assert calls == len(geography.LAYERS) * len(geography.PRUIDS)
    assert geography.run(conn, client) == 0
    assert len(client.fake_session.calls) == calls
    assert "skipped" in conn.execute(
        "SELECT detail FROM sources_log WHERE source = 'geography' ORDER BY id DESC").fetchone()[0]
    conn.execute("UPDATE fsa_centroids SET lat = lat + 0.001 WHERE fsa = 'R3T'")
    assert geography.run(conn, client) > 0


def test_an_error_body_is_not_kept(conn, fake_client, manitoba):
    load_fsa_centroids(conn)
    url = layer_url("cma", "46")
    good = manitoba[url]
    manitoba[url] = FakeResponse(200, b'{"error": {"code": 500, "message": "Error performing query"}}')
    client = fake_client(manitoba)
    geography.run(conn, client)
    assert region(conn, "R2H")["cma_uid"] is None
    assert "cma:46" in conn.execute("SELECT detail FROM sources_log WHERE source = 'geography'").fetchone()[0]
    # The bad answer was not cached, so the next run asks again and succeeds.
    client.fake_session.mapping[url] = good
    geography.run(conn, client)
    assert region(conn, "R2H")["cma_uid"] == "602"


def test_no_cma_is_a_valid_answer(conn, fake_client, manitoba):
    load_fsa_centroids(conn)
    manitoba[layer_url("cma", "11")] = b'{"features": []}'
    geography.run(conn, fake_client(manitoba))
    assert "cma:11" not in conn.execute("SELECT detail FROM sources_log WHERE source = 'geography'").fetchone()[0]


def test_interior_point_of_a_concave_shape():
    # A "C": the centroid of the outline falls in the gap.
    ring = [(0, 0), (10, 0), (10, 2), (2, 2), (2, 8), (10, 8), (10, 10), (0, 10)]
    shape = Shape({}, [ring], (0, 0, 10, 10))
    x, y = interior_point(shape)
    assert contains(shape, x, y)
    assert not contains(shape, 6, 5)


def test_holes_are_outside():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    shape = Shape({}, [outer, hole], (0, 0, 10, 10))
    assert contains(shape, 1, 1) and not contains(shape, 5, 5)


def test_english_names():
    assert english("North / Nord") == "North"
    assert english("Ottawa - Gatineau (Ontario part / partie de l'Ontario)") == "Ottawa - Gatineau"
    assert english("Winnipeg") == "Winnipeg"
