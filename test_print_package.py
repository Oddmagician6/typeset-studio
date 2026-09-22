"""Send-to-print package tests  (run: python test_print_package.py).

The package exists to stop one mistake: a cover wrap cut for a different page
count than the interior inside it. So these build a real project end to end and
measure the files — the interior carries no cover, and the wrap's width is the
retailer formula evaluated at *that* interior's page count.

The publish package (#67) is the same build with the ebook edition added, so the
checks there are the ones that could drift: that both editions came out of the
one pass, that the cover in the EPUB is the JPG in the zip, and that the ebook's
own checks reach the sheet a writer sends on.
"""

import sys, os, re, io, zipfile, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import engine, manuscript
import app as A
import fitz

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


PID = '_test_print_package'
MS_PATH = os.path.join(A.PROJECT_MS_DIR, PID + '.md')
# Background art for a designed cover: the plate the template is drawn over, with
# no title or author on it. It exists here to prove it never leaves as a cover.
ART_NAME = '_test_print_package_art.png'
ART_PATH = os.path.join(A.PROJECT_MS_DIR, ART_NAME)
# secure_filename strips the leading underscore, so that is the id on disk and in links
FILE_ID = A.secure_filename(PID)
PROJ_JSON = os.path.join(A.PROJECT_DIR, FILE_ID + '.json')
MS = ('# The Salt Road\n\nThe opening paragraph, long enough to set a real line of '
      'body text across the measure.\n\n# The Second Mile\n\nAnother chapter, so the '
      'book has more than one opening in it.\n')
PROJ = {'name': 'Print test', 'preset': 'classic-literary', 'title': 'The Salt Road',
        'author': 'Ellinor Vale', 'manuscript_file': PID + '.md',
        'manuscript_type': 'file', 'front_matter': 'full',
        'cover_mode': 'designed', 'cover_template': 'ashforge-house',
        'print_retailer': 'kdp', 'print_binding': 'paperback', 'print_paper': 'cream',
        'print_blurb': 'A road of salt, and the woman who walked it.'}


def cleanup():
    for p in (MS_PATH, PROJ_JSON, ART_PATH):
        if os.path.exists(p):
            os.remove(p)
    for f in os.listdir(A.OUT_DIR):
        if (f.startswith('the-salt-road-print-') or f.startswith('taiga-press-print-')
                or f.startswith('the-salt-road-publish-')) and f.endswith('.zip'):
            os.remove(os.path.join(A.OUT_DIR, f))


def send(proj, scope='print'):
    A.save_project_file(PID, proj)
    return client.post(f'/project/{PID}/print-package', data={'scope': scope},
                       follow_redirects=True)


def unpack(zip_name):
    """{name: bytes} for a package, with the folder prefix stripped."""
    with zipfile.ZipFile(os.path.join(A.OUT_DIR, zip_name)) as z:
        return {n.split('/', 1)[1]: z.read(n) for n in z.namelist()}


def pdf_info(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return doc.page_count, doc[0].rect.width / 72.0, doc[0].rect.height / 72.0


cleanup()
A.app.config['TESTING'] = True
client = A.app.test_client()
preset = A.load_preset('classic-literary')
tw, th = preset['trim']['w'], preset['trim']['h']
try:
    with open(MS_PATH, 'w', encoding='utf-8') as f:
        f.write(MS)

    # ------------------------------------------------------------ paperback
    print('a paperback package')
    r = send(dict(PROJ))
    html = r.get_data(as_text=True)
    check('it builds', r.status_code == 200 and 'Ready for the printer' in html, r.status_code)
    saved = A.load_project(PID)
    zip_name = saved.get('last_print_package', '')
    check('and the project remembers it', zip_name.endswith('.zip'), saved)
    files = unpack(zip_name)
    check('with the four files a printer handoff needs',
          sorted(files) == sorted(['the-salt-road-interior.pdf',
                                   'the-salt-road-cover-wrap.pdf',
                                   'the-salt-road-front-cover.jpg', 'PRINT-SPEC.txt']),
          sorted(files))

    pages, iw, ih = pdf_info(files['the-salt-road-interior.pdf'])
    check('the interior is the trim size', abs(iw - tw) < 0.01 and abs(ih - th) < 0.01,
          (iw, ih))
    meta, _ = A._project_meta(saved)
    fd, plain = tempfile.mkstemp(suffix='.pdf'); os.close(fd)
    try:
        ms = manuscript.parse_markdown(MS, smartquotes=True)
        coverless = engine.build_pdf(ms, preset, plain,
                                     dict(meta, cover_mode='none', cover_template_data=None))
    finally:
        os.remove(plain)
    check('the interior carries no cover', pages == coverless['page_count'],
          (pages, coverless['page_count']))
    check('and the page count is saved for the cover editor',
          saved.get('last_page_count') == pages, saved.get('last_page_count'))

    _, ww, wh = pdf_info(files['the-salt-road-cover-wrap.pdf'])
    want_w = 2 * 0.125 + 2 * tw + pages * A._PAPER['cream']['ppi']
    check('the wrap is sized from that page count, on that paper',
          abs(ww - want_w) < 0.01, (ww, want_w))
    check('and is trim plus bleed tall', abs(wh - (th + 0.25)) < 0.01, wh)

    spec = files['PRINT-SPEC.txt'].decode('utf-8')
    check('the spec sheet states the pages and spine',
          f'Pages        {pages}' in spec
          and f'{pages * A._PAPER["cream"]["ppi"]:.4f} in' in spec, spec[:400])
    check('and walks through the KDP upload', 'Upload a cover you already have' in spec)
    check('a short book is told its spine is blank, not failed',
          'Spine text' in html and 'under Amazon KDP' in html)

    # ------------------------------------------------------------ hardcover
    print('a hardcover package')
    r = send(dict(PROJ, print_binding='hardcover', print_retailer='kdp'))
    html = r.get_data(as_text=True)
    files = unpack(A.load_project(PID)['last_print_package'])
    check('the wrap is named for a case', 'the-salt-road-case-wrap.pdf' in files, sorted(files))
    _, ww, _ = pdf_info(files['the-salt-road-case-wrap.pdf'])
    H = A.HARDCOVER
    want_w = (2 * (H['wrap'] + 0.125) + 2 * tw + 2 * H['hinge']
              + pages * A._PAPER['cream']['ppi'] + H['board'])
    check('its width takes the turn-in, hinges and board', abs(ww - want_w) < 0.01,
          (ww, want_w))
    check('KDP’s hardcover limits are flagged, not enforced',
          'white paper only' in html and 'Download package' in html)

    # --------------------------------------------------- the colour fallback
    # A book the CMYK canvas refuses still has to come out coverless: the wrap
    # in the same zip is cut from whatever page count the interior reports, so
    # a cover page smuggled back in would thicken the spine by a leaf or two.
    print('when the press build falls back to RGB')
    real = engine._build_pdf

    def refuse_colour(ms_, preset_, out_, meta_, press=False):
        if press:
            raise ValueError('cannot convert color to CMYK: chromatic')
        return real(ms_, preset_, out_, meta_)

    engine._build_pdf = refuse_colour
    try:
        r = send(dict(PROJ))
        html = r.get_data(as_text=True)
        fb = unpack(A.load_project(PID)['last_print_package'])
        fb_pages, _, _ = pdf_info(fb['the-salt-road-interior.pdf'])
    finally:
        engine._build_pdf = real
    check('the fallback interior still carries no cover', fb_pages == pages,
          (fb_pages, pages))
    _, fb_ww, _ = pdf_info(fb['the-salt-road-cover-wrap.pdf'])
    check('so its wrap is the one the press-ready build would have had',
          abs(fb_ww - (2 * 0.125 + 2 * tw + pages * A._PAPER['cream']['ppi'])) < 0.01,
          fb_ww)
    check('and the page says why it is RGB', 'Ordinary RGB' in html)

    # ----------------------------------------------------------- the tallies
    # The browser and the sheet inside the zip count the same rows, or a writer
    # reads "all clear" on screen and "1 to look at" in the file they send on.
    print('the checks add up the same way twice')
    r = send(dict(PROJ))
    html = r.get_data(as_text=True)
    files = unpack(A.load_project(PID)['last_print_package'])
    spec = files['PRINT-SPEC.txt'].decode('utf-8')
    on_page = re.search(r'badge-warn">\s*(\d+) to look at', html)
    in_spec = re.search(r'CHECKS \((\d+) to look at\)', spec)
    check('the page and the spec sheet agree',
          (on_page.group(1) if on_page else None) == (in_spec.group(1) if in_spec else None),
          (html.count('badge-ok'), in_spec.group(0) if in_spec else 'all clear'))
    check('the output intent reads as a note, not a fault',
          '[--] Output intent' in spec
          and int(in_spec.group(1)) == spec.count('[!!]'), in_spec.group(0))

    # ------------------------------------------------------- what it is named
    print('naming')
    r = send(dict(PROJ, title='Тайга', name='Taiga Press'))
    named = A.load_project(PID)['last_print_package']
    check('a title with no ASCII in it falls back to the project name',
          named.startswith('taiga-press-print-'), named)
    os.remove(os.path.join(A.OUT_DIR, named))

    # ------------------------------------------------------ publish package
    # The point of the publish package is that one build makes both editions,
    # so what is worth measuring is that they agree: the same manuscript, the
    # same cover, and the print half unchanged from the print-only package.
    print('a publish package')
    r = send(dict(PROJ), 'publish')
    html = r.get_data(as_text=True)
    check('it builds', r.status_code == 200
          and 'Ready for the printer and the shop' in html, r.status_code)
    zip_name = A.load_project(PID).get('last_print_package', '')
    check('and is named for what it is', '-publish-' in zip_name, zip_name)
    check('the project remembers which kind it was',
          A.load_project(PID).get('last_package_scope') == 'publish')
    pub = unpack(zip_name)
    check('the two editions are sorted into folders',
          sorted(pub) == sorted(['print/the-salt-road-interior.pdf',
                                 'print/the-salt-road-cover-wrap.pdf',
                                 'ebook/the-salt-road.epub',
                                 'ebook/the-salt-road-cover.jpg',
                                 'PUBLISH-SPEC.txt']), sorted(pub))

    pub_pages, _, _ = pdf_info(pub['print/the-salt-road-interior.pdf'])
    check('the print half is the same interior as a print-only package',
          pub_pages == pages, (pub_pages, pages))
    _, pub_ww, _ = pdf_info(pub['print/the-salt-road-cover-wrap.pdf'])
    check('cut to the same wrap',
          abs(pub_ww - (2 * 0.125 + 2 * tw + pages * A._PAPER['cream']['ppi'])) < 0.01,
          pub_ww)

    # one rasterisation, two uses: a second render could differ, and then the
    # shop listing and the file readers open would not be the same picture
    with zipfile.ZipFile(io.BytesIO(pub['ebook/the-salt-road.epub'])) as ez:
        names = ez.namelist()
        inside = [n for n in names if n.lower().endswith(('.jpg', '.jpeg'))]
        cover_bytes = ez.read(inside[0]) if inside else b''
        opf = next((ez.read(n).decode('utf-8') for n in names if n.endswith('.opf')), '')
    check('the ebook carries a cover', bool(inside), names)
    check('and it is byte-for-byte the JPG in the zip',
          cover_bytes == pub['ebook/the-salt-road-cover.jpg'],
          (len(cover_bytes), len(pub['ebook/the-salt-road-cover.jpg'])))
    check('declared the way Kindle tooling wants', 'name="cover"' in opf)
    check('the book itself is in there',
          sum(1 for n in names if n.endswith('.xhtml')) >= 2, names)

    spec = pub['PUBLISH-SPEC.txt'].decode('utf-8')
    check('the sheet covers both uploads',
          'UPLOADING THE PRINT EDITION' in spec and 'UPLOADING THE EBOOK EDITION' in spec
          and 'Kindle eBook Content page' in spec, spec[-400:])
    check('and states the ebook cover in pixels',
          re.search(r'Ebook cover\s+\d+x2560 px JPEG', spec) is not None,
          [l for l in spec.splitlines() if 'Ebook' in l])
    check('the ebook checks travel with it',
          'EBOOK CHECKS' in spec and 'Accessibility metadata' in spec)

    # the same tally rule as the print package: the page and the sheet count
    # the same rows, ebook ones included
    on_page = re.search(r'Ebook checks</span>\s*\n?\s*<span class="badge badge-(ok|warn)">'
                        r'\s*(?:(\d+) to look at|All clear)', html)
    in_spec = re.search(r'EBOOK CHECKS \((\d+) to look at\)', spec)
    check('the ebook tallies agree on the page and in the sheet',
          (on_page.group(2) if on_page else None) == (in_spec.group(1) if in_spec else None),
          (on_page.group(0) if on_page else 'no card', in_spec.group(0) if in_spec else 'all clear'))

    # forced, because a book we build ourselves passes every ebook check: the
    # tally has to survive a failing row, which is the only time it is read
    print('when an ebook check fails')
    real_check = A.epub.check
    A.epub.check = lambda path: [{'label': 'Spine', 'ok': False, 'detail': 'Invented fault'}]
    try:
        r = send(dict(PROJ), 'publish')
        html = r.get_data(as_text=True)
        spec = unpack(A.load_project(PID)['last_print_package'])['PUBLISH-SPEC.txt'].decode('utf-8')
    finally:
        A.epub.check = real_check
    check('the page counts it', 'Ebook checks' in html and 'Invented fault' in html
          and re.search(r'badge-warn">\s*1 to look at', html) is not None)
    check('and the sheet counts the same one',
          'EBOOK CHECKS (1 to look at)' in spec and '[!!] Spine: Invented fault' in spec,
          [l for l in spec.splitlines() if 'EBOOK' in l])

    print('a publish package whose ebook will not build')
    real_epub = A.epub.build_epub

    def refuse_epub(*a, **k):
        raise ValueError('no ebook today')

    A.epub.build_epub = refuse_epub
    try:
        r = send(dict(PROJ), 'publish')
        html = r.get_data(as_text=True)
        broke = unpack(A.load_project(PID)['last_print_package'])
    finally:
        A.epub.build_epub = real_epub
    check('the print files still ship',
          'print/the-salt-road-interior.pdf' in broke
          and 'print/the-salt-road-cover-wrap.pdf' in broke, sorted(broke))
    check('and the page says the ebook is the part that failed',
          'no ebook today' in html and 'print files' in html)

    # a package that promises an edition it does not contain is worse than one
    # that admits it shipped half: the sheet is what a writer works from
    broke_spec = broke['PUBLISH-SPEC.txt'].decode('utf-8')
    check('the sheet does not offer an ebook that is not in the zip',
          'UPLOADING THE EBOOK EDITION' not in broke_spec
          and 'EPUB 3, reflowable' not in broke_spec
          and 'the cover inside the EPUB' not in broke_spec,
          [l for l in broke_spec.splitlines() if 'EPUB' in l or 'EBOOK' in l])
    check('and it walks through the one upload there is',
          'UPLOADING' in broke_spec and 'UPLOADING THE' not in broke_spec
          and 'upload the interior PDF' in broke_spec,
          [l for l in broke_spec.splitlines() if 'UPLOAD' in l])
    check('the page does not claim one either',
          'EPUB 3, reflowable' not in html and 'Ready for the printer and the shop' not in html
          and 'the ebook edition could not be built' in html.lower())

    print('a publish package whose cover will not render')
    with open(ART_PATH, 'wb') as f:
        from PIL import Image
        Image.new('RGB', (600, 900), (30, 60, 90)).save(f, 'PNG')
    real_jpeg = A._cover_page_jpeg

    def refuse_cover(*a, **k):
        raise RuntimeError('no cover today')

    A._cover_page_jpeg = refuse_cover
    try:
        r = send(dict(PROJ, cover_file=ART_NAME), 'publish')
        html = r.get_data(as_text=True)
        nocov = unpack(A.load_project(PID)['last_print_package'])
    finally:
        A._cover_page_jpeg = real_jpeg
    check('the ebook still ships', 'ebook/the-salt-road.epub' in nocov, sorted(nocov))
    with zipfile.ZipFile(io.BytesIO(nocov['ebook/the-salt-road.epub'])) as ez:
        pics = [n for n in ez.namelist() if n.lower().endswith(('.jpg', '.jpeg', '.png'))]
    # the project's background plate carries no title: it is not a cover, and a
    # row saying the ebook has none must not be contradicted by the file itself
    check('without the cover art smuggled in as its cover', pics == [], pics)
    check('and the row says so', 'was built without one' in html)
    nocov_spec = nocov['PUBLISH-SPEC.txt'].decode('utf-8')
    check('the sheet says so too', 'Ebook cover  not rendered' in nocov_spec,
          [l for l in nocov_spec.splitlines() if 'Ebook' in l])

    print('when the ebook cannot be checked at all')
    A.epub.check = lambda path: (_ for _ in ()).throw(RuntimeError('checker down'))
    try:
        r = send(dict(PROJ), 'publish')
        html = r.get_data(as_text=True)
        spec = unpack(A.load_project(PID)['last_print_package'])['PUBLISH-SPEC.txt'].decode('utf-8')
    finally:
        A.epub.check = real_check
    check('the card does not quietly disappear',
          'Ebook checks' in html and 'nothing here vouches for it' in html
          and re.search(r'badge-warn">\s*1 to look at', html) is not None)
    check('and the sheet counts it as outstanding',
          'EBOOK CHECKS (1 to look at)' in spec
          and '[!!] Ebook checks:' in spec,
          [l for l in spec.splitlines() if 'EBOOK' in l or 'Ebook checks' in l])

    # ------------------------------------------------- uploaded cover art (#66)
    # The art is the front panel and the rest of the wrap is built around it, so
    # what is worth measuring is where the art stops: it has to reach the outer
    # edge of the sheet (bleed included) and no further than the front fold.
    print('a package around uploaded cover art')
    from PIL import Image
    ART = (206, 41, 58)
    g = engine.wrap_geometry({'trim_w': tw, 'trim_h': th, 'bleed': 0.125,
                              'spine_w': pages * A._PAPER['cream']['ppi'],
                              'binding': 'paperback'})
    aw, ah = engine.front_art_size(g)
    Image.new('RGB', (int(aw * 300), int(ah * 300)), ART).save(ART_PATH, 'PNG')
    IMG_PROJ = dict(PROJ, cover_mode='image', cover_file=ART_NAME,
                    cover_template='', cover_overlay=True, cover_color='light')
    r = send(dict(IMG_PROJ))
    html = r.get_data(as_text=True)
    check('it builds', r.status_code == 200 and 'Ready for the printer' in html,
          r.status_code)
    art_files = unpack(A.load_project(PID)['last_print_package'])
    check('with the same four files as a designed cover',
          sorted(art_files) == sorted(['the-salt-road-interior.pdf',
                                       'the-salt-road-cover-wrap.pdf',
                                       'the-salt-road-front-cover.jpg',
                                       'PRINT-SPEC.txt']), sorted(art_files))
    art_pages, _, _ = pdf_info(art_files['the-salt-road-interior.pdf'])
    check('the interior is still coverless, so the spine is still honest',
          art_pages == pages, (art_pages, pages))
    _, aww, awh = pdf_info(art_files['the-salt-road-cover-wrap.pdf'])
    paperback_w = 2 * 0.125 + 2 * tw + pages * A._PAPER['cream']['ppi']
    check('and the wrap is the size it would have been with a template',
          abs(aww - paperback_w) < 0.01 and abs(awh - (th + 0.25)) < 0.01, (aww, awh))

    with fitz.open(stream=art_files['the-salt-road-cover-wrap.pdf'],
                   filetype='pdf') as doc:
        DPI = 36
        pm = doc[0].get_pixmap(dpi=DPI)
        text = doc[0].get_text()

    def at(x_in, y_in):
        """Colour at a point on the wrap, measured in inches from the top-left."""
        return pm.pixel(min(int(x_in * DPI), pm.width - 1),
                        min(int(y_in * DPI), pm.height - 1))

    def near(c, want, tol=12):
        return all(abs(a - b) <= tol for a, b in zip(c[:3], want))

    check('the front panel is the art', near(at(g['front_x'] + tw / 2, 0.75), ART),
          at(g['front_x'] + tw / 2, 0.75))
    check('which runs out into the bleed at the fore-edge and the head',
          near(at(g['wrap_w'] - 0.05, th / 2), ART) and near(at(g['front_x'] + 0.5, 0.03), ART),
          (at(g['wrap_w'] - 0.05, th / 2), at(g['front_x'] + 0.5, 0.03)))
    check('and stops at the spine, so the back panel is not the art',
          not near(at(g['back_x'] + tw / 2, th / 2), ART),
          at(g['back_x'] + tw / 2, th / 2))
    check('the back panel takes its colour from the art',
          at(g['back_x'] + tw / 2, th / 2)[0] > at(g['back_x'] + tw / 2, th / 2)[2],
          at(g['back_x'] + tw / 2, th / 2))
    # this book is too short for spine text, so the only title on the sheet is
    # the overlay one — which is how we know the overlay reached the wrap
    check('the title overlay is drawn on the front panel', 'The Salt Road' in text,
          text[:200])
    r = send(dict(IMG_PROJ, cover_overlay=False))
    with fitz.open(stream=unpack(A.load_project(PID)['last_print_package'])
                   ['the-salt-road-cover-wrap.pdf'], filetype='pdf') as doc:
        plain_text = doc[0].get_text()
    check('and left off when the writer turned it off', 'The Salt Road' not in plain_text,
          plain_text[:200])

    art_spec = art_files['PRINT-SPEC.txt'].decode('utf-8')
    check('the sheet says the cover is the writer’s own art, at its resolution',
          'Cover        Uploaded art' in art_spec and ' dpi on the front panel)' in art_spec,
          [l for l in art_spec.splitlines() if 'Cover' in l])
    check('and the page says so too', 'Uploaded art' in html and 'dpi on the front' in html)
    check('the resolution passes at 300 dpi',
          re.search(r'Cover art[^<]*</span>\s*<span class="chk-detail">[^<]*300 dpi', html)
          is not None or '300 dpi across the' in html,
          [l for l in art_spec.splitlines() if 'Cover art' in l])

    # too small is the failure this check exists for: it only shows up in print
    print('when the art is too small for the panel')
    Image.new('RGB', (900, 1350), ART).save(ART_PATH, 'PNG')
    r = send(dict(IMG_PROJ))
    html = r.get_data(as_text=True)
    small = unpack(A.load_project(PID)['last_print_package'])
    small_spec = small['PRINT-SPEC.txt'].decode('utf-8')
    check('the wrap still ships', 'the-salt-road-cover-wrap.pdf' in small, sorted(small))
    check('and the row says how soft it will print, in pixels',
          'will print soft' in html and '900×1350 px' in html,
          [l for l in small_spec.splitlines() if 'Cover art' in l])
    check('the sheet counts it as an issue like any other',
          '[!!] Cover art:' in small_spec, [l for l in small_spec.splitlines()
                                            if 'Cover art' in l])
    on_page = re.search(r'badge-warn">\s*(\d+) to look at', html)
    in_spec = re.search(r'CHECKS \((\d+) to look at\)', small_spec)
    check('and the page and the sheet still agree on the tally',
          (on_page.group(1) if on_page else None) == (in_spec.group(1) if in_spec else None),
          (on_page.group(0) if on_page else 'none', in_spec.group(0) if in_spec else 'none'))

    print('a publish package around uploaded cover art')
    Image.new('RGB', (int(aw * 300), int(ah * 300)), ART).save(ART_PATH, 'PNG')
    r = send(dict(IMG_PROJ), 'publish')
    pub_art = unpack(A.load_project(PID)['last_print_package'])
    check('both editions come out of it',
          'print/the-salt-road-cover-wrap.pdf' in pub_art
          and 'ebook/the-salt-road.epub' in pub_art, sorted(pub_art))
    with zipfile.ZipFile(io.BytesIO(pub_art['ebook/the-salt-road.epub'])) as ez:
        inside = [n for n in ez.namelist() if n.lower().endswith(('.jpg', '.jpeg'))]
        cover_bytes = ez.read(inside[0]) if inside else b''
    # the rasterised cover page, not the raw upload: that one has no title on it
    check('and the ebook carries the rendered cover, not the raw upload',
          bool(inside) and cover_bytes == pub_art['ebook/the-salt-road-cover.jpg']
          and cover_bytes != open(ART_PATH, 'rb').read(), (len(cover_bytes), inside))

    # The overlay is one painter in two places; it has to be one face as well.
    with fitz.open(stream=pub_art['print/the-salt-road-cover-wrap.pdf'],
                   filetype='pdf') as doc:
        wrap_faces = {s['text']: s['font'] for b in doc[0].get_text('dict')['blocks']
                      for l in b.get('lines', []) for s in l['spans']}
    from reportlab.pdfbase import pdfmetrics
    book_fonts = engine.register_fonts(A.load_preset(PROJ['preset']))
    face = lambda role: pdfmetrics.getFont(book_fonts[role]).face.name.decode()
    check('the wrap’s title is set in the book’s own faces, as page 1 is',
          wrap_faces.get('The Salt Road') == face('bold')
          and wrap_faces.get('Ellinor Vale') == face('regular'),
          (wrap_faces, face('bold'), face('regular')))

    # A phone photo stored sideways with an EXIF turn: upright in the browser,
    # so it has to be upright on the book too — blue at the head, red at the foot.
    print('when the art is a phone photo stored on its side')
    BLUE, RED = (30, 40, 200), (200, 30, 40)
    turned = Image.new('RGB', (int(ah * 300), int(aw * 300)), RED)
    turned.paste(BLUE, (0, 0, turned.width // 2, turned.height))
    ex = Image.Exif()
    ex[0x0112] = 6                       # stored a quarter-turn anticlockwise
    turned.save(ART_PATH, 'JPEG', exif=ex.tobytes())
    r = send(dict(IMG_PROJ, cover_overlay=False))
    html = r.get_data(as_text=True)
    side = unpack(A.load_project(PID)['last_print_package'])
    with fitz.open(stream=side['the-salt-road-cover-wrap.pdf'], filetype='pdf') as doc:
        pm = doc[0].get_pixmap(dpi=DPI)
    check('the front panel is printed the way up the writer sees it',
          near(at(g['front_x'] + tw / 2, 1.0), BLUE, 30)
          and near(at(g['front_x'] + tw / 2, th - 1.0), RED, 30),
          (at(g['front_x'] + tw / 2, 1.0), at(g['front_x'] + tw / 2, th - 1.0)))
    front = Image.open(io.BytesIO(side['the-salt-road-front-cover.jpg'])).convert('RGB')
    check('and so is the cover page',
          near(front.getpixel((front.width // 2, front.height // 8)), BLUE, 30)
          and near(front.getpixel((front.width // 2, front.height * 7 // 8)), RED, 30),
          (front.getpixel((front.width // 2, front.height // 8)),
           front.getpixel((front.width // 2, front.height * 7 // 8))))
    check('and its resolution is measured upright, so it is not flagged soft',
          'will print soft' not in html and '300 dpi across the' in html,
          re.findall(r'[^>]*dpi[^<]*', html)[:3])

    # A project's standalone EPUB export takes the same cover the package does.
    Image.new('RGB', (int(aw * 300), int(ah * 300)), ART).save(ART_PATH, 'PNG')
    ometa, _ = A._project_meta(dict(IMG_PROJ))
    with A._epub_cover(A.load_preset(PROJ['preset']), ometa) as emeta:
        check('an exported EPUB carries the rendered cover page, overlay and all',
              emeta['cover_image'] != ART_PATH and emeta['cover_image'].endswith('.jpg'),
              emeta['cover_image'])
    nmeta, npath = A._project_meta(dict(IMG_PROJ, cover_mode='none'))
    check('and a project set to No cover does not use the art it still keeps',
          nmeta['cover_image'] == '' and npath == '', (nmeta['cover_image'], npath))
    os.remove(ART_PATH)

    # ------------------------------------------------------------ refusals
    print('what it refuses')
    r = send(dict(PROJ, cover_mode='none'))
    check('a book with no cover at all is sent back to Edit with the reason',
          'needs a cover' in r.get_data(as_text=True))
    r = send(dict(PROJ, cover_mode='image', cover_file=''), 'publish')
    check('and the reason names the button that was pressed',
          'Send to publish needs a cover' in r.get_data(as_text=True),
          [l for l in r.get_data(as_text=True).splitlines() if 'needs a cover' in l])
    os.remove(MS_PATH)
    r = send(dict(PROJ))
    check('a missing manuscript is a message, not a crash',
          r.status_code == 200 and 'Manuscript file not found' in r.get_data(as_text=True))

    # ------------------------------------------------------------ the editor
    print('the project editor')
    with open(MS_PATH, 'w', encoding='utf-8') as f:
        f.write(MS)
    A.save_project_file(PID, dict(PROJ))
    page = client.get(f'/project/{PID}/edit').get_data(as_text=True)
    check('it offers the print settings', 'name="print_binding"' in page
          and 'name="print_blurb"' in page)
    client.post(f'/project/{PID}/edit', data={
        'name': 'Print test', 'preset': 'classic-literary', 'title': 'The Salt Road',
        'cover_mode': 'designed', 'cover_template': 'ashforge-house',
        'print_retailer': 'ingramspark', 'print_binding': 'jacket', 'print_paper': 'white',
        'print_blurb': 'Saved blurb.', 'print_back_w': '2'})
    saved = A.load_project(PID)
    check('and saves them', saved.get('print_retailer') == 'ingramspark'
          and saved.get('print_binding') == 'jacket'
          and saved.get('print_blurb') == 'Saved blurb.'
          and saved.get('print_back_w') == 2.0, saved)
    listing = client.get('/projects').get_data(as_text=True)
    check('the projects page has the buttons', f'/project/{FILE_ID}/print-package' in listing
          and 'value="publish"' in listing)
finally:
    cleanup()

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
