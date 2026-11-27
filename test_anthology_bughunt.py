"""Anthologies, poems and the index  (run: python test_anthology_bughunt.py).

Joint bug hunt, round 7, section 31 (anthology, poems & index):

    31.2  a telegram / small-caps table header keeps its index and anchor markers
    31.3  a chapter titled "Chapter 2" does not take the second chapter's name
    31.4  a byline survives its title being cleared (`# | Author`)
    31.5  a pipe in a Word heading is the title's, not a byline separator
    31.7  Word verse: a blank manual line is a stanza break
    31.8  a raised-initial / small-caps opening carries its markers in its text
    31.11 the EPUB byline and tagline read their Markdown, as the PDF does
    31.12 a contributor's name ends at the first separator, not an em dash later
    31.13 `Café` precomposed and decomposed is one index entry
    31.14 an EPUB page reference to a heading leaves out its note number
(31.1 is held in test_variants_bughunt.py with 30.2; 31.9/31.10 are 29.6/29.7.)
"""

import copy, os, re, shutil, sys, tempfile, unicodedata, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh31-')

import app as A
import engine, epub, manuscript, doc_model, bookindex
import fitz

META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'smartquotes': True}
PARA = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 3


def preset(**sections):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    for k, v in sections.items():
        p[k] = {**p.get(k, {}), **v}
    return p


def build(md, p, name, **meta):
    out = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta))
    return out, res


def pages_text(pdf):
    with fitz.open(pdf) as doc:
        return [p.get_text() for p in doc]


def epub_docs(md, name, p=None):
    out = os.path.join(TMP, name + '.epub')
    epub.build_epub(manuscript.parse_markdown(md), p or preset(), out, dict(META))
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml')}


def index_lines(pdf):
    """The lines of the Index page (the last pages, from its heading on)."""
    text = '\n'.join(pages_text(pdf))
    i = text.rfind('Index')
    return [l.strip() for l in text[i:].splitlines() if l.strip()] if i >= 0 else []


# ---- 31.2 -------------------------------------------------------------------
print('31.2 capitals keep the index and anchor markers')
md = ('# One\n\n~~~ telegram\nArrived at noon{index: Arrival}{#arrival}.\n~~~\n\n'
      + PARA + '\n\nSee page {page: arrival} for the wire.\n')
try:
    pdf, res = build(md, preset(), 'telegram')
    built = True
except Exception as e:
    built, pdf = repr(e), None
check('a telegram with a page reference to it builds', built is True, built)
if pdf:
    check('and its index entry is listed', any(l.startswith('Arrival') for l in index_lines(pdf)),
          index_lines(pdf)[:6])
md = ('# One\n\n~~~ table\nHarbour{index: Harbour}{#harbour} | Depth\nNorth | 4\n~~~\n\n'
      + PARA + '\n\nSee page {page: harbour}.\n')
try:
    pdf, res = build(md, preset(table={'header_style': 'smallcaps'}), 'sc-table')
    built = True
except Exception as e:
    built, pdf = repr(e), None
check('a small-caps table header with a page reference to it builds', built is True, built)
if pdf:
    check('and its index entry is listed', any(l.startswith('Harbour') for l in index_lines(pdf)),
          index_lines(pdf)[:6])
check('a note reference in capitals is still kept',
      '<super>1</super>' in engine._caps_keep_notes('arrived<super>1</super> stop'))

# ---- 31.3 -------------------------------------------------------------------
print('31.3 a title does not take a later chapter\'s positional name')
names = manuscript.book_anchors([{'title': 'Chapter 2'}, {'title': 'The Vault'},
                                 {'title': 'Interlude'}, {'title': 'Interlude'}])
check('chapter 2 keeps chapter-2', names[1][0] == 'chapter-2', names)
check('the first chapter\'s title slug steps aside', names[0] == ['chapter-1', 'chapter-2-2'], names)
check('a repeated title is still numbered', names[3] == ['chapter-4', 'interlude-2'], names)
md = '# Chapter 2\n\n' + PARA + '\n\n# The Vault\n\n' + PARA + '\n\nBack to {page: chapter-2}.\n'
docs = epub_docs(md, 'positional')
ch2 = docs.get('OEBPS/chapter002.xhtml', '')
check('the EPUB links chapter-2 to the second chapter',
      re.search(r'href="chapter002\.xhtml', ch2) is not None,
      re.findall(r'href="[^"]*"', ch2))

# ---- 31.4 / 31.5 ------------------------------------------------------------
print('31.4 / 31.5 the byline separator')
for src, want in (('The Lottery | Shirley Jackson', ('The Lottery', 'Shirley Jackson')),
                  ('| Ana Vale', (None, 'Ana Vale')),
                  ('Salt \\| Ash', ('Salt | Ash', None)),
                  ('Salt \\| Ash | Ana', ('Salt | Ash', 'Ana')),
                  ('[Salt | Road](#x) | Ana', ('[Salt | Road](#x)', 'Ana'))):
    check(f'split {src!r}', manuscript._split_byline(src) == want, manuscript._split_byline(src))
blocks = [{'type': 'chapter', 'title': None, 'byline': 'Ana Vale'}]
md = doc_model.to_markdown(blocks)
check('a cleared title keeps its byline in Markdown', 'Ana Vale' in md, md)
check('and it reads back', doc_model.parse_markdown(md)[0].get('byline') == 'Ana Vale'
      if hasattr(doc_model, 'parse_markdown') else
      doc_model.from_markdown(md)[0].get('byline') == 'Ana Vale', md)
blocks = [{'type': 'chapter', 'title': 'Salt | Ash', 'byline': None}]
md = doc_model.to_markdown(blocks)
back = doc_model.from_markdown(md)[0]
check('a title with a pipe reads back as that title', (back['title'], back.get('byline'))
      == ('Salt | Ash', None), (md, back))
ch = manuscript.parse_markdown('# Salt \\| Ash\n\n' + PARA + '\n')['chapters'][0]
check('the book reads it as one title', (ch['title'], ch.get('byline')) == ('Salt | Ash', None),
      (ch['title'], ch.get('byline')))

try:
    import docx
    d = docx.Document()
    d.add_heading('Salt | Ash', level=1)
    d.add_paragraph('The keeper rang the bell.')
    try:
        verse = d.styles.add_style('Verse', 1)
    except Exception:
        verse = d.styles['Verse']
    p = d.add_paragraph(style=verse)
    r = p.add_run('First stanza line')
    r.add_break(); r.add_break()
    p.add_run('Second stanza line')
    dp = os.path.join(TMP, 'pipe.docx')
    d.save(dp)
    imported = manuscript.import_docx(dp)
    md = imported[0] if isinstance(imported, tuple) else imported
    ch = manuscript.parse_markdown(md)['chapters'][0]
    check('a Word heading "Salt | Ash" has no byline',
          (ch['title'], ch.get('byline')) == ('Salt | Ash', None), (ch['title'], ch.get('byline')))
    # ---- 31.7 ---------------------------------------------------------------
    print('31.7 Word verse keeps its stanza breaks')
    poem = re.search(r'~~~ poem\n(.*?)\n~~~', md, re.S)
    check('the two stanzas are apart', poem and re.search(r'First stanza line\n\nSecond', poem.group(1)),
          poem and poem.group(1))
except ImportError:
    check('python-docx is available', False)

# ---- 31.8 -------------------------------------------------------------------
print('31.8 a decorative opening carries its markers in its first line')
for style in ('raised_initial', 'smallcaps_leadin'):
    md = ('# One\n\nArrival{index: Arrival}{#arrival} came at noon. ' + PARA
          + '\n\n' + PARA + '\n\nSee page {page: arrival}.\n')
    p = preset(chapter={'open_style': style})
    pdf, _ = build(md, p, 'open-' + style)
    check(f'{style}: the index lists it', any(l.startswith('Arrival') for l in index_lines(pdf)),
          index_lines(pdf)[:6])
    # no marker is a flowable of its own in front of the paragraph any more
    fl = engine._opening_para('Arrival<onDraw name="_ts_anchor" label="arrival"/> came.',
                              {'first': engine.ParagraphStyle('f', fontName='Times-Roman',
                                                              fontSize=11, leading=14)},
                              p, {'regular': 'Times-Roman', 'bold': 'Times-Bold'})
    check(f'{style}: one flowable, with the marker in it',
          len(fl) == 1 and not isinstance(fl[0], (engine.IndexMark, engine.AnchorMark)), fl)

# ---- 31.11 ------------------------------------------------------------------
print('31.11 the EPUB byline reads its Markdown')
md = ('# Salt Road | Ana \\*Vale\\* and [Bo](#notes)\n#> A *tale* of salt\n\n' + PARA
      + '\n\n# Notes\n\n' + PARA + '\n')
docs = epub_docs(md, 'byline')
c1 = docs.get('OEBPS/chapter001.xhtml', '')
byl = re.search(r'<p class="chapter-byline">(.*?)</p>', c1, re.S)
byl = byl.group(1) if byl else ''
check('no backslashes are printed', '\\' not in byl and 'Ana *Vale*' in byl, byl)
check('the link is a link', 'href="chapter002.xhtml' in byl, byl)
tag = re.search(r'<p class="chapter-tagline">(.*?)</p>', c1, re.S)
check('the tagline\'s emphasis is set (30.11)', tag and '<em>tale</em>' in tag.group(1),
      tag and tag.group(1))

# ---- 31.12 ------------------------------------------------------------------
print('31.12 a contributor\'s name ends at the first separator')
meta = dict(META, contributors='Ana Vale -- writes mysteries — and poems.',
            front_matter='none', back_matter='full')
out = os.path.join(TMP, 'contrib.pdf')
engine.build_pdf(manuscript.parse_markdown('# One\n\n' + PARA + '\n'), preset(), out, meta)
with fitz.open(out) as doc:
    bold = [s['text'] for pg in doc for b in pg.get_text('dict')['blocks']
            for l in b.get('lines', []) for s in l['spans']
            if 'Bold' in s['font'] and ('Ana' in s['text'] or 'writes' in s['text'])]
check('only the name is bold in the PDF', bold and all('writes' not in t for t in bold), bold)
xhtml = epub._matter_xhtml('Contributors', meta['contributors'], 'matter-contributors')
check('only the name is bold in the EPUB',
      re.search(r'<strong>Ana Vale</strong>', xhtml) is not None, xhtml[-300:])

# ---- 31.13 ------------------------------------------------------------------
print('31.13 one entry per term, however it is composed')
nfc, nfd = unicodedata.normalize('NFC', 'Café'), unicodedata.normalize('NFD', 'Café')
marks = [{'path': (nfc,), 'chapter': 1}, {'path': (nfd,), 'chapter': 1}]
entries, _ = bookindex.tree(marks, [(0, 3), (1, 9)], {})
check('Café is one entry with both pages', len(entries) == 1 and len(entries[0][1]) == 2, entries)

# ---- 31.14 ------------------------------------------------------------------
print('31.14 an EPUB page reference leaves out the heading\'s note number')
md = ('# One\n\n' + PARA + '\n\n## Guard Room[^n]\n\n' + PARA
      + '\n\nBack in the {page: guard-room}.\n\n[^n]: Built later.\n')
docs = epub_docs(md, 'caption')
c1 = docs.get('OEBPS/chapter001.xhtml', '')
link = re.search(r'<a [^>]*href="[^"]*guard-room[^"]*"[^>]*>(.*?)</a>', c1)
check('the reference reads "Guard Room"', link and re.sub('<[^>]+>', '', link.group(1)) == 'Guard Room',
      link and link.group(0))

shutil.rmtree(TMP, ignore_errors=True)
print('\n' + ('ALL PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
