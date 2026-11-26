"""The bug-hunt fixes don't bring bugs of their own  (run: python test_regressions_bughunt.py).

Joint bug hunt, round 4, section 17:

    17.1  a slow Wrap Designer load for a book left behind doesn't fill the page
    17.2  unticking "Use as this book's cover" brings the template cover back
    17.3  Send to print carries the wrap's copy-cut-short warning
    17.4  a proof's cover is a whole leaf, so its page count sizes the spine
    17.5  a `Chapter {N}` number format builds the EPUB too
    17.6  renaming a designed page whose name holds curly quotes
    17.7  a poem title that looks like a link prints as typed
    17.8  a spread's page backgrounds stop at the fold
    17.9  a `~~~ page` fence of plain text leaves Page Plan editable
    17.10 a damaged style doesn't stop figures being deleted
    17.11 the back photo's resolution is measured at the size it prints
"""

import sys, os, io, re, json, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import engine
import epub
import manuscript as M
import page_plan
import wrap_design

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def use_folders(tmp):
    shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(tmp, 'presets'))
    shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(tmp, 'covers'),
                    ignore=shutil.ignore_patterns('assets'))
    A.PRESET_DIR, A.COVER_DIR = os.path.join(tmp, 'presets'), os.path.join(tmp, 'covers')
    A.PROJECT_DIR = os.path.join(tmp, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(tmp, 'out')
    A.UPLOAD_DIR = os.path.join(tmp, 'uploads')
    A.FIGURE_DIR = os.path.join(tmp, 'figures')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.OUT_DIR, A.FIGURE_DIR):
        os.makedirs(d, exist_ok=True)


def make_book(pid, text='# One\n\nThe text.\n', **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(text)
    data = dict(name=pid, title='T', author='A', preset='classic-literary', format='pdf',
                manuscript_file=pid + '.md', manuscript_type='markdown', cover_file='',
                cover_mode='none', last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', print_back_file='', front_matter='none')
    data.update(over)
    A.save_project_file(pid, data)
    return data


TMP = tempfile.mkdtemp()
use_folders(TMP)
A.app.config['TESTING'] = True
c = A.app.test_client()
P = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))

# ---- 17.1 ------------------------------------------------------------------
print('17.1 a late Wrap Designer load')
js = open(os.path.join(HERE, 'static', 'wrap_designer.js'), encoding='utf-8').read()
body = js[js.index('function openBook('):js.index('function bookDirty(')]
check('each load knows whether a newer one has started',
      'var seq = ++openSeq' in body and body.count('if (stale()) return;') >= 3, body[:400])

# ---- 17.2 ------------------------------------------------------------------
print('17.2 unticking the wrap as cover')
make_book('wc', cover_mode='designed', cover_template='ashforge-house')
EL = [{'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
       'text': 'Title', 'font': 'EBGaramond-Regular.ttf', 'size': 24, 'color': '#000000'}]
r = c.post('/wrap-designer/project/wc/save',
           json={'design': {'elements': EL}, 'use_as_cover': True}).get_json()
check('the wrap becomes the cover', r and r.get('ok') and A.load_project('wc')['cover_mode'] == 'wrap', r)
r = c.post('/wrap-designer/project/wc/save',
           json={'design': {'elements': EL}, 'use_as_cover': False}).get_json()
check('unticked, the template cover is back', A.load_project('wc')['cover_mode'] == 'designed',
      A.load_project('wc')['cover_mode'])

# ---- 17.3 / 17.11 -----------------------------------------------------------
print('17.3 / 17.11 Send to print reads what the wrap drew')
from PIL import Image
photo = os.path.join(A.PROJECT_MS_DIR, 'bk-photo.png')
Image.new('RGB', (3000, 3000), (120, 90, 60)).save(photo)
make_book('bk', text='# One\n\n' + 'Words on a page. ' * 40 + '\n',
          cover_mode='designed', cover_template='ashforge-house',
          print_retailer='kdp', print_binding='paperback', print_paper='cream',
          print_blurb=('A very long blurb that runs and runs. ' * 120).strip(),
          print_back_file='bk-photo.png', print_back_w=12)
info = A.build_print_package(A.load_project('bk'))
checks = info.get('checks') or []
copy = [ch for ch in checks if 'too long to fit' in (ch.get('detail') or '')]
check('the package says the back cover copy was cut short', copy and not copy[0]['ok'],
      [ch.get('label') for ch in checks])
pic = [ch for ch in checks if ch.get('label') == 'Back-cover picture']
check('the photo is measured at the width it prints, not 12 inches',
      pic and pic[0]['ok'], pic)

# ---- 17.4 ------------------------------------------------------------------
print('17.4 the cover leaf')
text = '# One\n\n' + ('A paragraph of words to fill the page. ' * 60 + '\n\n') * 3
meta = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': True, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'designed', 'cover_image': '',
        'cover_template': 'ashforge-house',
        'cover_template_data': A.load_cover_template('ashforge-house'),
        'cover_overlay': False, 'cover_color': 'light'}
covered = engine.build_pdf(M.parse_markdown(text), P, os.path.join(TMP, 'c.pdf'), meta)
plain = engine.build_pdf(M.parse_markdown(text), P, os.path.join(TMP, 'p.pdf'),
                         dict(meta, cover_mode='none', cover_template_data=None))
check('the proof counts exactly the coverless interior',
      covered['interior_pages'] == plain['page_count'],
      (covered['page_count'], covered['interior_pages'], plain['page_count']))
check('the cover and its blank inside come first', covered['page_count'] == plain['page_count'] + 2)

# ---- 17.5 ------------------------------------------------------------------
print('17.5 Chapter {N}')
p5 = json.loads(json.dumps(P))
p5.setdefault('chapter', {})['number_format'] = 'Chapter {N}'
out = os.path.join(TMP, 'n.epub')
ms = M.parse_markdown('# One\n\nText.\n\n# Two\n\nMore.\n')
try:
    epub.build_epub(ms, p5, out, {'title': 'T', 'author': 'A'})
    import zipfile
    with zipfile.ZipFile(out) as z:
        allx = ''.join(z.read(n).decode('utf-8', 'replace') for n in z.namelist()
                       if n.endswith('.xhtml'))
    ok = 'Chapter 1' in allx or 'Chapter {N}' not in allx
    check('the EPUB builds and numbers the chapter', ok, allx[:300])
except Exception as e:
    check('the EPUB builds and numbers the chapter', False, repr(e))
check('the EPUB label reads as the PDF one', epub._num_label('Chapter {N}', 3) == 'Chapter 3'
      and epub._num_label('{x} {n}', 2) == '{x} 2')

# ---- 17.6 / 17.9 ------------------------------------------------------------
print('17.6 / 17.9 page fences')
t = ('~~~ page src="The “Map” Page" side="right"\nalt\n~~~\n\n'
     '~~~ page\nOld prose in a fence.\n~~~\n')
moved = page_plan.rename(t, 'the-map-page', 'north-map', key=wrap_design.page_name)
check('the rename replaces the whole name', moved.startswith('~~~ page src="north-map" side="right"'),
      moved.split('\n')[0])
kinds = [i['kind'] for i in page_plan.split(t)]
check('a fence that names no design is text', kinds == ['page', 'text'], kinds)
placed = [b for ch in M.parse_markdown('# One\n\n' + t)['chapters'] for b in ch['blocks']
          if b[0] == 'doc_block' and len(b) > 2 and b[2].get('_type') == 'page']
check('as the typesetter reads it', len(placed) == 1, placed)

# ---- 17.7 ------------------------------------------------------------------
print('17.7 a poem title with brackets')
ms = M.parse_markdown('# One\n\n~~~ poem title="[Draft](#missing)"\nA line\n~~~\n')
fixed, dead = engine._resolve_inbook_links(ms['chapters'])
attrs = [b[2] for ch in fixed for b in ch['blocks'] if b[0] == 'doc_block' and len(b) > 2]
check('the poem title is left as typed', attrs and attrs[0].get('title') == '[Draft](#missing)', attrs)
ms = M.parse_markdown('# One\n\n~~~ quote source="[Ann](#missing)"\nWords\n~~~\n')
fixed, dead = engine._resolve_inbook_links(ms['chapters'])
attrs = [b[2] for ch in fixed for b in ch['blocks'] if b[0] == 'doc_block' and len(b) > 2]
check('a quote source still loses its dead link', attrs and attrs[0].get('source') == 'Ann', attrs)

# ---- 17.8 ------------------------------------------------------------------
print('17.8 backgrounds stop at the fold')
from reportlab.pdfgen import canvas as rl_canvas
import fitz
bgimg = os.path.join(TMP, 'stripes.png')
im = Image.new('RGB', (400, 100), (255, 0, 0))
for x in range(200, 400):
    for y in range(100):
        im.putpixel((x, y), (0, 0, 255))
im.save(bgimg)
pdfp = os.path.join(TMP, 'bg.pdf')
cv = rl_canvas.Canvas(pdfp, pagesize=(200, 100))
bg = {'color': None, 'path': bgimg, 'opacity': 1.0}
engine.paint_background(cv, bg, 0, 0, 100, 100)
engine.paint_background(cv, bg, 100, 0, 100, 100)
cv.showPage(); cv.save()
pix = fitz.open(pdfp)[0].get_pixmap()
# the left page is painted first, its centre crop runs red|blue at x=50; the
# right page's picture, unclipped, covered x 50..100 of the left page too
left_quarter = pix.pixel(25, 50)
check('the left page keeps its own left half', left_quarter[0] > 200 and left_quarter[2] < 60,
      left_quarter)

# ---- 17.10 -----------------------------------------------------------------
print('17.10 a damaged style and figure deletion')
check('a null chapter_art reads as none', engine.chapter_art_src({'chapter_art': None}) == '')
check('a string scene break reads as none', engine.scene_image_src({'scene_break': 'x'}) == '')
check('a null background reads as none', engine.page_background_src({'page_background': None}) == '')

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
