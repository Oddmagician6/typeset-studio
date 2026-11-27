"""Round-7 Lows  (run: python test_lows7_bughunt.py).

Joint bug hunt, round 7, the Lows of sections 29, 30 and 32 (and one
speculative):

    29.14 a bleed the printer fixes (KDP case) is locked on the cover form
    30.10 a white stat-block section rule stays white on a dark screen page
    30.11 the EPUB tagline's Markdown is set, not printed (fixed with 31.11)
    30.12 an untitled part's PDF contents line uses the part number format
    32.10 cover uploads refuse a picture whose name lies about its format
    32.11 a failed package says where inside the data folder, not the full path
    spec  the package ZIP's move onto its name is retried, as the PDF's is
"""

import io, json, os, re, shutil, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
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


TMP = tempfile.mkdtemp(prefix='ts-bh7l-')

import app as A
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(TMP, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(TMP, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(TMP, 'presets'), os.path.join(TMP, 'covers')
A.PROJECT_DIR = os.path.join(TMP, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(TMP, 'out')
A.COVER_ASSET_DIR = os.path.join(TMP, 'cover-assets')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.OUT_DIR, A.COVER_ASSET_DIR):
    os.makedirs(d)
A.app.config['TESTING'] = True
C = A.app.test_client()

import engine, epub, manuscript
import fitz
from PIL import Image

META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False}
PARA = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 3
classic = A.load_preset('classic-literary')


def picture(fmt):
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (120, 60, 30)).save(buf, fmt)
    return buf.getvalue()


# ---- 29.14 ------------------------------------------------------------------
print('29.14 a bleed the printer fixes is locked on the cover form')
page = C.get('/cover/new').get_data(as_text=True)
m = re.search(r'<script id="wrap-retailers" type="application/json">(.*?)</script>', page, re.S)
data = json.loads(m.group(1)) if m else {}
check('the form gets each printer\'s fixed bleeds',
      data.get('kdp', {}).get('fixed_bleed') == ['hardcover']
      and data.get('generic', {}).get('fixed_bleed') == [], {k: v.get('fixed_bleed')
                                                             for k, v in data.items()})
check('and locks the field from them', 'fixed_bleed' in page and 'readOnly' in page)
for rid, rc in A.WRAP_RETAILERS.items():
    for binding in ('paperback', 'hardcover', 'jacket'):
        form = {'wrap_retailer': rid, 'wrap_binding': binding, 'wrap_bleed': '0.4'}
        ignored = A._wrap_dims(form, 200)['bleed'] != 0.4
        if ignored != (binding in rc.get('fixed_bleed', ())):
            check(f'{rid} {binding}: locked exactly where the build ignores it', False,
                  (ignored, rc.get('fixed_bleed')))
            break
    else:
        check(f'{rid}: locked exactly where the build ignores the bleed', True)

# ---- 30.10 ------------------------------------------------------------------
print('30.10 a white section rule stays white on a dark screen page')
game = A.load_preset('game-light-rulebook')
sb = dict(game.get('statblock') or {}, fill='', rule_color='#ffffff', section_rule=True,
          rule='none')
dark = dict(game, statblock=sb,
            screen=dict(game.get('screen') or {}, page='#1c1c1c', text='#eeeeee'))
ms = manuscript.parse_markdown(
    '# One\n\n' + PARA + '\n\n~~~ statblock cr="2"\nGate Warden\nMedium humanoid, lawful '
    'neutral\n\nArmor Class: 16 (chain)\nHit Points: 39 (6d8 + 12)\n\n### Actions\n'
    '***Halberd.*** Melee weapon attack: +4 to hit.\n~~~\n')
pdf = os.path.join(TMP, 'dark.pdf')
engine.build_pdf(ms, dark, pdf, dict(META), screen=True)
strokes = []
with fitz.open(pdf) as doc:
    for p in doc:
        for d in p.get_drawings():
            if d.get('color') is not None and d['rect'].height < 2 and d['rect'].width > 30:
                strokes.append(tuple(round(x, 2) for x in d['color']))
check('the section rule was drawn', bool(strokes), strokes)
check('every rule in the white it was given, none in the page colour',
      all(s == (1.0, 1.0, 1.0) for s in strokes), strokes)

# ---- 30.11 ------------------------------------------------------------------
print('30.11 the EPUB tagline sets its Markdown')
ms = manuscript.parse_markdown('# Arrival\n#> A **quiet** warning\n\n' + PARA + '\n')
ep = os.path.join(TMP, 'tag.epub')
epub.build_epub(ms, classic, ep, dict(META))
with zipfile.ZipFile(ep) as z:
    body = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml'))
tag = re.search(r'<p class="chapter-tagline">(.*?)</p>', body, re.S)
check('the tagline is there', bool(tag))
check('in bold, with no asterisks', tag and '**' not in tag.group(1)
      and re.search(r'<(strong|b)>quiet</\1>', tag.group(1)), tag and tag.group(1))

# ---- 30.12 ------------------------------------------------------------------
print('30.12 an untitled part\'s contents line takes the number format')
vol = dict(classic, part_divider=dict(classic.get('part_divider') or {},
                                      number_format='Volume {n}'))
ms = manuscript.parse_markdown('===\n\n# One\n\n' + PARA + '\n\n# Two\n\n' + PARA + '\n')
pdf = os.path.join(TMP, 'parts.pdf')
engine.build_pdf(ms, vol, pdf, dict(META, include_toc=True))
with fitz.open(pdf) as doc:
    pages = [p.get_text() for p in doc]
toc = next((t for t in pages if 'One' in t and 'Two' in t and '.' * 5 in t), '')
check('the contents page was found', bool(toc))
check('it says Volume 1, not Part 1', 'Volume 1' in toc and 'Part 1' not in toc, toc[:200])

# ---- 32.10 ------------------------------------------------------------------
print('32.10 a BMP named .png is refused as cover art')
bmp, png = picture('BMP'), picture('PNG')
try:
    A._is_image(png, '.png')
except TypeError:
    A._is_image = lambda data, ext=None, _f=A._is_image: _f(data)   # the unfixed one
check('a real PNG is a picture', A._is_image(png, '.png') and A._is_image(png))
check('a BMP named .png is not', not A._is_image(bmp, '.png'))
check('nor a PNG named .jpg', not A._is_image(png, '.jpg'))
r = C.post('/cover/asset/upload', data={'asset': (io.BytesIO(bmp), 'emblem.png')},
           content_type='multipart/form-data').get_json()
check('the asset upload refuses it', r and not r.get('ok'), r)
check('and keeps no file', os.listdir(A.COVER_ASSET_DIR) == [], os.listdir(A.COVER_ASSET_DIR))
r = C.post('/cover/asset/upload', data={'asset': (io.BytesIO(png), 'emblem.png')},
           content_type='multipart/form-data').get_json()
check('a real one is still taken', r and r.get('ok'), r)


class _Upload:
    def __init__(self, data, name):
        self.filename, self._d = name, data
    def read(self, n=-1):
        return self._d
    def seek(self, *a):
        pass
    def save(self, f):
        f.write(self._d)
    stream = property(lambda self: io.BytesIO(self._d))


try:
    A._cover_upload(_Upload(bmp, 'front.png'), os.path.join(TMP, 'covers-up'))
    took = True
except A._PreviewError:
    took = False
except Exception as exc:          # a stand-in the reader doesn't take: say so
    took = repr(exc)
check('the cover image upload refuses it', took is False, took)
try:
    A._save_back_image(_Upload(bmp, 'back.png'))
    took = True
except A._BadBackImage:
    took = False
except Exception as exc:
    took = repr(exc)
check('and so does the back-cover image', took is False, took)

# ---- 32.11 / spec -----------------------------------------------------------
print('32.11 a failed package names its file inside the data folder')
with open(os.path.join(A.PROJECT_MS_DIR, 'pk.md'), 'w', encoding='utf-8') as f:
    f.write('# One\n\n' + PARA + '\n')
A.save_project_file('pk', {'name': 'pk', 'title': 'pk', 'preset': 'classic-literary',
                           'manuscript_file': 'pk.md', 'manuscript_type': 'markdown',
                           'format': 'pdf', 'front_matter': 'none',
                           'author': 'Test Fixture', 'cover_mode': 'designed',
                           'cover_template': 'fantasy-emerald', 'print_retailer': 'kdp',
                           'print_binding': 'paperback', 'print_paper': 'cream'})
real_build = A.build_print_package
def failing(proj, scope='print'):
    raise PermissionError(13, 'Access is denied', os.path.join(A.OUT_DIR, 'pk-print.zip'))
A.build_print_package = failing
try:
    r = C.post('/project/pk/print-package', data={'scope': 'print'}, follow_redirects=True)
finally:
    A.build_print_package = real_build
text = r.get_data(as_text=True)
check('the failure is reported', 'package failed' in text, r.status_code)
# (the temp folder's own name: str() of the error doubled its backslashes)
check('without the absolute path', os.path.basename(TMP) not in text
      and 'out/pk-print.zip' in text)
check('in the writer\'s words', 'refused access' in text)

print('spec: a ZIP held open a moment by another program is still published')
real_replace = os.replace
held = []
def flaky(src, dst):
    if str(dst).endswith('.zip') and not held:
        held.append(dst)
        raise PermissionError(13, 'The process cannot access the file', dst)
    return real_replace(src, dst)
os.replace = flaky
try:
    info = A.build_print_package(A.load_project('pk'), 'print')
    err = None
except Exception as exc:
    info, err = None, exc
finally:
    os.replace = real_replace
check('the first move was refused', bool(held))
check('and the package still came out', info and os.path.isfile(
    os.path.join(A.OUT_DIR, info['zip_name'])), err)

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
