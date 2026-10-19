import xml.etree.ElementTree as ET

from lmia_pipeline import config, export_static, status
from lmia_pipeline.db import upsert_employer

NS = {"sm": export_static.SITEMAP_NS}
BASE = "https://lmiawatch.ca"
NOW = "2026-10-12T00:00:00Z"


def seed(conn, n: int) -> list[str]:
    ids = [upsert_employer(conn, f"Employer {i:03d} Ltd", "BC", source="esdc_positive", city="Kelowna", now=NOW)
           for i in range(n)]
    status.recompute(conn, now=NOW)
    return sorted(ids)


def parse(path):
    root = ET.parse(path).getroot()  # raises on malformed XML
    return root


def locs(root, tag):
    return [(e.findtext("sm:loc", namespaces=NS), e.findtext("sm:lastmod", namespaces=NS))
            for e in root.findall(f"sm:{tag}", NS)]


def test_parts_respect_the_limit_and_the_index_lists_them(conn, tmp_path):
    ids = seed(conn, 3)
    conn.execute("UPDATE employers SET updated_at = '2026-10-15T03:00:00Z' WHERE id = ?", (ids[2],))
    counts = export_static.write_sitemaps(conn, tmp_path, BASE + "/", "2026-10-12", max_urls=4)

    # 7 fixed pages, the feeds and watchlist pages and 3 profiles, four to a file.
    assert counts == {"sitemap_files": 3, "sitemap_urls": 12}
    parts = [locs(parse(tmp_path / "sitemaps" / f"sitemap-{n}.xml"), "url") for n in (1, 2, 3)]
    assert [len(p) for p in parts] == [4, 4, 4]
    assert not (tmp_path / "sitemaps" / "sitemap-4.xml").exists()

    flat = [entry for part in parts for entry in part]
    urls = [u for u, _ in flat]
    assert urls[:7] == [BASE + p for p in export_static.SITEMAP_PAGES]
    assert urls[7:9] == [BASE + "/feeds", BASE + "/watchlist"]
    assert urls[9:] == [f"{BASE}/employers/{i}" for i in ids]
    assert len(set(urls)) == len(urls)
    assert all("?" not in u for u in urls)

    lastmod = dict(flat)
    assert lastmod[BASE + "/"] == "2026-10-12" and lastmod[BASE + "/data"] == "2026-10-12"
    # Pages that change only with the code carry no date at all.
    assert lastmod[BASE + "/methodology"] is None and lastmod[BASE + "/corrections"] is None
    assert lastmod[f"{BASE}/employers/{ids[0]}"] == "2026-10-12"
    assert lastmod[f"{BASE}/employers/{ids[2]}"] == "2026-10-15"
    assert lastmod[BASE + "/feeds"] == "2026-10-12" and lastmod[BASE + "/watchlist"] is None

    index = parse(tmp_path / "sitemaps" / "index.xml")
    assert index.tag == f"{{{export_static.SITEMAP_NS}}}sitemapindex"
    # Parts are named at the site root, where the Worker serves them.
    assert locs(index, "sitemap") == [
        (f"{BASE}/sitemap-1.xml", "2026-10-12"),
        (f"{BASE}/sitemap-2.xml", "2026-10-12"),
        (f"{BASE}/sitemap-3.xml", "2026-10-15"),
    ]


def test_full_size_split():
    # The live profile count: 168,000 profiles plus the fixed pages fit in four files.
    entries = list(range(168_000 + len(export_static.SITEMAP_PAGES)))
    chunks = export_static.sitemap_chunks(entries)
    assert [len(c) for c in chunks] == [50_000, 50_000, 50_000, 18_007]
    assert export_static.sitemap_chunks(list(range(50_000))) == [list(range(50_000))]


def test_lastmod_accepts_dates_only():
    assert export_static._lastmod("2026-10-12T09:10:00Z") == "2026-10-12"
    assert export_static._lastmod("2026-10-12") == "2026-10-12"
    assert export_static._lastmod(None) is None
    assert export_static._lastmod("") is None
    assert export_static._lastmod("pending") is None


def test_static_export_writes_the_sitemaps(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", BASE)
    ids = seed(conn, 3)
    counts = export_static.export_static(conn, tmp_path / "static")
    assert counts["sitemap_files"] == 1 and counts["sitemap_urls"] == 12
    part = parse(tmp_path / "static" / "sitemaps" / "sitemap-1.xml")
    assert part.tag == f"{{{export_static.SITEMAP_NS}}}urlset"
    urls = [u for u, _ in locs(part, "url")]
    assert urls == [BASE + p for p in export_static.SITEMAP_PAGES + ["/feeds", "/watchlist"]] + [f"{BASE}/employers/{i}" for i in ids]
    text = (tmp_path / "static" / "sitemaps" / "index.xml").read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex ')
    assert f"<loc>{BASE}/sitemap-1.xml</loc>" in text
