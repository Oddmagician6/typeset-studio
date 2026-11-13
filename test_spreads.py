"""Two-page spreads (ROADMAP #74, Phase 6c)  (run: python test_spreads.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

A spread is a page design with `"spread": true`, one sheet two pages wide,
placed with `~~~ page src="name"` on a left page and the right one beside it.
Held here:

  1. the model: the spread's sheet, `back` the left page and `front` the
     right, fills to the fold, the proof and the ebook picture both pages
     wide, the alt text left page first;
  2. the engine: always a left page then a right one (a blank before when
     needed), each page its own half, cut at the fold, out past the trim with
     bleed, no folio; `side=` is ignored; two columns; press and screen;
  3. the ebook: one wide image page;
  4. the app: `spread` is kept on save and reported to the designer and the
     picker, and - in a real browser - the designer turns a page into a
     spread and back, shows the gutter and warns about words in it.
"""
import copy, json, os, shutil, subprocess, sys, tempfile, threading, traceback, zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, engine, epub, app as A, wrap_design as W
from test_rich_editor import find_browser

TMP = tempfile.mkdtemp(prefix='ts-spreads-')
results = []
B = 0.125 * 72
BLUE, RED = '#2040c0', '#c03020'
BLUE_PX, RED_PX = (32, 64, 192), (192, 48, 32)


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (('\n         ' + str(detail)) if detail and not cond else ''))
    results.append((label, bool(cond)))


def preset(cols=1):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    if cols == 2:
        p['trim'] = {'w': 8.5, 'h': 11.0}
        p['columns'] = {'count': 2, 'gap': 0.25}
    return p


def spread(name='marsh-map'):
    return {'name': name, 'spread': True, 'saved': '2026-11-12T10:00:00', 'elements': [
        {'id': 'left-bg', 'type': 'rect', 'fill': 'back', 'color': BLUE},
        {'id': 'right-bg', 'type': 'rect', 'fill': 'front', 'color': RED},
        {'id': 'lt', 'type': 'text', 'anchor': 'back', 'x': 0.5, 'y': 1, 'w': 4,
         'text': 'Westward Fens', 'font': 'EBGaramond-Regular.ttf', 'size': 20, 'color': '#ffffff'},
        {'id': 'rt', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
         'text': 'Eastern Causeway', 'font': 'EBGaramond-Regular.ttf', 'size': 20, 'color': '#ffffff'}]}


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it. ' * 30


def build(md, name, p=None, press=False, screen=False, **meta):
    out = os.path.join(TMP, name + '.pdf')
    m = dict(META, page_designs=[spread()], **meta)
    res = engine.build_pdf(manuscript.parse_markdown(md), p or preset(), out, m,
                           press=press, screen=screen)
    return out, res


def pages_with(doc, text):
    return [i + 1 for i, pg in enumerate(doc) if text in pg.get_text()]


def pixel(page, x, y, dpi=36):
    pm = page.get_pixmap(dpi=dpi)
    k = dpi / 72.0
    return pm.pixel(min(int(x * k), pm.width - 1), min(int(y * k), pm.height - 1))


def near(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------- 1
def test_model():
    print('\nthe model')
    g = W.page_geometry(6, 9, spread=True)
    check('a spread\'s sheet is two trims plus 0.125" all round',
          g['wrap_w'] == 12.25 and g['wrap_h'] == 9.25 and g['spread'] and g['spine_x'] == 6.125)
    check('back is the left page, front the right',
          W.el_rect(g, {'anchor': 'back', 'x': 1, 'y': 1}) == (1.125, 1.125, 0, 0)
          and W.el_rect(g, {'anchor': 'front', 'x': 1, 'y': 1}) == (7.125, 1.125, 0, 0))
    check('a fill covers its own page out to the bleed and the fold',
          W.el_rect(g, {'fill': 'back'}) == (0, 0, 6.125, 9.25)
          and W.el_rect(g, {'fill': 'front'}) == (6.125, 0, 6.125, 9.25)
          and W.el_rect(g, {'fill': 'sheet'}) == (0, 0, 12.25, 9.25))
    check('a single page is as it was', W.el_rect(W.page_geometry(6, 9), {'fill': 'back'}) == (0, 0, 6.25, 9.25))
    check('a design says whether it is a spread',
          W.is_spread(spread()) and not W.is_spread({'elements': []}) and not W.is_spread(None))
    check('and gets the sheet it is drawn on', W.design_geometry(spread(), 6, 9)['wrap_w'] == 12.25
          and W.design_geometry({'elements': []}, 6, 9)['wrap_w'] == 6.25)
    d = spread()
    d['elements'].insert(0, {'type': 'text', 'anchor': 'front', 'x': 0, 'y': 0.2, 'text': 'Top right'})
    check('its words read the left page first', W.page_words(d) == 'Westward Fens Top right Eastern Causeway',
          W.page_words(d))
    out = os.path.join(TMP, 'proof.pdf')
    lines = W.build_page_pdf(spread(), 6, 9, out)
    with fitz.open(out) as doc:
        pg = doc[0]
        check('the proof is one sheet, both pages side by side',
              doc.page_count == 1 and abs(pg.rect.width - 12.25 * 72) < .01
              and abs(pg.trimbox.width - 12 * 72) < .01)
        check('left blue, right red', near(pixel(pg, 3 * 72, 4 * 72), BLUE_PX)
              and near(pixel(pg, 9 * 72, 4 * 72), RED_PX))
    check('and its lines are reported', lines.get('rt') == ['Eastern Causeway'], lines)
    from PIL import Image
    jpg = W.render_page(spread(), 6, 9, os.path.join(TMP, 's.jpg'), dpi=50)
    with Image.open(jpg) as im:
        check('the ebook picture is both trimmed pages', im.size == (600, 450), im.size)
    check('a spread reaches the edge', W.reaches_edge(spread(), W.design_geometry(spread(), 6, 9)))


# ---------------------------------------------------------------- 2
def test_engine():
    print('\nin the book')
    # after a right-hand page with words on it the next page is a left one
    md = '# One\n\nA line.\n\n~~~ page src="marsh-map"\n~~~\n\n' + L
    out, res = build(md, 'next')
    with fitz.open(out) as doc:
        lp, rp = pages_with(doc, 'Westward Fens'), pages_with(doc, 'Eastern Causeway')
        check('the left half on a left-hand page, the right half on the next',
              lp == [2] and rp == [3], (lp, rp))
        check('each page has only its own half (no folio, no running head)',
              doc[1].get_text().split() == ['Westward', 'Fens']
              and doc[2].get_text().split() == ['Eastern', 'Causeway'],
              [doc[1].get_text(), doc[2].get_text()])
        w = doc[1].rect.width
        check('each page is its own colour to the fold',
              near(pixel(doc[1], w - 2, 300), BLUE_PX) and near(pixel(doc[2], 2, 300), RED_PX)
              and near(pixel(doc[1], 2, 300), BLUE_PX) and near(pixel(doc[2], w - 2, 300), RED_PX))
        words = [x for x in doc[2].get_text('words') if x[4] == 'Eastern']
        check('a right-page element stands from the right page\'s trim',
              words and abs(words[0][0] - 0.5 * 72) < 2, words[:1])
        check('what follows starts after the spread', 'tide' in doc[3].get_text())
    check('a book without bleed reports the spread', res['pages_bleed_wanted'] == ['marsh-map'], res)

    # after a left-hand page with words on it, the spread takes a blank page first
    md2 = '# One\n\n' + L + '\n\n~~~ page src="marsh-map" side="right"\n~~~\n\n' + L
    out, _ = build(md2, 'blank')
    with fitz.open(out) as doc:
        lp, rp = pages_with(doc, 'Westward Fens'), pages_with(doc, 'Eastern Causeway')
        check('a spread always opens on a left page, a blank before it when needed (side= ignored)',
              lp and lp[0] % 2 == 0 and rp == [lp[0] + 1]
              and not doc[lp[0] - 2].get_text().strip(), (lp, rp, len(doc)))

    out, res = build(md, 'bleed', bleed=True)
    with fitz.open(out) as doc:
        lpg, rpg = doc[1], doc[2]
        check('with bleed, each half runs out past the outer trim',
              near(pixel(lpg, 2, 300), BLUE_PX) and near(pixel(rpg, rpg.rect.width - 2, 300), RED_PX))
        check('and stops at the fold', near(pixel(lpg, lpg.rect.width - 2, 300), BLUE_PX)
              and near(pixel(rpg, 2, 300), RED_PX))
        tb = rpg.trimbox
        words = [x for x in rpg.get_text('words') if x[4] == 'Eastern']
        check('its words stand where the design puts them, from the trim',
              words and abs(words[0][0] - tb.x0 - 0.5 * 72) < 2, (words[:1], tb))
    check('a book with bleed has nothing to report', res['pages_bleed_wanted'] == [])

    out, res = build(md, 'press', press=True)
    with fitz.open(out) as doc:
        px = pixel(doc[2], 20, 300)
    check('press-ready: it builds, in greys',
          res['press'] and not res.get('press_error') and abs(px[0] - px[1]) < 8 and abs(px[1] - px[2]) < 8,
          (res.get('press_error'), px))
    out, _ = build(md, 'screen', screen=True)
    with fitz.open(out) as doc:
        lp = pages_with(doc, 'Westward Fens')
        check('the screen PDF keeps its colours, on facing pages',
              lp and near(pixel(doc[lp[0] - 1], 20, 300), BLUE_PX) and near(pixel(doc[lp[0]], 20, 300), RED_PX))

    md3 = '# Two\n\n' + L + '\n\n~~~ page src="marsh-map"\n~~~\n\n' + L
    out, _ = build(md3, 'cols', p=preset(2))
    with fitz.open(out) as doc:
        lp, rp = pages_with(doc, 'Westward Fens'), pages_with(doc, 'Eastern Causeway')
        check('in two columns it still takes two whole facing pages',
              lp and lp[0] % 2 == 0 and rp == [lp[0] + 1]
              and doc[lp[0] - 1].get_text().split() == ['Westward', 'Fens'], (lp, rp))

    single = {'name': 'single', 'elements': [{'id': 'x', 'type': 'text', 'anchor': 'front', 'x': 1, 'y': 1,
                                              'text': 'Lone Page', 'font': 'EBGaramond-Regular.ttf',
                                              'size': 20}]}
    out = os.path.join(TMP, 'single.pdf')
    engine.build_pdf(manuscript.parse_markdown('# One\n\nA line.\n\n~~~ page src="single"\n~~~\n\n' + L),
                     preset(), out, dict(META, page_designs=[spread(), single]))
    with fitz.open(out) as doc:
        check('a single page design beside a spread is still one page',
              pages_with(doc, 'Lone Page') == [2] and 'tide' in doc[2].get_text())


# ---------------------------------------------------------------- 3
def test_epub():
    print('\nin the ebook')
    md = '# One\n\n' + L + '\n\n~~~ page src="marsh-map"\n~~~\n\n' + L
    out = os.path.join(TMP, 's.epub')
    epub.build_epub(manuscript.parse_markdown(md), preset(), out, dict(META, page_designs=[spread()]))
    with zipfile.ZipFile(out) as z:
        imgs = [n for n in z.namelist() if n.startswith('OEBPS/images/page')]
        ch = z.read('OEBPS/chapter001.xhtml').decode('utf-8')
        from PIL import Image
        import io
        with Image.open(io.BytesIO(z.read(imgs[0]))) as im:
            size = im.size
    check('one picture for the spread', len(imgs) == 1, imgs)
    check('it is both pages wide', size[0] > size[1] * 1.2, size)
    check('alt text, left page first', 'alt="Westward Fens Eastern Causeway"' in ch)


# ---------------------------------------------------------------- 4
def test_app():
    print('\nin the app')
    saved = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR', 'HISTORY_DIR')}
    tmp = tempfile.mkdtemp(prefix='ts-spreads-app-')
    try:
        A.PROJECT_DIR = os.path.join(tmp, 'projects')
        A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
        A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
        A.OUT_DIR = os.path.join(tmp, 'out')
        for d in (A.PROJECT_MS_DIR, A.OUT_DIR, A.HISTORY_DIR):
            os.makedirs(d)
        with open(os.path.join(A.PROJECT_MS_DIR, 'g.md'), 'w', encoding='utf-8') as f:
            f.write('# One\n\nA line.\n\n~~~ page src="marsh-map"\n~~~\n\n' + L)
        A.save_project_file('g', {'name': 'G', 'title': 'G', 'preset': 'classic-literary',
                                  'manuscript_file': 'g.md', 'manuscript_type': 'markdown',
                                  'format': 'pdf'})
        c = A.app.test_client()
        info = c.get('/page-designer/g').get_json()
        trim = A.load_preset('classic-literary')['trim']
        check('the designer is told the spread\'s geometry too',
              info['spread_geometry']['wrap_w'] == 2 * trim['w'] + 0.25 and info['spread_geometry']['spread'])
        s = spread()
        r = c.post('/page-designer/g/save', json={'name': 'marsh-map',
                                                   'design': {'elements': s['elements'], 'spread': True}}).get_json()
        stored = A.load_project('g')['page_designs'][0]
        check('saving keeps it a spread', r['ok'] and stored.get('spread') is True
              and r['designs'][0]['spread'] is True, stored)
        c.post('/page-designer/g/save', json={'name': 'marsh-map', 'design': {'elements': s['elements']}})
        check('saved as a page, it stops being one', 'spread' not in A.load_project('g')['page_designs'][0])
        c.post('/page-designer/g/save', json={'name': 'marsh-map',
                                              'design': {'elements': s['elements'], 'spread': True}})
        res = A._build_project('g', A.load_project('g'))
        with fitz.open(os.path.join(A.OUT_DIR, res['out_name'])) as d:
            lp, rp = pages_with(d, 'Westward Fens'), pages_with(d, 'Eastern Causeway')
            check('built, the book carries it on facing pages',
                  len(lp) == 1 and lp[0] % 2 == 0 and rp == [lp[0] + 1], (lp, rp))
        pr = c.post('/page-designer/g/proof', json={'design': {'elements': s['elements'], 'spread': True},
                                                    'name': 'x'}).get_json()
        check('its proof is the whole spread', pr['ok'] and pr['lines'].get('lt') == ['Westward Fens'], pr.get('error'))
        ed = c.get('/project/g/write').get_data(as_text=True)
        check('the writing editor\'s picker marks spreads', 'two-page spread' in ed)

        if os.environ.get('TS_SKIP_BROWSER'):
            print('  SKIP browser (TS_SKIP_BROWSER)')
        else:
            browser_half()
    finally:
        for k, v in saved.items():
            setattr(A, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


# The designer in a real browser: it opens a single page, turns it into a
# spread on the left, checks the guides and the gutter warning, saves it, then
# turns it back into a page keeping the right page (dropping the left).
from werkzeug.serving import make_server
from flask import request
_result = {}
SCRIPT = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  w.confirm = function () { out.asked = (out.asked || 0) + 1; return true; };
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR;
    out.kinds = Array.prototype.map.call(d.getElementById('wd-page-kind').options, function (o) { return o.value; });
    out.w1 = E.geometry().wrap_w;
    E.setKind('spread-left');
    var g = E.geometry();
    out.w2 = g.wrap_w; out.spread = !!g.spread && !!E.design().spread;
    out.anchors = E.design().elements.map(function (e) { return e.fill || e.anchor; }).join(',');
    out.bg = E.bbox(E.design().elements.find(function (e) { return e.id === 'bg'; }));
    out.kinds2 = Array.prototype.map.call(d.getElementById('wd-page-kind').options, function (o) { return o.value; });
    out.leftBtn = getComputedStyle(d.getElementById('wd-art-left')).display !== 'none';
    out.gutterShade = d.querySelectorAll('#wd-svg rect[fill="#1e88e5"]').length;
    var t = E.design().elements.find(function (e) { return e.id === 't'; });
    t.x = g.panel_w - 1;                 // across the fold
    E.commit(); d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
    out.checks = d.getElementById('wd-checks').textContent;
    t.x = 0.5; E.commit(); d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
    out.checks2 = d.getElementById('wd-checks').textContent;
    d.getElementById('wd-page-save').click();
    var w2 = setInterval(function () {
      var st = d.getElementById('wd-page-status').textContent;
      if (st.indexOf('Saved') !== 0) return;
      clearInterval(w2);
      out.saved = st;
      out.pick = d.getElementById('wd-page-pick').options[d.getElementById('wd-page-pick').selectedIndex].textContent;
      d.getElementById('wd-proof-btn').click();
      var w3 = setInterval(function () {
        var msg = d.getElementById('wd-proof-msg').textContent;
        if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
        clearInterval(w3);
        out.proof = msg;
        out.back = E.setKind('page-right');
        out.w3 = E.geometry().wrap_w;
        out.left = E.design().elements.length;
        out.undoSpread = (E.undo(), !!E.design().spread && E.geometry().wrap_w);
        var x = new XMLHttpRequest(); x.open('POST', '/_sp_result', false); x.send(JSON.stringify(out));
      }, 100);
    }, 100);
  }, 100);
};'''


@A.app.route('/_sp_harness')
def _sp_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" '
            'src="/wrap-designer?page=g&design=lone" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT + '</script>')


@A.app.route('/_sp_result', methods=['POST'])
def _sp_result():
    _result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def browser_half():
    print('\nthe designer, in a browser')
    browser = find_browser()
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
        return
    c = A.app.test_client()
    els = [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': RED},
           {'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 3,
            'text': 'A Letter', 'font': 'EBGaramond-Regular.ttf', 'size': 20, 'color': '#ffffff'}]
    c.post('/page-designer/g/save', json={'name': 'lone', 'design': {'elements': els}})
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                        '--user-data-dir=' + os.path.join(TMP, 'browser'),
                        '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                        f'http://127.0.0.1:{server.server_port}/_sp_harness'],
                       capture_output=True, timeout=300)
    finally:
        server.shutdown()
    r = _result
    check('the designer loaded and ran', bool(r), browser)
    if not r:
        return
    tw = A.load_preset('classic-literary')['trim']['w']
    check('a page offers to become a spread', r['kinds'] == ['page', 'spread-right', 'spread-left'], r['kinds'])
    check('made a spread, its sheet is two pages wide',
          r['spread'] and abs(r['w2'] - 2 * tw - 0.25) < 1e-9 and abs(r['w1'] - tw - 0.25) < 1e-9, r)
    check('its elements moved to the left page, as asked', r['anchors'] == 'back,back', r['anchors'])
    check('the colour covers the left page to the fold', r['bg'][0] == 0 and abs(r['bg'][2] - tw - 0.125) < 1e-9,
          r['bg'])
    check('a spread offers to become a page again, either side',
          r['kinds2'] == ['spread', 'page-left', 'page-right'], r['kinds2'])
    check('the left-page art button shows', r['leftBtn'])
    check('the gutter is shaded', r['gutterShade'] >= 1, r['gutterShade'])
    check('words across the fold are warned about', 'In the gutter' in r['checks'], r['checks'])
    check('and not once moved clear', 'In the gutter' not in r['checks2'], r['checks2'])
    stored = A.load_project('g')['page_designs']
    lone = W.find_page(stored, 'lone')
    check('saved, the book has a spread', 'Saved' in r['saved'] and lone and lone.get('spread') is True, lone)
    check('the picker marks it', r['pick'] == 'lone (spread)', r['pick'])
    check('its proof breaks every line where the editor does', r.get('proof', '').startswith('Built'), r.get('proof'))
    check('back to a page keeping the right one: the left page\'s elements are dropped, after asking',
          r['back'] and r['left'] == 0 and r.get('asked') == 1 and abs(r['w3'] - tw - 0.25) < 1e-9, r)
    check('and undo brings the spread back', r['undoSpread'] and abs(r['undoSpread'] - 2 * tw - 0.25) < 1e-9,
          r['undoSpread'])


if __name__ == '__main__':
    try:
        for t in (test_model, test_engine, test_epub, test_app):
            try:
                t()
            except Exception:
                traceback.print_exc()
                results.append((t.__name__, False))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [l for l, ok in results if not ok]
    print(f'\n{len(results) - len(bad)}/{len(results)} passed')
    sys.exit(1 if bad else 0)
