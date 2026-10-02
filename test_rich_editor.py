"""Rich-editor tests in a real browser  (run: python test_rich_editor.py).

The rich editor is a contenteditable surface, and most of what can go wrong in
one is the browser's doing — what Enter clones, what Backspace merges, what a
paste drops in — so it can only be tested by editing in a browser. This serves
the app on a background thread against throwaway folders, opens the real
manuscript editor in headless Chrome or Edge, and runs test_rich_editor.js.

Two things are checked:

    CORPUS     every manuscript survives a plain rich-mode round trip — the
               engine reads the same book before and after (the sample, a
               document with every feature, and any local manuscripts)
    SCENARIOS  each edit leaves the manuscript it should

Needs a Chromium browser; set TS_BROWSER to its path if it isn't found. Without
one the test says so and passes, so the suite still runs anywhere.
"""

import sys, os, json, glob, shutil, tempfile, threading, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

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


# Every block and inline feature, including the escapes a round trip must keep.
FEATURES = r'''=== Part One

# The Salt Road | Ellinor Vale

The *opening* paragraph with **bold**, ***both***, a [link](https://example.com/a_b?x=1) and a [*styled* link](#the-salt-road), and a note.[^a] Literal \*stars\* and \_unders\_ and \[^lit] and a back\\slash. "Quotes" and it's -- dashes... done. Mr.''' + ' ' + r'''Smith keeps his space.

## A *subhead* with a note[^b]

* * *

~~~ letter from="Ann" to="Bo" date="May 1"
Dear Bo,

It is *raining*.
~~~

~~~ poem title="Night"
First line of verse
second *line*[^b]

New stanza here
~~~

~~~ figure src="map.png" alt="A map" width="0.5"
The *caption*.
~~~

~~~ list type="number"
one item
two **items**
~~~

~~~ quote source="Someone"
A quoted passage.
~~~

~~~ center
Centered line
~~~

~~~ table caption="Sums" align="left,right"
Name | Value
A | **1**
~~~

\# Not a heading

\* * *

\~~~ not a fence

[^a]: The note text, citing[^b].
[^b]: Second.

#* Epilogue

The end.
'''

# What each scenario in test_rich_editor.js must leave in the manuscript.
EXPECT = {
    'enter-after-subhead': '# One\n\n## Sub\n\nNew text\n\nPara.\n',
    'type-in-empty': 'Hello\n',
    'shift-enter': '# One\n\nFirst half second half\n',
    'convert-bold-to-subhead': ('# One\n\n## Some **bold** and *it* and [a link](https://x.example) '
                                'and a note.[^a]\n\n[^a]: N.\n'),
    'convert-in-letter': '# One\n\n~~~ letter from="A"\nDear B,\n\nBody.\n~~~\n\nAfter.\n',
    'convert-in-poem': '# One\n\n~~~ poem title="T"\nverse one\nverse two\n~~~\n',
    'paste-divs': '# One\n\nBefore.\n\nPasted one.\n\nPasted two.\n',
    'paste-list': '# One\n\nBefore.\n\nalpha\n\nbeta\n',
    'paste-links': '# One\n\nBefore.rel and js and [ok](https://ok.example/)\n',
    'paste-styled-spans': '# One\n\nBefore.**heavy** *slanted*\n',
    'paste-heading': '# One\n\nBefore.\n\nPasted heading\n\nafter it\n',
    'paste-plain-lines': '# One\n\nBefore.\n\nline one wrapped here\n\nline two\n',
    'trailing-space': '# One\n\nWord\n',
    'space-after-note': '# One\n\nA note[^a] then more\n\n[^a]: N.\n',
    'space-after-link': '# One\n\nSee [this](https://x.example) then more\n',
    'double-space': '# One\n\nWord  two\n',
    'backspace-after-scene': '# One\n\nA.\n\nB.\n',
    'delete-before-scene': '# One\n\nA.\n\nB.\n',
    'backspace-mid-para-next-to-scene': '# One\n\nA.\n\n* * *\n\nBe.\n',
    'enter-end-of-list': '# One\n\n~~~ list\none\ntwo\nthree\n~~~\n',
    'enter-twice-end-of-letter': '# One\n\n~~~ letter from="A"\nDear B,\n~~~\n\noutside?\n',
    'exit-list': '# One\n\n~~~ list\none\ntwo\n~~~\n\noutside\n',
    'exit-caption': '# One\n\n~~~ figure src="m.png"\nCap.\n~~~\n\nafter\n',
    'poem-enter': '# One\n\n~~~ poem title="T"\nverse one\ninserted\nverse two\n~~~\n',
    'poem-stanza-then-exit': ('# One\n\n~~~ poem title="T"\nverse one\n\nstanza two\n~~~\n\n'
                              'after the poem\n'),
    'bold-button': '# One\n\nmake **this** bold please\n',
    'bold-across-note': '# One\n\n**make**[^a]** this** bold\n\n[^a]: N.\n',
    'figure-caption-enter': '# One\n\n~~~ figure src="m.png"\nCap one.\n\nCap two.\n~~~\n',
    'scene-button': '# One\n\nText.\n\n* * *\n\nAfter\n',
    'list-button-in-letter': '# One\n\n~~~ letter from="A"\nDear B,\n~~~\n\n~~~ list\nitem\n~~~\n',
    'paste-gdocs': '# One\n\nBefore.\n\n*It* was late.\n\n**Next** para.\n',
    'paste-word': '# One\n\nBefore.\n\nThe *first* paragraph.\n\n**Second** one.\n',
    'paste-mid-para': '# One\n\nStart middle one\n\nmiddle two end.\n',
    'paste-into-list': '# One\n\n~~~ list\none and more\nsecond item\nthird item\n~~~\n',
    'paste-into-title': '# OneTwo Three\n\nText.\n',
    'paste-over-selection': '# One\n\nKeep this *swapped* keep.\n',
    'paste-scene-from-editor': '# One\n\nBefore.Copied.\n\n* * *\n\nAfter [^a].\n',
    'paste-word-with-space': '# One\n\nSay hello and go.\n',
    'nbsp-survives': '# One\n\nMr. Smith came. Then left.\n',
    'nbsp-in-paste': '# One\n\nX.A B\n',
}


def main():
    browser = find_browser()
    if not browser:
        print('SKIP  no Chrome/Edge found (set TS_BROWSER to a Chromium browser)')
        print('\nALL PASS')
        return 0

    import app as A
    import manuscript
    from werkzeug.serving import make_server
    from flask import request

    tmp = tempfile.mkdtemp(prefix='ts-rich-')
    A.PROJECT_DIR = os.path.join(tmp, 'projects')
    A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
    A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
    A.OUT_DIR = os.path.join(tmp, 'out')
    A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
    for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.PROJECT_THUMB_DIR):
        os.makedirs(d)
    with open(os.path.join(A.PROJECT_MS_DIR, 'w.md'), 'w', encoding='utf-8') as f:
        f.write('# One\n\nStart.\n')
    with open(os.path.join(A.PROJECT_DIR, 'w.json'), 'w', encoding='utf-8') as f:
        json.dump({'name': 'W', 'title': 'W', 'preset': 'classic-literary',
                   'manuscript_file': 'w.md', 'manuscript_type': 'markdown',
                   'format': 'pdf'}, f)

    corpus = {'features': FEATURES}
    for p in [os.path.join(HERE, 'sample', 'sample.md')] + sorted(
            glob.glob(os.path.join(HERE, 'projects', 'manuscripts', '*.md'))):
        with open(p, encoding='utf-8') as f:
            corpus[os.path.relpath(p, HERE).replace(os.sep, '/')] = f.read()
    with open(os.path.join(HERE, 'test_rich_editor.js'), encoding='utf-8') as f:
        script = f.read()
    harness = ('<!doctype html><meta charset="utf-8">'
               '<iframe id="f" src="/project/w/write" style="width:1100px;height:900px"></iframe>'
               '<script>var CORPUS = ' + json.dumps(corpus) + ';\n' + script + '</script>')
    result = {}

    @A.app.route('/_rich_harness')
    def _rich_harness():
        return harness

    @A.app.route('/_rich_result', methods=['POST'])
    def _rich_result():
        result.update(json.loads(request.get_data(as_text=True)))
        return 'ok'

    server = make_server('127.0.0.1', 0, A.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-first-run',
                        '--user-data-dir=' + os.path.join(tmp, 'browser'),
                        '--virtual-time-budget=60000', '--dump-dom',
                        f'http://127.0.0.1:{server.server_port}/_rich_harness'],
                       capture_output=True, timeout=300)
    finally:
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    if not result:
        check('the browser ran the harness', False, browser)
        return 1

    print('[corpus: a rich-mode round trip reads as the same book]')
    for name, md in corpus.items():
        after = result['roundtrip'].get(name)
        same = after is not None and all(
            manuscript.parse_markdown(md, smartquotes=s)
            == manuscript.parse_markdown(after, smartquotes=s) for s in (True, False))
        check(name, same)
    check('the marked non-breaking space survives',
          'Mr. Smith' in result['roundtrip'].get('features', ''))

    print('\n[scenarios]')
    got = result['scenarios']
    for name, want in EXPECT.items():
        have = got.get(name)
        check(name, have == want, f'\n         want {want!r}\n         got  {have!r}')
    extra = set(got) - set(EXPECT)
    check('every scenario has an expectation', not extra, sorted(extra))
    return 0 if not fails else 1


if __name__ == '__main__':
    code = main()
    print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
    sys.exit(code)
