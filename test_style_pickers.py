"""The style editor's pickers  (run: python test_style_pickers.py).

Bug hunt item 10. test_style_editor.py proves a style opened and saved unchanged
is itself; this drives what a writer clicks on the same page, in headless Chrome
against throwaway folders, and checks:

    SAVE      the Save button submits every bundled style (a number's `step` made
              the browser refuse three of them, and five standard trims), and an
              unchanged save through the real button gives the style back
    TRIMS     the standard-size picker shows the style's trim, and every size
              picked from it is kept and can be saved
    BREAKS    an ornament tile or a picture picked on a glyph style makes that
              the scene break; "none" goes back to the glyph
    MISSING   a font, chapter art or scene-break picture the libraries don't have
              is marked in its picker, and the preview says what it drew without
    NUMBERS   a typed 0, a negative, NaN or a huge number is held to its range;
              no real style is outside one; a style that can't fit a page says so
              in words, not ReportLab's
    PICTURES  a scene-break picture comes from the figure library (and still from
              the font folder, where it had to live before); one that is gone is
              in the checks; deleting it from the library asks first
"""

import sys, os, io, json, glob, shutil, tempfile, threading, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine, epub, manuscript, matter
from test_rich_editor import find_browser
from werkzeug.serving import make_server
from werkzeug.datastructures import MultiDict
from flask import request
logging.disable(logging.CRITICAL)        # after test_rich_editor's import resets it

def differences(a, b, path=''):
    """Where two styles differ (a key the save fills in is not a loss)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in a for d in (differences(a[k], b[k], f'{path}{k}.') if k in b
                                       else [f'{path}{k}: dropped'])]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) < 1e-9 else [f'{path[:-1]}: {a} -> {b}']
    return [] if a == b else [f'{path[:-1]}: {a!r} -> {b!r}']


fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-pickers-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
shutil.copytree(os.path.join(HERE, 'fonts'), os.path.join(ROOT, 'fonts'),
                ignore=shutil.ignore_patterns('licenses'))
A.PRESET_DIR = os.path.join(ROOT, 'presets')
A.FONT_DIR = engine.FONT_DIR = os.path.join(ROOT, 'fonts')
A.FIGURE_DIR = engine.FIGURE_DIR = epub.FIGURE_DIR = manuscript.FIGURE_DIR = \
    os.path.join(ROOT, 'figures')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
for d in (A.FIGURE_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR, A.OUT_DIR):
    os.makedirs(d, exist_ok=True)


def png(path, w=120, h=30):
    from PIL import Image
    Image.new('RGB', (w, h), (90, 40, 30)).save(path, 'PNG')


png(os.path.join(A.FIGURE_DIR, 'crest.png'))
png(os.path.join(A.FONT_DIR, 'legacy-break.png'))       # where 1.x styles kept one
BUNDLED = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(A.PRESET_DIR, '*.json')))
ORIGINAL = {pid: A.load_preset(pid) for pid in BUNDLED}

lost = json.loads(json.dumps(ORIGINAL['classic-literary']))
lost['name'] = 'Lost things'
lost['font_files']['regular'] = 'Gone-Regular.ttf'
lost['chapter_art'] = dict(lost.get('chapter_art') or {}, image='lost-art.png')
lost['scene_break'].update(type='image', image='lost-break.png')
A.save_preset('lost-things', lost)

GLYPH = 'thriller-crime'          # 5.5 x 8.5, a glyph scene break
check('the tile test starts from a glyph style',
      ORIGINAL[GLYPH]['scene_break']['type'] == 'glyph')
SHAPES = [k for k, v in ORIGINAL.items()
          if (v['trim']['w'], v['trim']['h']) in {(w, h) for w, h, _ in A.TRIM_PRESETS}]

# ---------------------------------------------------------------- the browser
got = {}

SCRIPT = r'''
window.onerror = function (m, u, l) { out.error = m + ' @' + l; send(); };
var STYLES = %(styles)s, GLYPH = %(glyph)s, f = document.getElementById('f'), out = {}, k = 0;
function send() {
  var x = new XMLHttpRequest(); x.open('POST', '/_sp_capture', false);
  x.send(JSON.stringify(out));
}
function form(d) { return d.querySelector('form.editor'); }
function submittable(d) { var fm = form(d); return fm.noValidate || fm.checkValidity(); }
function selText(d, name) { var s = d.querySelector('[name=' + name + ']');
  return s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''; }
function preview(d, then) {
  d.getElementById('preview-btn').click();
  var st = d.getElementById('preview-status');
  var t = setInterval(function () {
    if (!st.textContent || st.textContent.indexOf('Rendering') === 0) return;
    clearInterval(t);
    var w = []; d.querySelectorAll('#preview-warn li').forEach(function (li) { w.push(li.textContent); });
    then(st.textContent, w);
  }, 50);
}
var steps = [];
STYLES.concat(['new']).forEach(function (pid) {
  steps.push({url: pid === 'new' ? '/editor/new' : '/editor/' + pid, run: function (d, w, next) {
    out['open:' + pid] = {submittable: submittable(d), pick: d.getElementById('trim-pick').value};
    next();
  }});
});
// every standard size, picked from the list, stays picked and can be saved
steps.push({url: '/editor/' + GLYPH, run: function (d, w, next) {
  var pick = d.getElementById('trim-pick'), rows = [];
  for (var i = 1; i < pick.options.length; i++) {
    pick.selectedIndex = i; pick.dispatchEvent(new Event('change'));
    var want = pick.options[i].value;
    d.getElementById('f-tw').dispatchEvent(new Event('input', {bubbles: true}));
    rows.push({want: want, kept: pick.value, submittable: submittable(d),
               w: d.getElementById('f-tw').value, h: d.getElementById('f-th').value});
  }
  out.trims = rows; next();
}});
// tiles and the picture on a glyph style
steps.push({url: '/editor/' + GLYPH, run: function (d, w, next) {
  var type = d.querySelector('[name=sb_type]'), rows = [];
  d.querySelectorAll('[name=sb_ornament]').forEach(function (r) {
    r.closest('label').click();
    rows.push({id: r.value, type: type.value, card: d.getElementById('pv-break').textContent});
  });
  out.tiles = rows;
  var img = d.querySelector('[name=sb_image]');
  img.value = 'crest.png'; img.dispatchEvent(new Event('change', {bubbles: true}));
  out.image_on = {type: type.value, card: d.getElementById('pv-break').textContent};
  img.value = ''; img.dispatchEvent(new Event('change', {bubbles: true}));
  out.image_off = {type: type.value};
  out.image_options = Array.prototype.map.call(img.options, function (o) { return o.value; });
  next();
}});
// what the libraries don't have
steps.push({url: '/editor/lost-things', run: function (d, w, next) {
  out.lost = {regular: selText(d, 'font_regular'), art: selText(d, 'ca_image'),
              scene: selText(d, 'sb_image')};
  preview(d, function (status, warn) { out.lost.preview = status; out.lost.warn = warn; next(); });
}});
// the real Save button: a style the browser used to refuse, unchanged
// (a submitting step moves on first: the page it lands on runs the next step)
function submit(d, key) {
  k++;
  d.querySelector('form.editor button[type=submit]').click();
  setTimeout(function () { if (!out[key]) { out[key] = 'stayed on the page'; k++; go(); } }, 3000);
}
steps.push({url: '/editor/mass-market', run: function (d, w, next) { submit(d, 'saved_mm'); }});
steps.push({url: null, run: function (d, w, next) { out.saved_mm = w.location.pathname; next(); }});
// a writer's change through the same button: a trim the browser refused, a tile
steps.push({url: '/editor/' + GLYPH, run: function (d, w, next) {
  var pick = d.getElementById('trim-pick');
  pick.value = '6.14x9.21'; pick.dispatchEvent(new Event('change'));
  d.querySelector('[name=sb_ornament][value=fleuron]').closest('label').click();
  submit(d, 'saved_glyph');
}});
steps.push({url: null, run: function (d, w, next) { out.saved_glyph = w.location.pathname; next(); }});

function go() {
  if (k >= steps.length) { send(); return; }
  if (steps[k].url) f.src = steps[k].url;       // else: the page is already on its way
}
f.onload = function () {
  var s = steps[k];
  if (!s) return;
  s.run(f.contentDocument, f.contentWindow, function () { if (steps[k] === s) { k++; go(); } });
};
go();
'''


@A.app.route('/_sp_harness')
def _sp_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT % {'styles': json.dumps(BUNDLED + ['lost-things']),
                                            'glyph': json.dumps(GLYPH)} + '</script>')


@A.app.route('/_sp_capture', methods=['POST'])
def _sp_capture():
    got.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def opened(pid):
    return got.get('open:' + pid) or {}


try:
    browser = find_browser()
    print('[the style editor in a browser]')
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
    else:
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                            '--user-data-dir=' + os.path.join(tmp, 'browser'),
                            '--window-size=1400,1000', '--virtual-time-budget=300000',
                            '--dump-dom', f'http://127.0.0.1:{server.server_port}/_sp_harness'],
                           capture_output=True, timeout=600)
        finally:
            server.shutdown()
        check('the harness ran to the end', 'saved_glyph' in got and 'error' not in got,
              got.get('error') or sorted(got))

        print('\n[SAVE: the button submits every style]')
        for pid in BUNDLED + ['new']:
            check(pid, opened(pid).get('submittable'), opened(pid))
        check('mass market saved through the real button', got.get('saved_mm') == '/',
              got.get('saved_mm'))
        diff = differences(ORIGINAL['mass-market'], A.load_preset('mass-market'))
        check('... and is itself afterwards', not diff, diff)

        print('\n[TRIMS: the picker shows and keeps a standard size]')
        for pid in SHAPES:
            t = ORIGINAL[pid]['trim']
            check(f'{pid} opens on {t["w"]:g} x {t["h"]:g}',
                  opened(pid).get('pick') == f'{t["w"]:g}x{t["h"]:g}', opened(pid).get('pick'))
        for row in got.get('trims', []):
            check(f'{row["want"]} stays picked and can be saved',
                  row['kept'] == row['want'] and row['submittable'], row)
        check('every standard size was tried', len(got.get('trims', [])) == len(A.TRIM_PRESETS))
        saved = A.load_preset(GLYPH)
        check('a 6.14 x 9.21 trim picked and saved', (saved['trim']['w'], saved['trim']['h'])
              == (6.14, 9.21), saved['trim'])

        print('\n[BREAKS: picking an ornament or a picture is picking that break]')
        for row in got.get('tiles', []):
            want = 'ornament' if row['id'] else 'glyph'
            check(f'tile {row["id"] or "none"} -> {want}', row['type'] == want, row)
        check('a tile names itself on the spec card',
              any(r['id'] == 'fleuron' and r['card'] == 'Ivy leaf' for r in got.get('tiles', [])),
              got.get('tiles'))
        check('a picture picked -> image', got.get('image_on', {}).get('type') == 'image'
              and got['image_on']['card'] == 'crest.png', got.get('image_on'))
        check('the picture taken off -> glyph', got.get('image_off', {}).get('type') == 'glyph',
              got.get('image_off'))
        check('pictures come from the figure library',
              got.get('image_options') == ['', 'crest.png'], got.get('image_options'))
        check('the tile picked before Save is the scene break saved',
              saved['scene_break']['type'] == 'ornament'
              and saved['scene_break']['ornament'] == 'fleuron', saved['scene_break'])

        print('\n[MISSING: the pickers and the preview say what is not there]')
        lostp = got.get('lost', {})
        check('a missing font is marked', 'not in your font library' in lostp.get('regular', ''),
              lostp)
        check('missing chapter art is marked', 'not in your figure library' in lostp.get('art', ''),
              lostp)
        check('a missing scene-break picture is marked',
              'not in your figure library' in lostp.get('scene', ''), lostp)
        warn = ' | '.join(lostp.get('warn', []))
        check('the preview still renders', lostp.get('preview', '').endswith('pages'), lostp)
        check('the preview says it fell back to Times', 'Times' in warn, warn)
        check('the preview names the chapter art', 'lost-art.png' in warn, warn)
        check('the preview names the scene-break picture', 'lost-break.png' in warn, warn)

    # ------------------------------------------------------------ no browser needed
    print('\n[NUMBERS: held to their range]')
    for field, typed, path, want in [
            ('b_size', '0', ('body', 'size'), 4.0),
            ('b_size', 'nan', ('body', 'size'), 11.0),
            ('b_size', '1e999', ('body', 'size'), 11.0),
            ('m_top', '-1', ('margins', 'top'), 0.0),
            ('trim_w', '0', ('trim', 'w'), 2.0),
            ('pd_sink', '5', ('part_divider', 'sink'), 1.0),
            ('s_gap', '500', ('scene_break', 'gap'), 144.0),
            ('c_dropcap_lines', '40', ('chapter', 'dropcap_lines'), 10),
            ('fo_size', 'large', ('folio', 'size'), 9.5)]:
        v = A.parse_preset_form(MultiDict({field: typed}))
        for p in path:
            v = v[p]
        check(f'{field} typed as {typed} -> {want}', v == want, v)

    # every number in every style a release has shipped, the user has saved here,
    # or the installed app holds, is already inside its range
    keys = sorted(A.STYLE_RANGES)
    probe = MultiDict({k: repr(sum(A.STYLE_RANGES[k]) / 2 + i * 1e-7) for i, k in enumerate(keys)})
    where = {}
    def walk(d, path):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, path + [k])
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                for f in keys:
                    if abs(float(probe[f]) - v) < 5e-8 or (isinstance(v, int)
                                                          and int(float(probe[f])) == v):
                        where.setdefault(f, path + [k])
    walk(A.parse_preset_form(probe), [])
    check('every number field has a range and a place', len(where) == len(keys),
          sorted(set(keys) - set(where)))
    files = glob.glob(os.path.join(HERE, 'presets', '*.json'))
    files += glob.glob(os.path.join(HERE, 'test_fixtures', '*', 'presets', '*.json'))
    files += glob.glob(os.path.join(os.environ.get('APPDATA', tmp), 'Typeset Studio',
                                    'presets', '*.json'))
    outside = []
    for fn in files:
        try:
            s = A.read_json(fn)
        except Exception:
            continue
        for f, path in where.items():
            v = s
            for p in path:
                v = v.get(p) if isinstance(v, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and not A.STYLE_RANGES[f][0] <= v <= A.STYLE_RANGES[f][1]:
                outside.append(f'{os.path.relpath(fn, HERE)} {f}={v}')
    check(f'no real style is outside a range ({len(files)} files)', not outside, outside[:6])

    print('\n[NUMBERS: a style that cannot fit a page says so]')
    with A.app.test_client() as c:            # a 10" sink on a 9" page: in range, too tall
        r = c.post('/preview', data={'c_sink': '10', 'trim_h': '9'}).get_json()
    check('the preview refuses it', r and not r['ok'], r)
    check('... in words', r and 'doesn’t fit' in r.get('error', '')
          and 'Flowable' not in r.get('error', ''), r and r.get('error'))

    print('\n[PICTURES: scene-break pictures]')
    ms = manuscript.parse_markdown('# One\n\nBefore.\n\n* * *\n\nAfter.\n', smartquotes=True)
    meta = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
            'front_matter': 'none', 'right_hand_starts': False, 'cover_image': '',
            'cover_overlay': False, 'cover_color': 'light', 'smartquotes': True, **matter.blank()}

    def scene(image):
        import fitz
        p = json.loads(json.dumps(ORIGINAL[GLYPH]))
        p['scene_break'].update(type='image', image=image)
        out = os.path.join(tmp, 'scene.pdf')
        res = engine.build_pdf(ms, p, out, meta)
        doc = fitz.open(out)
        n = sum(len(pg.get_images()) for pg in doc)
        doc.close()
        return res, n

    res, n = scene('crest.png')
    check('a figure-library picture prints', n == 1 and not res['scene_image_missing'], (n, res['scene_image_missing']))
    res, n = scene('legacy-break.png')
    check('a font-folder picture (1.x) still prints', n == 1 and not res['scene_image_missing'], (n, res['scene_image_missing']))
    res, n = scene('nowhere.png')
    check('a gone picture prints the glyph', n == 0)
    rows = A._preflight(res, ORIGINAL[GLYPH], res['page_count'])
    row = next((r for r in rows if r['label'] == 'Scene breaks'), None)
    check('... and the checks say so', row and not row['ok'] and 'nowhere.png' in row['detail'], rows)
    with open(os.path.join(A.FIGURE_DIR, 'cut.png'), 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n not really')
    res, n = scene('cut.png')
    check('an unreadable picture is in the checks too', res['scene_image_missing'] == 'cut.png', res['scene_image_missing'])
    pic = json.loads(json.dumps(ORIGINAL[GLYPH]))
    pic['name'] = 'Crested'
    pic['scene_break'].update(type='image', image='crest.png')
    A.save_preset('crested', pic)
    uses = A._figure_uses('crest.png')
    check('deleting the picture says the style uses it',
          any('Crested' in u and 'scene breaks' in u for u in uses), uses)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
