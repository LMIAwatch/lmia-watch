"""2021 Census geography for postal areas: economic region and census metropolitan area.

Source: Statistics Canada, 2021 Census cartographic boundary files (economic
regions, census metropolitan areas and agglomerations, forward sortation
areas), Statistics Canada Open Licence
(https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm).
The zipped shapefiles on that page sit behind a browser challenge that a
plain client cannot pass, so the same layers are read from Statistics
Canada's map service for those files (SERVICE below) as JSON polygons: one
request per province or territory per layer, simplified by the server to
about 200 m (1 km in the territories). The service fails some requests with
HTTP 500 and succeeds on a retry, so the stage uses a client with more
attempts. Responses are cached for good, since census boundaries are fixed,
and once the table is built for the current centroids the stage makes no
requests at all (the nightly runner's download cache does not survive).

Each forward sortation area gets one point: its GeoNames centroid when that
lies inside the area's own 2021 boundary, otherwise an interior point of the
boundary (about one area in ten, mostly where the GeoNames point sits in
water or in a neighbouring area). The point is placed in an economic region
and, when it falls inside one, a census metropolitan area. An area that
straddles a boundary goes wholly to the side its point falls on. The table
is rebuilt only when the cached responses or the centroids change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from urllib.parse import urlencode

from ..db import get_meta, log_run, set_meta
from ..http import FetchError, PoliteClient

log = logging.getLogger(__name__)

SERVICE = "https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer"
# layer key -> (layer id in the service, fields, extra filter)
LAYERS: dict[str, tuple[int, str, str]] = {
    "er": (2, "ERUID,ERNAME,PRUID", ""),
    "cma": (6, "CMAUID,CMANAME,PRUID", " AND CMATYPE='B'"),  # B = census metropolitan area
    "fsa": (14, "CFSAUID,PRUID", ""),
}
PRUIDS = ["10", "11", "12", "13", "24", "35", "46", "47", "48", "59", "60", "61", "62"]
TERRITORIES = {"60", "61", "62"}
OFFSET_DEG = "0.002"
TERRITORY_OFFSET_DEG = "0.01"
NEAREST_KM = 10.0
MAX_ATTEMPTS = 8
# Part of the rebuild signature: bump it when derive() changes so the table is rebuilt.
DERIVATION_VERSION = "1"


def layer_url(layer: str, pruid: str) -> str:
    lid, fields, extra = LAYERS[layer]
    params = {
        "where": f"PRUID='{pruid}'{extra}",
        "outFields": fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": TERRITORY_OFFSET_DEG if pruid in TERRITORIES else OFFSET_DEG,
        "geometryPrecision": "5",
        "f": "json",
    }
    return f"{SERVICE}/{lid}/query?{urlencode(params)}"


# -- polygons ----------------------------------------------------------------------

@dataclass
class Shape:
    attrs: dict
    rings: list[list[tuple[float, float]]]
    bbox: tuple[float, float, float, float]


def shapes(features: list[dict]) -> list[Shape]:
    out: list[Shape] = []
    for f in features:
        rings = [[(float(x), float(y)) for x, y, *_ in ring] for ring in (f.get("geometry") or {}).get("rings", [])]
        rings = [r for r in rings if len(r) >= 3]
        if not rings:
            continue
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        out.append(Shape(f.get("attributes") or {}, rings, (min(xs), min(ys), max(xs), max(ys))))
    return out


def _edges(ring: list[tuple[float, float]]):
    return zip(ring, ring[1:] + ring[:1])


def contains(shape: Shape, x: float, y: float) -> bool:
    """Even-odd test over every ring, so holes and multi-part areas need no special case."""
    x0, y0, x1, y1 = shape.bbox
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    inside = False
    for ring in shape.rings:
        for (ax, ay), (bx, by) in _edges(ring):
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
    return inside


def locate(candidates: list[Shape], x: float, y: float) -> Shape | None:
    for shape in candidates:
        if contains(shape, x, y):
            return shape
    return None


def _segment_km(x: float, y: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    kx = 111.32 * math.cos(math.radians(y))
    ky = 110.57
    ax, ay = (a[0] - x) * kx, (a[1] - y) * ky
    bx, by = (b[0] - x) * kx, (b[1] - y) * ky
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py)


def nearest(candidates: list[Shape], x: float, y: float, max_km: float = NEAREST_KM) -> tuple[Shape, float] | None:
    """The shape whose edge is closest to the point within max_km, with the distance in km.
    Used for points that fall just offshore, where the cartographic files stop at the coast."""
    pad = max_km / 100.0 + 0.05
    best: tuple[Shape, float] | None = None
    for shape in candidates:
        x0, y0, x1, y1 = shape.bbox
        if not (x0 - 2 * pad <= x <= x1 + 2 * pad and y0 - pad <= y <= y1 + pad):
            continue
        for ring in shape.rings:
            for a, b in _edges(ring):
                d = _segment_km(x, y, a, b)
                if d <= max_km and (best is None or d < best[1]):
                    best = (shape, d)
    return best


def _ring_area_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in _edges(ring):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area == 0:
        return 0.0, ring[0][0], ring[0][1]
    return area / 2, cx / (3 * area), cy / (3 * area)


def interior_point(shape: Shape) -> tuple[float, float]:
    """The centroid of the largest part when it lies inside, else the middle of the widest
    span of the horizontal line through that centroid, which is inside by construction."""
    largest = max(shape.rings, key=lambda r: abs(_ring_area_centroid(r)[0]))
    _, cx, cy = _ring_area_centroid(largest)
    if contains(shape, cx, cy):
        return cx, cy
    y = cy
    if any(py == y for ring in shape.rings for _, py in ring):
        y += 1e-7
    xs = sorted(
        ax + (y - ay) * (bx - ax) / (by - ay)
        for ring in shape.rings
        for (ax, ay), (bx, by) in _edges(ring)
        if (ay > y) != (by > y)
    )
    spans = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]
    if not spans:
        return cx, cy
    a, b = max(spans, key=lambda s: s[1] - s[0])
    return (a + b) / 2, y


def english(name: str | None) -> str | None:
    """'North / Nord' -> 'North'; "Ottawa - Gatineau (Ontario part / ...)" -> 'Ottawa - Gatineau'."""
    if not name:
        return None
    text = name.split(" / ")[0]
    if " (" in text:
        text = text.split(" (")[0]
    return text.strip() or None


# -- the stage -----------------------------------------------------------------------

def fetch_layers(client: PoliteClient) -> tuple[dict[str, list[dict]], str, list[str]]:
    """Every layer piece from the cache or the service; returns features, a digest, missing pieces."""
    features: dict[str, list[dict]] = {k: [] for k in LAYERS}
    digest = hashlib.sha256()
    missing: list[str] = []
    for layer in LAYERS:
        for pruid in PRUIDS:
            url = layer_url(layer, pruid)
            try:
                data = client.get(url, cache=True, max_age_s=float("inf"), timeout=300)
            except FetchError as exc:
                log.warning("boundary %s %s: %s", layer, pruid, exc)
                missing.append(f"{layer}:{pruid}")
                continue
            try:
                # An empty list is a real answer: PEI and the territories have no CMA.
                items = list(json.loads(data.decode("utf-8"))["features"])
            except (ValueError, KeyError, TypeError) as exc:
                # An error body arrives with HTTP 200; drop it so the next run asks again.
                client.forget(url)
                log.warning("boundary %s %s unusable: %s", layer, pruid, exc)
                missing.append(f"{layer}:{pruid}")
                continue
            digest.update(url.encode("utf-8"))
            digest.update(hashlib.sha256(data).digest())
            features[layer].extend(items)
    return features, digest.hexdigest(), missing


def derive(conn: sqlite3.Connection, features: dict[str, list[dict]]) -> int:
    """Rebuild fsa_regions from the layers and the centroid table; returns areas written."""
    regions = shapes(features.get("er", []))
    metros = shapes(features.get("cma", []))
    fsa_shapes = {str(s.attrs.get("CFSAUID", "")).upper(): s for s in shapes(features.get("fsa", []))}
    centroids = {r["fsa"]: (float(r["lon"]), float(r["lat"])) for r in conn.execute("SELECT fsa, lat, lon FROM fsa_centroids")}
    rows = []
    for code in sorted(set(centroids) | set(fsa_shapes)):
        if not code:
            continue
        shape = fsa_shapes.get(code)
        point = centroids.get(code)
        if point is not None and shape is not None and contains(shape, *point):
            method = "centroid"
        elif shape is not None:
            point = interior_point(shape)
            method = "boundary"
        elif point is not None:
            method = "centroid_unchecked"
        else:
            continue
        x, y = point
        region = locate(regions, x, y)
        metro = locate(metros, x, y)
        if region is None:
            # Offshore: take the closest region, and the closest metropolitan
            # area when its edge is about as close as that region's.
            hit = nearest(regions, x, y)
            if hit is not None:
                region, distance = hit
                method += "+nearest"
                near_metro = nearest(metros, x, y, distance + 1.0)
                metro = near_metro[0] if near_metro else None
        rows.append((
            code,
            region.attrs.get("ERUID") if region else None,
            english(region.attrs.get("ERNAME")) if region else None,
            str(metro.attrs.get("CMAUID")).zfill(3) if metro else None,
            english(metro.attrs.get("CMANAME")) if metro else None,
            round(y, 5),
            round(x, 5),
            method,
        ))
    conn.execute("DELETE FROM fsa_regions")
    conn.executemany(
        "INSERT INTO fsa_regions (fsa, er_uid, er_name, cma_uid, cma_name, lat, lon, method) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def run(conn: sqlite3.Connection, client: PoliteClient) -> int:
    centroid_sig = hashlib.sha256(
        "".join(f"{r['fsa']},{r['lat']},{r['lon']};" for r in conn.execute("SELECT fsa, lat, lon FROM fsa_centroids ORDER BY fsa")).encode()
    ).hexdigest()
    build = hashlib.sha256(f"{DERIVATION_VERSION}|{centroid_sig}".encode()).hexdigest()
    have_rows = conn.execute("SELECT COUNT(*) FROM fsa_regions").fetchone()[0]
    # The nightly runner starts with an empty download cache, so the decision
    # to fetch rests on the database: a complete build for these centroids
    # and this derivation is never fetched again.
    if have_rows and get_meta(conn, "geography_build") == build and get_meta(conn, "geography_missing") == "":
        log_run(conn, "geography", detail=f"skipped: built; areas={have_rows}", rows_in=have_rows)
        return 0
    features, digest, missing = fetch_layers(client)
    signature = hashlib.sha256(f"{build}|{digest}".encode()).hexdigest()
    written = 0
    if features["er"] and (get_meta(conn, "geography_sha") != signature or not have_rows):
        written = derive(conn, features)
        set_meta(conn, "geography_sha", signature)
    if features["er"]:
        set_meta(conn, "geography_build", build)
        set_meta(conn, "geography_missing", ",".join(missing))
    conn.commit()
    counts = conn.execute(
        "SELECT COUNT(*), SUM(er_uid IS NOT NULL), SUM(cma_uid IS NOT NULL) FROM fsa_regions"
    ).fetchone()
    detail = f"areas={counts[0]} in_region={counts[1] or 0} in_cma={counts[2] or 0} rebuilt={written}"
    if missing:
        detail += " missing=" + ",".join(missing)
    log_run(conn, "geography", detail=detail, rows_in=counts[0], rows_new=written, ok=not missing)
    return written
