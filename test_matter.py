"""Front/back-matter tests  (run: python test_matter.py).

No test framework, like test_epub.py. Matter pages carry *raw author text* —
a dedication, an Also By list, a contributors note — which each builder inlines
itself rather than receiving pre-parsed from `manuscript`. That second code path
is where the two bugs these tests pin down lived:

  1. The EPUB's own emphasis pass had no bold-italic rule, so `***x***` came out
     cross-nested (`<strong><em>x</strong></em>`) — not well-formed XHTML, which
     fails epubcheck and strict readers — and `___x___` kept its underscores.
  2. The PDF unlinked dead `#anchor` links in chapters but not in matter, and an
     unresolved destination is fatal to ReportLab: an Also By page pointing at a
     since-renamed chapter killed the whole build.

Both are about the two builders agreeing with each other, so most checks here
compare EPUB output against the PDF's for the same source text.
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
import epub, engine, manuscript

TMP = tempfile.mkdtemp()
preset = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'),
                        encoding='utf-8'))

TEXT = '# The Salt Road\n\nSome prose.\n\n# The Long Way Home\n\nMore prose.\n'
ms = manuscript.parse_markdown(TEXT, smartquotes=True)

MATTER_KEYS = ('dedication', 'epigraph', 'foreword', 'preface', 'introduction',
               'afterword', 'bibliography', 'acknowledgments', 'contributors',
               'about_author', 'also_by', 'blurbs')


def meta(**over):
    m = {'title': 'T', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
         'front_matter': 'full', 'right_hand_starts': False, 'include_toc': False,
         'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
         'cover_overlay': False, 'cover_color': 'light',
         **{k: '' for k in MATTER_KEYS}}
    m.update(over)
    return m


fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond: fails.append(name)


def wellformed(markup):
    try:
        ET.fromstring('<p>' + markup + '</p>')
        return True
    except ET.ParseError as exc:
        return str(exc)


def as_html(reportlab_markup):
    """The PDF's tags, renamed to the EPUB's — the two must agree on structure."""
    return (reportlab_markup.replace('<b>', '<strong>').replace('</b>', '</strong>')
                            .replace('<i>', '<em>').replace('</i>', '</em>'))


# ---------------------------------------------------------------- 1. emphasis
print('matter emphasis: the EPUB agrees with the PDF')

for src in ('A ***bold italic*** phrase.',
            'A ___bold italic___ phrase.',
            'Plain **bold** and *italic* and a [link](https://example.com).',
            'Both ***at once*** and **just bold**.'):
    got = epub._md_emph_to_html(src)
    check('well-formed XHTML: %r' % src, wellformed(got) is True, got)
    check('matches the PDF: %r' % src,
          got == as_html(manuscript._inline(src, smartquotes=False)),
          '%r vs %r' % (got, as_html(manuscript._inline(src, smartquotes=False))))

check('bold-italic is one nested span, not two crossed ones',
      epub._md_emph_to_html('***x***') == '<strong><em>x</em></strong>',
      epub._md_emph_to_html('***x***'))
check('underscores do not survive into the text',
      '_' not in epub._md_emph_to_html('___x___'),
      epub._md_emph_to_html('___x___'))

# ---- and the built book is actually valid
GOOD = os.path.join(TMP, 'matter.epub')
epub.build_epub(ms, preset, GOOD,
                meta(dedication='For ***Mira***, who read ___every___ draft.'))
bad = []
with zipfile.ZipFile(GOOD) as z:
    for n in z.namelist():
        if n.endswith(('.xhtml', '.opf', '.ncx')):
            try:
                ET.fromstring(z.read(n))
            except ET.ParseError as exc:
                bad.append('%s: %s' % (n, exc))
check('every page of the built EPUB is well-formed', not bad, bad)
check("and the project's own EPUB check agrees",
      all(c['ok'] for c in epub.check(GOOD)),
      [c['label'] for c in epub.check(GOOD) if not c['ok']])

# --------------------------------------------------------------- 2. dead links
print('\nmatter links: a stale anchor does not cost the writer the PDF')

def build(**over):
    out = os.path.join(TMP, 'book.pdf')
    return engine.build_pdf(ms, preset, out, meta(**over))

check('a live #anchor in a chapter is left alone',
      manuscript.parse_markdown('x') is not None
      and build()['dead_links'] == [])

live = build(also_by='[The Salt Road](#the-salt-road)')
check('a live #anchor on an Also By page stays a link',
      live['dead_links'] == [], live['dead_links'])

for key, label in (('also_by', 'Also By page'), ('dedication', 'dedication'),
                   ('acknowledgments', 'acknowledgments'),
                   ('contributors', 'contributors note'),
                   ('epigraph', 'epigraph')):
    try:
        res = build(**{key: 'See [the old road](#the-old-road) — gone now.'})
        built, dead = True, res['dead_links']
    except Exception as exc:
        built, dead = False, '%s: %s' % (type(exc).__name__, exc)
    check('a stale #anchor on the %s still builds' % label, built, dead)
    check('and the %s reports it in preflight' % label,
          built and dead == ['#the-old-road'], dead)

# The story is rebuilt once per layout pass; a broken anchor is still one
# broken anchor, so the count the writer is shown must not multiply.
res = build(include_toc=True, also_by='[gone](#the-old-road)')
check('a TOC build reports the stale anchor once, not once per pass',
      res['dead_links'] == ['#the-old-road'], res['dead_links'])

res = build(also_by='[a](#the-old-road)', dedication='[b](#nowhere)')
check('two different stale anchors are both named',
      sorted(res['dead_links']) == ['#nowhere', '#the-old-road'], res['dead_links'])

shutil.rmtree(TMP, ignore_errors=True)
print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
