"""EPUB self-check tests  (run: python test_epub.py).

No test framework, like test_doc_model.py. Builds one good EPUB, asserts it
passes every check, then breaks it in each way `epub.check` claims to notice and
asserts the matching check fails. A validator that cannot fail is worthless, so
the negative cases are the point of this file.
"""

import sys, os, json, zipfile, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)
import epub, manuscript
from PIL import Image

BASE = HERE
TMP = tempfile.mkdtemp()
epub.FIGURE_DIR = TMP
Image.new('RGB', (400, 300), (60, 90, 130)).save(os.path.join(TMP, 'plate.png'))

TEXT = '''# One

Text with a link to [chapter two](#two) and a plate.

~~~ figure src="plate.png" alt="A plate"
The caption.
~~~

# Two

Done.
'''
ms = manuscript.parse_markdown(TEXT, smartquotes=True)
preset = json.load(open(os.path.join(BASE, 'presets', 'classic-literary.json'), encoding='utf-8'))
meta = {'title': 'T', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light',
        **{k: '' for k in ('dedication', 'epigraph', 'foreword', 'preface', 'introduction',
                           'afterword', 'bibliography', 'acknowledgments', 'contributors',
                           'about_author', 'also_by', 'blurbs')}}
GOOD = os.path.join(TMP, 'good.epub')
epub.build_epub(ms, preset, GOOD, meta)

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond: fails.append(name)

def result(path):
    return {c['label']: c for c in epub.check(path)}

# ---- the healthy file ----
r = result(GOOD)
check('a good EPUB passes every check', all(c['ok'] for c in r.values()),
      [k for k, c in r.items() if not c['ok']])
check('the image check ran at all', 'Image alt text' in r, sorted(r))

def mutate(label, fn):
    """Rebuild the zip with fn(name, data) -> (name, data) | None (drop)."""
    dst = os.path.join(TMP, label + '.epub')
    with zipfile.ZipFile(GOOD) as src, zipfile.ZipFile(dst, 'w') as out:
        for i in src.infolist():
            data = src.read(i.filename)
            res = fn(i.filename, data)
            if res is None:
                continue
            n2, d2 = res
            out.writestr(zipfile.ZipInfo(n2), d2,
                         compress_type=(zipfile.ZIP_STORED if n2 == 'mimetype'
                                        else zipfile.ZIP_DEFLATED))
    return result(dst)

# ---- each break must be caught ----
r = mutate('nomime', lambda n, d: None if n == 'mimetype' else (n, d))
check('missing mimetype is caught', not r['Container']['ok'], r['Container'])

r = mutate('nodoc', lambda n, d: None if n.endswith('chapter002.xhtml') else (n, d))
check('a manifested file that is missing is caught', not r['Manifest']['ok'], r['Manifest'])

r = mutate('stray', lambda n, d: (n, d))
with zipfile.ZipFile(os.path.join(TMP, 'stray.epub'), 'a') as z:
    z.writestr('OEBPS/orphan.xhtml', '<html/>')
r = result(os.path.join(TMP, 'stray.epub'))
check('an undeclared file is caught', not r['No stray files']['ok'], r['No stray files'])

r = mutate('badxml', lambda n, d: (n, b'<html><body><p>unclosed') if n.endswith('chapter001.xhtml') else (n, d))
check('malformed XHTML is caught', not r['Content documents']['ok'], r['Content documents'])

r = mutate('noalt', lambda n, d: (n, d.replace(b'alt="A plate"', b'alt=""'))
           if n.endswith('chapter001.xhtml') else (n, d))
check('a missing alt is caught', not r['Image alt text']['ok'], r['Image alt text'])

r = mutate('dangling', lambda n, d: (n, d.replace(b'href="chapter002.xhtml"', b'href="chapter999.xhtml"'))
           if n.endswith('chapter001.xhtml') else (n, d))
check('a dangling link is caught', not r['Internal links']['ok'], r['Internal links'])

r = mutate('badfrag', lambda n, d: (n, d.replace(b'href="chapter002.xhtml"', b'href="chapter002.xhtml#nope"'))
           if n.endswith('chapter001.xhtml') else (n, d))
check('a dangling fragment is caught', not r['Internal links']['ok'], r['Internal links'])

r = mutate('nonav', lambda n, d: (n, d.replace(b' properties="nav"', b''))
           if n.endswith('content.opf') else (n, d))
check('a missing nav declaration is caught', not r['Navigation']['ok'], r['Navigation'])

r = mutate('badspine', lambda n, d: (n, d.replace(b'idref="ch001"', b'idref="ghost"'))
           if n.endswith('content.opf') else (n, d))
check('a bad spine idref is caught', not r['Spine']['ok'], r['Spine'])

r = mutate('noa11y', lambda n, d: (n, d.replace(b'schema:access', b'x:y'))
           if n.endswith('content.opf') else (n, d))
check('missing accessibility metadata is caught',
      not r['Accessibility metadata']['ok'], r['Accessibility metadata'])

shutil.rmtree(TMP, ignore_errors=True)
print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
