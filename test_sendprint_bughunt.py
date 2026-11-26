"""Joint bug hunt round 6, section 25: Send to print / Send to publish, re-checked.

(run: python test_sendprint_bughunt.py)

Each block names the finding it pins down. The retailer rules (25.5, 25.9,
25.10) were checked against KDP's trim-size and cover help pages and
IngramSpark's print file guidelines before they changed.
"""

import sys, os, io, json, shutil, tempfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine
import wrap_design
import fitz
from PIL import Image

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh25-')
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

MS = '# The Salt Road\n\nThe opening paragraph, long enough to set a line.\n\n# Two\n\nMore.\n'


def make_book(pid, **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(MS)
    data = dict(name=pid, title='The Salt Road', author='A. Writer', preset='classic-literary',
                format='pdf', manuscript_file=pid + '.md', manuscript_type='file',
                cover_file='', cover_mode='designed', cover_template='ashforge-house',
                created='2026-01-01T00:00:00', updated='2026-01-01T00:00:00',
                front_matter='none', print_retailer='kdp', print_binding='paperback',
                print_paper='white')
    data.update(over)
    A.save_project_file(pid, data)
    return data


def solid(path, rgb, size=(1800, 2700)):
    Image.new('RGB', size, rgb).save(path)


def unpack(zip_name):
    with zipfile.ZipFile(os.path.join(A.OUT_DIR, zip_name)) as z:
        return {n.split('/', 1)[1]: z.read(n) for n in z.namelist()}


def centre(jpg_bytes):
    with Image.open(io.BytesIO(jpg_bytes)) as im:
        return im.convert('RGB').getpixel((im.width // 2, im.height // 2))


try:
    # ------------------------------------------------------------------ 25.1
    print('25.1 a late package keeps off a newer one, and off another book')
    make_book('late', created='2026-01-01T00:00:00')
    newer = '2026-05-05T10:00:00.000000'
    older = '2026-05-05T09:00:00.000000'
    A._record_package('late', {'last_print_package': 'new.zip', 'last_page_count': 300},
                      newer, '2026-01-01T00:00:00')
    A._record_package('late', {'last_print_package': 'old.zip', 'last_page_count': 100},
                      older, '2026-01-01T00:00:00')
    p = A.load_project('late')
    check('the newer package stays on the shelf, with its page count',
          p.get('last_print_package') == 'new.zip' and p.get('last_page_count') == 300,
          {k: p.get(k) for k in ('last_print_package', 'last_page_count')})
    got = A._record_package('late', {'last_print_package': 'other.zip'},
                            '2026-06-01T00:00:00.000000', '1999-01-01T00:00:00')
    p = A.load_project('late')
    check('a package for a book since deleted lands nowhere',
          got is None and p.get('last_print_package') == 'new.zip', p.get('last_print_package'))
    A.update_project('late', {'build_started': '2026-07-01T00:00:00.000000',
                              'last_page_count': 444})
    A._record_package('late', {'last_print_package': 'p3.zip', 'last_page_count': 12},
                      '2026-06-15T00:00:00.000000', '2026-01-01T00:00:00')
    p = A.load_project('late')
    check('a build begun later keeps its page count; the package is still recorded',
          p.get('last_page_count') == 444 and p.get('last_print_package') == 'p3.zip',
          {k: p.get(k) for k in ('last_print_package', 'last_page_count')})

    # through the route: a book recreated under the id while the package built
    make_book('swap', created='2026-01-01T00:00:00')
    real = A.build_print_package

    def recreating(proj, scope='print'):
        info = real(proj, scope)
        make_book('swap', created='2026-09-09T00:00:00')     # deleted, and a new one made
        return info
    A.build_print_package = recreating
    try:
        r = c.post('/project/swap/print-package', data={'scope': 'print'})
    finally:
        A.build_print_package = real
    p = A.load_project('swap')
    check('the route does not hand the old book’s package to the new one',
          r.status_code == 200 and not p.get('last_print_package'), p.get('last_print_package'))

    # ------------------------------------------------------------------ 25.2
    print('25.2 one package, one revision of the uploaded cover')
    art = os.path.join(A.PROJECT_MS_DIR, 'cover-art.png')
    solid(art, (20, 40, 200))
    proj = make_book('art', cover_mode='image', cover_file='cover-art.png',
                     cover_template='')
    real_build = engine.build_pdf

    def replacing(ms, preset, out, meta, **kw):
        res = real_build(ms, preset, out, meta, **kw)
        if kw.get('press'):
            solid(art, (210, 20, 20))       # Edit replaces the file mid-package
        return res
    A.engine.build_pdf = replacing
    try:
        info = A.build_print_package(A.load_project('art'), 'publish')
    finally:
        A.engine.build_pdf = real_build
    files = unpack(info['zip_name'])
    jpg = [n for n in files if n.endswith('.jpg')]
    px = centre(files[jpg[0]]) if jpg else None
    check('the listing JPG has the art the package began with, not the replacement',
          px is not None and px[2] > 150 and px[0] < 100, px)
    wrap = [n for n in files if n.endswith('cover-wrap.pdf')]
    with fitz.open(stream=files[wrap[0]], filetype='pdf') as doc:
        pg = doc[0]
        pix = pg.get_pixmap(dpi=20, clip=fitz.Rect(pg.rect.width * 0.7, pg.rect.height * 0.4,
                                                   pg.rect.width * 0.8, pg.rect.height * 0.6))
        wpx = pix.pixel(pix.width // 2, pix.height // 2)
    check('and so does the front of the wrap', wpx[2] > 150 and wpx[0] < 100, wpx)

    # ------------------------------------------------------------------ 25.3 / 25.4
    print('25.3/25.4 a wrap design’s listing cover comes from this wrap')
    design = {'elements': [{'id': 'bg', 'type': 'rect', 'fill': 'sheet', 'color': '#1a6b2a'}]}
    make_book('wrapd', cover_mode='wrap', wrap_design=design,
              wrap_front_file='wrapd-wrap-front.jpg', last_page_count=100)
    seen = []
    real_front = wrap_design.render_front

    def recording(design, dims, out, dpi=300):
        seen.append(dims.get('pages'))
        return real_front(design, dims, out, dpi)

    def broken_cache(*a, **k):
        raise OSError('the cache JPG is locked by another program')
    real_cache = A._render_wrap_front
    A._render_wrap_front = broken_cache
    wrap_design.render_front = recording
    try:
        meta, _ = A._project_meta(A.load_project('wrapd'))
        check('(the failing cache leaves the book with no cover, as reported)',
              meta['cover_mode'] == 'none', meta['cover_mode'])
        info = A.build_print_package(A.load_project('wrapd'), 'publish')
    finally:
        A._render_wrap_front = real_cache
        wrap_design.render_front = real_front
    files = unpack(info['zip_name'])
    jpg = [n for n in files if n.endswith('.jpg')]
    px = centre(files[jpg[0]]) if jpg else None
    check('the listing JPG is the design’s front, not the dummy "# Cover" page',
          px is not None and px[1] > 80 and px[0] < 60, px)
    check('cut from a wrap of this interior’s page count, not the last build’s 100',
          seen and seen[-1] == A.bound_pages('kdp', info['pages']) and seen[-1] != 100,
          (seen, info['pages']))
    try:
        A._cover_page_jpeg(A.load_preset('classic-literary'),
                           dict(meta, cover_mode='none', cover_image=''),
                           os.path.join(TMP, 'none.jpg'))
        raised = False
    except ValueError:
        raised = True
    check('a book with no cover is not rasterised as one', raised)

    # ------------------------------------------------------------------ 25.5
    print('25.5 IngramSpark binds its barcode page')
    ppi = A._PAPER['white']['ppi']
    for n, bound in ((200, 202), (199, 200)):
        d = A._wrap_dims({'wrap_retailer': 'ingramspark', 'wrap_paper': 'white'}, n)
        check(f'{n} pages: the spine is sized for {bound}',
              abs(d['spine_w'] - bound * ppi) < 1e-9 and d['pages'] == bound, d['spine_w'])
    d = A._wrap_dims({'wrap_retailer': 'kdp', 'wrap_paper': 'white'}, 200)
    check('KDP still binds 200 as 200', abs(d['spine_w'] - 200 * ppi) < 1e-9)
    spec = A._print_spec_text({
        'title': 'T', 'author': '', 'retailer': 'ingramspark', 'retailer_label': 'IngramSpark',
        'binding': 'paperback', 'trim_w': 6, 'trim_h': 9, 'pages': 200, 'paper_label': 'White',
        'wrap': {'spine_w': 0.45, 'wrap_w': 12.7, 'wrap_h': 9.25, 'spine_text': True},
        'bleed': 0.125, 'press_ready': True, 'checks': [], 'press': None}, ['a.pdf'])
    check('the sheet says how many pages are bound', 'bound as 202' in spec, spec[:500])

    # ------------------------------------------------------------------ 25.6
    print('25.6 the back photo stays clear of the barcode box')
    back = os.path.join(TMP, 'back.png')
    solid(back, (200, 30, 30), (1200, 1200))
    solid(art, (20, 40, 200))
    preset = A.load_preset('classic-literary')
    meta = {'title': 'T', 'author': 'A', 'cover_mode': 'image', 'cover_image': art,
            'cover_back_image': back, 'cover_back_image_w': 4.0, 'cover_back_image_y': 0.05}
    dims = A._wrap_dims({}, 300)
    dims.pop('warnings', None)
    out = os.path.join(TMP, 'wrap-photo.pdf')
    engine.build_cover_wrap(engine.image_wrap_template(art), engine.image_cover_fonts(preset),
                            meta, dims, out)
    with fitz.open(out) as doc:
        pg = doc[0]
        boxes = [d['rect'] for d in pg.get_drawings()
                 if d.get('fill') and min(d['fill']) > 0.99
                 and abs(d['rect'].width - 144) < 1 and abs(d['rect'].height - 86.4) < 1]
        imgs = [fitz.Rect(i['bbox']) for i in pg.get_image_info()
                if fitz.Rect(i['bbox']).x1 < pg.rect.width / 2]
    hit = [b for b in boxes for im in imgs if (b & im).get_area() > 1]
    check('the photo and the barcode box do not overlap',
          boxes and imgs and not hit, (boxes, imgs))

    # ------------------------------------------------------------------ 25.7
    print('25.7 the designer’s warnings reach the package')
    g = engine.wrap_geometry(A._wrap_dims({}, 300))
    bad = {'elements': [
        {'id': 'b', 'type': 'barcode', 'anchor': 'back', 'x': 1, 'y': 6, 'w': 2, 'h': 1.2,
         'isbn': '978-0-00-000000-1'},
        {'id': 'r', 'type': 'rect', 'anchor': 'sheet', 'x': g['edge'], 'y': 1, 'w': 2, 'h': 1,
         'color': '#000000'}]}
    warns = wrap_design.print_warnings(bad, g)
    check('a wrong ISBN check digit is warned of', any('check digit' in w for w in warns), warns)
    check('a shape stopping at the trim is warned of', any('short of the bleed' in w for w in warns),
          warns)
    good = {'elements': [
        {'id': 'b', 'type': 'barcode', 'anchor': 'back', 'x': 1, 'y': 6, 'w': 2, 'h': 1.2,
         'isbn': '978-0-306-40615-7'},
        {'id': 'f', 'type': 'rect', 'fill': 'sheet', 'color': '#000000'}]}
    check('a good design has none', wrap_design.print_warnings(good, g) == [],
          wrap_design.print_warnings(good, g))
    make_book('badwrap', cover_mode='wrap', wrap_design=bad, wrap_front_file='badwrap-front.jpg')
    info = A.build_print_package(A.load_project('badwrap'), 'print')
    check('and the package carries them',
          sum(1 for ch in info['checks'] if ch['label'] == 'Cover design') == 2,
          [ch for ch in info['checks'] if ch['label'] == 'Cover design'])

    # ------------------------------------------------------------------ 25.8
    print('25.8 the inside margin is checked in the package')
    rows = [ch for ch in info['checks'] if ch['label'] == 'Inside margin']
    check('a KDP package has an inside-margin row', len(rows) == 1 and 'KDP' in rows[0]['detail'],
          rows)
    A.save_preset('narrow', dict(A.load_preset('classic-literary'),
                                 margins=dict(A.load_preset('classic-literary')['margins'],
                                              inside=0.2)))
    make_book('narrow', preset='narrow')
    info = A.build_print_package(A.load_project('narrow'), 'print')
    rows = [ch for ch in info['checks'] if ch['label'] == 'Inside margin']
    check('and a margin under KDP’s minimum fails it', rows and not rows[0]['ok'], rows)

    # ------------------------------------------------------------------ 25.9
    print('25.9 KDP’s page limits by trim')
    for paper, w, h, want in (('white', 7, 10, 828), ('white', 8, 10, 828),
                              ('white', 6.14, 9.21, 828), ('cream', 7.5, 9.25, 776),
                              ('white', 8.25, 8.25, 800), ('white', 8.27, 11.69, 780),
                              ('white', 8.5, 11, 590), ('cream', 8.5, 8.5, 550),
                              ('color', 7, 10, 828), ('color_standard', 8.5, 11, 600)):
        got = A.kdp_page_range(paper, w, h)[1]
        check(f'{w}x{h} on {paper}: {want} pages', got == want, got)

    # ------------------------------------------------------------------ 25.10
    print('25.10 KDP spine text')
    check('KDP allows spine text from 80 pages', A.WRAP_RETAILERS['kdp']['spine_text_min'] == 80)
    g90 = engine.wrap_geometry(A._wrap_dims({'wrap_retailer': 'kdp'}, 90))
    check('so a 90-page KDP paperback may carry it', g90['spine_text'], g90.get('spine_text'))

    # ------------------------------------------------------------------ 25.11
    print('25.11 the ZIP appears whole or not at all')
    real_zip = zipfile.ZipFile.write

    def dying(self, *a, **k):
        raise KeyboardInterrupt('forced close')
    zipfile.ZipFile.write = dying
    try:
        try:
            A.build_print_package(A.load_project('narrow'), 'print')
        except KeyboardInterrupt:
            pass
    finally:
        zipfile.ZipFile.write = real_zip
    left = [f for f in os.listdir(A.OUT_DIR) if f.startswith('the-salt-road-print-')]
    before = set(left)
    check('nothing is left under a package name, whole or part',
          not any(f.endswith('.part') for f in left)
          and all(os.path.getsize(os.path.join(A.OUT_DIR, f)) > 0 for f in left), left)
    # what a forced close does leave: the part file and the empty name; the sweep
    stale = os.path.join(A.OUT_DIR, 'x-print-20260101-000000.zip')
    open(stale, 'wb').close()
    with open(stale + '.part', 'wb') as f:
        f.write(b'PK')
    A._sweep_stale(now=time.time() + 7 * 3600)
    check('the start-up sweep removes them', not os.path.exists(stale)
          and not os.path.exists(stale + '.part'))

    # ------------------------------------------------------------------ 25.12
    print('25.12 the page and the sheet describe what shipped')
    real_jpg = A._cover_page_jpeg

    def no_jpg(*a, **k):
        raise RuntimeError('render failed')
    A._cover_page_jpeg = no_jpg
    try:
        r = c.post('/project/art/print-package', data={'scope': 'publish'})
    finally:
        A._cover_page_jpeg = real_jpg
    html = r.get_data(as_text=True)
    zn = A.load_project('art')['last_print_package']
    spec = unpack(zn)['PUBLISH-SPEC.txt'].decode('utf-8')
    check('the header does not promise a shared cover image',
          'one\n         cover image serving' not in html and 'could not be rendered' in html)
    check('the sheet does not say to upload a JPG that is not there',
          'upload the cover JPG' not in spec and 'no cover JPG here' in spec, spec[-900:])

    # ------------------------------------------------------------------ 25.13
    print('25.13 template downloads are named for their size')
    names = set()
    for paper in ('white', 'cream'):
        r = c.get(f'/style/classic-literary/cover-specs/template.pdf?pages=200&paper={paper}')
        names.add(r.headers.get('Content-Disposition', ''))
    check('white and cream templates have different names', len(names) == 2, names)

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print(f'{len(fails)} FAILED:')
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('all passed')
