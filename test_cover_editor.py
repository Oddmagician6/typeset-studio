"""Cover-template editor tests in a real browser  (run: python test_cover_editor.py).

A bug hunt turned into a test (roadmap: "browser bug hunt on the cover editor"),
the way test_rich_editor.py was for the manuscript editor. It serves the app
against throwaway folders, opens the real cover editor in headless Chrome or
Edge, and does what a writer does there. The checks are about agreement:

    ROUND TRIP  opening a template and saving it unchanged gives back the same
                template - every family's own settings included
    PREVIEW     the editor's live preview is the cover the template prints

Needs a Chromium browser (TS_BROWSER to point at one); without one the browser
half is skipped and says so.
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
import engine
from test_rich_editor import find_browser
from werkzeug.serving import make_server
from flask import request

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-covered-')
A.COVER_DIR = os.path.join(tmp, 'covers')
A.COVER_ASSET_DIR = engine.COVER_ASSET_DIR = os.path.join(A.COVER_DIR, 'assets')
A.OUT_DIR = os.path.join(tmp, 'out')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
for d in (A.COVER_ASSET_DIR, A.OUT_DIR, A.PROJECT_MS_DIR):
    os.makedirs(d)
for f in glob.glob(os.path.join(HERE, 'covers', '*.json')):
    shutil.copy(f, A.COVER_DIR)
ORIGINAL = {os.path.basename(f)[:-5]: json.load(open(f, encoding='utf-8'))
            for f in glob.glob(os.path.join(A.COVER_DIR, '*.json'))}
CIDS = sorted(ORIGINAL)

captured = {}          # cid -> the form the editor would submit, as (name, value) pairs

# The harness: each template's editor in turn, in an iframe; once its first
# preview has rendered, the form exactly as Save would send it is posted back.
SCRIPT = r'''
var cids = %s, i = 0, f = document.getElementById('f');
function next() {
  if (i >= cids.length) { var x = new XMLHttpRequest(); x.open('POST', '/_ce_done', false); x.send('1'); return; }
  f.src = '/cover/' + cids[i];
}
f.onload = function () {
  var d = f.contentDocument, cid = cids[i];
  var wait = setInterval(function () {
    var st = d.getElementById('pv-status');
    if (!st || st.textContent.indexOf('Updated') !== 0) return;
    clearInterval(wait);
    var form = d.querySelector('form.editor'), pairs = [];
    new f.contentWindow.FormData(form).forEach(function (v, k) { if (typeof v === 'string') pairs.push([k, v]); });
    var x = new XMLHttpRequest(); x.open('POST', '/_ce_capture/' + cid, false);
    x.send(JSON.stringify({form: pairs, preview: d.getElementById('pv-img').src}));
    i++; next();
  }, 50);
};
next();
'''
done = threading.Event()

# A book to fill the print wrap from, set for an IngramSpark jacket on cream paper.
BOOK = 'tidewater'
with open(os.path.join(A.PROJECT_MS_DIR, BOOK + '.md'), 'w', encoding='utf-8') as fh:
    fh.write('# One\n\nText.\n')
A.save_project_file(BOOK, {'name': 'The Tidewater', 'preset': 'classic-literary',
                           'title': 'The Tidewater', 'author': 'Ada Merrow', 'publisher': 'Ashforge',
                           'manuscript_file': BOOK + '.md', 'manuscript_type': 'file',
                           'cover_mode': 'none', 'last_page_count': 288,
                           'print_retailer': 'ingramspark', 'print_paper': 'cream',
                           'print_binding': 'jacket', 'print_blurb': 'A tide that never turns.',
                           'print_flap_blurb': 'Front flap words.', 'print_flap_bio': 'Ada lives by the sea.'})

# What a writer does on one template's page, in order; each step reports back.
SCRIPT2 = r'''
var f = document.getElementById('f'), out = {};
window.onerror = function (msg, src, line) { out.error = msg + ' @' + line; send(); };
function send() { var x = new XMLHttpRequest(); x.open('POST', '/_ce_scenarios', false); x.send(JSON.stringify(out)); }
f.onload = function () {
  if (f.contentWindow.location.pathname !== '/cover/ashforge-house') {   // after the save
    out.saved_to = f.contentWindow.location.pathname; send(); return;
  }
  var w = f.contentWindow, d = f.contentDocument, form = d.querySelector('form.editor');
  w.onerror = function (msg, src, line) { out.error = msg + ' @' + line; send(); };
  var st = d.getElementById('pv-status'), img = d.getElementById('pv-img');
  var field = function (n) { return form.querySelector('[name="' + n + '"]'); };
  var set = function (n, v) { var el = field(n); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles:true}));
                              el.dispatchEvent(new w.Event('change', {bubbles:true})); };
  // previews finished, counted as the page reads each answer: a preview that
  // comes back the same picture is still a preview
  var renders = 0, of = w.fetch;
  w.fetch = function (u) {
    return of.apply(w, arguments).then(function (res) {
      if (String(u).indexOf('/cover/preview') === -1) return res;
      var oj = res.json.bind(res);
      res.json = function () { return oj().then(function (j) { setTimeout(function () { renders++; }, 0); return j; }); };
      return res;
    });
  };
  var rendered = function (since, then) {
    var n = renders;
    var t = setInterval(function () {
      if (renders <= n && !(since === '' && st.textContent.indexOf('Updated') === 0)) return;
      clearInterval(t);
      then(st.textContent.indexOf('Updated') === 0 ? undefined : st.textContent);
    }, 50);
  };
  rendered('', function () {
    var first = img.src;
    // 1. another design family: the preview changes
    set('design', 'typographic');
    rendered(first, function (err) {
      out.family_preview = !err && img.src !== first;
      // 2. awkward numbers: empty, negative, huge - the preview still renders
      var before = img.src;
      set('title_size', ''); set('title_y', '-3'); set('kick_size', '9999');
      rendered(before, function (err2) {
        out.odd_numbers = err2 || 'ok';
        set('design', 'classic-frame'); set('title_size', '40'); set('title_y', '0.585'); set('kick_size', '11');
        // 3. background art and an emblem, uploaded through the file pickers
        var png = Uint8Array.from(atob(%s), function (c) { return c.charCodeAt(0); });
        var up = function (target, then) {
          var inp = d.querySelector('.img-file[data-target="' + target + '"]');
          var dt = new w.DataTransfer();
          dt.items.add(new w.File([png], 'art.png', {type:'image/png'}));
          inp.files = dt.files; inp.dispatchEvent(new w.Event('change'));
          var t = setInterval(function () { if (field(target).value) { clearInterval(t); then(); } }, 50);
        };
        up('bg_image', function () {
          out.bg_image = field('bg_image').value;
          up('emblem1_image', function () {
            out.emblem = field('emblem1_image').value;
            out.slotmap = d.getElementById('slotmap-dims').textContent;
            // 4. the print wrap: fill from a book, then each binding previews
            var from = d.getElementById('wrap-from');
            from.value = %s; from.dispatchEvent(new w.Event('change'));
            out.from_book = {retailer: field('wrap_retailer').value, paper: field('wrap_paper').value,
                             binding: field('wrap_binding').value, pages: field('wrap_pages').value,
                             blurb: field('wrap_blurb').value, flap: field('wrap_flap_blurb').value,
                             trim_w: field('wrap_trim_w').value, prev_w: field('prev_w').value,
                             flaps_shown: !d.getElementById('wrap-flap-copy').hidden};
            var bindings = ['paperback', 'hardcover', 'jacket'], k = 0, ws = d.getElementById('wrap-status');
            out.wraps = {};
            var nextWrap = function () {
              if (k >= bindings.length) return download();
              set('wrap_binding', bindings[k]);
              ws.textContent = '';
              d.getElementById('wrap-pv').click();
              var t = setInterval(function () {
                if (!ws.textContent || ws.textContent.indexOf('Rendering') === 0) return;
                clearInterval(t); out.wraps[bindings[k]] = ws.textContent; k++; nextWrap();
              }, 50);
            };
            // 5. the wrap download, named for a cover whose name has no ASCII in it
            var download = function () {
              set('name', 'Тайга');
              var names = [];
              var orig = w.HTMLAnchorElement.prototype.click;
              w.HTMLAnchorElement.prototype.click = function () { names.push(this.download); };
              d.getElementById('wrap-dl').click();
              var t = setInterval(function () {
                if (ws.textContent !== 'Downloaded.' && ws.textContent.indexOf('failed') === -1) return;
                clearInterval(t);
                w.HTMLAnchorElement.prototype.click = orig;
                out.download = [ws.textContent, names[0]];
                // 6. save it, for real: the browser posts the form and follows the redirect
                set('name', 'Тайга <b>"quoted"</b>');
                send();
                form.submit();
              }, 50);
            };
            nextWrap();
          });
        });
      });
    });
  });
};
f.src = '/cover/ashforge-house';
'''
scen = {}

@A.app.route('/_ce_harness2')
def _ce_harness2():
    import base64, io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (600, 900), (30, 120, 90)).save(buf, 'PNG')
    data = json.dumps(base64.b64encode(buf.getvalue()).decode())
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT2 % (data, json.dumps(BOOK)) + '</script>')

@A.app.route('/_ce_scenarios', methods=['POST'])
def _ce_scenarios():
    scen.update(json.loads(request.get_data(as_text=True)))
    return 'ok'

@A.app.route('/_ce_harness')
def _ce_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT % json.dumps(CIDS) + '</script>')

@A.app.route('/_ce_capture/<cid>', methods=['POST'])
def _ce_capture(cid):
    captured[cid] = json.loads(request.get_data(as_text=True))
    return 'ok'

@A.app.route('/_ce_done', methods=['POST'])
def _ce_done():
    done.set()
    return 'ok'


def as_form(pairs):
    from werkzeug.datastructures import MultiDict
    return MultiDict(pairs)


def differences(a, b, path=''):
    """Where two templates differ, as 'path: old -> new' strings (numbers compared as numbers)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out.append(f'{path}{k}: dropped')
            elif k not in a:
                continue                          # a default filled in is not a loss
            else:
                out += differences(a[k], b[k], f'{path}{k}.')
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-9:
            out.append(f'{path[:-1]}: {a} -> {b}')
    elif a != b:
        out.append(f'{path[:-1]}: {a!r} -> {b!r}')
    return out


try:
    browser = find_browser()
    print('[opening every template in the editor]')
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=300000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_ce_harness'],
                           capture_output=True, timeout=600)
        finally:
            server.shutdown()
        check('the editor opened and previewed every template', len(captured) == len(CIDS),
              sorted(set(CIDS) - set(captured)))

        print('\n[ROUND TRIP: saved unchanged, a template is itself]')
        for cid in CIDS:
            if cid not in captured:
                continue
            saved = A.parse_cover_form(as_form(captured[cid]['form']))
            diff = differences(ORIGINAL[cid], saved)
            check(f'{cid}', not diff, diff[:6])

        print('\n[PREVIEW: the editor shows the cover the template prints]')
        import base64, fitz
        from PIL import Image, ImageChops
        import io, manuscript, matter
        for cid in CIDS:
            if cid not in captured:
                continue
            form = as_form(captured[cid]['form'])
            # the page 1 the template makes, from the same sample text the preview uses
            meta = {'title': form.get('prev_title'), 'author': form.get('prev_author'),
                    'year': '2026', 'publisher': form.get('prev_studio'), 'front_matter': 'none',
                    'right_hand_starts': False, 'smartquotes': True, 'cover_mode': 'designed',
                    'cover_template': cid, 'cover_template_data': ORIGINAL[cid],
                    'cover_collection': form.get('prev_collection'), 'cover_kicker': form.get('prev_kicker'),
                    'cover_accent': form.get('prev_accent', ''), 'cover_epigraph': form.get('prev_epigraph', ''),
                    'cover_studio': form.get('prev_studio'), 'cover_image': '', 'cover_overlay': False,
                    'cover_color': 'light', **matter.blank()}
            preset = dict(A.DEFAULTS, trim={'w': 6.0, 'h': 9.0})
            path = os.path.join(tmp, 'real.pdf')
            engine.build_pdf(manuscript.parse_markdown(A.PREVIEW_SAMPLE, smartquotes=True), preset, path, meta)
            with fitz.open(path) as doc:
                real = Image.open(io.BytesIO(doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                                             .tobytes('png'))).convert('RGB')
            shown = Image.open(io.BytesIO(base64.b64decode(captured[cid]['preview'].split(',', 1)[1]))).convert('RGB')
            same = real.size == shown.size and not ImageChops.difference(real, shown).getbbox()
            check(f'{cid}', same)

        print('\n[a writer at work on one template]')
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser2'),
                            '--window-size=1400,1000', '--virtual-time-budget=300000', '--dump-dom',
                            f'http://127.0.0.1:{server.server_port}/_ce_harness2'],
                           capture_output=True, timeout=600)
        finally:
            server.shutdown()
        s = scen
        check('the scenarios ran to the end', 'saved_to' in s, s.get('error') or sorted(s))
        if s:
            check('another design family changes the preview', s.get('family_preview'))
            check('an empty, a negative and a huge number still preview', s.get('odd_numbers') == 'ok',
                  s.get('odd_numbers'))
            check('background art uploads through its picker', bool(s.get('bg_image')) and
                  os.path.isfile(os.path.join(A.COVER_ASSET_DIR, s.get('bg_image', '-'))), s.get('bg_image'))
            check('and so does an emblem, which the slot map then measures',
                  bool(s.get('emblem')) and 'Emblem 1' in s.get('slotmap', ''), s.get('slotmap'))
            fb = s.get('from_book', {})
            check("'From a book' takes the book's page count and trim",
                  fb.get('pages') == '288' and fb.get('trim_w') == '6', fb)
            check("and its printer, paper and binding - the spine's width depends on them",
                  (fb.get('retailer'), fb.get('paper'), fb.get('binding')) == ('ingramspark', 'cream', 'jacket'), fb)
            check('and its back-cover and flap copy',
                  fb.get('blurb') == 'A tide that never turns.' and fb.get('flap') == 'Front flap words.'
                  and fb.get('flaps_shown'), fb)
            wraps = s.get('wraps', {})
            check('the wrap previews in every binding',
                  len(wraps) == 3 and all('fail' not in v.lower() for v in wraps.values()), wraps)
            dl = s.get('download', ['', ''])
            check('the wrap downloads', dl[0] == 'Downloaded.', dl)
            check('named sensibly when the cover\'s name has no ASCII in it',
                  dl[1] and not dl[1].startswith('-') and dl[1].endswith('.pdf'), dl[1])
            check('Save goes back to the covers list', s.get('saved_to') == '/covers', s.get('saved_to'))
            made = {k: v for k, v in ((os.path.basename(f)[:-5], json.load(open(f, encoding='utf-8')))
                                      for f in glob.glob(os.path.join(A.COVER_DIR, '*.json')))
                    if v.get('name', '').startswith('Тайга')}
            check('and the cover is saved under its name, quotes and all',
                  any(v['name'] == 'Тайга <b>"quoted"</b>' for v in made.values()), list(made))
            if made:
                saved_id = next(iter(made))
                page = A.app.test_client().get('/cover/' + saved_id).get_data(as_text=True)
                check('which reopens with its name escaped, not run as HTML',
                      '<b>"quoted"</b>' not in page and 'Тайга' in page)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
