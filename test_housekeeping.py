"""Clone and delete, for books, styles and cover templates  (run: python test_housekeeping.py).

Bug hunt item 8. Checked, against throwaway folders:

    BOOKS     deleting takes everything only the book has (manuscript, cover, back
              image, wrap front, History, thumbnail), keeps what another book also
              names and what it built; a new book of the same name starts clean,
              even beside a History left by an older version; a broken or missing
              book deletes without an error
    STYLES    deleting one books use says which and asks; those books then say
              their style is gone; a clone carries everything; ids never land on a
              file that is there but unreadable
    COVERS    the same for cover templates (the books' checks say the cover is
              gone); gallery tiles follow the fonts they are drawn with and the app
              version, one tile per template, gone with it
    PROMPTS   in a browser: a name with a quote in it still asks before deleting
"""

import sys, os, io, json, re, time, shutil, tempfile, threading, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, matter
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-housekeeping-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(ROOT, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
shutil.copytree(os.path.join(HERE, 'fonts'), os.path.join(ROOT, 'fonts'),
                ignore=shutil.ignore_patterns('licenses'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(ROOT, 'presets'), os.path.join(ROOT, 'covers')
A.FONT_DIR = engine.FONT_DIR = os.path.join(ROOT, 'fonts')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
A.UPLOAD_DIR = os.path.join(ROOT, 'uploads')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR, A.PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)

C = A.app.test_client()
MS = lambda p: os.path.join(A.PROJECT_MS_DIR, p)


def png():
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (60, 90), (40, 60, 90)).save(b, 'PNG')
    return b.getvalue()


def book(pid, name=None, **extra):
    with open(MS(pid + '.md'), 'w', encoding='utf-8') as f:
        f.write('# One\n\nThe text of ' + pid + '.\n')
    A.save_project_file(pid, {
        'name': name or pid, 'preset': 'classic-literary', 'title': 'The Salt Road',
        'author': 'Ellinor Vale', 'front_matter': 'none', 'right_hand_starts': False,
        'cover_mode': 'none', 'format': 'pdf', 'include_toc': False, 'smartquotes': True,
        **matter.blank(), 'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
        'cover_file': '', 'last_pdf': '', 'last_epub': '', **extra})


def text(r):
    return re.sub(r'\s+', ' ', r.get_data(as_text=True))


def books_tests():
    print('\n[deleting a book]')
    for f in ('doomed-cover.png', 'doomed-back.png', 'doomed-wrap-front.jpg', 'shared-cover.png'):
        with open(MS(f), 'wb') as fh:
            fh.write(png())
    book('doomed', cover_mode='image', cover_file='doomed-cover.png',
         print_back_file='doomed-back.png', wrap_front_file='doomed-wrap-front.jpg')
    book('keeper', cover_mode='image', cover_file='shared-cover.png')
    A.update_project('doomed', {'print_back_file': 'doomed-back.png'})
    # a second book naming the same back image as this one
    A.update_project('keeper', {'print_back_file': 'doomed-back.png'})
    A.snapshot_manuscript('doomed', '# One\n\nAn older version.\n', force=True)
    C.post('/project/doomed/generate')
    A._project_thumb_bytes('doomed')
    built = A.load_project('doomed')['last_pdf']
    check('set up: history, a thumbnail and a build exist',
          os.listdir(A._history_folder('doomed'))
          and os.path.exists(os.path.join(A.PROJECT_THUMB_DIR, 'doomed.png')) and built)
    C.post('/project/doomed/delete')
    gone = [f for f in ('doomed.md', 'doomed-cover.png', 'doomed-wrap-front.jpg')
            if os.path.exists(MS(f))]
    check('its manuscript, cover and wrap front are gone', not gone, gone)
    check('its History and thumbnail are gone',
          not os.path.exists(A._history_folder('doomed'))
          and not os.path.exists(os.path.join(A.PROJECT_THUMB_DIR, 'doomed.png')))
    check('a file another book also names is kept', os.path.exists(MS('doomed-back.png')))
    check('what it built stays (a download the writer may want)',
          os.path.exists(os.path.join(A.OUT_DIR, built)))
    check('the other book is untouched', A.load_project('keeper')['cover_file'] == 'shared-cover.png'
          and os.path.exists(MS('shared-cover.png')))

    print('\n[a new book of the same name]')
    C.post('/project/new-draft', data={'name': 'doomed'})
    check('starts with no History of the deleted one',
          os.path.exists(os.path.join(A.PROJECT_DIR, 'doomed.json'))
          and not A.list_snapshots('doomed'), A.list_snapshots('doomed'))
    os.makedirs(os.path.join(A.HISTORY_DIR, 'orphan'))
    with open(os.path.join(A.HISTORY_DIR, 'orphan', '20260101-120000-edit.md'), 'w') as f:
        f.write('# Old\n\nLeft by an older version.\n')
    C.post('/project/new-draft', data={'name': 'orphan'})
    check('beside a History an older version left, it takes another name',
          os.path.exists(os.path.join(A.PROJECT_DIR, 'orphan-2.json'))
          and not os.path.exists(os.path.join(A.PROJECT_DIR, 'orphan.json')))

    print('\n[deleting a broken or missing book]')
    with open(os.path.join(A.PROJECT_DIR, 'broken.json'), 'w') as f:
        f.write('{ not json')
    os.makedirs(A._history_folder('broken'), exist_ok=True)
    r = C.post('/project/broken/delete')
    check('a broken one goes, history and all', r.status_code == 302
          and not os.path.exists(os.path.join(A.PROJECT_DIR, 'broken.json'))
          and not os.path.exists(A._history_folder('broken')))
    r = C.post('/project/never-was/delete')
    check('a missing one is no error', r.status_code == 302)
    C.post('/project/new-draft', data={'name': 'broken'})
    with open(os.path.join(A.PROJECT_DIR, 'unread.json'), 'w') as f:
        f.write('{ damaged')
    C.post('/project/new-draft', data={'name': 'unread'})
    check('a new book never takes the name of a damaged one',
          open(os.path.join(A.PROJECT_DIR, 'unread.json')).read() == '{ damaged'
          and os.path.exists(os.path.join(A.PROJECT_DIR, 'unread-2.json')))


def styles_tests():
    print('\n[deleting a style books use]')
    st = A.load_preset('modern-clean')
    st['min_text_size'] = 16
    with open(os.path.join(A.PRESET_DIR, 'modern-clean.json'), 'w', encoding='utf-8') as f:
        json.dump(st, f)
    book('uses-style', name='A “quoted” book', preset='modern-clean')
    book('also-style', preset='modern-clean')
    t = text(C.post('/delete/modern-clean'))
    check('the page says which books, and keeps it',
          os.path.exists(os.path.join(A.PRESET_DIR, 'modern-clean.json')) and 'is in use' in t
          and 'the book “A “quoted” book”' in t and 'the book “also-style”' in t, t[:300])
    r = C.post('/clone/modern-clean')
    cid = r.headers['Location'].rsplit('/', 1)[-1]
    clone = A.load_preset(cid)
    check('a clone carries everything, under a new name',
          {k: v for k, v in clone.items() if k != 'name'} == {k: v for k, v in st.items() if k != 'name'}
          and clone['name'] == st['name'] + ' (copy)', cid)
    C.post('/delete/modern-clean', data={'confirm': '1'})
    check('asked again, it goes', not os.path.exists(os.path.join(A.PRESET_DIR, 'modern-clean.json')))
    j = C.post('/project/uses-style/rebuild').get_json()
    check('its books then say their style is gone', not j['ok'] and 'style' in j['error'].lower(), j)
    r = C.post(f'/delete/{cid}')
    check('an unused style goes at once', r.status_code == 302
          and not os.path.exists(os.path.join(A.PRESET_DIR, cid + '.json')))
    with open(os.path.join(A.PRESET_DIR, 'thriller-crime-5-5-8-5-copy.json'), 'w') as f:
        f.write('{ damaged')
    C.post('/clone/thriller-crime')
    check('a clone never lands on a damaged file of its name',
          open(os.path.join(A.PRESET_DIR, 'thriller-crime-5-5-8-5-copy.json')).read() == '{ damaged'
          and os.path.exists(os.path.join(A.PRESET_DIR, 'thriller-crime-5-5-8-5-copy-2.json')))


def covers_tests():
    print('\n[deleting a cover template books use]')
    book('uses-cover', cover_mode='designed', cover_template='geometric-coral')
    t = text(C.post('/cover/delete/geometric-coral'))
    check('the page says which books, and keeps it',
          os.path.exists(os.path.join(A.COVER_DIR, 'geometric-coral.json'))
          and 'the book “uses-cover”' in t, t[:300])
    r = C.post('/cover/clone/geometric-coral')
    clone_id = r.headers['Location'].rsplit('/', 1)[-1]
    src = json.load(open(os.path.join(A.COVER_DIR, 'geometric-coral.json'), encoding='utf-8'))
    clone = json.load(open(os.path.join(A.COVER_DIR, clone_id + '.json'), encoding='utf-8'))
    check('a clone carries everything (its family’s own settings too)',
          {k: v for k, v in clone.items() if k != 'name'} == {k: v for k, v in src.items() if k != 'name'},
          sorted(set(src) ^ set(clone)))
    A._cover_thumb_bytes('geometric-coral')
    C.post('/cover/delete/geometric-coral', data={'confirm': '1'})
    check('asked again, it goes, and so do its tiles',
          not os.path.exists(os.path.join(A.COVER_DIR, 'geometric-coral.json'))
          and not [f for f in os.listdir(A.COVER_THUMB_DIR) if f.startswith('geometric-coral')])
    t = text(C.post('/project/uses-cover/generate'))
    check('its books say their cover is gone', 'has been deleted, so this book has no cover' in t,
          re.findall(r'Cover.{0,120}', t)[:2])

    print('\n[gallery tiles]')
    tid = clone_id
    t = A.load_cover_template(tid)
    shutil.copy(os.path.join(A.FONT_DIR, 'Lora-Bold.ttf'), os.path.join(A.FONT_DIR, 'Tile-Bold.ttf'))
    t['fonts'] = dict(t.get('fonts') or {}, display='Tile-Bold.ttf')
    A.save_cover_template(tid, t)
    first = A._cover_thumb_bytes(tid)
    again = A._cover_thumb_bytes(tid)
    os.remove(os.path.join(A.FONT_DIR, 'Tile-Bold.ttf'))
    after_font = A._cover_thumb_bytes(tid)
    old_version = A.APP_VERSION
    A.APP_VERSION = '99.0.0'
    try:
        A._cover_thumb_bytes(tid)
    finally:
        A.APP_VERSION = old_version
    tiles = [f for f in os.listdir(A.COVER_THUMB_DIR) if f.startswith(tid + '~')]
    check('a tile is drawn once and then served', first and first == again)
    check('a font it is drawn in leaving the library redraws it', after_font and after_font != first)
    check('so does a new version of the app, and only one tile is kept', len(tiles) == 1, tiles)


RESULT = {}
from flask import request
SCRIPT = r'''
var f = document.getElementById('f'), steps = %s, out = {asked: []}, i = 0;
function next() {
  if (i >= steps.length) {
    var x = new XMLHttpRequest(); x.open('POST', '/_hk_result', false); x.send(JSON.stringify(out));
    return;
  }
  var st = steps[i++];
  f.onload = function () {
    var w = f.contentWindow, d = f.contentDocument;
    w.confirm = function (msg) { out.asked.push(msg); return false; };
    var form = Array.prototype.find.call(d.querySelectorAll('form'), function (fm) {
      return (fm.getAttribute('action') || '').indexOf(st[1]) !== -1;
    });
    if (!form) { out.asked.push('NO FORM ' + st[1]); setTimeout(next, 50); return; }
    f.onload = null;
    form.querySelector('button[type=submit]').click();
    setTimeout(next, 1200);     // long enough for a submit to have gone through
  };
  f.src = st[0];
}
next();'''
STEPS = [['/projects', '/project/obrien/delete'],
         ['/', '/delete/obrien-style'],
         ['/covers', '/cover/delete/obrien-cover']]

@A.app.route('/_hk_harness')
def _hk_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" style="width:1200px;height:800px">'
            '</iframe><script>' + SCRIPT % json.dumps(STEPS) + '</script>')

@A.app.route('/_hk_result', methods=['POST'])
def _hk_result():
    RESULT.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def prompt_tests():
    print('\n[delete prompts, in a browser]')
    browser = find_browser()
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
        return
    book('obrien', name="O'Brien's \"Road\"")
    st = A.load_preset('classic-literary')
    st['name'] = "O'Brien's style"
    A.save_preset('obrien-style', st)
    ct = A.load_cover_template('minimal-noir') or A.load_cover_template('fantasy-emerald')
    ct['name'] = "O'Brien's cover"
    A.save_cover_template('obrien-cover', ct)
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        proc = subprocess.Popen([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--user-data-dir=' + os.path.join(tmp, 'browser'),
                                 f'http://127.0.0.1:{server.server_port}/_hk_harness'],
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
    asked = RESULT.get('asked', [])
    check('each Delete asked first, naming what it would delete',
          len(asked) == 3 and all("O'Brien's" in a for a in asked), asked)
    check('and, told no, deleted nothing',
          os.path.exists(os.path.join(A.PROJECT_DIR, 'obrien.json'))
          and os.path.exists(os.path.join(A.PRESET_DIR, 'obrien-style.json'))
          and os.path.exists(os.path.join(A.COVER_DIR, 'obrien-cover.json')))


def main():
    try:
        books_tests()
        styles_tests()
        covers_tests()
        prompt_tests()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
