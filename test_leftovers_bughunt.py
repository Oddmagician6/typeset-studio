"""Leftovers from the joint bug hunt  (run: python test_leftovers_bughunt.py).

Round 6 left these open; each answer is the same as before, only faster:

    28.5  EPUB page references: the links before each one are counted once
    28.7  Continuity's look-alike index has a budget (10,000 long names took
          gigabytes), and the quick ratios go first
    28.8  emphasis with no closing marker, and a long bare word on a fence,
          are linear
    28.11 repeated chapter and heading names get their suffix without
          probing every one already given
    28.12 Continuity numbers the chapters once
    28.14 a running head is fitted once per label, by halving
    spec  Word import can't reach Python's recursion limit: the XML parser
          refuses anything nested past 256 first
    27    text dropped into the rich editor goes through the paste cleanup

Measured and left: 28.10 (the two-column queue: 20,000 paragraphs in one run
lay out in about a second) and 28.13 (already linear since round 6).
The browser half needs Chrome or Edge (TS_BROWSER).
"""

import json, os, random, re, shutil, subprocess, sys, tempfile, threading, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import manuscript, doc_model, checker, epub, engine

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def timed(fn):
    s = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - s


rng = random.Random(28)


def noise(alphabet, n):
    return ''.join(rng.choice(alphabet) for _ in range(n))


# ---- 28.8 -------------------------------------------------------------------
print('28.8 emphasis with nothing to close it')
bad = []
for pat in manuscript._CLOSERS:
    rx = re.compile(pat)
    for _ in range(3000):
        s = noise('*_ ab\n', rng.randint(0, 24))
        want = [(m.span(), m.groups()) for m in rx.finditer(s)]
        got = [(m.span(), m.groups()) for m in manuscript.emph_finditer(rx, s)]
        if want != got or manuscript._esub(pat, r'<\1>', s) != rx.sub(r'<\1>', s):
            bad.append((pat, s))
            break
check('the bounded search finds exactly what the pattern does', not bad, bad[:3])
for word, label in (('*word ', 'stars'), ('_word ', 'underscores'), ('***word ', 'triple stars')):
    text = word * 20000
    _, secs = timed(lambda: manuscript._inline(text))
    check(f'20,000 unclosed {label} set in under a second', secs < 1.0, f'{secs:.2f}s')
    _, secs = timed(lambda: doc_model._emphasis_runs(text))
    check(f'and the editor reads them in under a second', secs < 1.0, f'{secs:.2f}s')
check('closed emphasis still sets', manuscript._inline('a *b* _c_ ***d*** **e**', False)
      == 'a <i>b</i> <i>c</i> <b><i>d</i></b> <b>e</b>',
      manuscript._inline('a *b* _c_ ***d*** **e**', False))
check('with a stray star after it', manuscript._inline('*b* and *c', False)
      == '<i>b</i> and *c', manuscript._inline('*b* and *c', False))

OLD_ATTR = re.compile(
    r'(\w+)=["“”]((?:(?!\s\w+=["“”]).)*?)["“”](?=\s+\w+=["“”]|\s*$)'
    r'|(\w+)=["“”]([^"“”]*)["“”]')
bad = []
for _ in range(3000):
    s = noise('ab =" “', rng.randint(0, 20))
    old = {(m.group(1) or m.group(3)): (m.group(2) if m.group(1) else m.group(4))
           for m in OLD_ATTR.finditer(s)}
    if manuscript.parse_attrs(s) != old:
        bad.append(s)
check('a fence header reads as it did', not bad, bad[:3])
attrs, secs = timed(lambda: manuscript.parse_attrs('x' * 100000 + ' src="map.png"'))
check('a 100,000-letter word on a fence reads in under a second', secs < 1.0, f'{secs:.2f}s')
check('and its key is still found', attrs == {'src': 'map.png'}, attrs)

# ---- 28.11 ------------------------------------------------------------------
print('28.11 repeated names')
chs = [{'title': 'Interlude', 'blocks': [('para', 'x')]} for _ in range(3)]
chs.insert(1, {'title': 'Interlude 2', 'blocks': [('para', 'x')]})
names = [n[1] for n in manuscript.book_anchors(chs)]
check('a name a title already took is skipped',
      names == ['interlude', 'interlude-2', 'interlude-3', 'interlude-4'], names)
chs = [{'title': 'Interlude', 'blocks': [('para', 'x')]} for _ in range(20000)]
anchors, secs = timed(lambda: manuscript.book_anchors(chs))
check('20,000 chapters of one title are named in under a second', secs < 1.0, f'{secs:.2f}s')
check('each once', len({n for a in anchors for n in a}) == 40000)
blocks = [('subhead', 'Equipment'), ('para', 'x')] * 10000 + [('subhead', 'Equipment 2')]
tg, secs = timed(lambda: manuscript.book_targets([{'title': 'Gear', 'blocks': blocks}]))
heads = tg['headings'][0]
check('10,000 headings of one name are named in under a second', secs < 1.0, f'{secs:.2f}s')
check('in order', [heads[0], heads[2], heads[4]] == ['equipment', 'equipment-2', 'equipment-3'],
      [heads[0], heads[2], heads[4]])
check('and a heading whose own words make a taken name moves on',
      heads[20000] == 'equipment-2-2', heads[20000])

# ---- 28.12 / 28.7 -----------------------------------------------------------
print('28.12 and 28.7 Continuity')
book = {'chapters': [{'title': 'Prologue', 'unnumbered': True, 'blocks': [('para', 'Mara ran.')]},
                     {'title': 'One', 'blocks': [('para', 'Mara ran. Marra hid.')]},
                     {'title': 'Two', 'blocks': [('para', 'Marra ran.')]}]}
issues = checker.run_tier1(book)
var = [i for i in issues if i['label'].startswith('Name variant')]
check('a variant is still found', len(var) == 1, issues)
check('and placed by its printed number', var and re.search(r'first at Chapter\s1\b', var[0]['detail']),
      var and var[0]['detail'])
book['chapters'][0]['unnumbered'] = False
var = [i for i in checker.run_tier1(book) if i['label'].startswith('Name variant')]
check('a changed book is numbered again', var and re.search(r'“Marra”.*Chapter\s2\b', var[0]['detail']),
      var and var[0]['detail'])
big = {'chapters': [{'title': f'T{i}', 'blocks': [('para', 'Hello there')]}
                    for i in range(20000)]}
_, secs = timed(lambda: checker._check_name_variants(big))
check('20,000 chapters are checked in under two seconds', secs < 2.0, f'{secs:.2f}s')
real = checker._MAX_KEYS
checker._MAX_KEYS = 0
try:
    pairs = checker._similar_pairs(['Pinfeather', 'Pinfeathers', 'Ostrander'], 0.85)
finally:
    checker._MAX_KEYS = real
check('past the budget a name is still compared', pairs and sorted(pairs[0]) ==
      ['Pinfeather', 'Pinfeathers'], pairs)
words = [noise('abcdefghijklmnop', 16).capitalize() for _ in range(3000)]
_, secs = timed(lambda: checker._similar_pairs(words, 0.85))
check('3,000 different 16-letter names in under 15 seconds', secs < 15, f'{secs:.2f}s')

# ---- 28.5 -------------------------------------------------------------------
print('28.5 EPUB page references')
chs = [{'title': 'The Gate', 'blocks': [('para', 'x')]},
       {'title': 'Two', 'blocks': [('para', '<a href="#x">see <pageref to="the-gate"/></a> and '
                                             '<pageref to="the-gate"/>')]}]
out, _ = epub._apply_page_refs(chs, {}, {})
para = out[1]['blocks'][0][1]
check('inside a link a reference is its words only',
      para.startswith('<a href="#x">see The Gate</a>'), para)
check('outside one it is a link', para.endswith('<a href="#the-gate">The Gate</a>'), para)
chs[1]['blocks'] = [('para', ' '.join(['<pageref to="the-gate"/>'] * 30000))]
out, secs = timed(lambda: epub._apply_page_refs(chs, {}, {}))
check('30,000 references in a paragraph in under two seconds', secs < 2.0, f'{secs:.2f}s')
check('every one a link', out[0][1]['blocks'][0][1].count('<a href') == 30000)

# ---- 28.14 ------------------------------------------------------------------
print('28.14 running heads')
from reportlab.pdfbase.pdfmetrics import stringWidth


def old_fit(txt, font, size, tw):
    if stringWidth(txt, font, size) > tw:
        words = txt.split()
        while len(words) > 1 and stringWidth(' '.join(words) + '…', font, size) > tw:
            words.pop()
        txt = ' '.join(words).rstrip(',;:.—–-') + '…'
        while len(txt) > 1 and stringWidth(txt, font, size) > tw:
            txt = txt[:-2] + '…'
    return txt


class Fake:
    head_font = 'Times-Roman'
    _fit_head = engine.BookDoc._fit_head


bad = []
for _ in range(2000):
    words = [noise('abcdefghijklmnopqrstuvwxyzWM,.-', rng.randint(1, 14))
             for _ in range(rng.randint(0, 12))]
    txt = ' '.join(words)
    tw = rng.choice([5, 30, 80, 150, 300])
    if Fake()._fit_head(txt, 9, tw) != old_fit(txt, 'Times-Roman', 9, tw):
        bad.append((txt, tw))
check('a head is cut where it always was', not bad, bad[:3])
f = Fake()
long_title = 'W' * 30000
cut, secs = timed(lambda: [f._fit_head(long_title, 9, 300) for _ in range(500)])
check('a 30,000-letter title on 500 pages in under a second', secs < 1.0, f'{secs:.2f}s')
check('cut to the measure', stringWidth(cut[0], 'Times-Roman', 9) <= 300
      and cut[0].endswith('…'), cut[0][:20])

# ---- docx depth (spec) ------------------------------------------------------
print('spec: deeply nested Word files')
TMP = tempfile.mkdtemp(prefix='ts-leftovers-')
import docx
base = os.path.join(TMP, 'base.docx')
docx.Document().save(base)
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def nested_docx(depth):
    inner = '<w:p><w:r><w:t>deep</w:t></w:r></w:p>'
    for _ in range(depth):
        inner = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol/></w:tblGrid><w:tr><w:tc>'
                 f'{inner}<w:p/></w:tc></w:tr></w:tbl><w:p/>')
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}>'
           f'<w:body>{inner}</w:body></w:document>')
    out = os.path.join(TMP, f'deep{depth}.docx')
    with zipfile.ZipFile(base) as zi, zipfile.ZipFile(out, 'w') as zo:
        for it in zi.infolist():
            zo.writestr(it, xml.encode() if it.filename == 'word/document.xml' else zi.read(it))
    return out


md = manuscript.import_docx(nested_docx(80))
check('tables nested 80 deep import', 'deep' in md, md)
try:
    manuscript.import_docx(nested_docx(300))
    err = None
except RecursionError as e:
    err = e
except Exception as e:                                     # refused by the parser
    err = None if 'depth' in str(e).lower() else e
check('300 deep is refused by the parser, not a recursion error', err is None, repr(err))

# ---- 27 drop ----------------------------------------------------------------
print('\n27 text dropped into the rich editor, in a browser')
import app as A
from flask import request
from test_rich_editor import find_browser

SCRIPT = r'''
var R = {};
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
async function run(){
  localStorage.setItem('ts-write-mode', 'rich');
  var f = document.createElement('iframe');
  f.style.width = '1100px'; f.style.height = '800px';
  f.style.position = 'fixed'; f.style.left = '0'; f.style.top = '0';
  await new Promise(function(res){ f.onload = res; f.src = '/project/drop/write';
                                   document.body.appendChild(f); });
  await sleep(300);
  var w = f.contentWindow, d = f.contentDocument, rich = d.getElementById('ms-rich');
  var p = rich.querySelector('.wb-para'), box = p.getBoundingClientRect();
  function drop(html, plain){
    var dt = new w.DataTransfer();
    if (html) dt.setData('text/html', html);
    dt.setData('text/plain', plain);
    var ev = new w.DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true,
                                       clientX: box.right - 2, clientY: box.top + box.height / 2});
    return p.dispatchEvent(ev);
  }
  R.taken = !drop('<span style="color:red;font-family:Comic Sans MS">Dropped</span> <b>words</b>',
                  'Dropped words');
  await sleep(50);
  R.no_style = !rich.innerHTML.match(/color:\s*red|Comic Sans/);
  R.has_text = rich.textContent.indexOf('Dropped') >= 0;
  await sleep(1200);
  R.md = d.getElementById('ms').value;
  rich.setAttribute('contenteditable', 'false');
  R.locked_refused = !drop('', 'While locked');
  R.locked_kept = rich.textContent.indexOf('While locked') < 0;
}
run().then(function(){
  var x = new XMLHttpRequest(); x.open('POST', '/_lo_result', false); x.send(JSON.stringify(R));
}).catch(function(e){
  R.error = String(e && e.stack || e);
  var x = new XMLHttpRequest(); x.open('POST', '/_lo_result', false); x.send(JSON.stringify(R));
});
'''
result = {}


@A.app.route('/_lo_harness')
def _lo_harness():
    return '<!doctype html><meta charset="utf-8"><body><script>' + SCRIPT + '</script>'


@A.app.route('/_lo_result', methods=['POST'])
def _lo_result():
    result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


browser = find_browser()
if not browser or os.environ.get('TS_SKIP_BROWSER'):
    print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
else:
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
    with open(os.path.join(A.PROJECT_MS_DIR, 'drop.md'), 'w', encoding='utf-8') as fh:
        fh.write('# One\n\nThe text.\n')
    A.save_project_file('drop', dict(
        name='drop', title='T', author='A', preset='classic-literary', format='pdf',
        manuscript_file='drop.md', manuscript_type='markdown', cover_file='', cover_mode='none',
        last_pdf='', last_epub='', created='2026-01-01T00:00:00',
        updated='2026-01-01T00:00:00', front_matter='none'))
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                        '--user-data-dir=' + os.path.join(TMP, 'browser'),
                        '--window-size=1200,900', '--virtual-time-budget=20000', '--dump-dom',
                        f'http://127.0.0.1:{server.server_port}/_lo_harness'],
                       capture_output=True, timeout=180)
    finally:
        server.shutdown()
    r = result
    check('the page ran', bool(r) and 'error' not in r, r)
    if r and 'error' not in r:
        check('a drop from outside is taken over', r.get('taken'), r)
        check('its styling is left behind', r.get('no_style'), r)
        check('its words are kept', r.get('has_text'), r)
        check('and reach the manuscript', 'Dropped' in (r.get('md') or ''), r.get('md'))
        check('a locked editor takes no drop', r.get('locked_refused') and r.get('locked_kept'), r)

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('all passed')
