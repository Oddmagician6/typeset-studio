"""Send-to-print package tests  (run: python test_print_package.py).

The package exists to stop one mistake: a cover wrap cut for a different page
count than the interior inside it. So these build a real project end to end and
measure the files — the interior carries no cover, and the wrap's width is the
retailer formula evaluated at *that* interior's page count.
"""

import sys, os, zipfile, tempfile

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
    for p in (MS_PATH, PROJ_JSON):
        if os.path.exists(p):
            os.remove(p)
    for f in os.listdir(A.OUT_DIR):
        if f.startswith('the-salt-road-print-') and f.endswith('.zip'):
            os.remove(os.path.join(A.OUT_DIR, f))


def send(proj):
    A.save_project_file(PID, proj)
    return client.post(f'/project/{PID}/print-package', follow_redirects=True)


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

    # ------------------------------------------------------------ refusals
    print('what it refuses')
    r = send(dict(PROJ, cover_mode='image'))
    check('a book without a designed cover is sent back to Edit with the reason',
          'needs a designed cover' in r.get_data(as_text=True))
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
    check('the projects page has the button', f'/project/{FILE_ID}/print-package' in listing)
finally:
    cleanup()

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
