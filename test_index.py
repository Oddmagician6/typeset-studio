"""The index (ROADMAP #74, Phase 5a)  (run: python test_index.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

`{index: Term}` in the text, an Index page at the back of the PDF and the
ebook. What is held here:

  1. the marker's grammar, and its round trip through the editor's model;
  2. the printed index: every number is the page its marker is on (one column
     and two, with contents, footnotes and a decorative opening), entries in
     order under their letters, runs of pages merged, numbers that link;
  3. stat blocks by name and by challenge rating, when the book asks;
  4. a book with no markers is the book it was;
  5. the ebook's index, linked by chapter, and a valid EPUB;
  6. the book's two options through the app's forms.
"""
import copy, json, os, re, sys, tempfile, traceback, zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, doc_model, bookindex, engine, epub, app as A

TMP = tempfile.mkdtemp(prefix='ts-index-')
results = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (('\n         ' + str(detail)) if detail and not cond else ''))
    results.append((label, bool(cond)))


def preset(cols=1, **sections):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    if cols == 2:
        p['trim'] = {'w': 8.5, 'h': 11.0}
        p['columns'] = {'count': 2, 'gap': 0.25}
    for k, v in sections.items():
        p[k] = {**p.get(k, {}), **v}
    return p


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True}

LOREM = ("The tide comes in over the causeway twice a day and the bell under the "
         "water answers it. Nobody in the village will say who hung it there. ")

NAMES = ['Owlbear', 'Marsh Hag', 'Tide Wraith', 'Bell Warden', 'Eel Swarm', 'Salt Golem',
         'Drowned Sailor', 'Causeway Troll', 'Lantern Moth', 'Brine Hound', 'Reed Stalker',
         'Ålesund Ghost', '3-Headed Pike', 'Zephyr Imp', 'Kelp Shambler', 'Wreck Diver']
CRS = ['1/4', '5', '1/2', '12', '0', '1/8']


def book(stat=True, notes=False):
    """A two-chapter book. Every marker sits beside a word found nowhere else
    (`Qx<n>q`), so the page a marker is on can be read back from the PDF."""
    n = [0]

    def mark(term):
        n[0] += 1
        return f'Qx{n[0]}q{{index: {term}}}'

    md = ['# The Causeway', '',
          f'The first {mark("Causeway")} paragraph opens the chapter {mark("Tides > spring")}. '
          + LOREM * 5]
    for i, name in enumerate(NAMES):
        md += ['', f'## {name} lair {mark("Lairs > " + name)}', '',
               f'A **{name}** {mark(name)} lives here. ' + LOREM * (8 + i % 3)
               + ('A claim.[^n%d]' % i if notes and i % 4 == 0 else ''),
               '', f'More on the *{name} {mark(name)}* and the bell {mark("Bell")}. ' + LOREM * 6]
        if notes and i % 4 == 0:
            md += ['', '[^n%d]: The note for it, with a marker{index: Never} that is dropped.' % i]
        if i % 5 == 0:
            md += ['', '~~~ table', 'Thing | Where', f'{name} den {mark("Dens")} | north', '~~~']
        if stat and i % 3 == 0:
            md += ['', f'~~~ statblock cr="{CRS[(i // 3) % len(CRS)]}"', f'{name} Elder',
                   'Large monstrosity, unaligned', 'Armor Class 13',
                   'Hit Points 59 (7d10 + 21)', 'Speed 40 ft.', '~~~']
    md += ['', '# The Bell', '',
           f'Second chapter {mark("Bell")} text {mark("Tides > neap")}. ' + LOREM * 4,
           '', LOREM * 14]
    if stat:
        md += ['', '~~~ statblock', 'Bell Keeper', 'Medium undead, lawful evil',
               'Armor Class 15', 'Challenge 3 (700 XP)', '~~~']
    return '\n'.join(md)


def build(md, p, name, **meta):
    out = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta))
    return out, res


def markers(md):
    """[(term, word)] in the manuscript: each marker and the word beside it."""
    return [(' '.join(t.split()), w) for w, t in re.findall(r'(Qx\d+q)\{index: ([^}]+)\}', md)]


def read_pdf(pdf):
    """(folio of each word, the index's lines, links, page count).

    The folio of a page is counted as the book counts it: from the first
    chapter's page. The index is the last pages, from the one headed Index.
    """
    with fitz.open(pdf) as d:
        texts = [pg.get_text() for pg in d]
        first = next(i for i, t in enumerate(texts) if 'qx1q' in t.lower())
        at = max(i for i, t in enumerate(texts) if t.strip().startswith('Index')
                 or re.search(r'^\s*Index\s*$', t, re.M))
        folio = {}
        for i, t in enumerate(texts[:at]):
            # an opening set in capitals prints the word as QX1Q
            for w in re.findall(r'qx(\d+)q', t.lower()):
                folio.setdefault(f'Qx{w}q', i - first + 1)
        names = {}
        for i, t in enumerate(texts[:at]):
            names[i - first + 1] = t
        lines = [l.strip() for t in texts[at:] for l in t.split('\n') if l.strip()]
        links = []
        for pg in list(d)[at:]:
            for ln in pg.get_links():
                if ln.get('kind') in (fitz.LINK_GOTO, fitz.LINK_NAMED):
                    links.append(ln)
        return folio, lines, links, len(d), names, at - first + 1


def parse_index(lines):
    """{term: {folios}} from the index's lines; a sub-entry is 'Main > sub'.
    A line that is only numbers continues the entry above it."""
    out, main, last = {}, None, None
    stop = lines.index(bookindex.CR_HEADING) if bookindex.CR_HEADING in lines else len(lines)
    for line in lines[:stop]:
        if line == bookindex.HEADING or re.fullmatch(r'[A-ZÅ]', line) or re.fullmatch(r'\d+', line):
            continue
        m = re.match(r'^(.*?)((?:,\s*\d+(?:–\d+)?)+),?$', line)
        if re.fullmatch(r'[\d–,\s]+', line) and last:
            m, text = re.match(r'^()(.*?),?$', ', ' + line), None
        else:
            text = (m.group(1) if m else line).strip()
        folios = set()
        for part in re.findall(r'\d+(?:–\d+)?', m.group(2) if m else ''):
            a, _, b = part.partition('–')
            folios.update(range(int(a), int(b or a) + 1))
        if text is None:
            out[last].update(folios)
            continue
        last = text
        out.setdefault(text, set()).update(folios)
    return out


def want_index(md, folio, with_stat=False):
    """{term: {folios}} the index should print, from where the words landed.
    Sub-entries are keyed by their own words, as the index prints them."""
    want = {}
    for term, word in markers(md):
        parts = [p.strip() for p in term.split('>')]
        want.setdefault(parts[0], set())
        want.setdefault(parts[-1], set()).add(folio[word]) if len(parts) > 1 \
            else want[parts[0]].add(folio[word])
    return want


# ------------------------------------------------------------------ 1
def test_grammar():
    print('\n1. The marker')
    il = manuscript._inline
    check('a marker is a neutral tag that prints nothing',
          il('the owlbear{index: Owlbear} attacks') == 'the owlbear<index item="Owlbear"/> attacks')
    check('a sub-entry is one marker',
          manuscript.index_path('Monsters &gt; Owlbear') == ('Monsters', 'Owlbear')
          and il('x{index: Monsters > Owlbear}') == 'x<index item="Monsters &gt; Owlbear"/>')
    check('emphasis characters in a term are not markup',
          il('*a{index: snake_case*x} b*') == '<i>a<index item="snake_case*x"/> b</i>')
    check('a quote in a term cannot end the tag',
          '"' not in manuscript.INDEX_TAG_RE.search(il('x{index: a "b" c}', False)).group(1))
    check('an escaped brace is a literal', il(r'a \{index: no} b') == 'a {index: no} b')
    check('no term, no marker', il('a {index: } b {index:} c') == 'a {index: } b {index:} c')
    check('a term holds no note and no link',
          '<index' not in il('a {index: b[^n]} c') and '<index' not in il('a {index: [x](#y)} c'))
    check('strip_index takes the tags out', manuscript.strip_index(il('a{index: B} c')) == 'a c')

    cases = ['The owlbear{index: Owlbear} attacks.',
             'A *marked{index: a_b*c} italic* and **bold{index: Monsters > Owlbear}**.',
             r'Literal \{index: nope} here.', '{index: Alone}',
             '[see {index: Linked} this](#chapter-2) ok',
             'Note[^n]{index: After} and {index: "Quoted" term} done.',
             r'Odd {index: a\\b} and {index: a\{b} and {index: a\[b} x',
             'Empty {index: } stays; nested {index: a {b} c}.',
             '*{index: x}* *y*', 'two{index: A}{index: B} adjacent']
    bad = []
    for md in cases:
        m1 = doc_model.from_markdown(md)
        out = doc_model.to_markdown(m1)
        if (doc_model.from_markdown(out) != m1
                or manuscript.parse_markdown('# T\n\n' + md) != manuscript.parse_markdown('# T\n\n' + out)):
            bad.append(md)
    check('the editor model round trips every marker', not bad, bad)
    runs = doc_model.from_markdown('a{index: B}c')[0]['runs']
    check('a marker is a run of its own, never merged',
          [r.get('index', False) for r in runs] == [False, True, False] and runs[1]['text'] == 'B')
    lit = doc_model.from_markdown(r'a \{index: B} c')[0]['runs']
    check('a literal is plain text and is written back escaped',
          len(lit) == 1 and not lit[0].get('index')
          and doc_model.to_markdown([{'type': 'para', 'runs': lit}]).strip() == r'a \{index: B} c')
    check('the Word importer escapes a typed marker',
          manuscript._escape_literal('{index: x}') == r'\{index: x}')
    block = doc_model.from_markdown('~~~ statblock\nOwlbear\n{index: kept as written}\n~~~')[0]
    check('a stat block line keeps its source', block['children'][1]['runs'][0]['text']
          == '{index: kept as written}')


# ------------------------------------------------------------------ 2
def test_print():
    print('\n2. The printed index')
    md = book(stat=False)
    setups = [
        ('one column', preset(1), {}),
        ('two columns, contents', preset(2), {'include_toc': True, 'front_matter': 'full'}),
        ('a drop cap, footnotes, contents',
         preset(1, chapter={'open_style': 'dropcap'}, endnotes={'placement': 'foot'}),
         {'include_toc': True, 'front_matter': 'full', '_notes': True}),
        ('small caps opening, any-page starts',
         preset(1, chapter={'open_style': 'smallcaps_leadin', 'start': 'any'}),
         {'right_hand_starts': False}),
    ]
    for label, p, meta in setups:
        src = book(stat=False, notes=True) if meta.pop('_notes', False) else md
        pdf, res = build(src, p, 'print-' + re.sub(r'\W+', '-', label), **meta)
        folio, lines, links, pages, _, _ = read_pdf(pdf)
        got, want = parse_index(lines), want_index(src, folio)
        wrong = {k: (sorted(got.get(k, ())), sorted(v)) for k, v in want.items()
                 if got.get(k, set()) != v}
        check(f'{label}: every number is the page its marker is on', not wrong,
              dict(list(wrong.items())[:4]))
        check(f'{label}: nothing is listed that was not marked',
              not (set(got) - set(want)), sorted(set(got) - set(want))[:6])
        check(f'{label}: each number links to a page', len(links) >= len(want) - 2, len(links))
        check(f'{label}: a marker in a note is dropped', 'Never' not in got)
    # order, letters, ranges: from the one-column build
    pdf, _ = build(md, preset(1), 'print-order')
    folio, lines, links, pages, _, _ = read_pdf(pdf)
    heads = [l for l in lines if re.fullmatch(r'[A-Z]', l)]
    check('entries sit under their letters, in order', heads == sorted(heads) and 'O' in heads, heads)
    names = [re.sub(r',\s*\d.*$', '', l) for l in lines]
    check('a digit comes first, under no letter', names.index('3-Headed Pike') < lines.index('A'))
    check('an accent files under its letter',
          lines.index('A') < names.index('Ålesund Ghost') < lines.index('B'))
    subs = names[names.index('Lairs') + 1:names.index('Lairs') + 1 + len(NAMES)]
    check('sub-entries follow their main entry, in order',
          subs == sorted(NAMES, key=bookindex.sort_key), subs[:5])
    bell = next(l for l in lines if l.startswith('Bell,'))
    check('pages in a row are one range', '–' in bell or len(want_index(md, folio)['Bell']) < 3, bell)
    with fitz.open(pdf) as d:
        toc = [t[1] for t in d.get_toc()]
        last = d[pages - 1]
        xs = sorted({round(b[0]) for b in last.get_text('blocks') if re.search(r', \d', b[4])})
    check('the index is in the PDF bookmarks', bookindex.HEADING in toc, toc[-3:])
    check('the index is set in two columns in a one-column book',
          len(xs) >= 2 and xs[-1] - xs[0] > 100, xs)
    # a second build is the same build
    pdf2, _ = build(md, preset(1), 'print-order-2')
    check('the same book builds the same index', read_pdf(pdf2)[1] == lines)


# ------------------------------------------------------------------ 3
def test_statblocks():
    print('\n3. Stat blocks')
    md = book(stat=True)
    pdf, _ = build(md, preset(2), 'stat-default')
    lines = read_pdf(pdf)[1]
    check('by default: the stat blocks are listed, with the challenge list',
          any(l.startswith('Owlbear Elder') for l in lines) and bookindex.CR_HEADING in lines)
    pdf, _ = build(md, preset(2), 'stat-off', index_statblocks=False, index_cr=False)
    lines = read_pdf(pdf)[1]
    check('off: no stat block is listed', not any(l.startswith('Owlbear Elder') for l in lines)
          and bookindex.CR_HEADING not in lines)
    pdf, _ = build(md, preset(2), 'stat-on', index_statblocks=True, index_cr=True)
    folio, lines, links, pages, texts, _ = read_pdf(pdf)
    got = parse_index(lines)
    elders = [n + ' Elder' for i, n in enumerate(NAMES) if i % 3 == 0] + ['Bell Keeper']
    check('on: every stat block is listed by name', all(e in got for e in elders),
          [e for e in elders if e not in got])
    texts = {f: ' '.join(t.split()) for f, t in texts.items()}    # a name can wrap
    wrong = [e for e in elders
             if not any(e.upper() in texts[f].upper() for f in got.get(e, ()))]
    check('and its number is the page its name is on', not wrong,
          [(e, sorted(got.get(e, ())), [f for f, t in texts.items() if e.upper() in t.upper()])
           for e in wrong[:3]])
    cr = lines[lines.index(bookindex.CR_HEADING) + 1:]
    heads = [l for l in cr if l.startswith('CR ')]
    check('the challenge list runs lowest first',
          heads == ['CR 0', 'CR 1/8', 'CR 1/4', 'CR 1/2', 'CR 3', 'CR 5', 'CR 12'], heads)
    check('a Challenge line counts as its rating',
          cr[cr.index('CR 3') + 1].startswith('Bell Keeper,'), cr[cr.index('CR 3'):][:3])
    pdf, _ = build(md, preset(1), 'stat-cr-only', index_statblocks=False, index_cr=True)
    lines = read_pdf(pdf)[1]
    check('the challenge list alone leaves the names out of the index',
          bookindex.CR_HEADING in lines
          and not any(l.startswith('Owlbear Elder') for l in lines[:lines.index(bookindex.CR_HEADING)]))
    only = '# One\n\nNo markers here. ' + LOREM * 3 + \
           '\n\n~~~ statblock cr="2"\nOwlbear\nLarge monstrosity\nArmor Class 13\n~~~\n'
    pdf, _ = build(only, preset(1), 'stat-only', index_statblocks=True)
    with fitz.open(pdf) as d:
        text = d[len(d) - 1].get_text()
    check('a book of stat blocks and no markers gets its index',
          'Index' in text and re.search(r'Owlbear, 1', text) is not None, text[:80])


# ------------------------------------------------------------------ 4
def test_unchanged():
    print('\n4. A book with no markers')
    off = dict(index_statblocks=False, index_cr=False)
    plain = re.sub(r'\{index: [^}]+\}', '', book(stat=True))
    a, ra = build(plain, preset(1), 'plain', **off)
    b, rb = build(plain, preset(1), 'plain-default')
    with fitz.open(a) as d:
        text = '\n'.join(pg.get_text() for pg in d)
    check('no Index page with the stat-block options off', not re.search(r'^\s*Index\s*$', text, re.M))
    check('by default its stat blocks alone add the index', rb['page_count'] > ra['page_count'],
          (ra['page_count'], rb['page_count']))
    marked, rm = build(book(stat=True), preset(1), 'plain-marked', **off)
    with fitz.open(marked) as d:
        body = [pg.get_text() for pg in d][:ra['page_count']]
    with fitz.open(a) as d:
        base = [pg.get_text() for pg in d]
    check('markers move no word: the pages before the index are the same',
          rm['page_count'] > ra['page_count'] and body == base,
          (ra['page_count'], rm['page_count']))
    front = {'afterword': 'An afterword {index: Ignored} here.', 'dedication': 'For {index: X} you.'}
    pdf, _ = build(plain, preset(1), 'plain-matter', **front, **off)
    with fitz.open(pdf) as d:
        text = '\n'.join(pg.get_text() for pg in d)
    check('a marker on a matter page prints nothing and makes no index',
          '{index' not in text and 'Ignored' not in text and not re.search(r'^\s*Index\s*$', text, re.M))


# ------------------------------------------------------------------ 5
def test_epub():
    print('\n5. The ebook')
    md = book(stat=True, notes=True)
    out = os.path.join(TMP, 'book.epub')
    meta = dict(META, include_toc=True, index_statblocks=True, index_cr=True,
                afterword='An afterword {index: Ignored} here.')
    epub.build_epub(manuscript.parse_markdown(md), preset(1), out, meta)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        page = z.read('OEBPS/bookindex.xhtml').decode('utf-8')
        nav = z.read('OEBPS/nav.xhtml').decode('utf-8')
        opf = z.read('OEBPS/content.opf').decode('utf-8')
        files = {n: z.read(n).decode('utf-8') for n in names if n.endswith('.xhtml')}
    check('the index is a page of the book, last in the reading order',
          'bookindex.xhtml' in nav and opf.rstrip().count('bookindex') >= 2
          and re.search(r'<itemref idref="bookindex"/>\s*</spine>', opf) is not None)
    links = re.findall(r'href="(chapter\d+\.xhtml)#(ix-\d+)"', page)
    dead = [(f, i) for f, i in links if f'id="{i}"' not in files['OEBPS/' + f]]
    check('every entry links to an anchor that is there', links and not dead, dead[:4])
    check('an entry names the chapters it is marked in',
          re.search(r'Bell: <a [^>]+>The Causeway</a>, <a [^>]+>The Bell</a>', page) is not None)
    check('stat blocks and the challenge list are in it',
          'Owlbear Elder' in page and bookindex.CR_HEADING in page and 'CR 1/4' in page)
    check('no neutral tag and no raw marker reaches the book',
          not any('<index ' in t or '{index' in t for t in files.values()))
    check('a marker in a note or on a matter page is dropped',
          'Never' not in page and 'Ignored' not in page)
    bad = [c for c in epub.check(out) if not c['ok']]
    check('the EPUB is valid', not bad, bad)
    out2 = os.path.join(TMP, 'plain.epub')
    epub.build_epub(manuscript.parse_markdown('# One\n\nNo markers.'), preset(1), out2, META)
    with zipfile.ZipFile(out2) as z:
        check('a book with no markers has no index page',
              'OEBPS/bookindex.xhtml' not in z.namelist())


# ------------------------------------------------------------------ 6
def test_forms():
    print('\n6. The book options')
    src = open(os.path.join(REPO, 'app.py'), encoding='utf-8').read()
    check('both options are book flags',
          {'index_statblocks', 'index_cr'} <= set(A.BOOK_FLAGS))
    for name in ('project_edit.html', 'generate.html', 'result.html'):
        t = open(os.path.join(REPO, 'templates', name), encoding='utf-8').read()
        check(f'{name} carries both options',
              'name="index_statblocks"' in t and 'name="index_cr"' in t)
    check('the editor cheat sheet names the marker',
          '{index: Owlbear}' in open(os.path.join(REPO, 'templates', 'manuscript_editor.html'),
                                     encoding='utf-8').read())
    check('a save writes an option only once it differs from on',
          "if (k in form) != proj.get(k, True) or k in proj" in src)
    gen = open(os.path.join(REPO, 'templates', 'generate.html'), encoding='utf-8').read()
    edit = open(os.path.join(REPO, 'templates', 'project_edit.html'), encoding='utf-8').read()
    check('both options start ticked',
          all(f"not form or form.get('{k}')" in gen and f"proj.get('{k}', True)" in edit
              for k in ('index_statblocks', 'index_cr')))
    check('a book that never said has both on',
          bookindex.on({}, 'index_statblocks') and not bookindex.on({'index_cr': False}, 'index_cr'))
    for name in ('doc_model.js', 'wysiwyg.js'):
        js = open(os.path.join(REPO, 'static', name), encoding='utf-8').read()
        check(f'{name} knows an index run', 'index: true' in js)


def main():
    for t in (test_grammar, test_print, test_statblocks, test_unchanged, test_epub, test_forms):
        try:
            t()
        except Exception:
            traceback.print_exc()
            results.append((t.__name__ + ' raised', False))
    failed = [l for l, ok in results if not ok]
    print('\n' + ('ALL PASS' if not failed else f'{len(failed)} FAILED: ' + '; '.join(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
