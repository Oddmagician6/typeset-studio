"""Update-check tests  (run: python test_update.py).

The check is the only thing in this app that touches the network, so what is
tested here is mostly what it *doesn't* do: never call out unless asked, never
raise, never let a hostile or broken feed reach the page. No test in this file
makes a real request — the fetcher is injected.
"""

import sys, os, io, json, time

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


SETTINGS_BACKUP = None
if os.path.exists(A.SETTINGS_PATH):
    SETTINGS_BACKUP = open(A.SETTINGS_PATH, encoding='utf-8').read()


def reset(**settings):
    A.save_settings(settings)


def feed(payload):
    """A fetcher that returns a canned document and records that it was called."""
    calls = []
    def fetch(url):
        calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload
    fetch.calls = calls
    return fetch


try:
    # ------------------------------------------------------------ version maths
    print('the version')
    check('the app knows its own version',
          A.APP_VERSION and A.APP_VERSION[0].isdigit(), A.APP_VERSION)
    check('it matches the VERSION file',
          A.APP_VERSION == open(os.path.join(HERE, 'VERSION'), encoding='utf-8').read().strip())
    check('1.10 is newer than 1.9, not older',      # the classic string-compare bug
          A.is_newer('1.10.0', '1.9.0') and not A.is_newer('1.9.0', '1.10.0'))
    check('a v prefix is ignored', not A.is_newer('v1.2.0', '1.2.0'))
    check('equal is not newer', not A.is_newer('1.2.0', '1.2.0'))
    check('a longer version wins on the tail', A.is_newer('1.2.1', '1.2'))
    check('nonsense sorts as nothing', not A.is_newer('', '1.2.0')
          and not A.is_newer('not-a-version', '1.2.0'))

    # ------------------------------------------------------------ consent
    print('asking first')
    reset()
    check('checks are off unless switched on', A.update_checks_on() is False)
    f = feed({'tag_name': 'v9.9.9', 'html_url': 'https://example.com/r'})
    check('and nothing is fetched while they are off',
          A.check_for_update(fetch=f) is None and not f.calls, f.calls)
    check('Check now still works, because it is an explicit ask',
          A.check_for_update(force=True, fetch=f) is not None and len(f.calls) == 1)

    reset(update_check=True)
    f = feed({'tag_name': 'v9.9.9', 'html_url': 'https://example.com/r'})
    info = A.check_for_update(fetch=f)
    check('once on, a newer release is reported',
          info and info['newer'] and info['version'] == 'v9.9.9', info)
    check('with the release page to go to', info['url'] == 'https://example.com/r')

    # ------------------------------------------------------------ the cache
    print('not asking twice')
    f2 = feed({'tag_name': 'v9.9.9', 'html_url': 'https://example.com/r'})
    again = A.check_for_update(fetch=f2)
    check('a second check inside the day is answered from the cache',
          not f2.calls and again and again['version'] == 'v9.9.9', f2.calls)
    check('forcing it asks anyway',
          A.check_for_update(force=True, fetch=f2) and len(f2.calls) == 1)
    s = A.load_settings()
    s['update_checked_at'] = time.time() - (A.UPDATE_INTERVAL + 60)
    A.save_settings(s)
    f3 = feed({'tag_name': 'v9.9.9', 'html_url': 'https://example.com/r'})
    A.check_for_update(fetch=f3)
    check('a day later it asks again', len(f3.calls) == 1)

    # ------------------------------------------------------------ bad feeds
    print('when the feed misbehaves')
    for label, payload in (
            ('a network error', ConnectionError('no route to host')),
            ('a timeout', TimeoutError('timed out')),
            ('html instead of json', 'not json at all'),
            ('an empty document', {}),
            ('a version that is not one', {'tag_name': 'latest-and-greatest'}),
            ('a version with markup in it', {'tag_name': '<script>alert(1)</script>'}),
    ):
        reset(update_check=True)
        got = A.check_for_update(fetch=feed(payload))
        check(f'{label} is silence, not an error', got is None, got)

    reset(update_check=True)
    got = A.check_for_update(fetch=feed({'tag_name': 'v9.9.9',
                                         'html_url': 'javascript:alert(1)'}))
    check('a non-https link is replaced with the real releases page',
          got and got['url'] == A.UPDATE_PAGE, got)

    reset(update_check=True)
    got = A.check_for_update(fetch=feed({'tag_name': 'v0.0.1',
                                         'html_url': 'https://example.com/old'}))
    check('an older release is reported as not newer', got and not got['newer'], got)

    # ------------------------------------------------------------ the pages
    print('the About page')
    A.app.config['TESTING'] = True
    client = A.app.test_client()
    reset()
    page = client.get('/about').get_data(as_text=True)
    check('it renders', 'Installed version' in page)
    check('and shows the running version', A.APP_VERSION in page)
    check('it says checking is off', 'Turn checking on' in page)
    check('and names exactly what would be sent where', A.UPDATE_FEED in page
          and 'no telemetry' in page)

    r = client.post('/about/updates', data={'update_check': '1'}, follow_redirects=True)
    check('the toggle turns it on', A.update_checks_on() is True)
    check('and says so', 'once a day' in r.get_data(as_text=True))
    r = client.post('/about/updates', data={}, follow_redirects=True)
    check('the toggle turns it off again', A.update_checks_on() is False)
    check('and forgets what it had learned',
          'update_latest' not in A.load_settings(), A.load_settings())
    check('and says nothing leaves the machine',
          'Nothing leaves this machine' in r.get_data(as_text=True))

    # the footer badge only appears when there is something to say
    reset(update_check=True, update_checked_at=time.time(),
          update_latest='99.0.0', update_url='https://example.com/r')
    check('the footer flags an available version',
          'is available' in client.get('/').get_data(as_text=True))
    reset(update_check=True, update_checked_at=time.time(),
          update_latest=A.APP_VERSION, update_url='https://example.com/r')
    check('and says nothing when you are current',
          'is available' not in client.get('/').get_data(as_text=True))
    reset()
    check('nor when checking is off',
          'is available' not in client.get('/').get_data(as_text=True))

    # a page render must never wait on the network, whatever the settings say
    reset(update_check=True)
    calls = []
    real = A._fetch_json
    A._fetch_json = lambda url, timeout=6: calls.append(url) or {'tag_name': 'v9.9.9'}
    try:
        client.get('/')
        first = len(calls)
        client.get('/')
        client.get('/generate')
        check('a page render asks at most once, then uses the cache',
              first <= 1 and len(calls) == first, calls)
    finally:
        A._fetch_json = real

    # ------------------------------------------------------------ the build
    print('one version, three readers')
    iss = open(os.path.join(HERE, 'typeset-studio.iss'), encoding='utf-8').read()
    check('the installer reads the VERSION file', 'FileRead(FileOpen("VERSION"))' in iss)
    bat = open(os.path.join(HERE, 'make-installer.bat'), encoding='utf-8').read()
    check('so does the build script', 'set /p APPVERSION=<VERSION' in bat)
    spec = open(os.path.join(HERE, 'typeset-studio.spec'), encoding='utf-8').read()
    check('and the spec, which also bundles it',
          "open('VERSION'" in spec and "('VERSION', '.')" in spec)
finally:
    if SETTINGS_BACKUP is not None:
        io.open(A.SETTINGS_PATH, 'w', encoding='utf-8', newline='').write(SETTINGS_BACKUP)
    elif os.path.exists(A.SETTINGS_PATH):
        os.remove(A.SETTINGS_PATH)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
