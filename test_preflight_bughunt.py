"""Preflight says what the book will really print  (run: python test_preflight_bughunt.py).

Joint bug hunt, round 2, section 11:

    11.1  a designed page that loses its text (its font gone) is reported
    11.2  a figure with no src (PDF) or a missing file (EPUB) is reported
    11.3  a picture whose bytes aren't its extension is refused at upload, and
          an EPUB declaring the wrong type is caught
    11.4  a page background that has gone is reported
    11.5  the continuity check ends on a pathological manuscript
    11.6  "fonts embedded" reads the PDF: a telegram's Courier is not embedded
    11.7  a KDP hardcover is held to the hardcover page range
    11.9  the page preview builds the print variant the export makes
    11.10 the ebook preview has the designed cover the export has
    11.11 an epubcheck run that never finished is not a pass
    11.12 continuity names chapters by their printed number
    11.13 a chapter holding only a picture is not "empty"
    11.14 a repeated quoted sentence is found
"""

import sys, os, io, re, json, time, tempfile, shutil, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import engine, epub, checker
import manuscript as M

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


PRESET = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
META = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light'}
TMP = tempfile.mkdtemp()


def pdf(md, meta=None, preset=None, **kw):
    return engine.build_pdf(M.parse_markdown(md), preset or PRESET,
                            os.path.join(TMP, 'b.pdf'), dict(META, **(meta or {})), **kw)


def labels(checks):
    return {c['label']: c for c in checks}


# ---- 11.1 ------------------------------------------------------------------
print('11.1 designed page without its font')
design = {'name': 'Map page', 'kind': 'page',
          'elements': [{'type': 'text', 'id': 't1', 'text': 'Welcome', 'font': 'Gone-Font.ttf',
                        'size': 20, 'x': 0.1, 'y': 0.1, 'w': 3, 'h': 1}]}
res = pdf('# One\n\n~~~ page src="Map page"\n~~~\n', {'page_designs': [design]})
rows = [c for c in A._preflight(res, PRESET, res['page_count']) if not c['ok']]
check('the page is reported', any('Gone-Font' in c['detail'] for c in rows),
      [c['detail'][:80] for c in rows])

# ---- 11.2 ------------------------------------------------------------------
print('11.2 missing figures')
res = pdf('# One\n\n~~~ figure\nA caption only.\n~~~\n')
check('a figure with no src is listed', '(no src)' in res['figures_missing'], res['figures_missing'])
ep = os.path.join(TMP, 'b.epub')
epub.build_epub(M.parse_markdown('# One\n\n~~~ figure src="absent-map.png"\nMap.\n~~~\n'),
                PRESET, ep, META)
rows = labels(epub.check(ep))
check('the EPUB check names the missing picture',
      'Figures' in rows and not rows['Figures']['ok'] and 'absent-map.png' in rows['Figures']['detail'],
      rows.get('Figures'))

# ---- 11.3 ------------------------------------------------------------------
print('11.3 pictures named for another format')
try:
    from PIL import Image
    bmp = os.path.join(TMP, 'map.upload.png')
    Image.new('RGB', (40, 30), (200, 10, 10)).save(bmp, format='BMP')
    problem = A._figure_problem(bmp)
    check('a BMP named .png is refused', problem and 'BMP' in problem, problem)
    good = os.path.join(TMP, 'map2.upload.png')
    Image.new('RGB', (40, 30), (200, 10, 10)).save(good, format='PNG')
    check('a real PNG passes', A._figure_problem(good) is None)
    # an EPUB that declares the wrong type
    bad = os.path.join(TMP, 'bad.epub')
    with zipfile.ZipFile(ep) as src, zipfile.ZipFile(bad, 'w') as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr('OEBPS/images/x.png', open(bmp, 'rb').read())
    # (the manifest needs the item for the check to look at it)
    with zipfile.ZipFile(bad) as z:
        opf_name = next(n for n in z.namelist() if n.endswith('.opf'))
        files = {n: z.read(n) for n in z.namelist()}
    opf = files[opf_name].decode('utf-8').replace(
        '</manifest>', '<item id="xbad" href="images/x.png" media-type="image/png"/></manifest>')
    files[opf_name] = opf.encode('utf-8')
    base = os.path.dirname(opf_name)
    if base and base != 'OEBPS':
        files[base + '/images/x.png'] = files.pop('OEBPS/images/x.png')
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), files.pop('mimetype'))
        for n, b in files.items():
            z.writestr(n, b, compress_type=zipfile.ZIP_DEFLATED)
    rows = labels(epub.check(bad))
    check('the EPUB check catches a BMP declared as PNG',
          'Picture formats' in rows and not rows['Picture formats']['ok'], rows.get('Picture formats'))
except ImportError:
    print('  skip (no Pillow)')

# ---- 11.4 ------------------------------------------------------------------
print('11.4 page background gone')
p = dict(PRESET, page_background={'image': 'gone-parchment-xyz.png', 'color': '', 'opacity': 1.0})
res = pdf('# One\n\nWords.\n', {'bleed': True}, p)
check('the missing background is in the result', res.get('page_background_missing') ==
      'gone-parchment-xyz.png', res.get('page_background_missing'))
rows = [c for c in A._preflight(res, p, res['page_count']) if c['label'] == 'Page background']
check('and preflight says so', rows and not rows[0]['ok'])

# ---- 11.5 ------------------------------------------------------------------
print('11.5 continuity on look-alike tokens')
import itertools, string
toks = ['Aabcdefghijkl' + ''.join(t) for t in itertools.islice(
    itertools.product(string.ascii_lowercase, repeat=3), 3000)]
md = '# One\n\n' + ' '.join(toks * 2) + '\n'
t0 = time.time()
issues = checker.run_tier1(M.parse_markdown(md))
check('the check ends promptly', time.time() - t0 < 60, round(time.time() - t0, 1))

# ---- 11.6 ------------------------------------------------------------------
print('11.6 fonts embedded')
res = pdf('# One\n\nHello.\n\n~~~ telegram\nMeet at dawn.\n~~~\n')
check('a telegram\'s Courier makes "fonts embedded" false',
      not res['fonts_embedded'] and any('Courier' in f for f in res['fonts_unembedded']),
      (res['fonts_embedded'], res.get('fonts_unembedded')))
res = pdf('# One\n\nHello.\n')
check('a plain book is still embedded', res['fonts_embedded'], res.get('fonts_unembedded'))

# ---- 11.7 ------------------------------------------------------------------
print('11.7 hardcover page range')
rows = labels(A._preflight(res, PRESET, 48, 'white', 'hardcover', 'kdp'))
check('48 pages fails for a KDP hardcover', not rows['Page count']['ok'], rows['Page count'])
rows = labels(A._preflight(res, PRESET, 48, 'white', 'paperback', 'kdp'))
check('48 pages passes for a paperback', rows['Page count']['ok'], rows['Page count'])

# ---- 11.9 / 11.10 ---------------------------------------------------------
print('11.9 / 11.10 previews')
form = {'preset': 'classic-literary', 'pasted': '# One\n\nWords.\n', 'title': 'Salt',
        'author': 'A', 'front_matter': 'none', 'cover_mode': 'designed',
        'cover_template': 'ashforge-house', 'smartquotes': 'on'}
with A.app.test_client() as c:
    plain = c.post('/generate/preview', data=form).get_json()
    press = c.post('/generate/preview', data=dict(form, press='on')).get_json()
    check('press-ready preview drops the cover page',
          plain['ok'] and press['ok'] and press['built_pages'] < plain['built_pages'],
          (plain.get('built_pages'), press.get('built_pages'), press.get('error')))
    j = c.post('/generate/epub-preview', data=form).get_json()
    shown = ' '.join(d.get('html', '') for d in j.get('docs', []))
    check('ebook preview carries the designed cover',
          j.get('ok') and re.search(r'<img[^>]+cover', shown, re.I) is not None,
          j.get('error'))

# ---- 11.11 -----------------------------------------------------------------
print('11.11 epubcheck that never finished')
import subprocess
orig_run, orig_jar, orig_which = subprocess.run, A._epubcheck_jar, A.shutil.which
try:
    A._epubcheck_jar = lambda: 'epubcheck.jar'
    A.shutil.which = lambda n: 'java'
    def boom(*a, **k):
        raise subprocess.TimeoutExpired('java', 120)
    subprocess.run = boom
    row = A._run_epubcheck(ep)
    check('the row is not a tick', row and not row['ok'], row)
finally:
    subprocess.run, A._epubcheck_jar, A.shutil.which = orig_run, orig_jar, orig_which

# ---- 11.12 / 11.13 / 11.14 -------------------------------------------------
print('11.12-11.14 continuity')
long = 'We hid the only key beneath the old stone bridge last night'
md = ('#* Prologue\n\nOnce.\n\n# Harbor\n\n“' + long + '.” She looked away.\n\n'
      '# Hill\n\n“' + long + '.” He laughed and left.\n\n'
      '# Map\n\n~~~ figure src="map.png"\n~~~\n')
issues = checker.run_tier1(M.parse_markdown(md))
text = ' | '.join(i['label'] + ' ' + i.get('detail', '') + ' ' + i.get('location', '')
                  for i in issues).replace(' ', ' ')
check('the repeated quoted sentence is found',
      any('Harbor' in (i.get('detail', '') + i.get('location', '')) for i in issues
          if 'epeat' in i['label'] or 'uplicate' in i['label']), text[:300])
check('Harbor is Chapter 1, not 2', 'Chapter 1 · “Harbor”' in text
      and 'Chapter 2 · “Harbor”' not in text, text[:300])
check('a picture-only chapter is not empty', not any('Empty chapter' in i['label'] and 'Map' in
                                                     i['label'] for i in issues))

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
