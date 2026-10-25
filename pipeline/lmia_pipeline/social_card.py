"""The image attached to the daily X post: a 1200 by 675 card drawn with Pillow.

Why an image at all: X bills a post that contains a URL at thirteen times the
rate of one that does not, and bills nothing extra for an attached image. The
card carries the site address and the full breakdown (postings by province,
the employers with the most positions) that the 280-character text cannot.

Why Pillow and not a plotting library: the card is rectangles, polygons and
text, and Pillow is already needed for the icons. It keeps the nightly install
small.

The map: Statistics Canada's 2021 province and territory boundaries
(data/provinces_2021.json, built by scripts/build_province_boundaries.py),
drawn in Statistics Canada's own Lambert conformal conic (EPSG:3347) so the
country has the shape readers know, and shaded by the night's postings. The
Maritime provinces are a few pixels across at that scale, so an inset repeats
them enlarged. When the boundary file cannot be read the card is drawn
without the map.

The typeface is Public Sans (the site's own), read from brand/fonts in the
checkout; Pillow's built-in font stands in if those files are missing, so a
missing font can never stop a post.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from . import config

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1200, 675
NAVY = (0x1C, 0x3D, 0x6A)
INK = (0x0B, 0x0C, 0x0C)
MUTED = (0x4F, 0x5A, 0x60)
RULE = (0xB1, 0xB4, 0xB6)
PANEL = (0xF3, 0xF3, 0xF1)
WHITE = (255, 255, 255)
MARGIN = 48
HEADER_H = 96
FOOTER_H = 60
CARD_EMPLOYERS = 4
CARD_PROVINCES = 9

# Columns: the headline and employers, then the map, then the province bars.
LEFT_W = 380
MAP_X = 456
BARS_X = 884
EMPLOYER_ROW_H = 46
BAR_ROW_H = 40

# The site mark on its 32-unit grid (the same rectangles as site/public/favicon.svg).
MARK_FRAME = (4, 6, 28, 26)
MARK_HOLES = [(6, 8, 12, 12), (14, 8, 26, 12), (6, 14, 12, 18), (6, 20, 12, 24), (14, 20, 26, 24)]

FONT_DIR = config.REPO_ROOT / "brand" / "fonts"
FONT_FILES = {"regular": "PublicSans-Regular.ttf", "semibold": "PublicSans-SemiBold.ttf", "bold": "PublicSans-Bold.ttf"}

# -- the map ---------------------------------------------------------------------

BOUNDARY_FILE = config.PACKAGE_DATA / "provinces_2021.json"
# Statistics Canada's province and territory codes (PRUID) to the postal abbreviations.
PROVINCE_CODES = {"10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC", "35": "ON", "46": "MB",
                  "47": "SK", "48": "AB", "59": "BC", "60": "YT", "61": "NT", "62": "NU"}
KNOWN_CODES = frozenset(PROVINCE_CODES.values())

# A single-hue ramp toward the card's navy; zero postings is a flat grey. Every
# step is one a count can reach, so the legend shows nothing the map cannot.
ZERO = (0xE6, 0xE7, 0xE4)
RAMP = [(0x9D, 0xB3, 0xD1), (0x6B, 0x8B, 0xB8), (0x3E, 0x62, 0x95), NAVY]

MAP_BOX = (MAP_X, 180, 866, 562)
INSET_BOX = (716, 180, 866, 296)  # top right of the map box, over the Arctic islands
MARITIMES = ("NB", "PE", "NS")
SCALE = 3  # polygons are drawn at three times the size and scaled down, for smooth edges

# Label anchors (longitude, latitude) on the main map, in drawing order. The
# prairie labels are staggered (SK sits lower) so they fit side by side, and
# BC's sits inland. The Maritimes are labelled in the inset instead.
MAP_LABELS = {"BC": (-123.6, 55.4), "AB": (-115.0, 55.6), "SK": (-105.8, 51.6), "MB": (-97.8, 55.4),
              "ON": (-86.2, 50.2), "QC": (-71.8, 52.6), "NL": (-61.5, 53.6), "YT": (-135.4, 64.0),
              "NT": (-119.5, 65.2), "NU": (-96.0, 66.5)}
# In the inset PEI is too narrow for its code, which sits above it in the Gulf, and
# NS too thin, so its code sits below it; a label on the water is always dark ink.
INSET_LABELS = {"NB": ((-66.5, 46.6), False), "NS": ((-64.9, 44.0), True), "PE": ((-63.2, 47.3), True)}

# Lambert conformal conic on the unit sphere with EPSG:3347's parameters:
# standard parallels 49 and 77, latitude of origin 63.390675, central meridian -91.866667.
_LAT1, _LAT2, _LAT0, _LON0 = map(math.radians, (49.0, 77.0, 63.390675, -91.866667))
_N = math.log(math.cos(_LAT1) / math.cos(_LAT2)) / math.log(
    math.tan(math.pi / 4 + _LAT2 / 2) / math.tan(math.pi / 4 + _LAT1 / 2))
_F = math.cos(_LAT1) * math.tan(math.pi / 4 + _LAT1 / 2) ** _N / _N
_RHO0 = _F / math.tan(math.pi / 4 + _LAT0 / 2) ** _N

Point = tuple[float, float]
Shape = tuple[str, tuple[tuple[Point, ...], ...]]  # (province code, projected rings)


def lcc(lon: float, lat: float) -> Point:
    """Projected x (east) and y (north) of a longitude and latitude."""
    rho = _F / math.tan(math.pi / 4 + math.radians(lat) / 2) ** _N
    theta = _N * (math.radians(lon) - _LON0)
    return rho * math.sin(theta), _RHO0 - rho * math.cos(theta)


@lru_cache(maxsize=2)
def _load_provinces(path: Path) -> tuple[Shape, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            (PROVINCE_CODES[f["attributes"]["PRUID"]],
             tuple(tuple(lcc(x, y) for x, y in ring) for ring in f["geometry"]["rings"]))
            for f in data["features"]
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("card map left out: boundary file %s unusable (%s)", path.name, exc)
        return ()


def provinces() -> tuple[Shape, ...]:
    """Every province and territory with its rings projected, or () when the file cannot be read."""
    return _load_provinces(BOUNDARY_FILE)


def shade(n: int, top: int) -> tuple:
    """The fill for a count: grey for none, then steps on a square-root scale,
    so one posting and forty are both visible."""
    if n <= 0:
        return ZERO
    if top <= 1:
        return RAMP[-1]
    k = int(math.sqrt(n / top) * len(RAMP) + 0.999)  # a ceiling with a little slack
    return RAMP[min(max(k, 1), len(RAMP)) - 1]


def _fit(shapes, box: tuple, pad: int = 0) -> Callable[[float, float], Point]:
    """A function from projected units to card pixels that centres the shapes in box."""
    x0, y0, x1, y1 = box
    xs = [p[0] for _, rings in shapes for ring in rings for p in ring]
    ys = [p[1] for _, rings in shapes for ring in rings for p in ring]
    mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
    s = min((x1 - x0 - 2 * pad) / (mxx - mnx), (y1 - y0 - 2 * pad) / (mxy - mny))
    ox = x0 + pad + ((x1 - x0 - 2 * pad) - (mxx - mnx) * s) / 2
    oy = y0 + pad + ((y1 - y0 - 2 * pad) - (mxy - mny) * s) / 2

    def pt(x: float, y: float) -> Point:
        return ox + (x - mnx) * s, oy + (mxy - y) * s
    return pt


def _paint(img: Image.Image, shapes, counts: dict[str, int], top: int, pt, region: tuple) -> None:
    """Fill the shapes, with white outlines, into region (x0, y0, x1, y1) of img. Only
    the region is drawn at SCALE; anything outside it is cut off."""
    rx0, ry0, rx1, ry1 = region
    k = SCALE
    layer = Image.new("RGBA", ((rx1 - rx0) * k, (ry1 - ry0) * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for code, rings in shapes:
        fill = shade(counts.get(code, 0), top)
        for ring in rings:
            pts = [((px - rx0) * k, (py - ry0) * k) for px, py in (pt(x, y) for x, y in ring)]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=WHITE, width=2)
    small = layer.resize((rx1 - rx0, ry1 - ry0), Image.LANCZOS)
    img.paste(small, (rx0, ry0), small)


def _halo_text(d: ImageDraw.ImageDraw, xy: Point, code: str, font, dark: bool, anchor: str) -> None:
    d.text(xy, code, font=font, fill=WHITE if dark else INK, anchor=anchor,
           stroke_width=2, stroke_fill=NAVY if dark else WHITE)


def _draw_map(img: Image.Image, d: ImageDraw.ImageDraw, counts: dict[str, int]) -> None:
    """The legend, the main map, the Maritimes inset and the inset's extent on the main map."""
    shapes = provinces()
    if not shapes:
        return
    top = max(counts.values(), default=0)
    if top:
        _legend(d, MAP_X, HEIGHT - FOOTER_H - 26, top)

    # Main map, labelled with codes only (the bars carry the numbers).
    pt = _fit(shapes, MAP_BOX)
    m = 8  # room for the scaled-down edges just outside the box
    _paint(img, shapes, counts, top, pt,
           (max(MAP_BOX[0] - m, 0), max(MAP_BOX[1] - m, 0), min(MAP_BOX[2] + m, WIDTH), min(MAP_BOX[3] + m, HEIGHT)))
    f_lab = _font("semibold", 17)
    for code, (lon, lat) in MAP_LABELS.items():
        _halo_text(d, pt(*lcc(lon, lat)), code, f_lab, shade(counts.get(code, 0), top) in RAMP[2:], "mm")

    # Inset, drawn after the main map so its white ground covers the islands beneath.
    east = [s for s in shapes if s[0] in MARITIMES]
    if not east:
        return
    x0, y0, x1, y1 = INSET_BOX
    d.rectangle(INSET_BOX, fill=WHITE, outline=RULE, width=2)
    ipt = _fit(east, INSET_BOX, pad=10)
    _paint(img, east, counts, top, ipt, (x0 + 2, y0 + 2, x1 - 1, y1 - 1))
    f_inset = _font("semibold", 15)
    for code, ((lon, lat), on_water) in INSET_LABELS.items():
        dark = not on_water and shade(counts.get(code, 0), top) in RAMP[2:]
        _halo_text(d, ipt(*lcc(lon, lat)), code, f_inset, dark, "mm")

    # Where the inset sits on the main map, in a thin muted frame.
    xs = [p[0] for _, rings in east for ring in rings for p in ring]
    ys = [p[1] for _, rings in east for ring in rings for p in ring]
    (ex0, ey0), (ex1, ey1) = pt(min(xs), max(ys)), pt(max(xs), min(ys))
    d.rectangle((ex0 - 4, ey0 - 4, ex1 + 4, ey1 + 4), outline=MUTED, width=1)


def _legend(d: ImageDraw.ImageDraw, x: int, y: int, top: int) -> None:
    f = _font("regular", 18)
    d.text((x, y), "0", font=f, fill=MUTED, anchor="lm")
    x += 18
    for colour in [ZERO, *RAMP]:
        d.rectangle((x, y - 9, x + 26, y + 9), fill=colour, outline=RULE)
        x += 26
    top_text = f"{top:,}"
    d.text((x + 8, y), top_text, font=f, fill=MUTED, anchor="lm")
    word = "posting" if top == 1 else "postings"
    d.text((x + 8 + int(d.textlength(top_text, font=f)) + 10, y), word, font=f, fill=MUTED, anchor="lm")


# -- the rest of the card ----------------------------------------------------------


@dataclass
class CardEmployer:
    name: str
    place: str
    positions: int


@dataclass
class CardData:
    date: str
    title: str                        # "New on Job Bank, 2026-10-18" or "... since 2026-10-16"
    postings: int
    positions_line: str | None        # e.g. "164 positions", "at least 164 positions", or None
    context: str | None               # e.g. "Last 7 days: 412 postings, 1,160 positions"
    province_counts: dict[str, int]   # new postings by province code
    employers: list[CardEmployer]     # by positions, descending
    site: str                         # bare host shown in the footer, e.g. lmiawatch.ca
    label: str = 'Postings newly flagged "LMIA requested"'  # the line above the headline number
    note: str = "Counts are postings carrying the flag when first seen."  # the footer's second sentence


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_DIR / FONT_FILES[kind]
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size)


def _ellipsize(d: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if d.textlength(text, font=font) <= max_width:
        return text
    cut = text
    while cut and d.textlength(cut + "...", font=font) > max_width:
        cut = cut[:-1]
    return cut.rstrip() + "..."


# A word, or a quoted phrase ("LMIA requested", « EIMT demandée ») together with
# whatever touches it, so the phrase never breaks across lines. A quote mark
# with no partner is an ordinary character.
_WORD = re.compile(r'(?:"[^"]*"|«[^»]*»|\S)+')


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in _WORD.findall(text):
        trial = f"{cur} {word}" if cur else word
        if cur and d.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _fitted(d: ImageDraw.ImageDraw, text: str, kind: str, size: int, width: int, smallest: int):
    """The font at the largest size, from size down to smallest, that fits text in width,
    and the text, ellipsized when it does not fit even at the smallest."""
    font = _font(kind, size)
    while size > smallest and d.textlength(text, font=font) > width:
        size -= 1
        font = _font(kind, size)
    return font, _ellipsize(d, text, font, width)


def _mark(d: ImageDraw.ImageDraw, x: int, y: int, k: int, ink: tuple, bg: tuple) -> None:
    def box(r):
        x0, y0, x1, y1 = r
        return (x + (x0 - MARK_FRAME[0]) * k, y + (y0 - MARK_FRAME[1]) * k,
                x + (x1 - MARK_FRAME[0]) * k - 1, y + (y1 - MARK_FRAME[1]) * k - 1)

    d.rectangle(box(MARK_FRAME), fill=ink)
    for hole in MARK_HOLES:
        d.rectangle(box(hole), fill=bg)


def _headline(d: ImageDraw.ImageDraw, card: CardData, x: int, y: int, width: int) -> int:
    """The label, the number and the two lines under it; returns the y below them."""
    f_label = _font("regular", 24)
    for line in _wrap(d, card.label, f_label, width):
        d.text((x, y), line, font=f_label, fill=MUTED)
        y += 30
    y += 6
    d.text((x - 6, y - 12), f"{card.postings:,}", font=_font("bold", 96), fill=NAVY)
    y += 96 + 14
    if card.positions_line:
        font, text = _fitted(d, card.positions_line, "semibold", 28, width, 20)
        d.text((x, y), text, font=font, fill=INK)
    y += 36
    if card.context:
        # The week beside the day, so a thin day reads against its context.
        font, text = _fitted(d, card.context, "regular", 19, width, 14)
        d.text((x, y), text, font=font, fill=MUTED)
    return y + 36


def _employers(d: ImageDraw.ImageDraw, employers: list[CardEmployer], x: int, y: int, width: int) -> None:
    """Two lines per employer: the name and its positions, then the place in small muted type."""
    d.text((x, y), "Most positions", font=_font("semibold", 24), fill=INK)
    y += 36
    d.line((x, y, x + width, y), fill=RULE, width=2)
    y += 10
    f_name, f_place, f_num = _font("regular", 22), _font("regular", 17), _font("bold", 22)
    for e in employers[:CARD_EMPLOYERS]:
        if y + EMPLOYER_ROW_H > HEIGHT - FOOTER_H:
            break
        num = f"{e.positions:,}"
        num_w = int(d.textlength(num, font=f_num))
        d.text((x, y), _ellipsize(d, e.name, f_name, width - num_w - 20), font=f_name, fill=INK)
        d.text((x + width, y), num, font=f_num, fill=INK, anchor="ra")
        if e.place:
            d.text((x, y + 25), _ellipsize(d, e.place, f_place, width), font=f_place, fill=MUTED)
        y += EMPLOYER_ROW_H


def bar_rows(counts: dict[str, int]) -> list[tuple[str, int]]:
    """The province bars: the CARD_PROVINCES largest, then "Other" for the rest."""
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    rows = items[:CARD_PROVINCES]
    rest = sum(n for _, n in items[CARD_PROVINCES:])
    if rest:
        rows.append(("Other", rest))
    return rows


def _bars(d: ImageDraw.ImageDraw, counts: dict[str, int], x: int, y: int, width: int) -> None:
    rows = bar_rows(counts)
    top = max((n for _, n in rows), default=0)
    f_code, f_count = _font("semibold", 22), _font("regular", 22)
    # Two-letter codes fit in 54 px; a wider label ("Other") moves the bars right.
    label_w = max((int(d.textlength(code, font=f_code)) for code, _ in rows), default=0)
    bar_x0 = x + max(54, label_w + 12)
    bar_max = x + width - 72 - bar_x0
    for code, n in rows:
        d.text((x, y + 14), code, font=f_code, fill=INK, anchor="lm")
        w = int(bar_max * n / top) if top else 0
        d.rectangle((bar_x0, y + 3, bar_x0 + max(w, 2), y + 25), fill=NAVY)
        d.text((bar_x0 + max(w, 2) + 12, y + 14), f"{n:,}", font=f_count, fill=INK, anchor="lm")
        y += BAR_ROW_H


def _known_counts(card: CardData) -> dict[str, int]:
    """The province counts the card can place: one of the thirteen codes, above zero."""
    return {code: n for code, n in card.province_counts.items() if code in KNOWN_CODES and n > 0}


def render_card(card: CardData) -> bytes:
    """The PNG bytes of the card."""
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    d = ImageDraw.Draw(img)

    # Header band: mark, site name, and the date on the right.
    d.rectangle((0, 0, WIDTH, HEADER_H), fill=NAVY)
    _mark(d, MARGIN, 28, 2, WHITE, NAVY)
    f_name = _font("semibold", 34)
    d.text((MARGIN + 64, HEADER_H // 2), "LMIA Watch", font=f_name, fill=WHITE, anchor="lm")
    f_date = _font("regular", 26)
    d.text((WIDTH - MARGIN, HEADER_H // 2), card.title, font=f_date, fill=WHITE, anchor="rm")

    # Left column: the headline number, then the employers with the most positions.
    y = _headline(d, card, MARGIN, HEADER_H + 34, LEFT_W)
    if card.employers:
        _employers(d, card.employers, MARGIN, y, LEFT_W)

    # Beside it, one "By province" section: the map, then the bars.
    d.text((MAP_X, HEADER_H + 34), "By province", font=_font("semibold", 24), fill=INK)
    d.line((MAP_X, HEADER_H + 70, WIDTH - MARGIN, HEADER_H + 70), fill=RULE, width=2)
    counts = _known_counts(card)
    _draw_map(img, d, counts)
    _bars(d, counts, BARS_X, 182, WIDTH - MARGIN - BARS_X)

    # Footer: provenance on the left, the site address on the right.
    fy = HEIGHT - FOOTER_H
    d.rectangle((0, fy, WIDTH, HEIGHT), fill=PANEL)
    d.line((0, fy, WIDTH, fy), fill=RULE, width=2)
    f_foot = _font("regular", 20)
    d.text((MARGIN, fy + FOOTER_H // 2), f"Source: Job Bank, Government of Canada. {card.note}", font=f_foot, fill=MUTED, anchor="lm")
    d.text((WIDTH - MARGIN, fy + FOOTER_H // 2), card.site, font=_font("semibold", 24), fill=NAVY, anchor="rm")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def alt_text(card: CardData, limit: int = 1000) -> str:
    """A plain description of the card for screen readers (X allows 1,000 characters)."""
    what = card.label[0].lower() + card.label[1:]  # 'postings newly flagged "LMIA requested"'
    parts = [f"LMIA Watch daily card. {card.title}: {card.postings:,} {what.replace('"', '')}"]
    if card.positions_line:
        parts[0] += f", {card.positions_line}"
    parts[0] += "."
    if card.context:
        parts.append(card.context + ".")
    counts = _known_counts(card)
    if counts:
        by = ", ".join(f"{c} {n:,}" for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        parts.append(f"By province, on a map of Canada shaded by count with an inset of the Maritimes: {by}.")
    if card.employers:
        emp = "; ".join(f"{e.name}, {e.place}: {e.positions:,}" if e.place else f"{e.name}: {e.positions:,}" for e in card.employers[:CARD_EMPLOYERS])
        parts.append(f"Most positions: {emp}.")
    parts.append(f"Source: Job Bank. {card.site}")
    text = " ".join(parts)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def save_card(card: CardData, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_card(card))
    return path
