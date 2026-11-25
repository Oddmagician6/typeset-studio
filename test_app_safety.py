"""App routes keep a writer's files safe  (run: python test_app_safety.py).

Joint bug hunt, section 7. Each check is one way a route could lose, misplace
or mix up a book's files, or break a page, that the hunt found:

    7.1   an id with Windows path parts finds a book and writes only inside it
    7.2   a Word manuscript that can't be read is never replaced by a write
    7.3   a failed Edit save leaves the files the book still names
    7.4   a book whose record can't be deleted keeps its files
    7.5   two books made at once under one name get two ids
    7.7   a failed Wrap Designer save leaves the front cover the builds use
    7.8   renaming a page design follows a `src=“curly”` placement
    7.9   one malformed wrap design doesn't take down the Projects page
    7.10  a font used only on a designed interior page is reported as used
    7.11  cover-art uploads of one name get their own files
    7.12  a damaged back-cover photo is refused, not silently dropped
    7.13  an EPUB-only rebuild that fails says so and keeps the last download
"""

import sys, os, json, shutil, tempfile, io

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import page_plan
import wrap_design

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
    A.COVER_ASSET_DIR = os.path.join(tmp, 'covers', 'assets')
    A.PROJECT_DIR = os.path.join(tmp, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(tmp, 'out')
    A.UPLOAD_DIR = os.path.join(tmp, 'uploads')
    A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR,
              A.PROJECT_THUMB_DIR, A.COVER_ASSET_DIR):
        os.makedirs(d, exist_ok=True)


def png_bytes(w=60, h=90):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (w, h), (120, 30, 30)).save(b, 'PNG')
    return b.getvalue()


def make_book(pid, text='# One\n\nThe text.\n', **over):
    ms = over.pop('manuscript_file', pid + '.md')
    if ms.endswith('.md'):
        with open(os.path.join(A.PROJECT_MS_DIR, ms), 'w', encoding='utf-8') as f:
            f.write(text)
    data = dict(name=pid, preset='', format='pdf', manuscript_file=ms,
                manuscript_type='markdown', cover_file='', cover_mode='none',
                last_pdf='', last_epub='', created='2026-01-01T00:00:00',
                updated='2026-01-01T00:00:00', print_back_file='')
    data.update(over)
    A.save_project_file(pid, data)
    return data


def stored(pid):
    with open(os.path.join(A.PROJECT_DIR, pid + '.json'), encoding='utf-8') as f:
        return json.load(f)


def ms_path(name):
    return os.path.join(A.PROJECT_MS_DIR, name)


def main():
    tmp = tempfile.mkdtemp(prefix='ts-safety-')
    try:
        use_folders(tmp)
        c = A.app.test_client()

        print('7.1  ids with path parts')
        make_book('atlas')
        outside = os.path.join(A.PROJECT_DIR, 'atlas.md')
        r = c.post('/project/..\\atlas/write/save', data={'text': '# One\n\nNew.\n'})
        check('the save went to the book', r.status_code == 200 and
              open(ms_path('atlas.md'), encoding='utf-8').read() == '# One\n\nNew.\n',
              r.status_code)
        check('and nothing was written outside its folder', not os.path.exists(outside))

        print('7.2  an unreadable Word manuscript')
        with open(ms_path('worded.docx'), 'wb') as f:
            f.write(b'PK\x03\x04 not really a word file')
        make_book('worded', manuscript_file='worded.docx', manuscript_type='file')
        r = c.post('/project/worded/plan/add', json={'rev': A._ms_rev(''), 'kind': 'page'})
        check('+ Page is refused', r.status_code == 409 and not r.get_json()['ok'], r.status_code)
        r = c.post('/project/worded/write/save', data={'text': 'typed', 'base': A._ms_rev('')})
        check('an editor save is refused', r.status_code == 409, r.status_code)
        check('the Word file is still there and still named',
              os.path.exists(ms_path('worded.docx'))
              and stored('worded')['manuscript_file'] == 'worded.docx')

        print('7.3  a failed Edit save')
        with open(ms_path('edit-cover.jpg'), 'wb') as f:
            f.write(b'old jpeg')
        make_book('edit', cover_file='edit-cover.jpg', cover_mode='image')
        real_save = A.save_project_file
        def failing_save(pid, data):
            raise OSError('disk full')
        A.save_project_file = failing_save
        try:
            c.post('/project/edit/edit', data={'name': 'edit',
                   'cover': (io.BytesIO(png_bytes()), 'new.png')},
                   content_type='multipart/form-data')
        finally:
            A.save_project_file = real_save
        check('the cover the book names is kept', os.path.exists(ms_path('edit-cover.jpg'))
              and stored('edit')['cover_file'] == 'edit-cover.jpg')
        c.post('/project/edit/edit', data={'name': 'edit',
               'cover': (io.BytesIO(png_bytes()), 'new.png')},
               content_type='multipart/form-data')
        check('a save that works still drops the old one',
              stored('edit')['cover_file'] == 'edit-cover.png'
              and not os.path.exists(ms_path('edit-cover.jpg')))

        print('7.4  a record that can\'t be deleted')
        make_book('held')
        held_json = os.path.join(A.PROJECT_DIR, 'held.json')
        real_remove = os.remove
        def held_remove(p, *a, **k):
            if os.path.abspath(p) == os.path.abspath(held_json):
                raise PermissionError('in use')
            return real_remove(p, *a, **k)
        A.os.remove = held_remove
        try:
            c.post('/project/held/delete')
        finally:
            A.os.remove = real_remove
        check('the book and its manuscript are both kept',
              os.path.exists(held_json) and os.path.exists(ms_path('held.md')))

        print('7.5  two books at once')
        a, b = A.unique_project_id('twin'), A.unique_project_id('twin')
        check('get two ids', a != b, (a, b))
        make_book(a)
        check('a saved id is no longer held', a not in A._RESERVED_IDS)

        print('7.7  a failed wrap save')
        make_book('wrapped', last_page_count=200)
        design = {'elements': [{'id': 't', 'type': 'text', 'panel': 'front', 'x': 0.5, 'y': 1,
                                'w': 4, 'h': 1, 'text': 'First', 'size': 30}]}
        r = c.post('/wrap-designer/project/wrapped/save', json={'design': design})
        check('a first save works', r.get_json().get('ok'), r.get_json())
        front = ms_path('wrapped-wrap-front.jpg')
        before = open(front, 'rb').read() if os.path.exists(front) else None
        A.save_project_file = failing_save
        try:
            design['elements'][0]['text'] = 'Second, unsaved'
            design['elements'][0]['size'] = 60
            c.post('/wrap-designer/project/wrapped/save', json={'design': design})
        finally:
            A.save_project_file = real_save
        check('the front the builds use is the saved one',
              before is not None and open(front, 'rb').read() == before)
        check('and no half-saved file is left', not os.path.exists(front + '.saving.jpg'))

        print('7.8  renaming a curly-quoted placement')
        moved = page_plan.rename('~~~ page src=“moon-map”\n~~~\n', 'moon-map', 'moon-chart')
        check('follows the new name', moved == '~~~ page src="moon-chart"\n~~~\n', ascii(moved))
        items = page_plan.split('Text.\n\n~~~ page src=“moon-map”\n~~~\n')
        check('and the plan reads it', any(i.get('src') == 'moon-map' for i in items), items)

        print('7.9  a malformed wrap design')
        check('an empty drawing op is just not a reserve',
              wrap_design.reserve_box({'type': 'vector', 'ops': [[]]}) is None)
        make_book('odd', wrap_design={'elements': [{'type': 'vector', 'ops': [[]]}]})
        r = c.get('/projects')
        check('the Projects page still opens', r.status_code == 200, r.status_code)

        print('7.10 fonts on designed pages')
        make_book('paged', page_designs=[{'name': 'map', 'elements': [
            {'type': 'text', 'font': 'Inkwell.ttf', 'text': 'Here'}]}])
        uses = A._font_uses('Inkwell.ttf')
        check('the page is named as a use', any('map' in u for u in uses), uses)

        print('7.11 cover-art uploads of one name')
        names = [c.post('/cover/asset/upload', data={'asset': (io.BytesIO(png_bytes()), 'emblem.png')},
                        content_type='multipart/form-data').get_json().get('filename')
                 for _ in range(2)]
        check('get their own files', names[0] and names[1] and names[0] != names[1], names)

        print('7.12 a damaged back-cover photo')
        r = c.post('/cover/wrap', data={'name': 'x', 'wrap_back_image':
                                        (io.BytesIO(b'\xff\xd8\xff broken'), 'author.jpg')},
                   content_type='multipart/form-data')
        check('the download is refused, and says why', r.status_code == 400
              and 'back-cover image' in (r.get_json() or {}).get('error', ''), r.status_code)

        print('7.13 a failed EPUB-only rebuild')
        make_book('ebook', format='epub', last_epub='ebook-old.epub')
        real_build = A.epub.build_epub
        def failing_epub(*a, **k):
            raise OSError('disk full')
        A.epub.build_epub = failing_epub
        try:
            r = c.post('/project/ebook/rebuild')
        finally:
            A.epub.build_epub = real_build
        check('counts as failed', r.get_json().get('ok') is False, r.get_json())
        check('and keeps the last download', stored('ebook').get('last_epub') == 'ebook-old.epub',
              stored('ebook').get('last_epub'))

        print('7.S1 another site can\'t change a book')
        make_book('target')
        r = c.post('/project/target/delete', headers={'Origin': 'http://evil.example'})
        check('a cross-origin delete is refused', r.status_code == 403, r.status_code)
        r = c.post('/project/target/delete', headers={'Sec-Fetch-Site': 'cross-site'})
        check('so is one the browser marks cross-site', r.status_code == 403, r.status_code)
        r = c.post('/project/target/delete', headers={'Origin': 'null'})
        check('and one from an opaque origin', r.status_code == 403, r.status_code)
        check('the book is still there', os.path.isfile(os.path.join(A.PROJECT_DIR, 'target.json')))
        r = c.get('/', base_url='http://rebound.example/')
        check('a page asked for under another hostname is refused', r.status_code == 403,
              r.status_code)
        r = c.post('/project/target/delete', headers={'Origin': 'http://localhost',
                                               'Sec-Fetch-Site': 'same-origin'})
        check('the app\'s own page still deletes', r.status_code == 302
              and not os.path.isfile(os.path.join(A.PROJECT_DIR, 'target.json')), r.status_code)

        print('7.S2 the art route serves only pictures')
        art = os.path.join(tmp, 'art')
        os.makedirs(art)
        with open(os.path.join(art, 'page.html'), 'w') as f:
            f.write('<script>alert(1)</script>')
        with open(os.path.join(art, 'pic.png'), 'wb') as f:
            f.write(png_bytes())
        real_dirs = list(A.wrap_design.ART_DIRS)
        A.wrap_design.ART_DIRS[:] = [art]
        try:
            r = c.get('/wrap-designer/art/page.html')
            check('an html file in an art folder is not served', r.status_code == 404, r.status_code)
            r = c.get('/wrap-designer/art/pic.png')
            check('a picture is', r.status_code == 200, r.status_code)
            check('and can\'t be sniffed as anything else',
                  r.headers.get('X-Content-Type-Options') == 'nosniff', dict(r.headers))
            r.close()
        finally:
            A.wrap_design.ART_DIRS[:] = real_dirs

        print('8.S  the update feed asks for a full page')
        check('100 releases, not 30', 'per_page=100' in A.UPDATE_FEED, A.UPDATE_FEED)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f'{len(fails)} FAILED: ' + '; '.join(fails))
        sys.exit(1)
    print('all app safety checks passed')


if __name__ == '__main__':
    main()
