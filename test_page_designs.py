"""Designed pages (ROADMAP #74, Phase 6b)  (run: python test_page_designs.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

A book keeps page designs (the wrap designer's document laid out on one
interior page) and places them with `~~~ page src="name" side="…"`. Held here:

  1. the model: a page geometry the designer and the PDF share, names, the
     words for alt text, what reaches the edge;
  2. the engine: each design on a page of its own, on the side asked for,
     blank page before when needed, no folio; drawn edge to edge with bleed,
     cut at the trim without; its colours on screen, greys on press; a name
     the book doesn't have stands in grey and is reported; two columns;
  3. the ebook: an image page with alt text, once per design;
  4. the app: save, rename, delete and proof through the routes, the build's
     checks, the book that never made one is never written a key, the
     manuscript editor's picker, and - in a real browser - the designer's
     page mode loading, saving and proofing a page.
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
from test_project_edit import form_of        # adds routes: before the first request

TMP = tempfile.mkdtemp(prefix='ts-pages-')
results = []
B = 0.125 * 72
RED = '#c03020'


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


def design(name='handout-1', fill=True, words='A Letter Found'):
    els = [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': RED}] if fill else []
    els.append({'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
                'text': words, 'font': 'EBGaramond-Regular.ttf', 'size': 24, 'color': '#ffffff'})
    return {'name': name, 'elements': els, 'saved': '2026-11-12T10:00:00'}


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it. ' * 30


def book(*pages):
    md = ['# The Approach', '', L]
    for p in pages:
        md += ['', p, '~~~', '', L]
    return '\n'.join(md)


def build(md, name, p=None, press=False, screen=False, **meta):
    out = os.path.join(TMP, name + '.pdf')
    m = dict(META, page_designs=[design()], **meta)
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
    g = W.page_geometry(6, 9)
    check('a page sheet is the trim plus 0.125" all round',
          g['wrap_w'] == 6.25 and g['wrap_h'] == 9.25 and g['edge'] == 0.125 and g['page'])
    check('a fill covers the whole sheet', W.el_rect(g, {'fill': 'front'}) == (0, 0, 6.25, 9.25))
    check('an element sits from the trim corner',
          W.el_rect(g, {'anchor': 'front', 'x': 1, 'y': 2, 'w': 3, 'h': 1}) == (1.125, 2.125, 3, 1))
    check('names are written as the manuscript writes them',
          W.page_name('  Handout #1!  ') == 'handout-1' and W.page_name('***') == '')
    check('a design is found by name, however it is written',
          W.find_page([design()], 'Handout 1') is not None and W.find_page([design()], 'x') is None)
    d = design(words='Top')
    d['elements'].append({'type': 'text', 'anchor': 'front', 'x': 0, 'y': 5, 'text': 'Bottom\nline'})
    d['elements'].append({'type': 'text', 'anchor': 'front', 'x': 0, 'y': 6, 'text': 'gone', 'hidden': True})
    check('its words read top to bottom, hidden ones left out', W.page_words(d) == 'Top Bottom line',
          W.page_words(d))
    check('a filled page reaches the edge; text alone does not',
          W.reaches_edge(design(), g) and not W.reaches_edge(design(fill=False), g))
    out = os.path.join(TMP, 'proof.pdf')
    lines = W.build_page_pdf(design(), 6, 9, out)
    with fitz.open(out) as doc:
        pg = doc[0]
        check('the proof is one page, trim declared inside the bleed',
              doc.page_count == 1 and abs(pg.rect.width - 6.25 * 72) < .01
              and abs(pg.trimbox.x0 - B) < .01 and abs(pg.trimbox.width - 6 * 72) < .01)
    check('and its lines are reported for the editor', lines.get('t') == ['A Letter Found'], lines)
    jpg = W.render_page(design(), 6, 9, os.path.join(TMP, 'p.jpg'), dpi=50)
    from PIL import Image
    with Image.open(jpg) as im:
        check('the ebook picture is the trimmed page', im.size == (300, 450), im.size)


# ---------------------------------------------------------------- 2
def test_engine():
    print('\nin the book')
    md = book('~~~ page src="handout-1" side="right"', '~~~ page src="handout-1" side="left"',
              '~~~ page src="handout-1"')
    out, res = build(md, 'sides')
    with fitz.open(out) as doc:
        hits = pages_with(doc, 'A Letter Found')
        check('three designed pages', len(hits) == 3, hits)
        check('right on a right-hand page, left on a left-hand one',
              len(hits) == 3 and hits[0] % 2 == 1 and hits[1] % 2 == 0, hits)
        check('a designed page has nothing else on it (no folio, no running head)',
              all(doc[n - 1].get_text().split() == 'A Letter Found'.split() for n in hits),
              [doc[n - 1].get_text() for n in hits])
        check('it fills the page edge to edge',
              all(near(pixel(doc[n - 1], 2, 2), (192, 48, 32)) for n in hits))
        nxt = hits[0]
        check('what follows starts on the next page', 'tide' in doc[nxt].get_text())
    check('a book without bleed reports the designed page that reaches the edge',
          res['pages_bleed_wanted'] == ['handout-1'] and res['pages_missing'] == [], res)
    # after a right-hand page with words on it, a right-hand design takes a
    # blank page first; a left-hand one goes straight on the next
    out, _ = build('# One\n\nA line.\n\n~~~ page src="handout-1" side="right"\n~~~\n\n' + L, 'first')
    with fitz.open(out) as doc:
        check('a blank page goes before one when its side needs it',
              pages_with(doc, 'A Letter Found') == [3] and not doc[1].get_text().strip(),
              pages_with(doc, 'A Letter Found'))
    out, _ = build('# One\n\nA line.\n\n~~~ page src="handout-1" side="left"\n~~~\n\n' + L, 'next')
    with fitz.open(out) as doc:
        check('and none when the next page is already on its side',
              pages_with(doc, 'A Letter Found') == [2], pages_with(doc, 'A Letter Found'))

    out, res = build(md, 'bleed', bleed=True)
    with fitz.open(out) as doc:
        hits = pages_with(doc, 'A Letter Found')
        ok = True
        for n in hits:
            pg = doc[n - 1]
            if abs(pg.rect.width - (6 * 72 + B)) > 1 and abs(pg.rect.width - pg.trimbox.width - B) > .01:
                ok = False
            outer_x = pg.rect.width - 2 if n % 2 == 1 else 2
            if not near(pixel(pg, outer_x, 2), (192, 48, 32)):
                ok = False
        check('with bleed it runs out past the trim on the outer edge', ok and hits, hits)
        tb = doc[hits[0] - 1].trimbox
        words = [w for w in doc[hits[0] - 1].get_text('words') if w[4] == 'A']
        check('and its words stand where the design puts them, from the trim',
              words and abs(words[0][0] - tb.x0 - 0.5 * 72) < 2, words[:1])
    check('a book with bleed has nothing to report', res['pages_bleed_wanted'] == [])

    out, res = build(md, 'press', press=True)
    with fitz.open(out) as doc:
        n = pages_with(doc, 'A Letter Found')[0]
        px = pixel(doc[n - 1], 20, 20)
    check('press-ready: it builds, the colour printed as grey',
          res['press'] and not res.get('press_error') and abs(px[0] - px[1]) < 8 and abs(px[1] - px[2]) < 8,
          (res.get('press_error'), px))
    out, res = build(md, 'screen', screen=True)
    with fitz.open(out) as doc:
        n = pages_with(doc, 'A Letter Found')[0]
        check('the screen PDF keeps its colours', near(pixel(doc[n - 1], 20, 20), (192, 48, 32)))

    out, res = build(book('~~~ page src="no-such-page"'), 'missing')
    with fitz.open(out) as doc:
        check('a name the book has no design for stands in grey', pages_with(doc, 'missing page design'))
    check('and is reported', res['pages_missing'] == ['no-such-page'], res['pages_missing'])

    md2 = '# Two\n\n' + L + '\n\n~~~ page src="handout-1"\n~~~\n\n' + L
    out, _ = build(md2, 'cols', p=preset(2))
    with fitz.open(out) as doc:
        n = pages_with(doc, 'A Letter Found')
        check('in two columns it still takes a whole page',
              n and doc[n[0] - 1].get_text().split() == 'A Letter Found'.split(), n)


# ---------------------------------------------------------------- 3
def test_epub():
    print('\nin the ebook')
    md = book('~~~ page src="handout-1"', '~~~ page src="handout-1"\nThe letter, read aloud',
              '~~~ page src="nope"')
    out = os.path.join(TMP, 'b.epub')
    epub.build_epub(manuscript.parse_markdown(md), preset(), out, dict(META, page_designs=[design()]))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        ch = z.read('OEBPS/chapter001.xhtml').decode('utf-8')
        opf = z.read('OEBPS/content.opf').decode('utf-8')
    imgs = [n for n in names if n.startswith('OEBPS/images/page')]
    check('one picture per design, however often it is placed', imgs == ['OEBPS/images/page001.jpg'], imgs)
    check('and it is in the manifest', 'images/page001.jpg' in opf)
    check('an image page, its alt text the design\'s words', 'alt="A Letter Found"' in ch)
    check('words inside the fence are its alt text instead', 'alt="The letter, read aloud"' in ch)
    check('a design the book doesn\'t have leaves a note', 'missing page design: nope' in ch)
    report = epub.check(out) if hasattr(epub, 'check') else None
    if report is not None:
        bad = [c for c in report if not c.get('ok')] if isinstance(report, list) else []
        check('the ebook passes its own checks', not bad, bad[:3])


# ---------------------------------------------------------------- 4
def test_app():
    print('\nin the app')
    saved = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR', 'HISTORY_DIR')}
    tmp = tempfile.mkdtemp(prefix='ts-pages-app-')
    try:
        A.PROJECT_DIR = os.path.join(tmp, 'projects')
        A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
        A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
        A.OUT_DIR = os.path.join(tmp, 'out')
        for d in (A.PROJECT_MS_DIR, A.OUT_DIR, A.HISTORY_DIR):
            os.makedirs(d)
        with open(os.path.join(A.PROJECT_MS_DIR, 'g.md'), 'w', encoding='utf-8') as f:
            f.write(book('~~~ page src="handout-1" side="right"'))
        A.save_project_file('g', {'name': 'G', 'title': 'G', 'preset': 'classic-literary',
                                  'manuscript_file': 'g.md', 'manuscript_type': 'markdown',
                                  'format': 'pdf'})
        c = A.app.test_client()
        info = c.get('/page-designer/g').get_json()
        trim = A.load_preset('classic-literary')['trim']
        check('the designer is told the book\'s trim and its page geometry',
              info['trim'] == trim and info['geometry']['wrap_w'] == trim['w'] + 0.25
              and info['designs'] == [])
        res = A._build_project('g', A.load_project('g'))
        check('a book with no designs builds, the page reported missing', not res['error'], res['error'])
        page = c.post('/project/g/generate').get_data(as_text=True)
        check('the result page says so', 'handout-1' in page and 'missing page design' in page)

        els = design()['elements']
        r = c.post('/page-designer/g/save', json={'name': 'Handout 1', 'design': {'elements': els}}).get_json()
        check('saving keeps it with the book under its written name',
              r['ok'] and r['name'] == 'handout-1'
              and [d['name'] for d in A.load_project('g')['page_designs']] == ['handout-1'], r)
        r = c.post('/page-designer/g/save', json={'name': '!!', 'design': {'elements': els}}).get_json()
        check('a name with nothing usable in it is refused', not r['ok'] and 'name' in r['error'])
        r = c.post('/page-designer/g/save', json={'name': 'map', 'design': {'elements': els}}).get_json()
        r2 = c.post('/page-designer/g/save', json={'name': 'map', 'was': 'handout-1',
                                                    'design': {'elements': els}}).get_json()
        check('renaming onto another page\'s name is refused', r['ok'] and not r2['ok'], r2)
        r = c.post('/page-designer/g/save', json={'name': 'letter', 'was': 'map',
                                                   'design': {'elements': els[:1]}}).get_json()
        names = [d['name'] for d in A.load_project('g')['page_designs']]
        check('renaming replaces it, in place', r['ok'] and names == ['handout-1', 'letter'], names)
        r = c.post('/page-designer/g/save', json={'name': 'big', 'design': {
            'elements': [{'type': 'rect'}] * (W.MAX_ELEMENTS + 1)}}).get_json()
        check('a design past the limit is refused', not r['ok'] and 'at most' in r['error'], r)

        res = A._build_project('g', A.load_project('g'))
        with fitz.open(os.path.join(A.OUT_DIR, res['out_name'])) as d:
            check('built, the book carries its design', pages_with(d, 'A Letter Found'))
        page = c.post('/project/g/generate').get_data(as_text=True)
        check('the result page asks for bleed for it', 'Designed pages' in page and 'white sliver' in page)

        pr = c.post('/page-designer/g/proof', json={'design': {'elements': els}, 'name': 'x'}).get_json()
        check('a proof is built, pictured and linked',
              pr['ok'] and pr['png'].startswith('data:image/png') and '/download/' in pr['pdf']
              and pr['lines'].get('t') == ['A Letter Found'], {k: pr.get(k) for k in ('ok', 'lines', 'error')})

        r = c.post('/page-designer/g/delete', json={'name': 'letter'}).get_json()
        check('delete takes one out', [d['name'] for d in r['designs']] == ['handout-1'])
        c.post('/page-designer/g/delete', json={'name': 'handout-1'})
        check('and the last one out leaves no key', 'page_designs' not in A.load_project('g'))

        # the book page links to the designer; saving it as it came writes no key
        form_page = c.get('/project/g/edit').get_data(as_text=True)
        check('the book page links to the page designer', '/wrap-designer?page=g' in form_page)
        c.post('/project/g/edit', data=form_of(form_page, '/project/g/edit'), follow_redirects=True)
        check('saving the book page writes no page designs into it',
              'page_designs' not in A.load_project('g'))
        c.post('/page-designer/g/save', json={'name': 'handout-1', 'design': {'elements': els}})
        form_page = c.get('/project/g/edit').get_data(as_text=True)
        c.post('/project/g/edit', data=form_of(form_page, '/project/g/edit'), follow_redirects=True)
        check('nor takes them out', len(A.load_project('g').get('page_designs') or []) == 1)

        dp = c.get('/wrap-designer?page=g&design=handout-1').get_data(as_text=True)
        check('the designer opens in page mode', 'Page designer' in dp and '"pageProject": "g"' in dp
              and 'id="wd-page-bar"' in dp)
        wp = c.get('/wrap-designer').get_data(as_text=True)
        check('and the wrap designer is as it was', 'Wrap designer' in wp and 'id="wd-page-bar"' not in wp)
        ed = c.get('/project/g/write').get_data(as_text=True)
        check('the writing editor has the designed page button and its picker',
              'data-act="page"' in ed and 'id="pagepick"' in ed and '/page-designer/g' in ed)

        if os.environ.get('TS_SKIP_BROWSER'):
            print('  SKIP browser (TS_SKIP_BROWSER)')
        else:
            browser_half(c)
    finally:
        for k, v in saved.items():
            setattr(A, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


# The designer's page mode in a real browser: it opens the saved page, edits
# it, saves it back to the book under a new name and builds the proof, whose
# lines match the editor's.
from werkzeug.serving import make_server
from flask import request
_result = {}
SCRIPT = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, g = E.geometry();
    out.page = !!g.page; out.wrap_w = g.wrap_w;
    out.loaded = E.design().elements.map(function (e) { return e.id; }).join(',');
    out.name = d.getElementById('wd-page-name').value;
    out.picker = Array.prototype.map.call(d.getElementById('wd-page-pick').options, function (o) { return o.value; });
    out.barcode_hidden = getComputedStyle(d.getElementById('wd-add-barcode')).display === 'none';
    out.fill = E.bbox(E.design().elements.find(function (e) { return e.id === 'bg'; }));
    out.sheet = [0, 0, g.wrap_w, g.wrap_h];
    out.checks = d.getElementById('wd-checks').textContent;
    var t = E.design().elements.find(function (e) { return e.id === 't'; });
    t.text = 'Edited in the browser';
    d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
    out.dirty = d.getElementById('wd-page-status').textContent;
    d.getElementById('wd-page-name').value = 'Edited Page';
    d.getElementById('wd-page-save').click();
    var w2 = setInterval(function () {
      var st = d.getElementById('wd-page-status').textContent;
      if (st.indexOf('Saved') !== 0) return;
      clearInterval(w2);
      out.saved = st;
      out.picker2 = Array.prototype.map.call(d.getElementById('wd-page-pick').options, function (o) { return o.value; });
      d.getElementById('wd-proof-btn').click();
      var w3 = setInterval(function () {
        var msg = d.getElementById('wd-proof-msg').textContent;
        if (msg.indexOf('Built') !== 0 && msg.indexOf('These') !== 0 && msg.indexOf('The PDF') !== 0) return;
        clearInterval(w3);
        out.proof = msg;
        var x = new XMLHttpRequest(); x.open('POST', '/_pd_result', false); x.send(JSON.stringify(out));
      }, 100);
    }, 100);
  }, 100);
};'''


@A.app.route('/_pd_harness')
def _pd_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" '
            'src="/wrap-designer?page=g&design=handout-1" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT + '</script>')


@A.app.route('/_pd_result', methods=['POST'])
def _pd_result():
    _result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def browser_half(c):
    print('\nthe page designer, in a browser')
    browser = find_browser()
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
        return
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
    r = _result
    check('the page designer loaded and ran', bool(r), browser)
    if not r:
        return
    trim = A.load_preset('classic-literary')['trim']
    check('it is drawn on the book\'s page, with its bleed',
          r['page'] and abs(r['wrap_w'] - trim['w'] - 0.25) < 1e-9, r)
    check('it opened the saved page', r['loaded'] == 'bg,t' and r['name'] == 'handout-1', r)
    check('the picker lists the book\'s pages', r['picker'] == ['', 'handout-1'], r['picker'])
    check('cover tools are hidden', r['barcode_hidden'])
    check('a whole-page colour covers the sheet, as it prints', r['fill'] == r['sheet'], (r['fill'], r['sheet']))
    check('a fresh page passes its checks', 'stops short' not in r['checks'] and 'barcode' not in r['checks'].lower(),
          r['checks'])
    check('an edit shows as unsaved', r['dirty'] == 'Unsaved changes', r['dirty'])
    check('saving keeps it with the book, under the new name',
          'src="edited-page"' in r.get('saved', '') and r.get('picker2') == ['', 'edited-page'], r)
    saved = A.load_project('g')['page_designs']
    check('and the book has the edit', [d['name'] for d in saved] == ['edited-page']
          and any(e.get('text') == 'Edited in the browser' for e in saved[0]['elements']), saved)
    check('the proof breaks every line where the editor does', r.get('proof', '').startswith('Built'),
          r.get('proof'))


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
