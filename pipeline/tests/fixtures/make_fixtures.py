"""Trim raw downloads under data/raw/ into small test fixtures.

Run from the pipeline directory after refreshing data/raw/:
    python tests/fixtures/make_fixtures.py
Only public web pages and open-data files are used.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import openpyxl

from lmia_pipeline.sources import lfs, vacancies

HERE = Path(__file__).resolve().parent
RAW = HERE.parents[2] / "data" / "raw"
WAGES_2025_URL = (
    "https://open.canada.ca/data/dataset/adad580f-76b0-4502-bd05-20c125de9116/resource/"
    "9da94d63-b178-4a64-aeb3-b6a3bd721ad2/download/2a71-das-wage2025opendata-esdc-all-19nov2025-vf.csv"
)

ARTICLE_RE = re.compile(r"<article[^>]*id=\"article-\d+\".*?</article>", re.S)
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def read_html(src: Path) -> str:
    data = src.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def trim_search(src: Path, dst: Path, keep: int = 4) -> None:
    html = read_html(src)
    articles = ARTICLE_RE.findall(html)
    first = html.find(articles[0])
    last_end = html.find(articles[-1]) + len(articles[-1])
    trimmed = html[:first] + "\n".join(articles[:keep]) + html[last_end:]
    dst.write_text(SCRIPT_RE.sub("", trimmed), encoding="utf-8")


def trim_detail(src: Path, dst: Path) -> None:
    dst.write_text(SCRIPT_RE.sub("", read_html(src)), encoding="utf-8")


def trim_xlsx(src: Path, dst: Path, keep: int = 40) -> None:
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    out = openpyxl.Workbook()
    ws = out.active
    for row in rows[: keep + 2] + rows[-3:]:
        ws.append(list(row))
    out.save(dst)


def trim_ircc(html_src: Path, json_src: Path, dst_html: Path, dst_json: Path) -> None:
    html = read_html(html_src)
    items = [m.group(0) for m in re.finditer(r"<(\w+)[^>]*id=\"list\d+\"[^>]*>.*?</\1>", html, re.S)]
    dst_html.write_text("<html><body><ol>" + "\n".join(items) + "</ol></body></html>", encoding="utf-8")
    data = json.loads(json_src.read_text(encoding="utf-8"))
    dst_json.write_text(json.dumps({"list": data["list"][:3]}, ensure_ascii=False, indent=1), encoding="utf-8")


def cached(url: str) -> Path:
    """The pipeline's cache file for a URL (http.PoliteClient keys it by sha1)."""
    return RAW / "cache" / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.bin"


# Regional figures (44101), provincial only in Manitoba (22101), national only
# (21103) and an occupation published at an annual rate (00010).
WAGE_NOCS = ("NOC_44101", "NOC_22101", "NOC_21103", "NOC_00010")


def trim_wages(src: Path, dst: Path) -> None:
    text = src.read_bytes().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    keep = [rows[0]] + [
        r for r in rows[1:]
        if r and r[0] in WAGE_NOCS and (r[4] == "ER00" or r[4].startswith("ER46") or r[4] in ("ER10", "ER1010"))
    ]
    with dst.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(keep)


LFS_GEOS = ("2021A000011124", "2021S05031", "2021S0503505", "2021S050535505", "2021S0503602")
LFS_MONTHS = {f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)}


def trim_lfs(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(src) as zf:
        text = zf.read("14100459.csv").decode("utf-8-sig")
        meta = zf.read("14100459_MetaData.csv")
    rows = list(csv.reader(io.StringIO(text)))
    keep = [rows[0]] + [
        r for r in rows[1:]
        if r[2] in LFS_GEOS and r[0] in LFS_MONTHS and r[3] in ("Unemployment rate", "Population")
        and r[4] in ("Estimate", "Standard error of estimate")
    ]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(keep)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("14100459.csv", out.getvalue().encode("utf-8"))
        zf.writestr("14100459_MetaData.csv", meta[:2000])


GEO_FSAS = {"R2H", "R3C", "R3T", "R0C", "R0G", "R0E", "R1A"}


def _thin(ring: list, limit: int = 120) -> list:
    step = max(1, len(ring) // limit)
    return [[round(x, 4), round(y, 4)] for x, y in ring[::step]]


def trim_geography(dst: Path) -> None:
    from lmia_pipeline.sources.geography import layer_url

    out: dict[str, dict] = {}
    for layer in ("er", "cma", "fsa"):
        data = json.loads(cached(layer_url(layer, "46")).read_bytes())
        feats = data["features"]
        if layer == "fsa":
            feats = [f for f in feats if f["attributes"]["CFSAUID"] in GEO_FSAS]
        for f in feats:
            # Small islands and lakes only add bytes; the tests place points on land.
            rings = sorted(f["geometry"]["rings"], key=len, reverse=True)
            f["geometry"] = {"rings": [_thin(r) for r in rings[:1] + [r for r in rings[1:] if len(r) >= 40]]}
        out[layer] = {"features": feats}
    dst.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


# Winnipeg, its province and Canada, one combined region, and a region with no
# Manitoba tie (Avalon Peninsula); cooks, wage-fixture occupations, a minor
# group (dropped) and the all-occupations total, ten quarters (eight kept).
VACANCY_GEOS = ("2021A000011124", "2021A000246", "2021S05004650", "2021S05001010", "")
VACANCY_COMBINED = "South Central and North Central, Manitoba"
VACANCY_NOCS = ("[63200]", "[44101]", "[22101]", "[4410]", "Total, all occupations")


def trim_vacancies(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(src) as zf:
        meta = zf.read("14100444_MetaData.csv")
        with zf.open("14100444.csv") as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            reader = csv.reader(text)
            keep = [next(reader)]
            for r in reader:
                if r[0] < "2024-01" or r[2] not in VACANCY_GEOS or (r[2] == "" and r[1] != VACANCY_COMBINED):
                    continue
                if any(r[3].endswith(code) or r[3] == code for code in VACANCY_NOCS):
                    keep.append(r)
    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(keep)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("14100444.csv", ("﻿" + out.getvalue()).encode("utf-8"))
        # The cube's title row is enough: it carries the last reference month.
        zf.writestr("14100444_MetaData.csv", meta.replace(b"\r\n", b"\n").split(b"\n\n")[0] + b"\n")


NOC_KEEP = {"6", "63", "632", "6320", "63200", "4", "44", "441", "4410", "44101", "2", "22", "221", "2210", "22101"}


def trim_noc(src: Path, dst: Path) -> None:
    # Some definitions hold line breaks inside quotes; the repository keeps LF only.
    lines = src.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").splitlines(keepends=True)
    rows = list(csv.reader(lines))
    keep = [rows[0]] + [r for r in rows[1:] if len(r) > 2 and r[2] in NOC_KEEP]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(keep)
    dst.write_bytes(("﻿" + out.getvalue()).encode("utf-8"))


def main() -> None:
    trim_search(RAW / "jobbank" / "jb_bc_requested.html", HERE / "jobbank_requested.html")
    trim_search(RAW / "jobbank" / "jb_bc_approved.html", HERE / "jobbank_approved.html")
    trim_detail(RAW / "jobbank" / "jb_50456228.html", HERE / "jobbank_detail_50456228.html")
    trim_detail(RAW / "jobbank" / "jb_50440025.html", HERE / "jobbank_detail_50440025.html")
    trim_xlsx(RAW / "esdc" / "tfwp_2026q1_pos_en.xlsx", HERE / "esdc_2026q1_pos_trim.xlsx")
    trim_xlsx(RAW / "esdc" / "tfwp_2026q1_neg_en.xlsx", HERE / "esdc_2026q1_neg_trim.xlsx")
    trim_ircc(RAW / "ircc" / "noncompliant.html", RAW / "ircc" / "non_compliant.json",
              HERE / "ircc_legend.html", HERE / "ircc_sample.json")
    # The next three read the pipeline's download cache, so run the wages,
    # lfs and geography stages once first.
    trim_wages(cached(WAGES_2025_URL), HERE / "wages_trim.csv")
    trim_lfs(cached(lfs.URL), HERE / "lfs_14100459_trim.zip")
    trim_geography(HERE / "geography_mb.json")
    # These two read the cache the vacancies stage fills.
    trim_vacancies(cached(vacancies.URL), HERE / "vacancies_14100444_trim.zip")
    trim_noc(cached(vacancies.NOC_URLS["en"]), HERE / "noc2021_en_trim.csv")
    trim_noc(cached(vacancies.NOC_URLS["fr"]), HERE / "noc2021_fr_trim.csv")
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
