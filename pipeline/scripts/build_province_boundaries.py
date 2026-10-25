"""Build lmia_pipeline/data/provinces_2021.json, the outlines on the daily card's map.

Source: Statistics Canada, 2021 Census cartographic boundary file for
provinces and territories, under the Statistics Canada Open Licence
(https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm).
The zipped shapefiles on that page sit behind a browser challenge, so the
layer is read the way lmia_pipeline/sources/geography.py reads the others:
from layer 0 of Statistics Canada's map service for those files, as JSON
rings in longitude and latitude (EPSG:4326), one request per province or
territory, generalized by the server (0.05 degrees, or 0.005 for the three
Maritime provinces, which the card's inset enlarges) and rounded to three
decimals (about 12 MB in all; the whole country in one request fails).

The card is 1200 pixels wide, so the outlines are cut down to about 150 KB:
rings whose longitude/latitude bounding box covers less than 0.15 square
degrees are dropped (the small islands; the large Arctic islands stay), each
remaining ring is opened at the point farthest from its start and both halves
are simplified with Douglas-Peucker at 0.03 degrees (0.005 for the Maritimes),
coordinates are rounded
to three decimals, and rings left with fewer than four points are dropped.
The output keeps each feature's PRUID and PRENAME and is written as compact
JSON. The same raw response always gives the same bytes.

Usage: python scripts/build_province_boundaries.py [--from PATH] [--out PATH] [--save-raw PATH]
  --from PATH      read a saved raw response (the features of all thirteen) instead of downloading
  --save-raw PATH  keep the downloaded features as one raw response (do not commit it)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from lmia_pipeline import config
from lmia_pipeline.sources.geography import MAX_ATTEMPTS, PRUIDS, SERVICE

LAYER = 0  # provinces and territories
FINE = {"11", "12", "13"}  # PE, NS, NB: enlarged in the card's inset, so kept in finer detail
OFFSET_DEG = {"coarse": "0.05", "fine": "0.005"}  # the server's own generalization, before the steps below
MIN_RING_AREA = 0.15  # square degrees of bounding box
TOLERANCE = {"coarse": 0.03, "fine": 0.005}  # degrees, Douglas-Peucker


def detail(pruid: str) -> str:
    return "fine" if pruid in FINE else "coarse"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "lmia_pipeline" / "data" / "provinces_2021.json"


def query_url(pruid: str) -> str:
    params = {
        "where": f"PRUID='{pruid}'",
        "outFields": "PRUID,PRENAME",
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": OFFSET_DEG[detail(pruid)],
        "geometryPrecision": "3",
        "f": "json",
    }
    return f"{SERVICE}/{LAYER}/query?{urlencode(params)}"


def fetch_features(pruid: str) -> list[dict]:
    """One province or territory. The service fails some requests with HTTP 500, or
    with an error body under HTTP 200, and succeeds on a retry."""
    url = query_url(pruid)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=300)
            resp.raise_for_status()
            features = json.loads(resp.content)["features"]
            if features:
                return features
            raise ValueError("no features")
        except (requests.RequestException, ValueError, KeyError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(f"PRUID {pruid}: no answer after {MAX_ATTEMPTS} attempts ({exc})")
            print(f"PRUID {pruid}: attempt {attempt} failed ({str(exc)[:80]}); retrying", file=sys.stderr)
            time.sleep(3 * attempt)
    raise AssertionError("unreachable")


def download() -> bytes:
    features: list[dict] = []
    for pruid in PRUIDS:
        features.extend(fetch_features(pruid))
        time.sleep(config.DEFAULT_DELAY)
    return json.dumps({"features": features}, separators=(",", ":")).encode("utf-8")


def dp(points: list, tol: float) -> list:
    """Douglas-Peucker on an open polyline; keeps both ends."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    best, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        dist = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / norm
        if dist > best:
            best, idx = dist, i
    if best > tol:
        return dp(points[: idx + 1], tol)[:-1] + dp(points[idx:], tol)
    return [points[0], points[-1]]


def simplify(raw: dict) -> dict:
    out: dict = {"features": []}
    for f in raw["features"]:
        tol = TOLERANCE[detail(f["attributes"]["PRUID"])]
        kept = []
        for ring in f["geometry"]["rings"]:
            ring = [(p[0], p[1]) for p in ring]
            if len(ring) < 3:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if (max(xs) - min(xs)) * (max(ys) - min(ys)) < MIN_RING_AREA:
                continue
            # A ring closes on its first point, which gives Douglas-Peucker a zero-length
            # baseline; open it at the point farthest from the start and simplify the halves.
            x0, y0 = ring[0]
            k = max(range(1, len(ring) - 1), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
            simple = dp(ring[: k + 1], tol)[:-1] + dp(ring[k:], tol)
            if len(simple) >= 4:
                kept.append([[round(x, 3), round(y, 3)] for x, y in simple])
        out["features"].append({"attributes": f["attributes"], "geometry": {"rings": kept}})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", help="a saved raw response to read instead of downloading")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--save-raw", help="where to keep the downloaded raw response")
    args = parser.parse_args(argv)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))  # Douglas-Peucker recurses per split

    if args.source:
        data = Path(args.source).read_bytes()
    else:
        data = download()
        if args.save_raw:
            Path(args.save_raw).write_bytes(data)
    out = simplify(json.loads(data))
    text = json.dumps(out, separators=(",", ":"))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    for f in out["features"]:
        rings = f["geometry"]["rings"]
        print(f["attributes"]["PRUID"], f["attributes"]["PRENAME"][:22].ljust(22),
              "rings", len(rings), "points", sum(len(r) for r in rings))
    print(f"wrote {len(out['features'])} features, {len(text) // 1024} KB, to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
