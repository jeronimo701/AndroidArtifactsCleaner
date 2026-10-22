from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


OUT_DIR = Path(__file__).resolve().parent
PNG_PATH = OUT_DIR / "android_cleaner_icon.png"
ICO_PATH = OUT_DIR / "android_cleaner_icon.ico"


def lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def gradient_background(size: int) -> Image.Image:
    top = (18, 29, 47)
    bottom = (7, 103, 108)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pix = img.load()

    for y in range(size):
        t = y / (size - 1)
        for x in range(size):
            radial = math.hypot((x - size * 0.74) / size, (y - size * 0.18) / size)
            glow = max(0.0, 1.0 - radial * 2.15)
            r = lerp(top[0], bottom[0], t) + int(22 * glow)
            g = lerp(top[1], bottom[1], t) + int(88 * glow)
            b = lerp(top[2], bottom[2], t) + int(96 * glow)
            pix[x, y] = (min(r, 255), min(g, 255), min(b, 255), 255)

    return img


def draw_shadow(base: Image.Image, shape: Image.Image, offset: tuple[int, int], blur: int, alpha: int) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.alpha_composite(shape, offset)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    a = shadow.getchannel("A").point(lambda p: min(p, alpha))
    shadow.putalpha(a)
    base.alpha_composite(shadow)


def make_icon(size: int = 1024) -> Image.Image:
    scale = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    bg = gradient_background(size)
    bg.putalpha(rounded_mask(size, int(210 * scale)))
    img.alpha_composite(bg)

    d = ImageDraw.Draw(img)
    inset = int(30 * scale)
    d.rounded_rectangle(
        (inset, inset, size - inset, size - inset),
        radius=int(180 * scale),
        outline=(255, 255, 255, 26),
        width=max(2, int(6 * scale)),
    )

    # USB body.
    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bx1, by1 = int(350 * scale), int(230 * scale)
    bx2, by2 = int(674 * scale), int(810 * scale)
    bd.rounded_rectangle((bx1, by1, bx2, by2), radius=int(86 * scale), fill=(236, 245, 247, 255))
    bd.rounded_rectangle(
        (int(395 * scale), int(150 * scale), int(629 * scale), int(304 * scale)),
        radius=int(44 * scale),
        fill=(151, 169, 178, 255),
    )
    bd.rectangle((int(445 * scale), int(130 * scale), int(489 * scale), int(206 * scale)), fill=(218, 231, 235, 255))
    bd.rectangle((int(535 * scale), int(130 * scale), int(579 * scale), int(206 * scale)), fill=(218, 231, 235, 255))
    bd.rounded_rectangle(
        (int(406 * scale), int(365 * scale), int(618 * scale), int(430 * scale)),
        radius=int(30 * scale),
        fill=(12, 119, 128, 255),
    )
    bd.rounded_rectangle(
        (int(406 * scale), int(462 * scale), int(618 * scale), int(527 * scale)),
        radius=int(30 * scale),
        fill=(24, 154, 151, 255),
    )
    bd.rounded_rectangle(
        (int(406 * scale), int(560 * scale), int(618 * scale), int(625 * scale)),
        radius=int(30 * scale),
        fill=(94, 202, 171, 255),
    )

    draw_shadow(img, body, (0, int(18 * scale)), int(26 * scale), 96)
    img.alpha_composite(body)

    # Clean action: cyan sweep and check.
    sweep = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    sd.line(
        (int(262 * scale), int(702 * scale), int(770 * scale), int(410 * scale)),
        fill=(95, 231, 218, 245),
        width=int(52 * scale),
    )
    sd.line(
        (int(260 * scale), int(702 * scale), int(770 * scale), int(410 * scale)),
        fill=(224, 255, 250, 255),
        width=int(20 * scale),
    )
    sd.line(
        (int(396 * scale), int(676 * scale), int(487 * scale), int(760 * scale), int(666 * scale), int(542 * scale)),
        fill=(16, 68, 73, 255),
        width=int(48 * scale),
        joint="curve",
    )
    sd.line(
        (int(396 * scale), int(676 * scale), int(487 * scale), int(760 * scale), int(666 * scale), int(542 * scale)),
        fill=(112, 245, 177, 255),
        width=int(30 * scale),
        joint="curve",
    )

    for cx, cy, r in [(760, 270, 20), (806, 344, 13), (248, 548, 16)]:
        x, y, rr = int(cx * scale), int(cy * scale), int(r * scale)
        sd.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(169, 255, 235, 230))

    img.alpha_composite(sweep)
    return img


def main() -> None:
    icon = make_icon()
    icon.save(PNG_PATH)
    icon.save(
        ICO_PATH,
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(PNG_PATH)
    print(ICO_PATH)


if __name__ == "__main__":
    main()
