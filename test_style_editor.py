"""Style editor tests in a real browser  (run: python test_style_editor.py).

The second half of the roadmap's editor bug hunt (test_cover_editor.py is the
first). It serves the app against throwaway folders, opens every bundled style
in the real style editor in headless Chrome or Edge, and checks:

    ROUND TRIP  opening a style and saving it unchanged gives back the same style
    PREVIEW     the editor's Preview button renders the style's pages

Needs a Chromium browser (TS_BROWSER to point at one); without one it is
skipped and says so.
"""

import sys, os, json, glob, shutil, tempfile, threading, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
from test_rich_editor import find_browser
from werkzeug.serving import make_server
from werkzeug.datastructures import MultiDict
from flask import request

def differences(a, b, path=''):
    """Where two saved styles differ, as 'path: old -> new' (numbers compared as numbers;
    a key filled in by the save is not a loss)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out.append(f'{path}{k}: dropped')
            elif k in a:
                out += differences(a[k], b[k], f'{path}{k}.')
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-9:
            out.append(f'{path[:-1]}: {a} -> {b}')
    elif a != b:
        out.append(f'{path[:-1]}: {a!r} -> {b!r}')
    return out


fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-styled-')
A.PRESET_DIR = os.path.join(tmp, 'presets')
A.OUT_DIR = os.path.join(tmp, 'out')
for d in (A.PRESET_DIR, A.OUT_DIR):
    os.makedirs(d)
for f in glob.glob(os.path.join(HERE, 'presets', '*.json')):
    shutil.copy(f, A.PRESET_DIR)
ORIGINAL = {os.path.basename(f)[:-5]: json.load(open(f, encoding='utf-8'))
            for f in glob.glob(os.path.join(A.PRESET_DIR, '*.json'))}
PIDS = sorted(ORIGINAL)
captured = {}

SCRIPT = r'''
var pids = %s, i = 0, f = document.getElementById('f');
function next() {
  if (i >= pids.length) return;
  f.src = '/editor/' + pids[i];
}
f.onload = function () {
  var d = f.contentDocument, pid = pids[i], form = d.querySelector('form.editor'), pairs = [];
  new f.contentWindow.FormData(form).forEach(function (v, k) { if (typeof v === 'string') pairs.push([k, v]); });
  d.getElementById('preview-btn').click();
  var st = d.getElementById('preview-status');
  var t = setInterval(function () {
    if (!st.textContent || st.textContent.indexOf('Rendering') === 0) return;
    clearInterval(t);
    var x = new XMLHttpRequest(); x.open('POST', '/_se_capture/' + pid, false);
    x.send(JSON.stringify({form: pairs, preview: st.textContent}));
    i++; next();
  }, 50);
};
next();
'''

@A.app.route('/_se_harness')
def _se_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT % json.dumps(PIDS) + '</script>')

@A.app.route('/_se_capture/<pid>', methods=['POST'])
def _se_capture(pid):
    captured[pid] = json.loads(request.get_data(as_text=True))
    return 'ok'


try:
    browser = find_browser()
    print('[opening every style in the editor]')
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=300000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_se_harness'],
                           capture_output=True, timeout=600)
        finally:
            server.shutdown()
        check('the editor opened every style', len(captured) == len(PIDS),
              sorted(set(PIDS) - set(captured)))

        print('\n[ROUND TRIP: saved unchanged, a style is itself]')
        for pid in PIDS:
            if pid in captured:
                diff = differences(ORIGINAL[pid], A.parse_preset_form(MultiDict(captured[pid]['form'])))
                check(pid, not diff, diff[:8])

        print('\n[PREVIEW: the Preview button renders the pages]')
        for pid in PIDS:
            if pid in captured:
                pv = captured[pid]['preview']
                check(pid, pv.endswith('pages') or pv.endswith('page'), pv)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
