"""EPUB features left open in round 5  (run: python test_epubfeatures_bughunt.py).

    23.5  a book says its own language: the EPUB (both layouts) and the PDF,
          from a Language setting on Set a Book and Book settings
    23.12 an animated picture makes the flashing and motion hazards unknown,
          not "none"
    23.13 both layouts list landmarks: cover, contents, start of the story,
          notes and index
"""

import copy, io, os, re, sys, shutil, tempfile, zipfile
from xml.dom import minidom

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
import manuscript

fails = []
TMP = tempfile.mkdtemp(prefix='ts-epubfeat-')
META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}


def check(label, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f'         {detail}')
        fails.append(label)


def read(out):
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode('utf-8') for n in z.namelist()
                if n.endswith(('.xhtml', '.opf', '.xml'))}


def build(md, name, **meta):
    out = os.path.join(TMP, name + '.epub')
    epub.build_epub(manuscript.parse_markdown(md), copy.deepcopy(A.DEFAULTS), out,
                    dict(META, **meta))
    return out, read(out)


def well_formed(docs):
    bad = []
    for n, s in docs.items():
        try:
            minidom.parseString(s.encode('utf-8'))
        except Exception as e:
            bad.append(f'{n}: {e}')
    return bad


# ---- 23.5 -------------------------------------------------------------------
print('23.5 the book\'s language')
check('a tag is kept', epub.book_lang({'language': 'pt-BR'}) == 'pt-BR')
check('an underscore is read as a hyphen', epub.book_lang({'language': 'pt_BR'}) == 'pt-BR')
for bad in ('', 'French', 'en"><x', 'e', '12'):
    check(f'{bad!r} is taken as English', epub.book_lang({'language': bad}) == 'en')
check('no setting is English', epub.book_lang({}) == 'en')

out, docs = build('# Un\n\nLa mer monte.\n', 'fr', language='fr')
opf = docs['OEBPS/content.opf']
check('the package says French', '<dc:language>fr</dc:language>' in opf
      and 'xml:lang="fr"' in opf, re.findall(r'<dc:language>[^<]*', opf))
chap = docs['OEBPS/chapter001.xhtml']
check('so does a chapter', 'xml:lang="fr" lang="fr"' in chap, chap[:300])
check('and the contents', 'xml:lang="fr"' in docs['OEBPS/nav.xhtml'])
check('no page says English', not any('xml:lang="en"' in s for s in docs.values()))
check('every page is well-formed', not well_formed(docs), well_formed(docs))
out, docs = build('# One\n\nThe tide.\n', 'en')
check('a book with no setting is still English', '<dc:language>en</dc:language>'
      in docs['OEBPS/content.opf'])
check('and the next build forgets the last one\'s language',
      'xml:lang="en"' in docs['OEBPS/chapter001.xhtml'])

# fixed layout
TRIM = {'trim': {'w': 8.5, 'h': 8.5}}
design = {'name': 'fox', 'saved': 's', 'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#c08040'},
    {'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 1, 'w': 7.0,
     'text': 'Le renard.', 'font': 'Andika-Regular.ttf', 'size': 22, 'leading': 1.3,
     'color': '#000000', 'align': 'left', 'tracking': 0}]}
fxl = os.path.join(TMP, 'fxl.epub')
cover = os.path.join(TMP, 'cover.jpg')
from PIL import Image
Image.new('RGB', (850, 850), (200, 120, 60)).save(cover)
epub.build_epub(manuscript.parse_markdown('~~~ page src="fox"\nUn renard.\n~~~\n'), TRIM, fxl,
                {'title': 'T', 'author': 'A', 'page_designs': [design], 'ebook_layout': 'fixed',
                 'front_matter': 'none', 'language': 'fr', 'cover_image': cover})
fdocs = read(fxl)
check('a picture book says French', '<dc:language>fr</dc:language>' in fdocs['OEBPS/content.opf'])
check('on its pages too', all('lang="fr"' in v for k, v in fdocs.items()
                              if k.endswith('.xhtml')))
check('its pages are well-formed', not well_formed(fdocs), well_formed(fdocs))

# the PDF
pdf = os.path.join(TMP, 'fr.pdf')
engine.build_pdf(manuscript.parse_markdown('# Un\n\nLa mer monte.\n'), copy.deepcopy(A.DEFAULTS),
                 pdf, dict(META, language='fr'))
import fitz
with fitz.open(pdf) as d:
    lang = d.xref_get_key(d.pdf_catalog(), 'Lang')
check('the PDF says French', lang == ('string', 'fr'), lang)

# the settings
A.app.config['TESTING'] = True
for d in ('presets', 'covers'):
    shutil.copytree(os.path.join(HERE, d), os.path.join(TMP, d),
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
with open(os.path.join(A.PROJECT_MS_DIR, 'bk.md'), 'w', encoding='utf-8') as f:
    f.write('# Un\n\nLa mer.\n')
A.save_project_file('bk', dict(
    name='bk', title='T', author='A', preset='classic-literary', format='pdf',
    manuscript_file='bk.md', manuscript_type='markdown', cover_file='', cover_mode='none',
    last_pdf='', last_epub='', created='2026-01-01T00:00:00',
    updated='2026-01-01T00:00:00', front_matter='none'))
c = A.app.test_client()
page = c.get('/project/bk/edit').get_data(as_text=True)
check('Book settings shows the language, English when unset',
      re.search(r'name="language"[^>]*value="en"', page), re.findall(r'<input[^>]*language[^>]*>', page))
form = {'name': 'bk', 'title': 'T', 'author': 'A', 'preset': 'classic-literary',
        'front_matter': 'none', 'language': 'de'}
c.post('/project/bk/edit', data=form)
check('a language is saved', A.load_project('bk').get('language') == 'de',
      A.load_project('bk').get('language'))
c.post('/project/bk/edit', data=dict(form, language='<b>'))
check('nonsense is saved as English', A.load_project('bk').get('language') == 'en',
      A.load_project('bk').get('language'))
check('Set a Book has the field', 'name="language"' in c.get('/generate').get_data(as_text=True))

# ---- 23.12 ------------------------------------------------------------------
print('23.12 animated pictures')
figdir = os.path.join(TMP, 'figures')
os.makedirs(figdir)
frames = [Image.new('RGB', (40, 40), col) for col in ((255, 255, 255), (0, 0, 0))]
frames[0].save(os.path.join(figdir, 'flash.gif'), save_all=True, append_images=frames[1:],
               duration=50, loop=0)
frames[0].save(os.path.join(figdir, 'still.gif'))
real = epub.FIGURE_DIR
epub.FIGURE_DIR = figdir
try:
    out, docs = build('# One\n\n~~~ figure src="flash.gif" alt="A lamp"\n~~~\n', 'anim')
    opf = docs['OEBPS/content.opf']
    hz = re.findall(r'accessibilityHazard">([^<]*)', opf)
    check('an animated picture: flashing and motion unknown, no sound',
          sorted(hz) == ['noSoundHazard', 'unknownFlashingHazard',
                         'unknownMotionSimulationHazard'], hz)
    check('and the summary says so', 'animated' in opf)
    out, docs = build('# One\n\n~~~ figure src="still.gif" alt="A lamp"\n~~~\n', 'still')
    hz = re.findall(r'accessibilityHazard">([^<]*)', docs['OEBPS/content.opf'])
    check('a still picture: none', hz == ['none'], hz)
finally:
    epub.FIGURE_DIR = real

# ---- 23.13 ------------------------------------------------------------------
print('23.13 landmarks')


def landmarks(nav):
    m = re.search(r'<nav epub:type="landmarks".*?</nav>', nav, re.S)
    return re.findall(r'epub:type="(\w+)" href="([^"]+)"', m.group(0)) if m else None


out, docs = build('# One\n\nText.[^1]\n\n[^1]: A note.\n\n# Two\n\nMore.\n', 'marks')
lm = landmarks(docs['OEBPS/nav.xhtml'])
check('contents, start and notes', lm == [('toc', 'nav.xhtml#toc'),
                                          ('bodymatter', 'chapter001.xhtml'),
                                          ('endnotes', 'endnotes.xhtml')], lm)
out, docs = build('=== The Coast\n\n# One\n\nText.\n', 'part', include_toc=True)
lm = landmarks(docs['OEBPS/nav.xhtml'])
check('a book opening on a part starts there; a contents page is the contents',
      lm and ('bodymatter', 'part001.xhtml') in lm and ('toc', 'toc.xhtml') in lm, lm)
names = set(zipfile.ZipFile(out).namelist())
check('and every landmark is in the book', lm and all(
    'OEBPS/' + h.split('#')[0] in names for _, h in lm), lm)
out, docs = build('# One\n\nThe {index: bell} rang.\n', 'ix', index_terms=True)
lm = landmarks(docs['OEBPS/nav.xhtml'])
if 'OEBPS/bookindex.xhtml' in docs:
    check('an index is a landmark', lm and ('index', 'bookindex.xhtml') in lm, lm)
check('the contents page is well-formed', not well_formed(docs), well_formed(docs))
lm = landmarks(fdocs['OEBPS/nav.xhtml'])
check('a picture book: cover, contents, beginning', lm and [t for t, _ in lm]
      == ['cover', 'toc', 'bodymatter'], lm)
check('its check still passes', all(r['ok'] for r in epub.check(fxl)
                                    if r.get('severity') != 'info'),
      [r for r in epub.check(fxl) if not r['ok']])

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('all passed')
