"""Trim raw downloads under data/raw/ into small test fixtures.

Run from the pipeline directory after refreshing data/raw/:
    python tests/fixtures/make_fixtures.py
Only public web pages and open-data files are used.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
RAW = HERE.parents[2] / "data" / "raw"

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


def main() -> None:
    trim_search(RAW / "jobbank" / "jb_bc_requested.html", HERE / "jobbank_requested.html")
    trim_search(RAW / "jobbank" / "jb_bc_approved.html", HERE / "jobbank_approved.html")
    trim_detail(RAW / "jobbank" / "jb_50456228.html", HERE / "jobbank_detail_50456228.html")
    trim_detail(RAW / "jobbank" / "jb_50440025.html", HERE / "jobbank_detail_50440025.html")
    trim_xlsx(RAW / "esdc" / "tfwp_2026q1_pos_en.xlsx", HERE / "esdc_2026q1_pos_trim.xlsx")
    trim_xlsx(RAW / "esdc" / "tfwp_2026q1_neg_en.xlsx", HERE / "esdc_2026q1_neg_trim.xlsx")
    trim_ircc(RAW / "ircc" / "noncompliant.html", RAW / "ircc" / "non_compliant.json",
              HERE / "ircc_legend.html", HERE / "ircc_sample.json")
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
