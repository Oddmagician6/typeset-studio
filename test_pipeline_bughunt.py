"""Builds record, show and clean up what they made  (run: python test_pipeline_bughunt.py).

Joint bug hunt, round 4, section 18:

    18.1  an older build finishing last doesn't replace the newer edition
    18.2  a deleted book's build doesn't land on a new book with its id
    18.3  one build uses one cover for every edition
    18.4  the PDF appears under its name only once it is finished
    18.5  a cover left off the EPUB (template deleted) is a failed check
    18.6  Rebuild all counts a saved screen PDF as built
    18.7  an EPUB-only build that made nothing is a failure
    18.8  a refused EPUB file doesn't hide the finished PDF
    18.9  the preview shows the screen PDF an ebook-only book exports
    18.10 the preview's contents list every chapter
    18.11 a thumbnail of the old edition isn't kept for the new one
    18.12 a failed build leaves no scratch PDFs or page folders
    18.13 a rejected Compose attempt removes the files it staged
    18.14 a Compose retry keeps smart punctuation off and dark cover text
"""

import sys, os, io, re, json, shutil, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine
import epub

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
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.OUT_DIR, A.FIGURE_DIR,
              A.PROJECT_THUMB_DIR):
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

# ---- 18.1 / 18.2 -----------------------------------------------------------
print('18.1 / 18.2 recording a build')
make_book('rb')
A._record_build('rb', {'last_pdf': 'new.pdf'}, '2026-02-01T10:00:05.000000', '2026-01-01T00:00:00')
A._record_build('rb', {'last_pdf': 'old.pdf'}, '2026-02-01T10:00:01.000000', '2026-01-01T00:00:00')
p = A.load_project('rb')
check('the newer edition stays on the shelf', p['last_pdf'] == 'new.pdf', p['last_pdf'])
check('built is when that build read the book', p['built'] == '2026-02-01T10:00:05', p.get('built'))
A.update_project('rb', {'updated': '2026-02-01T10:00:09'})      # saved while it built
A._record_build('rb', {'last_pdf': 'newest.pdf'}, '2026-02-01T10:00:08.000000', '2026-01-01T00:00:00')
p = A.load_project('rb')
check('a save during the build still reads "changed since"', p['updated'] > p['built'],
      (p['updated'], p['built']))
make_book('rb', created='2026-03-01T00:00:00')                   # deleted, made again
got = A._record_build('rb', {'last_pdf': 'ghost.pdf'}, '2026-03-01T10:00:00.000000',
                      '2026-01-01T00:00:00')
check("the old book's build leaves the new one alone",
      got is None and A.load_project('rb')['last_pdf'] == '', A.load_project('rb').get('last_pdf'))

# ---- 18.3 ------------------------------------------------------------------
print('18.3 one cover per build')
from PIL import Image
Image.new('RGB', (600, 900), (10, 80, 160)).save(os.path.join(A.PROJECT_MS_DIR, 'cv.jpg'))
make_book('cv', cover_mode='image', cover_file='cv.jpg', format='both')
seen = {}
real_pdf, real_epub = engine.build_pdf, epub.build_epub
def spy_pdf(ms, preset, out, meta, **kw):
    seen['pdf'] = meta.get('cover_image')
    seen['pdf_exists'] = os.path.exists(seen['pdf'] or '')
    return real_pdf(ms, preset, out, meta, **kw)
engine.build_pdf = spy_pdf
try:
    res = A._build_project('cv', A.load_project('cv'))
finally:
    engine.build_pdf = real_pdf
check('the build works from its own copy of the cover',
      seen.get('pdf') and seen['pdf'] != os.path.join(A.PROJECT_MS_DIR, 'cv.jpg')
      and seen['pdf_exists'], seen)
check('and the copy is gone afterwards', not os.path.exists(seen.get('pdf') or 'x'))
check('the build still made both editions', res['out_name'] and res['epub_name'], res.get('error'))

# ---- 18.4 / 18.12 -----------------------------------------------------------
print('18.4 / 18.12 the PDF and its scratch files')
import manuscript as M
P = A.load_preset('classic-literary')
paths = []
real_inner = engine._build_pdf
def spy_inner(ms, preset, out, meta, **kw):
    paths.append(out)
    return real_inner(ms, preset, out, meta, **kw)
engine._build_pdf = spy_inner
try:
    out = os.path.join(TMP, 'final.pdf')
    engine.build_pdf(M.parse_markdown('# One\n\nText.\n'), P, out, {'title': 'T', 'author': 'A'})
finally:
    engine._build_pdf = real_inner
check('the passes write beside the final name', paths and paths[0].endswith('.part'), paths)
check('and the finished file takes it', os.path.getsize(out) > 0 and not os.path.exists(out + '.part'))

scratch = tempfile.mkdtemp()
old_tempdir = tempfile.tempdir
tempfile.tempdir = scratch
real_story = engine._build_story
def boom(*a, **k):
    raise RuntimeError('layout failed')
engine._build_story = boom
try:
    try:
        engine.build_pdf(M.parse_markdown('# One\n\nText.\n\n# Two\n\nMore.\n'), P,
                         os.path.join(TMP, 'f.pdf'), {'title': 'T', 'author': 'A',
                                                      'include_toc': True})
    except RuntimeError:
        pass
finally:
    engine._build_story = real_story
    tempfile.tempdir = old_tempdir
check('a failed contents pass leaves no scratch PDF', os.listdir(scratch) == [], os.listdir(scratch))
check('nor a .part file', not os.path.exists(os.path.join(TMP, 'f.pdf.part')))

real_pages = epub._render_pages
def pages_then_fail(chapters, meta, preset, folder):
    seen['pages_dir'] = folder
    raise RuntimeError('zip failed')
epub._render_pages = pages_then_fail
try:
    try:
        epub.build_epub(M.parse_markdown('# One\n\nText.\n'), P, os.path.join(TMP, 'x.epub'),
                        {'title': 'T', 'author': 'A'})
    except RuntimeError:
        pass
finally:
    epub._render_pages = real_pages
check("a failed EPUB removes its pages folder", not os.path.exists(seen.get('pages_dir', 'x')))

# ---- 18.5 ------------------------------------------------------------------
print('18.5 a deleted cover template in the EPUB')
ep = os.path.join(TMP, 'plain.epub')
epub.build_epub(M.parse_markdown('# One\n\nText.\n'), P, ep, {'title': 'T', 'author': 'A'})
rows = A._epub_checks(ep, None, {'cover_mode': 'designed', 'cover_template': 'gone-one',
                                  'cover_template_data': None}, P)
check('the checks name the missing cover',
      any(not r['ok'] and 'gone-one' in r['detail'] for r in rows), rows)

# ---- 18.6 / 18.7 / 18.8 -----------------------------------------------------
print('18.6 / 18.7 / 18.8 failures beside what was made')
def epub_fails(*a, **k):
    raise RuntimeError('writer failed')
make_book('eo', format='epub', built='2026-01-05T00:00:00')
epub.build_epub = epub_fails
try:
    res = A._build_project('eo', A.load_project('eo'))
    check('an EPUB-only build that made nothing is an error', res['error'], res)
    check('and keeps its old build date', A.load_project('eo').get('built') == '2026-01-05T00:00:00',
          A.load_project('eo').get('built'))
    r = c.post('/generate', data={'preset': 'classic-literary', 'format': 'epub',
                                  'pasted': '# One\n\nText.\n', 'title': 'T'})
    check('Compose shows the form again, not "Off the press"',
          b'Off the press' not in r.data and b'writer failed' in r.data, r.status_code)
    make_book('es', format='epub', screen_pdf=True)
    r = c.post('/project/es/rebuild').get_json()
    check('Rebuild all counts the screen PDF it made', r['ok'] and r['screen'], r)
finally:
    epub.build_epub = real_epub
make_book('bo', format='both')
real_claim = A._claim_out
def claim(name, folder=None):
    if name.endswith('.epub'):
        raise OSError('no room')
    return real_claim(name, folder)
A._claim_out = claim
try:
    res = A._build_project('bo', A.load_project('bo'))
finally:
    A._claim_out = real_claim
check('a refused EPUB file leaves the PDF recorded',
      not res['error'] and res['out_name'] and A.load_project('bo')['last_pdf'] == res['out_name'],
      res.get('error'))

# ---- 18.9 / 18.10 -----------------------------------------------------------
print('18.9 / 18.10 the first-pages proof')
calls = []
def spy(ms, preset, out, meta, **kw):
    calls.append((len(ms['chapters']), kw))
    return real_pdf(ms, preset, out, meta, **kw)
engine.build_pdf = spy
try:
    c.post('/generate/preview', data={'preset': 'classic-literary', 'format': 'epub',
                                      'screen_pdf': 'on', 'pasted': '# One\n\nText.\n'})
    check('an ebook-only book with a screen PDF previews the screen PDF',
          calls and calls[-1][1].get('screen'), calls)
    many = ''.join(f'# Chapter {i}\n\nText.\n\n' for i in range(1, 9))
    r = c.post('/generate/preview', data={'preset': 'classic-literary', 'format': 'pdf',
                                          'include_toc': 'on', 'pasted': many}).get_json()
    check('the contents list every chapter', calls[-1][0] == 8, calls[-1])
    check('the proof still says two were shown', r.get('chapters_shown') == 2, r)
finally:
    engine.build_pdf = real_pdf

# ---- 18.11 -----------------------------------------------------------------
print('18.11 thumbnails')
make_book('th')
a = A._thumb_cache('th', os.path.join(A.OUT_DIR, 'th-1.pdf'))
b = A._thumb_cache('th', os.path.join(A.OUT_DIR, 'th-2.pdf'))
check('each edition has a thumbnail of its own', a != b, (a, b))

# ---- 18.13 / 18.14 ----------------------------------------------------------
print('18.13 / 18.14 a rejected Compose attempt')
for f in os.listdir(A.UPLOAD_DIR):
    os.remove(os.path.join(A.UPLOAD_DIR, f))
r = c.post('/generate', data={'preset': 'classic-literary', 'format': 'pdf',
                              'manuscript': (io.BytesIO(b'# One\n\nText.\n'), 'book.md'),
                              'cover_mode': 'image', 'cover_color': 'dark',
                              'cover': (io.BytesIO(b'not a picture'), 'c.png')},
           content_type='multipart/form-data')
check('the cover is refused', r.status_code == 200 and b'isn' in r.data, r.status_code)
check('and the manuscript it staged is gone', os.listdir(A.UPLOAD_DIR) == [], os.listdir(A.UPLOAD_DIR))
page = r.data.decode('utf-8')
check('smart punctuation stays off', not re.search(r'name="smartquotes" checked', page))
check('dark cover text stays picked', re.search(r'value="dark" selected', page))

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
