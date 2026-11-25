"""Upgrades and packaging  (run: python test_upgrades_bughunt.py).

Joint bug hunt, section 8. Each check is one way an upgrade, the installed
app or its update check went wrong, that the hunt found:

    8.2   (in test_fixed_layout.py) a picture book with no page designs flows
    8.3   with no WebView2, the app opens in the browser, not in IE's engine
    8.4   Setup refuses a build older than the VERSION file
    8.5   a start interrupted mid-copy leaves no half-seeded font or style
    8.6   epubcheck.jar beside the installed .exe is found
    8.7   a release list bigger than 200 KB is still read
    8.8   a check that lands after checking was turned off writes nothing
    8.9   a settings folder that can't be written doesn't break Check now
    8.10  on a shared feed a bare `v9.0.0` is somebody else's release
    8.11  a failed check retries after an hour, whenever the last success was
    8.12  the cover editor offers Standard colour paper
"""

import sys, os, io, json, time, shutil, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


SETTINGS_BACKUP = None
if os.path.exists(A.SETTINGS_PATH):
    SETTINGS_BACKUP = open(A.SETTINGS_PATH, encoding='utf-8').read()


def reset(**settings):
    A.save_settings(settings)


def ours(v):
    return {'tag_name': f'typeset-studio-v{v}', 'html_url': f'https://example.com/{v}'}


try:
    # ------------------------------------------------------------ 8.3
    print('the desktop window (8.3)')
    fake = types.ModuleType('webview.platforms.winforms')
    real_mod = sys.modules.get('webview.platforms.winforms')
    real_frozen, real_platform = A.IS_FROZEN, A.sys.platform
    try:
        import webview.platforms as wp
        real_attr = getattr(wp, 'winforms', None)
        sys.modules['webview.platforms.winforms'] = fake
        wp.winforms = fake
        A.IS_FROZEN = True
        A.sys.platform = 'win32'
        os.environ.pop('TS_NO_WINDOW', None)
        fake.renderer = 'mshtml'
        check('IE\'s engine: open in the browser instead', A._want_window() is False)
        fake.renderer = 'edgechromium'
        check('WebView2: the window', A._want_window() is True)
    finally:
        A.IS_FROZEN, A.sys.platform = real_frozen, real_platform
        if real_mod is not None:
            sys.modules['webview.platforms.winforms'] = real_mod
        else:
            sys.modules.pop('webview.platforms.winforms', None)
        if real_attr is not None:
            wp.winforms = real_attr
        elif hasattr(wp, 'winforms'):
            del wp.winforms

    # ------------------------------------------------------------ 8.4
    print('the installer (8.4)')
    bat = open(os.path.join(HERE, 'make-installer.bat'), encoding='utf-8').read()
    check('it reads the build\'s own VERSION',
          '_internal\\VERSION' in bat and 'set /p BUILTVERSION=' in bat)
    check('and stops when the two differ',
          'if not "%BUILTVERSION%"=="%APPVERSION%" goto STALE' in bat and ':STALE' in bat)

    # ------------------------------------------------------------ 8.5
    print('seeding the defaults (8.5)')
    tmp = tempfile.mkdtemp()
    src, dst = os.path.join(tmp, 'bundle'), os.path.join(tmp, 'data')
    os.makedirs(os.path.join(src, 'fonts')); os.makedirs(dst)
    open(os.path.join(src, 'fonts', 'New.ttf'), 'wb').write(b'x' * 1000)
    real_rp, real_df, real_copy = A.resource_path, A._data_folder, shutil.copy2
    try:
        A.resource_path = lambda *p: os.path.join(src, *p)
        A._data_folder = lambda name: dst
        def dies(s, d, *a, **k):
            open(d, 'wb').write(b'x' * 10)       # half a file, then the power goes
            raise OSError('interrupted')
        A.shutil.copy2 = dies
        A._seed_defaults()
        check('an interrupted copy leaves nothing under the real name',
              not os.path.exists(os.path.join(dst, 'New.ttf')), os.listdir(dst))
        check('nor a stray temporary file', os.listdir(dst) == [], os.listdir(dst))
        A.shutil.copy2 = real_copy
        A._seed_defaults()
        check('the next start copies it whole',
              os.path.getsize(os.path.join(dst, 'New.ttf')) == 1000)
    finally:
        A.resource_path, A._data_folder, A.shutil.copy2 = real_rp, real_df, real_copy
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------ 8.6
    print('epubcheck beside the program (8.6)')
    tmp = tempfile.mkdtemp()
    jar = os.path.join(tmp, 'epubcheck.jar')
    open(jar, 'wb').write(b'')
    real_exe, real_frozen = A.sys.executable, A.IS_FROZEN
    env = os.environ.pop('EPUBCHECK_JAR', None)
    try:
        A.sys.executable = os.path.join(tmp, 'Typeset Studio.exe')
        A.IS_FROZEN = True
        got = A._epubcheck_jar()
        check('the jar beside the .exe is found',
              got and os.path.samefile(got, jar), got)
    finally:
        A.sys.executable, A.IS_FROZEN = real_exe, real_frozen
        if env is not None:
            os.environ['EPUBCHECK_JAR'] = env
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------ 8.7
    print('a long release list (8.7)')
    big = [ours('1.0.0')] + [{'tag_name': f'other-v{i}', 'body': 'n' * 5000}
                             for i in range(60)]
    big.insert(0, ours('9.9.9'))
    payload = json.dumps(big).encode()

    class Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.request
    real_open = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda req, timeout=6: Resp(payload)
        got = A._fetch_json('https://example.com/feed')
        check('a feed past 200 KB is read whole',
              len(payload) > 200_000 and isinstance(got, list) and len(got) == len(big))
    finally:
        urllib.request.urlopen = real_open

    # ------------------------------------------------------------ 8.8
    print('turned off mid-check (8.8)')
    reset(update_check=True)
    def slow(url):
        # the user turns checking off while the request is out
        A.app.test_client().post('/about/updates', data={})
        return ours('9.9.9')
    got = A.check_for_update(fetch=slow)
    s = A.load_settings()
    check('the late answer is not written back',
          'update_latest' not in s and 'update_checked_at' not in s, s)
    check('and checking stays off', not A.update_checks_on())

    # ------------------------------------------------------------ 8.9
    print('a settings folder that can\'t be written (8.9)')
    reset(update_check=True)
    real_save, real_fetch = A.save_settings, A._fetch_json
    try:
        def full(data):
            raise OSError('disk full')
        A.save_settings = full
        got = A.check_for_update(force=True, fetch=lambda url: ours('9.9.9'))
        check('Check now still answers', got and got['version'] == '9.9.9', got)
        got = A.check_for_update(force=True, fetch=lambda url: None)
        check('and a failed check is still a quiet None', got is None)
        A._fetch_json = lambda url, timeout=6: ours('9.9.9')
        r = A.app.test_client().post('/about/check')
        check('the Check now button doesn\'t error', r.status_code in (200, 302), r.status_code)
    finally:
        A.save_settings, A._fetch_json = real_save, real_fetch

    # ------------------------------------------------------------ 8.10
    print('a shared feed (8.10)')
    shared = [{'tag_name': 'v9.0.0', 'html_url': 'https://example.com/other'},
              ours('1.14.0')]
    check('a bare tag beside ours is not ours',
          A._pick_release(shared) == ('1.14.0', 'https://example.com/1.14.0'),
          A._pick_release(shared))
    check('a feed of bare tags only still works (a repo of this app alone)',
          A._pick_release([{'tag_name': 'v1.2.0', 'html_url': 'https://e.com/a'},
                           {'tag_name': 'v1.3.0', 'html_url': 'https://e.com/b'}])
          == ('1.3.0', 'https://e.com/b'))
    check('as does a hand-written {"version": …}',
          A._pick_release({'version': '2.0.0', 'url': 'https://e.com/x'})
          == ('2.0.0', 'https://e.com/x'))

    # ------------------------------------------------------------ 8.11
    print('the retry after a failure (8.11)')
    now = time.time()
    reset(update_check=True, update_checked_at=now - 2 * 3600,
          update_failed_at=now - 3600 - 5, update_latest='1.0.0')
    check('an hour after a failed Check now, a check is due', A._update_due())
    reset(update_check=True, update_checked_at=now - 2 * 3600,
          update_failed_at=now - 60, update_latest='1.0.0')
    check('but not a minute after it', not A._update_due())
    reset(update_check=True, update_checked_at=now - 3600, update_latest='1.0.0')
    check('a success still holds for the day', not A._update_due())

    # ------------------------------------------------------------ 8.12
    print('the cover editor\'s paper (8.12)')
    html = open(os.path.join(HERE, 'templates', 'cover_editor.html'), encoding='utf-8').read()
    for key in A._PAPER:
        check(f'it offers {key}', f'<option value="{key}">' in html)
finally:
    if SETTINGS_BACKUP is not None:
        io.open(A.SETTINGS_PATH, 'w', encoding='utf-8', newline='').write(SETTINGS_BACKUP)
    elif os.path.exists(A.SETTINGS_PATH):
        os.remove(A.SETTINGS_PATH)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
