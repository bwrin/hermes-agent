#!/usr/bin/env python3
"""Redraw chore/UI icons as dense monochrome masks for email tinting.

128x128 transparent PNG, dark #2C2620 mask, ~7px strokes / filled pads.
Readable when tinted and shown at ~28–34px in email.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

OUT = Path(__file__).resolve().parent / "icons"
SIZE = 128
S = 7
COLOR = (0x2C, 0x26, 0x20, 255)
MAX_GLYPH = 104  # approximately 12px transparent margin on the long axis


def blank() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def save(im: Image.Image, name: str) -> None:
    """Normalize the drawn mask into a centered 128px transparent canvas."""
    alpha = im.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError(f"{name} has no alpha content")
    cropped = alpha.crop(bbox)
    scale = min(MAX_GLYPH / cropped.width, MAX_GLYPH / cropped.height)
    size = (
        max(1, round(cropped.width * scale)),
        max(1, round(cropped.height * scale)),
    )
    glyph = cropped.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("L", (SIZE, SIZE), 0)
    canvas.paste(glyph, ((SIZE - glyph.width) // 2, (SIZE - glyph.height) // 2))
    normalized = Image.new("RGBA", (SIZE, SIZE), COLOR)
    normalized.putalpha(canvas)

    path = OUT / f"{name}.png"
    normalized.save(path, "PNG", optimize=True)
    print(f"{name}: {path.stat().st_size} bytes  size={normalized.size}")


def punch(im: Image.Image, *ellipses: tuple) -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    for box in ellipses:
        md.ellipse(box, fill=255)
    r, g, b, a = im.split()
    a = ImageChops.subtract(a, mask)
    return Image.merge("RGBA", (r, g, b, a))


def trash() -> None:
    im, d = blank()
    d.rounded_rectangle([26, 36, 102, 48], radius=4, fill=COLOR)
    d.arc([52, 22, 76, 46], start=200, end=340, fill=COLOR, width=S)
    d.rounded_rectangle([34, 48, 94, 112], radius=10, outline=COLOR, width=S)
    for x in (50, 64, 78):
        d.line([(x, 58), (x, 102)], fill=COLOR, width=5)
    save(im, "trash")


def washer() -> None:
    im, d = blank()
    d.rounded_rectangle([26, 22, 102, 110], radius=14, outline=COLOR, width=S)
    d.ellipse([40, 40, 88, 88], outline=COLOR, width=S)
    d.ellipse([52, 52, 76, 76], outline=COLOR, width=5)
    d.ellipse([36, 28, 48, 40], fill=COLOR)
    d.ellipse([54, 28, 66, 40], fill=COLOR)
    d.line([(36, 96), (92, 96)], fill=COLOR, width=5)
    save(im, "washer")


def tub() -> None:
    im, d = blank()
    d.rounded_rectangle([22, 50, 106, 102], radius=22, outline=COLOR, width=S)
    d.rounded_rectangle([20, 46, 108, 58], radius=4, fill=COLOR)
    d.arc([38, 62, 90, 86], start=20, end=160, fill=COLOR, width=5)
    d.line([(90, 24), (90, 46)], fill=COLOR, width=S)
    d.arc([70, 18, 98, 46], start=200, end=350, fill=COLOR, width=S)
    d.rounded_rectangle([34, 100, 46, 114], radius=3, fill=COLOR)
    d.rounded_rectangle([82, 100, 94, 114], radius=3, fill=COLOR)
    save(im, "tub")


def bed() -> None:
    im, d = blank()
    d.rounded_rectangle([22, 26, 46, 78], radius=8, outline=COLOR, width=S)
    d.rounded_rectangle([22, 62, 108, 92], radius=10, outline=COLOR, width=S)
    d.rounded_rectangle([52, 42, 90, 62], radius=8, fill=COLOR)
    d.rounded_rectangle([32, 90, 42, 114], radius=2, fill=COLOR)
    d.rounded_rectangle([90, 90, 100, 114], radius=2, fill=COLOR)
    save(im, "bed")


def dishes() -> None:
    im, d = blank()
    for y0, y1 in ((24, 50), (46, 72), (68, 94)):
        d.ellipse([24, y0, 104, y1], outline=COLOR, width=S)
        d.ellipse([42, y0 + 6, 86, y1 - 6], outline=COLOR, width=4)
    save(im, "dishes")


def bowl() -> None:
    """Cat bowl. Heavier than the other masks on purpose.

    The email draws this at 34px. A 7px arc on the 128px grid was collapsing
    to a couple of pixels — the sparsest chore glyph, and the one Apple Mail
    showed as a broken image.
    """
    im, d = blank()
    d.arc([16, 36, 112, 118], start=10, end=170, fill=COLOR, width=12)
    d.line([(20, 76), (108, 76)], fill=COLOR, width=12)
    d.ellipse([28, 48, 100, 80], outline=COLOR, width=8)
    for cx, cy in ((48, 34), (64, 26), (80, 34)):
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=COLOR)
    save(im, "bowl")


def sofa() -> None:
    im, d = blank()
    d.rounded_rectangle([34, 26, 94, 62], radius=12, outline=COLOR, width=S)
    d.line([(64, 32), (64, 56)], fill=COLOR, width=5)
    d.rounded_rectangle([22, 54, 106, 96], radius=14, outline=COLOR, width=S)
    d.line([(64, 62), (64, 90)], fill=COLOR, width=5)
    d.rounded_rectangle([14, 44, 32, 96], radius=10, fill=COLOR)
    d.rounded_rectangle([96, 44, 114, 96], radius=10, fill=COLOR)
    d.line([(34, 82), (94, 82)], fill=COLOR, width=4)
    d.rounded_rectangle([28, 94, 38, 116], radius=2, fill=COLOR)
    d.rounded_rectangle([90, 94, 100, 116], radius=2, fill=COLOR)
    save(im, "sofa")


def paw() -> None:
    im, d = blank()
    pad = [
        (42, 66), (50, 58), (64, 56), (78, 58), (86, 66),
        (92, 80), (90, 98), (78, 112), (64, 116), (50, 112),
        (38, 98), (36, 80),
    ]
    d.polygon(pad, fill=COLOR)
    d.ellipse([40, 74, 88, 114], fill=COLOR)
    for box in (
        (18, 28, 44, 56),
        (38, 14, 62, 42),
        (66, 14, 90, 42),
        (84, 28, 110, 56),
    ):
        d.ellipse(box, fill=COLOR)
    save(im, "paw")


def vacuum() -> None:
    im, d = blank()
    d.arc([48, 8, 80, 36], start=200, end=340, fill=COLOR, width=S + 1)
    d.line([(52, 18), (76, 18)], fill=COLOR, width=S)
    d.rounded_rectangle([58, 22, 70, 52], radius=4, fill=COLOR)
    d.rounded_rectangle([42, 48, 86, 98], radius=14, fill=COLOR)
    im = punch(im, (52, 58, 76, 82))
    d = ImageDraw.Draw(im)
    d.ellipse([52, 58, 76, 82], outline=COLOR, width=4)
    d.rounded_rectangle([56, 94, 72, 104], radius=3, fill=COLOR)
    d.rounded_rectangle([20, 100, 108, 116], radius=8, fill=COLOR)
    d.ellipse([28, 108, 46, 126], outline=COLOR, width=4)
    d.ellipse([82, 108, 100, 126], outline=COLOR, width=4)
    im = punch(im, (33, 113, 41, 121), (87, 113, 95, 121))
    save(im, "vacuum")


def rotate() -> None:
    im, d = blank()
    d.arc([22, 22, 106, 106], start=50, end=320, fill=COLOR, width=S + 1)
    d.polygon([(84, 68), (108, 72), (94, 96)], fill=COLOR)
    save(im, "rotate")


def home() -> None:
    im, d = blank()
    d.line([(64, 20), (18, 60)], fill=COLOR, width=S + 1)
    d.line([(64, 20), (110, 60)], fill=COLOR, width=S + 1)
    d.line([(18, 60), (110, 60)], fill=COLOR, width=S)
    d.polygon([(64, 24), (24, 58), (104, 58)], fill=COLOR)
    d.rounded_rectangle([32, 58, 96, 112], radius=4, outline=COLOR, width=S)
    d.rounded_rectangle([52, 78, 76, 112], radius=4, fill=COLOR)
    save(im, "home")


def check() -> None:
    im, d = blank()
    d.ellipse([20, 20, 108, 108], outline=COLOR, width=S)
    d.line([(38, 66), (56, 86)], fill=COLOR, width=S + 2)
    d.line([(56, 86), (92, 44)], fill=COLOR, width=S + 2)
    save(im, "check")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (
        trash, washer, tub, bed, dishes, bowl, sofa, paw, vacuum, rotate, home, check
    ):
        fn()


if __name__ == "__main__":
    main()
