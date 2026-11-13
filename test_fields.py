"""Fillable boxes on designed pages (ROADMAP #74 follow-up)  (run: python test_fields.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

A page design may hold `field` elements: a text line, a text area or a
checkbox a reader fills in the PDF (a character sheet). Held here:

  1. the model: names tidied, kinds and looks, the count of fields; the
     fillable sheet (trim size, live fields where the design puts them, a
     checkbox square, a text area multi-line, boxes of one name one field);
  2. the engine: live fields in the plain print PDF and the screen PDF, at
     their place with and without bleed, on the right page of a spread; none in
     the press-ready PDF, which prints only their look; a design placed twice
     is one set of fields;
  3. the app: the sheet route, the designer's buttons, and - in a real browser
     - adding a box, making it a checkbox, its checks and the sheet.
"""
import copy, json, os, re, shutil, subprocess, sys, tempfile, threading, traceback

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, engine, app as A, wrap_design as W
from test_rich_editor import find_browser

TMP = tempfile.mkdtemp(prefix='ts-fields-')
results = []
B = 0.125 * 72


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (('\n         ' + str(detail)) if detail and not cond else ''))
    results.append((label, bool(cond)))


def preset():
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    return p


def sheet(name='sheet', spread=False, extra=()):
    a = 'back' if spread else 'front'
    els = [{'id': 't', 'type': 'text', 'anchor': a, 'x': 0.5, 'y': 0.5, 'w': 4,
            'text': 'Character Sheet', 'font': 'EBGaramond-Regular.ttf', 'size': 18, 'color': '#000000'},
           {'id': 'f1', 'type': 'field', 'kind': 'line', 'name': 'Character name', 'anchor': a,
            'x': 1, 'y': 1.5, 'w': 3, 'h': 0.3},
           {'id': 'f2', 'type': 'field', 'kind': 'area', 'name': 'Notes', 'anchor': a,
            'x': 1, 'y': 3, 'w': 3, 'h': 2, 'look': 'box', 'face': 'serif', 'size': 9},
           {'id': 'f3', 'type': 'field', 'kind': 'check', 'name': 'Inspired', 'anchor': a,
            'x': 1, 'y': 6, 'w': 0.4, 'h': 0.2}]
    els += list(extra)
    d = {'name': name, 'elements': els, 'saved': '2026-11-12T10:00:00'}
    if spread:
        d['spread'] = True
    return d


def widgets(page):
    return {w.field_name: w for w in page.widgets()}


def form_fields(doc):
    """The top-level fields of a PDF's form: [(name, kids)]."""
    cat = doc.pdf_catalog()
    kind, val = doc.xref_get_key(cat, 'AcroForm')
    if kind == 'null':
        return []
    form = int(val.split()[0]) if kind == 'xref' else None
    arr = doc.xref_get_key(form, 'Fields')[1] if form else ''
    out = []
    for ref in re.findall(r'(\d+) 0 R', arr):
        x = int(ref)
        name = doc.xref_get_key(x, 'T')[1]
        kids = re.findall(r'(\d+) 0 R', doc.xref_get_key(x, 'Kids')[1])
        out.append((name, len(kids)))
    return out


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it. ' * 30


def build(md, name, designs, press=False, screen=False, **meta):
    out = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), preset(), out,
                           dict(META, page_designs=designs, **meta), press=press, screen=screen)
    return out, res


def pages_with(doc, text):
    return [i for i, pg in enumerate(doc) if text in pg.get_text()]


# ---------------------------------------------------------------- 1
def test_model():
    print('\nthe model')
    check('a name is tidied: no dots (a dot nests fields), spaces closed up',
          W.field_name({'name': '  Str. score\n bonus '}) == 'Str score bonus')
    check('a box with no name is named by its id', W.field_name({'id': 'field-3'}) == 'field-3')
    check('an unknown kind is a text line; a line is underlined, an area and a checkbox boxed',
          W.field_kind({'kind': 'x'}) == 'line' and W.field_look({}) == 'underline'
          and W.field_look({'kind': 'area'}) == 'box' and W.field_look({'kind': 'check', 'look': 'underline'}) == 'box')
    check('the typed size is held to 4-48pt', W.field_size({'size': 200}) == 48 and W.field_size({'size': 'x'}) == 10)
    d = sheet(extra=[{'type': 'field', 'name': 'Notes', 'kind': 'area', 'anchor': 'front', 'x': 1, 'y': 7, 'w': 1, 'h': 1},
                     {'type': 'field', 'name': 'Notes', 'kind': 'check', 'anchor': 'front', 'x': 3, 'y': 7, 'w': .2, 'h': .2},
                     {'type': 'field', 'name': 'Gone', 'hidden': True, 'anchor': 'front', 'w': 1, 'h': 1}])
    check('boxes of one name count once; a checkbox of that name apart; hidden ones not at all',
          W.field_count(d) == 4, W.field_count(d))

    out = os.path.join(TMP, 'sheet.pdf')
    W.build_sheet_pdf(d, 6, 9, out, title='sheet')
    with fitz.open(out) as doc:
        pg = doc[0]
        ws = widgets(pg)
        check('the sheet is one page at trim size, no bleed',
              doc.page_count == 1 and abs(pg.rect.width - 432) < .01 and abs(pg.rect.height - 648) < .01)
        check('its boxes are live fields', {'Character name', 'Notes', 'Inspired'} <= set(ws), sorted(ws))
        r = ws['Character name'].rect
        check('where the design puts them, from the trim',
              abs(r.x0 - 72) < .5 and abs(r.y0 - 1.5 * 72) < .5 and abs(r.width - 216) < .5
              and abs(r.height - 0.3 * 72) < .5, r)
        check('a text area takes several lines',
              ws['Notes'].field_flags & 4096 and not ws['Character name'].field_flags & 4096)
        ins = ws['Inspired']
        check('a checkbox is a checkbox, a square of the smaller side',
              ins.field_type_string == 'CheckBox' and abs(ins.rect.width - ins.rect.height) < .01
              and abs(ins.rect.width - 0.2 * 72) < .5, ins.rect)
        ff = dict(form_fields(doc))
        check('two boxes named Notes are one field with two places; the checkbox stands apart',
              ff.get('Notes') == 2 and ff.get('Notes (tick)') == 1, ff)
        check('a hidden box makes no field', 'Gone' not in ws)
        # the look prints: the underline of "Character name" is dark
        pm = pg.get_pixmap(dpi=288)
        check('a box prints its look (the underline)', pm.pixel(int(2.5 * 288), int(1.8 * 288) - 1)[0] < 120,
              pm.pixel(int(2.5 * 288), int(1.8 * 288) - 1))
    out = os.path.join(TMP, 'spread-sheet.pdf')
    sp = sheet(spread=True, extra=[{'type': 'field', 'name': 'Right one', 'anchor': 'front',
                                    'x': 1, 'y': 1, 'w': 2, 'h': .3}])
    W.build_sheet_pdf(sp, 6, 9, out)
    with fitz.open(out) as doc:
        left, right = (set(widgets(doc[i])) for i in (0, 1)) if doc.page_count == 2 else (set(), set())
        check('a spread\'s sheet is two pages, each box on the page it sits on',
              doc.page_count == 2 and 'Character name' in left and 'Right one' in right
              and 'Right one' not in left and 'Character name' not in right, (left, right))
        r = widgets(doc[1])['Right one'].rect if doc.page_count == 2 else None
        check('the right page\'s box is placed from its own trim', r is not None and abs(r.x0 - 72) < .5, r)
    out = os.path.join(TMP, 'proof.pdf')
    W.build_page_pdf(d, 6, 9, out)
    with fitz.open(out) as doc:
        check('the designer\'s proof (what a printer gets) has no live fields', not list(doc[0].widgets()))


# ---------------------------------------------------------------- 2
def test_engine():
    print('\nin the book')
    md = '\n'.join(['# The Approach', '', L, '', '~~~ page src="sheet" side="left"', '~~~', '', L,
                    '', '~~~ page src="sheet" side="right"', '~~~', '', L])
    out, res = build(md, 'plain', [sheet()])
    with fitz.open(out) as doc:
        hits = pages_with(doc, 'Character Sheet')
        check('two sheet pages', len(hits) == 2, hits)
        ws = [widgets(doc[n]) for n in hits]
        check('the print PDF\'s designed pages carry live fields',
              all({'Character name', 'Notes', 'Inspired'} <= set(w) for w in ws), [sorted(w) for w in ws])
        r = ws[0]['Character name'].rect if ws else None
        check('placed from the trim', r is not None and abs(r.x0 - 72) < .5 and abs(r.y0 - 108) < .5, r)
        others = [i for i in range(doc.page_count) if i not in hits and list(doc[i].widgets())]
        check('no other page has a field', not others, others)
        ff = dict(form_fields(doc))
        check('a design placed twice is one set of fields: each name in both places',
              ff.get('Character name') == 2 and ff.get('Inspired') == 2 and len(ff) == 3, ff)

    out, _ = build(md, 'bleed', [sheet()], bleed=True)
    with fitz.open(out) as doc:
        ok = []
        for n in pages_with(doc, 'Character Sheet'):
            pg, tb = doc[n], doc[n].trimbox
            r = widgets(pg).get('Character name')
            ok.append(r is not None and abs(r.rect.x0 - tb.x0 - 72) < .5 and abs(r.rect.y0 - tb.y0 - 108) < .5)
        check('with bleed, on both a left and a right page, still from the trim', ok == [True, True], ok)

    out, res = build(md, 'screen', [sheet()], screen=True)
    with fitz.open(out) as doc:
        n = pages_with(doc, 'Character Sheet')
        check('the screen PDF\'s fields are live too', n and 'Notes' in widgets(doc[n[0]]))

    out, res = build(md, 'press', [sheet()], press=True)
    with fitz.open(out) as doc:
        n = pages_with(doc, 'Character Sheet')
        check('the press-ready PDF builds press-ready', res['press'] and not res.get('press_error'),
              res.get('press_error'))
        check('with no fields and no form at all (PDF/X forbids them)',
              n and not any(list(doc[i].widgets()) for i in range(doc.page_count))
              and doc.xref_get_key(doc.pdf_catalog(), 'AcroForm')[0] == 'null')
        pm = doc[n[0]].get_pixmap(dpi=288)
        check('but the boxes print their look', pm.pixel(int(2.5 * 288), int(1.8 * 288) - 1)[0] < 120)
        rows = engine.press_preflight(out) if hasattr(engine, 'press_preflight') else None
        if rows:
            check('and its preflight finds no interactive content', all(r.get('ok') or r.get('note') for r in rows
                                                                           if 'link' in r['label'].lower()), rows)

    spread_md = '# One\n\n' + L + '\n\n~~~ page src="map"\n~~~\n\n' + L
    sp = sheet('map', spread=True, extra=[{'type': 'field', 'name': 'Right one', 'anchor': 'front',
                                           'x': 1, 'y': 1, 'w': 2, 'h': .3}])
    out, _ = build(spread_md, 'spread', [sp])
    with fitz.open(out) as doc:
        n = pages_with(doc, 'Character Sheet')
        left = set(widgets(doc[n[0]])) if n else set()
        right = set(widgets(doc[n[0] + 1])) if n else set()
        check('in a spread each box is on its own page, once',
              'Character name' in left and 'Right one' in right and not (left & right), (left, right))
        r = widgets(doc[n[0] + 1]).get('Right one') if n else None
        check('the right page\'s box placed from that page\'s trim', r is not None and abs(r.rect.x0 - 72) < .5,
              r and r.rect)

    out, _ = build('# Plain\n\n' + L, 'none', [])
    with fitz.open(out) as doc:
        check('a book with no fillable boxes has no form', doc.xref_get_key(doc.pdf_catalog(), 'AcroForm')[0] == 'null')


# ---------------------------------------------------------------- 3
def test_app():
    print('\nin the app')
    saved = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR', 'HISTORY_DIR')}
    tmp = tempfile.mkdtemp(prefix='ts-fields-app-')
    try:
        A.PROJECT_DIR = os.path.join(tmp, 'projects')
        A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
        A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
        A.OUT_DIR = os.path.join(tmp, 'out')
        for d in (A.PROJECT_MS_DIR, A.OUT_DIR, A.HISTORY_DIR):
            os.makedirs(d)
        with open(os.path.join(A.PROJECT_MS_DIR, 'g.md'), 'w', encoding='utf-8') as f:
            f.write('# One\n\n' + L + '\n\n~~~ page src="sheet"\n~~~\n')
        A.save_project_file('g', {'name': 'G', 'title': 'G', 'preset': 'classic-literary',
                                  'manuscript_file': 'g.md', 'manuscript_type': 'markdown',
                                  'format': 'pdf', 'page_designs': [sheet()]})
        c = A.app.test_client()
        trim = A.load_preset('classic-literary')['trim']
        r = c.post('/page-designer/g/sheet', json={'design': {'elements': sheet()['elements']},
                                                    'name': 'Sheet'}).get_json()
        check('the sheet route builds it and counts its fields', r['ok'] and r['fields'] == 3
              and '/download/' in r['pdf'], r)
        fn = r['pdf'].rsplit('/', 1)[-1]
        with fitz.open(os.path.join(A.OUT_DIR, fn)) as doc:
            check('at the book\'s trim, fields live', abs(doc[0].rect.width - trim['w'] * 72) < .01
                  and len(widgets(doc[0])) == 3)
        r = c.post('/page-designer/g/sheet', json={'design': {'elements': sheet(spread=True)['elements'],
                                                              'spread': True}}).get_json()
        with fitz.open(os.path.join(A.OUT_DIR, r['pdf'].rsplit('/', 1)[-1])) as doc:
            check('a spread\'s sheet has two pages', doc.page_count == 2)
        r = c.post('/page-designer/g/sheet', json={'design': 'nonsense'}).get_json()
        check('a design it can\'t read is refused', not r['ok'])
        r = c.post('/page-designer/g/save', json={'name': 'sheet', 'design': {'elements': sheet()['elements']}}).get_json()
        kept = A.load_project('g')['page_designs'][0]['elements']
        check('saving keeps a fillable box as it is', r['ok'] and any(
            e.get('type') == 'field' and e.get('kind') == 'check' and e.get('name') == 'Inspired' for e in kept))
        res = A._build_project('g', A.load_project('g'))
        with fitz.open(os.path.join(A.OUT_DIR, res['out_name'])) as doc:
            n = pages_with(doc, 'Character Sheet')
            check('the built book has the live fields', n and len(widgets(doc[n[0]])) == 3, res.get('error'))
        dp = c.get('/wrap-designer?page=g&design=sheet').get_data(as_text=True)
        check('the page designer has the fillable box and sheet buttons',
              'id="wd-add-field"' in dp and 'id="wd-sheet-btn"' in dp)
        wp = c.get('/wrap-designer').get_data(as_text=True)
        check('which the wrap designer hides (page-only)',
              re.search(r'class="[^"]*page-only[^"]*" id="wd-add-field"', wp) is not None
              and '.page-only{display:none!important}' in wp)
        if os.environ.get('TS_SKIP_BROWSER'):
            print('  SKIP browser (TS_SKIP_BROWSER)')
        else:
            browser_half()
    finally:
        for k, v in saved.items():
            setattr(A, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


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
    var E = w.WD_EDITOR;
    out.layers = d.getElementById('wd-layers').textContent;
    out.checks = d.getElementById('wd-checks').textContent;
    d.getElementById('wd-add-field').click();
    var els = E.design().elements, nf = els[els.length - 1];
    out.added = {type: nf.type, kind: nf.kind, name: nf.name, look: nf.look};
    out.props = d.getElementById('wd-props').textContent;
    out.drawn = d.querySelectorAll('#wd-svg g.el[data-id="' + nf.id + '"] line').length;
    var kind = Array.prototype.find.call(d.querySelectorAll('#wd-props select'),
                                         function (s) { return s.querySelector('option[value="check"]'); });
    kind.value = 'check';
    kind.dispatchEvent(new w.Event('input'));
    kind.dispatchEvent(new w.Event('change'));
    out.check = {kind: nf.kind, w: nf.w, h: nf.h, bbox: E.bbox(nf)};
    out.looks = Array.prototype.map.call(d.querySelectorAll('#wd-props select'), function (s) {
      return Array.prototype.map.call(s.options, function (o) { return o.value; }).join(','); });
    nf.name = 'Character name';
    d.getElementById('wd-guides').dispatchEvent(new w.Event('change'));
    out.checks2 = d.getElementById('wd-checks').textContent;
    d.getElementById('wd-sheet-btn').click();
    var w2 = setInterval(function () {
      var link = d.getElementById('wd-sheet-link');
      if (!link) return;
      clearInterval(w2);
      out.sheet = d.getElementById('wd-sheet-msg').textContent;
      out.href = link.getAttribute('href');
      var x = new XMLHttpRequest(); x.open('POST', '/_fd_result', false); x.send(JSON.stringify(out));
    }, 100);
  }, 100);
};'''


@A.app.route('/_fd_harness')
def _fd_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" '
            'src="/wrap-designer?page=g&design=sheet" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT + '</script>')


@A.app.route('/_fd_result', methods=['POST'])
def _fd_result():
    _result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def browser_half():
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
                        f'http://127.0.0.1:{server.server_port}/_fd_harness'],
                       capture_output=True, timeout=300)
    finally:
        server.shutdown()
    r = _result
    check('the page designer loaded and ran', bool(r), browser)
    if not r:
        return
    check('the saved boxes are listed as layers by kind and name',
          'Text line: Character name' in r['layers'] and 'Checkbox: Inspired' in r['layers']
          and 'Text area: Notes' in r['layers'], r['layers'])
    check('its checks say where the boxes are live', 'fillable boxes' in r['checks'] and
          'press-ready PDF prints only' in r['checks'], r['checks'])
    check('+ Fillable box adds a named, underlined text line',
          r['added'] == {'type': 'field', 'kind': 'line', 'name': 'Field 4', 'look': 'underline'}, r['added'])
    check('drawn with its underline', r['drawn'] == 1, r['drawn'])
    check('its panel offers name, kind and look', 'Name' in r['props'] and 'Kind' in r['props']
          and 'Look' in r['props'], r['props'])
    ck = r['check']
    check('made a checkbox, it becomes square',
          ck['kind'] == 'check' and ck['w'] == ck['h'] and abs(ck['bbox'][2] - ck['bbox'][3]) < 1e-9, ck)
    check('and a checkbox offers no underline', not any(o.startswith('underline') for o in r['looks']), r['looks'])
    check('a shared name is pointed out', 'Shared names' in r['checks2'] and 'Character name' in r['checks2'],
          r['checks2'])
    check('the sheet button builds a sheet and links it',
          '/download/' in r.get('href', '') and 'fillable field' in r.get('sheet', ''), r)


if __name__ == '__main__':
    try:
        for t in (test_model, test_engine, test_app):
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
