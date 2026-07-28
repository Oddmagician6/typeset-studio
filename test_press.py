"""Press-ready interior tests  (run: python test_press.py).

A press build makes three claims about the file it writes — that the black is
one ink, that the trim box is declared, and that nothing screen-only is left in
it — and one claim about what it is *not*: a certified PDF/X-1a, which needs an
embedded ICC output intent we don't ship. Each of those is checked here by
reading the built PDF back, because a claim about a print file that isn't
measured off the file is just a hope.

The colour rule this rests on: ReportLab's CMYK enforcement converts any grey
to K-only and raises on anything chromatic. Our interiors are black and grey
throughout, so the conversion is exact — and the fallback path is what happens
when a book isn't.
"""

import sys, os, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import engine, manuscript, matter
import app as A
import fitz

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


MS_TEXT = """\
# The Salt Road

The opening paragraph, with a [link to somewhere](https://example.com) in it and
enough words to make a real line of body text.

## A subhead

~~~ table
Year | Cargo
1841 | Salt
~~~

Another paragraph, so the page has furniture on it.[^n]

[^n]: A note, which the style prints at the back.
"""

META = {'title': 'Press', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
        'front_matter': 'full', 'right_hand_starts': True, 'include_toc': True,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light', 'press': False,
        **{k: '' for k in matter.KEYS}}

ms = manuscript.parse_markdown(MS_TEXT, smartquotes=True)
preset = A.load_preset('classic-literary')

RGB_OP = re.compile(r'(?<![A-Za-z/])(rg|RG)(?![A-Za-z])')
CMYK_OP = re.compile(r'(?<![A-Za-z/])(k|K)(?![A-Za-z])')


def read(path):
    ops, links = [], 0
    with fitz.open(path) as doc:
        pages = doc.page_count
        for page in doc:
            s = page.read_contents().decode('latin-1')
            ops.append(s)
            links += len(page.get_links())
    body = open(path, 'rb').read()
    joined = '\n'.join(ops)
    return {'rgb': len(RGB_OP.findall(joined)), 'cmyk': len(CMYK_OP.findall(joined)),
            'links': links, 'trimbox': b'/TrimBox' in body, 'pages': pages,
            'text': ' '.join(ops)}


fd, PDF = tempfile.mkstemp(suffix='.pdf'); os.close(fd)

# ---------------------------------------------------------------- the normal build
print('the ordinary build')
plain = engine.build_pdf(ms, preset, PDF, dict(META))
before = read(PDF)
check('is RGB, as it always was', before['rgb'] > 0, before['rgb'])
check('keeps its links', before['links'] >= 1, before['links'])
check('declares no trim box', not before['trimbox'])
check('says it is not a press build', plain.get('press') is False, plain)

# ---------------------------------------------------------------- the press build
print('the press build')
res = engine.build_pdf(ms, preset, PDF, dict(META), press=True)
after = read(PDF)
check('the build reports itself press-ready', res.get('press') is True, res)
check('no RGB is left in the file', after['rgb'] == 0, after['rgb'])
check('the black is CMYK instead', after['cmyk'] > 0, after['cmyk'])
check('the trim box is declared', after['trimbox'])
check('the links are gone', after['links'] == 0, after['links'])
check('the pagination is untouched', after['pages'] == before['pages'],
      (after['pages'], before['pages']))
check('and so is the page count it reports',
      res['page_count'] == plain['page_count'], (res['page_count'], plain['page_count']))
check('the words survive the link being dropped', 'link to somewhere' in after['text'],
      after['text'][:80])
check('the fonts are still embedded', res['fonts_embedded'])

# ---------------------------------------------------------------- the cover rule
print('the cover')
cov = dict(META, cover_mode='designed',
           cover_template_data=A.load_cover_template('ashforge-house'))
normal_cover = engine.build_pdf(ms, preset, PDF, dict(cov))
with fitz.open(PDF) as doc:
    cover_pages = doc.page_count
res_c = engine.build_pdf(ms, preset, PDF, dict(cov), press=True)
with fitz.open(PDF) as doc:
    press_pages = doc.page_count
check('an ordinary build keeps the designed cover',
      cover_pages == normal_cover['page_count'], cover_pages)
# the cover also costs a blank verso, so dropping it lands on the no-cover count
check('a press build drops it — a printer wants the cover as its own file',
      press_pages == plain['page_count'] < cover_pages,
      (press_pages, plain['page_count'], cover_pages))
check('and still builds press-ready, not by falling back',
      res_c.get('press') is True and 'press_error' not in res_c, res_c)
check('the interior it wrote is still ink-only', read(PDF)['rgb'] == 0)

# ---------------------------------------------------------------- the fallback
print('the fallback')
# a chromatic colour the CMYK canvas cannot express, forced in through the style
import reportlab.lib.colors as _c
orig = engine._styles


def coloured_styles(p, f):
    st = orig(p, f)
    st['body'].textColor = _c.Color(0.8, 0.1, 0.1)
    return st


engine._styles = coloured_styles
try:
    fb = engine.build_pdf(ms, preset, PDF, dict(META), press=True)
finally:
    engine._styles = orig
check('a book with real colour still builds', fb['page_count'] > 0, fb)
check('but says so rather than pretending', fb.get('press') is False and fb.get('press_error'),
      fb.get('press_error'))
check('and the file it wrote is the ordinary RGB one', read(PDF)['rgb'] > 0)

# ---------------------------------------------------------------- the report
print('the press check')
engine.build_pdf(ms, preset, PDF, dict(META), press=True)
rows = engine.press_check(PDF)
by = {r['label']: r for r in rows}
check('every row is reported', set(by) == {'Colour', 'Illustrations', 'Transparency',
                                           'Annotations', 'Trim box', 'Output intent'}, set(by))
check('colour passes on a press build', by['Colour']['ok'], by['Colour'])
check('annotations pass', by['Annotations']['ok'], by['Annotations'])
check('the trim box passes', by['Trim box']['ok'], by['Trim box'])
check('transparency passes', by['Transparency']['ok'], by['Transparency'])
check('the output intent is honestly reported as missing',
      by['Output intent']['ok'] is False
      and 'PDF/X-1a' in by['Output intent']['detail'], by['Output intent'])

engine.build_pdf(ms, preset, PDF, dict(META))
plain_rows = {r['label']: r for r in engine.press_check(PDF)}
check('an ordinary build fails the colour row', not plain_rows['Colour']['ok'],
      plain_rows['Colour'])
check('and the annotation row', not plain_rows['Annotations']['ok'], plain_rows['Annotations'])

# an illustrated book: RGB images are reported, not hidden
from PIL import Image
figp = os.path.join(A.FIGURE_DIR, '_press_fig.png')
Image.new('RGB', (400, 300), (170, 110, 80)).save(figp)
try:
    ms_fig = manuscript.parse_markdown(
        '# One\n\nText.\n\n~~~ figure src="_press_fig.png"\nA plate.\n~~~\n', smartquotes=True)
    engine.build_pdf(ms_fig, preset, PDF, dict(META, include_toc=False), press=True)
    figrows = {r['label']: r for r in engine.press_check(PDF)}
    check('an RGB illustration is reported', not figrows['Illustrations']['ok'],
          figrows['Illustrations'])
    check('while the type around it is still single-ink', figrows['Colour']['ok'],
          figrows['Colour'])
finally:
    os.remove(figp)
os.remove(PDF)

# ---------------------------------------------------------------- the app
print('the app')
A.app.config['TESTING'] = True
client = A.app.test_client()
page = client.get('/generate').get_data(as_text=True)
check('the compose form offers it', 'name="press"' in page)

r = client.post('/generate', data={'preset': 'classic-literary', 'use_sample': '1',
                                   'title': 'Press Test', 'author': 'E', 'format': 'pdf',
                                   'front_matter': 'full', 'press': 'on'},
                follow_redirects=True)
html = r.get_data(as_text=True)
check('a press build composes', r.status_code == 200 and 'Off the press' in html,
      r.status_code)
check('and the result page shows the press card', 'Press check' in html)
check('with the output-intent caveat on it', 'PDF/X-1a' in html)

r2 = client.post('/generate', data={'preset': 'classic-literary', 'use_sample': '1',
                                    'title': 'Plain Test', 'author': 'E', 'format': 'pdf',
                                    'front_matter': 'full'}, follow_redirects=True)
check('an ordinary build shows no press card',
      'Press check' not in r2.get_data(as_text=True))

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
