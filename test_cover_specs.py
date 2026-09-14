"""Cover-specs tests  (run: python test_cover_specs.py).

A writer designing their own wrap takes these numbers into another app and
prints to them, so they have to be the numbers a real wrap is built to. The
geometry is checked against `build_cover_wrap`'s own output, the page against
the geometry, and the blank template's page box against both.
"""

import sys, os, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import engine
import app as A
import fitz

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TPL = A.load_cover_template('ashforge-house')
CF = engine._register_cover_fonts(TPL, engine.register_fonts(A.DEFAULTS))
PID = 'classic-literary'
preset = A.load_preset(PID)
tw, th = preset['trim']['w'], preset['trim']['h']
fd, PDF = tempfile.mkstemp(suffix='.pdf'); os.close(fd)

# ------------------------------------------------------------ one geometry
print('the geometry')
for binding in ('paperback', 'hardcover', 'jacket'):
    spec = A._cover_spec(preset, {'pages': 240, 'binding': binding, 'paper': 'cream'})
    g = spec['geo']
    built = engine.build_cover_wrap(TPL, CF, {'title': 'T'}, dict(spec['dims']), PDF)
    check(f'the {binding} geometry is the size a designed wrap is built to',
          (round(g['wrap_w'], 3), round(g['wrap_h'], 3)) == (built['wrap_w'], built['wrap_h']),
          (g['wrap_w'], g['wrap_h'], built))
    check(f'and the {binding} panels add up across the wrap',
          abs(g['front_x'] + g['panel_w'] + g['flap'] + g['edge'] - g['wrap_w']) < 1e-9, g)
g = A._cover_spec(preset, {'pages': 200})['geo']
check('a 200-page white paperback spine is pages x caliper',
      abs(g['spine_w'] - 200 * A._PAPER['white']['ppi']) < 1e-9, g['spine_w'])
check('pixels round up, so no bleed is lost',
      engine.wrap_pixels({'wrap_w': 12.7004, 'wrap_h': 9.25}) == (3811, 2775))

junk = A._cover_spec(preset, {'pages': 'lots', 'binding': 'scroll', 'paper': 'vellum',
                              'retailer': 'nowhere'})
check('junk in the query falls back to a 200-page white KDP paperback',
      (junk['pages'], junk['binding'], junk['paper'], junk['retailer'])
      == (200, 'paperback', 'white', 'kdp'), junk)
check('page counts are clamped', A._cover_spec(preset, {'pages': '-5'})['pages'] == 1)

guides = A._wrap_guide_lines(A._cover_spec(preset, {'pages': 200})['geo'])
check('a paperback has four vertical guides: two trims and two folds',
      len(guides['x']) == 4, guides['x'])
hg = A._wrap_guide_lines(A._cover_spec(preset, {'pages': 200, 'binding': 'hardcover'})['geo'])
check('a case adds its turn-ins and hinges', len(hg['x']) == 8 and len(hg['y']) == 4, hg)
jg = A._wrap_guide_lines(A._cover_spec(preset, {'pages': 200, 'binding': 'jacket'})['geo'])
check('a jacket adds its flap folds', len(jg['x']) == 8
      and sum('flap' in l for l, _ in jg['x']) == 2, jg['x'])
check('guides run left to right', [x for _, x in hg['x']] == sorted(x for _, x in hg['x']))

# ------------------------------------------------------------ the page
print('the page')
A.app.config['TESTING'] = True
client = A.app.test_client()
index = client.get('/').get_data(as_text=True)
check('every style card links to its cover specs',
      index.count('/cover-specs"') == len(A.list_presets()), index.count('/cover-specs"'))
check('so does the style editor', '/cover-specs' in client.get(f'/editor/{PID}').get_data(as_text=True))

r = client.get(f'/style/{PID}/cover-specs?pages=200&paper=white')
html = r.get_data(as_text=True)
g = A._cover_spec(preset, {'pages': 200})['geo']
px = engine.wrap_pixels(g)
check('it renders', r.status_code == 200 and 'Design your own wrap' in html, r.status_code)
check('with the full wrap size', f'{g["wrap_w"]:.4f} &times; {g["wrap_h"]:.4f}' in html)
check('the pixel size at 300 dpi', f'{px[0]} &times; {px[1]} px' in html, px)
check('the spine width', f'{g["spine_w"]:.4f}"' in html)
check('a diagram and a template link', '<svg' in html and 'cover-specs/template.pdf' in html)
check('and the how-to steps', 'no crop marks' in html and 'Upload it as the <b>cover</b>' in html)
check('the table marks the page count in view', re.search(r'class="cur">\s*<td><a[^>]*>200<', html))

hard = client.get(f'/style/{PID}/cover-specs?pages=200&binding=hardcover&paper=cream').get_data(as_text=True)
check('a hardcover explains the turn-in and hinge', 'Turn-in' in hard and 'hinges' in hard)
check('and carries KDP’s objections', 'white paper only' in hard)
short = client.get(f'/style/{PID}/cover-specs?pages=40').get_data(as_text=True)
check('a short book is told to leave the spine blank', 'Leave the spine free of text' in short)
check('an unknown style is a 404', client.get('/style/no-such-style/cover-specs').status_code == 404)

# ------------------------------------------------------------ the template
print('the blank template')
for binding in ('paperback', 'hardcover', 'jacket'):
    r = client.get(f'/style/{PID}/cover-specs/template.pdf?pages=320&binding={binding}&retailer=ingramspark')
    g = A._cover_spec(preset, {'pages': 320, 'binding': binding, 'retailer': 'ingramspark'})['geo']
    ok = r.status_code == 200 and r.data[:4] == b'%PDF'
    check(f'the {binding} template downloads', ok, r.status_code)
    if not ok:
        continue
    check(f'named for what it is', f'-{binding}-320pp-cover-template.pdf'
          in r.headers.get('Content-Disposition', ''), r.headers.get('Content-Disposition'))
    with fitz.open(stream=r.data, filetype='pdf') as doc:
        rect, text = doc[0].rect, doc[0].get_text()
    check(f'the {binding} template is the wrap, to the thousandth',
          abs(rect.width / 72 - g['wrap_w']) < 0.001 and abs(rect.height / 72 - g['wrap_h']) < 0.001,
          (rect.width / 72, rect.height / 72, g['wrap_w'], g['wrap_h']))
    check(f'and says what it is and to hide it', 'FRONT COVER' in text and 'SPINE' in text
          and 'TEMPLATE ONLY' in text and 'barcode' in text, text[:200])
check('a jacket template labels its flaps', 'FRONT FLAP' in text and 'BACK FLAP' in text)

os.remove(PDF)
print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
