"""Rounds 4-5's fixes don't bring bugs of their own  (run: python test_regressions6_bughunt.py).

Joint bug hunt, round 6, section 26 (regressions shipped in 1.15.0):

    26.1  taking an unclosed page off the Page Plan keeps the chapter after it
    26.2  saving a result whose staged manuscript was cleared away says so
    26.3  a font set aside at start-up is still the one the user's styles use
    26.4  unticking the wrap brings back an uploaded cover, not a template
    26.5  a `# ` line inside a closed poem stays a verse
    26.6  TS_PORT=65535 taken falls back to another port
    26.7  a second settings recovery keeps the first one's copy
    26.8  bold around a bold-italic span (`**The ___Moon___ Gate**`)
    26.9  the settings lock is only removed, or written under, by its holder
    26.10 a long run of blank lines pastes in linear time
    26.11 the first-pages preview stops before chapters set only for the contents
    26.12 an apostrophe after emphasis (`*fox*'s`) is not an opening quote

(26.5 and 26.10 in the rich editor: `bh26-*` in test_rich_editor.js.)
"""

import sys, os, io, json, re, shutil, socket, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import doc_model
import engine
import manuscript as M
import page_plan
import statblock

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh26-')
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
A.app.config['TESTING'] = True
c = A.app.test_client()


def make_book(pid, text='# One\n\nThe text.\n', **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    data = dict(name=pid, title='T', author='A', preset='classic-literary', format='pdf',
                manuscript_file=pid + '.md', manuscript_type='markdown', cover_file='',
                cover_mode='none', last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', front_matter='none')
    data.update(over)
    A.save_project_file(pid, data)


def ms_of(pid):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), encoding='utf-8') as f:
        return f.read()


def titles(text):
    return [ch['title'] for ch in M.parse_markdown(text)['chapters']]


# ---- 26.1 -------------------------------------------------------------------
print('26.1 an unclosed page taken off the plan')
design = {'name': 'map', 'saved': '2026-11-13T10:00:00',
          'elements': [{'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#c03020'}]}
text = '# One\n\nThe first chapter.\n\n~~~ page src="map"\n\n# Chapter Two\n\nIts own prose.\n'
make_book('pp', text, page_designs=[design], preset='picture-book', bleed=True)
items = page_plan.split(text)
check('the page piece holds only the page',
      [(it['kind'], it.get('src')) for it in items] == [('text', None), ('page', 'map'), ('text', None)]
      and 'Chapter Two' in items[2]['text'], items)
d = c.get('/project/pp/plan/data').get_json()
r = c.post('/project/pp/plan/save', json={'rev': d['rev'], 'order': [{'text': 0}, {'text': 2}]})
after = ms_of('pp')
check('the page is gone', r.get_json().get('ok', True) is not False
      and 'src="map"' not in after, r.get_json())
check('chapter two and its prose are kept', titles(after) == ['One', 'Chapter Two']
      and 'Its own prose.' in after, after)
# any rewrite that would change the chapters is refused, however it came about
outline = getattr(page_plan, 'outline', lambda t: None)
check('the outline guard sees a lost chapter',
      outline('# One\n\nA.\n') != outline('# One\n\nA.\n\n# Two\n\nB.\n'))
check('but not a moved page',
      outline('# One\n\n~~~ page src="a"\n~~~\n\nA.\n')
      == outline('# One\n\nA.\n\n~~~ page src="a"\n~~~\n'))

# ---- 26.2 -------------------------------------------------------------------
print('26.2 a result whose staged manuscript was cleared away')
gone = os.path.join(A.UPLOAD_DIR, 'cleared.md')
before = set(os.listdir(A.PROJECT_DIR))
r = c.post('/project/create', data={'project_name': 'Lost Book', 'ms_path': gone,
                                    'ms_type': 'pasted', 'preset_id': 'classic-literary'},
           follow_redirects=True)
page = r.get_data(as_text=True)
check('no project is saved', set(os.listdir(A.PROJECT_DIR)) == before,
      set(os.listdir(A.PROJECT_DIR)) - before)
check('and the page says why', 'cleared away' in page and 'Compose the book again' in page)
staged = os.path.join(A.UPLOAD_DIR, 'here.md')
open(staged, 'w', encoding='utf-8').write('# One\n\nText.\n')
c.post('/project/create', data={'project_name': 'Kept Book', 'ms_path': staged,
                                'ms_type': 'pasted', 'preset_id': 'classic-literary'})
check('a staged file still there is saved', os.path.exists(
    os.path.join(A.PROJECT_MS_DIR, 'kept-book.md')), os.listdir(A.PROJECT_MS_DIR))

# ---- 26.3 -------------------------------------------------------------------
print('26.3 a font set aside keeps its styles')
bundle = os.path.join(TMP, 'bundle')
data = os.path.join(TMP, 'data')
for sub in ('fonts', 'presets', 'covers'):
    os.makedirs(os.path.join(bundle, sub)); os.makedirs(os.path.join(data, sub))
os.makedirs(os.path.join(data, 'projects'))
open(os.path.join(bundle, 'fonts', 'Andika-Regular.ttf'), 'wb').write(b'bundled andika')
open(os.path.join(data, 'fonts', 'Andika-Regular.ttf'), 'wb').write(b'the user font')
json.dump({'name': 'Early Reader', 'font_files': {'regular': 'Andika-Regular.ttf'}},
          open(os.path.join(bundle, 'presets', 'early-reader.json'), 'w'))
json.dump({'name': 'Mine', 'font_files': {'regular': 'Andika-Regular.ttf',
                                          'bold': 'Other-Bold.ttf'}},
          open(os.path.join(data, 'presets', 'mine.json'), 'w'))
json.dump({'name': 'My cover', 'fonts': {'title': 'andika-regular.ttf'}},
          open(os.path.join(data, 'covers', 'my-cover.json'), 'w'))
json.dump({'name': 'Book', 'wrap_design': {'elements': [{'id': 't', 'font': 'Andika-Regular.ttf'}]},
           'page_designs': [{'name': 'p', 'elements': [{'id': 'u', 'font': 'Andika-Regular.ttf'},
                                                        {'id': 'v', 'font': 'Else.ttf'}]}]},
          open(os.path.join(data, 'projects', 'book.json'), 'w'))
saved = (A.resource_path, A.FONT_DIR, A.PRESET_DIR, A.COVER_DIR, A.PROJECT_DIR)
A.resource_path = lambda *p: os.path.join(bundle, *p)
A.FONT_DIR, A.PRESET_DIR, A.COVER_DIR = (os.path.join(data, s) for s in ('fonts', 'presets', 'covers'))
A.PROJECT_DIR = os.path.join(data, 'projects')
try:
    A._seed_defaults()
    rd = lambda *p: json.load(open(os.path.join(data, *p), encoding='utf-8'))
    check('the user font was set aside',
          open(os.path.join(data, 'fonts', 'Andika-Regular-own.ttf'), 'rb').read() == b'the user font')
    check('their style now names it', rd('presets', 'mine.json')['font_files']
          == {'regular': 'Andika-Regular-own.ttf', 'bold': 'Other-Bold.ttf'})
    check('their cover template too', rd('covers', 'my-cover.json')['fonts']['title']
          == 'Andika-Regular-own.ttf')
    book = rd('projects', 'book.json')
    check('their wrap design and designed pages too',
          book['wrap_design']['elements'][0]['font'] == 'Andika-Regular-own.ttf'
          and [e['font'] for e in book['page_designs'][0]['elements']]
          == ['Andika-Regular-own.ttf', 'Else.ttf'], book)
    check('the bundled style keeps the bundled face',
          rd('presets', 'early-reader.json')['font_files']['regular'] == 'Andika-Regular.ttf')
finally:
    A.resource_path, A.FONT_DIR, A.PRESET_DIR, A.COVER_DIR, A.PROJECT_DIR = saved

# ---- 26.4 -------------------------------------------------------------------
print('26.4 unticking the wrap brings back the cover the book had')
open(os.path.join(A.PROJECT_MS_DIR, 'up-cover.jpg'), 'wb').write(b'x')
EL = [{'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1, 'w': 4,
       'text': 'Title', 'font': 'EBGaramond-Regular.ttf', 'size': 24, 'color': '#000000'}]


def tick(pid, on):
    return c.post(f'/wrap-designer/project/{pid}/save',
                  json={'design': {'elements': EL}, 'use_as_cover': on}).get_json()


# Compose saves the template id beside the uploaded picture
make_book('img', cover_mode='image', cover_file='up-cover.jpg', cover_template='ashforge-house')
tick('img', True); tick('img', False)
check('an uploaded cover comes back', A.load_project('img')['cover_mode'] == 'image',
      A.load_project('img')['cover_mode'])
make_book('tpl', cover_mode='designed', cover_file='up-cover.jpg', cover_template='ashforge-house')
tick('tpl', True); tick('tpl', False)
check('a template cover comes back', A.load_project('tpl')['cover_mode'] == 'designed')
# ticked before this fix: no record of the mode before, the picture wins
make_book('old', cover_mode='wrap', cover_file='up-cover.jpg', cover_template='ashforge-house')
tick('old', False)
check('with no record, an uploaded picture wins', A.load_project('old')['cover_mode'] == 'image')

# ---- 26.5 -------------------------------------------------------------------
print('26.5 a `# ` line in a closed poem')
poem = '# One\n\n~~~ poem\nA line\n# 7 on the door\nB line\n~~~\n\nProse after.\n'
got = M.parse_markdown(poem)
check('one chapter, the line a verse', len(got['chapters']) == 1
      and '# 7 on the door' in got['chapters'][0]['blocks'][0][1][0][1], got['chapters'])
check('the prose after stays prose', got['chapters'][0]['blocks'][-1] == ('para', 'Prose after.'))
check('nothing reported unclosed', not got.get('blocks_unclosed'))
check('the editor model agrees', doc_model.to_markdown(doc_model.from_markdown(poem, False))
      == poem.replace('\n# 7', '\n\\# 7'))
# the recovery still works where the fence really is missing
lost = '# One\n\n~~~ poem\nA line\n\n# Two\n\nProse.\n\n~~~ sidebar\nNote.\n~~~\n'
check('a missing fence still ends at the chapter', titles(lost) == ['One', 'Two'], titles(lost))
check('and at the end of the book', titles('# One\n\n~~~ poem\nA\n\n# Two\n\nB.\n') == ['One', 'Two'])

# ---- 26.6 -------------------------------------------------------------------
print('26.6 the highest port taken')
hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    hold.bind(('127.0.0.1', 65535)); hold.listen(1)
    held = True
except OSError:
    held = False                        # someone has it already: just as good
try:
    s = A._bind_port(65535)
    check('another port is found', s.getsockname()[1] not in (65535,), s.getsockname())
    s.close()
except Exception as exc:
    check('another port is found', False, repr(exc))
finally:
    hold.close()

# ---- 26.7 -------------------------------------------------------------------
print('26.7 two settings recoveries')
open(A.SETTINGS_PATH, 'w').write('{"first": tru')
with A.settings_change() as st:
    st['update_check'] = True
open(A.SETTINGS_PATH, 'w').write('{"second": fals')
with A.settings_change() as st:
    st['update_check'] = True
readf = lambda p: open(p).read() if os.path.exists(p) else None
check('the first copy is kept', readf(A.SETTINGS_PATH + '.damaged') == '{"first": tru')
check('the second beside it', readf(A.SETTINGS_PATH + '.damaged-2') == '{"second": fals')

# ---- 26.8 -------------------------------------------------------------------
print('26.8 emphasis around emphasis')
check('bold around bold-italic', M._inline('**The ___Moon___ Gate**')
      == '<b>The <b><i>Moon</i></b> Gate</b>', M._inline('**The ___Moon___ Gate**'))
check('italic around bold', M._inline('*x **y** z*') == '<i>x <b>y</b> z</i>')
check('bold around italic', M._inline('**a *b* c**') == '<b>a <i>b</i> c</b>')
check('tags never cross (23.2)', M._inline('***bold **a*** b**') == '<b><i>bold **a</i></b> b**')
check('an unpaired star stays out (22.x)', M._inline('a*b **a *b* c**') == 'a*b <b>a <i>b</i> c</b>')

# ---- 26.9 -------------------------------------------------------------------
print('26.9 the settings lock')
lock = A.SETTINGS_PATH + '.lock'
A.save_settings({'a': 1})
try:
    with A.settings_change() as st:
        st['a'] = 2
        # paused past the stale age: another copy takes the lock over and writes
        with open(lock, 'w') as f:
            f.write('another copy')
        A.save_settings({'a': 3})
    check('a holder whose lock was taken does not write', False)
except OSError:
    check('a holder whose lock was taken does not write', A.load_settings() == {'a': 3})
check('nor removes the other copy\'s lock', os.path.exists(lock)
      and open(lock).read() == 'another copy')
if os.path.exists(lock): os.remove(lock)
with A.settings_change() as st:
    st['a'] = 4
check('an ordinary change writes and lets go', A.load_settings() == {'a': 4}
      and not os.path.exists(lock))

# ---- 26.10 ------------------------------------------------------------------
print('26.10 a long run of blank lines')
t0 = time.time()
out = statblock.wrap_unfenced('Prose.' + '\n' * 50000 + 'More.')
check('wrapped in linear time', time.time() - t0 < 2 and out.count('\n') == 50000,
      time.time() - t0)
check('a rule then a monster is still wrapped',
      statblock.wrap_unfenced('___\n\n\n> ## Ash Drake\n> AC 15\n').startswith('~~~ statblock'))

# ---- 26.11 ------------------------------------------------------------------
print('26.11 the first-pages preview')
three = ''.join(f'# Chapter {n}\n\nA short chapter.\n\n' for n in (1, 2, 3))
r = c.post('/generate/preview', data={'preset': 'classic-literary', 'pasted': three,
                                       'include_toc': '1', 'cover_mode': 'none',
                                       'front_matter': 'none', 'title': 'T'}).get_json()
check('it built', r and r.get('ok'), r)
if r and r.get('ok'):
    check('only two chapters are shown', r['chapters_shown'] == 2 and r['truncated'])
    check('and no page past the second chapter',
          r['shown'] < r['built_pages'], (r['shown'], r['built_pages']))
    res = engine.build_pdf(M.parse_markdown(three), A.load_preset('classic-literary'),
                           os.path.join(TMP, 'three.pdf'), {'title': 'T', 'front_matter': 'none'})
    check('the build says where each chapter opens',
          sorted(res['chapter_pages']) == [1, 2, 3], res.get('chapter_pages'))

# ---- 26.12 ------------------------------------------------------------------
print('26.12 quotes after emphasis')
check('a possessive after italics', M._inline("The *fox*'s paw") == 'The <i>fox</i>’s paw',
      M._inline("The *fox*'s paw"))
check('a closing quote after italics', M._inline('"He said *no*"') == '“He said <i>no</i>”')
check('a quotation inside italics still opens', M._inline('*"wait"*') == '<i>“wait”</i>')
check('and a single one', M._inline("(*'quoted'*)") == '(<i>‘quoted’</i>)')

print()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print(f'{len(fails)} FAILED')
    sys.exit(1)
print('all passed')
