"""Template art reaches the bleed  (run: python test_wrap_bleed.py).

A wrap is printed bigger than the book and cut down, and the cut wanders. So
whatever a designed front cover puts at its edge - background art, a vignette,
a flat ground, a full-height band - has to carry on past the trim to the edge
of what is printed, or a sliver of the gradient underneath shows on the
finished book. This renders every design family's front, with and without
art, on each binding, and compares a strip just inside each trimmed edge with
a strip just outside it: they must be the same colour.

The edges checked are the head, the tail and the fore-edge. The spine side is
a fold, not a cut, and on a dust jacket the fore-edge is the fold to the flap.
"""

import sys, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import engine
import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


DPI = 144
TOL = 10            # mean difference per channel, out of 255, either side of a trim
META = {'title': 'The Salt Road', 'author': 'Ellinor Vale',
        'cover_collection': 'Edenfall Collection', 'cover_studio': 'Ashforge Studio'}
BINDINGS = {
    'paperback': {},
    'hardcover': {'binding': 'hardcover'},
    'jacket':    {'binding': 'jacket'},
}
# one template per design family, plus a right-hand stripe so its band meets
# the fore-edge
FAMILIES = ['ashforge-house', 'photo-dusk', 'typographic-bold', 'geometric-block',
            'vintage-pulp', 'minimal-ivory', 'stripe-crimson', 'postcard-classic']

tmp = tempfile.mkdtemp()
ART = os.path.join(tmp, 'art.png')
from PIL import Image
Image.new('RGB', (600, 900), (40, 160, 90)).save(ART)   # a colour no palette uses
PDF = os.path.join(tmp, 'wrap.pdf')
interior = engine.register_fonts(A.DEFAULTS)


def strip_mean(pix, x0, y0, x1, y1):
    """Mean RGB over a pixel rectangle."""
    n, tot = 0, [0, 0, 0]
    for y in range(int(y0), int(y1)):
        for x in range(int(x0), int(x1)):
            p = pix.pixel(x, y)
            for i in range(3):
                tot[i] += p[i]
            n += 1
    return [t / n for t in tot]


def edges_match(tpl, binding, label):
    import fitz
    cf = engine._register_cover_fonts(tpl, interior)
    dims = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5, 'bleed': 0.125}
    dims.update(BINDINGS[binding])
    engine.build_cover_wrap(tpl, cf, META, dims, PDF)
    g = engine.wrap_geometry(dims)
    k = DPI                                  # pixels per inch
    with fitz.open(PDF) as doc:
        pix = doc[0].get_pixmap(dpi=DPI)
    H = pix.height
    fx0, fx1 = g['front_x'] * k, (g['front_x'] + g['panel_w']) * k
    top = g['edge'] * k                      # the head's trim, from the top of the image
    foot = (g['edge'] + g['panel_h']) * k
    a, b = 4, 9                              # sample 4..9 px either side of the line
    mid0, mid1 = fx0 + 0.6 * k, fx1 - 0.6 * k
    pairs = {
        'head': ((mid0, top + a, mid1, top + b), (mid0, top - b, mid1, top - a)),
        'tail': ((mid0, foot - b, mid1, foot - a), (mid0, foot + a, mid1, foot + b)),
    }
    if not g['flap']:
        pairs['fore-edge'] = ((fx1 - b, top + 0.6 * k, fx1 - a, foot - 0.6 * k),
                              (fx1 + a, top + 0.6 * k, fx1 + b, foot - 0.6 * k))
    for edge, (inside, outside) in pairs.items():
        mi, mo = strip_mean(pix, *inside), strip_mean(pix, *outside)
        diff = max(abs(p - q) for p, q in zip(mi, mo))
        check('%s, %s: the %s carries on past the trim' % (label, binding, edge),
              diff <= TOL, 'inside %s outside %s' % ([round(v) for v in mi],
                                                     [round(v) for v in mo]))
    assert H > 0


for name in FAMILIES:
    base = A.load_cover_template(name)
    variants = [(name, base)]
    if name.startswith('stripe'):
        right = dict(base, stripe=dict(base.get('stripe', {}), side='right'))
        variants.append((name + ' (right)', right))
    for label, tpl in variants:
        with_art = dict(tpl, background=dict(tpl.get('background') or {}, image=ART))
        for binding in BINDINGS:
            edges_match(tpl, binding, label)
            edges_match(with_art, binding, label + ' with art')


# --------------------------------------------- the interior's page 1 cover is untouched
print()
tpl = A.load_cover_template('photo-dusk')
calls = []
orig = engine._draw_image_cover
engine._draw_image_cover = lambda canv, path, x, y, w, h: calls.append((x, y, w, h))
try:
    from reportlab.pdfgen import canvas as _canvas
    c = _canvas.Canvas(os.path.join(tmp, 'page.pdf'), pagesize=(432, 648))
    engine._paint_background(c, dict(tpl, background={'image': ART}), 0, 0, 432, 648)
finally:
    engine._draw_image_cover = orig
check('without a bleed, background art fills just the panel it is given',
      calls == [(0, 0, 432, 648)], calls)


print()
print('ALL PASS' if not fails else '%d FAILED' % len(fails))
sys.exit(1 if fails else 0)
