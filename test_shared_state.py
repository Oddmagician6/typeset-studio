"""Shared state between requests  (run: python test_shared_state.py).

Bug hunt item 5. The server is threaded, and some state outlives a request:
ReportLab's font table, module globals, the book's JSON, the output folder, the
thumbnail caches, the history folder. Checked, against throwaway folders:

    FONTS     a name stands for one file: covers and styles drawn one after
              another, or all at once in threads, embed their own faces - two
              styles sharing a family name too; a font file replaced in the
              library is used (book, cover, wrap designer); a broken upload under
              a name a good font once had is refused
    GALLERY   cover thumbnails asked for at once on a real threaded server are
              the tiles each draws alone
    EPUB      books exported at once keep their own in-book links
    BOOKS     a save made while the book builds (or packages) survives it; two
              builds of one book in the same second write two files
    HISTORY   snapshots taken at once each keep their own stamp and text
"""

import sys, os, io, json, time, shutil, tempfile, threading, zipfile, re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, epub, manuscript, matter, wrap_design
import fitz

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


FACES = ('Alegreya', 'Vollkorn', 'Lora', 'Spectral')
EMBEDDED = {'Alegreya': 'Alegreya', 'Vollkorn': 'Vollkorn', 'Lora': 'Lora',
            'Spectral': 'Spectral', 'Book': 'Book'}


def use_folders(root):
    os.makedirs(root)
    shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(root, 'presets'))
    shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(root, 'covers'),
                    ignore=shutil.ignore_patterns('assets'))
    shutil.copytree(os.path.join(HERE, 'fonts'), os.path.join(root, 'fonts'),
                    ignore=shutil.ignore_patterns('licenses'))
    A.PRESET_DIR, A.COVER_DIR = os.path.join(root, 'presets'), os.path.join(root, 'covers')
    A.FONT_DIR = engine.FONT_DIR = wrap_design.FONT_DIR = os.path.join(root, 'fonts')
    A.PROJECT_DIR = os.path.join(root, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(root, 'out')
    A.UPLOAD_DIR = os.path.join(root, 'uploads')
    A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR,
              A.PROJECT_THUMB_DIR):
        os.makedirs(d, exist_ok=True)


def faces_in(path, pages=None):
    """The faces a PDF embeds (subset prefix dropped), on the given pages or all."""
    with fitz.open(path) as d:
        pages = range(len(d)) if pages is None else pages
        return {f[3].split('+')[-1] for p in pages for f in d[p].get_fonts()}


def only(faces, face):
    """True if every embedded TrueType face is `face` (the built-ins aside)."""
    mine = {f for f in faces if not f.startswith(('Helvetica', 'Times', 'Courier', 'Symbol'))}
    return bool(mine) and all(f.startswith(EMBEDDED[face]) for f in mine), sorted(faces)


def files_of(face):
    return {r: f'{face}-{r.title()}.ttf' for r in ('regular', 'bold', 'italic')}


MS = manuscript.parse_markdown(
    '# The First\n\nIt began with **salt** and *ash*, as these things do.\n\n'
    '# The Second\n\nAnd it went on.\n', smartquotes=True)


def build(out, face=None, cover=None):
    """The book in `face` (a style named 'Shared' whatever its files), with a
    designed cover in `cover`'s faces, or none."""
    p = dict(A.DEFAULTS)
    p['trim'] = {'w': 6.0, 'h': 9.0}
    if face:
        p.update(font_family='Shared', font_files=files_of(face))
    meta = {'title': 'The Salt Road', 'author': 'Ellinor Vale', 'front_matter': 'none',
            'right_hand_starts': False, 'include_toc': False, 'cover_image': '',
            **matter.blank()}
    if cover:
        tpl = json.load(open(os.path.join(A.COVER_DIR, 'fantasy-emerald.json'), encoding='utf-8'))
        tpl['fonts'] = {'display': f'{cover}-Bold.ttf', 'serif': f'{cover}-Regular.ttf',
                        'italic': f'{cover}-Italic.ttf'}
        meta.update(cover_mode='designed', cover_template='x', cover_template_data=tpl)
    else:
        meta['cover_mode'] = 'none'
    return engine.build_pdf(MS, p, out, meta)


def fonts_tests(tmp):
    print('\n[fonts: one after another]')
    out = os.path.join(tmp, 'f.pdf')
    for face in ('Alegreya', 'Lora'):
        build(out, face=face)
        ok, got = only(faces_in(out), face)
        check(f'a style called "Shared" in {face} prints in {face}', ok, got)
    for face in ('Vollkorn', 'Spectral'):
        build(out, cover=face)
        ok, got = only(faces_in(out, [0]) - {'Book-Regular', 'Book-Bold', 'Book-Italic'}, face)
        check(f'a cover set in {face} prints in {face}', ok, got)

    print('\n[fonts: a file replaced in the library]')
    custom = os.path.join(A.FONT_DIR, 'Custom.ttf')
    shutil.copy(os.path.join(A.FONT_DIR, 'Alegreya-Bold.ttf'), custom)
    p = dict(A.DEFAULTS, font_family='Custom',
             font_files={'regular': 'Custom.ttf', 'bold': 'Custom.ttf', 'italic': 'Custom.ttf'})
    first = engine.register_fonts(p)['regular']
    w1 = wrap_design.metrics('Custom.ttf')['widths']
    time.sleep(0.05)
    shutil.copy(os.path.join(A.FONT_DIR, 'Lora-Bold.ttf'), custom)
    second = engine.register_fonts(p)['regular']
    from reportlab.pdfbase import pdfmetrics
    check('a style picks up the replaced file', first != second and
          pdfmetrics.getFont(second).face.name.startswith(b'Lora'),
          (first, second, pdfmetrics.getFont(second).face.name))
    check('so does the wrap designer (what it measures with)',
          wrap_design.metrics('Custom.ttf')['widths'] != w1
          and pdfmetrics.getFont(wrap_design.font_name('Custom.ttf')).face.name.startswith(b'Lora'))
    check('a style unchanged keeps one name', engine.register_fonts(p)['regular'] == second)
    os.remove(custom)

    print('\n[fonts: a broken upload under a name a good font had]')
    c = A.app.test_client()
    good = open(os.path.join(A.FONT_DIR, 'Lora-Regular.ttf'), 'rb').read()
    c.post('/fonts/upload', data={'fonts': (io.BytesIO(good), 'Probe.ttf')},
           content_type='multipart/form-data')
    had = os.path.exists(os.path.join(A.FONT_DIR, 'Probe.ttf'))
    c.post('/fonts/delete/Probe.ttf')
    c.post('/fonts/upload', data={'fonts': (io.BytesIO(b'not a font' * 100), 'Probe.ttf')},
           content_type='multipart/form-data')
    check('the good one went in, the broken one is refused',
          had and not os.path.exists(os.path.join(A.FONT_DIR, 'Probe.ttf')), had)

    print('\n[fonts: all at once, in threads]')
    wrong, errors = [], []
    def job(i):
        face = FACES[i % 4]
        out = os.path.join(tmp, f't{i}.pdf')
        try:
            if i % 2:
                build(out, face=face)
                ok, got = only(faces_in(out), face)
            else:
                build(out, cover=face)
                ok, got = only(faces_in(out, [0]) - {'Book-Regular', 'Book-Bold',
                                                     'Book-Italic'}, face)
            if not ok:
                wrong.append((i, face, got))
        except Exception as exc:
            errors.append((i, repr(exc)))
    ts = [threading.Thread(target=job, args=(i,)) for i in range(24)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check('24 books and covers drawn at once: none fails', not errors, errors[:3])
    check('and each prints in its own faces', not wrong, wrong[:3])


def gallery_tests(tmp):
    print('\n[gallery: thumbnails on a real threaded server]')
    from werkzeug.serving import make_server
    base = json.load(open(os.path.join(A.COVER_DIR, 'fantasy-emerald.json'), encoding='utf-8'))
    for face in FACES:
        t = dict(base, name=f'Test {face}', fonts={
            'display': f'{face}-Bold.ttf', 'serif': f'{face}-Regular.ttf',
            'italic': f'{face}-Italic.ttf'})
        with open(os.path.join(A.COVER_DIR, f'zz-{face.lower()}.json'), 'w', encoding='utf-8') as f:
            json.dump(t, f)
    alone = {}
    for face in FACES:
        alone[face] = A._cover_thumb_bytes(f'zz-{face.lower()}')
    check('each tile drawn alone differs from the others',
          all(alone.values()) and len(set(alone.values())) == 4)
    shutil.rmtree(A.COVER_THUMB_DIR)
    os.makedirs(A.COVER_THUMB_DIR)
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    got, errors = {}, []
    def fetch(i):
        face = FACES[i % 4]
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}'
                                        f'/cover/thumb/zz-{face.lower()}.png', timeout=120) as r:
                got.setdefault(face, []).append(r.read())
        except Exception as exc:
            errors.append(repr(exc))
    try:
        ts = [threading.Thread(target=fetch, args=(i,)) for i in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        server.shutdown()
    check('16 tiles asked for at once all come back', not errors and
          sum(len(v) for v in got.values()) == 16, errors[:2])
    check('each is the tile its template draws alone',
          all(b == alone[face] for face, bs in got.items() for b in bs),
          {f: [b == alone[f] for b in bs] for f, bs in got.items()})


def epub_tests(tmp):
    print('\n[EPUB: books exported at once]')
    books = {
        'a': ('# One\n\nOn to [the second](#two).\n\n# Two\n\nHere.\n', 'chapter002.xhtml'),
        'b': ('# Alpha\n\nx\n\n# Beta\n\ny\n\n# Two\n\nBack to [the first](#alpha), '
              'or [this one](#two).\n', 'chapter003.xhtml'),
    }
    want_b_alpha = 'chapter001.xhtml'
    bad, errors = [], []
    def job(i):
        key = 'ab'[i % 2]
        text, want = books[key]
        out = os.path.join(tmp, f'e{i}.epub')
        try:
            epub.build_epub(manuscript.parse_markdown(text, smartquotes=True), dict(A.DEFAULTS),
                            out, {'title': key, 'author': 'X', 'front_matter': 'none',
                                  'cover_image': '', **matter.blank()})
            with zipfile.ZipFile(out) as z:
                html = ''.join(z.read(n).decode('utf-8') for n in z.namelist()
                               if re.search(r'chapter\d+\.xhtml$', n))
            hrefs = re.findall(r'href="([^"]*)"', html)
            need = [want] + ([want_b_alpha] if key == 'b' else [])
            if not all(any(h.startswith(n) for h in hrefs) for n in need) \
                    or any(h.startswith('#') for h in hrefs):
                bad.append((i, key, hrefs))
        except Exception as exc:
            errors.append((i, repr(exc)))
    ts = [threading.Thread(target=job, args=(i,)) for i in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check('16 ebooks built at once: none fails', not errors, errors[:2])
    check('each one’s in-book links point at its own chapters', not bad, bad[:2])


def new_book(pid, text, **extra):
    """A book whose manuscript is an uploaded .txt (the editor's first save
    moves it to .md)."""
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.txt'), 'w', encoding='utf-8') as f:
        f.write(text)
    now = '2026-10-05T12:00:00'
    A.save_project_file(pid, {
        'name': pid, 'preset': 'classic-literary', 'title': 'The Salt Road', 'subtitle': '',
        'author': 'Ellinor Vale', 'year': '', 'publisher': '', 'front_matter': 'none',
        'right_hand_starts': False, 'cover_mode': 'none', 'format': 'pdf',
        'include_toc': False, 'smartquotes': True, **matter.blank(),
        'manuscript_file': pid + '.txt', 'manuscript_type': 'file', 'cover_file': '',
        'last_pdf': '', 'last_epub': '', 'created': now, 'updated': now, **extra})


def load(pid):
    with open(os.path.join(A.PROJECT_DIR, pid + '.json'), encoding='utf-8') as f:
        return json.load(f)


class Paused:
    """Replace `owner.attr` so its first `n` calls wait at a gate until released."""
    def __init__(self, owner, attr, n=1):
        self.owner, self.attr, self.orig = owner, attr, getattr(owner, attr)
        self.arrived, self.go, self.n, self.count = threading.Semaphore(0), threading.Event(), n, 0
        lock = threading.Lock()
        def wrapper(*a, **k):
            with lock:
                self.count += 1
                mine = self.count <= self.n
            if mine:
                self.arrived.release()
                self.go.wait(60)
            return self.orig(*a, **k)
        setattr(owner, attr, wrapper)

    def wait_arrivals(self):
        for _ in range(self.n):
            if not self.arrived.acquire(timeout=60):
                return False
        return True

    def undo(self):
        self.go.set()
        setattr(self.owner, self.attr, self.orig)


def books_tests(tmp):
    print('\n[books: a save made while the book builds]')
    new_book('mid', '# One\n\nThe old text.\n')
    gate = Paused(engine, 'build_pdf')
    res = {}
    t = threading.Thread(target=lambda: res.setdefault(
        'r', A.app.test_client().post('/project/mid/generate')))
    t.start()
    try:
        check('the build is under way', gate.wait_arrivals())
        r = A.app.test_client().post('/project/mid/write/save',
                                     data={'text': '# One\n\nThe new text.\n'})
        check('the editor saves meanwhile', r.status_code == 200 and r.get_json()['ok'])
    finally:
        gate.undo()
        t.join(120)
    p = load('mid')
    check('the build finished', res.get('r') is not None and res['r'].status_code == 200
          and p.get('last_pdf') and os.path.getsize(os.path.join(A.OUT_DIR, p['last_pdf'])) > 0,
          p.get('last_pdf'))
    check('and the editor’s save survives it (the book reads the new text)',
          p.get('manuscript_file') == 'mid.md'
          and 'The new text.' in A._project_manuscript_text(p, report_import=False),
          (p.get('manuscript_file'), p.get('manuscript_type')))

    print('\n[books: a save made while the book packages]')
    new_book('pkg', '# One\n\nThe old text.\n', cover_mode='designed',
             cover_template='fantasy-emerald')
    A.app.test_client().post('/project/pkg/generate')
    gate = Paused(engine, 'build_pdf')        # the interior, after the text is read
    t = threading.Thread(target=lambda: res.__setitem__(
        'p', A.app.test_client().post('/project/pkg/print-package', data={'scope': 'print'})))
    t.start()
    try:
        check('the package is under way', gate.wait_arrivals())
        r = A.app.test_client().post('/project/pkg/write/save',
                                     data={'text': '# One\n\nThe new text.\n'})
        check('the editor saves meanwhile', r.status_code == 200 and r.get_json()['ok'])
    finally:
        gate.undo()
        t.join(180)
    p = load('pkg')
    check('the package finished and is recorded', res['p'].status_code == 200
          and p.get('last_print_package')
          and os.path.exists(os.path.join(A.OUT_DIR, p['last_print_package'])),
          (res['p'].status_code, p.get('last_print_package')))
    check('and the editor’s save survives it', p.get('manuscript_file') == 'pkg.md',
          p.get('manuscript_file'))

    print('\n[books: two builds of one book in the same second]')
    new_book('twice', '# One\n\nText.\n')
    before = set(os.listdir(A.OUT_DIR))
    gate = Paused(engine, 'build_pdf', n=2)
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(
        A.app.test_client().post('/project/twice/generate').status_code)) for _ in range(2)]
    [x.start() for x in ts]
    try:
        both = gate.wait_arrivals()
    finally:
        gate.undo()
        [x.join(120) for x in ts]
    made = sorted(set(os.listdir(A.OUT_DIR)) - before)
    pdfs = [m for m in made if m.endswith('.pdf')]
    def opens(name):
        try:
            with fitz.open(os.path.join(A.OUT_DIR, name)) as d:
                return len(d) > 0
        except Exception:
            return False
    check('both builds ran at once', both and codes == [200, 200], codes)
    check('each wrote its own file, and both open', len(pdfs) == 2 and all(map(opens, pdfs)),
          made)
    check('the book points at one of them', load('twice')['last_pdf'] in pdfs)

    print('\n[books: a build that fails leaves no empty file behind]')
    before = set(os.listdir(A.OUT_DIR))
    orig = engine.build_pdf
    def boom(*a, **k):
        raise RuntimeError('no')
    engine.build_pdf = boom
    try:
        A.app.test_client().post('/project/twice/generate')
    finally:
        engine.build_pdf = orig
    check('nothing new in the output folder', set(os.listdir(A.OUT_DIR)) == before,
          set(os.listdir(A.OUT_DIR)) - before)

    print('\n[books: a book deleted while it builds]')
    new_book('gone', '# One\n\nText.\n')
    gate = Paused(engine, 'build_pdf')
    t = threading.Thread(target=lambda: res.__setitem__(
        'g', A.app.test_client().post('/project/gone/generate')))
    t.start()
    try:
        gate.wait_arrivals()
        os.remove(os.path.join(A.PROJECT_DIR, 'gone.json'))
    finally:
        gate.undo()
        t.join(120)
    check('the build ends without bringing it back',
          res['g'].status_code < 500 and not os.path.exists(
              os.path.join(A.PROJECT_DIR, 'gone.json')), res['g'].status_code)


def history_tests(tmp):
    print('\n[history: snapshots taken at once]')
    new_book('hist', '# One\n\nText.\n')
    stamps, errors = {}, []
    def job(i):
        try:
            stamps[i] = A.snapshot_manuscript('hist', f'# One\n\nVersion {i}.\n',
                                              reason='conflict', force=True)
        except Exception as exc:
            errors.append(repr(exc))
    ts = [threading.Thread(target=job, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check('8 snapshots, 8 stamps', not errors and len(set(stamps.values())) == 8,
          (errors[:2], stamps))
    check('each stamp gives back its own text',
          all(f'Version {i}.' in (A.read_snapshot('hist', s) or '') for i, s in stamps.items()))


def main():
    tmp = tempfile.mkdtemp(prefix='ts-shared-')
    try:
        use_folders(os.path.join(tmp, 'data'))
        fonts_tests(tmp)
        gallery_tests(tmp)
        epub_tests(tmp)
        books_tests(tmp)
        history_tests(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
