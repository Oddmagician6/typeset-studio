"""Rebuild all tests  (run: python test_rebuild.py).

Rebuild all walks the projects page one book at a time through
/project/<pid>/rebuild, so what matters is that endpoint: it builds a book the
way Regenerate does, records the build on the project, answers in JSON a page
can show, and a book that can't be built says why without taking the rest of
the batch down with it.
"""

import sys, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


# secure_filename strips a leading underscore, so these ids carry none
GOOD, BAD, PDF_ONLY = 'test-rebuild-good', 'test-rebuild-bad', 'test-rebuild-pdf'
MS_FILE = 'test-rebuild-good.md'
MS = ('# The Salt Road\n\nThe opening paragraph, long enough to set a real line of '
      'body text across the measure.[^a]\n\n[^a]: A note.\n\n# The Second Mile\n\n'
      'Another chapter.\n')
BASE = {'preset': 'classic-literary', 'author': 'Ellinor Vale', 'front_matter': 'full',
        'manuscript_type': 'file', 'cover_mode': 'none'}
PROJECTS = {
    GOOD:     dict(BASE, name='Rebuild good', title='Rebuild Good Book',
                   manuscript_file=MS_FILE, format='both'),
    PDF_ONLY: dict(BASE, name='Rebuild pdf', title='Rebuild Pdf Book',
                   manuscript_file=MS_FILE, format='pdf'),
    BAD:      dict(BASE, name='Rebuild bad', title='Rebuild Bad Book',
                   manuscript_file='test-rebuild-missing.md', format='pdf'),
}


def path_of(pid):
    return os.path.join(A.PROJECT_DIR, pid + '.json')


def outputs():
    return {f for f in os.listdir(A.OUT_DIR)
            if f.startswith('rebuild-') and f.endswith(('.pdf', '.epub'))}


def cleanup():
    for pid in PROJECTS:
        for p in (path_of(pid), os.path.join(A.PROJECT_THUMB_DIR, pid + '.png')):
            if os.path.exists(p):
                os.remove(p)
    ms = os.path.join(A.PROJECT_MS_DIR, MS_FILE)
    if os.path.exists(ms):
        os.remove(ms)
    for f in outputs():
        os.remove(os.path.join(A.OUT_DIR, f))


cleanup()
before = outputs()
with open(os.path.join(A.PROJECT_MS_DIR, MS_FILE), 'w', encoding='utf-8') as f:
    f.write(MS)
for pid, proj in PROJECTS.items():
    A.save_project_file(pid, proj)
client = A.app.test_client()

try:
    print('[a book that builds]')
    j = client.post(f'/project/{GOOD}/rebuild').get_json()
    check('answers ok', j and j['ok'], j)
    check('reports its page count', j['pages'] > 0, j)
    check('links the PDF and the EPUB', j['pdf'].endswith('.pdf') and j['epub'].endswith('.epub'), j)
    check('both files download', all(client.get(u).status_code == 200 for u in (j['pdf'], j['epub'])))
    check('links a thumbnail that renders',
          client.get(j['thumb']).status_code == 200, j['thumb'])
    saved = json.load(open(path_of(GOOD), encoding='utf-8'))
    check('the build is recorded on the project',
          j['pdf'].endswith(saved['last_pdf']) and j['epub'].endswith(saved['last_epub'])
          and saved['last_page_count'] == j['pages'], saved)
    check('issues and warnings are lists of text',
          isinstance(j['issues'], list) and isinstance(j['warnings'], list)
          and all(isinstance(x, str) for x in j['issues'] + j['warnings']), j)

    print('\n[a project set to PDF only]')
    j = client.post(f'/project/{PDF_ONLY}/rebuild').get_json()
    check('builds the PDF and no EPUB', j['ok'] and j['pdf'] and not j['epub'], j)

    print('\n[a book that cannot be built]')
    raw_before = open(path_of(BAD), encoding='utf-8').read()
    j = client.post(f'/project/{BAD}/rebuild').get_json()
    check('answers not ok, with the reason', j and not j['ok'] and 'not found' in j['error'], j)
    check('the project is left untouched',
          open(path_of(BAD), encoding='utf-8').read() == raw_before)
    j = client.post('/project/test-rebuild-nonexistent/rebuild').get_json()
    check('a project that does not exist answers in JSON too', j and not j['ok'], j)

    print('\n[the page and Regenerate]')
    page = client.get('/projects').get_data(as_text=True)
    check('the projects page has the button', 'id="rebuild-all"' in page)
    check('each card carries its project id', f'data-pid="{GOOD}"' in page)
    r = client.post(f'/project/{GOOD}/generate')
    check('Regenerate still shows its result page',
          r.status_code == 200 and 'Rebuild Good Book' in r.get_data(as_text=True), r.status_code)
    r = client.post(f'/project/{BAD}/generate')
    check('Regenerate still sends a failure back to the projects page',
          r.status_code == 302 and r.headers['Location'].endswith('/projects'), r.status_code)
finally:
    cleanup()

check('no stray output left behind', outputs() == before, outputs() - before)
print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
