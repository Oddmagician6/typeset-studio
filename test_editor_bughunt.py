"""The writing page keeps every edit  (run: python test_editor_bughunt.py).

Joint bug hunt, round 6, section 27 (manuscript editor, autosave, history):

    27.1  two saves at once: the second is a conflict, not a silent overwrite
    27.2  a Book settings save doesn't point the book back at a deleted manuscript
    27.3  leaving for Typeset stops typing until the last words are saved
    27.4  typing stops while a restore is on its way
    27.5  a queued beacon is not taken for a save: the browser still asks
    27.6  "Open the saved version" stays put when the latest edits can't be kept
    27.7  the copy kept before a restore survives a clock put back
    27.8  Find closes when the rich editor opens; Replace won't touch hidden text
    27.9  pasting only blocks over a rich chapter title keeps the title
    27.10 a Homebrewery paste inside a stat block's own fences adds no fences
    27.11 the Designed page picker closes when the editor changes mode
    27.13 typed and taken back is not unsaved
    spec  back from the back-forward cache, leaving is guarded again

Not fixed: 27.12 (one undo history across the two editors: each keeps the
browser's own). The browser half needs Chrome or Edge (TS_BROWSER).
"""

import json, os, shutil, subprocess, sys, tempfile, threading, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
from flask import request
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh27-')
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


def make_book(pid, text='# One\n\nThe text.\n', ext='.md', **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + ext), 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    data = dict(name=pid, title='T', author='A', preset='classic-literary', format='pdf',
                manuscript_file=pid + ext,
                manuscript_type='markdown' if ext == '.md' else 'file', cover_file='',
                cover_mode='none', last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', front_matter='none')
    data.update(over)
    A.save_project_file(pid, data)


def ms_of(pid):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), encoding='utf-8') as f:
        return f.read()


# ---- the page, in a browser ---------------------------------------------------
SCRIPT = r'''
var R = {};
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
function frame(url){
  return new Promise(function(res){
    var f = document.createElement('iframe');
    f.style.width = '1100px'; f.style.height = '800px';
    f.style.position = 'fixed'; f.style.left = '0'; f.style.top = '0';
    f.onload = function(){ f.onload = null; res(f); };
    f.src = url; document.body.appendChild(f);
  });
}
function nextLoad(f){
  return new Promise(function(res){ f.onload = function(){ f.onload = null; res(f); }; });
}
async function open(pid, mode){
  localStorage.setItem('ts-write-mode', mode || 'markdown');
  return frame('/project/' + pid + '/write');
}
async function disk(pid){ return (await fetch('/_bh27_disk/' + pid)).text(); }
function $(f, id){ return f.contentDocument.getElementById(id); }
function typeMd(f, s){
  var w = f.contentWindow, ta = $(f, 'ms');
  ta.value = ta.value + s;
  ta.dispatchEvent(new w.Event('input', {bubbles: true}));
}
function unloadAsks(f){
  var w = f.contentWindow, ev = new w.Event('beforeunload', {cancelable: true});
  w.dispatchEvent(ev);
  return ev.defaultPrevented;
}
// saves (or anything matching `part`) answered `ms` late
function slow(f, part, ms){
  var w = f.contentWindow, real = w.fetch;
  w.fetch = function(u, o){
    if (String(u).indexOf(part) < 0) return real.call(w, u, o);
    return new Promise(function(r){ setTimeout(r, ms); }).then(function(){ return real.call(w, u, o); });
  };
}
function failing(f, part){
  var w = f.contentWindow, real = w.fetch;
  w.fetch = function(u, o){
    if (String(u).indexOf(part) >= 0) return Promise.reject(new TypeError('Failed to fetch'));
    return real.call(w, u, o);
  };
}
function paste(f, el, text){
  var w = f.contentWindow, dt = new w.DataTransfer();
  dt.setData('text/plain', text);
  return el.dispatchEvent(new w.ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
}

async function run(){
  var f, w, go;

  // 27.3 Typeset clicked while a save is on its way
  f = await open('leave');
  slow(f, '/write/save', 800);
  typeMd(f, ' FIRST');
  $(f, 'save-btn').click();
  typeMd(f, ' SECOND');
  go = nextLoad(f);
  f.contentDocument.querySelector('#typeset-form button[type=submit]').click();
  await sleep(100);
  R.leave_locked = $(f, 'ms').readOnly;
  await go;
  R.leave_disk = await disk('leave');

  // 27.4 typing during a restore
  f = await open('restore');
  w = f.contentWindow;
  await sleep(500);
  slow(f, '/restore', 800);
  var btn = f.contentDocument.querySelector('#history .snap button');
  btn.click(); btn.click();
  await sleep(300);
  R.restore_locked = $(f, 'ms').readOnly;
  await sleep(1500);
  R.restore_unlocked = !$(f, 'ms').readOnly;

  // 27.5 a beacon is not a save
  f = await open('beacon');
  failing(f, '/write/save');
  typeMd(f, ' UNSAVED');
  R.beacon_asks = unloadAsks(f);

  // 27.13 typed and taken back
  f = await open('big');
  var ta = $(f, 'ms'), was = ta.value;
  typeMd(f, 'x');
  ta.value = was; ta.dispatchEvent(new f.contentWindow.Event('input', {bubbles: true}));
  R.big_quiet = !unloadAsks(f);
  typeMd(f, ' REALLY');
  R.big_asks = unloadAsks(f);

  // 27.6 the saved version, when the latest edits can't be kept
  f = await open('clash');
  await fetch('/_bh27_clash');                 // another tab saved meanwhile
  typeMd(f, ' MINE'); await sleep(2500);
  R.clash_banner = !$(f, 'conflict').hidden;
  typeMd(f, ' LATEST');
  failing(f, '/write/save');
  var reloaded = false;
  f.onload = function(){ reloaded = true; };
  $(f, 'cf-load').click();
  await sleep(800);
  R.clash_stayed = !reloaded && $(f, 'ms').value.indexOf('LATEST') >= 0;
  R.clash_status = $(f, 'save-status').textContent;
  f.onload = null;

  // 27.8 / 27.11 the find bar and the page picker over the rich editor
  f = await open('bars');
  f.contentDocument.querySelector('[data-act=find]').click();
  R.find_open = !$(f, 'findbar').hidden;
  $(f, 'mode-toggle').click();
  R.find_closed = $(f, 'findbar').hidden;
  $(f, 'f-find').value = 'text'; $(f, 'f-repl').value = 'XXX';
  $(f, 'f-all').click();
  R.rich_text_kept = $(f, 'ms').value.indexOf('XXX') < 0;
  $(f, 'mode-toggle').click();                 // back to Markdown
  f.contentDocument.querySelector('[data-act=page]').click();
  R.pick_open = !$(f, 'pagepick').hidden;
  $(f, 'mode-toggle').click();
  R.pick_closed = $(f, 'pagepick').hidden;
  $(f, 'mode-toggle').click();

  // 27.9 blocks pasted over a rich chapter title
  f = await open('title', 'rich');
  w = f.contentWindow;
  var h = $(f, 'ms-rich').querySelector('.wb-chapter');
  var rg = f.contentDocument.createRange(); rg.selectNodeContents(h);
  var sel = w.getSelection(); sel.removeAllRanges(); sel.addRange(rg);
  paste(f, $(f, 'ms-rich'), '~~~ statblock\nGoblin\nArmor Class: 12\n~~~');
  R.title_kept = $(f, 'ms-rich').querySelector('.wb-chapter').textContent;

  // 27.10 a Homebrewery monster pasted inside a stat block's fences
  f = await open('fenced');
  ta = $(f, 'ms');
  var at = ta.value.indexOf('Old line');
  ta.setSelectionRange(at, at + 'Old line'.length);
  var browserPastes = paste(f, ta, '{{monster,frame\n## Goblin\n*Small humanoid*\n}}');
  R.fenced_count = ta.value.split('~~~ statblock').length - 1;
  R.fenced_pasted_plain = browserPastes;   // not taken over: the browser pastes it as it is

  await sleep(500);
}
run().then(function(){
  var x = new XMLHttpRequest(); x.open('POST', '/_bh27_result', false); x.send(JSON.stringify(R));
}).catch(function(e){
  R.error = String(e && e.stack || e);
  var x = new XMLHttpRequest(); x.open('POST', '/_bh27_result', false); x.send(JSON.stringify(R));
});
'''

result = {}

@A.app.route('/_bh27_harness')
def _bh27_harness():
    return '<!doctype html><meta charset="utf-8"><body><script>' + SCRIPT + '</script>'

@A.app.route('/_bh27_disk/<pid>')
def _bh27_disk(pid):
    return ms_of(pid)

@A.app.route('/_bh27_clash')
def _bh27_clash():
    A.app.test_client().post('/project/clash/write/save', data={'text': '# One\n\nOther tab.\n'})
    return 'ok'

@A.app.route('/_bh27_result', methods=['POST'])
def _bh27_result():
    result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


# ---- 27.1 -------------------------------------------------------------------
print('27.1 two saves at once')
make_book('race')
rev = A._ms_rev(ms_of('race'))
real_read = A._project_manuscript_text
def slow_read(*a, **k):
    out = real_read(*a, **k)
    time.sleep(0.3)                     # both requests have read the draft by now
    return out
A._project_manuscript_text = slow_read
res = {}
try:
    def go(n):
        r = A.app.test_client().post('/project/race/write/save',
                                     data={'text': f'# One\n\nTab {n}.\n', 'base': rev})
        res[n] = r.status_code
    ts = [threading.Thread(target=go, args=(n,)) for n in (1, 2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
finally:
    A._project_manuscript_text = real_read
check('one is saved and the other is a conflict', sorted(res.values()) == [200, 409], res)
lost = [n for n in (1, 2) if res.get(n) == 409][0] if 409 in res.values() else None
kept = [A.read_snapshot('race', s['stamp']) for s in A.list_snapshots('race')
        if s['reason'] == 'conflict']
check('and the refused one is kept in History', lost and f'# One\n\nTab {lost}.\n' in kept, kept)
check('the lock file is gone afterwards',
      not [f for f in os.listdir(A.PROJECT_MS_DIR) if f.endswith('.mslock')])

# ---- 27.2 -------------------------------------------------------------------
print('27.2 a Book settings save racing a manuscript save')
make_book('word', 'Chapter text from an imported file.\n', ext='.txt')
real_presets, fired = A.list_presets, []
def presets_then_editor_save():
    # the settings request has read the book; the editor saves now
    if not fired:
        fired.append(A.app.test_client().post('/project/word/write/save', data={
            'text': '# One\n\nSaved in the editor.\n',
            'base': A._ms_rev('Chapter text from an imported file.\n')}).status_code)
    return real_presets()
A.list_presets = presets_then_editor_save
try:
    r = c.post('/project/word/edit', data={'name': 'Word', 'title': 'New title',
                                          'preset': 'classic-literary'})
finally:
    A.list_presets = real_presets
proj = A.load_project('word')
check('the editor save went through', fired == [200], fired)
check('the book still points at the saved draft', proj['manuscript_file'] == 'word.md'
      and proj['manuscript_type'] == 'markdown', (proj['manuscript_file'], proj['manuscript_type']))
check('which is there', os.path.exists(os.path.join(A.PROJECT_MS_DIR, 'word.md'))
      and 'Saved in the editor.' in ms_of('word'))
check('and the settings change is kept too', proj['title'] == 'New title', proj['title'])
make_book('word2', 'Old words.\n', ext='.txt')
def presets_then_upload():
    if not fired[1:]:
        fired.append(A.app.test_client().post('/project/word2/write/save', data={
            'text': '# One\n\nEditor.\n', 'base': A._ms_rev('Old words.\n')}).status_code)
    return real_presets()
A.list_presets = presets_then_upload
try:
    import io
    c.post('/project/word2/edit', data={'name': 'W2', 'preset': 'classic-literary',
                                       'manuscript': (io.BytesIO(b'# New\n\nUploaded.\n'), 'n.txt')},
           content_type='multipart/form-data')
finally:
    A.list_presets = real_presets
proj = A.load_project('word2')
check('an upload racing an editor save points at the upload',
      proj['manuscript_file'] == 'word2.txt', proj['manuscript_file'])
check('and the draft the editor wrote meanwhile is not left behind',
      not os.path.exists(os.path.join(A.PROJECT_MS_DIR, 'word2.md')))

# ---- 27.7 -------------------------------------------------------------------
print('27.7 a restore after the clock went back')
make_book('clock', '# One\n\nNot in History anywhere.\n')
folder = A._history_folder('clock')
os.makedirs(folder, exist_ok=True)
ahead = datetime.now() + timedelta(days=2)
for n in range(A.HISTORY_KEEP):
    stamp = (ahead + timedelta(minutes=n)).strftime('%Y%m%d-%H%M%S')
    with open(os.path.join(folder, f'{stamp}-edit.md'), 'w', encoding='utf-8') as f:
        f.write(f'# One\n\nFuture {n}.\n')
oldest = min(s['stamp'] for s in A.list_snapshots('clock'))
j = c.post(f'/project/clock/history/{oldest}/restore').get_json()
texts = [A.read_snapshot('clock', s['stamp']) for s in A.list_snapshots('clock')]
check('the restore went through', j and j['ok'], j)
check('the draft it replaced is still in History', '# One\n\nNot in History anywhere.\n' in texts)
check('and History is still capped', len(texts) <= A.HISTORY_KEEP, len(texts))


print('\nthe page, in a browser')
browser = find_browser()
if not browser or os.environ.get('TS_SKIP_BROWSER'):
    print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
else:
    from werkzeug.serving import make_server
    for pid in ('leave', 'beacon', 'clash', 'bars'):
        make_book(pid, '# One\n\nThe text.\n')
    make_book('restore', '# One\n\nNow.\n')
    A.snapshot_manuscript('restore', '# One\n\nEarlier.\n', force=True)
    make_book('big', '# One\n\n' + 'Some words in a long book. ' * 4000 + '\n')
    make_book('title', '# The Crossing\n\nThe text.\n')
    make_book('fenced', '# One\n\n~~~ statblock\nOld line\n~~~\n\nProse after.\n')
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                        '--user-data-dir=' + os.path.join(TMP, 'browser'),
                        '--window-size=1200,900', '--virtual-time-budget=60000', '--dump-dom',
                        f'http://127.0.0.1:{server.server_port}/_bh27_harness'],
                       capture_output=True, timeout=300)
    finally:
        server.shutdown()
    r = result
    check('the page ran', bool(r) and 'error' not in r, r)
    if r and 'error' not in r:
        check('27.3 typing stops while the page is left', r.get('leave_locked'), r)
        check('27.3 and Typeset builds the last words', 'FIRST SECOND' in r.get('leave_disk', ''),
              r.get('leave_disk'))
        check('27.4 typing stops while a restore is on its way', r.get('restore_locked'), r)
        check('27.4 and starts again after it', r.get('restore_unlocked'), r)
        check('27.4 the restore happened', 'Earlier.' in ms_of('restore'), ms_of('restore'))
        check('27.5 an unconfirmed edit still asks before leaving', r.get('beacon_asks'), r)
        check('27.13 typed and taken back does not ask', r.get('big_quiet'), r)
        check('27.13 a real edit still asks', r.get('big_asks'), r)
        check('27.6 the conflict showed', r.get('clash_banner'), r)
        check('27.6 a failed keep does not reload', r.get('clash_stayed'), r)
        check('27.6 and says why', (r.get('clash_status') or '').startswith('Not reloaded'),
              r.get('clash_status'))
        check('27.8 find opens', r.get('find_open'), r)
        check('27.8 and closes when the rich editor opens', r.get('find_closed'), r)
        check('27.8 Replace All leaves the hidden text alone', r.get('rich_text_kept'), r)
        check('27.11 the picker opens', r.get('pick_open'), r)
        check('27.11 and closes on a mode switch', r.get('pick_closed'), r)
        check('27.9 the chapter title is kept', r.get('title_kept') == 'The Crossing',
              r.get('title_kept'))
        check('27.10 no second stat block', r.get('fenced_count') == 1, r.get('fenced_count'))
        check('27.10 the monster is left to paste as it is', r.get('fenced_pasted_plain'), r)

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('all passed')
