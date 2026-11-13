"""Picture books, part 1: colour print and picture-book trims (ROADMAP #75b-1)
(run: python test_picture_books.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.
Everything runs against throwaway folders, set up here.

Held here:

  1. the colour canvas: neutrals become K-only, colours are left as set;
  2. a colour interior's press PDF keeps a designed page's colour and a
     chromatic style colour, while black text stays one ink; a black-and-white
     press build is as before (greys, and a fallback for a chromatic style);
     the press check reads each for what it is;
  3. the picture-book trims, square and landscape: each builds at its size,
     with bleed too, every word inside the trim; the cover wrap is two trims
     wide plus the spine;
  4. the app: the colour papers (premium keeps the old key and caliper), the
     book's colour interior from its paper, Send to print's package built in
     colour, and the Picture Book style building and surviving the style
     editor's round trip.
"""
import copy, os, re, shutil, sys, tempfile, traceback, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, manuscript
import fitz
from reportlab.lib import colors as RC

fails = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


# throwaway folders: the app writes nothing into the real ones
tmp = tempfile.mkdtemp(prefix='ts-picture-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(ROOT, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(ROOT, 'presets'), os.path.join(ROOT, 'covers')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
A.UPLOAD_DIR = os.path.join(ROOT, 'uploads')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR, A.PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)
A.app.config['TESTING'] = True
C = A.app.test_client()

RED = '#c03020'
META = {'title': 'The Kite Day', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True,
        'index_statblocks': False, 'index_cr': False}
L = 'The kite went up and up over the hill and the dog ran after it. ' * 12


def design(name='kite'):
    return {'name': name, 'saved': '2026-11-13T10:00:00', 'elements': [
        {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': RED},
        {'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 1, 'w': 4,
         'text': 'Up it goes', 'font': 'Andika-Regular.ttf', 'size': 28, 'color': '#000000'}]}


def preset(**kw):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    p.update(kw)
    return p


def build(md, name, p=None, press=False, **meta):
    out = os.path.join(tmp, name + '.pdf')
    m = dict(META, page_designs=[design()], **meta)
    res = engine.build_pdf(manuscript.parse_markdown(md), p or preset(), out, m, press=press)
    return out, res


def pixel(page, x, y, dpi=36):
    pm = page.get_pixmap(dpi=dpi)
    k = dpi / 72.0
    return pm.pixel(min(int(x * k), pm.width - 1), min(int(y * k), pm.height - 1))


def near(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def grey(px):
    return abs(px[0] - px[1]) < 8 and abs(px[1] - px[2]) < 8


def ops(path):
    with fitz.open(path) as doc:
        return ''.join(pg.read_contents().decode('latin-1') for pg in doc)


def designed_page(path):
    with fitz.open(path) as doc:
        return [i for i, pg in enumerate(doc) if 'Up it goes' in pg.get_text()][0]


MD = '# The Kite\n\n' + L + '\n\n~~~ page src="kite"\n~~~\n\n' + L


# ---------------------------------------------------------------- 1
def canvas_tests():
    print('\n[the colour canvas]')
    k = engine._neutral_to_k
    black = k((0, 0, 0))
    check('black becomes K-only', isinstance(black, RC.CMYKColor)
          and (black.cyan, black.magenta, black.yellow, black.black) == (0, 0, 0, 1), black)
    g = k(RC.Color(.5, .5, .5))
    check('a grey becomes a tint of K', isinstance(g, RC.CMYKColor) and abs(g.black - .5) < 1e-3, g)
    check('so does a hex grey and a CMYK grey',
          isinstance(k('#808080'), RC.CMYKColor) and k(RC.CMYKColor(0, 0, 0, .3)).black == .3)
    red = RC.HexColor(RED)
    check('a colour is left as set', k(red) is red)
    check('a rich black is left as set (it was set on purpose)',
          k(RC.CMYKColor(.6, .4, .4, 1)).cyan == .6)


# ---------------------------------------------------------------- 2
def press_tests():
    print('\n[a colour interior, press-ready]')
    out, res = build(MD, 'colour', press=True, colour_interior=True)
    n = designed_page(out)
    with fitz.open(out) as doc:
        px = pixel(doc[n], 30, 30)
    check('it builds press-ready, as a colour interior',
          res['press'] and res['colour'] and not res.get('press_error'), res.get('press_error'))
    check('the designed page keeps its colour', near(px, (192, 48, 32)), px)
    body = ops(out)
    check('black text is K-only, never RGB black',
          '0 0 0 1 k' in body and not re.search(r'(?<![\d.])0 0 0 rg', body))
    rows = {r['label']: r for r in engine.press_check(out, colour=True)}
    check('the press check passes its colour row', rows['Colour']['ok'], rows['Colour'])
    check('and names it a colour interior', 'colour interior' in rows['Colour']['detail'])

    out_bw, res_bw = build(MD, 'bw', press=True)
    with fitz.open(out_bw) as doc:
        px = pixel(doc[designed_page(out_bw)], 30, 30)
    check('black and white, as before: the design prints grey',
          res_bw['press'] and not res_bw['colour'] and grey(px), px)
    rows = {r['label']: r for r in engine.press_check(out_bw)}
    check('and its press check is the black-and-white one',
          rows['Colour']['ok'] and 'K-only black' in rows['Colour']['detail'])
    check('a colour interior read as black and white would fail (so the flag matters)',
          not {r['label']: r for r in engine.press_check(out)}['Colour']['ok'])

    # a chromatic colour in the style itself: black-and-white press refuses it
    # and falls back; a colour interior keeps it
    p = preset()
    p['sidebar'] = dict(p.get('sidebar') or {}, print_fill='#2050c0')
    sp = preset(scene_break=dict(preset()['scene_break'], type='rule'))
    md = '# One\n\n' + L + '\n\n~~~ sidebar title="Kites"\nThey fly.\n~~~\n\n' + L
    _, r1 = build(md, 'link-bw', p=p, press=True)
    out2, r2 = build(md, 'link-colour', p=p, press=True, colour_interior=True)
    check('a coloured sidebar: black and white falls back to an ordinary PDF',
          r1.get('press_error') and not r1['press'], r1.get('press_error'))
    check('a colour interior builds it press-ready', r2['press'] and not r2.get('press_error'),
          r2.get('press_error'))
    check('with the colour in it', re.search(r'\.125\d* \.313\d* \.752\d* rg', ops(out2)))
    out3, r3 = build('# One\n\n' + L + '\n\n* * *\n\n' + L, 'rule', p=sp, press=True,
                     colour_interior=True)
    check('a rule in a colour interior is K-only too',
          r3['press'] and not re.search(r'(?<![\d.])0 0 0 RG', ops(out3)))
    _, r4 = build(MD, 'not-press', colour_interior=True)
    check('an ordinary build ignores the flag', not r4['press'] and not r4['colour'])


# ---------------------------------------------------------------- 3
NEW_TRIMS = [(8.0, 8.0), (8.25, 6.0), (10.0, 8.0), (11.0, 8.5)]


def trims_tests():
    print('\n[picture-book trims]')
    sizes = {(w, h) for w, h, _ in A.TRIM_PRESETS}
    check('square and landscape trims are offered',
          set(NEW_TRIMS) | {(8.25, 8.25), (8.5, 8.5)} <= sizes, sorted(sizes))
    pb = A.load_preset('picture-book')
    for w, h in NEW_TRIMS:
        p = copy.deepcopy(pb)
        p['trim'] = {'w': w, 'h': h}
        tag = f'{w:g}x{h:g}'
        try:
            md = '# One\n\n' + L + '\n\n' + L + '\n\n~~~ page src="kite"\n~~~\n'
            out, res = build(md, 'trim-' + tag, p=p)
            with fitz.open(out) as doc:
                r = doc[0].rect
                ok_size = round(r.width) == round(w * 72) and round(r.height) == round(h * 72)
                inside = all(0 <= wd[0] and wd[2] <= r.width + .5 and 0 <= wd[1] and wd[3] <= r.height + .5
                             for pg in doc for wd in pg.get_text('words'))
                n = designed_page(out)
                filled = near(pixel(doc[n], 3, 3), (192, 48, 32))
            check(f'{tag}: builds at its size, words on the page, the design fills it',
                  ok_size and inside and filled, (r, inside, filled))
            out, res = build(md, 'trim-bleed-' + tag, p=p, bleed=True, press=True,
                             colour_interior=True)
            with fitz.open(out) as doc:
                ok = True
                for i, pg in enumerate(doc):
                    tb = pg.trimbox
                    if abs(tb.width - w * 72) > .5 or abs(tb.height - h * 72) > .5:
                        ok = False
                    if abs(pg.rect.height - (h + .25) * 72) > .5:
                        ok = False
                    for wd in pg.get_text('words'):
                        if wd[0] < tb.x0 - .5 or wd[2] > tb.x1 + .5:
                            ok = False
            check(f'{tag}: with bleed and in colour, the trim declared and the words inside it',
                  ok and res['press'] and res['colour'], res.get('press_error'))
            dims = A._wrap_dims({'wrap_retailer': 'kdp', 'wrap_binding': 'paperback',
                                 'wrap_paper': 'color', 'wrap_trim_w': w, 'wrap_trim_h': h}, 32)
            spine = 32 * A._PAPER['color']['ppi']
            g = engine.wrap_geometry(dims)
            check(f'{tag}: the cover wrap is two trims and the spine wide',
                  abs(dims['spine_w'] - spine) < 1e-4
                  and abs(g['wrap_w'] - (2 * w + spine + 2 * dims['bleed'])) < .01
                  and abs(g['wrap_h'] - (h + 2 * dims['bleed'])) < .01,
                  {k: g.get(k) for k in ('wrap_w', 'wrap_h')})
        except Exception:
            check(f'{tag}: builds', False, traceback.format_exc()[-900:])


# ---------------------------------------------------------------- 4
def app_tests():
    print('\n[the app]')
    check('premium colour keeps the old key and caliper',
          A._PAPER['color']['ppi'] == 0.002347 and A._colour_paper('color'))
    check('standard colour is the thinner stock',
          A._PAPER['color_standard']['ppi'] < A._PAPER['color']['ppi']
          and A._colour_paper('color_standard'))
    check('white, cream and nonsense are black and white',
          not any(A._colour_paper(p) for p in ('white', 'cream', '', None, 'vellum')))
    meta, _ = A._project_meta({'title': 'T', 'print_paper': 'color_standard'})
    check('a book on colour paper is a colour interior', meta['colour_interior'] is True)
    meta, _ = A._project_meta({'title': 'T'})
    check('a book that never chose a paper is not', meta['colour_interior'] is False)

    # Send to print, end to end, on premium colour
    pid = 'kite-day'
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(MD)
    proj = {'name': 'Kite', 'preset': 'picture-book', 'title': 'The Kite Day',
            'author': 'Test Fixture', 'manuscript_file': pid + '.md', 'manuscript_type': 'file',
            'front_matter': 'none', 'bleed': True, 'cover_mode': 'designed',
            'cover_template': 'ashforge-house', 'print_retailer': 'kdp',
            'print_binding': 'paperback', 'print_paper': 'color',
            'page_designs': [design()]}
    A.save_project_file(pid, proj)
    try:
        info = A.build_print_package(A.load_project(pid))
        with zipfile.ZipFile(os.path.join(A.OUT_DIR, info['zip_name'])) as z:
            name = [n for n in z.namelist() if n.endswith('-interior.pdf')][0]
            data = z.read(name)
        with fitz.open(stream=data, filetype='pdf') as doc:
            n = [i for i, pg in enumerate(doc) if 'Up it goes' in pg.get_text()][0]
            px = pixel(doc[n], 30, 30)
        check('Send to print: a press-ready colour interior',
              info['press_ready'] and near(px, (192, 48, 32)), (info['press_ready'], px))
        rows = {r['label']: r for r in info['press']}
        check('its press check reads it as colour, nothing outstanding',
              all(r['ok'] or r.get('note') for r in rows.values()), rows)
        with zipfile.ZipFile(os.path.join(A.OUT_DIR, info['zip_name'])) as z:
            spec = z.read([n for n in z.namelist() if n.endswith('PRINT-SPEC.txt')][0]).decode()
        check('and the spec sheet names the paper and the colour interior',
              'Premium colour' in spec and 'press-ready colour' in spec, spec[:600])
    except Exception:
        check('Send to print builds', False, traceback.format_exc()[-900:])

    # the Picture Book style: builds, and the style editor saves it unchanged
    before = A.load_preset('picture-book')
    check('the Picture Book style: square, Andika, no folios or running heads',
          (before['trim']['w'], before['trim']['h']) == (8.5, 8.5)
          and before['font_files']['regular'] == 'Andika-Regular.ttf'
          and not before['folio']['show'] and not before['running_head']['show'])
    html = C.get('/editor/picture-book').get_data(as_text=True)
    form = form_of(html, '/save/')
    C.post('/save/picture-book', data=form)
    after = A.load_preset('picture-book')
    # the editor writes every section out in full; what the style set must
    # come back as it was
    diff = {}
    for k, v in before.items():
        a = after.get(k)
        if isinstance(v, dict) and isinstance(a, dict):
            bad = {s: (v[s], a.get(s)) for s in v if a.get(s) != v[s]}
            if bad:
                diff[k] = bad
        elif a != v:
            diff[k] = (v, a)
    check('the style editor saves what it sets unchanged', not diff, diff)


def form_of(html, action):
    """The fields a form posts, as a browser would (inputs, checked boxes,
    selected options, textareas)."""
    from html.parser import HTMLParser
    start = html.find(f'action="{action}')
    if start < 0:
        start = html.find(action)
    form_html = html[html.rfind('<form', 0, start):html.find('</form>', start)]

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.data, self.sel, self.ta = {}, None, None

        def handle_starttag(self, tag, at):
            a = dict(at)
            if tag == 'input' and a.get('name'):
                t = a.get('type', 'text')
                if t in ('checkbox', 'radio'):
                    if 'checked' in a:
                        self.data[a['name']] = a.get('value', 'on')
                elif t not in ('submit', 'button', 'file'):
                    self.data[a['name']] = a.get('value', '')
            elif tag == 'select':
                self.sel = a.get('name')
            elif tag == 'option' and self.sel:
                if 'selected' in a or self.sel not in self.data:
                    self.data[self.sel] = a.get('value', '')
            elif tag == 'textarea':
                self.ta = a.get('name')
                self.data[self.ta] = ''

        def handle_endtag(self, tag):
            if tag == 'select':
                self.sel = None
            elif tag == 'textarea':
                self.ta = None

        def handle_data(self, d):
            if self.ta:
                self.data[self.ta] += d

    p = P()
    p.feed(form_html)
    return p.data


if __name__ == '__main__':
    for t in (canvas_tests, press_tests, trims_tests, app_tests):
        try:
            t()
        except Exception:
            check(t.__name__ + ' ran', False, traceback.format_exc()[-900:])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{"ALL PASS" if not fails else str(len(fails)) + " FAILED"}')
    sys.exit(1 if fails else 0)
