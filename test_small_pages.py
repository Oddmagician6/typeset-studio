"""The small pages  (run: python test_small_pages.py).

Bug hunt item 11: pages with a route each and little else testing them. No test
here touches the network or Anthropic; fetchers and the Claude call are stubbed.

    CONTINUITY  the report reads the book the way the editor and builds do; a
                name misspelt late in a long book is found (only the first 200
                capitalised words were ever compared), quickly; Claude's half
                runs only when asked on the page, never because a key is set
    ABOUT       no page waits on the update feed: a due check runs in its own
                thread; a failed one (offline) is remembered, not retried by
                every page; Check now still asks and says what it found
    SPECS       the cover specs page and its template PDF at the extremes a style
                may now have (2" to 20" trims), every binding and retailer
"""

import sys, os, io, json, time, random, difflib, shutil, tempfile, threading, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import checker, manuscript

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-small-')
A.PRESET_DIR = os.path.join(tmp, 'presets')
A.PROJECT_DIR = os.path.join(tmp, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.SETTINGS_PATH = os.path.join(tmp, 'settings.json')
for d in (A.PRESET_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR):
    os.makedirs(d)
shutil.copy(os.path.join(HERE, 'presets', 'classic-literary.json'), A.PRESET_DIR)
A.app.config['TESTING'] = True
client = A.app.test_client()


def book(pid, text, **extra):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8') as f:
        f.write(text)
    A.save_project_file(pid, dict({'name': pid, 'title': pid.title(), 'preset': 'classic-literary',
                                   'manuscript_type': 'file', 'manuscript_file': pid + '.md'},
                                  **extra))


def report(pid, **form):
    return client.post(f'/project/{pid}/continuity', data=form, follow_redirects=True)


claude_calls = []
real_tier2 = checker.run_tier2
def fake_tier2(parsed, key):
    claude_calls.append(len(parsed['chapters']))
    return []


try:
    print('[CONTINUITY: the report]')
    random.seed(3)
    filler = ('the river ran cold under grey light and nobody spoke of it again '
              'until morning came over the hills').split()
    places = [''.join(random.choice('aeioulnrst') for _ in range(6)).capitalize()
              for _ in range(400)]
    chapters = []
    for i in range(30):
        paras = []
        for _ in range(20):
            words = [random.choice(filler) for _ in range(40)]
            for k in (5, 12, 30):                 # 400 capitalised words, used up early
                words[k] = random.choice(places)
            words[20] = 'Marguerite' if i < 25 else 'Marguerete'
            paras.append(' '.join(words) + '.')
        chapters.append(f'# Chapter {i + 1}\n\n' + '\n\n'.join(paras))
    book('long', '\n\n'.join(chapters))
    t = time.time()
    r = report('long')
    took = time.time() - t
    page = r.get_data(as_text=True)
    check('the report renders', r.status_code == 200 and 'Continuity Report' in page)
    check('a name misspelt in chapter 26 of 30 is found',
          'Marguerite' in page and 'Marguerete' in page, page[:0])
    check(f'... in a few seconds ({took:.1f}s)', took < 5)

    random.seed(5)
    words = sorted({''.join(random.choice('aeiourstlnmk') for _ in range(random.randint(3, 15)))
                    .capitalize() for _ in range(600)})
    words += [w[:-1] + 'x' for w in words[:150]] + [w + 'e' for w in words[150:300]]
    brute = {tuple(sorted((a, b))) for i, a in enumerate(words) for b in words[i + 1:]
             if a.lower() != b.lower()
             and difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.85}
    fast = {tuple(sorted(p)) for p in checker._similar_pairs(words, 0.85)}
    check(f'the quick search finds exactly what comparing every pair finds ({len(brute)})',
          fast == brute, sorted(fast ^ brute)[:5])

    letters = 'bcdfghjklmnpqrstvwxz'
    names = [f'Ka{x}{y}ton' for x in letters[:8] for y in letters[:8]]      # 64 names
    many = '# One\n\n' + ' '.join(f'{n} met {n}e and {n} met {n}e.' for n in names)
    issues = checker._check_name_variants(manuscript.parse_markdown(many))
    check('a long list of variants is cut short and says how many more',
          len(issues) == checker._MAX_VARIANTS + 1 and issues[-1]['severity'] == 'info'
          and issues[-1]['label'].endswith('more name variants'), [i['label'] for i in issues[-2:]])

    book('sampled', '', manuscript_type='sample', manuscript_file='')
    check('a book on the sample text is checked', 'Continuity Report' in
          report('sampled').get_data(as_text=True))
    book('blank', '   \n\n')
    check('a book with no text says so', 'no text yet' in report('blank').get_data(as_text=True))
    book('gone', 'x')
    os.remove(os.path.join(A.PROJECT_MS_DIR, 'gone.md'))
    check('a book whose file is gone says so',
          'Manuscript file not found' in report('gone').get_data(as_text=True))
    with open(os.path.join(A.PROJECT_MS_DIR, 'accents.md'), 'wb') as f:
        f.write('# Café\n\nZoë met Zoë.\n\n# Café\n\nAgain.\n'.encode('cp1252'))
    A.save_project_file('accents', {'name': 'accents', 'title': 'Accents',
                                    'preset': 'classic-literary', 'manuscript_type': 'file',
                                    'manuscript_file': 'accents.md'})
    check('a Windows-1252 manuscript reads as written (the shared reader)',
          'Café' in report('accents').get_data(as_text=True))

    print('\n[CONTINUITY: Claude only when asked]')
    checker.run_tier2 = fake_tier2
    old_key = os.environ.pop('ANTHROPIC_API_KEY', None)
    try:
        page = report('long', ask_claude='1').get_data(as_text=True)
        check('no key: nothing is sent, even if asked', not claude_calls)
        check('... and the page says how to enable it', 'ANTHROPIC_API_KEY' in page)
        os.environ['ANTHROPIC_API_KEY'] = 'test-key'
        page = report('long').get_data(as_text=True)
        check('a key alone sends nothing', not claude_calls, claude_calls)
        check('... the page offers it, saying what is sent',
              'Ask Claude as well' in page and 'first 150 words' in page and '30' in page)
        page = report('long', ask_claude='1').get_data(as_text=True)
        check('pressing the button runs it once', claude_calls == [30], claude_calls)
        check('... and the button is gone', 'Ask Claude as well' not in page)
    finally:
        checker.run_tier2 = real_tier2
        if old_key is None:
            os.environ.pop('ANTHROPIC_API_KEY', None)
        else:
            os.environ['ANTHROPIC_API_KEY'] = old_key

    seen = {}
    class FakeClient:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = self
        def create(self, **kw):
            blocks = [types.SimpleNamespace(type='thinking', thinking='…'),
                      types.SimpleNamespace(type='text', text='```json\n[{"label": "Eye colour", '
                                            '"detail": "blue then brown", "location": "1 vs 2"}]\n```')]
            return types.SimpleNamespace(content=blocks)
    real_mod = sys.modules.get('anthropic')
    sys.modules['anthropic'] = types.SimpleNamespace(Anthropic=FakeClient)
    try:
        got = checker.run_tier2(manuscript.parse_markdown('# A\n\nText.'), 'k')
    finally:
        if real_mod is None:
            sys.modules.pop('anthropic', None)
        else:
            sys.modules['anthropic'] = real_mod
    check('the reply is read from its text block, wherever it is',
          len(got) == 1 and got[0]['label'] == 'Eye colour', got)
    check('the call has a timeout and one retry', seen.get('timeout') == 60.0
          and seen.get('max_retries') == 1, seen)

    print('\n[ABOUT: no page waits on the feed]')
    calls = []
    def slow_feed(url):
        calls.append(time.time())
        time.sleep(2.5)
        return {'tag_name': 'v99.0.0', 'html_url': 'https://example.com/r'}
    real_fetch = A._fetch_json
    A._fetch_json = slow_feed
    try:
        A.save_settings({'update_check': True})
        t = time.time()
        page = client.get('/about').get_data(as_text=True)
        check(f'a due check doesn\'t hold up the page ({time.time() - t:.2f}s)', time.time() - t < 1.5)
        client.get('/')
        client.get('/covers')
        time.sleep(3.2)
        check('... it ran once, in its own thread', len(calls) == 1, len(calls))
        check('... and the next page has its answer',
              'is available' in client.get('/').get_data(as_text=True))

        def offline(url):
            calls.append(time.time())
            raise OSError('offline')
        A._fetch_json = offline
        calls.clear()
        A.save_settings({'update_check': True})
        for _ in range(4):
            client.get('/')
            time.sleep(0.3)
        check('offline: one try, remembered, not one per page', len(calls) == 1, len(calls))
        check('... the failure is recorded', 'update_failed_at' in A.load_settings())
        s = A.load_settings()
        s['update_failed_at'] = time.time() - A.UPDATE_RETRY - 5
        A.save_settings(s)
        client.get('/')
        time.sleep(0.5)
        check('... and tried again an hour later', len(calls) == 2, len(calls))

        A._fetch_json = lambda url: {'tag_name': 'v0.0.1', 'html_url': 'https://example.com/r'}
        r = client.post('/about/check', follow_redirects=True).get_data(as_text=True)
        check('Check now asks and says you are up to date', 'You are up to date' in r)
        A._fetch_json = offline
        r = client.post('/about/check', follow_redirects=True).get_data(as_text=True)
        check('Check now offline says it couldn\'t reach the feed', 'Could not reach' in r)
        r = client.post('/about/updates', data={}, follow_redirects=True)
        check('turning checks off forgets the failure too',
              'update_failed_at' not in A.load_settings(), A.load_settings())
    finally:
        A._fetch_json = real_fetch

    print('\n[SPECS: the cover specs at the extremes]')
    base = A.load_preset('classic-literary')
    bad = []
    for w, h in [(2.0, 2.0), (20.0, 20.0), (2.0, 20.0), (8.25, 11.0)]:
        A.save_preset('edge', dict(base, trim={'w': w, 'h': h}, name=f'Ünïcode “{w}”'))
        for binding in A._BINDINGS:
            for retailer in A.WRAP_RETAILERS:
                for pages in (1, 2000):
                    q = f'?pages={pages}&binding={binding}&retailer={retailer}'
                    for url in ('/style/edge/cover-specs' + q, '/style/edge/cover-specs/template.pdf' + q):
                        r = client.get(url)
                        if r.status_code != 200:
                            bad.append((r.status_code, w, h, url))
    check('every page and template PDF is made', not bad, bad[:4])
    r = client.get('/style/edge/cover-specs/template.pdf')
    check('the download name is plain ASCII', r.headers['Content-Disposition'].isascii(),
          r.headers['Content-Disposition'])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
