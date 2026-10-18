"""Draws the raster fallbacks for the site icon from the same rectangles as favicon.svg.

The mark lives on a 16 by 16 pixel grid inside a 32-unit box, with every edge on
an even unit. Rendering at a scale of 0.5, 1 or 1.5 units per pixel therefore
lands every edge on a whole pixel, which is why the ICO sizes are drawn
individually instead of resampled from one large image.

Run from the repository root or from site/:  python site/scripts/make-icons.py
Outputs: site/public/favicon.ico (16, 32, 48) and site/public/apple-touch-icon.png (180).
"""

from pathlib import Path

from PIL import Image, ImageDraw

NAVY = (0x1C, 0x3D, 0x6A, 255)
WHITE = (255, 255, 255, 255)

# Mark geometry in 32-unit coordinates: the outer frame, then the open cells
# that evenodd cuts out of it. The cell at (14, 14)-(26, 18) stays filled.
FRAME = (4, 6, 28, 26)
HOLES = [(6, 8, 12, 12), (14, 8, 26, 12), (6, 14, 12, 18), (6, 20, 12, 24), (14, 20, 26, 24)]

PUBLIC = Path(__file__).resolve().parent.parent / "public"


def draw(size: int, *, rounded: bool) -> Image.Image:
    """The mark on a white tile `size` pixels square, matching favicon.svg."""
    k = size / 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = round(size * 12 / 64) if rounded else 0
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=WHITE)

    def box(r: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = (round(v * k) for v in r)
        return x0, y0, x1 - 1, y1 - 1  # Pillow boxes are inclusive

    d.rectangle(box(FRAME), fill=NAVY)
    for hole in HOLES:
        d.rectangle(box(hole), fill=WHITE)
    return img


def main() -> None:
    sizes = [48, 32, 16]
    frames = [draw(s, rounded=True) for s in sizes]
    frames[0].save(PUBLIC / "favicon.ico", sizes=[(s, s) for s in sizes], append_images=frames[1:])

    # iOS rounds the corners itself and composites over black, so the touch
    # icon is an opaque white square drawn at 6 units per pixel and resampled.
    touch = draw(192, rounded=False).resize((180, 180), Image.Resampling.LANCZOS)
    touch.convert("RGB").save(PUBLIC / "apple-touch-icon.png", optimize=True)
    print("wrote favicon.ico and apple-touch-icon.png to", PUBLIC)


if __name__ == "__main__":
    main()
