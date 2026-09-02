#!/usr/bin/env python3
"""Generate the app icon set and Play Store graphics for Hindsight.

Draws a brass "since" ring — a clock face with most of the sweep done and a dot
marking the last time — on the app's dark surface color, then writes:

  app/android/app/src/main/res/mipmap-*/ic_launcher{,_round,_foreground}.png
  app/android/app/src/main/res/values/ic_launcher_background.xml
  store/graphics/icon-512.png            (Play listing icon)
  store/graphics/feature-1024x500.png    (Play feature graphic)

Run from the repo root:  python3 store/make-graphics.py   (needs Pillow)
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "app", "android", "app", "src", "main", "res")
OUT = os.path.join(ROOT, "store", "graphics")

BG = "#1d2026"        # --surface (dark)
BRASS = "#cf9c4f"     # --brass (dark)
INK = "#eceef1"       # --ink (dark)
FAINT = "#6d7480"     # --ink-faint (dark)
SS = 4                # supersampling factor for smooth edges


def ring(size, scale=1.0):
    """The mark alone on a transparent square. `scale` shrinks it for adaptive-icon safe zones."""
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = s * 0.36 * scale
    cx = cy = s / 2
    w = s * 0.085 * scale
    box = [cx - r, cy - r, cx + r, cy + r]
    # faint full circle, then the brass sweep from "12 o'clock" clockwise to ~10 o'clock
    d.arc(box, start=0, end=360, fill=FAINT, width=int(w * 0.45))
    d.arc(box, start=-90, end=210, fill=BRASS, width=int(w))
    # dot at the end of the sweep: "the last time you did it"
    import math
    a = math.radians(210)
    px, py = cx + r * math.cos(a), cy + r * math.sin(a)
    dr = w * 1.05
    d.ellipse([px - dr, py - dr, px + dr, py + dr], fill=BRASS)
    return im.resize((size, size), Image.LANCZOS)


def rounded_bg(size, radius_frac, color=BG):
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * radius_frac), fill=color)
    return im.resize((size, size), Image.LANCZOS)


def circle_bg(size, color=BG):
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([0, 0, s - 1, s - 1], fill=color)
    return im.resize((size, size), Image.LANCZOS)


def icon(size, shape="square"):
    bg = rounded_bg(size, 0.22) if shape == "square" else circle_bg(size)
    bg.alpha_composite(ring(size))
    return bg


def foreground(size):
    """Adaptive-icon foreground: 108dp canvas, artwork inside the central 66dp safe zone."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    im.alpha_composite(ring(size, scale=66 / 108 * 1.15))
    return im


DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

for name, mult in DENSITIES.items():
    folder = os.path.join(RES, "mipmap-" + name)
    os.makedirs(folder, exist_ok=True)
    legacy = int(48 * mult)
    icon(legacy, "square").save(os.path.join(folder, "ic_launcher.png"))
    icon(legacy, "round").save(os.path.join(folder, "ic_launcher_round.png"))
    foreground(int(108 * mult)).save(os.path.join(folder, "ic_launcher_foreground.png"))

with open(os.path.join(RES, "values", "ic_launcher_background.xml"), "w") as f:
    f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
            '    <color name="ic_launcher_background">%s</color>\n</resources>\n' % BG.upper())

os.makedirs(OUT, exist_ok=True)
# Play icon: 512x512, opaque (Play rejects alpha), square corners — Play rounds it itself.
play = Image.new("RGB", (512, 512), BG)
play.paste(ring(512), (0, 0), ring(512))
play.save(os.path.join(OUT, "icon-512.png"))

# Feature graphic: mark + wordmark.
W, H = 1024, 500
fg = Image.new("RGB", (W, H), BG)
mark = ring(360)
fg.paste(mark, (90, (H - 360) // 2), mark)
d = ImageDraw.Draw(fg)
font_path = next((p for p in ["/system/fonts/Roboto-Regular.ttf", "/system/fonts/RobotoStatic-Regular.ttf",
                              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if os.path.exists(p)), None)
big = ImageFont.truetype(font_path, 96) if font_path else ImageFont.load_default()
small = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()
d.text((470, 165), "Hindsight", font=big, fill=INK)
d.text((470, 285), "When did I last do that?", font=small, fill=BRASS)
fg.save(os.path.join(OUT, "feature-1024x500.png"))
print("wrote launcher icons ->", RES)
print("wrote Play graphics  ->", OUT)
