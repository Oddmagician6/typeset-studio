"""Upgrade tests  (run: python test_upgrade.py).

A book outlives the version that made it. These check that what an older
version saved opens in this one as it would have been saved now - nothing
warned about falsely, nothing lost, and nothing printed differently.

The fixtures in test_fixtures/<version>/ are frozen from that release: made
by its own code (a worktree at its tag), not written by hand to look like it,
except where the old code was browser-only and is copied out literally.

Each release's projects/, presets/ and covers/ are what its own pages wrote
when driven as a writer would (each form submitted as the page offered it):

  draft         a blank new draft, never edited
  edited        a draft with its details, matter and format set on Edit
  image-cover   uploaded cover art (1.0.0 had no cover modes: just the file)
  designed      a designed cover template (from 1.1.0)
  set-a-book    "Set a book" with an uploaded manuscript, then saved as a project
  old-style     a style from the style editor's New, saved
  old-cover     a cover template from the cover editor's New, saved
  ashforge-house-style-dark-copy   a bundled template cloned and saved

Releases: 1.0.0 (741f6f1, the first installer), 1.1.0 (5fe5744), and the tags
1.2.0, 1.2.3, 1.2.6, 1.2.9, 1.3.0 (the last made by test_fixtures/make_fixtures.py,
which says how to freeze the next). Each is opened by the current app: every page, a
build, a print package, and every editor saved unchanged - which may write
keys the old file lacked, but must not change what the book, style or cover is.

  wrap-design-starter.json     1.2.9's example design; its barcode box a plain
                               white rect labelled "Barcode area" (1.2.5-1.2.9)
  wrap-design-customised.json  1.2.9's "Customise this design" of ashforge-house;
                               the template's reserve as a grey-outlined vector,
                               its caption a separate text (1.2.7-1.2.9)

The browser half needs Chrome or Edge (TS_BROWSER to point at one); without one
it is skipped and says so.
"""

import sys, os, json, glob, shutil, tempfile, threading, subprocess
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import wrap_design as WDm
from test_rich_editor import find_browser
from werkzeug.serving import make_server
from flask import request

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def fixture(version, name):
    with open(os.path.join(HERE, 'test_fixtures', version, name), encoding='utf-8') as f:
        return json.load(f)


tmp = tempfile.mkdtemp(prefix='ts-upgrade-')
A.OUT_DIR = os.path.join(tmp, 'out')
A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
for d in (A.OUT_DIR, A.WRAP_DESIGN_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d)
WDm.stand_in_art(os.path.join(A.WRAP_DESIGN_DIR, A.WRAP_STAND_IN))

STARTER = fixture('v1.2.9', 'wrap-design-starter.json')
CUSTOMISED = fixture('v1.2.9', 'wrap-design-customised.json')


def book(pid, design):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write('# The Salt Road\n\nThe opening paragraph.\n')
    A.save_project_file(pid, {'name': 'The Salt Road', 'preset': 'classic-literary',
                              'title': 'The Salt Road', 'author': 'Ellinor Vale',
                              'manuscript_file': pid + '.md', 'manuscript_type': 'file',
                              'front_matter': 'none', 'cover_mode': 'wrap', 'format': 'pdf',
                              'print_retailer': 'kdp', 'print_binding': 'paperback',
                              'print_paper': 'cream', 'print_blurb': 'A road of salt.',
                              'wrap_design': design})


book('old-starter', STARTER)
book('old-customised', CUSTOMISED)


# The browser half's harness. Flask takes no new routes after its first request,
# so they are added here, ahead of the server-side checks.
SCRIPT = r'''
var f = document.getElementById('f');
f.onload = function () {
  var w = f.contentWindow, d = f.contentDocument, out = {};
  var wait = setInterval(function () {
    if (!w.WD_READY) return;
    clearInterval(wait);
    var E = w.WD_EDITOR, svg = d.getElementById('wd-svg');
    var els = E.design().elements;
    var codes = els.filter(function (e) { return e.type === 'barcode'; });
    out.barcodes = codes.length;
    out.old_boxes = els.filter(function (e) {
      return e.type === 'rect' && e.label === 'Barcode area' || e.text === 'ISBN / barcode area';
    }).length;
    out.checks = d.getElementById('wd-checks').textContent;
    out.status = d.getElementById('wd-save-status').textContent;
    var bc = codes[0];
    if (!bc) { send(); return; }
    Array.prototype.find.call(d.querySelectorAll('#wd-layers li'), function (li) {
      return li.textContent.indexOf('Barcode area') !== -1;
    }).click();
    var isbn = d.querySelector('#wd-props input[type=text]');
    isbn.value = '978-0-306-40615-7'; isbn.dispatchEvent(new w.Event('input'));
    setTimeout(function () {
      out.bars = svg.querySelectorAll('[data-id="' + bc.id + '"] rect').length - 1;
      out.checks_isbn = d.getElementById('wd-checks').textContent;
      send();
    }, 1500);
  }, 100);
  function send() {
    var x = new XMLHttpRequest(); x.open('POST', '/_up_result?case=' + CASE, false);
    x.send(JSON.stringify(out));
  }
};'''
# a working copy kept only in the browser by 1.2.9, with no book picked
SEED = r'''
localStorage.setItem('ts-wrap-design-v1', JSON.stringify({design: DESIGN, settings: {
  'wd-project': '', 'wd-name': 'The Salt Road', 'wd-retailer': 'kdp', 'wd-paper': 'cream',
  'wd-binding': 'paperback', 'wd-trim': '6x9', 'wd-pages': '320'}}));
'''
results = {}


@A.app.route('/_up_harness/<case>')
def _up_harness(case):
    src, seed = '/wrap-designer?project=' + case, ''
    if case == 'local':
        src, seed = '/wrap-designer', SEED.replace('DESIGN', json.dumps(STARTER))
    return ('<!doctype html><meta charset="utf-8"><script>var CASE = ' + json.dumps(case) + ';'
            + seed + '</script><iframe id="f" src="' + src + '" style="width:1300px;height:900px">'
            '</iframe><script>' + SCRIPT + '</script>')


@A.app.route('/_up_result', methods=['POST'])
def _up_result():
    results[request.args['case']] = json.loads(request.get_data(as_text=True))
    return 'ok'


class FormFields(HTMLParser):
    """What a browser would submit from the form posting to `action`, untouched:
    each field's value as the page set it, ticked boxes only, the selected option
    (or the first, as a browser picks), no files."""
    def __init__(self, action):
        super().__init__(convert_charrefs=True)
        self.action, self.inside, self.fields = action, False, []
        self.select, self.options, self.textarea = None, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.inside = self.action in (a.get('action') or '')
        if not self.inside or 'disabled' in a:
            return
        if tag == 'input' and a.get('name'):
            kind = (a.get('type') or 'text').lower()
            if kind in ('checkbox', 'radio'):
                if 'checked' in a:
                    self.fields.append((a['name'], a.get('value', 'on')))
            elif kind not in ('file', 'submit', 'button', 'image', 'reset'):
                self.fields.append((a['name'], a.get('value', '')))
        elif tag == 'select' and a.get('name'):
            self.select, self.options = a['name'], []
        elif tag == 'option' and self.select:
            self.options.append([a.get('value'), 'selected' in a, ''])
        elif tag == 'textarea' and a.get('name'):
            self.textarea = [a['name'], '']

    def handle_data(self, data):
        if self.textarea is not None:
            self.textarea[1] += data
        elif self.select and self.options and self.options[-1][0] is None:
            self.options[-1][2] += data

    def handle_endtag(self, tag):
        if tag == 'form':
            self.inside = False
        elif tag == 'textarea' and self.textarea is not None:
            name, text = self.textarea
            self.fields.append((name, text[1:] if text.startswith('\n') else text))
            self.textarea = None
        elif tag == 'select' and self.select:
            opts = [(v if v is not None else t.strip(), s) for v, s, t in self.options]
            pick = next((v for v, s in opts if s), opts[0][0] if opts else None)
            if pick is not None:
                self.fields.append((self.select, pick))
            self.select = None


def form_of(html, action):
    from werkzeug.datastructures import MultiDict
    p = FormFields(action)
    p.feed(html)
    return MultiDict(p.fields)


RELEASES = ['v1.0.0', 'v1.1.0', 'v1.2.0', 'v1.2.3', 'v1.2.6', 'v1.2.9', 'v1.3.0', 'v1.3.1']


def open_release(version):
    """A data folder holding what `version` wrote, beside today's bundled styles
    and covers (as an installed app's would be), wired into the app."""
    root = os.path.join(tmp, version)
    src = os.path.join(HERE, 'test_fixtures', version)
    shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(root, 'presets'))
    shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(root, 'covers'),
                    ignore=shutil.ignore_patterns('assets'))
    shutil.copytree(os.path.join(src, 'projects'), os.path.join(root, 'projects'))
    for sub in ('presets', 'covers'):
        for f in glob.glob(os.path.join(src, sub, '*.json')):
            shutil.copy(f, os.path.join(root, sub))
    A.PROJECT_DIR = os.path.join(root, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.PRESET_DIR, A.COVER_DIR = os.path.join(root, 'presets'), os.path.join(root, 'covers')
    A.OUT_DIR = os.path.join(root, 'out')
    A.UPLOAD_DIR = os.path.join(root, 'uploads')
    A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    A.WRAP_DESIGN_DIR = os.path.join(A.OUT_DIR, '_wrap_designer')
    WDm.ART_DIRS = [A.COVER_ASSET_DIR, A.WRAP_DESIGN_DIR]
    for d in (A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR, A.PROJECT_THUMB_DIR, A.WRAP_DESIGN_DIR):
        os.makedirs(d, exist_ok=True)
    return src


def meaning(proj):
    """What a book is, as a build and the print package read it."""
    meta, cover = A._project_meta(proj)
    meta = {k: v for k, v in meta.items() if k not in ('year', 'cover_template_data')}
    return dict(meta, cover=os.path.basename(cover), name=proj.get('name'),
                preset=proj.get('preset'), format=proj.get('format', 'pdf'),
                **{k: proj.get(k, v) for k, v in A.PRINT_DEFAULTS.items()})


def page_pixels(preset, ms, **meta_extra):
    """Every page of `ms` set in `preset`, as pixels (coarse: layout, not grain)."""
    import engine, manuscript, fitz
    meta, _ = A._project_meta({'title': 'The Salt Road', 'author': 'Ellinor Vale', 'year': '2026',
                               'publisher': 'Ashforge', 'include_toc': True})
    meta.update(meta_extra)
    fd, out = tempfile.mkstemp(suffix='.pdf', dir=tmp)
    os.close(fd)
    engine.build_pdf(manuscript.parse_markdown(ms), preset, out, meta)
    with fitz.open(out) as doc:
        return [pg.get_pixmap(dpi=40).samples for pg in doc]


def flashes(client):
    with client.session_transaction() as s:
        return [m for _, m in (s.pop('_flashes', None) or [])]


try:
    # ------------------------------------------------- wrap designs before 1.3.0
    print('\nwrap designs saved before 1.3.0')
    import fitz
    dims = {'trim_w': 6.0, 'trim_h': 9.0, 'spine_w': 0.72, 'bleed': 0.125}

    def pixels(design, name):
        path = os.path.join(tmp, name + '.pdf')
        WDm.build_pdf(design, dims, path)
        with fitz.open(path) as doc:
            return doc[0].get_pixmap(dpi=150).samples

    for name, old in (('the 1.2.9 example design', STARTER),
                      ("a 1.2.9 template's Customise", CUSTOMISED)):
        new = WDm.upgrade(old)
        codes = [e for e in new['elements'] if e.get('type') == 'barcode']
        check(f'{name}: its barcode box becomes a barcode element', len(codes) == 1, codes)
        check(f'{name}: and nothing else is left of the old box',
              not any(e.get('label') == 'Barcode area' and e.get('type') != 'barcode'
                      or e.get('text') == 'ISBN / barcode area' for e in new['elements']))
        check(f'{name}: locked, like a new design\'s', codes and codes[0].get('locked'))
        # to within a shade of anti-aliasing: the template's outline was drawn a
        # half-stroke inside its path, the barcode's on its box
        a, b = pixels(old, name + '-a'), pixels(new, name + '-b')
        check(f'{name}: it prints as it did', len(a) == len(b) and
              max(abs(x - y) for x, y in zip(a, b)) <= 2)
        check(f'{name}: upgrading twice changes nothing', WDm.upgrade(new) == new)
        check(f'{name}: the design it was given is left alone',
              not any(e.get('type') == 'barcode' for e in old['elements']))

    # a 1.3.0 user who pressed "+ Barcode" beside the old box: not a second one
    both = {'elements': STARTER['elements'] + [{'id': 'barcode-2', 'type': 'barcode', 'anchor': 'back',
                                                'x': 3.75, 'y': 7.55, 'w': 2, 'h': 1.2}]}
    check('a design that already has a barcode is left as it is', WDm.upgrade(both) == both)
    # a white box the writer recoloured is theirs: it stays a shape
    red = {'elements': [dict(STARTER['elements'][-1], color='#aa0000')]}
    check('an old box recoloured by the writer stays a shape', WDm.upgrade(red) == red)
    check('a design with no elements, or not a design, passes through',
          WDm.upgrade({'elements': []}) == {'elements': []} and WDm.upgrade(None) is None)

    # every way the app reads a book's design gets the upgraded one
    proj = A.load_project('old-starter')
    check('a book opened by the app has the barcode element',
          any(e.get('type') == 'barcode' for e in proj['wrap_design']['elements']))
    c = A.app.test_client()
    j = c.get('/wrap-designer/project/old-customised').get_json()
    check("the designer is sent the book's design upgraded",
          sum(e.get('type') == 'barcode' for e in j['design']['elements']) == 1)
    j = c.post('/wrap-designer/upgrade', json={'design': STARTER}).get_json()
    check('and upgrades a design the browser kept',
          j['ok'] and any(e.get('type') == 'barcode' for e in j['design']['elements']))
    r = c.post('/wrap-designer/project/old-starter/save',
               json={'design': STARTER, 'settings': {}}).get_json()
    with open(os.path.join(A.PROJECT_DIR, 'old-starter.json'), encoding='utf-8') as f:
        saved = json.load(f)['wrap_design']
    check('an old design sent back to Save is stored upgraded',
          r.get('ok') and any(e.get('type') == 'barcode' for e in saved['elements']), r)

    # ------------------------------------------------- in the designer
    print('\nin the designer (browser)')
    browser = find_browser()
    if not browser:
        print('  skip  no Chrome or Edge found (set TS_BROWSER to run these)')
    else:
        book('old-starter', STARTER)                 # as 1.2.9 left it, again
        server = make_server('127.0.0.1', 0, A.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for case in ('old-starter', 'old-customised', 'local'):
                subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                                '--user-data-dir=' + os.path.join(tmp, 'browser-' + case),
                                '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                                f'http://127.0.0.1:{server.server_port}/_up_harness/{case}'],
                               capture_output=True, timeout=300)
        finally:
            server.shutdown()
        for case, name in (('old-starter', 'a book with the 1.2.9 example design'),
                           ('old-customised', "a book with a 1.2.9 template's Customise"),
                           ('local', 'a 1.2.9 working copy kept only in the browser')):
            r = results.get(case)
            check(f'{name}: opens in the editor', bool(r))
            if not r:
                continue
            check(f'{name}: one barcode box, and no old one beside it',
                  r['barcodes'] == 1 and r['old_boxes'] == 0, r)
            check(f'{name}: no false "No barcode area"', 'No barcode area' not in r['checks'], r['checks'])
            check(f'{name}: the old box takes an ISBN', r.get('bars') == 30
                  and 'carries the ISBN' in r.get('checks_isbn', ''), (r.get('bars'), r.get('checks_isbn')))
            if case != 'local':
                check(f'{name}: and opening it is not an unsaved change',
                      'Unsaved' not in r['status'], r['status'])

    # ------------------------------------------------- books, styles, covers
    # Last, as each release's folder rewires the app's data folders.
    with open(A.SAMPLE, encoding='utf-8') as f:
        SAMPLE_MS = f.read()
    for version in RELEASES:
        print(f'\nwhat {version[1:]} wrote')
        src = open_release(version)
        c = A.app.test_client()
        pages = ['/', '/projects', '/covers', '/generate', '/wrap-designer']
        check(f'{version}: the main pages open',
              all(c.get(u).status_code == 200 for u in pages),
              [(u, c.get(u).status_code) for u in pages])
        flashes(c)
        for path in sorted(glob.glob(os.path.join(src, 'projects', '*.json'))):
            pid = os.path.basename(path)[:-5]
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
            book_name = f'{version} {pid}'
            urls = [f'/project/{pid}/{p}' for p in ('edit', 'write', 'history')] + \
                   [f'/wrap-designer?project={pid}', f'/wrap-designer/project/{pid}']
            bad = [(u, c.get(u).status_code) for u in urls if c.get(u).status_code != 200]
            check(f'{book_name}: every page of the book opens', not bad, bad)
            was = meaning(A.load_project(pid))
            if raw.get('cover_file'):
                check(f'{book_name}: its uploaded cover is still its cover', bool(was['cover']), was)
            r = c.get(f'/project/{pid}/edit')
            c.post(f'/project/{pid}/edit', data=form_of(r.get_data(as_text=True), f'/project/{pid}/edit'))
            now = meaning(A.load_project(pid))
            changed = {k: (was[k], now.get(k)) for k in was if was[k] != now.get(k)}
            check(f'{book_name}: saved unchanged on Edit, it is the same book', not changed, changed)
            flashes(c)
            r = c.post(f'/project/{pid}/generate')
            fl = flashes(c)
            check(f'{book_name}: it builds', r.status_code == 200 and not fl, (r.status_code, fl))
            r = c.post(f'/project/{pid}/print-package', data={'scope': 'print'})
            fl = flashes(c)
            if now['cover_mode'] != 'none':
                check(f'{book_name}: and goes to print', r.status_code in (200, 302)
                      and not any('failed' in m or 'needs' in m for m in fl), fl)
            else:                                    # no cover: refused, and told why
                check(f'{book_name}: with no cover, Send to print says it needs one',
                      any('needs a cover' in m for m in fl), fl)
        for path in sorted(glob.glob(os.path.join(src, 'presets', '*.json'))):
            sid = os.path.basename(path)[:-5]
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
            r = c.get(f'/editor/{sid}')
            c.post(f'/save/{sid}', data=form_of(r.get_data(as_text=True), '/save'))
            with open(os.path.join(A.PRESET_DIR, sid + '.json'), encoding='utf-8') as f:
                after = json.load(f)
            check(f'{version} style {sid}: saved unchanged in its editor, it sets the book the same',
                  r.status_code == 200 and page_pixels(raw, SAMPLE_MS) == page_pixels(after, SAMPLE_MS))
            flashes(c)
        for path in sorted(glob.glob(os.path.join(src, 'covers', '*.json'))):
            cid = os.path.basename(path)[:-5]
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
            ok = c.get(f'/cover/thumb/{cid}.png').status_code == 200
            r = c.get(f'/cover/{cid}')
            c.post(f'/cover/save/{cid}', data=form_of(r.get_data(as_text=True), '/cover/save'))
            with open(os.path.join(A.COVER_DIR, cid + '.json'), encoding='utf-8') as f:
                after = json.load(f)
            cover = lambda t: page_pixels(A.DEFAULTS, '# One\n\nText.', cover_mode='designed',
                                          cover_template=cid, cover_template_data=t)[:1]
            check(f'{version} cover {cid}: saved unchanged in its editor, it draws the same',
                  ok and r.status_code == 200 and cover(raw) == cover(after))
            flashes(c)

    # the fewest keys a book has ever had (one written before the Edit page set
    # them all): right-hand chapter starts default on, and the page must say so
    print('\na book with only its name, style and manuscript')
    with open(os.path.join(A.PROJECT_MS_DIR, 'bare.md'), 'w', encoding='utf-8') as f:
        f.write('# One\n\nText.\n')
    A.save_project_file('bare', {'name': 'Bare', 'preset': 'classic-literary', 'title': 'Bare',
                                 'manuscript_file': 'bare.md', 'manuscript_type': 'file'})
    c = A.app.test_client()
    was = meaning(A.load_project('bare'))
    c.post('/project/bare/edit', data=form_of(c.get('/project/bare/edit').get_data(as_text=True),
                                              '/project/bare/edit'))
    now = meaning(A.load_project('bare'))
    changed = {k: (was[k], now.get(k)) for k in was if was[k] != now.get(k)}
    check('saved unchanged on Edit, it is the same book', not changed, changed)

    # cover templates the pre-1.3.0 editor saved without their family's settings
    # (test_fixtures/v1.2.9/damaged-covers: bundled ones cloned and saved by 1.2.9)
    print('\ncover templates damaged by the old cover editor')
    A.COVER_DIR = os.path.join(tmp, 'damaged-covers')
    A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_damaged_thumbs')
    shutil.copytree(os.path.join(HERE, 'test_fixtures', 'v1.2.9', 'damaged-covers'), A.COVER_DIR)
    os.makedirs(A.COVER_THUMB_DIR, exist_ok=True)
    draw = lambda t: page_pixels(A.DEFAULTS, '# One\n\nText.', cover_mode='designed',
                                 cover_template='x', cover_template_data=t)[:1]
    # a copy the writer renamed can't be traced, and one they changed keeps the change
    with open(os.path.join(A.COVER_DIR, 'geometric-block-copy.json'), encoding='utf-8') as f:
        geo = json.load(f)
    A.save_cover_template('renamed', dict(geo, name='My own cover'))
    A.save_cover_template('changed', dict(geo, title=dict(geo['title'], size=99.0)))
    listed = {it['id']: it['data'] for it in A.list_cover_templates()}
    for fn in sorted(os.listdir(os.path.join(HERE, 'test_fixtures', 'v1.2.9', 'damaged-covers'))):
        cid, bundled = fn[:-5], fn[:-len('-copy.json')]
        with open(os.path.join(HERE, 'covers', bundled + '.json'), encoding='utf-8') as f:
            src = json.load(f)
        block = A.FAMILY_BLOCKS[src['design']]
        with open(os.path.join(A.COVER_DIR, fn), encoding='utf-8') as f:
            saved = json.load(f)
        check(f'{bundled} (copy): its {block} settings are back, and saved',
              listed[cid].get(block) == src[block] and saved.get(block) == src[block])
        if bundled != 'vintage-pulp':
            check(f'{bundled} (copy): it draws as the template it was copied from',
                  draw(saved) == draw(src))
    check("vintage-pulp (copy): all but the accent colour the old editor's dropdown changed",
          listed['vintage-pulp-copy']['accent']['color'] == 'gold'
          and listed['vintage-pulp-copy']['kicker'].get('leading') == src['kicker'].get('leading'))
    check('a copy renamed by the writer is left as it is', 'blocks' not in listed['renamed'])
    check('a setting the writer changed is kept', listed['changed']['title']['size'] == 99.0
          and 'blocks' in listed['changed'])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
