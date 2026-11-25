"""The project and style pages keep what was typed  (run: python test_frontend_bughunt.py).

Joint bug hunt, round 2, section 12:

    12.1  a style saved from a tab opened before a newer save keeps both
    12.2  Rebuild all hands the card its new download links
    12.3  a file left in the hidden cover box doesn't replace the saved art
    12.5  the style editor asks before its unsaved changes are left behind
    12.6  the book page's unsaved-changes check can't be fooled by `&`
    12.7  save-first links make the same checks Save changes does
    12.8  a style named "New" can be opened again
    12.9  a failed style preview clears the pages it no longer describes
    12.10 an ebook-only book that asks for the screen PDF gets one
    12.11 a cover card's Set a book arrives with that cover chosen
    12.12 the ornament picker shows where the keyboard is
    12.13 the live spec card shows the family name as typed
    (12.4 - a `{N}` number format - is in test_interior_bughunt.py)
"""

import sys, os, io, re, json, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def use_folders(tmp):
    shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(tmp, 'presets'))
    shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(tmp, 'covers'),
                    ignore=shutil.ignore_patterns('assets'))
    A.PRESET_DIR, A.COVER_DIR = os.path.join(tmp, 'presets'), os.path.join(tmp, 'covers')
    A.PROJECT_DIR = os.path.join(tmp, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(tmp, 'out')
    A.UPLOAD_DIR = os.path.join(tmp, 'uploads')
    A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR,
              A.PROJECT_THUMB_DIR):
        os.makedirs(d, exist_ok=True)


def png_bytes(w=60, h=90, colour=(120, 30, 30)):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (w, h), colour).save(b, 'PNG')
    return b.getvalue()


def make_book(pid, **over):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write('# One\n\nThe text.\n')
    data = dict(name=pid, title='T', author='A', preset='classic-literary', format='pdf',
                manuscript_file=pid + '.md', manuscript_type='markdown', cover_file='',
                cover_mode='none', last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', print_back_file='', front_matter='none')
    data.update(over)
    A.save_project_file(pid, data)
    return data


def stored(pid):
    with open(os.path.join(A.PROJECT_DIR, pid + '.json'), encoding='utf-8') as f:
        return json.load(f)


TMP = tempfile.mkdtemp()
use_folders(TMP)
A.app.config['TESTING'] = True
editor_html = open(os.path.join(HERE, 'templates', 'editor.html'), encoding='utf-8').read()
edit_html = open(os.path.join(HERE, 'templates', 'project_edit.html'), encoding='utf-8').read()

with A.app.test_client() as c:
    # ---- 12.1 --------------------------------------------------------------
    print('12.1 a stale style tab')
    page = c.get('/editor/classic-literary').get_data(as_text=True)
    m = re.search(r'name="version" value="([0-9a-f]+)"', page)
    check('the editor sends back the version it opened', m)
    old = m.group(1) if m else ''
    base = A.load_preset('classic-literary')
    form = {'name': base['name'], 'description': 'first tab', 'version': old}
    # the first tab saves a body size
    r = c.post('/save/classic-literary', data=dict(form, b_size='12.5'))
    first = A.load_preset('classic-literary')
    # the second, opened before it, saves only its description
    r = c.post('/save/classic-literary', data=dict(form, description='second tab'))
    now = A.load_preset('classic-literary')
    check('the newer save is kept', now == first, (now.get('description'), first.get('description')))
    copies = [p for p in A.list_presets() if 'edited elsewhere' in (p.get('data') or p).get('name', '')]
    check('the stale settings are kept as a copy', copies, [p.get('id') for p in A.list_presets()][:8])
    page = c.get('/editor/classic-literary').get_data(as_text=True)
    new = re.search(r'name="version" value="([0-9a-f]+)"', page).group(1)
    r = c.post('/save/classic-literary', data=dict(form, version=new, description='third'))
    check('a save from an up-to-date page saves in place',
          A.load_preset('classic-literary').get('description') == 'third')

    # ---- 12.8 --------------------------------------------------------------
    print('12.8 a style called New')
    r = c.post('/save', data={'name': 'New'})
    ids = {p['id'] for p in A.list_presets()}
    check('it is not stored as "new"', 'new' not in ids and any(i.startswith('new-') for i in ids),
          sorted(ids)[:10])

    # ---- 12.3 --------------------------------------------------------------
    print('12.3 hidden cover upload')
    make_book('art', cover_mode='image')
    with open(os.path.join(A.PROJECT_DIR, 'art-cover.png'), 'wb') as f:
        f.write(png_bytes())
    d = stored('art'); d['cover_file'] = 'art-cover.png'; A.save_project_file('art', d)
    data = {'name': 'art', 'title': 'T', 'author': 'A', 'preset': 'classic-literary',
            'format': 'pdf', 'front_matter': 'none', 'cover_mode': 'none'}
    data['cover'] = (io.BytesIO(png_bytes(colour=(10, 200, 10))), 'new.png')
    c.post('/project/art/edit', data=data, content_type='multipart/form-data')
    after = stored('art')
    check('the saved art is still the book\'s', after.get('cover_file') == 'art-cover.png',
          after.get('cover_file'))
    check('and still on disk', os.path.exists(os.path.join(A.PROJECT_DIR, 'art-cover.png')))

    # ---- 12.10 / 12.2 ------------------------------------------------------
    print('12.10 / 12.2 rebuild')
    make_book('ebook', format='epub', screen_pdf=True)
    j = c.post('/project/ebook/rebuild', headers={'X-Requested-With': 'fetch'}).get_json()
    check('an ebook-only book with the screen PDF ticked gets it',
          j and j.get('ok') and j.get('screen'), j)
    make_book('print', format='pdf')
    j = c.post('/project/print/rebuild', headers={'X-Requested-With': 'fetch'}).get_json()
    check('the rebuild answer carries the new PDF', j and j.get('pdf'), j)

# ---- template-side fixes (the pages' own scripts) --------------------------
print('12.2 / 12.5-12.7 / 12.9 / 12.11-12.13 page scripts')
proj_html = open(os.path.join(HERE, 'templates', 'projects.html'), encoding='utf-8').read()
check('12.2 the card links are updated after a rebuild',
      'a[data-last="' in proj_html and 'data-last="pdf"' in proj_html)
check('12.5 the style editor guards unsaved changes', "beforeunload" in editor_html)
check('12.6 the book page compares encoded pairs, not k=v&k=v',
      'JSON.stringify(out)' in edit_html and "out.join('&')" not in edit_html)
check('12.7 save-first links check the form first', 'form.reportValidity()' in edit_html)
check('12.9 a failed preview clears its pages', 'clearPages();' in editor_html)
covers_html = open(os.path.join(HERE, 'templates', 'covers.html'), encoding='utf-8').read()
gen_html = open(os.path.join(HERE, 'templates', 'generate.html'), encoding='utf-8').read()
check('12.11 Set a book carries the cover', "url_for('generate', cover=item.id)" in covers_html
      and "request.args.get('cover')" in gen_html)
with A.app.test_client() as c:
    page = c.get('/generate?cover=vintage-pulp').get_data(as_text=True)
    m = re.search(r'name="cover_template" value="vintage-pulp"[^>]*checked', page)
    check('12.11 and the form opens with it chosen', m is not None)
check('12.12 the ornament tile shows keyboard focus', 'input:focus-visible' in editor_html)
check('12.13 the family name is set as text',
      "innerHTML = '<b>'+num('f-bsize')" not in editor_html and 'replaceChildren' in editor_html)

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
