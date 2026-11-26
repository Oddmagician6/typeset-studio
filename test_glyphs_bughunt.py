"""Fonts, glyph coverage and unusual text  (run: python test_glyphs_bughunt.py).

Joint bug hunt, round 4, section 20 (20.2, 20.9 and 20.12 are features, left open):

    20.1  letters the body face lacks are a failed preflight row
    20.3  Send to print names letters a designed wrap's fonts lack (copy: test_regressions)
    20.4  the kicker and epigraph are checked in the italic face they are set in
    20.5  page 1's overlay author is in the face the wrap uses
    20.6  a byte-order mark doesn't split a line in the designer only
    20.7  a soft hyphen doesn't print mid-word
    20.8  cover lines don't break at no-break spaces
    20.10 smart punctuation leaves a chapter's link addresses alone
    20.11 table widths measure bold and italic in their own faces
    20.13 elisions and quotes after emphasis or an en dash curl the right way
    20.14 small caps keep ß apart from ss
    20.15 a layer label never ends on half an emoji
"""

import sys, os, re, json, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine
import manuscript as M
import wrap_design
import fitz
from reportlab.pdfbase.pdfmetrics import stringWidth

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp()
P = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
F = engine.register_fonts(P)
META = {'title': 'T', 'author': 'A', 'front_matter': 'none'}

# ---- 20.1 ------------------------------------------------------------------
print('20.1 letters the body face lacks')
r = engine.build_pdf(M.parse_markdown('# One\n\nA star 星 and a rocket \U0001F680.\n'), P,
                     os.path.join(TMP, 'a.pdf'), META)
check('the build names them', '星' in r['text_glyphs_missing']
      and '\U0001F680' in r['text_glyphs_missing'], ascii(r['text_glyphs_missing']))
rows = A._preflight(r, P, r['page_count'])
check('and preflight fails on them', any(not x['ok'] and x['label'] == 'Letters the font lacks'
                                         for x in rows), [x['label'] for x in rows])
r = engine.build_pdf(M.parse_markdown('# One\n\nPlain “quoted” café—text…\n'), P,
                     os.path.join(TMP, 'b.pdf'), META)
check('ordinary text passes', r['text_glyphs_missing'] == '', ascii(r['text_glyphs_missing']))

# ---- 20.3 / 20.4 ------------------------------------------------------------
print('20.3 / 20.4 cover lettering')
design = {'elements': [{'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
                        'text': 'Night 星', 'font': 'EBGaramond-Regular.ttf', 'size': 24,
                        'color': '#000000'}]}
check("a design's missing letters are found", wrap_design.glyphs_missing(design) == '星',
      ascii(wrap_design.glyphs_missing(design)))
cf = {'display': 'Helvetica', 'serif': 'Helvetica', 'italic': F['italic']}
got = engine.cover_glyphs_missing({'cover_kicker': 'A tale 星'}, cf)
check('the kicker is checked in the italic face', got == '星', ascii(got))

# ---- 20.5 ------------------------------------------------------------------
print('20.5 the overlay author face')
from PIL import Image
art = os.path.join(TMP, 'art.jpg')
Image.new('RGB', (600, 900), (30, 40, 60)).save(art)
p5 = json.loads(json.dumps(P))
out = os.path.join(TMP, 'cov.pdf')
engine.build_pdf(M.parse_markdown('# One\n\nText.\n'), p5, out,
                 dict(META, author='Ana Writer', cover_mode='image', cover_image=art,
                      cover_overlay=True))
doc = fitz.open(out)
fonts = {s['font'] for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines', [])
         for s in l['spans'] if 'Ana Writer' in s['text']}
doc.close()
check('page 1 sets the author in the regular face, as the wrap does',
      fonts and all('Regular' in f for f in fonts), fonts)

# ---- 20.6 / 20.7 / 20.8 -----------------------------------------------------
print('20.6 / 20.7 / 20.8 cover text')
lines = engine._wrap_tracked('A﻿A', F['regular'], 20, 18)
check('a byte-order mark is no break and no width', lines == ['AA'], lines)
lines = engine._wrap_tracked('co­operate', F['regular'], 12, 400)
check('a soft hyphen is not printed', lines == ['cooperate'], lines)
lines = engine._wrap_tracked('it weighs 10 kg', F['regular'], 12,
                             stringWidth('it weighs 10', F['regular'], 12) + 2)
check('a no-break space holds its words together', lines[-1] == '10 kg', lines)
el = {'type': 'text', 'text': 'x­y', 'font': 'EBGaramond-Regular.ttf', 'size': 12}
check('the designer sets the same text', wrap_design.break_lines(el) == ['xy'],
      wrap_design.break_lines(el))
js = open(os.path.join(HERE, 'static', 'wrap_text.js'), encoding='utf-8').read()
check('the editor drops the same characters and keeps the same spaces',
      '\\u00ad\\u200b\\u2060\\ufeff' in js and '(?![\\u00a0\\u2007\\u202f])' in js)

# ---- 20.10 -----------------------------------------------------------------
print('20.10 links in chapter text')
ms = M.parse_markdown('# One\n\nSee [the map](https://example.test/old--mill?name=St.John...) now.\n')
blob = json.dumps(ms['chapters'], ensure_ascii=False)
check('the address is kept as typed', 'old--mill?name=St.John...' in blob, blob[:300])

# ---- 20.11 -----------------------------------------------------------------
print('20.11 table widths and bold')
runs = engine._markup_runs('<b>MMMMMMMM</b>', F)
check('a bold run is measured in the bold face', runs and runs[0][1] == F['bold'], runs)
cells = [[engine._markup_runs('<b>MMMMMMMM</b>', F), engine._markup_runs('ABCDEFGH', F)]]
need = stringWidth('MMMMMMMM', F['bold'], 12)
widths = engine._table_widths(cells, {}, need + stringWidth('ABCDEFGH', F['regular'], 12) + 30,
                              12, 12)
check('the bold column gets room for its bold word', widths[0] >= need + 12, (widths, need))

# ---- 20.13 -----------------------------------------------------------------
print('20.13 smart quotes')
for raw, want in (("'Tis dawn.", '’Tis dawn.'),
                  ('She said *"wait"*.', 'She said *“wait”*.'),
                  ('He stopped –"Wait."', 'He stopped –“Wait.”'),
                  ("in the '90s", 'in the ’90s'),
                  ("It's 'quoted' text", 'It’s ‘quoted’ text')):
    got = M._smarten(raw)
    check(f'{raw!r}', got == want, ascii(got))

# ---- 20.14 -----------------------------------------------------------------
print('20.14 small caps and sharp s')
a, b = engine._upper_text('Maße', F['regular']), engine._upper_text('Masse', F['regular'])
check('Maße and Masse stay two words', a != b, (a, b))
check('an entity is put back', engine._upper_text('a &amp; b', F['regular']) == 'A &amp; B')

# ---- 20.15 -----------------------------------------------------------------
print('20.15 layer labels')
wd = open(os.path.join(HERE, 'static', 'wrap_designer.js'), encoding='utf-8').read()
check('labels are cut by character', "WD.chars(String(el.text)).slice(0, 28).join('')" in wd)

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
