"""Pack assets for the 9:16 vertical cut.

Different sizing from the 16:9 reel: portrait stills (the cover, a chapter
opener) become hero elements and need more pixels, the wide page spread is
dropped entirely because it cannot read at 1080 wide, and the cover wall is
12 rather than 18 so each tile stays legible on a phone.
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

CROP = {
    "uiStyles":      (441, 0, 1465, 784),
    "uiEditor":      (346, 0, 1162, 784),
    "uiCoverStudio": (346, 0, 1162, 784),
    "uiResult":      (346, 452, 866, 744),
}

UI = {
    "uiStyles":      (os.path.join(SHOTS, "screenshot-1785373640325-0.jpg"), 1000, 76),
    "uiEditor":      (os.path.join(SHOTS, "screenshot-1785373679056-3.jpg"), 950, 78),
    "uiCoverStudio": (os.path.join(SHOTS, "screenshot-1785373679056-4.jpg"), 950, 78),
    "uiResult":      (os.path.join(SHOTS, "screenshot-1785374341292-9.jpg"), 900, 82),
}

PAGES = {
    "heroCover": (os.path.join(ASSETS, "hero-cover-page.png"), 900, 84),
    "chapter1":  (os.path.join(ASSETS, "hero-chapter1.png"), 860, 86),
}

# 12 covers, picked for structural variety rather than colour variety:
# framed, banded, bottom-weighted, spine-stripe, oversized-type, author-band.
WALL = [
    "fantasy-emerald", "geometric-block", "photo-dusk", "typographic-bold",
    "stripe-crimson", "romance-blush", "thriller-noir", "vintage-pulp",
    "photo-forest", "geometric-coral", "literary-ivory", "stripe-indigo",
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
            raise SystemExit(f"MISSING {name}: {path}")
        uri, n, size = encode(path, w, q, CROP.get(name))
        out[name] = uri
        total += n
        print(f"  {name:<16} {size[0]}x{size[1]:<5} a={size[0]/size[1]:.2f}  {n/1024:7.1f} KB")

wall = []
for cid in WALL:
    p = os.path.join(ASSETS, f"cover-{cid}.png")
    if not os.path.exists(p):
        raise SystemExit(f"MISSING cover {cid}")
    uri, n, _ = encode(p, 300, 78)
    wall.append(uri)
    total += n
out["wall"] = wall
print(f"  {'wall x' + str(len(wall)):<16} 300 wide")

dest = os.path.join(HERE, "assets_v.js")
with open(dest, "w", encoding="utf-8") as f:
    f.write("const A = ")
    json.dump(out, f)
    f.write(";\n")

print(f"\n  raw jpeg total : {total/1024/1024:.2f} MB")
print(f"  assets_v.js    : {os.path.getsize(dest)/1024/1024:.2f} MB")
