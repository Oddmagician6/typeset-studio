"""Ornaments and front/back matter, in print and in the ebook  (run: python test_matter_bughunt.py).

Joint bug hunt, round 4, section 19:

    19.1  chapter art over the number leaves the heading on the opener
    19.2  a closing full-page figure doesn't leave a numbered empty page
    19.3  a scene ornament taller than a landscape page is scaled to fit
    19.4  a furniture id named as the scene break falls back, not crashes
    19.5  a footer band stays on the page with folios off
    19.6  a text scene break wider than the measure is set smaller
    19.7  the page-by-page ebook names the front pages it leaves out (in test_fixed_layout)
    19.8  the ebook carries the style's own scene-break picture
    19.9  Also By titles one per line, every Praise source styled, in the ebook
    19.10 the ebook's chapter art keeps its alignment and space
    19.11 smart punctuation leaves link addresses alone (also 20.10)
    19.12 the ebook's matter honours escapes and smart punctuation
    19.13 an Also By running head keeps <…> in the author's name
"""

import sys, os, re, json, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import engine
import epub
import manuscript as M
import fitz
from PIL import Image

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp()
engine.FIGURE_DIR = epub.FIGURE_DIR = TMP
BASE = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
META = {'title': 'T', 'author': 'A', 'front_matter': 'none', 'right_hand_starts': False}


def preset(**over):
    p = json.loads(json.dumps(BASE))
    for k, v in over.items():
        p[k] = dict(p.get(k) or {}, **v) if isinstance(v, dict) else v
    return p


def pdf(ms_text, p, meta=None, name='b.pdf'):
    out = os.path.join(TMP, name)
    res = engine.build_pdf(M.parse_markdown(ms_text), p, out, dict(META, **(meta or {})))
    return out, res


def epub_files(ms_text, p, meta=None):
    out = os.path.join(TMP, 'b.epub')
    epub.build_epub(M.parse_markdown(ms_text), p, out, dict(META, **(meta or {})))
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n) for n in z.namelist()}


Image.new('RGB', (300, 600), (90, 40, 20)).save(os.path.join(TMP, 'tall.png'))
Image.new('RGB', (400, 60), (20, 20, 20)).save(os.path.join(TMP, 'rule.png'))

# ---- 19.1 ------------------------------------------------------------------
print('19.1 chapter art and a deep sink')
p = preset(chapter={'sink': 4.75}, margins={'top': 0.75, 'bottom': 0.75},
           chapter_art={'image': 'tall.png', 'position': 'above', 'width': 1.0,
                        'max_height': 2.5, 'gap': 0.5})
out, res = pdf('# The Long Night\n\nText of the chapter.\n', p, {'include_toc': False})
doc = fitz.open(out)
pg = [i for i, page in enumerate(doc) if 'Long Night' in page.get_text()]
check('the title is on the page with the art', pg and doc[pg[0]].get_images(), pg)
doc.close()

# ---- 19.2 ------------------------------------------------------------------
print('19.2 a full-page figure before the Afterword')
text = '# One\n\nSome text.\n\n~~~ figure src="tall.png" full="page"\n~~~\n'
out, res = pdf(text, BASE, {'afterword': 'After it all.'}, 'f.pdf')
doc = fitz.open(out)
pages = [(page.get_text(), bool(page.get_images())) for page in doc]
doc.close()
aw = [n for n, (t, _) in enumerate(pages) if 'Afterword' in t]
check('the Afterword follows the figure straight on',
      aw and aw[0] > 0 and pages[aw[0] - 1][1], [(t[:20], im) for t, im in pages])

# ---- 19.3 / 19.4 / 19.6 ----------------------------------------------------
print('19.3 / 19.4 / 19.6 scene breaks')
land = preset(trim={'w': 8.25, 'h': 6.0},
              margins={'top': 0.75, 'bottom': 0.75, 'inside': 0.75, 'outside': 0.75},
              scene_break={'type': 'ornament', 'ornament': 'star', 'ornament_width': 1.0})
try:
    pdf('# One\n\nBefore.\n\n* * *\n\nAfter.\n', land, name='s.pdf')
    check('a star across a landscape page builds', True)
except Exception as e:
    check('a star across a landscape page builds', False, repr(e))
furn = preset(scene_break={'type': 'ornament', 'ornament': 'corner-wedge', 'ornament_width': 0})
for oid in ('corner-wedge', 'band-solid'):
    furn['scene_break']['ornament'] = oid
    try:
        pdf('# One\n\nBefore.\n\n* * *\n\nAfter.\n', furn, name='w.pdf')
        files = epub_files('# One\n\nBefore.\n\n* * *\n\nAfter.\n', furn)
        check(f'{oid} as a scene break uses the glyph in both',
              b'scene-orn' not in b''.join(v for k, v in files.items() if k.endswith('.xhtml')))
    except Exception as e:
        check(f'{oid} as a scene break uses the glyph in both', False, repr(e))
wide = preset(scene_break={'type': 'glyph', 'glyph': ' '.join(['*'] * 16), 'size': 72.0})
out, _ = pdf('# One\n\nBefore.\n\n* * *\n\nAfter.\n', wide, name='g.pdf')
doc = fitz.open(out)
xs = [s['bbox'] for page in doc for b in page.get_text('dict')['blocks']
      for l in b.get('lines', []) for s in l['spans'] if '*' in s['text']]
W = doc[0].rect.width
doc.close()
check('the glyph line stays on the page', xs and all(0 <= b[0] and b[2] <= W for b in xs), (xs, W))

# ---- 19.5 ------------------------------------------------------------------
print('19.5 a footer band with folios off')
band = preset(furniture={'footer': 'band-solid'}, folio={'show': False, 'gap': 2.0})
out, _ = pdf('# One\n\n' + 'Words fill a page. ' * 300 + '\n', band, name='band.pdf')
doc = fitz.open(out)
H = doc[0].rect.height
ys = [d['rect'] for page in list(doc)[1:] for d in page.get_drawings() if d.get('rect')]
doc.close()
check('the band is drawn inside the trim', ys and all(r.y0 >= -0.5 and r.y1 <= H + 0.5 for r in ys),
      [tuple(round(v) for v in r) for r in ys[:4]])

# ---- 19.8 / 19.10 -----------------------------------------------------------
print('19.8 / 19.10 pictures in the ebook')
img = preset(scene_break={'type': 'image', 'image': 'rule.png', 'size': 14.0},
             chapter_art={'image': 'tall.png', 'align': 'left', 'gap': 0.8, 'position': 'above'})
files = epub_files('# One\n\nBefore.\n\n* * *\n\nAfter.\n', img)
ch = b''.join(v for k, v in files.items() if 'chapter' in k).decode('utf-8')
check('the scene break is the style\'s picture', re.search(r'class="scene-orn" src="images/fig\d+\.png"', ch), ch[:600])
check('and the picture is in the book', sum(1 for k in files if k.startswith('OEBPS/images/fig')) == 2,
      [k for k in files if 'images' in k])
check('chapter art keeps its alignment', 'text-align:left' in ch, ch[:500])
check('and its space', 'margin-bottom:4.80em' in ch, ch[:500])

# ---- 19.9 / 19.12 -----------------------------------------------------------
print('19.9 / 19.12 matter in the ebook')
files = epub_files('# One\n\nText.\n', BASE, {
    'smartquotes': True,
    'also_by': 'The First Book\nThe Second Book',
    'blurbs': 'Wonderful.\n\n-- A Reader\n\nMoving.\n\n-- Another',
    'dedication': 'It\'s for everyone who said "\\*keep\\* going"...'})
aby = next(v for k, v in files.items() if k.endswith('alsoby.xhtml')).decode('utf-8')
check('Also By sets a title per line', '<p>The First Book</p>' in aby and '<p>The Second Book</p>' in aby, aby)
blb = next(v for k, v in files.items() if k.endswith('blurbs.xhtml')).decode('utf-8')
check('every Praise source is styled', blb.count('class="attr"') == 2, blb)
ded = next((v for k, v in files.items() if 'dedication' in k), b'').decode('utf-8')
check('the dedication honours escapes', '*keep*' in ded and '\\' not in ded and '<em>' not in ded, ded)
check('and smart punctuation', '’s' in ded and '“' in ded and '…' in ded, ded)

# ---- 19.11 -----------------------------------------------------------------
print('19.11 links survive smart punctuation')
out = M._inline('[Buy the book](https://example.test/tide--ash?a=1&b=2...)', True)
check('the address is as typed', 'href="https://example.test/tide--ash?a=1&amp;b=2..."' in out, out)
check('a chapter link still works', 'href="#ch-2"' in M._inline('see [this](#ch-2) -- now', True))

# ---- 19.13 -----------------------------------------------------------------
print('19.13 the Also By running head')
rh = preset(running_head={'show': True, 'content': 'section', 'caps': False})
titles = '\n'.join(f'Book number {i}' for i in range(1, 90))
out, _ = pdf('# One\n\nText.\n', rh, {'author': 'R. Vale <Pen Name>', 'also_by': titles}, 'rh.pdf')
doc = fitz.open(out)
last = doc[doc.page_count - 1].get_text()
doc.close()
check('the continuation head keeps the whole name', 'R. Vale <Pen Name>' in last, last[:200])

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
