"""XML-escaping tests  (run: python test_escaping.py).

No test framework, like test_epub.py. Body text arrives at the builders already
escaped, because it came through `manuscript._inline`. Titles do not: a chapter
or part title, the book's title, subtitle and author, the matter-page headings
and the preset's number formats are all carried as plain text and emitted
straight into the XHTML. So an ordinary title — "Salt & Ash", "Sense &
Sensibility", a co-author line "Lovelace & Babbage" — produced an EPUB whose
nav, contents, chapter and OPF pages were all malformed. The validator rejects
that and a strict reader refuses to open it; the PDF was never affected.

These build a book with an ampersand in every one of those slots and assert two
things: every page parses, and the character reads back as a single `&` rather
than a double-escaped `&amp;`.
"""

import sys, os, json, zipfile, shutil, tempfile
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)
import epub, engine, manuscript, matter

TMP = tempfile.mkdtemp()
preset = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'),
                        encoding='utf-8'))

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond: fails.append(name)


# every slot that carries plain text gets an ampersand in it
SRC = ('=== Fire & Blood\n\n# Salt & Ash\n\nBody with salt & ash and a <tag>.\n\n'
       '## Wind & Rain\n\nMore prose.\n\n# Ice & Stone\n\nProse.\n')
ms = manuscript.parse_markdown(SRC)
meta = {'title': 'Sense & Sensibility', 'subtitle': 'Reason & Feeling',
        'author': 'Lovelace & Babbage', 'year': '2026',
        'publisher': 'Ashforge & Co', 'front_matter': 'full',
        'right_hand_starts': False, 'include_toc': True, 'smartquotes': True,
        'cover_mode': 'none', 'cover_image': '', 'cover_overlay': False,
        'cover_color': 'light',
        **{k: '' for k in matter.KEYS}}
meta['also_by'] = 'Pride & Prejudice'
meta['acknowledgments'] = 'Thanks to Smith & Sons.'

EP = os.path.join(TMP, 'amp.epub')
epub.build_epub(ms, preset, EP, meta)

# ---- 1. every page is well-formed
bad, texts = [], {}
with zipfile.ZipFile(EP) as z:
    for n in z.namelist():
        if not n.endswith(('.xhtml', '.opf', '.ncx')):
            continue
        try:
            root = ET.fromstring(z.read(n))
        except ET.ParseError as exc:
            bad.append('%s (%s)' % (n, exc))
            continue
        texts[os.path.basename(n)] = ' '.join(
            t.strip() for t in root.itertext() if t.strip())
check('every page of the EPUB is well-formed XML', not bad, bad)
check("and the project's own EPUB check passes",
      all(c['ok'] for c in epub.check(EP)),
      [c['label'] for c in epub.check(EP) if not c['ok']])

# ---- 2. the ampersand reads back as one character, in the page that owns it
ALL = ' || '.join(texts.values())
for probe, where in (('Salt & Ash', 'chapter title'),
                     ('Ice & Stone', 'second chapter title'),
                     ('Fire & Blood', 'part title'),
                     ('Wind & Rain', 'subhead'),
                     ('Sense & Sensibility', 'book title'),
                     ('Reason & Feeling', 'subtitle'),
                     ('Lovelace & Babbage', 'author'),
                     ('Pride & Prejudice', 'Also By entry'),
                     ('Smith & Sons', 'acknowledgments'),
                     ('Ashforge & Co', 'publisher / copyright'),
                     ('<tag>', 'angle brackets in body text')):
    check('%s survives as written' % where, probe in ALL,
          [k for k in texts if probe.split(' &')[0] in texts[k]])

check('nothing is double-escaped', 'amp;' not in ALL,
      [w for w in ALL.split() if 'amp;' in w])

# the chapter title reaches the nav, the contents page and the chapter itself —
# all three were malformed before, so all three are worth naming
for page in ('nav.xhtml', 'toc.xhtml', 'chapter001.xhtml'):
    check('%s carries the chapter title' % page,
          'Salt & Ash' in texts.get(page, ''), sorted(texts))

# ---- 3. the PDF was always fine and must stay so
res = engine.build_pdf(ms, preset, os.path.join(TMP, 'amp.pdf'), meta)
check('the PDF still builds with the same book', res['page_count'] > 0, res)

shutil.rmtree(TMP, ignore_errors=True)
print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
