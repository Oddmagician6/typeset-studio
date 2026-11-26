"""The page designer and the Page Plan  (run: python test_pagedesigner_bughunt.py).

Joint bug hunt, round 5, section 21 (21.8 is in test_epubvalid_bughunt.py):

    21.1  saving a new page under a taken name is refused, not an overwrite
    21.2  a save answered after another page was opened leaves that page be
    21.3  two saves at once to different designs both survive
    21.4  a working copy older than the saved page gives way to it
    21.5  after the picker switches pages, the address names the open one
    21.6  a recovered new-page draft counts as unsaved
    21.7  + Page never reuses a name the manuscript still places
    21.9  malformed saved elements don't stop the designer or the plan
    21.10 a rename rewrites the src the reader reads (the last one)
    21.11 one page from a spread keeps what is drawn on that page
    21.12 the plan doesn't number pages the book doesn't number that way
    21.13 art for one page of a new spread goes above its ground
    21.14 undoing a field's kind brings back the field as it was
"""

import copy, json, os, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import page_plan
import wrap_design as W
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-pagedesigner-')
saved_paths = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR', 'HISTORY_DIR',
                                         'PRESET_DIR')}
A.PROJECT_DIR = os.path.join(TMP, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(TMP, 'out')
A.PRESET_DIR = os.path.join(TMP, 'presets')
shutil.copytree(os.path.join(HERE, 'presets'), A.PRESET_DIR)
for d in (A.PROJECT_MS_DIR, A.OUT_DIR, A.HISTORY_DIR):
    os.makedirs(d)
A.app.config['TESTING'] = True
c = A.app.test_client()

FONT = 'EBGaramond-Regular.ttf'


def text(id_, y, words, anchor='front', x=0.5):
    return {'id': id_, 'type': 'text', 'anchor': anchor, 'x': x, 'y': y, 'w': 3,
            'text': words, 'font': FONT, 'size': 18, 'color': '#000000'}


def book(pid, md, designs=(), **extra):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    data = {'name': pid, 'title': pid, 'preset': 'classic-literary', 'manuscript_file': pid + '.md',
            'manuscript_type': 'markdown', 'format': 'pdf', 'front_matter': 'none',
            'page_designs': list(designs)}
    data.update(extra)
    A.save_project_file(pid, data)


def design(name, *els, **kw):
    return dict({'name': name, 'saved': '2026-11-20T10:00:00',
                 'elements': [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#ffffff'}] + list(els)},
                **kw)


from flask import request
result = {}
SCRIPT = r'''
var f = document.getElementById('f'), out = {};
function load(src, before) {
  return new Promise(function (res) {
    if (before) before();
    f.onload = function () {
      var w = f.contentWindow;
      w.confirm = function () { out.asked = (out.asked || 0) + 1; return true; };
      var t = setInterval(function () { if (w.WD_READY) { clearInterval(t); res(w); } }, 50);
    };
    f.src = src;
  });
}
function later(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
var STORE = 'ts-page-design-v1';
// 21.6 a new page's draft, brought back
load('/wrap-designer?page=h', function () {
  localStorage.setItem(STORE, JSON.stringify({design: {elements: [{id: 'x', type: 'rect', fill: 'front',
    color: '#00ff00'}]}, settings: {}, page: {pid: 'h', name: '', base: '', dirty: true}}));
}).then(function (w) {
  var d = w.document;
  out.recovered = w.WD_EDITOR.design().elements[0].color;
  out.asked = 0;
  var pick = d.getElementById('wd-page-pick'); pick.value = 'lone';
  pick.dispatchEvent(new w.Event('change'));
  out.askedOnLeave = out.asked;
  // 21.4 a clean working copy from an older save gives way
  return load('/wrap-designer?page=h&design=other', function () {
    localStorage.setItem(STORE, JSON.stringify({design: {elements: [{id: 'x', type: 'rect', fill: 'front',
      color: '#0000ff'}]}, settings: {}, page: {pid: 'h', name: 'other', base: '2026-01-01T00:00:00', dirty: false}}));
  });
}).then(function (w) {
  out.staleGaveWay = w.WD_EDITOR.design().elements.some(function (e) { return e.text === 'Other'; });
  localStorage.removeItem(STORE);
  return load('/wrap-designer?page=h&design=lone');
}).then(function (w) {
  var d = w.document, E = w.WD_EDITOR;
  // 21.14 undo a field's kind
  E.select(['fld']);
  var kind = Array.prototype.find.call(d.querySelectorAll('#wd-props select'), function (s) {
    return Array.prototype.some.call(s.options, function (o) { return o.value === 'check'; });
  });
  kind.value = 'check';
  kind.dispatchEvent(new w.Event('input')); kind.dispatchEvent(new w.Event('change'));
  out.checkSize = [E.design().elements.find(function (e) { return e.id === 'fld'; }).w];
  E.undo();
  var f2 = E.design().elements.find(function (e) { return e.id === 'fld'; });
  out.undone = [f2.kind, f2.w, f2.h];
  // 21.5 the picker switches: the address follows
  var pick = d.getElementById('wd-page-pick'); pick.value = 'other';
  out.asked = 0; w.confirm = function () { out.asked++; return true; };
  pick.dispatchEvent(new w.Event('change'));
  return later(300).then(function () {
    out.addr = w.location.search;
    // 21.2 a late answer to a save
    var held = null, realFetch = w.fetch;
    w.fetch = function (url, opts) {
      if (String(url).indexOf('/save') > -1)
        return new Promise(function (res) { held = function () { realFetch(url, opts).then(res); }; });
      return realFetch(url, opts);
    };
    d.getElementById('wd-page-save').click();          // saving "other"
    pick.value = 'lone'; pick.dispatchEvent(new w.Event('change'));
    return later(300).then(function () {
      held();
      return later(800);
    }).then(function () {
      w.fetch = realFetch;
      out.afterLate = [pick.value, d.getElementById('wd-page-name').value,
                       E.design().elements.some(function (e) { return e.text === 'Lone'; })];
      return load('/wrap-designer?page=h&design=sp');
    });
  });
}).then(function (w) {
  var d = w.document, E = w.WD_EDITOR, g = E.geometry();
  // 21.13 left-page art on a spread whose ground covers the sheet
  var art = d.getElementById('wd-art-pick');
  var op = d.createElement('option'); op.value = 'fleuron.png'; op.textContent = 'f'; art.appendChild(op);
  art.value = 'fleuron.png';
  d.getElementById('wd-art-left').click();
  var els = E.design().elements;
  out.artAbove = els.findIndex(function (e) { return e.type === 'image' && e.fill === 'back'; })
               > els.findIndex(function (e) { return e.id === 'bg'; });
  E.undo();
  // 21.11 a box dragged from the right page to the left, kept with the left page
  var img = E.design().elements.find(function (e) { return e.id === 'img'; });
  img.x = -(g.panel_w) + 1;
  E.commit();
  E.setKind('page-left');
  var kept = E.design().elements.find(function (e) { return e.id === 'img'; });
  out.keptLeft = kept ? [kept.anchor, kept.x] : null;
  out.pageW = E.geometry().panel_w;
  var x = new XMLHttpRequest(); x.open('POST', '/_pd_result', false); x.send(JSON.stringify(out));
}).catch(function (e) {
  out.error = String(e);
  var x = new XMLHttpRequest(); x.open('POST', '/_pd_result', false); x.send(JSON.stringify(out));
});
'''

@A.app.route('/_pd_harness')
def _pd_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" '
            'style="width:1300px;height:900px"></iframe><script>' + SCRIPT + '</script>')

@A.app.route('/_pd_result', methods=['POST'])
def _pd_result():
    result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'



try:
    # ---- 21.1 ---------------------------------------------------------------
    print('21.1 a new page under a taken name')
    book('a', '~~~ page src="moon-map"\n~~~\n', [design('moon-map', text('t', 1, 'Original'))])
    r = c.post('/page-designer/a/save', json={'name': 'Moon Map', 'was': '',
                                              'design': {'elements': [text('t', 1, 'Replacement')]}}).get_json()
    kept = W.find_page(A.load_project('a')['page_designs'], 'moon-map')
    check('it is refused', not r['ok'] and 'already has a page' in r['error'], r)
    check('and the saved page is untouched', kept['elements'][-1]['text'] == 'Original', kept)
    r = c.post('/page-designer/a/save', json={'name': 'moon-map', 'was': 'moon-map',
                                              'design': {'elements': [text('t', 1, 'Edited')]}}).get_json()
    check('saving the open page over itself still works', r['ok']
          and W.find_page(A.load_project('a')['page_designs'], 'moon-map')['elements'][-1]['text'] == 'Edited')

    # ---- 21.3 ---------------------------------------------------------------
    print('21.3 two saves at once')
    book('b', 'Text.\n', [design('alpha', text('t', 1, 'A0')), design('beta', text('t', 1, 'B0'))])
    real_save = A.save_project_file
    def slow_save(pid, data):
        time.sleep(0.3)                  # both requests have read the book by now
        real_save(pid, data)
    A.save_project_file = slow_save
    try:
        res = {}
        def go(n, words):
            res[n] = A.app.test_client().post('/page-designer/b/save', json={
                'name': n, 'was': n, 'design': {'elements': [text('t', 1, words)]}}).get_json()
        ts = [threading.Thread(target=go, args=('alpha', 'A1')),
              threading.Thread(target=go, args=('beta', 'B1'))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        A.save_project_file = real_save
    got = {d['name']: d['elements'][-1]['text'] for d in A.load_project('b')['page_designs']}
    check('both edits survive', got == {'alpha': 'A1', 'beta': 'B1'}, (got, res))

    # ---- 21.7 ---------------------------------------------------------------
    print('21.7 + Page and a placed name')
    book('c', 'Words.\n\n~~~ page src="page-1"\n~~~\n')           # its design was deleted
    data = c.get('/project/c/plan/data').get_json()
    r = c.post('/project/c/plan/add', json={'kind': 'page', 'rev': data['rev']}).get_json()
    check('the new page gets a fresh name', r.get('name') == 'page-2', r.get('name'))

    # ---- 21.9 ---------------------------------------------------------------
    print('21.9 malformed saved elements')
    book('d', '~~~ page src="odd"\n~~~\n', [
        {'name': 'odd', 'saved': 's', 'elements': [None, text('a', 1, 'One'), dict(text('b', '2', 'Two'))]}])
    info = c.get('/page-designer/d').get_json()
    odd = next(x for x in info['designs'] if x['name'] == 'odd')
    check('the designer is given only element objects', all(isinstance(e, dict) for e in odd['elements']),
          odd['elements'])
    r = c.get('/project/d/plan')
    check('the plan opens', r.status_code == 200, r.status_code)
    check('page_words sorts a string y beside a number',
          W.page_words({'elements': [text('a', 1, 'One'), text('b', '2', 'Two')]}) == 'One Two')

    # ---- 21.10 --------------------------------------------------------------
    print('21.10 a repeated src')
    t = '~~~ page src="draft-map" src="moon-map"\n~~~\n'
    out = page_plan.rename(t, 'moon-map', 'moon-chart', key=W.page_name)
    check('the last src is the one renamed', out == '~~~ page src="draft-map" src="moon-chart"\n~~~\n', out)

    # ---- 21.12 --------------------------------------------------------------
    print('21.12 numbers the plan can stand behind')
    art = os.path.join(A.PRESET_DIR, 'with-art.json')
    p = A.load_preset('classic-literary')
    p = copy.deepcopy(p); p['name'] = 'With art'; p['chapter_art'] = {'image': 'fleuron.png'}
    with open(art, 'w', encoding='utf-8') as f:
        json.dump(p, f)
    book('e', '~~~ page src="one"\n~~~\n', [design('one', text('t', 1, 'One'))], preset='with-art')
    d = c.get('/project/e/plan/data').get_json()
    check('with chapter-opening art the pages are not numbered', not d['numbered'] and d['pages'] is None, d)
    book('f', '~~~ page src="one"\n~~~\n', [design('one', text('t', 1, 'One'))],
         acknowledgments='Thanks to the tide.')
    d = c.get('/project/f/plan/data').get_json()
    check('with back matter the designs keep their numbers', d['numbered']
          and any(s.get('pages') == [1] for s in d['slots']), d['slots'])
    check('but the total is not claimed', d['pages'] is None, d['pages'])
    book('g', '~~~ page src="one"\n~~~\n', [design('one', text('t', 1, 'One'))])
    d = c.get('/project/g/plan/data').get_json()
    check('a plain book is still counted', d['numbered'] and d['pages'] == 1, d['pages'])

    # ---- the designer in a browser: 21.2 / 21.4 / 21.5 / 21.6 / 21.11 / 21.13 / 21.14
    print('\nthe designer, in a browser')
    browser = find_browser()
    if not browser or os.environ.get('TS_SKIP_BROWSER'):
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        from werkzeug.serving import make_server
        spread_els = [{'id': 'bg', 'type': 'rect', 'fill': 'sheet', 'color': '#ffffff'},
                      {'id': 'img', 'type': 'rect', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 1, 'h': 1,
                       'color': '#ff0000'}]
        field = {'id': 'fld', 'type': 'field', 'anchor': 'front', 'x': 1, 'y': 2, 'w': 2.5, 'h': 0.3,
                 'name': 'hp', 'kind': 'line'}
        book('h', 'Text.\n', [design('lone', text('t', 1, 'Lone'), field),
                              design('other', text('t', 1, 'Other')),
                              dict(name='sp', spread=True, saved='2026-11-20T10:00:00', elements=spread_els)])
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(TMP, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_pd_harness'],
                           capture_output=True, timeout=300)
        finally:
            server.shutdown()
        r = result
        check('the designer ran', bool(r) and 'error' not in r, r)
        if r and 'error' not in r:
            check('21.6 a recovered new-page draft is asked about before it is left',
                  r.get('recovered') == '#00ff00' and r.get('askedOnLeave') == 1, r)
            check('21.4 a clean copy of an older save gives way to the saved page', r.get('staleGaveWay'), r)
            check('21.14 undo brings back the text line', r.get('undone') == ['line', 2.5, 0.3]
                  and r.get('checkSize') != [2.5], (r.get('undone'), r.get('checkSize')))
            check('21.5 the address names the page now open', 'design=other' in (r.get('addr') or ''),
                  r.get('addr'))
            check('21.2 a late save answer leaves the page now open as it is',
                  r.get('afterLate') == ['lone', 'lone', True], r.get('afterLate'))
            other = W.find_page(A.load_project('h')['page_designs'], 'other')
            check('21.2 and the page it was for is saved with its own art',
                  any(e.get('text') == 'Other' for e in other['elements']), other)
            check('21.13 left-page art goes above the spread\'s ground', r.get('artAbove'), r)
            check('21.11 a box drawn on the left page stays with it',
                  r.get('keptLeft') is not None and r['keptLeft'][0] == 'front'
                  and 0 <= r['keptLeft'][1] < r.get('pageW', 0), (r.get('keptLeft'), r.get('pageW')))
finally:
    for k, v in saved_paths.items():
        setattr(A, k, v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
