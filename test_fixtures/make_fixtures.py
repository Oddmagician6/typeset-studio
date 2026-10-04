"""Freeze what a release writes, as fixtures for test_upgrade.py.

Run at a release, from a throwaway worktree at its tag (the old app writes
into that checkout's own data folders, which are then copied out):

    git worktree add ../wt v1.3.0
    cd ../wt && mkdir -p projects/manuscripts out uploads
    python <repo>/test_fixtures/make_fixtures.py <repo>/test_fixtures/v1.3.0
    cd <repo> && git worktree remove --force ../wt

It drives the release's own pages as a writer would, each form submitted as
the page offered it with a few fields changed, so the files are that version's
own. Add the new folder to RELEASES in test_upgrade.py.
"""
import sys, os, io, json, shutil, glob, re
from html.parser import HTMLParser
sys.path.insert(0, os.getcwd())
import logging; logging.disable(logging.INFO)
from werkzeug.datastructures import MultiDict, FileStorage
import app as A


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


OUT = sys.argv[1]
c = A.app.test_client()
before = {d: set(os.listdir(getattr(A, d))) for d in ('PRESET_DIR', 'COVER_DIR')}
log = []


def png(color=(120, 40, 40)):
    from PIL import Image
    b = io.BytesIO(); Image.new('RGB', (600, 900), color).save(b, 'PNG'); b.seek(0)
    return b


def post_form(page_url, action, changes=None, files=None, drop=()):
    html = c.get(page_url).get_data(as_text=True)
    fields = MultiDict([(k, v) for k, v in form_of(html, action).items(multi=True) if k not in drop])
    for k, v in (changes or {}).items():
        if isinstance(v, list):
            fields.setlist(k, v)
        else:
            fields[k] = v
    data = MultiDict(fields)
    for k, (stream, name) in (files or {}).items():
        data.add(k, FileStorage(stream, filename=name))
    return c.post(action, data=data, content_type='multipart/form-data'), fields


def new_draft():
    r = c.post('/project/new-draft')
    loc = r.headers.get('Location', '')
    m = re.search(r'/project/([^/]+)/', loc)
    return m.group(1) if m else None


def rename(old, new):
    """Give a project a fixture's name (its id is the file name)."""
    for f in glob.glob(os.path.join(A.PROJECT_MS_DIR, old + '*')):
        b = os.path.basename(f)
        os.rename(f, os.path.join(A.PROJECT_MS_DIR, new + b[len(old):]))
    p = json.load(open(os.path.join(A.PROJECT_DIR, old + '.json'), encoding='utf-8'))
    for k, v in list(p.items()):
        if isinstance(v, str) and v.startswith(old):
            p[k] = new + v[len(old):]
    os.remove(os.path.join(A.PROJECT_DIR, old + '.json'))
    with open(os.path.join(A.PROJECT_DIR, new + '.json'), 'w', encoding='utf-8') as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


# a blank new draft, never edited
pid = new_draft(); rename(pid, 'draft'); log.append('draft')

# a draft edited on the Edit page: details, matter, a dedication
pid = new_draft()
r, _ = post_form(f'/project/{pid}/edit', f'/project/{pid}/edit',
                 {'title': 'The Salt Road', 'author': 'Ellinor Vale', 'subtitle': 'A Novel',
                  'publisher': 'Ashforge', 'year': '2026', 'dedication': 'For the walkers.',
                  'also_by': 'The Tide Clock', 'format': 'both', 'include_toc': 'on'})
rename(pid, 'edited'); log.append(f'edited {r.status_code}')

# uploaded cover art (with "image" mode where the version has modes)
pid = new_draft()
ch = {'title': 'The Salt Road', 'author': 'Ellinor Vale'}
html = c.get(f'/project/{pid}/edit').get_data(as_text=True)
if 'name="cover_mode"' in html:
    ch['cover_mode'] = 'image'
if 'name="print_blurb"' in html:
    ch.update(print_blurb='A road of salt.', print_retailer='ingramspark', print_binding='hardcover',
              print_paper='cream')
r, _ = post_form(f'/project/{pid}/edit', f'/project/{pid}/edit', ch, files={'cover': (png(), 'art.png')})
rename(pid, 'image-cover'); log.append(f'image-cover {r.status_code}')

# a designed cover, where the version has them
pid = new_draft()
html = c.get(f'/project/{pid}/edit').get_data(as_text=True)
if 'name="cover_template"' in html:
    r, _ = post_form(f'/project/{pid}/edit', f'/project/{pid}/edit',
                     {'title': 'The Salt Road', 'author': 'Ellinor Vale', 'cover_mode': 'designed',
                      'cover_template': 'ashforge-house', 'cover_collection': 'Edenfall Collection',
                      'cover_studio': 'Ashforge Studio'})
    rename(pid, 'designed'); log.append(f'designed {r.status_code}')
else:
    os.remove(os.path.join(A.PROJECT_DIR, pid + '.json'))

# "Set a book" with an uploaded manuscript and cover, then "Save as project"
ms = io.BytesIO(b'# The Salt Road\n\nThe opening paragraph, long enough to set a line or two of type.\n\n'
                b'# The Second Mile\n\nAnother chapter.\n')
r, fields = post_form('/generate', '/generate',
                      {'title': 'The Salt Road', 'author': 'Ellinor Vale'},
                      files={'manuscript': (ms, 'salt-road.md'), 'cover': (png((40, 60, 120)), 'cover.png')})
html = r.get_data(as_text=True)
act = '/project/create'
if act in html:
    fields2 = form_of(html, act)
    fields2['project_name'] = 'Set a book'
    r2 = c.post(act, data=fields2)
    pid = re.sub(r'.*/project/([^/]+)/.*', r'\1', r2.headers.get('Location', ''))
    made = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(A.PROJECT_DIR, '*.json'))
            if os.path.basename(p)[:-5] not in ('draft', 'edited', 'image-cover', 'designed')]
    if made:
        rename(made[0], 'set-a-book'); log.append(f'set-a-book {r.status_code} {r2.status_code}')
else:
    log.append(f'set-a-book: no save-as-project form ({r.status_code})')

# a style saved from the style editor, untouched but for its name
r, _ = post_form('/editor/new', '/save', {'name': 'Old Style'})
log.append(f'style {r.status_code}')
# a cover template from "New", and a bundled one cloned and saved in the editor
r, _ = post_form('/cover/new', '/cover/save', {'name': 'Old Cover'})
log.append(f'cover-new {r.status_code}')
r = c.post('/cover/clone/ashforge-house')
loc = r.headers.get('Location', '')
cid = loc.rstrip('/').rsplit('/', 1)[-1]
r, _ = post_form(f'/cover/{cid}', f'/cover/save/{cid}')
log.append(f'cover-clone {cid} {r.status_code}')

# copy out what this version wrote
for sub in ('projects', 'projects/manuscripts', 'presets', 'covers'):
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)
for p in glob.glob(os.path.join(A.PROJECT_DIR, '*.json')):
    shutil.copy(p, os.path.join(OUT, 'projects'))
from PIL import Image
for p in glob.glob(os.path.join(A.PROJECT_MS_DIR, '*')):
    if os.path.isfile(p):
        shutil.copy(p, os.path.join(OUT, 'projects', 'manuscripts'))
for p in glob.glob(os.path.join(OUT, 'projects', 'manuscripts', '*.png')):
    Image.open(p).convert('RGB').resize((200, 300)).save(p, optimize=True)   # small in the repo
for d, sub in (('PRESET_DIR', 'presets'), ('COVER_DIR', 'covers')):
    for f in set(os.listdir(getattr(A, d))) - before[d]:
        if f.endswith('.json'):
            shutil.copy(os.path.join(getattr(A, d), f), os.path.join(OUT, sub))
print('\n'.join(log))
