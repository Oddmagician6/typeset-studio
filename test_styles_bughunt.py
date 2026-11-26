"""Styles, defaults and the libraries keep what they hold  (run: python test_styles_bughunt.py).

Joint bug hunt, round 3, section 16:

    16.1  a new style or cover can't take a deleted bundled one's id
    16.2  a History version from before a page rename still finds the page
    16.3  Repair keeps a whole settings object that has junk after it
    16.4  Large Print never shortens the page under a deep chapter sink
    16.5  a font re-uploaded under the same name is read afresh
    16.6  a Regular file standing in for Bold leaves Italic working
    16.7  saving a style keeps sections the editor has no fields for
    16.8  a figure an older History version places counts as in use
    16.9  a damaged style or book still holds the fonts and figures it names
    16.10 Large Print stays inside the editor's limits
    16.11 Large Print scales table and heading sizes with the body
    16.12 a History restore doesn't read as a fresh build
    16.13 small caps for stat-block labels and entry names
    16.14 the ebook keeps the two heading sizes
"""

import sys, os, io, re, json, shutil, tempfile, time

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


def ms_text(pid):
    return A._project_manuscript_text(A.load_project(pid), report_import=False)


TMP = tempfile.mkdtemp()
use_folders(TMP)
A.app.config['TESTING'] = True
c = A.app.test_client()

# ---- 16.1 ------------------------------------------------------------------
print('16.1 a deleted bundled id stays reserved')
real = A._bundled_ids
A._bundled_ids = lambda name: {'modern-clean'} if name == 'presets' else {'gilded-frame'}
try:
    gone = os.path.join(A.PRESET_DIR, 'modern-clean.json')
    if os.path.exists(gone):
        os.remove(gone)
    check('a new style called Modern Clean gets an id of its own',
          A.unique_id('modern-clean') != 'modern-clean', A.unique_id('modern-clean'))
    gone = os.path.join(A.COVER_DIR, 'gilded-frame.json')
    if os.path.exists(gone):
        os.remove(gone)
    check('and so does a cover template', A.unique_cover_id('gilded-frame') != 'gilded-frame')
finally:
    A._bundled_ids = real

# ---- 16.2 ------------------------------------------------------------------
print('16.2 restoring from before a page rename')
EL = [{'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
       'text': 'Map', 'font': 'EBGaramond-Regular.ttf', 'size': 24, 'color': '#000000'}]
make_book('pr', text='# One\n\nText.\n\n~~~ page src="map"\n~~~\n\nMore.\n')
r = c.post('/page-designer/pr/save', json={'name': 'map', 'design': {'elements': EL}}).get_json()
old_stamp = A.snapshot_manuscript('pr', ms_text('pr'), reason='edit', force=True)
r = c.post('/page-designer/pr/save', json={'name': 'island-map', 'was': 'map',
                                          'design': {'elements': EL}}).get_json()
check('the rename moves the manuscript', 'src="island-map"' in ms_text('pr'), ms_text('pr'))
c.post('/project/pr/write/save', data={'text': '# One\n\nRewritten.\n'})
r = c.post(f'/project/pr/history/{old_stamp}/restore').get_json()
check('the restored version places the page by its new name',
      r and r.get('ok') and 'src="island-map"' in ms_text('pr'), (r, ms_text('pr')))

# ---- 16.3 ------------------------------------------------------------------
print('16.3 junk after a whole object')
p = os.path.join(TMP, 'junk.json')
with open(p, 'w', encoding='utf-8') as f:
    f.write(json.dumps({'name': 'x', 'page_designs': [{'name': 'a', 'elements': []}]},
                       indent=2) + 'oops')
got = A.salvage_json(p)
check('the last setting survives', got.get('page_designs') == [{'name': 'a', 'elements': []}], got)

# ---- 16.4 / 16.10 / 16.11 --------------------------------------------------
print('16.4 / 16.10 / 16.11 Large Print')
base = A.load_preset('classic-literary')
tall = json.loads(json.dumps(base))
tall['trim'] = {'w': 6.0, 'h': 12.0}
tall['chapter']['sink'] = 8.5
lp = A.make_large_print(tall)
text_h = lp['trim']['h'] - lp['margins']['top'] - lp['margins']['bottom']
check('the page is not cut shorter', lp['trim']['h'] >= 12.0, lp['trim'])
check('the sink still leaves the opener room', lp['chapter']['sink'] <= text_h - 1.5,
      (lp['chapter']['sink'], text_h))
out = os.path.join(TMP, 'lp.pdf')
try:
    engine.build_pdf(M.parse_markdown('# One\n\nShort.\n'), lp, out,
                     {'title': 'T', 'author': 'A', 'front_matter': 'none', 'include_toc': False})
    built = os.path.exists(out)
except Exception as exc:
    built = repr(exc)
check('and it builds', built is True, built)
small = json.loads(json.dumps(base))
small['body']['size'] = 8.0
small['chapter']['title_size'] = 80.0
small.setdefault('table', {})['font_size'] = 20.0
small.setdefault('headings', {})['section_size'] = 20.0
lp = A.make_large_print(small)
check('16.10 the title stays inside the editor limit', lp['chapter']['title_size'] <= 144.0,
      lp['chapter']['title_size'])
check('16.11 table text scales with the body', lp['table']['font_size'] == 40.0, lp['table'])
check('16.11 so do section headings', lp['headings']['section_size'] == 40.0, lp['headings'])

# ---- 16.5 ------------------------------------------------------------------
print('16.5 a font re-uploaded under its old name')
from reportlab.pdfbase import pdfmetrics
custom = os.path.join(TMP, 'Inkwell.ttf')
shutil.copy(os.path.join(A.FONT_DIR, 'Alegreya-Regular.ttf'), custom)
n1 = engine.font_for(custom)
os.remove(custom)
time.sleep(0.05)
shutil.copy(os.path.join(A.FONT_DIR, 'Alegreya-Regular.ttf'), custom)
os.utime(custom, None)
n2 = engine.font_for(custom)
check('the new file gets a face of its own', n1 != n2 and
      pdfmetrics.getFont(n2).face is not pdfmetrics.getFont(n1).face, (n1, n2))

# ---- 16.6 ------------------------------------------------------------------
print('16.6 Regular reused as Bold')
p = json.loads(json.dumps(base))
p['font_files'] = {'regular': 'Alegreya-Regular.ttf', 'bold': 'Alegreya-Regular.ttf',
                   'italic': 'Alegreya-Italic.ttf'}
fonts = engine.register_fonts(p)
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate
out = os.path.join(TMP, 'it.pdf')
SimpleDocTemplate(out).build([Paragraph('plain <i>emphasis</i>', ParagraphStyle(
    't', fontName=fonts['regular'], fontSize=11))])
import fitz
used = {f[3] for f in fitz.open(out).load_page(0).get_fonts()}
check('the emphasis is set in the italic face', any('Italic' in u for u in used), used)

# ---- 16.7 ------------------------------------------------------------------
print('16.7 a save keeps the poem settings')
d = A.load_preset('classic-literary')
d['poem'] = dict(d.get('poem') or {}, align='center', font_size=18)
A.save_preset('classic-literary', d)
page = c.get('/editor/classic-literary').get_data(as_text=True)
ver = re.search(r'name="version" value="([0-9a-f]+)"', page).group(1)
c.post('/save/classic-literary', data={'name': d['name'], 'description': 'changed',
                                       'version': ver})
after = A.load_preset('classic-literary')
check('the poem section survives', (after.get('poem') or {}).get('align') == 'center'
      and after['poem'].get('font_size') == 18, after.get('poem'))
check('and the description changed', after.get('description') == 'changed')

# ---- 16.8 ------------------------------------------------------------------
print('16.8 a figure an older version places')
with open(os.path.join(A.FIGURE_DIR, 'island.png'), 'wb') as f:
    from PIL import Image
    b = io.BytesIO(); Image.new('RGB', (20, 20), (1, 2, 3)).save(b, 'PNG'); f.write(b.getvalue())
make_book('fig', text='# One\n\n~~~ figure src="island.png"\n~~~\n')
A.snapshot_manuscript('fig', ms_text('fig'), reason='edit', force=True)
c.post('/project/fig/write/save', data={'text': '# One\n\nNo picture now.\n'})
uses = A._figure_uses('island.png')
check('the History version counts as a use', any('History' in u for u in uses), uses)

# ---- 16.9 ------------------------------------------------------------------
print('16.9 a damaged style still holds its font')
d = A.load_preset('classic-literary')
d['font_files'] = dict(d['font_files'], regular='Inkwell.ttf')
d['body'] = dict(d['body'], leading='wide')
with open(os.path.join(A.PRESET_DIR, 'broken.json'), 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2)
check('the style is damaged', any(x['id'] == 'broken' for x in A.damaged_files('style')))
check('its font counts as in use', any('Inkwell' in u or 'Classic' in u or 'broken' in u
                                       for u in A._font_uses('Inkwell.ttf')),
      A._font_uses('Inkwell.ttf'))

# ---- 16.12 -----------------------------------------------------------------
print('16.12 a restore is not a build')
make_book('rb', last_pdf='rb.pdf', built='2026-02-01T10:00:00', updated='2026-03-05T10:00:00')
html = c.get('/projects').get_data(as_text=True)
check('the card shows the build date', '2026-02-01' in html, '')
check('and that the book changed since', 'changed since' in html)

# ---- 16.13 -----------------------------------------------------------------
print('16.13 small-caps stat-block labels')
p = json.loads(json.dumps(base))
p['statblock'] = dict(engine.GAME_BLOCK_DEFAULTS['statblock'],
                      field_label_style='smallcaps', entry_name_style='smallcaps')
fonts = engine.register_fonts(p)
from reportlab.lib.styles import getSampleStyleSheet
st = ParagraphStyle('b', fontName=fonts['regular'], fontSize=10, leading=13)
text = ('~~~ statblock\n## Bog Hag\n*Medium fey*\n**Armor Class** 15\n**Hit Points** 40\n'
        '***Multiattack.*** The hag claws twice.\n~~~\n')
doc = M.parse_markdown('# One\n\n' + text)
blk = [b for ch in doc['chapters'] for b in ch.get('blocks', []) if isinstance(b, dict)] \
    if isinstance(doc['chapters'][0], dict) else []
src = open(os.path.join(HERE, 'engine.py'), encoding='utf-8').read()
check('field labels take the small-caps face',
      "_gb_caps(f['label'], flabel)" in src and "'smallcaps': (f'<b><font size" in src)
check('entry names too', "_gb_caps(e['name'], estyle)" in src)
out = os.path.join(TMP, 'sb.pdf')
engine.build_pdf(doc, p, out, {'title': 'T', 'author': 'A', 'front_matter': 'none',
                               'include_toc': False})
import fitz
words = fitz.open(out).load_page(0).get_text()
for pg in fitz.open(out):
    words += pg.get_text()
check('the PDF prints them in capitals', 'ARMOR CLASS' in words and 'MULTIATTACK' in words,
      words[-300:])

# ---- 16.14 -----------------------------------------------------------------
print('16.14 heading sizes in the ebook')
p = json.loads(json.dumps(base))
p['body']['size'] = 12.0
p['headings'] = dict(p.get('headings') or {}, section_size=24, subsection_size=14)
css = epub._style_css(p)
# (the rule also names the heading's class: round 5, 23.10)
check('### is twice the body', re.search(r'h3, \.hd-section \{ font-size: 2em', css), css[:300])
check('#### is in proportion', re.search(r'h4, \.hd-subsection \{ font-size: 1\.167em', css), css[:300])
check('unset sizes stay at the body', 'h3, .hd-section { font-size: 1em' in epub._style_css(base))

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
