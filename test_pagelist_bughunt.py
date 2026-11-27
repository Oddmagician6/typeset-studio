"""The print edition's pages in the reflowable EPUB  (run: python test_pagelist_bughunt.py).

    23.11 a PDF and a reflowable EPUB of the same book had no shared page
          navigation. The PDF now reports, for each numbered page, the
          chapter block it shows (`print_pages`); an EPUB built beside it
          marks where each page starts (doc-pagebreak), lists the pages in a
          page-list nav and says so in its accessibility metadata. Built
          alone, or handed another book's pages, it claims none. The
          fixed-layout EPUB's page list is its own pages: no source named (29.9).
"""

import copy, os, re, sys, shutil, tempfile, zipfile
from datetime import datetime
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import engine
import epub
import manuscript

fails = []
TMP = tempfile.mkdtemp(prefix='ts-pagelist-')
META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'full',
        'include_toc': False}


def check(label, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f'         {detail}')
        fails.append(label)


PARA = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 5
MD = ('# The Harbor\n\n' + '\n\n'.join(f'Para{i} ' + PARA for i in range(6))
      + '\n\n## Arrival\n\n' + PARA + '[^1]\n\n[^1]: A note about the bell.\n\n* * *\n\n'
      + '~~~ table\n| A | B |\n|---|---|\n'
      + '\n'.join(f'| r{i} | v{i} |' for i in range(45)) + '\n~~~\n\n'
      + '\n\n'.join(f'Later{i} ' + PARA for i in range(6))
      + '\n\n# Second Light\n\n### Deep\n\n'
      + '\n\n'.join(f'Second{i} ' + PARA for i in range(10)) + '\n\n# Short\n\nOne line only.\n')


def read(out):
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode('utf-8') for n in z.namelist()
                if n.endswith(('.xhtml', '.opf'))}


def preset_of(name='classic-literary'):
    return A.load_preset(name)


# ---- the PDF reports its pages --------------------------------------------
print('PDF print_pages')
for name in ('classic-literary', 'game-rulebook-two-column'):
    ms = manuscript.parse_markdown(MD)
    pdf = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(ms, preset_of(name), pdf, dict(META))
    pp = res.get('print_pages') or []
    check(f'{name}: pages listed', len(pp) > 4, pp)
    folios = [f for f, _, _ in pp]
    check(f'{name}: folio 1 is the first chapter opening',
          pp[:1] == [(1, 1, -1)], pp[:2])
    check(f'{name}: folios run 1..n with none missing',
          folios == list(range(1, len(pp) + 1)), folios)
    check(f'{name}: positions never go backwards',
          all(pp[i][1:] <= pp[i + 1][1:] for i in range(len(pp) - 1)), pp)
    check(f'{name}: the last chapter is listed', pp[-1][1] == 3, pp[-1])
    # each block a page starts with is on that page in the PDF
    import fitz
    doc = fitz.open(pdf)
    start = res['chapter_pages'][1]            # 1-based place of folio 1
    wrong, seen = [], set()
    for folio, idx, bi in pp:
        # only where the block starts: a page none starts on shows the block
        # still running (a blank verso before a chapter, a long table)
        if bi < 0 or (idx, bi) in seen:
            continue
        seen.add((idx, bi))
        block = ms['chapters'][idx - 1]['blocks'][bi]
        word = re.sub(r'<[^>]+>', ' ', block[1] if isinstance(block[1], str) else '').split()
        if not word or not re.match(r'^(Para|Later|Second)\d+$', word[0]):
            continue
        text = doc[start - 1 + folio - 1].get_text()
        if word[0] not in text.split():
            wrong.append((folio, word[0]))
    doc.close()
    check(f'{name}: each listed block is on its page', not wrong, wrong)

# ---- the EPUB marks and lists them -----------------------------------------
print('EPUB beside the PDF')
ms = manuscript.parse_markdown(MD)
res = engine.build_pdf(ms, preset_of(), os.path.join(TMP, 'pair.pdf'), dict(META))
pp = res['print_pages']
out = os.path.join(TMP, 'pair.epub')
epub.build_epub(ms, preset_of(), out, dict(META, print_pages=pp,
                                            print_pages_key=res['print_pages_key']))
docs = read(out)
bad = []
for n, s in docs.items():
    try:
        minidom.parseString(s.encode('utf-8'))
    except Exception as e:
        bad.append(f'{n}: {e}')
check('every document is well formed', not bad, bad)
nav = docs['OEBPS/nav.xhtml']
plist = re.search(r'<nav epub:type="page-list"[^>]*>(.*?)</nav>', nav, re.S)
check('the nav has a page list', plist is not None)
hrefs = re.findall(r'<a href="([^"]+)">(\d+)</a>', plist.group(1) if plist else '')
check('one entry per print page, in order',
      [int(n) for _, n in hrefs] == [f for f, _, _ in pp], hrefs[:5])
missing = []
for href, n in hrefs:
    f, frag = href.split('#')
    span = re.search(rf'<span epub:type="pagebreak" role="doc-pagebreak" id="{frag}"'
                     rf' aria-label="{n}"></span>', docs.get('OEBPS/' + f, ''))
    if not span:
        missing.append(href)
check('every entry lands on a page break marker in its chapter', not missing, missing)
# page N's marker sits just before the block the PDF named
ch1 = docs['OEBPS/chapter001.xhtml']
first_block = [(f, bi) for f, idx, bi in pp if idx == 1 and bi >= 0]
f, bi = first_block[0]
blk = ms['chapters'][0]['blocks'][bi][1]
word = re.sub(r'<[^>]+>', ' ', blk).split()[0]
after = ch1.split(f'aria-label="{f}"></span>', 1)[1]
check('a marker comes right before its block',
      re.sub(r'<[^>]+>', ' ', after).split()[:1] == [word],
      (word, after[:200]))
opf = docs['OEBPS/content.opf']
check('OPF: pageNavigation and pageBreakMarkers',
      'accessibilityFeature">pageNavigation<' in opf
      and 'accessibilityFeature">pageBreakMarkers<' in opf)
check('OPF: the pagination source names the print edition',
      '<dc:source id="pagination-source">The Drowned Bell, print edition</dc:source>' in opf
      and '<meta refines="#pagination-source" property="source-of">pagination</meta>' in opf
      and 'pageBreakSource' not in opf, opf)
problems = [p for p in epub.check(out) if 'error' in str(p).lower()] \
    if hasattr(epub, 'check') else []
check("the app's EPUB check finds no errors", not problems, problems)

print('EPUB alone, or with another book\'s pages')
alone = os.path.join(TMP, 'alone.epub')
epub.build_epub(manuscript.parse_markdown(MD), preset_of(), alone, dict(META))
d = read(alone)
check('alone: no page list', 'page-list' not in d['OEBPS/nav.xhtml'])
check('alone: no page claims',
      'pageNavigation' not in d['OEBPS/content.opf']
      and 'source-of' not in d['OEBPS/content.opf'])
check('alone: no markers', not any('doc-pagebreak' in s for s in d.values()))
other = os.path.join(TMP, 'other.epub')
epub.build_epub(manuscript.parse_markdown('# Only\n\nOne paragraph.\n'), preset_of(), other,
                dict(META, print_pages=pp))
d = read(other)
check("another book's pages: no list, no markers",
      'page-list' not in d['OEBPS/nav.xhtml']
      and not any('doc-pagebreak' in s for s in d.values()))

# ---- the app hands the PDF's pages to the EPUB ------------------------------
print('App: a book built as both')
saved = A.OUT_DIR
A.OUT_DIR = os.path.join(TMP, 'out')
os.makedirs(A.OUT_DIR)
try:
    proj = {'name': 'Pagelist', 'title': 'Pagelist Book', 'author': 'T. Fixture',
            'preset': 'classic-literary', 'front_matter': 'full', 'format': 'both',
            'cover_mode': 'none', 'manuscript_type': 'paste'}
    meta, cover = A._project_meta(proj)
    now = datetime.now().isoformat(timespec='microseconds')
    r = A._build_project_with('test-pagelist', proj, preset_of(), MD, meta, cover, now, '')
    check('built both', r.get('out_name') and r.get('epub_name'), r.get('error'))
    if r.get('epub_name'):
        d = read(os.path.join(A.OUT_DIR, r['epub_name']))
        n = len(re.findall(r'doc-pagebreak', ''.join(d.values())))
        check('its EPUB lists the PDF\'s pages',
              'epub:type="page-list"' in d['OEBPS/nav.xhtml']
              and n == len(r['build_result']['print_pages']), n)
    check('_with_print_pages leaves a PDF-less build alone',
          A._with_print_pages({'a': 1}, None) == {'a': 1})
finally:
    A.OUT_DIR = saved

# ---- fixed layout: its own pages ---------------------------------------------
print('Fixed layout')
import fixed_epub
src = open(fixed_epub.__file__, encoding='utf-8').read()
check('fixed layout names no pagination source',
      'pageBreakSource' not in src and 'source-of' not in src)

shutil.rmtree(TMP, ignore_errors=True)
print()
print('ALL PASS' if not fails else f'{len(fails)} FAILED: {fails}')
sys.exit(1 if fails else 0)
