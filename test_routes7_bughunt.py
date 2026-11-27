"""Routes since 1.14.0  (run: python test_routes7_bughunt.py).

Joint bug hunt, round 7, section 32:

    32.1  a Page Plan write holds the manuscript lock: an autosave waits for it
    32.2  saving a wrap keeps a title saved while its front rendered
    32.3  two cover replacements at once leave the book with a cover
    32.4  a page rename whose manuscript write fails keeps the old name
    32.5  a design saved but not rendered isn't drawn from the old front
    32.6  a History restore follows a renamed page, even once its old name is reused
    32.7  Automatic EPUB layout stays reflowable with an unplaced draft design
    32.8  an oversized cover upload is refused
    32.9  opening the Page Plan of a Word book writes no figures
    32.12 designer saves with a JSON list are refused, not a 500
"""

import io, json, os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import manuscript
import page_plan
import wrap_design as W

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh32-')
A.PROJECT_DIR = os.path.join(TMP, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(TMP, 'out')
A.PRESET_DIR = os.path.join(TMP, 'presets')
A.COVER_DIR = os.path.join(TMP, 'covers')
FIG = os.path.join(TMP, 'figures')
A.FIGURE_DIR = manuscript.FIGURE_DIR = FIG
shutil.copytree(os.path.join(HERE, 'presets'), A.PRESET_DIR)
shutil.copytree(os.path.join(HERE, 'covers'), A.COVER_DIR, ignore=shutil.ignore_patterns('assets'))
for d in (A.PROJECT_MS_DIR, A.OUT_DIR, A.HISTORY_DIR, FIG):
    os.makedirs(d)
A.app.config['TESTING'] = True
c = A.app.test_client()

PARA = 'The tide came in over the stones while the bell kept its silence.'


def book(pid, md, designs=(), **extra):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    data = {'name': pid, 'title': pid, 'preset': 'classic-literary', 'manuscript_file': pid + '.md',
            'manuscript_type': 'markdown', 'format': 'pdf', 'front_matter': 'none',
            'page_designs': list(designs)}
    data.update(extra)
    A.save_project_file(pid, data)


def design(name, words='', **kw):
    els = [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#ffffff'}]
    if words:
        els.append({'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 3,
                    'text': words, 'font': 'EBGaramond-Regular.ttf', 'size': 18,
                    'color': '#000000'})
    return dict({'name': name, 'saved': '2026-11-20T10:00:00', 'elements': els}, **kw)


def ms_text(pid):
    return A._project_manuscript_text(A.load_project(pid), report_import=False)


def picture(fmt):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (40, 60), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


# ---- 32.1 -------------------------------------------------------------------
print('32.1 a Page Plan move holds the manuscript lock')
md = f'# One\n\n{PARA}\n\n{page_plan.fence("moon")}\n\n# Two\n\n{PARA}\n'
book('plan', md, [design('moon')])
data = c.get('/project/plan/plan/data').get_json()
rev = data['rev']
# the page moved to the front, the text left in its order
order = ([{'page': it['i']} for it in data['items'] if it['kind'] == 'page']
         + [{'text': it['i']} for it in data['items'] if it['kind'] == 'text'])
seen = {}
real_readable = page_plan.readable


def autosave():
    seen['status'] = A.app.test_client().post(
        '/project/plan/write/save', data={'text': md + '\nA new paragraph.\n',
                                          'base': rev}).status_code


def racing_readable(text, items=None):
    if 'thread' not in seen:          # the autosave lands after the revision check
        seen['thread'] = threading.Thread(target=autosave)
        seen['thread'].start()
        seen['thread'].join(1.0)
        seen['done_inside'] = 'status' in seen
    return real_readable(text, items)


page_plan.readable = racing_readable
try:
    r = c.post('/project/plan/plan/save', json={'rev': rev, 'order': order})
finally:
    page_plan.readable = real_readable
seen['thread'].join(10)
check('the plan moved the page', r.get_json().get('ok')
      and ms_text('plan').index('~~~ page') < ms_text('plan').index('# One'), r.get_json())
check('the autosave waited for the plan to write', not seen.get('done_inside'))
check('and was then refused as a conflict, not written over', seen.get('status') == 409,
      seen.get('status'))
snaps = A.list_snapshots('plan')
kept = any('A new paragraph.' in (A.read_snapshot('plan', s['stamp']) or '') for s in snaps)
check('its text is kept in History', kept)

print('32.1 + Page adds the design and its placement together')
data = c.get('/project/plan/plan/data').get_json()
r = c.post('/project/plan/plan/add', json={'rev': data['rev'], 'kind': 'page'}).get_json()
proj = A.load_project('plan')
check('the new page is saved', r.get('ok') and W.find_page(A._page_designs(proj), r.get('name')),
      r)
check('and placed', f'src="{r.get("name")}"' in ms_text('plan'))

# ---- 32.2 -------------------------------------------------------------------
print('32.2 a wrap save keeps a title saved while it rendered')
book('wrap', f'# One\n\n{PARA}\n', title='Old Title')
real_render = W.render_front


def slow_render(design_, dims, path):
    A.update_project('wrap', {'title': 'New Title', 'print_blurb': 'A new blurb.'})
    return real_render(design_, dims, path)


W.render_front = slow_render
try:
    r = c.post('/wrap-designer/project/wrap/save',
               json={'design': {'elements': design('x', 'Hello')['elements']},
                     'use_as_cover': True}).get_json()
finally:
    W.render_front = real_render
proj = A.load_project('wrap')
check('the wrap saved', r.get('ok'), r)
check('the title saved meanwhile stands', proj.get('title') == 'New Title', proj.get('title'))
check('and the blurb', proj.get('print_blurb') == 'A new blurb.')
check('the design is the cover', proj.get('cover_mode') == 'wrap' and proj.get('wrap_design'))

# ---- 32.5 -------------------------------------------------------------------
print('32.5 the cached front belongs to the design saved')
calls = []


def counting_render(design_, dims, path):
    calls.append(1)
    return real_render(design_, dims, path)


W.render_front = counting_render
try:
    A._wrap_front_path(A.load_project('wrap'))
    check('a front just saved is reused', not calls, len(calls))
    # the design committed, the app gone before the front was replaced
    A.update_project('wrap', {'wrap_design': W.upgrade(
        {'elements': design('x', 'Different lettering')['elements']})})
    A._wrap_front_path(A.load_project('wrap'))
    check('a changed design is drawn again', len(calls) == 1, len(calls))
finally:
    W.render_front = real_render

# ---- 32.3 -------------------------------------------------------------------
print('32.3 two cover replacements at once')
book('cov', f'# One\n\n{PARA}\n', cover_file='cov-cover.jpg', cover_mode='image')
with open(os.path.join(A.PROJECT_MS_DIR, 'cov-cover.jpg'), 'wb') as f:
    f.write(picture('JPEG'))
real_drop = A._drop_files
state = {}


def second_request():
    state['b'] = A.app.test_client().post(
        '/project/cov/edit', data={'title': 'cov', 'cover_mode': 'image',
                                   'cover': (io.BytesIO(picture('JPEG')), 'b.jpg')},
        content_type='multipart/form-data').status_code


def racing_drop(names):
    if names and 'thread' not in state:   # the first request, about to drop the old JPG
        state['thread'] = threading.Thread(target=second_request)
        state['thread'].start()
        state['thread'].join(1.0)
    return real_drop(names)


A._drop_files = racing_drop
try:
    c.post('/project/cov/edit', data={'title': 'cov', 'cover_mode': 'image',
                                      'cover': (io.BytesIO(picture('PNG')), 'a.png')},
           content_type='multipart/form-data')
finally:
    A._drop_files = real_drop
state['thread'].join(10)
proj = A.load_project('cov')
cover = os.path.join(A.PROJECT_MS_DIR, proj.get('cover_file') or '-')
check('both saves went through', state.get('b') == 302, state.get('b'))
check('the book\'s cover file is there', os.path.isfile(cover), proj.get('cover_file'))

# ---- 32.4 -------------------------------------------------------------------
print('32.4 a rename whose manuscript write fails')
book('ren', f'# One\n\n{PARA}\n\n{page_plan.fence("moon-map")}\n', [design('moon-map')])
real_write = A._atomic_write_text


def no_md(path, text):
    if path.endswith('.md'):
        raise PermissionError(13, 'in use', path)
    return real_write(path, text)


A._atomic_write_text = no_md
try:
    r = c.post('/page-designer/ren/save', json={'name': 'moon-chart', 'was': 'moon-map',
                                               'design': {'elements': design('x')['elements']}})
finally:
    A._atomic_write_text = real_write
names = [d['name'] for d in A._page_designs(A.load_project('ren'))]
check('the save failed', r.status_code >= 400 or not (r.get_json() or {}).get('ok'), r.status_code)
check('the design keeps the name its placements use', names == ['moon-map'], names)

# ---- 32.6 -------------------------------------------------------------------
print('32.6 a restore follows a renamed page once its name is reused')
old_md = f'# One\n\n{PARA}\n\n{page_plan.fence("moon-map")}\n'
book('hist', old_md, [design('moon-map', 'The moon map')])
folder = A._history_folder('hist')
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, '20260101-090000-edit.md'), 'w', encoding='utf-8') as f:
    f.write(old_md)
r1 = c.post('/page-designer/hist/save', json={'name': 'moon-chart', 'was': 'moon-map',
                                             'design': {'elements': design('x', 'The moon map')['elements']}})
r2 = c.post('/page-designer/hist/save', json={'name': 'moon-map', 'was': '',
                                             'design': {'elements': design('x', 'A new map')['elements']}})
check('renamed, and the old name taken again',
      r1.get_json().get('ok') and r2.get_json().get('ok'), (r1.get_json(), r2.get_json()))
r = c.post('/project/hist/history/20260101-090000/restore').get_json()
check('the restored version places the renamed page', 'src="moon-chart"' in (r.get('text') or ''),
      r.get('text'))
check('not the new one', 'src="moon-map"' not in (r.get('text') or ''))
# a version kept after the rename and the reuse means the new page
time.sleep(1.1)
stamp = A.snapshot_manuscript('hist', f'# Two\n\n{PARA}\n\n{page_plan.fence("moon-map")}\n',
                              force=True)
r = c.post(f'/project/hist/history/{stamp}/restore').get_json()
check('a version from after the reuse keeps the new page', 'src="moon-map"' in (r.get('text') or ''),
      r.get('text'))

# ---- 32.7 -------------------------------------------------------------------
print('32.7 Automatic EPUB layout with an unplaced draft design')
book('pb', f'# One\n\n{PARA}\n', [design('draft')], picture_book=True)
check('an unplaced design leaves the ebook reflowable',
      A.ebook_layout(A.load_project('pb')) == 'flow')
book('pb2', f'# One\n\n{page_plan.fence("spot")}\n', [design('spot')], picture_book=True)
check('a placed one makes it page by page', A.ebook_layout(A.load_project('pb2')) == 'fixed')

# ---- 32.8 -------------------------------------------------------------------
print('32.8 an oversized cover upload')
book('big', f'# One\n\n{PARA}\n')
real_cap = A.IMAGE_MAX_BYTES
A.IMAGE_MAX_BYTES = 100
try:
    r = c.post('/project/big/edit', data={'title': 'big', 'cover_mode': 'image',
                                          'cover': (io.BytesIO(picture('PNG')), 'a.png')},
               content_type='multipart/form-data', follow_redirects=True)
finally:
    A.IMAGE_MAX_BYTES = real_cap
check('it is refused', not A.load_project('big').get('cover_file'))
check('and the page says why', 'larger than' in r.get_data(as_text=True))

# ---- 32.9 -------------------------------------------------------------------
print('32.9 opening a Word book\'s Page Plan writes no figures')
from docx import Document
png = os.path.join(TMP, 'pic.png')
with open(png, 'wb') as f:
    f.write(picture('PNG'))
doc = Document()
doc.add_heading('One', 1)
doc.add_paragraph(PARA)
doc.add_picture(png)
doc.save(os.path.join(A.PROJECT_MS_DIR, 'wordy.docx'))
A.save_project_file('wordy', {'name': 'wordy', 'title': 'wordy', 'preset': 'classic-literary',
                              'manuscript_file': 'wordy.docx', 'manuscript_type': 'file',
                              'format': 'pdf', 'front_matter': 'none'})
r1 = c.get('/project/wordy/plan')
r2 = c.get('/project/wordy/plan/data')
check('the plan opened', r1.status_code == 200 and r2.get_json().get('ok'))
check('and no figure was written', not os.listdir(FIG), os.listdir(FIG))
text = A._project_manuscript_text(A.load_project('wordy'), report_import=False)
check('a build\'s read still writes them', os.listdir(FIG) and '~~~ figure' in text, os.listdir(FIG))

# ---- 32.12 ------------------------------------------------------------------
print('32.12 designer saves with a JSON list')
r1 = c.post('/wrap-designer/project/wrap/save', json=['draft'])
r2 = c.post('/page-designer/ren/save', json=['draft'])
check('the wrap designer refuses it', r1.status_code < 500 and not r1.get_json().get('ok'),
      r1.status_code)
check('and the page designer', r2.status_code < 500 and not r2.get_json().get('ok'), r2.status_code)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f'{len(fails)} failure(s)' if fails else 'all passed')
sys.exit(1 if fails else 0)
