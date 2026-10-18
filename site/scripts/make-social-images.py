"""Draws the link-preview images the page metadata points at, from the site mark.

social-card.png (1200 by 630) is the large card for the site's own pages: the
lockup and tagline on navy, kept inside the middle 1200 by 600 so the 2:1 crop
some services apply cuts only empty margin. social-square.png (400 by 400) is
the small card on employer profiles, the white mark on navy.

The drawing helpers and the wordmark font come from brand/make_brand.py, so the
card matches the X header.

Run from the repository root or from site/:  python site/scripts/make-social-images.py
Outputs: site/public/social-card.png and site/public/social-square.png.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "brand"))
from make_brand import INK_H, INK_W, MUTED, NAVY, TAGLINE, WHITE, draw_mark, font  # noqa: E402

PUBLIC = ROOT / "site" / "public"


def card() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(img)
    k, gap = 6, 36
    f = font(124)
    word = "LMIA Watch"
    bbox = d.textbbox((0, 0), word, font=f, anchor="ls")
    text_w, cap_h = bbox[2] - bbox[0], -bbox[1]
    x0 = (w - (INK_W * k + gap + text_w)) // 2
    cy = 280  # lockup centre line, above the middle to leave room for the tagline
    draw_mark(d, x0, cy - INK_H * k // 2, k, WHITE, NAVY)
    d.text((x0 + INK_W * k + gap, cy + cap_h // 2), word, font=f, fill=WHITE, anchor="ls")
    d.text((w // 2, 420), TAGLINE, font=font(34), fill=MUTED, anchor="ms")
    img.save(PUBLIC / "social-card.png", optimize=True)


def square() -> None:
    size, k = 400, 9
    img = Image.new("RGB", (size, size), NAVY)
    draw_mark(ImageDraw.Draw(img), (size - INK_W * k) // 2, (size - INK_H * k) // 2, k, WHITE, NAVY)
    img.save(PUBLIC / "social-square.png", optimize=True)


def main() -> None:
    card()
    square()
    print("wrote social-card.png and social-square.png to", PUBLIC)


if __name__ == "__main__":
    main()
