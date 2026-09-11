"""Find the horizontal content box of each UI screenshot.

The app centres its content in a max-width container on a flat ground, so most
of each capture is empty. Cropping to the real content makes the UI read roughly
twice as large in the reel at no extra byte cost.

The full-width top nav and the right-hand scrollbar both span the frame, so the
measurement ignores the nav rows and the last few columns.
"""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
# Raw UI captures live outside the repo - they are large and disposable.
# Point TYPESET_PROMO_SHOTS at the directory holding them; it defaults to
# promo/shots/ so a fresh clone has an obvious place to drop them.
SHOTS = os.environ.get("TYPESET_PROMO_SHOTS", os.path.join(HERE, "shots"))
FILES = {
    "uiStyles": "screenshot-1785373640325-0.jpg",
    "uiEditor": "screenshot-1785373679056-3.jpg",
    "uiCoverStudio": "screenshot-1785373679056-4.jpg",
    "uiResult": "screenshot-1785374341292-9.jpg",
}
NAV_H = 80        # skip the full-width header
SB_W = 20         # skip the scrollbar gutter

for name, fn in FILES.items():
    im = Image.open(os.path.join(SHOTS, fn)).convert("RGB")
    W, H = im.size
    body = im.crop((0, NAV_H, W - SB_W, H))
    bw, bh = body.size
    px = body.load()
    bg = px[bw - 6, bh // 2]

    def far(c):
        return max(abs(c[0]-bg[0]), abs(c[1]-bg[1]), abs(c[2]-bg[2])) > 16

    cols = []
    for x in range(bw):
        hits = sum(1 for y in range(0, bh, 3) if far(px[x, y]))
        if hits > 2:
            cols.append(x)
    if not cols:
        print(f"{name}: no content found")
        continue
    l, r = cols[0], cols[-1] + 1
    print(f"{name:<15} {W}x{H} bg={bg}  content x={l}..{r} (w={r-l})")
    print(f"{'':<15} suggested crop = ({max(0,l-14)}, 0, {min(W, r+14)}, {H})"
          f"  aspect={(min(W,r+14)-max(0,l-14))/H:.2f}")
