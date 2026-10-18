"""Renders the raster brand files (social profile photos and header) from the site mark.

The mark is the same register grid as site/public/favicon.svg: a 16 by 16 pixel
grid inside a 32-unit box, every edge on an even unit. Each output picks a whole
number of pixels per unit so the edges stay sharp without resampling.

Run:  python brand/make_brand.py
Writes into brand/: x-profile-400.png, x-profile-1024.png, x-profile-light-400.png,
x-header-1500x500.png. The wordmark uses Public Sans Bold from brand/fonts/ (OFL)
and falls back to Segoe UI Bold when that file is absent.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NAVY = (0x1C, 0x3D, 0x6A)
WHITE = (255, 255, 255)
MUTED = (0xC9, 0xD6, 0xE8)  # light blue-grey for the tagline on navy

FRAME = (4, 6, 28, 26)
HOLES = [(6, 8, 12, 12), (14, 8, 26, 12), (6, 14, 12, 18), (6, 20, 12, 24), (14, 20, 26, 24)]
INK_W, INK_H = FRAME[2] - FRAME[0], FRAME[3] - FRAME[1]  # 24 by 20 units

HERE = Path(__file__).resolve().parent
TAGLINE = "Public records of Labour Market Impact Assessments"


def draw_mark(d: ImageDraw.ImageDraw, x: int, y: int, k: int, ink: tuple, bg: tuple) -> None:
    """Draw the mark with its ink's top-left corner at (x, y), k pixels per unit."""

    def box(r: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = r
        return (x + (x0 - FRAME[0]) * k, y + (y0 - FRAME[1]) * k, x + (x1 - FRAME[0]) * k - 1, y + (y1 - FRAME[1]) * k - 1)

    d.rectangle(box(FRAME), fill=ink)
    for hole in HOLES:
        d.rectangle(box(hole), fill=bg)


def font(size: int) -> ImageFont.FreeTypeFont:
    bold = HERE / "fonts" / "PublicSans-Bold.ttf"
    if bold.exists():
        return ImageFont.truetype(str(bold), size)
    return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", size)


def profile(size: int, k: int, ink: tuple, bg: tuple, name: str) -> None:
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    draw_mark(d, (size - INK_W * k) // 2, (size - INK_H * k) // 2, k, ink, bg)
    img.save(HERE / name, optimize=True)


def header() -> None:
    w, h = 1500, 500
    img = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(img)
    k, gap = 7, 44
    f = font(150)
    word = "LMIA Watch"
    bbox = d.textbbox((0, 0), word, font=f, anchor="ls")  # relative to the baseline
    text_w, cap_h = bbox[2] - bbox[0], -bbox[1]
    total = INK_W * k + gap + text_w
    x0 = (w - total) // 2
    cy = 215  # lockup centre line, a little above the middle to leave room for the tagline
    draw_mark(d, x0, cy - INK_H * k // 2, k, WHITE, NAVY)
    d.text((x0 + INK_W * k + gap, cy + cap_h // 2), word, font=f, fill=WHITE, anchor="ls")
    tf = font(34)
    d.text((w // 2, 360), TAGLINE, font=tf, fill=MUTED, anchor="ms")
    img.save(HERE / "x-header-1500x500.png", optimize=True)


def main() -> None:
    profile(400, 9, WHITE, NAVY, "x-profile-400.png")
    profile(1024, 24, WHITE, NAVY, "x-profile-1024.png")
    profile(400, 9, NAVY, WHITE, "x-profile-light-400.png")
    header()
    print("wrote brand files to", HERE)


if __name__ == "__main__":
    main()
