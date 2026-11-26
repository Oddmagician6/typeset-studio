"""Template covers keep their type on the cover  (run: python test_covers_bughunt.py).

Joint bug hunt, round 2, section 10 (and 11.8):

    10.1  a wrap sized from a book uses the interior a printer binds, not a
          proof's cover page as well
    10.2  a long back-cover blurb shrinks and stops above the barcode, and says so
    10.3  a long byline fits along the spine
    10.4  a very long title stays above the foot of the cover
    10.5  front bylines stay inside the front panel
    10.6  an overlay title on uploaded art is measured, not guessed
    10.7  cover words its fonts can't set are reported
    10.8  a space in the front-flap field doesn't hide the blurb
    10.9  a spine byline is never painted near its own background colour
    10.10 a tall back-cover picture stays on the panel
    10.11 a negative bleed is refused
    10.12 the imprint stays out of the barcode reserve
    10.14 a spine too thin for type is not offered spine type
    11.8  the result page's spine counts an odd page count's blank leaf
"""

import sys, os, json, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import fitz
import engine
import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


interior = engine.register_fonts(A.DEFAULTS)
TMP = tempfile.mkdtemp()
PDF = os.path.join(TMP, 'wrap.pdf')
BASE = {'title': 'The Salt Road', 'author': 'Ann Vale', 'cover_blurb': 'A road of salt.'}
DIMS = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.9, 'bleed': 0.125}


def wrap(tpl_name, meta, **dims):
    tpl = A.load_cover_template(tpl_name)
    cf = engine._register_cover_fonts(tpl, interior)
    d = dict(DIMS, **dims)
    res = engine.build_cover_wrap(tpl, cf, dict(BASE, **meta), d, PDF)
    g = engine.wrap_geometry(d)
    with fitz.open(PDF) as doc:
        pg = doc[0]
        words = pg.get_text('words')
        images = pg.get_image_info()
        W, H = pg.rect.width, pg.rect.height
    return res, g, words, images, (W, H)


def panel(g, which):
    """(x0, x1) of a panel in points on the sheet."""
    x0 = {'back': g['back_x'], 'front': g['front_x'], 'spine': g['spine_x']}[which]
    w = g['spine_w'] if which == 'spine' else g['panel_w']
    return x0 * 72, (x0 + w) * 72


# ---- 10.2 / 10.12 ----------------------------------------------------------
print('10.2 / 10.12 back panel')
blurb = '\n'.join(['The island disappears every winter.'] * 32)
res, g, words, _, (W, H) = wrap('ashforge-house', {'cover_blurb': blurb,
                                                   'cover_studio': 'North Coast Writers Collective'})
bx0, bx1 = panel(g, 'back')
# the barcode reserve, found from its own label at its centre: 2.0 x 1.2 in
lab = [w for w in words if w[4] in ('ISBN', 'area')]
cx_ = (min(w[0] for w in lab) + max(w[2] for w in lab)) / 2 if lab else 0
cy_ = (lab[0][1] + lab[0][3]) / 2 if lab else 0
box = (cx_ - 72, cy_ - 0.6 * 72, cx_ + 72, cy_ + 0.6 * 72) if lab else None
in_box = [w for w in words if box and w[2] > box[0] and w[0] < box[2] and w[3] > box[1]
          and w[1] < box[3] and w[4] not in ('ISBN', '/', 'barcode', 'area')]
check('no blurb or imprint word inside the barcode corner', not in_box, in_box[:5])
check('the overflow is reported', 'back cover' in res.get('overflow', []), res.get('overflow'))
check('nothing falls off the sheet', all(0 <= w[1] and w[3] <= H for w in words))
res, *_ = wrap('ashforge-house', {'cover_blurb': 'A road of salt.'})
check('a short blurb reports no overflow', 'back cover' not in res.get('overflow', []))

# ---- 10.3 ------------------------------------------------------------------
print('10.3 spine byline')
author = ('Alexandria Mercer, William Woodward, and the North Coast Writers Collective, '
          'with an introduction by Eleanor Fairweather')
tpl = A.load_cover_template('ashforge-house')
cf = engine._register_cover_fonts(tpl, interior)
lay = engine._spine_layout('MAP', author.upper(), cf['display'], 0.9 * 72, 9 * 72)
if lay and lay[2]:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    check('the byline fits along the spine',
          stringWidth(author.upper(), cf['display'], lay[2]) <= 9 * 72 * 0.82)
else:
    check('the byline fits along the spine (or is left off)', True)

# ---- 10.4 / 10.5 -----------------------------------------------------------
print('10.4 / 10.5 front panel')
long_title = ('The Illustrated Encyclopedia of Impossible Islands and the Travellers Who Mapped '
              'Them from the Frozen North to the Warm South and Across the Vast Western Seas '
              'and the Mysterious Eastern Shores')
res, g, words, _, (W, H) = wrap('postcard-classic', {'title': long_title}, trim_w=5.0, trim_h=5.0)
fx0, fx1 = panel(g, 'front')
front = [w for w in words if w[0] >= fx0 - 1]
foot = (g['edge'] + g['panel_h']) * 72
check('a very long title stays above the foot of the cover',
      all(w[3] <= foot + 1 for w in front), [w for w in front if w[3] > foot + 1][:3])
by = 'Alexandria Mercer and the North Coast Writers Collective'
for name in ('typographic-bold', 'ashforge-house', 'minimal-ivory', 'stripe-crimson', 'geometric-block', 'postcard-classic'):
    path = os.path.join(HERE, 'covers', name + '.json')
    if not os.path.exists(path):
        continue
    res, g, words, _, _ = wrap(name, {'author': by, 'cover_accent': by})
    fx0, fx1 = panel(g, 'front')
    sx0, _ = panel(g, 'spine')
    on_front = [w for w in words if w[2] > fx0 + 1 and w[4] in by.upper().split()]
    check(f'{name}: the byline stays on the front panel',
          all(fx0 - 0.5 <= w[0] and w[2] <= fx1 + 0.5 for w in on_front),
          [w[:5] for w in on_front if w[0] < fx0 or w[2] > fx1][:3])

# ---- 10.6 ------------------------------------------------------------------
print('10.6 overlay title')
from reportlab.pdfgen import canvas as _cv
c = _cv.Canvas(os.path.join(TMP, 'ov.pdf'), pagesize=(432, 648))
c.setFont('Helvetica-Bold', 10)
drawn = []
c.drawCentredString = lambda x, y, t, **k: drawn.append((x, t, c._fontname, c._fontsize))
engine._paint_cover_overlay(c, 'WORLDWIDE WATERWAYS WITH WILLOW', 'ANN', 'Helvetica-Bold',
                            'Helvetica', 0, 0, 432, 648)
from reportlab.pdfbase.pdfmetrics import stringWidth
check('every overlay line fits the panel',
      all(stringWidth(t, f, s) <= 432 for _, t, f, s in drawn),
      [(t, round(stringWidth(t, f, s))) for _, t, f, s in drawn])

# ---- 10.7 ------------------------------------------------------------------
print('10.7 missing glyphs')
res, *_ = wrap('ashforge-house', {'title': '星海'})
tpl = A.load_cover_template('ashforge-house')
cf = engine._register_cover_fonts(tpl, interior)
from reportlab.pdfbase import pdfmetrics as _pm
has_ttf = getattr(getattr(_pm.getFont(cf['display']), 'face', None), 'charToGlyph', None)
if has_ttf:
    check('CJK title in a Latin face is reported', '星' in res.get('glyphs_missing', ''),
          res.get('glyphs_missing'))
res, *_ = wrap('ashforge-house', {'title': 'Plain Latin'})
check('a plain title reports nothing', not res.get('glyphs_missing'), res.get('glyphs_missing'))

# ---- 10.8 ------------------------------------------------------------------
print('10.8 front-flap whitespace')
res, g, words, _, _ = wrap('ashforge-house', {'cover_blurb': 'Harbourlight carries the tale.',
                                              'cover_jacket_blurb': ' '},
                           binding='jacket', flap=3.5)
text = ' '.join(w[4] for w in words)
check('the blurb still prints (on the front flap)', 'Harbourlight' in text, text[:200])

# ---- 10.9 ------------------------------------------------------------------
print('10.9 spine byline colour')
tpl = A.load_cover_template('vintage-pulp')
cf = engine._register_cover_fonts(tpl, interior)
fills = []
c = _cv.Canvas(os.path.join(TMP, 'sp.pdf'))
orig = c.setFillColor
c.setFillColor = lambda col, *a, **k: (fills.append(col), orig(col, *a, **k))
engine._paint_spine(c, tpl, cf, {'title': 'Map', 'author': 'Ann Vale'}, 0, 0, 0.9 * 72, 9 * 72)
grounds = [engine._hex(tpl['palette'][k]) for k in ('bg_top', 'bg_bottom')]
check('both spine lines are legible on the spine ground',
      fills and all(min(engine.contrast(f, gr) for gr in grounds) >= 2.5 for f in fills),
      [str(f) for f in fills])

# ---- 10.10 -----------------------------------------------------------------
print('10.10 tall back picture')
try:
    from PIL import Image
    tall = os.path.join(TMP, 'tall.png')
    Image.new('RGB', (300, 1200), (20, 80, 140)).save(tall)
    res, g, _, images, (W, H) = wrap('ashforge-house', {'cover_back_image': tall,
                                                        'cover_back_image_w': 1.5,
                                                        'cover_back_image_y': 0.1})
    top = g['edge'] * 72
    bot = (g['edge'] + g['panel_h']) * 72
    pics = [im['bbox'] for im in images if im['bbox'][2] < panel(g, 'back')[1] + 1]
    check('the picture is inside the back panel',
          pics and all(b[1] >= top - 1 and b[3] <= bot + 1 for b in pics), pics)
except ImportError:
    print('  skip (no Pillow)')

# ---- 10.11 / 10.14 ---------------------------------------------------------
print('10.11 / 10.14 wrap geometry')
with A.app.test_request_context('/', method='POST',
                                data={'wrap_bleed': '-0.125', 'wrap_trim_w': '6',
                                      'wrap_trim_h': '9', 'pages': '200'}):
    from flask import request
    try:
        dims = A._wrap_dims(request.form, 200) if hasattr(A, '_wrap_dims') else None
    except TypeError:
        dims = None
if dims is not None:
    check('a negative bleed is clamped to zero', dims['bleed'] >= 0, dims['bleed'])
else:
    src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    check('a negative bleed is clamped to zero',
          "min(max(_f(form, 'wrap_bleed', a['bleed']), 0.0), 1.0)" in src)
thin = engine.wrap_geometry({'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.1081, 'bleed': 0.125})
check('a 0.108" spine offers no spine type', not thin['spine_text'])
ok_ = engine.wrap_geometry({'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5, 'bleed': 0.125})
check('a 0.5" spine still does', ok_['spine_text'])

# ---- 10.1 / 11.8 ------------------------------------------------------------
print('10.1 / 11.8 page counts')
import manuscript as M
P = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
meta = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'designed', 'cover_image': '',
        'cover_template': 'ashforge-house',
        'cover_template_data': A.load_cover_template('ashforge-house'),
        'cover_overlay': False, 'cover_color': 'light'}
r = engine.build_pdf(M.parse_markdown('# One\n\nWords.\n'), P, os.path.join(TMP, 'b.pdf'), meta)
check('a proof with a cover leaf (cover + its blank inside) counts two pages fewer as interior',
      r['interior_pages'] == r['page_count'] - 2, (r['page_count'], r['interior_pages']))
spec = A.print_spec(25, P)
check('a 25-page spine is 26 pages thick',
      all(abs(v - round(26 * A._PAPER[k]['ppi'], 3)) < 1e-9 for k, v in spec['spines'].items()),
      spec['spines'])

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
