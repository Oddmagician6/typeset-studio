"""Picture books, part 2: the page plan (ROADMAP #75b-2)
(run: python test_page_plan.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.
Everything runs against throwaway folders, set up here.

Held here:

  1. the model (page_plan.py): a manuscript split into its page fences and
     the text between, joined back word for word; the parser agrees on the
     pages; a rename touches only the fences that place the page;
  2. the layout: page 1 on the right, a spread on a left page, a side asked
     for, a blank where one is needed - and the engine sets the same number
     of pages, with no blank page before the first design;
  3. the checks: a picture book's page count, and pictures across the fold
     of a paperback spread (a flat colour is fine; a hardcover is a note);
  4. the app: the plan's data, reordering, taking a page out (its design is
     kept) and putting it back, adding a page and a spread, a stale plan and
     one that would lose text refused, thumbnails, a design renamed in the
     designer renamed in the manuscript, and a new picture book with its
     settings and starter pages, built end to end with its checks.
"""
import copy, json, os, shutil, sys, tempfile, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, manuscript, page_plan as P, wrap_design as W

fails = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


# throwaway folders: the app writes nothing into the real ones
tmp = tempfile.mkdtemp(prefix='ts-plan-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
A.PRESET_DIR = os.path.join(ROOT, 'presets')
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


def one(name, color='#c03020'):
    return {'name': name, 'saved': '2026-11-13T10:00:00', 'elements': [
        {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': color}]}


def spread(name, art=False):
    els = [{'id': 'bg', 'type': 'rect', 'fill': 'sheet', 'color': '#2040c0'}]
    if art:
        els.append({'id': 'pic', 'type': 'image', 'fill': 'sheet', 'src': 'none.png'})
    return {'name': name, 'spread': True, 'saved': '2026-11-13T10:00:00', 'elements': els}


def fence(src, side=''):
    return f'~~~ page src="{src}"' + (f' side="{side}"' if side else '') + '\n~~~'


# ---------------------------------------------------------------- 1
def test_model():
    print('the model')
    text = ('# Once\n\nThe kite went up.\n\n\n' + fence('a') + '\n\n~~~ quote\nA ~~~ fence of\n'
            'another kind.\n~~~\n\n' + fence('b', 'right') + '\n' + fence('sp') + '\n\nThe end.\n')
    items = P.split(text)
    kinds = [it['kind'] for it in items]
    check('pages and the text between them', kinds == ['text', 'page', 'text', 'page', 'page', 'text'],
          kinds)
    check('a page knows its name and side', (items[3]['src'], items[3]['side']) == ('b', 'right'))
    check('another block stays in the text', '~~~ quote' in items[2]['text']
          and 'another kind.' in items[2]['text'])
    check('the parser agrees on the pages', P.readable(text, items))
    again = P.split(P.join(items))
    check('joined and split again: the same pieces', [i['text'] for i in again] == [i['text'] for i in items])
    moved = P.join([items[0], items[4], items[2], items[1], items[3], items[5]])
    check('reordered: the text pieces are word for word', all(
        it['text'] in moved for it in items if it['kind'] == 'text'))
    check('reordered: the book reads the new order',
          engine.page_blocks(manuscript.parse_markdown(moved)) == ['sp', 'a', 'b'])
    # a page fence the parser doesn't see as one (swallowed by a note's text)
    odd = '[^1]: A note\n' + fence('a') + '\n'
    check('a manuscript the plan reads differently is not readable', not P.readable(odd))
    r = P.rename('x\n' + fence('Old-Name', 'left') + '\n\n~~~ figure src="old-name"\n~~~\n',
                 'old-name', 'new-name', key=W.page_name)
    check('rename: only the page fence changes', 'src="new-name" side="left"' in r
          and '~~~ figure src="old-name"' in r, r)
    check('rename: nothing to rename, nothing changed', P.rename('abc', 'x', 'y') == 'abc')
    check('no text is no manuscript', P.join([]) == '')


# ---------------------------------------------------------------- 2
def test_layout():
    print('\nthe layout')
    designs = [one('a'), one('b'), one('c'), spread('sp')]

    def lay(md):
        return P.layout(P.split(md), designs, W.find_page, W.is_spread)

    slots, n = lay(fence('a') + '\n' + fence('sp'))
    check('page 1 on the right, a spread on 2-3', n == 3 and slots[0]['pages'] == [1]
          and slots[1]['pages'] == [2, 3], (slots, n))
    slots, n = lay(fence('a') + '\n' + fence('b') + '\n' + fence('sp'))
    check('a spread after page 2: a blank page 3 first', n == 5
          and any(s.get('blank') == 3 for s in slots), (slots, n))
    slots, n = lay(fence('a') + '\n' + fence('b', 'right'))
    check('side="right" after page 1: a blank page 2', n == 3
          and any(s.get('blank') == 2 for s in slots))
    slots, n = lay(fence('a') + '\n\nSome words.\n\n' + fence('b'))
    check('text: no page numbers from there on', n is None and slots[2]['pages'] == [])
    slots, n = lay(fence('missing'))
    check('a missing design takes one page', n == 1)

    # the engine sets the same number of pages
    p = A.load_preset('picture-book')
    meta = {'title': 'T', 'author': 'A', 'front_matter': 'none', 'include_toc': False,
            'right_hand_starts': False, 'page_designs': designs}
    for md in (fence('a'), fence('a') + '\n' + fence('sp'),
               fence('a') + '\n' + fence('b') + '\n' + fence('sp') + '\n' + fence('c', 'left'),
               fence('a') + '\n' + fence('b', 'right') + '\n' + fence('c')):
        for bleed in (False, True):
            out = os.path.join(tmp, 'lay.pdf')
            res = engine.build_pdf(manuscript.parse_markdown(md), copy.deepcopy(p), out,
                                   dict(meta, bleed=bleed), press=True)
            want = lay(md)[1]
            check(f'the build agrees: {want} pages{" with bleed" if bleed else ""}',
                  res['page_count'] == want, (md, res['page_count']))
    import fitz
    out = os.path.join(tmp, 'first.pdf')
    engine.build_pdf(manuscript.parse_markdown(fence('a') + '\n' + fence('b')), copy.deepcopy(p),
                     out, dict(meta, bleed=True), press=False)
    with fitz.open(out) as doc:
        pg = doc[0]
        pm = pg.get_pixmap(dpi=20)
        px = pm.pixel(pm.width // 2, pm.height // 2)
    check('page 1 is the first design, not a blank', px[0] > 150 and px[2] < 100, px)
    # an ordinary untitled chapter keeps its opening space
    out = os.path.join(tmp, 'prose.pdf')
    res = engine.build_pdf(manuscript.parse_markdown('Just words, no heading.\n'),
                           copy.deepcopy(A.DEFAULTS), out, dict(meta, page_designs=[]))
    with fitz.open(out) as doc:
        y = [b for b in doc[0].get_text('blocks') if 'just words' in b[4].lower()][0][1]
    check('an untitled chapter of prose still opens lower down', y > 1.2 * 72, y)


# ---------------------------------------------------------------- 3
def test_checks():
    print('\nthe checks')
    check('20 pages: too few', 'at least 24' in P.count_problem(20))
    check('26 pages: not in fours', 'make 28' in P.count_problem(26), P.count_problem(26))
    check('32 pages: fine', P.count_problem(32) == '')
    check('56 pages: long', 'longer' in P.count_problem(56))
    check('a colour field across the fold is fine', not P.art_across_fold(spread('s'), 8.5, 8.5))
    check('a picture across the fold is flagged', P.art_across_fold(spread('s', art=True), 8.5, 8.5))
    left = spread('s')
    left['elements'].append({'id': 'pic', 'type': 'image', 'fill': 'back', 'src': 'x.png'})
    check('a picture on one page of a spread is fine', not P.art_across_fold(left, 8.5, 8.5))
    small = spread('s')
    small['elements'].append({'id': 'pic', 'type': 'image', 'anchor': 'back', 'x': 7.0, 'y': 1,
                              'w': 3, 'h': 3, 'src': 'x.png'})
    check('a placed picture over the fold is flagged', P.art_across_fold(small, 8.5, 8.5))
    check('a single page has no fold', not P.art_across_fold(one('a'), 8.5, 8.5))

    out = os.path.join(tmp, 'checks.pdf')
    base = engine.build_pdf(manuscript.parse_markdown(fence('a')), A.load_preset('picture-book'),
                            out, {'title': 'T', 'author': 'A', 'front_matter': 'none',
                                  'include_toc': False, 'page_designs': [one('a')]})
    check('the build says whether a book is a picture book', base['picture_book'] is False
          and base['fold_art'] == [])
    rows = A._preflight(dict(base, picture_book=True, fold_art=['sp'], binding='paperback'),
                        A.load_preset('picture-book'), 26)
    by = {r['label']: r for r in rows}
    check('preflight: the page count row', 'Picture book pages' in by
          and not by['Picture book pages']['ok'])
    check('preflight: a paperback warns about the fold', 'Art across the fold' in by
          and not by['Art across the fold']['ok'] and 'sp' in by['Art across the fold']['detail'])
    rows = A._preflight(dict(base, picture_book=True, fold_art=['sp'], binding='hardcover'),
                        A.load_preset('picture-book'), 32)
    by = {r['label']: r for r in rows}
    check('preflight: a hardcover is a note', by['Art across the fold']['ok']
          and by['Picture book pages']['ok'])
    rows = A._preflight(base, A.load_preset('picture-book'), 26)
    check('preflight: not a picture book, no rows', not any(
        r['label'] in ('Picture book pages', 'Art across the fold') for r in rows))


# ---------------------------------------------------------------- 4
def project(pid, md, designs, **kw):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8', newline='') as f:
        f.write(md)
    A.save_project_file(pid, {'name': pid, 'title': pid, 'preset': 'picture-book',
                              'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
                              'format': 'pdf', 'front_matter': 'none', 'include_toc': False,
                              'right_hand_starts': False, 'bleed': True,
                              'page_designs': designs, **kw})


def ms(pid):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), encoding='utf-8') as f:
        return f.read()


def test_app():
    print('\nin the app')
    prose = 'A paragraph that is the writer\'s own,\nkept  exactly   as typed.'
    project('pb', fence('a') + '\n\n' + prose + '\n\n' + fence('b') + '\n\n' + fence('sp') + '\n',
            [one('a'), one('b'), spread('sp'), one('spare')], picture_book=True)
    html = C.get('/project/pb/plan').get_data(as_text=True)
    check('the plan page opens', 'Page plan' in html and 'pp-data' in html)
    d = C.get('/project/pb/plan/data').get_json()
    check('its pieces', [(it['kind'], it.get('src')) for it in d['items']]
          == [('page', 'a'), ('text', None), ('page', 'b'), ('page', 'sp')], d['items'])
    check('the spread is known as one', d['items'][3]['spread'])
    check('the unplaced design is in the tray', [u['name'] for u in d['unplaced']] == ['spare'])
    check('numbers stop at the text', d['pages'] is None and d['slots'][0]['pages'] == [1])

    # reorder: the spread first, the text kept
    r = C.post('/project/pb/plan/save', json={'rev': d['rev'], 'order': [
        {'page': 3}, {'page': 0}, {'text': 1}, {'page': 2}]}).get_json()
    check('reordered', r['ok'] and [it.get('src') for it in r['items']] == ['sp', 'a', None, 'b'], r)
    text = ms('pb')
    check('the manuscript has the new order',
          engine.page_blocks(manuscript.parse_markdown(text)) == ['sp', 'a', 'b'])
    check('the text is word for word', prose in text)
    check('a History snapshot was kept', len(A.list_snapshots('pb')) >= 1)

    # a stale plan is refused, and comes back up to date
    r2 = C.post('/project/pb/plan/save', json={'rev': d['rev'], 'order': [{'page': 0}]})
    check('a stale plan is refused', r2.status_code == 409 and r2.get_json()['data']['rev'] == r['rev'])
    # a plan that drops text is refused
    r3 = C.post('/project/pb/plan/save', json={'rev': r['rev'], 'order': [
        {'page': 0}, {'page': 1}, {'page': 3}]}).get_json()
    check('a plan without the text is refused', not r3['ok'] and ms('pb') == text)
    r3 = C.post('/project/pb/plan/save', json={'rev': r['rev'], 'order': [
        {'page': 0}, {'page': 0}, {'text': 2}, {'page': 3}]}).get_json()
    check('a page twice is refused', not r3['ok'])
    r3 = C.post('/project/pb/plan/save', json={'rev': r['rev'], 'order': 'nonsense'}).get_json()
    check('nonsense is refused', not r3['ok'])

    # take a page out: its design stays, in the tray
    r4 = C.post('/project/pb/plan/save', json={'rev': r['rev'], 'order': [
        {'page': 0}, {'text': 2}, {'page': 3}]}).get_json()
    check('taken out of the plan', r4['ok'] and 'a' not in [it.get('src') for it in r4['items']])
    check('its design is kept, in the tray', 'a' in [u['name'] for u in r4['unplaced']]
          and W.find_page(A.load_project('pb')['page_designs'], 'a'))
    # and back in, at the front
    r5 = C.post('/project/pb/plan/save', json={'rev': r4['rev'], 'order': [
        {'src': 'a'}, {'page': 0}, {'text': 1}, {'page': 2}]}).get_json()
    check('put back from the tray', r5['ok'] and [it.get('src') for it in r5['items']][:2] == ['a', 'sp'])
    r6 = C.post('/project/pb/plan/save', json={'rev': r5['rev'], 'order': [
        {'src': 'nothing-here'}, {'page': 0}, {'page': 1}, {'text': 2}, {'page': 3}]}).get_json()
    check('a design the book hasn\'t got is refused', not r6['ok'])

    # add a page and a spread
    r7 = C.post('/project/pb/plan/add', json={'rev': r5['rev'], 'kind': 'page'}).get_json()
    check('a page is added at the end', r7['ok'] and r7['name'] == 'page-1'
          and r7['items'][-1]['src'] == 'page-1' and 'design=page-1' in r7['designer'], r7)
    r8 = C.post('/project/pb/plan/add', json={'rev': r7['rev'], 'kind': 'spread', 'at': 0}).get_json()
    check('a spread is added where asked', r8['ok'] and r8['items'][0]['src'] == 'spread-1'
          and r8['items'][0]['spread'])
    designs = A.load_project('pb')['page_designs']
    check('both designs are saved with the book', W.find_page(designs, 'page-1')
          and W.is_spread(W.find_page(designs, 'spread-1')))
    r9 = C.post('/project/pb/plan/add', json={'rev': 'stale', 'kind': 'page'})
    check('adding to a stale plan is refused, nothing made', r9.status_code == 409
          and not W.find_page(A.load_project('pb')['page_designs'], 'page-2'))

    # thumbnails
    t = C.get('/project/pb/plan/thumb/sp')
    check('a thumbnail', t.status_code == 200 and t.data[:3] == b'\xff\xd8\xff')
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(t.data))
    check('a spread\'s is two pages wide', abs(im.width / im.height - 2.0) < 0.05, im.size)
    check('an unknown page has none', C.get('/project/pb/plan/thumb/nope').status_code == 404)

    # a rename in the designer renames the page in the manuscript
    before = ms('pb')
    r10 = C.post('/page-designer/pb/save', json={'name': 'kite-day', 'was': 'b',
                                                  'design': {'elements': one('x')['elements']}}).get_json()
    after = ms('pb')
    check('renamed in the designer', r10['ok'])
    check('the manuscript places it by its new name', 'src="kite-day"' in after
          and 'src="b"' not in after and prose in after, after)
    check('nothing else in it changed', after.replace('src="kite-day"', 'src="b"') == before)

    # the Edit page's checkbox
    proj = A.load_project('pb')
    form = {'name': 'pb', 'preset': 'picture-book', 'title': 'pb'}
    C.post('/project/pb/edit', data=form)
    check('the Edit page can turn picture book off', A.load_project('pb').get('picture_book') is False)
    C.post('/project/pb/edit', data=dict(form, picture_book='on'))
    check('and on again', A.load_project('pb').get('picture_book') is True)
    html = C.get('/project/pb/edit').get_data(as_text=True)
    check('the Edit page links to the plan', '/project/pb/plan' in html)
    html = C.get('/project/pb/write').get_data(as_text=True)
    check('so does the manuscript editor', '/project/pb/plan' in html)
    html = C.get('/wrap-designer?page=pb&design=a').get_data(as_text=True)
    check('and the page designer', '/project/pb/plan' in html)


def test_new_picture_book():
    print('\na new picture book')
    html = C.get('/projects').get_data(as_text=True)
    check('the Projects page offers one', '/project/new-picture-book' in html)
    r = C.post('/project/new-picture-book', data={'name': 'The Kite Day'})
    check('it opens on the plan', r.status_code == 302 and r.headers['Location'].endswith('/plan'),
          r.headers.get('Location'))
    pid = r.headers['Location'].split('/project/')[1].split('/')[0]
    proj = A.load_project(pid)
    check('its settings', proj['preset'] == 'picture-book' and proj['bleed'] is True
          and proj['front_matter'] == 'none' and proj['include_toc'] is False
          and proj['picture_book'] is True and A._colour_paper(proj['print_paper'])
          and proj['right_hand_starts'] is False, {k: proj.get(k) for k in (
              'preset', 'bleed', 'front_matter', 'include_toc', 'picture_book', 'print_paper')})
    names = [d['name'] for d in proj['page_designs']]
    check('three starter pages', names == ['title-page', 'copyright', 'dedication'], names)
    words = W.page_words(W.find_page(proj['page_designs'], 'title-page'))
    check('the title page has the title', 'The Kite Day' in words, words)
    cr = W.page_words(W.find_page(proj['page_designs'], 'copyright'))
    check('the copyright page has the year and rights', 'All rights reserved' in cr
          and str(A.datetime.now().year) in cr, cr)
    for d in proj['page_designs']:
        check(f'{d["name"]}: the fonts are in the library',
              all(W.font_file(e['font']) for e in d['elements'] if e['type'] == 'text'))
        check(f'{d["name"]}: survives the designer\'s save',
              A._clean_design({'elements': d['elements']}) is not None)
    d = C.get(f'/project/{pid}/plan/data').get_json()
    check('the plan: 3 pages, and needs more', d['pages'] == 3 and 'at least 24' in d['problem'], d)

    # fill it to 24 and build it end to end
    rev = d['rev']
    for k in range(10):
        res = C.post(f'/project/{pid}/plan/add', json={'rev': rev, 'kind': 'spread'}).get_json()
        rev = res['rev']
    res = C.post(f'/project/{pid}/plan/add', json={'rev': rev, 'kind': 'page'}).get_json()
    check('the plan counts 24 (a blank page before the first spread)', res['pages'] == 24
          and not res['problem'], (res['pages'], res['problem']))
    proj = A.load_project(pid)
    sp = W.find_page(proj['page_designs'], 'spread-1')
    sp['elements'].append({'id': 'pic', 'type': 'image', 'fill': 'sheet', 'src': 'none.png'})
    A.save_project_file(pid, proj)
    page = C.post(f'/project/{pid}/generate').get_data(as_text=True)
    check('it builds', 'Picture book pages' in page, page[:300])
    check('24 pages, a picture book\'s length', 'a picture book' in page and '24 pages' in page)
    check('the spread with art across the fold is named', 'Art across the fold' in page
          and 'spread-1' in page)
    built = A.load_project(pid)
    check('the build counted 24 pages', built.get('last_page_count') == 24,
          built.get('last_page_count'))


# ---------------------------------------------------------------- 5
from werkzeug.serving import make_server
from flask import request
_result = {}
BROWSER_JS = r'''
var f = document.getElementById('f');
function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
async function until(fn) { for (var i = 0; i < 200; i++) { if (fn()) return true; await wait(50); } return false; }
function labels(d) { return [].map.call(d.querySelectorAll('#pp-board .lbl'), function (e) { return e.textContent; }); }
function cell(d, name) {
  return [].find.call(d.querySelectorAll('#pp-board .pp-cell.page'), function (c) {
    var l = c.querySelector('.lbl'); return l && l.textContent.split(' ')[0] === name; });
}
f.onload = async function () {
  if (window.__ran) { R.added = f.contentWindow.location.href; send(); return; }
  window.__ran = true;
  var w = f.contentWindow, d = w.document;
  var msg = d.getElementById('pp-msg');
  async function saved() { await until(function () { return msg.textContent.indexOf('Saved') === 0 || msg.className.indexOf('err') !== -1; }); }
  await wait(300);
  R.start = labels(d);
  R.openings = d.querySelectorAll('#pp-board .pp-opening').length;
  R.blank = d.querySelectorAll('#pp-board .pp-cell.blank').length;
  R.count = d.getElementById('pp-count').textContent;
  // drag c before a
  cell(d, 'c').dispatchEvent(new w.Event('dragstart', {bubbles: true}));
  var a = cell(d, 'a');
  a.dispatchEvent(new w.Event('dragover', {bubbles: true, cancelable: true}));
  a.dispatchEvent(new w.Event('drop', {bubbles: true, cancelable: true}));
  await saved(); R.moved = labels(d); msg.textContent = '';
  // take b out
  cell(d, 'b').querySelector('.x').click();
  await saved(); R.removed = labels(d); msg.textContent = '';
  R.tray = [].map.call(d.querySelectorAll('#pp-unplaced .lbl'), function (e) { return e.textContent; });
  // and put it back at the end
  d.querySelector('#pp-unplaced .acts a').click();
  await saved(); R.back = labels(d); R.trayHidden = d.getElementById('pp-tray').hidden;
  // add a page: off to the designer
  d.getElementById('pp-add-page').click();
};
var R = {};
function send() { fetch('/_pp_result', {method: 'POST', body: JSON.stringify(R)}); }
setTimeout(send, 20000);
'''


@A.app.route('/_pp_harness')
def _pp_harness():
    return ('<!doctype html><meta charset="utf-8"><iframe id="f" src="/project/ui/plan" '
            'style="width:1300px;height:900px"></iframe><script>' + BROWSER_JS + '</script>')


@A.app.route('/_pp_result', methods=['POST'])
def _pp_result():
    _result.update(json.loads(request.get_data(as_text=True)))
    return 'ok'


def test_browser():
    print('\nthe plan, in a browser')
    import subprocess, threading
    from test_rich_editor import find_browser
    browser = find_browser()
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
        return
    project('ui', '\n\n'.join([fence('a'), fence('b'), fence('sp'), fence('c')]) + '\n',
            [one('a'), one('b', '#2040c0'), spread('sp'), one('c', '#20a040')], picture_book=True)
    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                        '--user-data-dir=' + os.path.join(tmp, 'browser'),
                        '--window-size=1400,1000', '--virtual-time-budget=60000', '--dump-dom',
                        f'http://127.0.0.1:{server.server_port}/_pp_harness'],
                       capture_output=True, timeout=300)
    finally:
        server.shutdown()
    r = _result
    check('the plan loaded and ran', bool(r.get('start')), r)
    if not r.get('start'):
        return
    check('every page labelled, a spread once', r['start'] == ['a', 'b', 'sp', 'c'], r['start'])
    check('openings: 1 | 2, blank 3 | the spread on 4-5 | 6', r['blank'] == 1
          and r['openings'] == 4, (r['openings'], r['blank']))
    check('the count, with what is missing', '6 pages' in r['count'] and 'at least 24' in r['count'],
          r['count'])
    check('dragged: c before a', r['moved'] == ['c', 'a', 'b', 'sp'], r['moved'])
    check('taken out: b', r['removed'] == ['c', 'a', 'sp'] and r['tray'] == ['b'], (r['removed'], r['tray']))
    check('put back at the end', r['back'] == ['c', 'a', 'sp', 'b'] and r['trayHidden'], r['back'])
    check('+ Page opens the new page in the designer', 'design=page-1' in r.get('added', ''),
          r.get('added'))
    check('the manuscript followed', engine.page_blocks(manuscript.parse_markdown(ms('ui')))
          == ['c', 'a', 'sp', 'b', 'page-1'], ms('ui'))


def main():
    for t in (test_model, test_layout, test_checks, test_app, test_new_picture_book, test_browser):
        try:
            t()
        except Exception:
            traceback.print_exc()
            fails.append(t.__name__ + ' crashed')
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print(f'{len(fails)} FAILED:')
        for f in fails:
            print('  -', f)
        sys.exit(1)
    print('all page plan checks passed')


if __name__ == '__main__':
    main()
