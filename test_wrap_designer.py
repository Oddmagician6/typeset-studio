"""Wrap designer tests  (run: python test_wrap_designer.py).

The designer's promise is that what the editor shows is what prints, so the
checks are about agreement: the server builds the PDF the design describes, its
line breaks are the engine's, the geometry is the one the cover editor and the
print package use, and - in a real browser - the editor breaks every text box
exactly where the PDF does and moves things where you drag them.

The browser half needs Chrome or Edge (TS_BROWSER to point at one); without one
it is skipped and says so.
"""

import sys, os, json, shutil, tempfile, threading, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine
import wrap_design as WDm
from test_rich_editor import find_browser

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-wrapdesign-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.COVER_ASSET_DIR = os.path.join(tmp, 'assets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.OUT_DIR, A.COVER_ASSET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d)

# A book to design a cover for (phase B): short, so its spine is too thin for text.
PID = 'salt-road'
with open(os.path.join(A.PROJECT_MS_DIR, PID + '.md'), 'w', encoding='utf-8') as f:
    f.write('# The Salt Road\n\nThe opening paragraph, long enough to set a line.\n\n'
            '# The Second Mile\n\nAnother chapter.\n')
A.save_project_file(PID, {'name': 'The Salt Road', 'preset': 'classic-literary',
                          'title': 'The Salt Road', 'author': 'Ellinor Vale',
                          'manuscript_file': PID + '.md', 'manuscript_type': 'file',
                          'front_matter': 'none', 'cover_mode': 'none', 'format': 'pdf',
                          'print_retailer': 'kdp', 'print_binding': 'paperback',
                          'print_paper': 'cream', 'print_blurb': 'A road of salt.'})
# The browser half's harness. Flask takes no new routes after its first request,
# so they are added here, ahead of the server-side checks.
from werkzeug.serving import make_server
from flask import request
result = {}
SCRIPT = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, design = E.design();
    out.elements = design.elements.length;
    d.getElementById('wd-proof-btn').click();
    var w2 = setInterval(function () {
      var msg = d.getElementById('wd-proof-msg').textContent;
      if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
      clearInterval(w2);
      out.proof = msg;
      out.download = !!d.querySelector('#wd-proof a[href*="/download/"]');
      var title = design.elements.find(function (e) { return e.id === 'title'; });
      var g0 = E.geometry(), x0 = g0.front_x;
      d.getElementById('wd-pages').value = 640;
      d.getElementById('wd-pages').dispatchEvent(new w.Event('input'));
      E.regeometry().then(function () {
        var g1 = E.geometry();
        out.front_moved_with_spine = Math.abs((g1.front_x - x0) - (g1.spine_w - g0.spine_w)) < 1e-9
                                      && g1.spine_w > g0.spine_w;
        var svg = d.getElementById('wd-svg');
        var t = svg.querySelector('[data-id="title"] rect');
        var b = t.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height / 2;
        var tx = title.x;
        var fire = function (type, x, y, target) {
          target.dispatchEvent(new w.PointerEvent(type, {clientX:x, clientY:y, bubbles:true, pointerId:1, isPrimary:true}));
        };
        fire('pointerdown', cx, cy, t); fire('pointermove', cx + 100, cy, svg); fire('pointerup', cx + 100, cy, svg);
        var perPx = g1.wrap_w / svg.getBoundingClientRect().width;
        out.drag_ok = Math.abs((title.x - tx) - 100 * perPx) < 0.01;
        title.text = 'Title with a stray क glyph';
        title.x = -0.4;
        d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
        out.checks = d.getElementById('wd-checks').textContent;
        var x = new XMLHttpRequest(); x.open('POST', '/_wd_result', false); x.send(JSON.stringify(out));
      });
    }, 100);
  }, 100);
};'''
harness = ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer" '
           'style="width:1300px;height:900px"></iframe><script>' + SCRIPT + '</script>')

@A.app.route('/_wd_harness')
def _wd_harness():
    return harness

@A.app.route('/_wd_result', methods=['POST'])
def _wd_result():
    result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


SCRIPT2 = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var design = w.WD_EDITOR.design();
    out.title = (design.elements.find(function (e) { return e.id === 'title'; }) || {}).text;
    out.trim_locked = d.getElementById('wd-trim').disabled;
    out.paper = d.getElementById('wd-paper').value;
    out.save_shown = d.getElementById('wd-save-group').style.display !== 'none';
    d.getElementById('wd-save').click();
    var w2 = setInterval(function () {
      var st = d.getElementById('wd-save-status').textContent;
      if (st.indexOf('Saved') !== 0) return;
      clearInterval(w2);
      out.status = st;
      var x = new XMLHttpRequest(); x.open('POST', '/_wd_result2', false); x.send(JSON.stringify(out));
    }, 100);
  }, 100);
};'''
result2 = {}

@A.app.route('/_wd_harness2')
def _wd_harness2():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/wrap-designer?project='
            + PID + '" style="width:1300px;height:900px"></iframe><script>' + SCRIPT2 + '</script>')

@A.app.route('/_wd_result2', methods=['POST'])
def _wd_result2():
    result2.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


client = A.app.test_client()

SETTINGS = {'pages': 320, 'wrap_retailer': 'kdp', 'wrap_paper': 'white',
            'wrap_binding': 'paperback', 'wrap_trim_w': 6, 'wrap_trim_h': 9}
BLURB = ('The rain had not stopped for three days, and Aldren had begun to suspect it '
         'never would. He stood beneath the eaves of the Split Lantern Inn, watching the '
         'water carve small rivers through the mud of Briars Hollow.')
DESIGN = {'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'back', 'color': '#20283b'},
    {'id': 'art', 'type': 'image', 'fill': 'front', 'src': 'stand-in-dusk.png'},
    {'id': 'title', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 0.9, 'w': 5,
     'text': 'The Salt Road', 'font': 'EBGaramond-Bold.ttf', 'size': 46, 'leading': 1.05,
     'color': '#fbf3e2', 'align': 'center', 'tracking': 0.5},
    {'id': 'blurb', 'type': 'text', 'anchor': 'back', 'x': 0.6, 'y': 1, 'w': 4.8,
     'text': BLURB, 'font': 'CrimsonPro-Regular.ttf', 'size': 12.5, 'leading': 1.4,
     'color': '#efe7d6', 'align': 'left', 'tracking': 0},
    {'id': 'spine', 'type': 'text', 'anchor': 'spine', 'cx': 0.11, 'y': 0.6, 'w': 7.8,
     'rotate': 90, 'text': 'THE SALT ROAD', 'font': 'Spectral-Regular.ttf', 'size': 12,
     'color': '#fbf3e2', 'align': 'center', 'tracking': 1.5},
    {'id': 'gone', 'type': 'image', 'anchor': 'front', 'x': 1, 'y': 1, 'w': 1, 'h': 1,
     'src': 'no-such-picture.png'},
]}

try:
    print('[the page and its routes]')
    page = client.get('/wrap-designer').get_data(as_text=True)
    check('the tab is in the navigation', 'href="/wrap-designer"' in page)
    check('the page lists the font library', 'EBGaramond-Bold.ttf' in page)
    check('the stand-in art is made for it',
          os.path.isfile(os.path.join(A.WRAP_DESIGN_DIR, A.WRAP_STAND_IN)))
    m = client.get('/wrap-designer/metrics/EBGaramond-Regular.ttf').get_json()
    check('width tables are served', m and m['widths'] and 'ascent' in m)
    check('a font outside the library is refused',
          client.get('/wrap-designer/font/..%2Fapp.py').status_code == 404
          and client.get('/wrap-designer/metrics/notafont.txt').status_code == 404)
    check('art outside the art folders is refused',
          client.get('/wrap-designer/art/..%2F..%2Fapp.py').status_code == 404)

    print('\n[geometry is the cover editor\'s]')
    geo = client.post('/wrap-designer/geometry', json=SETTINGS).get_json()
    want = A._wrap_dims({k: v for k, v in SETTINGS.items() if k != 'pages'}, 320)
    check('the spine is _wrap_dims\' spine', abs(geo['dims']['spine_w'] - want['spine_w']) < 1e-9,
          (geo['dims']['spine_w'], want['spine_w']))
    cream = client.post('/wrap-designer/geometry', json=dict(SETTINGS, wrap_paper='cream')).get_json()
    check('thicker paper, wider spine', cream['geometry']['spine_w'] > geo['geometry']['spine_w'])
    jk = client.post('/wrap-designer/geometry',
                     json=dict(SETTINGS, wrap_binding='jacket')).get_json()
    check('a jacket has flaps, and KDP is warned off it',
          jk['geometry']['flap'] > 0 and any('jacket' in w for w in jk['warnings']), jk['warnings'])

    print('\n[the PDF]')
    res = client.post('/wrap-designer/build', json={'design': DESIGN, 'settings': SETTINGS,
                                                    'name': 'The Salt Road'}).get_json()
    check('it builds', res and res['ok'], res)
    pdf = os.path.join(A.OUT_DIR, os.path.basename(res['pdf']))
    import fitz
    with fitz.open(pdf) as doc:
        g = engine.wrap_geometry(A._wrap_dims({'wrap_paper': 'white'}, 320))
        check('the page is the wrap, to the point',
              abs(doc[0].rect.width - g['wrap_w'] * 72) < 0.01
              and abs(doc[0].rect.height - g['wrap_h'] * 72) < 0.01,
              (doc[0].rect, g['wrap_w'], g['wrap_h']))
        text = ' '.join(doc[0].get_text().split())
    check('the text is in it', 'The Salt Road' in text and 'Split Lantern' in text, text[:120])
    check('a picture that isn\'t there is skipped, not fatal', res['ok'])
    eng = engine._wrap_tracked(BLURB, WDm.font_name('CrimsonPro-Regular.ttf'), 12.5, 4.8 * 72, 0)
    check('the blurb is broken by the engine\'s own breaker', res['lines']['blurb'] == eng)
    check('the download link works', client.get(res['pdf']).status_code == 200)
    check('the preview picture is there', res['png'].startswith('data:image/png;base64,'))
    gg = engine.wrap_geometry(A._wrap_dims({}, 320))
    x = WDm.el_rect(gg, DESIGN['elements'][4])[0]
    check('spine text placed from the spine\'s centre',
          abs(x - (gg['spine_x'] + gg['spine_w'] / 2 + 0.11)) < 1e-9)

    print('\n[a design saved with a book (phase B)]')
    info = client.get(f'/wrap-designer/project/{PID}').get_json()
    check('a book opens with its own settings',
          info['settings']['wrap_paper'] == 'cream' and info['settings']['wrap_trim_w'] == 6.0
          and info['design'] is None and info['title'] == 'The Salt Road', info)
    bad = client.post(f'/wrap-designer/project/{PID}/save', json={'design': {'oops': 1}}).get_json()
    check("a design that isn't one is refused", not bad['ok'], bad)
    saved = client.post(f'/wrap-designer/project/{PID}/save', json={
        'design': DESIGN, 'use_as_cover': True,
        'settings': {'wrap_retailer': 'ingramspark', 'wrap_paper': 'white',
                     'wrap_binding': 'paperback'}}).get_json()
    check('it saves', saved['ok'] and saved['is_cover'], saved)
    proj = A.load_project(PID)
    check('the design and the print settings are on the book',
          proj['wrap_design']['elements'][2]['text'] == 'The Salt Road'
          and proj['print_retailer'] == 'ingramspark' and proj['print_paper'] == 'white'
          and proj['cover_mode'] == 'wrap',
          {k: proj.get(k) for k in ('print_retailer', 'print_paper', 'cover_mode')})
    from PIL import Image
    front = os.path.join(A.PROJECT_MS_DIR, proj['wrap_front_file'])
    with Image.open(front) as im:
        check('its front is rendered at the trim, 300 dpi', im.size == (1800, 2700), im.size)
    meta, cover = A._project_meta(proj)
    check("the book's cover is now that front, with no title laid over it",
          meta['cover_mode'] == 'image' and cover == front and not meta['cover_overlay'])
    page = client.get(f'/project/{PID}/edit').get_data(as_text=True)
    check('the edit page offers it as the cover', 'value="wrap"' in page and 'My wrap design' in page)

    import zipfile
    pkg = A.build_print_package(proj, 'publish')
    with zipfile.ZipFile(os.path.join(A.OUT_DIR, pkg['zip_name'])) as z:
        names = z.namelist()
        wrapname = next(n for n in names if n.endswith('-cover-wrap.pdf'))
        wrapdoc = fitz.open(stream=z.read(wrapname), filetype='pdf')
        gp = engine.wrap_geometry(A._wrap_dims(
            {'wrap_retailer': 'ingramspark', 'wrap_paper': 'white'}, pkg['pages']))
        check('Send to print builds the design as the wrap, sized to the real page count',
              abs(wrapdoc[0].rect.width - gp['wrap_w'] * 72) < 0.01
              and 'Split Lantern' in ' '.join(wrapdoc[0].get_text().split()),
              (wrapdoc[0].rect.width / 72, gp['wrap_w']))
        wrapdoc.close()
        check('the ebook and the listing JPG come with it',
              any(n.endswith('.epub') for n in names) and any(n.endswith('.jpg') for n in names),
              names)
    rows = {c['label']: c for c in pkg['checks']}
    check('the package says the cover is the wrap design',
          pkg['cover_label'] == 'Wrap design')
    check('a thin book with spine text in its design is flagged',
          'Spine text' in rows and not rows['Spine text']['ok'], rows.get('Spine text'))
    check('every picture is measured at its placed size',
          any(l.startswith('Picture: stand-in-dusk.png') for l in rows), sorted(rows))

    browser = find_browser()
    print('\n[the editor, in a browser]')
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness'],
                           capture_output=True, timeout=300)
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_wd_harness2'],
                           capture_output=True, timeout=300)
        finally:
            server.shutdown()
        check('the editor loaded and ran', bool(result), browser)
        if result:
            check('every text box breaks where the PDF does',
                  result['proof'].startswith('Built. All') and 'exactly' in result['proof'],
                  result['proof'])
            check('the proof offers the PDF to download', result['download'])
            check('more pages: the front panel moves by what the spine grew',
                  result['front_moved_with_spine'])
            check('a drag moves the title by the distance dragged', result['drag_ok'])
            check('the checks catch text outside the safe zone',
                  'Outside the safe zone' in result['checks'], result['checks'])
            check('and a character the font doesn\'t have',
                  'doesn\'t have' in result['checks'], result['checks'])
        check('a book opened by its link loads in the editor', bool(result2))
        if result2:
            check('with its saved design and its own settings',
                  result2['title'] == 'The Salt Road' and result2['paper'] == 'white'
                  and result2['trim_locked'], result2)
            check('and Save to book saves it', result2['save_shown']
                  and result2['status'].startswith('Saved'), result2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
