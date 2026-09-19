"""Generate Pitch Compass (绿茵罗盘) brand assets.

Reproducible brand artwork: avatars, README lockup and WeChat banners.
Run from the repo root:  python brand/generate_assets.py
Outputs land in brand/dist/. Fonts: Microsoft YaHei (Windows).
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_ROOT = Path(__file__).resolve().parent
DIST = BRAND_ROOT / "dist"
AMBER_TOP = (16, 185, 129)  # emerald-500
AMBER_BOTTOM = (13, 148, 136)  # teal-600
PITCH_DARK = (6, 10, 24)  # slate-950 tinted
WHITE = (255, 255, 255, 255)
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REGULAR = "C:/Windows/Fonts/msyh.ttc"


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, ...]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def diagonal_gradient(size: int) -> Image.Image:
    """Smooth diagonal emerald gradient built small and upscaled."""

    small = Image.new("RGB", (64, 64))
    pixels = small.load()
    for y in range(64):
        for x in range(64):
            pixels[x, y] = lerp(AMBER_TOP, AMBER_BOTTOM, (x + y) / 126)
    return small.resize((size, size), Image.BICUBIC)


def draw_compass(image: Image.Image, cx: float, cy: float, radius: float) -> None:
    """White compass ring + needle + emerald pivot, scaled to radius."""

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ring_width = max(2, int(radius * 0.10))
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(255, 255, 255, 140),
        width=ring_width,
    )
    needle = radius * 0.62
    draw.polygon(
        [
            (cx + needle, cy - needle),
            (cx + needle * 0.18, cy + needle * 0.18),
            (cx - needle, cy + needle),
            (cx - needle * 0.18, cy - needle * 0.18),
        ],
        fill=WHITE,
    )
    pivot = max(2.0, radius * 0.075)
    draw.ellipse(
        (cx - pivot, cy - pivot, cx + pivot, cy + pivot),
        fill=(217, 119, 6, 255),
    )
    image.alpha_composite(overlay)


def icon_avatar(size: int) -> Image.Image:
    """Rounded-square app icon on transparency."""

    scale = 4
    big = size * scale
    image = diagonal_gradient(big).convert("RGBA")
    draw_compass(image, big / 2, big / 2, big * 0.30)
    corner = int(big * 0.22)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=corner, fill=255)
    image.putalpha(mask)
    return image.resize((size, size), Image.LANCZOS)


def text_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: ImageFont.FreeTypeFont, tracking: float, fill=WHITE) -> None:
    x, y = xy
    for character in text:
        draw.text((x, y), character, font=font, fill=fill)
        width = draw.textlength(character, font=font)
        x += width + tracking


def tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    return sum(draw.textlength(character, font=font) for character in text) + tracking * max(0, len(text) - 1)


def lockup_horizontal(width: int = 1280, transparent: bool = True) -> Image.Image:
    """Icon + 绿茵罗盘 + PITCH COMPASS horizontal lockup."""

    height = int(width * 0.28)
    if transparent:
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        image = diagonal_gradient(height).convert("RGBA").resize((width, height))
    icon_size = int(height * 0.72)
    icon = icon_avatar(icon_size)
    image.alpha_composite(icon, (int(height * 0.14), int((height - icon_size) / 2)))
    x = height * 0.14 + icon_size + height * 0.18
    draw = ImageDraw.Draw(image)
    cy = height / 2
    name_font = text_font(int(height * 0.38))
    name_box = draw.textbbox((0, 0), "绿茵罗盘", font=name_font)
    name_h = name_box[3] - name_box[1]
    draw.text((x, cy - name_h * 1.15), "绿茵罗盘", font=name_font, fill=WHITE)
    latin_font = text_font(int(height * 0.10))
    latin = "P I T C H   C O M P A S S"
    latin_y = cy + name_h * 0.62
    if transparent:
        draw_tracked(draw, (x + 2, latin_y), latin, latin_font, 2.0, fill=(253, 230, 138, 255))
    else:
        draw_tracked(draw, (x + 2, latin_y), latin, latin_font, 2.0, fill=(255, 237, 213, 230))
    return image


def banner_wechat(width: int = 900, height: int = 383) -> Image.Image:
    """WeChat article header (2.35:1): dark pitch, lockup and tagline."""

    image = Image.new("RGBA", (width, height), PITCH_DARK + (255,))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Ghost compass rings on the right edge for depth without noise.
    for radius, alpha in ((height * 0.95, 26), (height * 0.62, 34)):
        draw.ellipse(
            (width - radius * 0.9, height / 2 - radius, width - radius * 0.9 + radius * 2, height / 2 + radius),
            outline=(245, 158, 11, alpha),
            width=3,
        )
    image.alpha_composite(overlay)
    icon = icon_avatar(int(height * 0.58))
    image.alpha_composite(icon, (int(width * 0.075), int((height - icon.height) / 2)))
    draw = ImageDraw.Draw(image)
    x = width * 0.075 + icon.width + width * 0.05
    name_font = text_font(int(height * 0.30))
    box = draw.textbbox((0, 0), "绿茵罗盘", font=name_font)
    name_h = box[3] - box[1]
    draw.text((x, height * 0.16), "绿茵罗盘", font=name_font, fill=WHITE)
    latin_font = text_font(int(height * 0.085))
    draw_tracked(draw, (x + 2, height * 0.16 + name_h * 1.16), "P I T C H   C O M P A S S", latin_font, 2.0, fill=(253, 230, 138, 255))
    tagline = "可追溯 · 可解释 · 可回测的足球赛前研究终端"
    max_width = width - x - width * 0.06
    tagline_size = int(height * 0.105)
    tagline_font = text_font(tagline_size, bold=False)
    while draw.textlength(tagline, font=tagline_font) > max_width and tagline_size > 12:
        tagline_size -= 2
        tagline_font = text_font(tagline_size, bold=False)
    draw.text(
        (x, height * 0.66),
        tagline,
        font=tagline_font,
        fill=(203, 213, 225, 235),
    )
    return image


def banner_square(size: int = 1080) -> Image.Image:
    """1:1 social banner: centered lockup on dark pitch."""

    image = Image.new("RGBA", (size, size), PITCH_DARK + (255,))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for radius, alpha in ((size * 0.46, 24), (size * 0.34, 30)):
        draw.ellipse(
            (size / 2 - radius, size / 2 - radius, size / 2 + radius, size / 2 + radius),
            outline=(245, 158, 11, alpha),
            width=3,
        )
    image.alpha_composite(overlay)
    icon = icon_avatar(int(size * 0.26))
    image.alpha_composite(icon, (int((size - icon.width) / 2), int(size * 0.17)))
    draw = ImageDraw.Draw(image)
    name_font = text_font(int(size * 0.115))
    box = draw.textbbox((0, 0), "绿茵罗盘", font=name_font)
    name_w = box[2] - box[0]
    draw.text(((size - name_w) / 2, size * 0.50), "绿茵罗盘", font=name_font, fill=WHITE)
    latin_font = text_font(int(size * 0.032))
    latin = "P I T C H   C O M P A S S"
    latin_w = tracked_width(draw, latin, latin_font, 3.0)
    draw_tracked(draw, ((size - latin_w) / 2, size * 0.635), latin, latin_font, 3.0, fill=(253, 230, 138, 255))
    tagline_font = text_font(int(size * 0.040), bold=False)
    tagline = "可追溯 · 可解释 · 可回测的足球赛前研究终端"
    tagline_w = draw.textlength(tagline, font=tagline_font)
    draw.text(((size - tagline_w) / 2, size * 0.70), tagline, font=tagline_font, fill=(203, 213, 225, 235))
    return image


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    targets = {
        "icon-512.png": icon_avatar(512),
        "icon-192.png": icon_avatar(192),
        "icon-180.png": icon_avatar(180),
        "lockup-horizontal.png": lockup_horizontal(1280),
        "banner-wechat-900x383.png": banner_wechat(),
        "banner-square-1080.png": banner_square(1080),
    }
    for name, image in targets.items():
        image.save(DIST / name)
        print(f"wrote {DIST / name}")


if __name__ == "__main__":
    main()
