"""Render high-res cover + interior page images for the promo video.

Mirrors what app._cover_thumb_bytes does, but at a larger matrix so the stills
stay crisp when they fill a 1920-wide frame.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)          # promo/ sits one level under the repo root
OUT = os.path.join(HERE, "assets")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
os.chdir(REPO)

import fitz  # noqa: E402
import app as ts  # noqa: E402
import engine, manuscript, matter  # noqa: E402

COVERS = ["fantasy-emerald", "scifi-cosmic", "thriller-noir", "literary-ivory",
          "romance-blush", "vintage-pulp", "minimal-noir", "photo-dusk"]


def render_cover(cid, scale=2.4):
    tpl = ts.load_cover_template(cid)
    if tpl is None:
        print(f"  !! no template {cid}")
        return None
    preset = dict(ts.DEFAULTS)
    preset["trim"] = {"w": 6.0, "h": 9.0}
    meta = {
        "title": "The Salt Road", "author": "Ellinor Vale",
        "year": "2026", "publisher": "Studio",
        "front_matter": "none", "right_hand_starts": False, "smartquotes": True,
        "cover_mode": "designed", "cover_template": cid, "cover_template_data": tpl,
        "cover_collection": "Sample Series", "cover_kicker": "",
        "cover_accent": "", "cover_epigraph": "", "cover_studio": "Studio",
        "cover_image": "", "cover_overlay": False, "cover_color": "light",
        **matter.blank(),
    }
    ms = manuscript.parse_markdown(ts.PREVIEW_SAMPLE, smartquotes=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        engine.build_pdf(ms, preset, tmp, meta)
        doc = fitz.open(tmp)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        dest = os.path.join(OUT, f"cover-{cid}.png")
        pix.save(dest)
        doc.close()
        print(f"  ok cover-{cid}.png  {pix.width}x{pix.height}")
        return dest
    except Exception as e:
        print(f"  !! {cid}: {e}")
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def survey_interior(pdf):
    """Print a per-page word count so we can spot chapter openers (short pages)."""
    doc = fitz.open(pdf)
    print(f"\n{os.path.basename(pdf)}  pages={len(doc)}")
    for i in range(min(len(doc), 24)):
        txt = doc[i].get_text().strip()
        first = " ".join(txt.split()[:9])
        print(f"  p{i:>3} words={len(txt.split()):>4}  {first[:70]}")
    doc.close()


def render_page(pdf, pageno, name, scale=2.6):
    doc = fitz.open(pdf)
    pix = doc[pageno].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    dest = os.path.join(OUT, name)
    pix.save(dest)
    doc.close()
    print(f"  ok {name}  {pix.width}x{pix.height}")
    return dest


def render_spread(pdf, left, name, scale=2.2):
    """Two facing pages side by side on a neutral card."""
    doc = fitz.open(pdf)
    m = fitz.Matrix(scale, scale)
    a = doc[left].get_pixmap(matrix=m, alpha=False)
    b = doc[left + 1].get_pixmap(matrix=m, alpha=False)
    gap = 8
    W, H = a.width + b.width + gap, max(a.height, b.height)
    canvas = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, W, H), False)
    canvas.set_rect(canvas.irect, (231, 228, 220))
    a.set_origin(0, 0)
    canvas.copy(a, a.irect)
    b.set_origin(a.width + gap, 0)
    canvas.copy(b, b.irect)
    dest = os.path.join(OUT, name)
    canvas.save(dest)
    doc.close()
    print(f"  ok {name}  {W}x{H}")
    return dest


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "covers"):
        print("covers:")
        for c in COVERS:
            render_cover(c)
    if mode in ("all", "survey"):
        for p in ("out/the-gardens-of-avenn-20260719-081732.pdf",
                  "out/kinslayer-20260702-100524.pdf",
                  "out/meltwater-20260702-192351.pdf"):
            if os.path.exists(p):
                survey_interior(p)
