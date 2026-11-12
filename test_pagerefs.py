"""Page references (ROADMAP #74, Phase 5b)  (run: python test_pagerefs.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

A link inside the book prints the page it goes to, "(page 42)", and
`{page: name}` prints the page of a heading or of a spot named `{#name}`.
What is held here:

  1. the grammar, the names a book's targets get, and the round trip through
     the editor's model;
  2. every printed number is the folio its target is on, and every number
     links there (one column and two, with contents, footnotes and a drop
     cap), including books whose numbers grow a digit as they settle;
  3. the book's switch, a target that names nothing, and a book with no
     references set as it was;
  4. the ebook: targets as ids, a page reference as a link by name, valid;
  5. the switch through the app's forms, and the editor's grammar.
"""
import copy, os, re, sys, tempfile, traceback, zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, doc_model, engine, epub, app as A

TMP = tempfile.mkdtemp(prefix='ts-pageref-')
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
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True,
        'index_statblocks': False, 'index_cr': False}

LOREM = ("The tide comes in over the causeway twice a day and the bell under the "
         "water answers it. Nobody in the village will say who hung it there. ")

ROOMS = ['Gate', 'Hall', 'Well', 'Crypt', 'Bell Loft', 'Vault', 'Kitchen', 'Chapel',
         'Stair', 'Cistern', 'Armoury', 'Lantern Room']


def book(notes=False, length=1):
    """A keyed adventure. Each room is a `###` heading holding a word found
    nowhere else (`Qx<n>q`), with a `{#t<n>}` spot beside another (`Sx<n>s`).
    The opening chapter refers to every one of them, forwards, and the last
    refers back; each reference sits after a word of its own (`Rx<n>r` for a
    spot, `Hx<n>h` for a heading, `Gx<n>g` in a link's words)."""
    md = ['# The Approach', '',
          'Opening words for the drop cap. ' + LOREM * 2]
    refs = []
    for n in range(1, len(ROOMS) + 1):
        refs.append(f'Rx{n}r {{page: t{n}}} and Hx{n}h {{page: area-{n}-qx{n}q}} '
                    f'and [Gx{n}g](#area-{n}-qx{n}q).')
    md += ['', ' '.join(refs) + ' ' + LOREM * 2]
    if notes:
        md[-1] += ' A claim.[^n1]'
        md += ['', '[^n1]: A note, which may name a page {page: t1} it cannot print.']
    md += ['', '# The Keep', '']
    for n, room in enumerate(ROOMS, 1):
        md += [f'### Area {n} Qx{n}q', '', f'The {room}. ' + LOREM * (3 * length + n % 3),
               '', f'In the corner Sx{n}s{{#t{n}}} lies something. ' + LOREM * (2 * length)]
    # (not the opening paragraph: a style may set that in capitals)
    md += ['', '# The Way Out', '', LOREM, '', 'Back to Bx1b [the gate](#area-1-qx1q) and '
           'Bx2b {page: t5}. ' + LOREM * 3]
    return '\n'.join(md)


def build(md, p, name, **meta):
    out = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta))
    return out, res


def read_pdf(pdf):
    """(folio of each marker word, numbers printed after each reference word,
    [(number a link reads, folio it goes to)], every page's text)."""
    with fitz.open(pdf) as d:
        texts = [pg.get_text() for pg in d]
        # the first chapter's page: the first with body text (not the contents)
        first = next(i for i, t in enumerate(texts) if 'Nobody in the village' in t)
        folio, printed = {}, {}
        for i, t in enumerate(texts):
            flat = ' '.join(t.split())
            for w in re.findall(r'(?:Qx|Sx)\d+[qs]', flat):
                folio.setdefault(w, i - first + 1)
            for w, num in re.findall(r'((?:Rx|Hx|Bx)\d+[rhb]) (\d+|\?\?)', flat):
                printed[w] = num
            for w, num in re.findall(r'(Gx\d+g|the gate) \(page (\d+|\?\?)\)', flat):
                printed[w] = num
        links = []
        for i, pg in enumerate(d):
            for ln in pg.get_links():
                if ln.get('kind') != fitz.LINK_GOTO:
                    continue
                # a justified line's box takes in a letter of the words beside
                words = (pg.get_textbox(ln['from']).split() or [''])[-1]
                links.append((words, ln['page'] - first + 1))
        return folio, printed, links, texts


def agrees(md, pdf, label):
    folio, printed, links, _ = read_pdf(pdf)
    want = {}
    for n in range(1, len(ROOMS) + 1):
        want[f'Rx{n}r'] = folio.get(f'Sx{n}s')
        want[f'Hx{n}h'] = folio.get(f'Qx{n}q')
        want[f'Gx{n}g'] = folio.get(f'Qx{n}q')
    want['Bx2b'], want['the gate'] = folio.get('Sx5s'), folio.get('Qx1q')
    got = {k: int(v) if v.isdigit() else v for k, v in printed.items()}
    wrong = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
    check(f'{label}: every printed number is where its target is', not wrong and None not in want.values(),
          wrong or want)
    numeric = [(w, f) for w, f in links if w.isdigit()]
    bad = [(w, f) for w, f in numeric if int(w) != f]
    check(f'{label}: every number links to its page', len(numeric) >= 2 * len(ROOMS) and not bad,
          (len(numeric), bad[:5]))
    return folio, printed


# ------------------------------------------------------------------ 1
def test_grammar():
    print('\n1. Grammar and names')
    il = manuscript._inline
    check('a spot is named', il('the vault{#a3} x') == 'the vault<anchor name="a3"/> x')
    check('a page reference, with or without #',
          il('see {page: a3}') == 'see <pageref to="a3"/>'
          and il('see {page:#a3}') == 'see <pageref to="a3"/>')
    check('a name may hold _ inside emphasis',
          il('*a{#snake_case} b*') == '<i>a<anchor name="snake_case"/> b</i>')
    check('escaped braces are literals',
          il(r'a \{#a3} b \{page: a3}') == 'a {#a3} b {page: a3}')
    check('not a name: no marker', il('a {#} b {# x} c {page: } d') == 'a {#} b {# x} c {page: } d')
    check('strip_index takes them out too',
          manuscript.strip_index(il('a{#x} b {page: x}c')) == 'a b c')
    md = ('# The Keep\n\n### The Hall\n\nText{#hall-spot}.\n\n### The Hall\n\nMore.\n\n'
          '### The Keep\n\nAgain.{#the-keep} And{#hall-spot}.\n\n'
          '# Two\n\n## The Hall\n\nEnd{#the-hall}.')
    t = manuscript.book_targets(manuscript.parse_markdown(md)['chapters'])
    check('chapters keep their old names', t['chapters'] == [['chapter-1', 'the-keep'],
                                                             ['chapter-2', 'two']], t['chapters'])
    check('headings are named from their words, a repeat gets -2',
          list(t['headings'][0].values()) == ['the-hall-2', 'the-hall-3', 'the-keep-2']
          and list(t['headings'][1].values()) == ['the-hall-4'], t['headings'])
    check('a written name is reserved before a heading takes it; a taken one is dropped',
          t['own'] == ['hall-spot', 'the-hall'] and t['where']['the-hall'] == 2, t['own'])
    cases = ['The vault{#a3} is on page {page: a3}.',
             'A *styled{#s_1} spot* and **bold {page: s_1}**.',
             r'Literal \{#a3} and \{page: a3} here.',
             '[see{#in-link} this](#chapter-2) {page: chapter-2}',
             'Note[^n]{#after} and {index: Term}{#t} adjacent{page: t}{page: after}']
    for md in cases:
        model = doc_model.from_markdown(md)
        back = doc_model.to_markdown(model).strip()
        check(f'round trip: {md[:40]}', manuscript._inline(back) == manuscript._inline(md),
              (back, md))
    runs = doc_model.from_markdown('a{#b}c{page: b}')[0]['runs']
    check('each is a run of its own', [r.get('anchor') or r.get('pageref') for r in runs]
          == [None, True, None, True] and runs[1]['text'] == 'b', runs)
    lit = doc_model.from_markdown(r'a \{#b} c')[0]['runs']
    check('a literal is a plain run', len(lit) == 1 and lit[0]['text'] == 'a {#b} c', lit)
    check('a Word import writes literals escaped',
          manuscript._escape_literal('{#x} {page: y}') == r'\{#x} \{page: y}')


# ------------------------------------------------------------------ 2
def test_print():
    print('\n2. The printed numbers')
    md = book()
    pdf, res = build(md, preset(1), 'one')
    agrees(md, pdf, 'one column')
    check('a page reference to a target is not reported', res['dead_links'] == [], res['dead_links'])
    pdf, _ = build(md, preset(2), 'two')
    agrees(md, pdf, 'two columns')
    pdf, _ = build(md, preset(1), 'toc', include_toc=True)
    agrees(md, pdf, 'with contents')
    nmd = book(notes=True)
    pdf, _ = build(nmd, preset(1, endnotes={'placement': 'foot'}), 'foot')
    agrees(nmd, pdf, 'with footnotes')
    _, _, _, texts = read_pdf(pdf)
    check('a page reference in a note prints nothing', not any('{page' in t or '<pageref' in t
                                                               for t in texts))
    pdf, _ = build(md, preset(1, chapter={'open_style': 'dropcap'}), 'dropcap')
    agrees(md, pdf, 'with a drop cap')
    # a long book: its numbers reach two and three digits, past the guess
    long = book(length=26)
    pdf, _ = build(long, preset(1), 'long', include_toc=True)
    folio, _ = agrees(long, pdf, 'a long book')
    check('the long book reaches three-digit pages', max(folio.values()) >= 100, max(folio.values()))


# ------------------------------------------------------------------ 3
def test_switch():
    print('\n3. The switch, a target that is not there, an unchanged book')
    md = book()
    pdf, _ = build(md, preset(1), 'off', link_pages=False)
    _, printed, _, texts = read_pdf(pdf)
    check('off: a link prints no page', not any('(page' in t for t in texts))
    check('off: a page reference still prints its number',
          printed.get('Rx1r', '').isdigit() and printed.get('Bx2b', '').isdigit(), printed)
    bad = '# One\n\nSee Rx1r {page: nowhere} and [Gx1g](#nowhere-either).\n\n' + LOREM
    pdf, res = build(bad.replace('See', LOREM + '\n\nSee'), preset(1), 'dead')
    _, printed, _, _ = read_pdf(pdf)
    check('a page reference to nothing prints ??', printed.get('Rx1r') == '??', printed)
    check('both are reported', sorted(res['dead_links']) == ['#nowhere', '#nowhere-either'],
          res['dead_links'])
    plain = '# One\n\nOpening words. ' + LOREM * 30 + '\n\n### A Hall\n\n' + LOREM * 30
    a, ra = build(plain, preset(1), 'plain-on')
    b, rb = build(plain, preset(1), 'plain-off', link_pages=False)
    ta, tb = read_pdf(a)[3], read_pdf(b)[3]
    check('a book with no references is set the same either way',
          ta == tb and ra['page_count'] == rb['page_count'])
    wanted, dead = engine._page_refs_wanted(manuscript.parse_markdown(plain)['chapters'], META)
    check('and asks for no extra pass', not wanted and not dead)


# ------------------------------------------------------------------ 4
def test_epub():
    print('\n4. The ebook')
    import test_outputs
    md = book(notes=True)
    out = os.path.join(TMP, 'book.epub')
    epub.build_epub(manuscript.parse_markdown(md), preset(1), out,
                    dict(META, include_toc=True, afterword='See {page: t1} and {#x} here.'))
    problems = test_outputs.validate(out)
    check('the EPUB validates', not problems, problems)
    z = zipfile.ZipFile(out)
    files = {n: z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml')}
    ch1, ch2 = files['OEBPS/chapter001.xhtml'], files['OEBPS/chapter002.xhtml']
    check('a heading holds its target',
          '<h3 id="h1"><span id="at-area-1-qx1q"></span>Area 1 Qx1q</h3>' in ch2, ch2[:600])
    check('a spot is an empty span', '<span id="at-t1"></span>' in ch2)
    check('a page reference links to the spot by the heading above it',
          'Rx1r <a href="chapter002.xhtml#at-t1">Area 1 Qx1q</a>' in ch1, ch1[:900])
    check('a page reference to a heading reads its words',
          'Hx2h <a href="chapter002.xhtml#at-area-2-qx2q">Area 2 Qx2q</a>' in ch1)
    check('a link keeps its words and gains no page',
          '<a href="chapter002.xhtml#at-area-1-qx1q">Gx1g</a>.' in ch1)
    check('no marker is left anywhere',
          not any(s in t for t in files.values()
                  for s in ('<anchor', '<pageref', '{page', '{#')))


# ------------------------------------------------------------------ 5
def test_app():
    print('\n5. The switch through the app, and the editor')
    check('the switch is a book flag, on when a book does not say',
          'link_pages' in A.BOOK_FLAGS and 'link_pages' in A.ON_FLAGS
          and engine._link_pages_on({}) and not engine._link_pages_on({'link_pages': False}))
    for name in ('project_edit.html', 'generate.html', 'result.html'):
        t = open(os.path.join(REPO, 'templates', name), encoding='utf-8').read()
        check(f'{name} carries it', 'name="link_pages"' in t)
    gen = open(os.path.join(REPO, 'templates', 'generate.html'), encoding='utf-8').read()
    edit = open(os.path.join(REPO, 'templates', 'project_edit.html'), encoding='utf-8').read()
    check('it starts ticked', "not form or form.get('link_pages')" in gen
          and "proj.get('link_pages', True)" in edit)
    sheet = open(os.path.join(REPO, 'templates', 'manuscript_editor.html'), encoding='utf-8').read()
    check('the cheat sheet names both', '{#a3}' in sheet and '{page: a3}' in sheet)
    for name in ('doc_model.js', 'wysiwyg.js'):
        js = open(os.path.join(REPO, 'static', name), encoding='utf-8').read()
        check(f'{name} knows both runs', 'anchor' in js and 'pageref' in js)
    js = open(os.path.join(REPO, 'static', 'doc_model.js'), encoding='utf-8').read()
    check('the JS grammar mirrors manuscript.py',
          manuscript.ANCHOR_RE.pattern.replace('\\-', '-') in js.replace('\\/', '/').replace('\\-', '-')
          and manuscript.PAGE_RE.pattern.replace('\\-', '-') in js.replace('\\-', '-'))


def main():
    for t in (test_grammar, test_print, test_switch, test_epub, test_app):
        try:
            t()
        except Exception:
            traceback.print_exc()
            results.append((t.__name__ + ' raised', False))
    failed = [l for l, ok in results if not ok]
    print(f'\n{"ALL PASS" if not failed else "FAILED (%d): %s" % (len(failed), "; ".join(failed))}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
