"""Wrap designer edges (bug hunt item 12)  (run: python test_wrap_edges.py).

test_wrap_designer.py proves the designer agrees with the PDF; this covers its
edges: resizing a turned picture, a rule, a rotated spine line and the locked
barcode; a barcode box made too small to scan; snapping while zoomed; undo
across presets, Customise and quick successions of actions; and a design past
the 400-element limit.

The browser half drives the real page in headless Chrome in real time (the
page's undo waits on timers) and needs Chrome or Edge (TS_BROWSER to point at
one); without one it is skipped and says so.
"""

import sys, os, json, tempfile, threading, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging

import app as A
import wrap_design as WDm
from test_rich_editor import find_browser
from werkzeug.serving import make_server
from flask import request
logging.disable(logging.CRITICAL)        # after test_rich_editor's import resets it

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-wrapedges-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = os.path.join(tmp, 'assets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.OUT_DIR, A.COVER_ASSET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d)
from PIL import Image
Image.new('RGB', (1200, 800), (90, 40, 30)).save(os.path.join(A.COVER_ASSET_DIR, 'wide.png'))
PID = 'salt-road'
with open(os.path.join(A.PROJECT_MS_DIR, PID + '.md'), 'w', encoding='utf-8') as f:
    f.write('# One\n\nText.\n')
A.save_project_file(PID, {'name': 'The Salt Road', 'preset': 'classic-literary',
                          'title': 'The Salt Road', 'author': 'Ellinor Vale',
                          'manuscript_file': PID + '.md', 'manuscript_type': 'file',
                          'front_matter': 'none', 'cover_mode': 'none', 'format': 'pdf',
                          'print_retailer': 'kdp', 'print_binding': 'paperback',
                          'print_paper': 'cream'})

# The browser half: the page in an iframe, the steps below run once it is
# ready, the results posted back. Routes go in before the first request.
STEPS = r'''
var out = {}, svg = d.getElementById('wd-svg');
w.confirm = function () { return true; };
var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
var find = function (id) { return E.design().elements.find(function (e) { return e.id === id; }); };
var count = function () { return E.design().elements.length; };
var snap = function () { return JSON.stringify(E.design()); };
var last = function () { return E.design().elements[count() - 1]; };
var fire = function (type, x, y, target) {
  target.dispatchEvent(new w.PointerEvent(type, {clientX:x, clientY:y, bubbles:true, pointerId:1, isPrimary:true}));
};
var handleDrag = function (dx, dy) {
  var h = svg.querySelector('[data-handle]');
  if (!h) return false;
  var b = h.getBoundingClientRect(), x = b.left + b.width / 2, y = b.top + b.height / 2;
  fire('pointerdown', x, y, h); fire('pointermove', x + dx, y + dy, svg); fire('pointerup', x + dx, y + dy, svg);
  return true;
};
var checks = function () { E.select([]); return d.getElementById('wd-checks').textContent; };
(async function () {
  // ---- resizing
  var bc = E.design().elements.find(function (e) { return e.type === 'barcode'; });
  E.select([bc.id]);
  out.locked_handle = !!svg.querySelector('[data-handle]');
  bc.locked = false; E.select([bc.id]);
  var bw = bc.w;
  handleDrag(40, 20);
  out.barcode_resized = find(bc.id).w > bw;
  E.undo(); bc = find(bc.id);
  d.getElementById('wd-add-rule').click();
  var rule = last(), rw = rule.w;
  handleDrag(40, 40);
  rule = find(rule.id);
  out.rule = {longer: rule.w > rw, h: 'h' in rule};
  d.getElementById('wd-art-pick').value = 'wide.png';
  d.getElementById('wd-art-place').click();
  var pic = last(); pic.turn = 90; E.select([pic.id]);
  handleDrag(50, -20);
  pic = find(pic.id);
  var ppi = svg.getBoundingClientRect().width / E.geometry().wrap_w;
  out.turned = {w: pic.w, h: pic.h, ew: 3 + 50 / ppi, eh: 3 - 20 / ppi, turn: pic.turn};
  E.select(['spine-text']);
  var sw = find('spine-text').w;
  handleDrag(5, -30);
  out.spine = {w: find('spine-text').w, ew: sw - 30 / ppi, h: 'h' in find('spine-text')};
  // ---- the barcode box too small to scan
  bc.isbn = '9780306406157'; bc.w = 1.0; bc.h = 0.9; checks(); await sleep(800);
  out.narrow = checks();
  bc.w = 2; bc.h = 0.4; checks(); await sleep(800);
  out.tiny = checks();
  bc.w = 2; bc.h = 1.2; checks(); await sleep(800);
  out.fine = checks();
  // ---- snapping while zoomed: within six screen pixels, at every zoom
  out.snap = {};
  [0.5, 1, 2, 4].forEach(function (z) {
    E.setZoom(z);
    out.snap[z] = [3, 12].map(function (px) {
      var g = E.geometry(), t = find('title');
      t.x = 0.9; E.select([]);
      var safe = E.safeBox(t)[0], left = E.bbox(t)[0];
      var p = svg.getBoundingClientRect().width / g.wrap_w;
      var node = svg.querySelector('[data-id="title"] rect'), b = node.getBoundingClientRect();
      var sx = b.left + 5, sy = b.top + b.height / 2, dx = (safe - left) * p + px;
      fire('pointerdown', sx, sy, node); fire('pointermove', sx + dx, sy, svg);
      var hit = Math.abs(E.bbox(find('title'))[0] - safe) < 1e-6;
      fire('pointerup', sx + dx, sy, svg);
      return hit;
    });
  });
  E.setZoom(1);
  // ---- undo
  await sleep(500);
  E.select(['title']);
  var ta = d.querySelector('#wd-props textarea'); ta.value = 'Typed Title'; ta.dispatchEvent(new w.Event('input'));
  var n = count();
  await E.quotePreset('one'); await sleep(600);
  E.undo(); out.typed_then_preset = [find('title').text, count() === n];
  E.redo(); out.preset_redone = count() === n + 2;
  var n0 = count();
  d.getElementById('wd-add-text').click(); await sleep(100);
  for (var i = 0; i < 3; i++) d.dispatchEvent(new w.KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));
  await sleep(600);
  var added = last(), ax = added.x;
  E.undo(); out.nudges = [count() === n0 + 1, Math.abs(find(added.id).x - (ax - 0.03)) < 1e-9];
  E.undo(); out.add_undone = count() === n0;
  // several deleted with the key: one step back
  E.select([last().id, E.design().elements[count() - 2].id]);
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key:'Delete', bubbles:true}));
  E.undo(); out.multi_delete_undone = count() === n0;
  var tpls = Array.prototype.map.call(d.getElementById('wd-from').options, function (o) { return o.value; })
    .filter(function (v) { return v && v !== '@book'; });
  var s0 = snap();
  await E.customise(tpls[0]); await sleep(300);
  var s1 = snap();
  await E.customise(tpls[1]); await sleep(300);
  var s2 = snap();
  E.undo(); var u1 = snap() === s1; E.undo(); var u2 = snap() === s0;
  E.redo(); var r1 = snap() === s1; E.redo(); var r2 = snap() === s2;
  out.customise = [u1, u2, r1, r2];
  var pre = snap();
  d.getElementById('wd-reset').click(); await sleep(800);
  var post = snap();
  E.undo(); await sleep(200);
  out.reset = [pre !== post, snap() === pre];
  d.getElementById('wd-binding').value = 'jacket';
  d.getElementById('wd-binding').dispatchEvent(new w.Event('change'));
  await sleep(800);
  var j0 = snap();
  await E.flapPreset('front'); await sleep(400);
  var j1 = snap();
  await E.flapPreset('back'); await sleep(400);
  E.undo(); var f1 = snap() === j1; E.undo();
  out.flaps = [f1, snap() === j0];
  // ---- past the element limit
  var D = E.design(), base = D.elements.find(function (e) { return e.type === 'text'; });
  while (D.elements.length < 401) {
    var c = JSON.parse(JSON.stringify(base)); c.id = 'copy-' + D.elements.length; D.elements.push(c);
  }
  out.big = checks();
  var r = await fetch('/wrap-designer/project/salt-road/save', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({design: D, settings: {}})});
  out.big_save = await r.json();
  out.pages_step = d.getElementById('wd-pages').step;
  done(out);
})().catch(function (e) { done({error: String(e) + ' ' + e.stack, partial: out}); });
'''
RESULT = {}
PAGE = ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer" '
        'style="width:1300px;height:900px"></iframe><script>'
        'var f=document.getElementById("f");f.onload=function(){var w=f.contentWindow,d=f.contentDocument;'
        'var t=setInterval(function(){if(!w.WD_READY)return;clearInterval(t);'
        'var done=function(o){var x=new XMLHttpRequest();x.open("POST","/_we_result",false);'
        'x.send(JSON.stringify(o));};'
        'try{(function(w,d,E,done){' + STEPS + '})(w,d,w.WD_EDITOR,done);}'
        'catch(e){done({error:String(e)+" "+e.stack});}},100);};</script>')


@A.app.route('/_we_harness')
def _we_harness():
    return PAGE


@A.app.route('/_we_result', methods=['POST'])
def _we_result():
    RESULT.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


print('[the barcode box: too small to scan]')
EAN = '9780306406157'
p = WDm.barcode_parts({'isbn': EAN}, 2.0, 1.2)
check('the standard box draws, with no warning', p['bars'] and not p['error'] and not p.get('warning'))
p = WDm.barcode_parts({'isbn': EAN, 'addon': '90000'}, 2.0, 1.2)
check('... and with a price code', p['bars'] and not p['error'] and not p.get('warning'))
p = WDm.barcode_parts({'isbn': EAN}, 0.5, 0.3)
check('a box with no room for bars says so and draws none (was: bars of negative height)',
      not p['bars'] and 'too small' in (p['error'] or ''), p)
p = WDm.barcode_parts({'isbn': EAN}, 1.0, 1.2)
check('a box under 80% of the standard width is drawn, with a warning',
      p['bars'] and 'too narrow' in p.get('warning', ''), p.get('warning'))
p = WDm.barcode_parts({'isbn': EAN}, 2.0, 0.85)
check('stubby bars are drawn, with a warning', p['bars'] and 'too short' in p.get('warning', ''),
      p.get('warning'))
check('every bar has a height', all(b[3] > 0 for h in (0.3, 0.6, 0.9, 1.2)
                                    for b in WDm.barcode_parts({'isbn': EAN}, 2.0, h)['bars']))
c = A.app.test_client()
r = c.post('/wrap-designer/barcode', json={'isbn': EAN, 'w': 2.0, 'h': 0.85}).get_json()
check('the editor is sent the warning', 'too short' in (r.get('warning') or ''), r)

print('\n[a design past the element limit]')
starter = {'elements': [{'id': f't{i}', 'type': 'rect', 'anchor': 'front', 'x': 0, 'y': 0,
                         'w': 1, 'h': 1} for i in range(WDm.MAX_ELEMENTS)]}
r = c.post(f'/wrap-designer/project/{PID}/save', json={'design': starter, 'settings': {}}).get_json()
check(f'{WDm.MAX_ELEMENTS} elements save', r.get('ok'), r)
starter['elements'].append(dict(starter['elements'][0], id='one-more'))
r = c.post(f'/wrap-designer/project/{PID}/save', json={'design': starter, 'settings': {}}).get_json()
check('one more is refused, saying why (was: "That design could not be read.")',
      not r.get('ok') and '401 elements' in r.get('error', ''), r)
r = c.post(f'/wrap-designer/project/{PID}/save', json={'design': 'junk', 'settings': {}}).get_json()
check('junk is still "could not be read"', r.get('error') == 'That design could not be read.', r)

browser = find_browser()
print('\n[the designer in a browser]')
if not browser:
    print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
else:
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = subprocess.Popen([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                             '--remote-debugging-port=0', '--window-size=1400,1000',
                             '--user-data-dir=' + os.path.join(tmp, 'browser'),
                             f'http://127.0.0.1:{server.server_port}/_we_harness'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(360):
            if RESULT:
                break
            time.sleep(0.5)
    finally:
        proc.kill()
        proc.wait()
        server.shutdown()
    R = RESULT
    check('the harness ran to the end', R and not R.get('error'), R.get('error') or 'no answer')
    if R and not R.get('error'):
        print('\n[RESIZE]')
        check('the locked barcode shows no resize handle (was: resized by accident)',
              R['locked_handle'] is False)
        check('... unlocked, it resizes', R['barcode_resized'])
        check('a rule gets longer and keeps no height (was: a stray "h")',
              R['rule']['longer'] and not R['rule']['h'], R['rule'])
        t = R['turned']
        check('a turned picture resizes its box as it is drawn, turn kept',
              abs(t['w'] - t['ew']) < 0.01 and abs(t['h'] - t['eh']) < 0.01 and t['turn'] == 90, t)
        s = R['spine']
        check('the spine line lengthens along its length, downwards', abs(s['w'] - s['ew']) < 0.01
              and not s['h'], s)
        print('\n[BARCODE SIZE in the checks]')
        check('too narrow is flagged', 'too narrow for a barcode' in R['narrow'], R['narrow'])
        check('too small is flagged', 'too small for a barcode' in R['tiny'], R['tiny'])
        check('the standard size is not', 'Barcode:' not in R['fine'] and 'carries the ISBN' in R['fine'],
              R['fine'])
        print('\n[SNAPPING while zoomed]')
        for z, (near, far) in sorted(R['snap'].items(), key=lambda kv: float(kv[0])):
            check(f'at {float(z) * 100:g}%: catches 3 px away, not 12', near and not far, (near, far))
        print('\n[UNDO]')
        check('typing then a preset at once: one undo takes the preset only (was: both)',
              R['typed_then_preset'] == ['Typed Title', True], R['typed_then_preset'])
        check('... and redo puts it back', R['preset_redone'])
        check('add, then nudge at once: one undo takes the nudges only (was: both)',
              all(R['nudges']), R['nudges'])
        check('... a second takes the added text', R['add_undone'])
        check('several deleted with the Delete key come back with one undo', R['multi_delete_undone'])
        check('Customise twice: undo and redo step through both', all(R['customise']), R['customise'])
        check('Start over: one undo brings the design back', all(R['reset']), R['reset'])
        check('the two flap presets undo one at a time', all(R['flaps']), R['flaps'])
        print('\n[THE ELEMENT LIMIT]')
        check('past it, the checks say so', '401 elements' in R['big'] and 'at most 400' in R['big'],
              R['big'])
        check('... and Save says why it refused', '401 elements' in R['big_save'].get('error', ''),
              R['big_save'])
        check('the Pages arrows step by 2 (was 10, from 24: 24, 34 ... 324)', R['pages_step'] == '2',
              R['pages_step'])

print()
print('FAILED: ' + ', '.join(fails) if fails else 'All wrap designer edge checks passed.')
sys.exit(1 if fails else 0)
