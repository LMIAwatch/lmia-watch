"""The daily card's province map: projection, shading, boundary file, inset and layout edge cases."""

import io
import json
import math
import tomllib

import pytest
from PIL import Image, ImageDraw

from lmia_pipeline import config
from lmia_pipeline import social_card as sc

LON0 = -91.866667
EXPECTED_CODES = {"10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC", "35": "ON", "46": "MB",
                  "47": "SK", "48": "AB", "59": "BC", "60": "YT", "61": "NT", "62": "NU"}
ALL_13 = {"ON": 52, "QC": 41, "BC": 30, "AB": 21, "MB": 11, "SK": 9, "NS": 7, "NB": 5,
          "NL": 4, "PE": 3, "YT": 2, "NT": 1, "NU": 1}
ALL_TOP_NINE = {"ON": 38, "QC": 27, "BC": 22, "AB": 14, "MB": 5, "SK": 4, "NB": 2, "PE": 1, "YT": 1}


def card(counts, employers=None, **kw):
    return sc.CardData(
        date="2026-10-24", title="New on Job Bank, 2026-10-24", postings=kw.get("postings", 114),
        positions_line=kw.get("positions_line", "at least 12 positions"),
        context=kw.get("context", "Last 7 days: 40 postings, 120 positions"),
        province_counts=counts, employers=employers or [], site="lmiawatch.example",
    )


def render(c) -> Image.Image:
    return Image.open(io.BytesIO(sc.render_card(c)))


# -- projection and shading ----------------------------------------------------


def test_projection_follows_epsg_3347_axes():
    assert sc.lcc(LON0, 63.390675) == pytest.approx((0.0, 0.0), abs=1e-12)  # the origin
    assert sc.lcc(LON0, 55.0)[0] == pytest.approx(0.0, abs=1e-12)  # the central meridian is x = 0
    assert sc.lcc(-75.0, 55.0)[0] > 0 > sc.lcc(-110.0, 55.0)[0]  # east is positive x
    assert sc.lcc(LON0, 70.0)[1] > sc.lcc(LON0, 55.0)[1] > sc.lcc(LON0, 45.0)[1]  # north is larger y


def test_shading_bins():
    assert sc.shade(0, 38) == sc.ZERO
    assert sc.shade(-3, 38) == sc.ZERO
    assert sc.shade(1, 38) == sc.RAMP[0]  # one posting is visible, on the lightest step
    assert sc.shade(38, 38) == sc.NAVY == sc.RAMP[-1]
    assert sc.shade(1, 1) == sc.NAVY  # a night whose top is one: every province with a posting is dark
    steps = [sc.RAMP.index(sc.shade(n, 38)) for n in range(1, 39)]
    assert steps == sorted(steps) and set(steps) == set(range(len(sc.RAMP)))  # every step is reachable
    assert sc.shade(4, 16) == sc.RAMP[1] and sc.shade(9, 16) == sc.RAMP[2]  # exact bin edges round up


# -- the boundary file ----------------------------------------------------------


def test_boundary_file_has_the_thirteen_provinces_and_territories():
    data = json.loads((config.PACKAGE_DATA / "provinces_2021.json").read_text(encoding="utf-8"))
    feats = data["features"]
    assert len(feats) == 13
    assert {f["attributes"]["PRUID"]: sc.PROVINCE_CODES[f["attributes"]["PRUID"]] for f in feats} == EXPECTED_CODES
    for f in feats:
        rings = f["geometry"]["rings"]
        assert rings, f["attributes"]
        for ring in rings:
            assert len(ring) >= 4
            assert all(-141.1 <= x <= -52.0 and 41.0 <= y <= 84.0 for x, y in ring)
    assert sorted(code for code, _ in sc.provinces()) == sorted(EXPECTED_CODES.values())


def test_boundary_file_ships_with_the_package():
    pyproject = tomllib.loads((config.REPO_ROOT / "pipeline" / "pyproject.toml").read_text(encoding="utf-8"))
    assert "data/*.json" in pyproject["tool"]["setuptools"]["package-data"]["lmia_pipeline"]


# -- rendering --------------------------------------------------------------------


@pytest.mark.parametrize("counts", [
    {},
    {"ON": 3},
    {"PE": 1},
    {"": 2, "XX": 9, "ON": 1},
    ALL_13,
], ids=["empty", "one province", "one maritime", "unknown codes", "all thirteen"])
def test_card_renders_at_size_for_any_counts(counts):
    img = render(card(counts))
    assert img.size == (sc.WIDTH, sc.HEIGHT) == (1200, 675) and img.mode == "RGB"


def test_unknown_codes_are_ignored():
    assert sc.render_card(card({"": 2, "XX": 9, "ON": 1})) == sc.render_card(card({"ON": 1}))


def test_other_row_appears_past_nine_provinces():
    assert len(sc.bar_rows(ALL_13)) == sc.CARD_PROVINCES + 1 == 10
    assert sc.bar_rows(ALL_13)[-1] == ("Other", 3 + 2 + 1 + 1)
    nine = ALL_TOP_NINE
    assert len(sc.bar_rows(nine)) == 9 and all(code != "Other" for code, _ in sc.bar_rows(nine))
    # The tenth row sits above the footer and holds a bar only when "Other" exists.
    row10 = (sc.BARS_X, 182 + 9 * sc.BAR_ROW_H + 3, sc.WIDTH - sc.MARGIN, 182 + 9 * sc.BAR_ROW_H + 26)
    assert row10[3] < sc.HEIGHT - sc.FOOTER_H
    assert sc.NAVY in {c for _, c in render(card(ALL_13)).crop(row10).getcolors(10000)}
    assert render(card(nine)).crop(row10).getcolors(10000) == [((row10[2] - row10[0]) * (row10[3] - row10[1]), sc.WHITE)]



def _deepest_pei_pixel() -> tuple[int, int]:
    """The inset pixel inside PEI farthest from its edges (PEI is only a few pixels thick there)."""
    east = [s for s in sc.provinces() if s[0] in sc.MARITIMES]
    ipt = sc._fit(east, sc.INSET_BOX, pad=10)
    (_, rings), = [s for s in east if s[0] == "PE"]
    poly = [ipt(x, y) for x, y in max(rings, key=len)]
    edges = list(zip(poly, poly[1:] + poly[:1]))

    def inside(x, y):
        hit = False
        for (ax, ay), (bx, by) in edges:
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                hit = not hit
        return hit

    def edge_distance(x, y):
        best = math.inf
        for (ax, ay), (bx, by) in edges:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ((dx * dx + dy * dy) or 1)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
        return best

    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    candidates = [(edge_distance(px + 0.5, py + 0.5), px, py)
                  for px in range(int(min(xs)), int(max(xs)) + 1)
                  for py in range(int(min(ys)), int(max(ys)) + 1) if inside(px + 0.5, py + 0.5)]
    _, px, py = max(candidates)
    return px, py


def _nearest(colour):
    palette = [sc.WHITE, sc.INK, sc.MUTED, sc.RULE, sc.ZERO, *sc.RAMP]
    return min(palette, key=lambda p: max(abs(a - b) for a, b in zip(p, colour)))


def test_pei_is_shaded_in_the_inset():
    px, py = _deepest_pei_pixel()
    x0, y0, x1, y1 = sc.INSET_BOX
    assert x0 < px < x1 and y0 < py < y1
    # Scaling down from three times the size blends a pixel or two at each edge,
    # so the probe is matched to the nearest card colour.
    shaded = render(card({"PE": 5})).getpixel((px, py))
    assert _nearest(shaded) in sc.RAMP
    blank = render(card({})).getpixel((px, py))
    assert _nearest(blank) == sc.ZERO


def test_card_without_the_boundary_file_draws_no_map(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "BOUNDARY_FILE", tmp_path / "missing.json")
    img = render(card(ALL_TOP_NINE))
    assert img.size == (1200, 675)
    colours = {c for _, c in img.crop(sc.MAP_BOX).getcolors(100000)}
    assert sc.ZERO not in colours and not colours & set(sc.RAMP)


def test_four_employers_with_long_names_fit_the_column():
    names = ["Greenhouse Operations and Seasonal Agricultural Holdings of Southwestern Ontario Limited " * 2,
             "Les Entreprises de Transformation Alimentaire du Bas-Saint-Laurent inc.",
             "Short Ltd", "Pacific Northwest Mushroom and Berry Growers Cooperative", "Fifth Employer Inc"]
    emps = [sc.CardEmployer(n, "Saint-Jean-sur-Richelieu QC", 1210 - i) for i, n in enumerate(names)]
    c = card(ALL_13, emps, context="Last 7 days: 1,212 postings, at least 11,480 positions")
    img = render(c)
    # Nothing from the left column spills into the gutter before the map.
    gutter = img.crop((sc.MARGIN + sc.LEFT_W + 2, sc.HEADER_H + 1, sc.MAP_X - 2, sc.HEIGHT - sc.FOOTER_H - 1))
    assert gutter.getcolors(100000) == [(gutter.width * gutter.height, sc.WHITE)]
    alt = sc.alt_text(c)
    assert len(alt) <= 1000 and "Fifth Employer" not in alt and sc.CARD_EMPLOYERS == 4


# -- text --------------------------------------------------------------------------


def test_label_wraps_with_the_quoted_phrase_whole():
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = sc._font("regular", 24)
    assert sc._wrap(d, 'Postings newly flagged "LMIA requested"', f, sc.LEFT_W) == [
        "Postings newly flagged", '"LMIA requested"']
    lines = sc._wrap(d, "Offres nouvellement signalées « EIMT demandée » sur le Guichet-Emplois", f, 200)
    assert any("« EIMT demandée »" in line for line in lines)
    # A quote mark with no partner loses nothing.
    assert sc._wrap(d, 'a "b c', f, 1000) == ['a "b c']
    assert sc._wrap(d, 'a "b c', f, 1) == ["a", '"b', "c"]


def test_alt_text_mentions_the_map_and_keeps_the_limit():
    c = card(ALL_TOP_NINE, [sc.CardEmployer("Acme Farms", "Leamington ON", 40)])
    alt = sc.alt_text(c)
    assert alt.startswith("LMIA Watch daily card. New on Job Bank, 2026-10-24")
    assert "map of Canada" in alt and "inset of the Maritimes" in alt and "ON 38" in alt
    long = card(ALL_13, [sc.CardEmployer("N" * 400, "Place " * 20, 9)] * 5)
    assert len(sc.alt_text(long)) <= 1000
    assert "map of Canada" not in sc.alt_text(card({}))
