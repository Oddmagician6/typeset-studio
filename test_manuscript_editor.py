"""Manuscript editor tests  (run: python test_manuscript_editor.py).

Bug hunt item 2: the writing page beyond rich mode's own editing, which
test_rich_editor.py covers. Two halves:

    SERVER   the save route as the page uses it: a whole novel in one request,
             a save from an out-of-date copy (refused, and kept in History),
             the writer's choice to keep it anyway, a request without text
    BROWSER  the real page in headless Chrome or Edge, one throwaway book per
             scenario (test_manuscript_editor.js): the ways out of the page with
             unsaved work, the same book in two tabs, a failed save, mode
             switching mid-edit, restoring over unsaved work, the preview, the
             Markdown toolbar, find in rich mode, awkward text, word counts

Needs a Chromium browser for the second half; set TS_BROWSER to its path if it
isn't found. Without one that half says so and is skipped.
"""

import sys, os, glob, json, time, shutil, tempfile, threading, subprocess

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


def find_browser():
    cands = [os.environ.get('TS_BROWSER', '')]
    for exe in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
                'chrome', 'msedge', 'microsoft-edge'):
        cands.append(shutil.which(exe) or '')
    for base in (os.environ.get('PROGRAMFILES', ''), os.environ.get('PROGRAMFILES(X86)', ''),
                 os.environ.get('LOCALAPPDATA', '')):
        if base:
            cands += [os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                      os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')]
    cands += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    return next((c for c in cands if c and os.path.isfile(c)), None)


def use_folders(tmp):
    A.PROJECT_DIR = os.path.join(tmp, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(tmp, 'out')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.PROJECT_THUMB_DIR):
        os.makedirs(d, exist_ok=True)


def make_book(pid, text):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8',
              newline='') as f:
        f.write(text)
    with open(os.path.join(A.PROJECT_DIR, pid + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': pid, 'title': pid, 'preset': 'classic-literary',
                   'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
                   'format': 'pdf'}, f)


def disk(pid):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), encoding='utf-8',
              newline='') as f:
        return f.read()


def snapshots(pid, reason=None):
    return [A.read_snapshot(pid, s['stamp']) for s in A.list_snapshots(pid)
            if reason is None or s['reason'] == reason]


# a long novel: ~150,000 words with curly quotes, past Flask's 500 KB default
PARA = ('“The quick brown fox,” she said, “jumps over the lazy dog '
        'and keeps on running for a good while yet.” ') * 6 + '\n\n'
NOVEL = ''.join(f'# Chapter {i}\n\n' + PARA * 40 for i in range(1, 50))

ODD = ('\n\n# Odd — été\n\n'
       'Tabs\there, a non' + chr(0xA0) + 'breaking space, an emoji \U0001F56F, and '
       '</textarea><b>not bold</b> {{ not jinja }} &amp; &lt;.\n\n'
       '<script>alert(1)</script>\n\n'
       '   leading spaces kept\n\n\n\nthree blank lines above\n')

CYRILLIC = ('# Глава\n\nПривет мир, '
            'это тест — кто-то.\n')


# The harness's own routes. Flask takes no new routes once it has served a
# request, so these are set up before either half runs.
from flask import request as _rq
RESULT, SEEN = {}, {}


@A.app.before_request
def _record():
    # what is on disk when a way out of the editor reaches the app
    parts = _rq.path.strip('/').split('/')
    if len(parts) == 3 and parts[0] == 'project' and parts[2] in ('generate', 'edit')             and parts[1] in ('typeset', 'settings'):
        SEEN[parts[1]] = disk(parts[1])


@A.app.route('/_ed_harness')
def _ed_harness():
    with open(os.path.join(HERE, 'test_manuscript_editor.js'), encoding='utf-8') as f:
        return '<!doctype html><meta charset="utf-8"><body><script>' + f.read() + '</script>'


@A.app.route('/_ed_local')
def _ed_local():
    with open(os.path.join(A.PROJECT_DIR, '_local.json')) as f:
        return f.read()


@A.app.route('/_ed_disk/<pid>')
def _ed_disk(pid):
    return disk(pid)


@A.app.route('/_ed_result', methods=['POST'])
def _ed_result():
    RESULT.update(json.loads(_rq.get_data(as_text=True)))
    return 'ok'


def server_half():
    print('[server: the save route]')
    c = A.app.test_client()
    make_book('s', '# One\n\nStart.\n')
    rev = A._ms_rev(disk('s'))

    r = c.post('/project/s/write/save', data={'text': NOVEL, 'base': rev})
    check(f'a {len(NOVEL.encode()) // 1024} KB novel saves', r.status_code == 200
          and disk('s') == NOVEL, r.status_code)
    rev = r.get_json()['rev']
    check('and the rev it hands back is the text on disk', rev == A._ms_rev(disk('s')))
    r = c.post('/project/s/write/preview', data={'text': NOVEL})
    check('and previews', r.status_code == 200 and r.get_json()['ok'], r.status_code)

    c.post('/project/s/write/save', data={'text': '# One\n\nTab one.\n', 'base': rev})
    r = c.post('/project/s/write/save', data={'text': '# One\n\nTab two.\n', 'base': rev})
    check('a save from an out-of-date copy is refused', r.status_code == 409
          and r.get_json()['conflict'] and disk('s') == '# One\n\nTab one.\n')
    check('and what it sent is kept in History',
          '# One\n\nTab two.\n' in snapshots('s', 'conflict'))
    r = c.post('/project/s/write/save', data={'text': '# One\n\nTab one.\n', 'base': rev})
    check('the same text from an old copy is no clash', r.status_code == 200)
    r = c.post('/project/s/write/save', data={'text': '# One\n\nTab two.\n', 'base': rev,
                                              'overwrite': '1'})
    check('keeping it anyway saves it', r.status_code == 200
          and disk('s') == '# One\n\nTab two.\n')
    check('and keeps what it replaced', '# One\n\nTab one.\n' in snapshots('s', 'overwritten'))
    r = c.post('/project/s/write/save', data={'text': '# One\n\nOld page.\n'})
    check('a page from before revisions still saves', r.status_code == 200
          and disk('s') == '# One\n\nOld page.\n')
    r = c.post('/project/s/write/save', data={'base': A._ms_rev(disk('s'))})
    check('a request without text writes nothing', r.status_code == 400
          and disk('s') == '# One\n\nOld page.\n')

    rev = A._ms_rev(disk('s'))
    stamp = A.list_snapshots('s')[-1]['stamp']
    j = c.post(f'/project/s/history/{stamp}/restore').get_json()
    check('a restore hands back the new rev', j['rev'] == A._ms_rev(disk('s')) != rev)
    page = c.get('/project/s/write').get_data(as_text=True)
    check('the page carries the rev of what it shows', A._ms_rev(disk('s')) in page)


def browser_half(tmp):
    print('\n[browser: the page]')
    browser = find_browser()
    if not browser:
        print('SKIP  no Chrome/Edge found (set TS_BROWSER to a Chromium browser)')
        return
    from werkzeug.serving import make_server

    small = '# One\n\nStart.\n'
    for pid in ('table', 'find', 'richleave', 'mdleave', 'richswitch', 'tabs',
                'typeset', 'settings', 'retry', 'modes', 'restore', 'preview'):
        make_book(pid, small)
    make_book('big', '# One\n\n' + 'Some words in a long book. ' * 4000 + '\n')
    make_book('odd', ODD)
    make_book('cyr', CYRILLIC)
    make_book('novel', NOVEL)
    make_book('oddhl', ODD)
    with open(os.path.join(HERE, 'sample', 'sample.md'), encoding='utf-8') as f:
        make_book('sample', f.read())
    # and copies of any local manuscripts, for the highlighting check
    local = []
    for i, path in enumerate(sorted(glob.glob(os.path.join(HERE, 'projects', 'manuscripts',
                                                           '*.md')))):
        with open(path, encoding='utf-8', errors='replace') as f:
            make_book(f'local{i}', A._norm_newlines(f.read()))
        local.append(f'local{i}')
    with open(os.path.join(A.PROJECT_DIR, '_local.json'), 'w') as f:
        json.dump(local, f)
    A.snapshot_manuscript('restore', '# One\n\nAn older draft.\n', force=True)
    # make it look older than the autosave interval, so the next save keeps one too
    folder = A._history_folder('restore')
    for fn in os.listdir(folder):
        os.rename(os.path.join(folder, fn), os.path.join(folder, '20200101-000000-edit.md'))

    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # Real time, not --virtual-time-budget: under virtual time the page's
        # animation frames never come, and it paints its highlighting in them.
        proc = subprocess.Popen([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                                 '--remote-debugging-port=0',
                                 '--user-data-dir=' + os.path.join(tmp, 'browser'),
                                 f'http://127.0.0.1:{server.server_port}/_ed_harness'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(600):
                if RESULT:
                    break
                time.sleep(0.5)
        finally:
            proc.kill()
            proc.wait()
    finally:
        server.shutdown()

    result, seen = RESULT, SEEN
    if not result:
        check('the browser ran the harness', False, browser)
        return
    if result.get('error'):
        check('the harness ran to the end', False, result['error'])
    R = result

    check('Markdown mode: the Table button inserts a table',
          '~~~ table\nColumn | Column\n' in disk('table'))
    check('rich mode: Ctrl+F finds what was just typed', R.get('find_count') == '– / 1',
          R.get('find_count'))
    check('and switches to Markdown, where find works', R.get('find_rich') is False)

    check('rich edit, then leaving at once: kept', 'RICHQUICK' in disk('richleave'))
    check('Markdown edit, then leaving at once: kept', 'MDQUICK' in disk('mdleave'))
    check('rich edit, to Markdown, leaving at once: kept', 'SWITCHQUICK' in disk('richswitch'))
    check('a book too big to send while closing asks before leaving', R.get('guard_big') is True)
    check('and asks nothing once saved', R.get('guard_clean') is False)
    check('and the edit was saved', 'BIGTAIL' in disk('big'))

    check('Typeset saves first', 'TYPESETNOW' in seen.get('typeset', ''), seen.get('typeset'))
    check('Book settings saves first', 'SETTINGSNOW' in seen.get('settings', ''))

    check('two tabs: the second, out of date, shows the clash', R.get('tabs_banner') is True)
    check('and has not written over the first', R.get('tabs_disk_after_clash') ==
          small + '\nTAB-ONE\n', R.get('tabs_disk_after_clash'))
    check('its text is kept in History', any(
        t and 'TAB-TWO' in t for t in snapshots('tabs', 'conflict')))
    check('the first tab saves on as before', R.get('tabs_one_more') is True)
    check('"Keep this version" saves the second tab\'s text', R.get('tabs_mine') is True)
    check('and keeps the text it replaced', any(
        t and 'MORE-ONE' in t for t in snapshots('tabs', 'overwritten')))
    check('the first tab, now behind, shows the clash in turn', R.get('tabs_one_banner') is True)
    check('"Open the saved version" shows the disk', R.get('tabs_loaded') is True,
          R.get('tabs_loaded_text'))
    check('and what that tab had typed since is in History', any(
        t and 'AGAIN' in t for t in snapshots('tabs', 'conflict')))

    check('a failed save says so', 'Not saved' in (R.get('retry_status') or ''),
          R.get('retry_status'))
    check('and is tried again', 'RETRYME' in disk('retry'))

    check('Markdown, then rich, then back: both edits saved',
          'MD-EDIT' in disk('modes') and 'RICH-EDIT' in disk('modes'), disk('modes'))
    check('restoring with unsaved work: the older draft is back',
          disk('restore') == '# One\n\nAn older draft.\n', disk('restore'))
    check('and the unsaved work is in History', any(
        t and 'UNSAVED' in t for t in snapshots('restore')))
    check('the preview shows the unsaved text', '2 chapters' in (R.get('preview') or ''),
          R.get('preview'))

    check('awkward text opens as it is on disk', R.get('odd_same') is True,
          R.get('odd_text'))
    check('and an edit undone saves it back unchanged', disk('odd') == ODD,
          repr(disk('odd')))
    for pid, (h1, t1, h2, t2, same) in (R.get('aligned') or {}).items():
        check(f'{pid}: the highlighting lines up with the text, opened and edited',
              abs(h1 - t1) <= 1 and abs(h2 - t2) <= 1 and same, (h1, t1, h2, t2, same))
    check('the highlighting was checked', len(R.get('aligned') or {}) == 3 + len(local))
    want = A._wordcount(CYRILLIC + ' ещё')
    check('Cyrillic words are counted as the server counts them',
          R.get('cyr_words') == str(want), (R.get('cyr_words'), want))


def main():
    tmp = tempfile.mkdtemp(prefix='ts-editor-')
    try:
        use_folders(tmp)
        server_half()
        browser_half(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
