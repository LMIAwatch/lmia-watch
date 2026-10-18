"""Build lmia_pipeline/data/fsa_centroids.csv from GeoNames postal data.

Source: https://download.geonames.org/export/zip/CA.zip, the GeoNames postal
code dataset, licensed Creative Commons Attribution 4.0. The Canadian file
holds one row per forward sortation area (the first three characters of a
postal code) with a latitude and longitude. Statistics Canada's 2021 FSA
boundary file would be the authoritative source, but its download sits behind
a browser challenge that a plain client cannot pass, so GeoNames is used with
attribution. Rows whose coordinates fall outside Canada are dropped.

Usage: python scripts/build_fsa_centroids.py [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

URL = "https://download.geonames.org/export/zip/CA.zip"
USER_AGENT = "LMIAWatch/0.1 (+https://lmiawatch.example; ops@lmiawatch.example)"
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 41.0, 84.0, -141.1, -52.0
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "lmia_pipeline" / "data" / "fsa_centroids.csv"

# Canada Post assigns the first letter of a postal code to a province. The
# three X0A to X0C areas are Nunavut; the rest of X is the Northwest Territories.
LETTER_PROVINCE = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC",
    "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK",
    "T": "AB", "V": "BC", "X": "NT", "Y": "YT",
}


def province_for(fsa: str) -> str | None:
    if fsa in ("X0A", "X0B", "X0C"):
        return "NU"
    return LETTER_PROVINCE.get(fsa[0])


def build(data: bytes) -> list[tuple[str, str, float, float]]:
    rows: dict[str, tuple[str, str, float, float]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read("CA.txt").decode("utf-8")
    for parts in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(parts) < 11:
            continue
        fsa = parts[1].strip().upper()[:3]
        if len(fsa) != 3:
            continue
        try:
            lat, lon = float(parts[9]), float(parts[10])
        except ValueError:
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue
        province = province_for(fsa)
        if not province or fsa in rows:
            continue
        rows[fsa] = (fsa, province, round(lat, 5), round(lon, 5))
    return sorted(rows.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=120)
    resp.raise_for_status()
    rows = build(resp.content)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        fh.write(f"# Source: GeoNames postal codes, CC BY 4.0, {URL}, built {date.today().isoformat()}\n")
        fh.write("# One row per forward sortation area; coordinates are area centroids, never addresses.\n")
        writer = csv.writer(fh)
        writer.writerow(["fsa", "province", "lat", "lon"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} areas to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
