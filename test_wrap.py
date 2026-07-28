"""Print-wrap tests  (run: python test_wrap.py).

A wrap is arithmetic that gets cut with a knife: if the page is the wrong size
by an eighth of an inch the book is wrong, and nothing on screen says so. So
this file checks the geometry against the retailers' published formulas — for
the paperback that shipped first, and for the case-laminate hardcover —
measures the real PDF's page box, and pins the one thing that must never move:
a paperback wrap is the same size it always was.

    paperback : bleed + back + spine + front + bleed
    hardcover : wrap + bleed + back + hinge + spine + hinge + front + bleed + wrap
"""

import sys, os, re, json, tempfile

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


TPL = A.load_cover_template('ashforge-house')
META = {'title': 'The Salt Road', 'author': 'Ellinor Vale', 'publisher': 'Ashforge',
        'cover_collection': 'Edenfall Collection', 'cover_accent': 'Ellinor Vale',
        'cover_blurb': 'A road of salt, and the woman who walked it.',
        'cover_studio': 'Ashforge Studio'}

interior = engine.register_fonts(A.DEFAULTS)
CF = engine._register_cover_fonts(TPL, interior)

fd, PDF = tempfile.mkstemp(suffix='.pdf'); os.close(fd)


def build(**dims):
    d = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5, 'bleed': 0.125}
    d.update(dims)
    return engine.build_cover_wrap(TPL, CF, META, d, PDF), d


def page_size():
    """The finished page box, in inches, straight out of the file."""
    import fitz
    with fitz.open(PDF) as doc:
        r = doc[0].rect
    return round(r.width / 72.0, 3), round(r.height / 72.0, 3)


# ------------------------------------------------------------ the paperback
print('the paperback wrap')
res, d = build()
check('the width is bleed + back + spine + front + bleed',
      res['wrap_w'] == 2 * 0.125 + 2 * 6.0 + 0.5, res['wrap_w'])
check('the height is bleed + trim + bleed', res['wrap_h'] == 9.0 + 0.25, res['wrap_h'])
check('the file is the size the builder reported', page_size() == (res['wrap_w'], res['wrap_h']),
      (page_size(), res['wrap_w'], res['wrap_h']))
check('it says which binding it made', res['binding'] == 'paperback', res)
check('and carries no hardcover allowances',
      res['wrap'] == 0 and res['hinge'] == 0, res)
# the regression that matters: hardcover support must not have moved a paperback
check('a paperback is the size it was before hardcovers existed',
      (res['wrap_w'], res['wrap_h']) == (12.75, 9.25), (res['wrap_w'], res['wrap_h']))

# ------------------------------------------------------------ the hardcover
print('the case laminate')
res, d = build(binding='hardcover', spine_w=0.5104, wrap=0.625, hinge=0.375)
# KDP's own worked example: 6x9, 200pp white paper -> 14.7604" wide
check('the width follows the published formula',
      res['wrap_w'] == round(2 * 0.625 + 2 * 0.125 + 2 * 6.0 + 2 * 0.375 + 0.5104, 3),
      res['wrap_w'])
check("and matches KDP's worked example for a 200-page 6×9",
      res['wrap_w'] == 14.76, res['wrap_w'])
check('the height adds the turn-in top and bottom',
      res['wrap_h'] == 9.0 + 2 * 0.125 + 2 * 0.625, res['wrap_h'])
check('the file is the size the builder reported', page_size() == (res['wrap_w'], res['wrap_h']),
      (page_size(), res['wrap_w'], res['wrap_h']))
check('it reports the allowances it used',
      res['binding'] == 'hardcover' and res['wrap'] == 0.625 and res['hinge'] == 0.375, res)

wide = build(binding='hardcover', spine_w=0.5104, wrap=0.625, hinge=0.5)[0]
check('a wider hinge widens the wrap by two of them',
      round(wide['wrap_w'] - res['wrap_w'], 3) == 0.25, (wide['wrap_w'], res['wrap_w']))
none = build(binding='hardcover', wrap=0, hinge=0, spine_w=0.5)[0]
check('zeroed allowances collapse onto the paperback geometry',
      (none['wrap_w'], none['wrap_h']) == (12.75, 9.25), none)
neg = build(binding='hardcover', wrap=-1, hinge=-1)[0]
check('a negative allowance is floored, not subtracted',
      neg['wrap'] == 0 and neg['hinge'] == 0, neg)

# spine text is a retailer rule, and must survive the new geometry
thin = build(binding='hardcover', spine_w=0.05, pages=90, spine_text_min=75)[0]
check('a spine too thin to read carries no text', thin['spine_text'] is False, thin)
short = build(binding='hardcover', spine_w=0.5, pages=40, spine_text_min=75)[0]
check('and neither does a book under the page minimum', short['spine_text'] is False, short)
ok = build(binding='hardcover', spine_w=0.5, pages=300, spine_text_min=75)[0]
check('a thick enough book gets it', ok['spine_text'] is True, ok)

# guides must not change the page, only what is drawn on it
guided_dims = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.5104, 'bleed': 0.125,
               'binding': 'hardcover', 'wrap': 0.625, 'hinge': 0.375}
engine.build_cover_wrap(TPL, CF, META, dict(guided_dims), PDF)
plain_size, plain_bytes = page_size(), os.path.getsize(PDF)
engine.build_cover_wrap(TPL, CF, META, dict(guided_dims), PDF, guides=True)
check('proof guides do not resize the wrap', page_size() == plain_size,
      (page_size(), plain_size))
check('but they do draw something', os.path.getsize(PDF) != plain_bytes)

# ------------------------------------------------------------ the dust jacket
print('the dust jacket')
res, d = build(binding='jacket', spine_w=0.5104, flap=3.5, board_ext=0.125, hinge=0.375)
check('the width is bleed + flap + board + hinge + spine + hinge + board + flap + bleed',
      res['wrap_w'] == round(2 * 0.125 + 2 * 3.5 + 2 * (6.0 + 0.125)
                             + 2 * 0.375 + 0.5104, 3), res['wrap_w'])
check('the height is the board, not the block',
      res['wrap_h'] == round(9.0 + 2 * 0.125 + 2 * 0.125, 3), res['wrap_h'])
check('the panels are the board width', res['panel_w'] == 6.125, res['panel_w'])
check('the file is the size the builder reported', page_size() == (res['wrap_w'], res['wrap_h']),
      (page_size(), res['wrap_w'], res['wrap_h']))
check('it reports the flap it used',
      res['binding'] == 'jacket' and res['flap'] == 3.5, res)
check('a jacket has no turn-in — the flaps do that job', res['wrap'] == 0, res)

wider = build(binding='jacket', spine_w=0.5104, flap=4.0)[0]
check('a wider flap widens the jacket by two of them',
      round(wider['wrap_w'] - res['wrap_w'], 3) == 1.0, (wider['wrap_w'], res['wrap_w']))
noflap = build(binding='jacket', spine_w=0.5104, flap=0, board_ext=0, hinge=0)[0]
check('zeroed jacket allowances collapse onto the paperback geometry',
      (noflap['wrap_w'], noflap['wrap_h']) == (12.76, 9.25), noflap)

# the flaps must actually carry their copy — and the back panel must not repeat it
import fitz
JMETA = dict(META, cover_jacket_blurb='The hook, set on the front flap.',
             cover_author_bio='Ellinor Vale lives on the coast.')


def jacket_text(meta):
    engine.build_cover_wrap(TPL, CF, meta,
                            {'trim_w': 6, 'trim_h': 9, 'spine_w': 0.5104, 'bleed': 0.125,
                             'binding': 'jacket', 'flap': 3.5, 'board_ext': 0.125,
                             'hinge': 0.375}, PDF)
    with fitz.open(PDF) as doc:
        page = doc[0]
        w = page.rect.width
        # left flap, then right flap, in page coordinates
        boxes = [page.get_textbox(fitz.Rect(0, 0, 3.7 * 72, page.rect.height)),
                 page.get_textbox(fitz.Rect(w - 3.7 * 72, 0, w, page.rect.height)),
                 page.get_textbox(fitz.Rect(3.7 * 72, 0, w - 3.7 * 72, page.rect.height))]
    # these faces extract glyph by glyph, so compare with the spaces squeezed out
    return [re.sub(r'\s+', '', b) for b in boxes]


left, right, middle = jacket_text(JMETA)
check('the front flap carries the jacket blurb', 'Thehook' in right, right[:80])
check('the back flap carries the author note',
      'coast' in left and 'ABOUTTHEAUTHOR' in left, left[:80])
check('the title heads the front flap', 'SALT' in right, right[:80])
check('the back panel keeps its own blurb when the flap has copy of its own',
      'roadofsalt' in middle, middle[:120])

# Flap copy must stay inside its fold. It didn't at first: character spacing is
# part of the PDF text state, so a plain drawString after a letterspaced line
# inherited the tracking, and the copy — measured untracked — ran past the fold.
def overruns():
    with fitz.open(PDF) as doc:            # the jacket built by jacket_text above
        page = doc[0]
        w = page.rect.width
        folds = (3.5 * 72, w - 3.5 * 72)
        bad = []
        for x0, y0, x1, y1, word, *_ in page.get_text('words'):
            if x1 <= folds[0] + 0.5 or x0 >= folds[1] - 0.5:
                continue                   # comfortably inside a flap
            if x0 < folds[0] < x1 or x0 < folds[1] < x1:
                bad.append(word)           # straddles the fold
    return bad


check('no flap copy crosses its fold', not overruns(), overruns()[:6])

left2, right2, middle2 = jacket_text(dict(META))     # no jacket-specific copy
check('with no flap copy the blurb moves to the flap',
      'roadofsalt' in right2, right2[:80])
check('and is not printed twice on one jacket', 'roadofsalt' not in middle2, middle2[:120])

# ------------------------------------------------------------ the app
print('the form')
form = {'name': 'Test', 'wrap_binding': 'hardcover', 'wrap_retailer': 'kdp',
        'wrap_trim_w': '6', 'wrap_trim_h': '9', 'wrap_pages': '200',
        'wrap_paper': 'white', 'wrap_bleed': '0.125'}
res, dims = A._wrap_from_form(form, PDF)
check('the spine carries the boards as well as the paper',
      abs(dims['spine_w'] - (200 * 0.002252 + 0.06)) < 1e-9, dims['spine_w'])
check('and the wrap comes out at the published size', res['wrap_w'] == 14.76, res['wrap_w'])
check('the defaults come from the documented allowances',
      dims['wrap'] == A.HARDCOVER['wrap'] and dims['hinge'] == A.HARDCOVER['hinge'], dims)

pb = A._wrap_from_form(dict(form, wrap_binding='paperback'), PDF)
check('a paperback spine is paper alone',
      abs(pb[1]['spine_w'] - 200 * 0.002252) < 1e-9, pb[1]['spine_w'])
check('and a paperback takes no hardcover warnings', pb[1]['warnings'] == [], pb[1]['warnings'])

jr, jd = A._wrap_from_form(dict(form, wrap_binding='jacket'), PDF)
check('a jacket takes the same spine as the case it covers',
      abs(jd['spine_w'] - dims['spine_w']) < 1e-9, jd['spine_w'])
check('and its defaults come from the documented jacket figures',
      jd['flap'] == A.JACKET['flap'] and jd['board_ext'] == A.JACKET['board_ext'], jd)
check('a jacket ordered from KDP is flagged, because KDP does not print them',
      any('does not print dust jackets' in w for w in jd['warnings']), jd['warnings'])
check('IngramSpark is not', not any('does not print' in w for w in
      A._wrap_from_form(dict(form, wrap_binding='jacket',
                             wrap_retailer='ingramspark'), PDF)[1]['warnings']))
check('an unknown binding falls back to a paperback',
      A._wrap_from_form(dict(form, wrap_binding='nonsense'), PDF)[1]['binding'] == 'paperback')

print('the retailer limits')
check('a book inside KDP\'s hardcover programme is not flagged',
      A.hardcover_warnings('kdp', 6.0, 9.0, 200, 'white') == [],
      A.hardcover_warnings('kdp', 6.0, 9.0, 200, 'white'))
check('too few pages is flagged',
      any('75' in w for w in A.hardcover_warnings('kdp', 6.0, 9.0, 40, 'white')))
check('too many pages is flagged',
      any('550' in w for w in A.hardcover_warnings('kdp', 6.0, 9.0, 900, 'white')))
check('an unsupported trim is flagged',
      any('trims' in w or 'only' in w for w in A.hardcover_warnings('kdp', 5.0, 8.0, 200, 'white')),
      A.hardcover_warnings('kdp', 5.0, 8.0, 200, 'white'))
check('a hardcover trim with an odd decimal still passes',
      A.hardcover_warnings('kdp', 6.14, 9.21, 200, 'white') == [])
check('cream paper is flagged, because KDP prints hardcovers on white',
      len(A.hardcover_warnings('kdp', 6.0, 9.0, 200, 'cream')) == 1)
check('other retailers get their note, not invented limits',
      A.hardcover_warnings('ingramspark', 5.0, 8.0, 900, 'cream') == [])
check('every retailer preset carries a hardcover note',
      all(r.get('hardcover_note') for r in A.WRAP_RETAILERS.values()))

os.remove(PDF)

# ------------------------------------------------------------ the editor
print('the cover editor')
A.app.config['TESTING'] = True
client = A.app.test_client()
page = client.get('/cover/ashforge-house').get_data(as_text=True)
check('the binding selector renders all three', 'name="wrap_binding"' in page
      and 'Hardcover — case laminate' in page and 'Dust jacket' in page)
check('the hardcover allowances render, hidden until chosen',
      all(f'name="wrap_{f}"' in page for f in ('turnin', 'hinge', 'board'))
      and re.search(r'id="wrap-hardcover"[^>]*hidden', page))
check('so do the jacket fields and the flap copy',
      all(f'name="wrap_{f}"' in page for f in ('flap', 'board_ext', 'flap_blurb', 'flap_bio'))
      and re.search(r'id="wrap-jacket"[^>]*hidden', page)
      and re.search(r'id="wrap-flap-copy"[^>]*hidden', page))
check('the retailer notes reach the page as data',
      'hardcover_note' in page)

# 200 white pages is a 0.4504" paper spine, plus the boards on the hardcover
for binding, expect_w in (('paperback', 12.7), ('hardcover', 14.76), ('jacket', 20.76)):
    r = client.post('/cover/wrap/preview', data=dict(form, wrap_binding=binding))
    j = r.get_json()
    check(f'the {binding} wrap previews', j.get('ok'), j.get('error'))
    check(f'and the {binding} info line reports the finished size',
          f'{expect_w:g}' in (j.get('info') or ''), j.get('info'))
check('the hardcover preview reports the case allowances',
      'case laminate' in (client.post('/cover/wrap/preview',
                                      data=dict(form, wrap_binding='hardcover'))
                          .get_json().get('info') or ''))
j = client.post('/cover/wrap/preview',
                data=dict(form, wrap_binding='hardcover', wrap_pages='900')).get_json()
check('an over-length hardcover comes back with a warning', j.get('warnings'), j)

for binding, fname in (('hardcover', 'case-wrap.pdf'), ('jacket', 'jacket.pdf'),
                       ('paperback', 'wrap.pdf')):
    r = client.post('/cover/wrap', data=dict(form, wrap_binding=binding))
    check(f'the {binding} wrap downloads as a PDF',
          r.status_code == 200 and r.data[:4] == b'%PDF', r.status_code)
    check(f'and the {binding} file is named for what it is',
          fname in r.headers.get('Content-Disposition', ''),
          r.headers.get('Content-Disposition'))

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
