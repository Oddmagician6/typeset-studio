"""The ebook's extras stay well-formed and linked  (run: python test_epub_bughunt.py).

Joint bug hunt, round 3, section 14:

    14.1  a writer's own block label (`~~~ Q&A`) is a safe class name
    14.2  a table caption with emphasis across a link stays well-formed
    14.3  a note on a heading leaves the heading's id alone
    14.4  a page reference inside a link is its words, not a link in a link
    14.5  anchors and index targets inside a telegram survive
    14.6  a missing page design fails the ebook's own checks
    14.7  a heading with no words is left out of the contents
    14.8  a writer's own `_ix` makes no duplicate ids
    14.9  the device preview's in-book links point inside the joined page
    14.10 a link's query string is not double-escaped
    14.11 a spread's alt text reads the left page first, by where boxes sit
    14.12 chapter art keeps its height limit (covered by the build: style cap)
    14.13 a negative list start is kept
"""

import copy, os, re, sys, tempfile, zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import epub
import manuscript
import wrap_design

fails = []
TMP = tempfile.mkdtemp(prefix='epub_bughunt_')
META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it.'


def check(label, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f'         {detail}')
        fails.append(label)


def preset(**kw):
    p = copy.deepcopy(A.DEFAULTS)
    for k, v in kw.items():
        p[k] = dict(p.get(k) or {}, **v)
    return p


def build(md, name, p=None, **meta):
    out = os.path.join(TMP, name + '.epub')
    epub.build_epub(manuscript.parse_markdown(md), p or preset(), out, dict(META, **meta))
    with zipfile.ZipFile(out) as z:
        docs = {n: z.read(n).decode('utf-8') for n in z.namelist()
                if n.endswith('.xhtml')}
    return out, docs


def well_formed(docs):
    bad = []
    for n, s in docs.items():
        try:
            minidom.parseString(s.encode('utf-8'))
        except Exception as e:
            bad.append(f'{n}: {e}')
    return bad


def ch1(docs):
    return docs['OEBPS/chapter001.xhtml']


def test_markup():
    print('\nwell-formed chapters')
    out, docs = build(f'# One\n\n~~~ Q&A\n{L}\n~~~\n\n{L}', 'qa')
    check('14.1 a `~~~ Q&A` block leaves the chapter readable', not well_formed(docs),
          well_formed(docs))
    check('     and it carries a safe class', 'doc-block-q-a' in ch1(docs))

    out, docs = build(f'# One\n\n~~~ table caption="**[Field guide**](https://example.test/guide)"\n'
                      f'A | B\n1 | 2\n~~~\n\n{L}', 'caption')
    check('14.2 a caption with emphasis across a link is well-formed', not well_formed(docs),
          well_formed(docs))

    html = epub._md_emph_to_html('[Shop](https://example.test/?book=ash&edition=ebook)')
    check('14.10 a link keeps its query string, escaped once',
          'href="https://example.test/?book=ash&amp;edition=ebook"' in html, html)


def test_links():
    print('\nheadings, references and anchors')
    out, docs = build(f'# One\n\n## Guard Room[^key]\n\n{L}\n\n'
                      f'See {{page: guard-room}} and [the room](#guard-room).\n\n[^key]: A note.',
                      'noteref')
    c = ch1(docs)
    check('14.3 a noted heading keeps its plain id', 'id="at-guard-room"' in c,
          re.findall(r'id="[^"]*guard[^"]*"', c))
    check('     and the links to it land', 'guard-room1' not in c and '#at-guard-room"' in c)

    out, docs = build(f'# One\n\n## Guard Room\n\n{L}\n\n'
                      f'[Nearest stair: {{page: guard-room}}](#one).', 'nested')
    c = ch1(docs)
    check('14.4 no link inside a link', not re.search(r'<a\b[^>]*>[^<]*<a\b', c) and
          not well_formed(docs), re.findall(r'<a\b.*?</a>', c)[:3])

    out, docs = build(f'# One\n\n~~~ telegram\nArrived{{#signal}}{{index: Arrival}}.\n~~~\n\n'
                      f'{L}\n\nSee {{page: signal}}.', 'telegram')
    c = ch1(docs)
    check('14.5 an anchor inside a telegram stays a destination', 'id="at-signal"' in c,
          re.findall(r'<span id="[^"]*"', c))
    bad = [r for r in epub.check(out) if not r.get('ok')]
    check('     and the ebook has no dangling links', not bad, bad[:3])

    p = preset(toc={'depth': 2})
    out, docs = build(f'# One\n\n## {{#signal}}\n\n{L}\n\n## Real\n\n{L}', 'navlabel', p,
                      include_toc=True)
    nav = next((s for n, s in docs.items() if n.endswith('nav.xhtml')), '')
    check('14.7 a heading with no words has no contents entry',
          not re.search(r'<a [^>]*>\s*</a>', nav) and 'Real' in nav, nav[-600:])

    out, docs = build(f'# One\n\n~~~ statblock name="Bog Hound" _ix="7"\n{L}\n~~~\n\n'
                      f'~~~ statblock name="Mire Cat" _ix="7"\n{L}\n~~~\n\n{L}', 'dupid')
    ids = re.findall(r'\bid="([^"]+)"', ch1(docs))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    check('14.8 a writer\'s own `_ix` makes no duplicate ids', not dup, dup)


def test_checks():
    print('\nthe ebook\'s own checks')
    out, docs = build(f'# One\n\n{L}\n\n~~~ page src="harbor-map"\n~~~\n\n{L}', 'nopage')
    rows = [r for r in epub.check(out) if r['label'] == 'Page designs']
    check('14.6 a missing page design fails the checks',
          rows and not rows[0]['ok'] and 'harbor-map' in rows[0]['detail'], rows)

    out, docs = build(f'# One\n\n~~~ list type="numbered" start="-2"\nfirst\nsecond\n~~~\n\n{L}',
                      'negstart')
    check('14.13 a negative list start is kept', 'start="-2"' in ch1(docs),
          re.findall(r'<ol[^>]*>', ch1(docs)))
    out, docs = build(f'# One\n\n~~~ list type="numbered" start="soon"\nfirst\n~~~\n\n{L}',
                      'badstart')
    check('      and a start that is no number is left out', '<ol class="block-list">' in ch1(docs),
          re.findall(r'<ol[^>]*>', ch1(docs)))


def test_preview():
    print('\nthe device preview')
    hrefs = {'chapter001.xhtml', 'endnotes.xhtml'}
    a = A._preview_links('<p>x<a id="ref-1" href="endnotes.xhtml#note-1">1</a>'
                         '<a href="https://example.test/">out</a></p>',
                         'chapter001.xhtml', hrefs)
    b = A._preview_links('<p id="note-1"><a href="chapter001.xhtml#ref-1">back</a></p>',
                         'endnotes.xhtml', hrefs)
    check('14.9 a note link points at the note in the joined page',
          'href="#endnotes--note-1"' in a and 'id="endnotes--note-1"' in b, a + b)
    check('     and back again', 'href="#chapter001--ref-1"' in b and 'id="chapter001--ref-1"' in a)
    check('     an outside link is as it was', 'href="https://example.test/"' in a)


def test_spread_words():
    print('\na spread\'s alt text')
    els = [{'type': 'text', 'anchor': 'front', 'x': 0.5, 'y': 1.0, 'w': 2, 'text': 'Right top'},
           # anchored right, but dragged across the fold onto the left page
           {'type': 'text', 'anchor': 'front', 'x': -5.0, 'y': 3.0, 'w': 2, 'text': 'Left low'}]
    d = {'name': 'map', 'spread': True, 'elements': els}
    words = wrap_design.page_words(d, 6, 9)
    check('14.11 the left page is read first, by where a box sits',
          words == 'Left low Right top', words)
    check('      without the trim, the anchor still orders it',
          wrap_design.page_words(d) == 'Right top Left low')


def test_chapter_art_cap():
    print('\nchapter art')
    src = open(epub.__file__, encoding='utf-8').read()
    check('14.12 the art carries a height limit', 'max-height:' in src and 'object-fit:contain' in src)


if __name__ == '__main__':
    for t in (test_markup, test_links, test_checks, test_preview, test_spread_words,
              test_chapter_art_cap):
        t()
    print(f'\n{"all passed" if not fails else f"{len(fails)} FAILED"}')
    sys.exit(1 if fails else 0)
