"""1.16.0's changes don't bring bugs of their own  (run: python test_regressions7_bughunt.py).

Joint bug hunt, round 7, section 29 (regressions shipped in 1.16.0):

    29.1  a save that lost the manuscript lock while paused doesn't write
    29.2  replacing the manuscript keeps an editor save made meanwhile
    29.3  the installed app's start-up font set-aside repoints the user's styles
    29.4  a paragraph's overlong first word is split at the measure, not run past the trim
    29.5  a back photo raised above the barcode doesn't paint over the blurb
    29.6  the page list runs to the end of a long last paragraph
    29.7  figures, and tables in two columns, are listed on their own page
    29.8  an ebook doesn't take another book's page map of the same shape
    29.9  the print source is a dc:source for the pagination, not a made-up property
    29.10 no landmark leads to the nav document, which isn't in the reading order
    29.11 a language tag is checked as BCP 47; Book settings refuses a bad one
    29.12 italics round a bold span read as the engine sets them (doc model;
          the rich editor in test_rich_editor.js `bh29-*`)
    29.13 the name-variant check finds a late variant past its key budget
"""

import sys, os, io, json, re, shutil, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh29-')

# ---- 29.3 -------------------------------------------------------------------
print('29.3 the installed start repoints a font it sets aside')
appdata = os.path.join(TMP, 'appdata')
data = os.path.join(appdata, 'Typeset Studio')
for sub in ('fonts', 'presets', 'covers', 'projects'):
    os.makedirs(os.path.join(data, sub))
open(os.path.join(data, 'fonts', 'Alegreya-Regular.ttf'), 'wb').write(b'the user font')
json.dump({'name': 'Mine', 'font_files': {'regular': 'Alegreya-Regular.ttf'}},
          open(os.path.join(data, 'presets', 'mine-29.json'), 'w'))
# the app as installed: frozen, its bundle the repo, its data under APPDATA -
# seeding runs while app.py is still being imported
driver = (
    'import sys, os\n'
    'sys.frozen = True\n'
    f'sys._MEIPASS = {HERE!r}\n'
    f'sys.path.insert(0, {HERE!r})\n'
    'import logging; logging.disable(logging.CRITICAL)\n'
    'import app\n')
env = dict(os.environ, APPDATA=appdata, PYTHONIOENCODING='utf-8')
run = subprocess.run([sys.executable, '-c', driver], env=env, capture_output=True,
                     text=True, timeout=300)
check('the frozen import starts', run.returncode == 0, run.stderr[-800:])
check('the user font was set aside',
      os.path.isfile(os.path.join(data, 'fonts', 'Alegreya-Regular-own.ttf')))
mine = json.load(open(os.path.join(data, 'presets', 'mine-29.json'), encoding='utf-8'))
check('their style names the set-aside file',
      mine['font_files']['regular'] == 'Alegreya-Regular-own.ttf', mine)


# ---- the app, on scratch folders ---------------------------------------------
import app as A

shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(TMP, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(TMP, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(TMP, 'presets'), os.path.join(TMP, 'covers')
A.PROJECT_DIR = os.path.join(TMP, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(TMP, 'out')
A.UPLOAD_DIR = os.path.join(TMP, 'uploads')
A.SETTINGS_PATH = os.path.join(TMP, 'settings.json')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.OUT_DIR):
    os.makedirs(d, exist_ok=True)
A.app.config['TESTING'] = True
c = A.app.test_client()


def make_book(pid, text='# One\n\nThe text.\n', ext='.md', **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + ext), 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    data = dict(name=pid, title='T', author='A', preset='classic-literary', format='pdf',
                manuscript_file=pid + ext,
                manuscript_type='markdown' if ext == '.md' else 'file', cover_file='',
                cover_mode='none', last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', front_matter='none')
    data.update(over)
    A.save_project_file(pid, data)


def ms_of(pid):
    proj = A.load_project(pid)
    with open(os.path.join(A.PROJECT_MS_DIR, proj['manuscript_file']), encoding='utf-8') as f:
        return f.read()


def history_texts(pid):
    return [A.read_snapshot(pid, s['stamp']) for s in A.list_snapshots(pid)]


# ---- 29.1 -------------------------------------------------------------------
print('29.1 a save that lost its lock does not write')
make_book('lk', '# One\n\nThe newer text.\n')

real_lock = A._manuscript_lock
import contextlib
@contextlib.contextmanager
def lost_lock(pid):
    with real_lock(pid):
        yield lambda: False         # another copy took it over meanwhile
A._manuscript_lock = lost_lock
try:
    r = c.post('/project/lk/write/save', data={'text': '# One\n\nThe older text.\n'})
finally:
    A._manuscript_lock = real_lock
check('the save is refused', r.status_code == 409, (r.status_code, r.get_data(as_text=True)[:200]))
check('the newer text stays', 'newer' in ms_of('lk'), ms_of('lk'))
check('the refused text is kept in History',
      any('older' in (t or '') for t in history_texts('lk')))
r = c.post('/project/lk/write/save', data={'text': '# One\n\nThe older text.\n'})
check('a save holding its lock still writes', r.status_code == 200 and 'older' in ms_of('lk'))

# ---- 29.2 -------------------------------------------------------------------
print('29.2 replacing the manuscript keeps an editor save made meanwhile')
make_book('rp', '# One\n\nThe draft.\n', ext='.txt')
A.snapshot_manuscript('rp', A._project_manuscript_text(A.load_project('rp')))  # recent: the save's own is skipped
real_read = A._read_manuscript_upload
def save_meanwhile(up, ext):
    # the writing page saves while the upload is read: the book moves to rp.md
    with A._manuscript_lock('rp'):
        A._store_manuscript('rp', A.load_project('rp'), '# One\n\nWritten meanwhile.\n')
    return real_read(up, ext)
A._read_manuscript_upload = save_meanwhile
try:
    r = c.post('/project/rp/edit', data={
        'name': 'rp', 'preset': 'classic-literary', 'format': 'pdf',
        'manuscript': (io.BytesIO(b'# One\n\nThe replacement.\n'), 'new.txt')},
        content_type='multipart/form-data')
finally:
    A._read_manuscript_upload = real_read
check('the upload is the manuscript', 'replacement' in ms_of('rp'), ms_of('rp'))
check('the text saved meanwhile is in History',
      any('Written meanwhile' in (t or '') for t in history_texts('rp')),
      history_texts('rp'))

# ---- the engine ---------------------------------------------------------------
import engine
import manuscript
import fitz

META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False}
PARA = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 3

# ---- 29.4 -------------------------------------------------------------------
print('29.4 an overlong first word stays inside the trim')
ms = manuscript.parse_markdown('# One\n\n' + PARA + '\n\n' + 'W' * 100 + ' ' + PARA + '\n')
pdf = os.path.join(TMP, 'long.pdf')
preset = A.load_preset('classic-literary')
check('the style has hyphenation off', not preset.get('hyphenate'))
engine.build_pdf(ms, preset, pdf, dict(META))
doc = fitz.open(pdf)
past = []
for page in doc:
    for x0, y0, x1, y1, word, *_ in page.get_text('words'):
        if x1 > page.rect.width - 18:          # inside any outer margin
            past.append((page.number, word[:12], round(x1)))
doc.close()
check('no word runs past the margin', not past, past[:4])
check('the marker sits after the first word',
      hasattr(engine, '_after_first_word') and engine._after_first_word('<T/>', '<a name="x"/><i>First</i> word') ==
      '<a name="x"/><i>First</i><T/> word')
check('a one-word paragraph takes it at the end',
      hasattr(engine, '_after_first_word') and engine._after_first_word('<T/>', 'Alone') == 'Alone<T/>')

# ---- 29.5 -------------------------------------------------------------------
print('29.5 the back photo and the blurb keep apart')
from PIL import Image
wide = os.path.join(TMP, 'wide.png')
Image.new('RGB', (900, 600), (20, 80, 140)).save(wide)
tpl = A.load_cover_template('ashforge-house')
cf = engine._register_cover_fonts(tpl, engine.register_fonts(A.DEFAULTS))
dims = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.9, 'bleed': 0.125}
wpdf = os.path.join(TMP, 'wrap.pdf')
blurb = '\n'.join(['The island disappears every winter and returns in spring.'] * 9)
res = engine.build_cover_wrap(tpl, cf, {'title': 'The Salt Road', 'author': 'Ann Vale',
                                        'cover_blurb': blurb, 'cover_back_image': wide,
                                        'cover_back_image_w': 4.0,
                                        'cover_back_image_y': 0.05}, dims, wpdf)
g = engine.wrap_geometry(dims)
with fitz.open(wpdf) as doc:
    pg = doc[0]
    words = pg.get_text('words')
    pics = [im['bbox'] for im in pg.get_image_info()
            if im['bbox'][2] < (g['back_x'] + g['panel_w']) * 72 + 1]
check('the photo is drawn', bool(pics))
under = [w[4] for w in words for b in pics
         if w[0] < b[2] and w[2] > b[0] and w[1] < b[3] and w[3] > b[1]]
check('no blurb word lies under the photo', not under, under[:6])

# ---- 29.6 -------------------------------------------------------------------
print('29.6 the page list reaches the last page of the chapters')
LONG = ' '.join(['The tide came in over the stones while the bell kept its silence.'] * 160)
for label, extra in (('no back matter', {}), ('with an About the Author page',
                                              {'about_author': 'Ann lives by the sea.'})):
    ms = manuscript.parse_markdown('# One\n\nA start.\n\n' + LONG + '\n')
    pdf = os.path.join(TMP, 'tail.pdf')
    res = engine.build_pdf(ms, preset, pdf, dict(META, **extra))
    pp = res['print_pages']
    with fitz.open(pdf) as doc:
        pages = [doc[i].get_text() for i in range(len(doc))]
    body = [i for i, t in enumerate(pages) if 'The tide came in' in t]
    start = res['chapter_pages'][1]
    check(f'{label}: every page of the paragraph is listed',
          len(pp) == body[-1] - (start - 1) + 1, (len(pp), body[-1], start))
    check(f'{label}: the back matter is not', not extra or len(pp) < len(pages) - start + 1)

# ---- 29.7 -------------------------------------------------------------------
print('29.7 a figure and a two-column table are listed where they are')
PAR = ('The tide came in over the stones while the bell kept its silence, and the '
       'keeper counted the hours by the gulls that settled on the rail. ') * 4
md = ('# One\n\n' + '\n\n'.join(['Before ' + PAR] * 3)
      + '\n\n~~~ figure src="ghost-29.png" full="page"\nThe ghost plate\n~~~\n\n'
      + 'After ' + PAR + '\n')
ms = manuscript.parse_markdown(md)
bi = next(i for i, b in enumerate(ms['chapters'][0]['blocks']) if b[0] == 'doc_block')
res = engine.build_pdf(ms, preset, os.path.join(TMP, 'fig.pdf'), dict(META))
with fitz.open(os.path.join(TMP, 'fig.pdf')) as doc:
    start = res['chapter_pages'][1]
    fig_page = next(i for i in range(len(doc)) if 'ghost' in doc[i].get_text())
mine = [f for f, idx, b in res['print_pages'] if (idx, b) == (1, bi)]
check('the full-page figure is listed', bool(mine), res['print_pages'])
check('on its own page', mine[:1] == [fig_page - (start - 1) + 1], (mine, fig_page, start))

tw = A.load_preset('game-rulebook-two-column')
rows = '\n'.join(f'| r{i} | v{i} |' for i in range(70))
md = ('# One\n\n' + '\n\n'.join(['Before ' + PAR] * 14)
      + '\n\n~~~ table\n| A | B |\n|---|---|\n' + rows + '\n~~~\n\n' + 'After ' + PAR + '\n')
ms = manuscript.parse_markdown(md)
bi = next(i for i, b in enumerate(ms['chapters'][0]['blocks']) if b[0] == 'doc_block')
# the list names the first block on each page; what each block reported is
# in the document's hits
hits = {}
real_pp = engine._print_pages
def spy(doc):
    hits.clear()
    hits.update(doc._pos_hits)
    return real_pp(doc)
engine._print_pages = spy
try:
    res = engine.build_pdf(ms, tw, os.path.join(TMP, 'tab.pdf'), dict(META))
finally:
    engine._print_pages = real_pp
with fitz.open(os.path.join(TMP, 'tab.pdf')) as doc:
    tab_page = next(i for i in range(len(doc)) if 'r0' in doc[i].get_text().split())
check('the two-column table reports its page', hits.get((1, bi)) == tab_page + 1,
      (hits.get((1, bi)), tab_page + 1))

# ---- 29.8 - 29.10 -------------------------------------------------------------
import epub, zipfile

def epub_docs(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode('utf-8') for n in z.namelist()
                if n.endswith(('.xhtml', '.opf'))}

print("29.8 another book's page map")
mine = manuscript.parse_markdown('# One\n\nA first paragraph.\n\nA second one.\n')
theirs = manuscript.parse_markdown('# Elsewhere\n\nOther words.\n\nAnd more.\n')
res = engine.build_pdf(theirs, preset, os.path.join(TMP, 'theirs.pdf'), dict(META))
check('the PDF reports what its pages were set from', bool(res.get('print_pages_key')))
out = os.path.join(TMP, 'mine.epub')
epub.build_epub(mine, preset, out, dict(META, print_pages=res['print_pages'],
                                         print_pages_key=res['print_pages_key']))
d = epub_docs(out)
check('a map of the same shape from another book is not listed',
      'page-list' not in d['OEBPS/nav.xhtml'] and 'source-of' not in d['OEBPS/content.opf'])
epub.build_epub(mine, preset, out, dict(META, print_pages=res['print_pages']))
check('nor one that says nothing of its book', 'page-list' not in epub_docs(out)['OEBPS/nav.xhtml'])
res = engine.build_pdf(mine, preset, os.path.join(TMP, 'mine.pdf'), dict(META))
epub.build_epub(mine, preset, out, dict(META, print_pages=res['print_pages'],
                                         print_pages_key=res['print_pages_key']))
d = epub_docs(out)
check("its own book's map is listed", 'page-list' in d['OEBPS/nav.xhtml'])

print('29.9 the pagination source')
opf = d['OEBPS/content.opf']
check('a dc:source refined as the source of the pagination',
      '<dc:source id="pagination-source">The Drowned Bell, print edition</dc:source>' in opf
      and '<meta refines="#pagination-source" property="source-of">pagination</meta>' in opf,
      opf)
check('no a11y:pageBreakSource', 'pageBreakSource' not in opf)
check("the app's EPUB check finds no errors",
      all(r['ok'] for r in epub.check(out) if r.get('severity') != 'info'),
      [r for r in epub.check(out) if not r['ok']])

print('29.10 the contents landmark')
nav = d['OEBPS/nav.xhtml']
lm = re.search(r'<nav epub:type="landmarks".*?</nav>', nav, re.S).group(0)
check('no Contents page: no landmark into the nav', 'nav.xhtml' not in lm, lm)
epub.build_epub(mine, preset, out, dict(META, include_toc=True))
lm = re.search(r'<nav epub:type="landmarks".*?</nav>', epub_docs(out)['OEBPS/nav.xhtml'],
               re.S).group(0)
check('a Contents page is the landmark', 'href="toc.xhtml"' in lm, lm)

# ---- 29.11 ------------------------------------------------------------------
print('29.11 language tags')
for tag, want in (('fr-u', 'en'), ('x-internal', 'x-internal'), ('en--us', 'en'),
                  ('zh-Hant-TW', 'zh-Hant-TW'), ('en-US-u-ca-gregory', 'en-US-u-ca-gregory'),
                  ('es-419', 'es-419'), ('pt_BR', 'pt-BR'), ('de-CH-1996', 'de-CH-1996')):
    check(f'{tag} -> {want}', epub.book_lang({'language': tag}) == want,
          epub.book_lang({'language': tag}))
make_book('lg', language='fr')
r = c.post('/project/lg/edit', data={'name': 'lg', 'preset': 'classic-literary',
                                     'format': 'pdf', 'language': 'fr-u'})
check('Book settings keeps the language', A.load_project('lg').get('language') == 'fr',
      A.load_project('lg').get('language'))
with c.session_transaction() as sess:
    msgs = [m for _, m in sess.get('_flashes', [])]
check('and says why', any('fr-u' in m and "isn't a language" in m for m in msgs), msgs)
c.post('/project/lg/edit', data={'name': 'lg', 'preset': 'classic-literary',
                                 'format': 'pdf', 'language': 'pt-BR'})
check('a good tag is taken', A.load_project('lg').get('language') == 'pt-BR')

# ---- 29.12 ------------------------------------------------------------------
print('29.12 italics round a bold span')
import doc_model
runs = doc_model._parse_inline('*before **bold** after*', smartquotes=False)
check('the doc model reads italics round the bold',
      [(r['text'], r['bold'], r['italic']) for r in runs]
      == [('before ', False, True), ('bold', True, True), (' after', False, True)], runs)
md = '# C\n\n*before **bold** after*\n'
check('and writes it back as typed',
      doc_model.to_markdown(doc_model.from_markdown(md, smartquotes=False)) == md)
check('as the engine sets it', manuscript._inline('*before **bold** after*', smartquotes=False)
      == '<i>before <b>bold</b> after</i>')

# ---- 29.13 ------------------------------------------------------------------
print('29.13 a late name variant past the key budget')
import checker, random, string
rnd = random.Random(7)
names = set()
while len(names) < 1500:
    names.add(rnd.choice(string.ascii_uppercase)
              + ''.join(rnd.choice('aeioulnrstmk') for _ in range(15)))
words = sorted(names) + ['Quellmarrowind', 'Quellmarrowund']
pairs = {tuple(sorted(p)) for p in checker._similar_pairs(words, 0.85)}
check('the variant pair is found', ('Quellmarrowind', 'Quellmarrowund') in pairs)
real = checker._MAX_CANDIDATES
checker._MAX_CANDIDATES = 0
try:
    text = '# One\n\n' + ' '.join(f'{w} met {w}.' for w in sorted(names)[:40] + ['Quellmarrowind', 'Quellmarrowund']) + '\n'
    issues = checker._check_name_variants(manuscript.parse_markdown(text)) \
        if hasattr(checker, '_check_name_variants') else None
finally:
    checker._MAX_CANDIDATES = real
if issues is not None:
    check('a check cut short says so',
          any('not every name' in i['label'] for i in issues), [i['label'] for i in issues])

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
