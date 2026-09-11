"""Downscale + JPEG-compress every still, then emit one JS module of data URIs.

A published Artifact runs under a strict CSP that blocks external hosts, so every
image has to travel inside the HTML. Sizes below are tuned to how large each still
actually appears in the ad, not to the source resolution.
"""
import base64
import io
import json
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
# Raw UI captures live outside the repo - they are large and disposable.
# Point TYPESET_PROMO_SHOTS at the directory holding them; it defaults to
# promo/shots/ so a fresh clone has an obvious place to drop them.
SHOTS = os.environ.get("TYPESET_PROMO_SHOTS", os.path.join(HERE, "shots"))

# The app centres its content in a max-width container, so each capture is
# mostly empty ground. Cropping to the measured content box (see
# measure_content.py) makes the UI read about twice as large in the reel
# without costing a byte. Boxes are (left, top, right, bottom) in source px.
CROP = {
    "uiStyles":      (441, 0, 1465, 784),
    "uiEditor":      (346, 0, 1162, 784),
    "uiCoverStudio": (346, 0, 1162, 784),
    # The result page is cropped to the two cards that carry the claim -
    # print spec and the all-clear preflight - so the real numbers stay
    # legible in the frame instead of shrinking to texture.
    "uiResult":      (346, 452, 866, 744),
}

# name -> (source path, target width, jpeg quality)
UI = {
    "uiStyles":   (os.path.join(SHOTS, "screenshot-1785373640325-0.jpg"), 1100, 72),
    "uiEditor":   (os.path.join(SHOTS, "screenshot-1785373679056-3.jpg"), 900, 74),
    "uiCoverStudio": (os.path.join(SHOTS, "screenshot-1785373679056-4.jpg"), 900, 74),
    "uiResult":   (os.path.join(SHOTS, "screenshot-1785374341292-9.jpg"), 560, 80),
}

PAGES = {
    "heroCover":  (os.path.join(ASSETS, "hero-cover-page.png"), 780, 80),
    "chapter1":   (os.path.join(ASSETS, "hero-chapter1.png"), 760, 82),
    "spread":     (os.path.join(ASSETS, "hero-spread.png"), 1440, 78),
}

WALL = [
    "fantasy-emerald", "geometric-block", "photo-dusk", "typographic-bold",
    "stripe-crimson", "romance-blush", "thriller-noir", "vintage-pulp",
    "photo-forest", "geometric-coral", "minimal-noir", "literary-ivory",
    "scifi-cosmic", "typographic-noir", "stripe-indigo", "photo-sand",
    "vintage-rust", "geometric-mono",
]


def encode(path, width, quality, crop=None):
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    if im.width > width:
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    raw = buf.getvalue()
    return f"data:image/jpeg;base64,{base64.b64encode(raw).decode()}", len(raw), im.size


out, total = {}, 0
for group in (UI, PAGES):
    for name, (path, w, q) in group.items():
        if not os.path.exists(path):
            print(f"  !! MISSING {name}: {path}")
            continue
        uri, n, size = encode(path, w, q, CROP.get(name))
        out[name] = uri
        total += n
        ar = size[0] / size[1]
        print(f"  {name:<16} {size[0]}x{size[1]:<5} a={ar:.2f}  {n/1024:7.1f} KB")

wall = []
for cid in WALL:
    p = os.path.join(ASSETS, f"cover-{cid}.png")
    if not os.path.exists(p):
        print(f"  !! MISSING cover {cid}")
        continue
    uri, n, size = encode(p, 250, 74)
    wall.append(uri)
    total += n
print(f"  {'wall x' + str(len(wall)):<16} 250 wide     {sum(1 for _ in wall)} covers")
out["wall"] = wall

dest = os.path.join(HERE, "assets.js")
with open(dest, "w", encoding="utf-8") as f:
    f.write("const A = ")
    json.dump(out, f)
    f.write(";\n")

b64_total = os.path.getsize(dest)
print(f"\n  raw jpeg total : {total/1024/1024:.2f} MB")
print(f"  assets.js      : {b64_total/1024/1024:.2f} MB  -> {dest}")
