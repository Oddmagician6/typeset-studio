"""A damaged data folder  (run: python test_damaged_data.py).

Bug hunt item 9. Against throwaway folders, files broken the ways files break:

    READING   a file cut short, empty, zero-filled, not JSON, holding a list,
              with a byte-order mark, in Windows-1252: each read as meant or
              named with what is wrong; every book, style and cover any release
              wrote (the fixtures, the bundled ones) reads clean
    PAGES     every page, with a damaged book, style and cover in the folder:
              never a bare 500 - a page naming the file - and one broken file
              doesn't take a list page (or every page) down; the lists name it
    SHAPES    settings of the wrong kind (a name that is a number, a trim that is
              a number) and missing settings every style and cover has
    REPAIR    keeps what can be read (a real book cut at 60%), defaults the rest,
              keeps the damaged file beside it, finds the manuscript
    PICTURES  a figure, cover-template art, wrap-design art or uploaded cover
              that isn't a readable picture: said, and the wrap still builds
    DISK      a read-only file, a full disk: the file named, JSON for a fetch
    NAMES     a very long book name, a very long upload name
    BROWSER   the real page: a fetch gets JSON, a page gets the problem page,
              whose Repair works
"""

import sys, os, io, json, re, html, stat, errno, time, glob, shutil, tempfile, threading, \
    subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

from flask import request as _rq
import app as A
import engine, epub, manuscript, matter, wrap_design
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-damaged-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(ROOT, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
shutil.copytree(os.path.join(HERE, 'fonts'), os.path.join(ROOT, 'fonts'),
                ignore=shutil.ignore_patterns('licenses'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(ROOT, 'presets'), os.path.join(ROOT, 'covers')
A.FONT_DIR = engine.FONT_DIR = wrap_design.FONT_DIR = os.path.join(ROOT, 'fonts')
A.FIGURE_DIR = engine.FIGURE_DIR = epub.FIGURE_DIR = manuscript.FIGURE_DIR = \
    os.path.join(ROOT, 'figures')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
A.UPLOAD_DIR = os.path.join(ROOT, 'uploads')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = engine.COVER_ASSET_DIR = os.path.join(ROOT, 'covers', 'assets')
A.SETTINGS_PATH = os.path.join(ROOT, 'settings.json')
wrap_design.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.FIGURE_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR,
          A.PROJECT_THUMB_DIR, A.WRAP_DESIGN_DIR, A.COVER_ASSET_DIR):
    os.makedirs(d, exist_ok=True)

C = A.app.test_client()
MS = lambda p: os.path.join(A.PROJECT_MS_DIR, p)
JSON = {'Sec-Fetch-Mode': 'cors'}        # what a page's own fetch() sends


def raw(path, data):
    with open(path, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def book(pid, ms=True, **extra):
    if ms:
        raw(MS(pid + '.md'), '# One\n\nThe text of ' + pid + '.\n')
    A.save_project_file(pid, {
        'name': pid, 'preset': 'classic-literary', 'title': 'The Salt Road',
        'author': 'Ellinor Vale', 'front_matter': 'none', 'right_hand_starts': False,
        'cover_mode': 'none', 'format': 'pdf', 'include_toc': False, 'smartquotes': True,
        **matter.blank(), 'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
        'cover_file': '', 'last_pdf': '', 'last_epub': '', **extra})


def problem(r):
    """(title, message) of a problem page or a JSON error; ('', '') otherwise."""
    j = r.get_json(silent=True)
    if j is not None:
        return ('json', j.get('error') or '')
    b = r.get_data(as_text=True)
    t = re.search(r'<h1>(.*?)</h1>', b)
    m = re.search(r'class="msg">(.*?)</p>', b, re.S)
    return (html.unescape(t.group(1)) if t and m else '', html.unescape(m.group(1)) if m else '')


def flashes(r):
    return [html.unescape(x) for x in
            re.findall(r'<div class="flash">\s*<div>(.*?)</div>', r.get_data(as_text=True), re.S)]


def png(w=40, h=30):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (w, h), (40, 60, 90)).save(b, 'PNG')
    return b.getvalue()


# ---------------------------------------------------------------- reading
def reading():
    print('[reading]')
    p = os.path.join(tmp, 'r.json')
    cases = [
        (b'', 'is empty'), (b'\0' * 300, 'is empty'),
        (json.dumps({'a': 1, 'b': 'two'}, indent=2).encode()[:-8], 'stops part-way'),
        (b'{"a": 1,, "b": 2}', 'is not valid JSON'),
        (b'[1, 2]', 'holds a list'), (b'"x"', 'holds a piece of text'),
    ]
    for data, said in cases:
        raw(p, data)
        try:
            A.read_json(p)
            check(f'{data[:12]!r} is refused', False)
        except A.DamagedFile as exc:
            check(f'{data[:12]!r}: "{said}"', said in exc.problem, exc.problem)
    raw(p, b'\xef\xbb\xbf{"name": "bom"}')
    check('a byte-order mark is read past', A.read_json(p) == {'name': 'bom'})
    raw(p, '{"name": "café"}'.encode('cp1252'))
    check('Windows-1252 (Notepad) is read as meant', A.read_json(p) == {'name': 'café'})

    src = sorted(glob.glob(os.path.join(HERE, 'test_fixtures', 'v1.3.0', 'projects', '*.json')))[0]
    full = open(src, 'rb').read()
    whole = json.loads(full)
    raw(p, full[:int(len(full) * .6)])
    got = A.salvage_json(p)
    keep = [k for k in whole if got.get(k) == whole[k]]
    check('a real book cut at 60% gives back every setting before the cut',
          len(keep) == len(got) and len(got) >= len(whole) // 2, (len(got), len(whole)))
    raw(p, full.rstrip()[:-1])                  # only the closing brace gone
    check('  and all of them when only its end is gone', A.salvage_json(p) == whole)

    n = flagged = 0
    for reader, pat in ((A.read_style, 'presets/*.json'), (A.read_cover, 'covers/*.json'),
                        (A.read_style, 'test_fixtures/**/presets/*.json'),
                        (A.read_cover, 'test_fixtures/**/covers/*.json'),
                        (A.read_cover, 'test_fixtures/**/damaged-covers/*.json'),
                        (A.read_book, 'test_fixtures/**/projects/*.json')):
        for f in glob.glob(os.path.join(HERE, pat), recursive=True):
            n += 1
            try:
                reader(f)
            except A.DamagedFile as exc:
                flagged += 1
                print('       ', exc)
    check(f'every style, cover and book a release wrote reads clean ({n} files)',
          n > 60 and not flagged, flagged)


# ----------------------------------------------------------------- pages
DAMAGED = {}


def damage():
    book('good')
    raw(os.path.join(A.PROJECT_DIR, 'cut.json'), '{\n  "name": "cut",\n  "preset": "class')
    raw(os.path.join(A.PROJECT_DIR, 'listed.json'), '[1, 2]')
    raw(os.path.join(A.PROJECT_DIR, 'blank.json'), '')
    raw(os.path.join(A.PROJECT_DIR, 'kinds.json'), json.dumps(
        {'name': 5, 'title': ['a'], 'preset': None, 'updated': 3}))
    raw(os.path.join(A.PRESET_DIR, 'cut-style.json'), '{\n  "name": "x",\n  "body_fo')
    raw(os.path.join(A.PRESET_DIR, 'kind-style.json'), json.dumps(
        dict(A.DEFAULTS, name='Kinds', trim=7, margins=None)))
    raw(os.path.join(A.PRESET_DIR, 'thin-style.json'), '{"name": "Thin"}')
    raw(os.path.join(A.COVER_DIR, 'cut-cover.json'), '{\n  "name": "x",\n  "desi')
    raw(os.path.join(A.COVER_DIR, 'text-cover.json'), '"a cover"')
    raw(os.path.join(A.COVER_DIR, 'kind-cover.json'), json.dumps(
        dict(A.COVER_DEFAULTS, name='K', design='geometric', title='x', blocks=5)))
    raw(os.path.join(A.COVER_DIR, 'thin-cover.json'), '{}')
    book('cutstyle', preset='cut-style')
    book('kindstyle', preset='kind-style')
    book('cutcover', cover_mode='designed', cover_template='cut-cover')
    book('kindcover', cover_mode='designed', cover_template='kind-cover')
    os.makedirs(MS('dirms.md'))
    book('dirms', ms=False)
    raw(A.SETTINGS_PATH, '{bad')
    DAMAGED.update(book=['cut', 'listed', 'blank', 'kinds'],
                   style=['cut-style', 'kind-style', 'thin-style'],
                   cover=['cut-cover', 'text-cover', 'kind-cover', 'thin-cover'])


def pages():
    print('\n[pages, with damaged files in the folder]')
    for u in ['/', '/projects', '/covers', '/fonts', '/figures', '/about', '/editor/new',
              '/cover/new', '/wrap-designer', '/project/good/edit', '/project/good/write',
              '/editor/classic-literary']:
        r = C.get(u)
        check(f'{u} still opens', r.status_code == 200, (r.status_code, problem(r)))
    for kind, ids, list_page in (('book', DAMAGED['book'], '/projects'),
                                 ('style', DAMAGED['style'], '/'),
                                 ('cover', DAMAGED['cover'], '/covers')):
        b = C.get(list_page).get_data(as_text=True)
        check(f'{list_page} names each damaged {kind}',
              all(f'/{i}.json' in b for i in ids) and 'damaged-panel' in b)
    check('  and still lists the good ones',
          'data-pid="good"' in C.get('/projects').get_data(as_text=True))

    urls = []
    for pid in DAMAGED['book']:
        urls += [('get', f'/project/{pid}/edit'), ('get', f'/project/{pid}/write'),
                 ('get', f'/project/{pid}/history'), ('get', f'/wrap-designer/project/{pid}'),
                 ('post', f'/project/{pid}/generate'), ('post', f'/project/{pid}/continuity'),
                 ('post', f'/project/{pid}/print-package'),
                 ('post', f'/project/{pid}/write/preview')]
    for sid in DAMAGED['style']:
        urls += [('get', f'/editor/{sid}'), ('get', f'/style/{sid}/cover-specs'),
                 ('get', f'/style/{sid}/cover-specs/template.pdf')]
    for cid in DAMAGED['cover']:
        urls += [('get', f'/cover/{cid}'), ('get', f'/cover/thumb/{cid}.png')]
    urls += [('post', '/project/cutstyle/generate'), ('post', '/project/kindstyle/generate'),
             ('post', '/project/cutcover/generate'), ('post', '/project/kindcover/generate'),
             ('get', '/project/dirms/write'), ('post', '/project/dirms/generate')]
    bare, unnamed = [], []
    for method, u in urls:
        r = getattr(C, method)(u)
        title, msg = problem(r)
        if r.status_code >= 500 and title in ('', 'Something went wrong'):
            bare.append((u, r.status_code, msg[:80]))
        elif r.status_code >= 500 and not re.search(r'[\w-]+(\.json|\.md)', msg):
            unnamed.append((u, msg[:80]))
    check(f'none of {len(urls)} requests is a bare error', not bare, bare)
    check('  each problem page names the file', not unnamed, unnamed)

    r = C.get('/project/cut/edit')
    b = r.get_data(as_text=True)
    check('a damaged book\'s page offers Repair and Delete',
          '/damaged/book/cut/repair' in b and '/project/cut/delete' in b)
    r = C.post('/project/cutstyle/rebuild', headers=JSON)
    check('Rebuild all says the style can\'t be read',
          r.get_json() and 'cut-style.json' in r.get_json().get('error', ''), r.get_json())
    r = C.post('/project/cut/write/save', data={'text': 'x'}, headers=JSON)
    check('a fetch gets JSON naming the file', r.get_json(silent=True) and
          r.get_json()['ok'] is False and 'cut.json' in r.get_json()['error'])

    r = C.post('/cover/delete/cut-cover')
    check('a damaged cover template in use asks first, with its name',
          r.status_code == 200 and 'in use' in r.get_data(as_text=True))
    r = C.post('/cover/delete/cut-cover', data={'confirm': '1'})
    check('a damaged cover template deletes', r.status_code == 302 and
          not os.path.exists(os.path.join(A.COVER_DIR, 'cut-cover.json')))
    DAMAGED['cover'].remove('cut-cover')


# ------------------------------------------------------------------ repair
def repair():
    print('\n[repair]')
    src = sorted(glob.glob(os.path.join(HERE, 'test_fixtures', 'v1.3.0', 'projects', '*.json')))[0]
    full = open(src, 'rb').read()
    whole = json.loads(full)
    raw(os.path.join(A.PROJECT_DIR, 'real.json'), full[:int(len(full) * .6)])
    raw(MS(whole['manuscript_file']), '# One\n\nText.\n')
    b = C.get('/project/real/edit').get_data(as_text=True)
    check('the page says the manuscript is safe', 'is safe' in b and whole['manuscript_file'] in b)
    r = C.post('/damaged/book/real/repair')
    fixed = json.load(open(os.path.join(A.PROJECT_DIR, 'real.json'), encoding='utf-8'))
    check('a cut book is repaired: what was read kept',
          r.status_code == 302 and all(fixed[k] == v for k, v in A.salvage_json(
              os.path.join(A.PROJECT_DIR, 'real.json.damaged')).items()))
    check('  its manuscript kept', fixed.get('manuscript_file') == whole['manuscript_file'])
    check('  the damaged file kept beside it', open(os.path.join(
        A.PROJECT_DIR, 'real.json.damaged'), 'rb').read() == full[:int(len(full) * .6)])
    check('  and it opens and builds', C.get('/project/real/edit').status_code == 200 and
          C.post('/project/real/generate').status_code == 200)

    raw(os.path.join(A.PROJECT_DIR, 'lost.json'), '')
    raw(MS('lost.md'), '# One\n\nText.\n')
    C.post('/damaged/book/lost/repair')
    check('an empty book finds the manuscript named after it',
          A.load_project('lost').get('manuscript_file') == 'lost.md')

    for kind in ('book', 'style', 'cover'):
        for ident in DAMAGED[kind]:
            r = C.post(f'/damaged/{kind}/{ident}/repair', follow_redirects=True)
            check(f'{kind} {ident}: repaired and opens', r.status_code == 200 and
                  any(f.startswith('Repaired') for f in flashes(r)), (r.status_code, flashes(r)))
    k = json.load(open(os.path.join(A.PRESET_DIR, 'kind-style.json'), encoding='utf-8'))
    check('a style keeps its good settings, the wrong ones defaulted',
          k['name'] == 'Kinds' and k['trim'] == A.DEFAULTS['trim'] and k['body'] == A.DEFAULTS['body'])
    kb = A.load_project('kinds')
    check('a book\'s wrong-kind settings are dropped', kb['name'] == 'kinds' and
          'title' not in kb and kb['updated'] == '' if 'updated' in kb else True, kb)
    for u in ('/', '/covers', '/projects'):
        check(f'{u} has nothing left to name', 'damaged-panel' not in C.get(u).get_data(as_text=True))
    before = open(os.path.join(A.PROJECT_DIR, 'good.json'), 'rb').read()
    r = C.post('/damaged/book/good/repair', follow_redirects=True)
    check('a good file is left alone', open(os.path.join(A.PROJECT_DIR, 'good.json'), 'rb').read()
          == before and 'nothing was changed' in ' '.join(flashes(r)))
    check('unknown kinds and files are 404', C.post('/damaged/nope/good/repair').status_code == 404
          and C.post('/damaged/book/zzz/repair').status_code == 404)


# ---------------------------------------------------------------- pictures
def build(pid):
    with A.app.test_request_context():
        res = A._build_project(pid, A.load_project(pid))
    br = res.get('build_result') or {}
    rows = A._preflight(br, res['preset'], res['page_count']) if br else []
    return res, [c for c in rows if not c['ok']]


def pictures():
    print('\n[pictures that are not pictures]')
    raw(os.path.join(A.FIGURE_DIR, 'map.png'), b'garbage')
    raw(MS('figs.md'), '# One\n\n~~~ figure src="map.png"\nThe map.\n~~~\n\nText.\n')
    book('figs', ms=False)
    res, bad = build('figs')
    check('a figure that won\'t open is in the checks',
          any(c['label'] == 'Figures' and 'map.png' in c['detail'] for c in bad), bad)

    tpl = json.load(open(os.path.join(A.COVER_DIR, 'photo-dusk.json'), encoding='utf-8'))
    tpl['background'] = dict(tpl.get('background') or {}, image='bad-bg.jpg')
    raw(os.path.join(A.COVER_ASSET_DIR, 'bad-bg.jpg'), b'garbage')
    A.save_cover_template('photo-bad', tpl)
    book('art', cover_mode='designed', cover_template='photo-bad')
    res, bad = build('art')
    check('cover art that won\'t open is in the checks',
          any(c['label'] == 'Cover art' and 'bad-bg.jpg' in c['detail'] for c in bad), bad)
    r = C.post('/project/art/print-package', data={'scope': 'print'})
    check('  and in Send to print\'s', r.status_code == 200 and 'bad-bg.jpg' in
          r.get_data(as_text=True))

    raw(os.path.join(A.WRAP_DESIGN_DIR, 'bad-art.png'), b'garbage')
    raw(os.path.join(A.WRAP_DESIGN_DIR, 'ok-art.png'), png())
    book('wrapart', cover_mode='wrap', wrap_design={'elements': [
        {'type': 'image', 'src': 'bad-art.png', 'x': 0, 'y': 0, 'w': 1, 'h': 1, 'id': 'a'},
        {'type': 'image', 'src': 'ok-art.png', 'x': 1, 'y': 1, 'w': 1, 'h': 1, 'id': 'b'}]})
    r = C.post('/project/wrapart/print-package', data={'scope': 'print'})
    b = r.get_data(as_text=True)
    check('a wrap with a picture that won\'t open still goes to print (it failed outright)',
          r.status_code == 200 and 'cover-wrap.pdf' in b, (r.status_code, flashes(r)))
    check('  and says which picture was left off', 'bad-art.png' in b and
          'can’t be read' in html.unescape(b))
    check('  the good picture is still measured', 'Picture: ok-art.png' in html.unescape(b))

    raw(MS('junk.png'), b'not a png')
    book('junk', cover_mode='image', cover_file='junk.png')
    res, _ = build('junk')
    check('an uploaded cover that won\'t open is said',
          any('junk.png' in w and 'can’t be read' in w for w in res['warnings']), res['warnings'])
    book('gone', cover_mode='image', cover_file='gone.png')
    res, _ = build('gone')
    check('  and one that has gone', any('gone.png' in w and 'missing' in w
                                         for w in res['warnings']), res['warnings'])
    check('a readable picture is readable', not engine.picture_unreadable(
        os.path.join(A.WRAP_DESIGN_DIR, 'ok-art.png')))


# -------------------------------------------------------------------- disk
def disk():
    print('\n[a read-only file, a full disk]')
    book('disk')
    pj = os.path.join(A.PROJECT_DIR, 'disk.json')
    os.chmod(pj, stat.S_IREAD)
    try:
        r = C.post('/project/disk/edit', data={'name': 'disk', 'preset': 'classic-literary'})
        t, m = problem(r)
        check('saving a read-only book names it', 'projects/disk.json' in m and
              'refused' in m, m)
    finally:
        os.chmod(pj, stat.S_IWRITE | stat.S_IREAD)
    check('  and no temporary file is left', not [f for f in os.listdir(A.PROJECT_DIR)
                                                 if f.endswith('.tmp')])
    mp = MS('disk.md')
    os.chmod(mp, stat.S_IREAD)
    try:
        r = C.post('/project/disk/write/save', data={'text': '# One\n\nNew.'}, headers=JSON)
        j = r.get_json(silent=True) or {}
        check('the editor\'s save of a read-only manuscript answers JSON naming it',
              j.get('ok') is False and 'manuscripts/disk.md' in j.get('error', ''), j)
    finally:
        os.chmod(mp, stat.S_IWRITE | stat.S_IREAD)

    real = A._atomic_write_bytes
    def full(path, data):
        raise OSError(errno.ENOSPC, 'No space left on device', path)
    A._atomic_write_bytes = full
    try:
        for what, r in (
                ('the editor', C.post('/project/disk/write/save', data={'text': 'x'}, headers=JSON)),
                ('the Edit page', C.post('/project/disk/edit', data={'name': 'disk'})),
                ('a style', C.post('/save/classic-literary', data={'name': 'Classic'})),
                ('a cover', C.post('/cover/save/photo-dusk', data={'name': 'x'})),
                ('a new draft', C.post('/project/new-draft', data={}))):
            t, m = problem(r)
            check(f'a full disk, saving {what}: said', 'the disk is full' in m, (r.status_code, m))
    finally:
        A._atomic_write_bytes = real
    check('the book is as it was', A.load_project('disk')['name'] == 'disk')


def names():
    print('\n[long names]')
    long = 'The Extraordinarily Long and Winding Chronicle of the Sea Kings ' * 5
    r = C.post('/project/new-draft', data={'name': long})
    loc = r.headers.get('Location', '')
    check('a book with a 320-character name can be made (it couldn\'t)',
          r.status_code == 302 and '/write' in loc, (r.status_code, problem(r)))
    pid = loc.split('/project/')[1].split('/')[0] if '/project/' in loc else ''
    check('  its id is short, cut at a word', 0 < len(pid) <= A.SLUG_MAX and not pid.endswith('-'),
          pid)
    check('  and it keeps its whole name', pid and A.load_project(pid)['name'] == long.strip())
    check('  and builds', pid and C.post(f'/project/{pid}/generate').status_code == 200)
    n = A._safe_upload_name('x' * 300 + '.docx', 'manuscript')
    check('a long upload name is shortened, its extension kept',
          len(n) <= 90 and n.endswith('.docx'), n)
    check('two long names differing at the end stay different',
          A._safe_upload_name('y' * 300 + 'a.md', 'm') != A._safe_upload_name('y' * 300 + 'b.md', 'm'))


# ----------------------------------------------------------------- browser
HARNESS = r"""
(async () => {
  const R = {};
  try {
    const r = await fetch('/project/brw/write/save', {method: 'POST',
      body: new URLSearchParams({text: 'x'})});
    R.save_status = r.status;
    R.save_type = r.headers.get('content-type') || '';
    const j = await r.json();
    R.save_ok = j.ok; R.save_error = j.error || '';
    const f = document.createElement('iframe');
    document.body.appendChild(f);
    const load = src => new Promise(res => { f.onload = () => res(); if (src) f.src = src; });
    await load('/project/brw/edit');
    let d = f.contentDocument;
    R.h1 = (d.querySelector('#problem h1') || {}).textContent || '';
    R.msg = (d.querySelector('#problem .msg') || {}).textContent || '';
    const form = d.querySelector('#problem form[action*="repair"]');
    R.has_repair = !!form;
    const p = load();
    form.submit();
    await p;
    R.after = f.contentWindow.location.pathname;
    R.flash = (f.contentDocument.querySelector('.flash') || {}).textContent || '';
  } catch (e) { R.error = String(e); }
  await fetch('/_dd_result', {method: 'POST', body: JSON.stringify(R)});
})();
"""
RESULT = {}


@A.app.route('/_dd_harness')
def _dd_harness():
    return '<!doctype html><meta charset="utf-8"><body><script>' + HARNESS + '</script>'


@A.app.route('/_dd_result', methods=['POST'])
def _dd_result():
    RESULT.update(json.loads(_rq.get_data(as_text=True)))
    return 'ok'


def browser():
    print('\n[browser: the real page]')
    exe = find_browser()
    if not exe:
        print('SKIP  no Chrome/Edge found (set TS_BROWSER to a Chromium browser)')
        return
    raw(os.path.join(A.PROJECT_DIR, 'brw.json'), '{\n  "name": "brw",\n  "preset": "cla')
    raw(MS('brw.md'), '# One\n\nText.\n')
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # real time: as in test_manuscript_editor.py
        proc = subprocess.Popen([exe, '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--remote-debugging-port=0',
                                 '--user-data-dir=' + os.path.join(tmp, 'browser'),
                                 f'http://127.0.0.1:{server.server_port}/_dd_harness'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(120):
                if RESULT:
                    break
                time.sleep(0.5)
        finally:
            proc.kill()
            proc.wait()
    finally:
        server.shutdown()
    R = RESULT
    check('the harness ran to the end', R and not R.get('error'), R.get('error'))
    check('a fetch() gets JSON naming the file', 'json' in R.get('save_type', '') and
          R.get('save_ok') is False and 'brw.json' in R.get('save_error', ''), R)
    check('the page gets the problem page', R.get('h1') == 'A file is damaged' and
          'projects/brw.json' in R.get('msg', ''), R)
    check('its Repair opens the repaired book', R.get('has_repair') and
          R.get('after') == '/project/brw/edit' and 'Repaired' in R.get('flash', ''), R)


def main():
    try:
        reading()
        damage()
        pages()
        repair()
        pictures()
        disk()
        names()
        browser()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
