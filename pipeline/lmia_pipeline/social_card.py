"""The image attached to the daily X post: a 1200 by 675 card drawn with Pillow.

Why an image at all: X bills a post that contains a URL at thirteen times the
rate of one that does not, and bills nothing extra for an attached image. The
card carries the site address and the full breakdown (postings by province,
the employers with the most positions) that the 280-character text cannot.

Why Pillow and not a plotting library: the card is rectangles and text, and
Pillow is already needed for the icons. It keeps the nightly install small.

The typeface is Public Sans (the site's own), read from brand/fonts in the
checkout; Pillow's built-in font stands in if those files are missing, so a
missing font can never stop a post.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

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
CARD_EMPLOYERS = 5
CARD_PROVINCES = 8

# The site mark on its 32-unit grid (the same rectangles as site/public/favicon.svg).
MARK_FRAME = (4, 6, 28, 26)
MARK_HOLES = [(6, 8, 12, 12), (14, 8, 26, 12), (6, 14, 12, 18), (6, 20, 12, 24), (14, 20, 26, 24)]

FONT_DIR = config.REPO_ROOT / "brand" / "fonts"
FONT_FILES = {"regular": "PublicSans-Regular.ttf", "semibold": "PublicSans-SemiBold.ttf", "bold": "PublicSans-Bold.ttf"}


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


def _mark(d: ImageDraw.ImageDraw, x: int, y: int, k: int, ink: tuple, bg: tuple) -> None:
    def box(r):
        x0, y0, x1, y1 = r
        return (x + (x0 - MARK_FRAME[0]) * k, y + (y0 - MARK_FRAME[1]) * k,
                x + (x1 - MARK_FRAME[0]) * k - 1, y + (y1 - MARK_FRAME[1]) * k - 1)

    d.rectangle(box(MARK_FRAME), fill=ink)
    for hole in MARK_HOLES:
        d.rectangle(box(hole), fill=bg)


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
    left_x, col_w = MARGIN, 540
    y = HEADER_H + 34
    f_label = _font("regular", 24)
    d.text((left_x, y), card.label, font=f_label, fill=MUTED)
    y += 36
    f_big = _font("bold", 120)
    d.text((left_x - 6, y - 12), f"{card.postings:,}", font=f_big, fill=NAVY)
    y += 136
    if card.positions_line:
        d.text((left_x, y), card.positions_line, font=_font("semibold", 30), fill=INK)
    y += 40
    if card.context:
        # The week beside the day, so a thin day reads against its context.
        d.text((left_x, y), card.context, font=_font("regular", 22), fill=MUTED)
    y += 44

    if card.employers:
        f_h = _font("semibold", 24)
        d.text((left_x, y), "Most positions", font=f_h, fill=INK)
        y += 36
        d.line((left_x, y, left_x + col_w, y), fill=RULE, width=2)
        y += 10
        f_row = _font("regular", 22)
        f_num = _font("bold", 22)
        for e in card.employers[:CARD_EMPLOYERS]:
            num = f"{e.positions:,}"
            num_w = int(d.textlength(num, font=f_num))
            avail = col_w - num_w - 24
            # Shorten the name before the place: "Example Holdings..., Leduc AB"
            # still says where, which the reader wants more than the name's tail.
            place = f", {e.place}" if e.place else ""
            name_w = avail - int(d.textlength(place, font=f_row))
            if name_w < int(d.textlength("M" * 10, font=f_row)):
                place, name_w = "", avail
            label = _ellipsize(d, e.name, f_row, name_w) + place
            d.text((left_x, y), label, font=f_row, fill=INK)
            d.text((left_x + col_w, y), num, font=f_num, fill=INK, anchor="ra")
            y += 36
            if y > HEIGHT - FOOTER_H - 40:
                break

    # Right column: new postings by province, as bars.
    right_x = 640
    bar_x0 = right_x + 78  # room for "Other" beside the two-letter codes
    bar_max = WIDTH - MARGIN - bar_x0 - 72
    y = HEADER_H + 34
    d.text((right_x, y), "By province", font=_font("semibold", 24), fill=INK)
    y += 36
    d.line((right_x, y, WIDTH - MARGIN, y), fill=RULE, width=2)
    y += 16
    items = sorted(card.province_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = items[:CARD_PROVINCES]
    rest = sum(n for _, n in items[CARD_PROVINCES:])
    if rest:
        shown.append(("Other", rest))
    top = max((n for _, n in shown), default=0)
    f_code = _font("semibold", 22)
    f_count = _font("regular", 22)
    for code, n in shown:
        d.text((right_x, y + 14), code, font=f_code, fill=INK, anchor="lm")
        w = int(bar_max * n / top) if top else 0
        d.rectangle((bar_x0, y + 3, bar_x0 + max(w, 2), y + 25), fill=NAVY)
        d.text((bar_x0 + max(w, 2) + 12, y + 14), f"{n:,}", font=f_count, fill=INK, anchor="lm")
        y += 40

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
    if card.province_counts:
        by = ", ".join(f"{c} {n:,}" for c, n in sorted(card.province_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        parts.append(f"By province: {by}.")
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
