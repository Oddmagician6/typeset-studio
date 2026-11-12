"""Reference-book structure (ROADMAP #74, Phase 2)  (run: python test_reference.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

`###` and `####` headings, the `#>` chapter tagline, contents depth, PDF
bookmarks, running heads by chapter or section, the Letter / A4 / A5 trims, and
Word headings by level. The fixture is `test_fixtures/ttrpg/reference.md`.
"""

import copy
import os
import re
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import logging; logging.disable(logging.INFO)
import manuscript
import doc_model

FIX = os.path.join(HERE, 'test_fixtures', 'ttrpg')
LOCAL = os.path.join(HERE, 'Edenfall for test')
TMP = tempfile.mkdtemp(prefix='ts-reference-')

_failures = []


def _check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        if detail:
            print(f"         {detail}")
        _failures.append(label)


def _fixture():
    with open(os.path.join(FIX, 'reference.md'), encoding='utf-8') as f:
        return f.read()


def _kinds(ch):
    return [b[0] for b in ch['blocks']]


def test_parse():
    print("parse")
    ms = manuscript.parse_markdown(_fixture())
    chs = ms['chapters']
    _check("three chapters", [c['title'] for c in chs]
           == ['The Drowned Chapel', 'Interlude', 'Untagged'], [c['title'] for c in chs])
    ch = chs[0]
    _check("the line after `# Title` is its tagline",
           ch.get('tagline') == 'Where the bells still ring below the water.', ch.get('tagline'))
    _check("heading kinds by level",
           [k for k in _kinds(ch) if k in manuscript.HEADING_KINDS]
           == ['subhead', 'section', 'subsection', 'subsection', 'section',
               'subhead', 'section'], _kinds(ch))
    texts = [b[1] for b in ch['blocks'] if b[0] == 'section']
    _check("a room key keeps its words", texts[0] == 'A1. The Porch', texts)
    paras = [b[1] for b in ch['blocks'] if b[0] == 'para']
    _check("an escaped `###` is text", any(p.startswith('### This line') for p in paras), paras)
    _check("an escaped `#>` is text",
           any(p.startswith('#&gt; Nor is this') for p in paras), paras)
    inter = chs[1]
    _check("an unnumbered chapter with a byline takes a tagline",
           inter.get('unnumbered') and inter['byline'] == 'A Guest Writer'
           and inter.get('tagline') == 'The tide goes out.', inter)
    _check("`#>` after text is only text",
           any(b[1].startswith('#&gt; A tagline-looking') for b in inter['blocks']),
           inter['blocks'])
    last = chs[2]
    _check("a chapter with no `#>` line has no tagline key", 'tagline' not in last)
    _check("a sub-section may sit straight under a chapter",
           _kinds(last)[0] == 'subsection', _kinds(last))
    _check("a bare `###` is still a scene break", 'scene' in _kinds(last), _kinds(last))

    # a fence's `### Actions` is the stat block's own line, never a heading
    sb = manuscript.parse_markdown(
        '# C\n\n~~~ statblock\n## Bog-Thrall\n**AC** 9\n### Actions\n'
        '***Bite.*** +3 to hit.\n~~~\n')['chapters'][0]
    _check("`###` inside a fence is not a heading", _kinds(sb) == ['doc_block'], _kinds(sb))
    model = sb['blocks'][0][2]['_statblock']
    _check("…and still the stat block's section",
           [s.get('name') for s in model.get('sections', [])] == ['Actions'],
           model.get('sections'))

    for line in ('### A3. Guard Room', '#### Hazards', '#> A tagline'):
        _check(f"`{line}` is guarded as body text", manuscript.block_collision(line))
    _check("`#>tight` (no space) is not a tagline", not manuscript.block_collision('#>tight'))


def test_round_trip():
    print("\nround trip")
    raw = _fixture()
    for smart in (True, False):
        doc1 = doc_model.from_markdown(raw, smartquotes=smart)
        md2 = doc_model.to_markdown(doc1)
        doc2 = doc_model.from_markdown(md2, smartquotes=smart)
        _check(f"engine fidelity (smart={smart})",
               manuscript.parse_markdown(raw, smartquotes=smart)
               == manuscript.parse_markdown(md2, smartquotes=smart))
        _check(f"model stability (smart={smart})", doc1 == doc2)
    doc = doc_model.from_markdown(raw)
    subs = [b.get('level', 2) for b in doc if b['type'] == 'subhead']
    _check("the model carries levels", subs == [2, 3, 4, 4, 3, 2, 3, 4], subs)
    _check("`level` is only carried when not 2",
           all('level' not in b for b in doc if b['type'] == 'subhead'
               and b.get('level', 2) == 2))
    ch = [b for b in doc if b['type'] == 'chapter']
    _check("the model carries the tagline",
           ch[0].get('tagline') == 'Where the bells still ring below the water.'
           and 'tagline' not in ch[2], ch)

    built = [{"type": "chapter", "title": "Keys", "byline": None, "tagline": "A *short* one"},
             {"type": "subhead", "runs": [doc_model._run("Upper Floor")]},
             {"type": "subhead", "level": 3, "runs": [doc_model._run("C1. Landing")]},
             {"type": "subhead", "level": 4, "runs": [doc_model._run("Trap", bold=True)]},
             {"type": "para", "runs": [doc_model._run("### typed, not a heading")]},
             {"type": "para", "runs": [doc_model._run("#> typed, not a tagline")]}]
    md = doc_model.to_markdown(built)
    _check("an editor-built model round-trips", doc_model.from_markdown(md) == built, md)
    _check("it writes `#>` under the title and `###`/`####`",
           md.startswith('# Keys\n#> A *short* one\n') and '\n### C1. Landing\n' in md
           and '\n#### **Trap**\n' in md and '\n\\### typed' in md, md)


def _preset(**over):
    import app
    p = copy.deepcopy(app.DEFAULTS)
    for path, v in over.items():
        sec, key = path.split('__')
        p.setdefault(sec, {})[key] = v
    return p


def _build(md, preset, meta=None, name='ref'):
    import engine
    out = os.path.join(TMP, name + '.pdf')
    m = {'title': 'The Valley Book', 'author': 'A. Writer', 'front_matter': 'none'}
    m.update(meta or {})
    res = engine.build_pdf(manuscript.parse_markdown(md), preset, out, m)
    return out, res


def test_pdf():
    print("\npdf")
    import fitz
    out, res = _build(_fixture(), _preset(toc__depth=3), {'include_toc': True})
    doc = fitz.open(out)
    toc = [(lvl, title) for lvl, title, _page in doc.get_toc()]
    want = [(1, 'Part One: The Valley'), (2, 'The Drowned Chapel'),
            (3, 'Approaching the Chapel'), (4, 'A1. The Porch'), (4, 'A2. The Nave'),
            (3, 'The Undercroft'), (4, 'B1. Ossuary'), (2, 'Interlude'), (2, 'Untagged')]
    _check("the bookmarks: parts, chapters, `##` and `###`", toc == want, toc)
    pages = {title: page for _l, title, page in doc.get_toc()}
    porch = doc[pages['A1. The Porch'] - 1].get_text()
    _check("a section's bookmark goes to its page", 'A1. The Porch' in porch)

    contents = doc[0].get_text()
    _check("contents depth 3 lists `###` sections",
           'A1. The Porch' in contents and 'Approaching the Chapel' in contents
           and 'Hazards' not in contents, contents[:300])
    opener = doc[pages['The Drowned Chapel'] - 1].get_text()
    _check("the tagline prints under the title",
           'Where the bells still ring below the water.' in opener)

    out1, _ = _build(_fixture(), _preset(), {'include_toc': True}, name='ref-d1')
    c1 = fitz.open(out1)[0].get_text()
    _check("contents depth 1 (the default) lists chapters only",
           'The Drowned Chapel' in c1 and 'A1. The Porch' not in c1, c1[:300])
    _check("every build has bookmarks, contents or not",
           len(fitz.open(_build(_fixture(), _preset(), name='ref-plain')[0]).get_toc()) == 9)

    # running heads: chapter on the verso, the current `##` on the recto
    filler = ' '.join(['Water rises in the old stones and falls again.'] * 60)
    md = (f'# Keys\n\n{filler}\n\n## Upper Floor\n\n{filler}\n\n{filler}\n\n'
          f'## Cellars\n\n{filler}\n\n{filler}\n')
    heads = {}
    for mode in ('book', 'chapter', 'section'):
        o, _ = _build(md, _preset(running_head__content=mode), name='rh-' + mode)
        d = fitz.open(o)
        heads[mode] = []
        for i in range(d.page_count):
            top = [w[4] for w in d[i].get_text('words') if w[3] < d[i].rect.height * 0.08]
            heads[mode].append(' '.join(top))
    _check("'book' keeps author and title", 'A. WRITER' in heads['book']
           and 'THE VALLEY BOOK' in heads['book'], heads['book'])
    _check("'chapter' sets the chapter on the recto",
           'KEYS' in heads['chapter'] and 'THE VALLEY BOOK' in heads['chapter']
           and 'A. WRITER' not in heads['chapter'], heads['chapter'])
    sec = heads['section']
    _check("'section' sets the chapter on the verso and the section on the recto",
           'KEYS' in sec and 'UPPER FLOOR' in sec and 'CELLARS' in sec
           and all(h in ('', 'KEYS') for h in sec[1::2]), sec)
    _check("…the recto shows a section once it has begun",
           sec.index('CELLARS') > sec.index('UPPER FLOOR'), sec)

    # the new trims build at their size
    import app
    trims = {(w, h) for w, h, _ in app.TRIM_PRESETS}
    _check("Letter, A4 and A5 are offered",
           {(8.5, 11.0), (8.27, 11.69), (5.83, 8.27)} <= trims, sorted(trims))
    for w, h in ((8.5, 11.0), (8.27, 11.69), (5.83, 8.27)):
        o, _ = _build('# One\n\n### A1. Hall\n\nText.\n', _preset(trim__w=w, trim__h=h),
                      name=f'trim-{w}')
        r = fitz.open(o)[0].rect
        _check(f"a {w} × {h} book is that size",
               abs(r.width - w * 72) < 0.5 and abs(r.height - h * 72) < 0.5, r)


def _pages(md, start, rhs, toc=True, name='fm', **meta):
    """(first lines, contents numbers, foot folio) for each page of a build."""
    import fitz
    m = dict({'include_toc': toc, 'right_hand_starts': rhs}, **meta)
    out, _ = _build(md, _preset(chapter__start=start), m, name=name)
    doc = fitz.open(out)
    pages = []
    for pg in doc:
        lines = [l.strip() for l in pg.get_text().splitlines() if l.strip()]
        listed = {}
        for ln in lines:
            hit = re.match(r'(.+?)\s*\.{4,}\s*(\d+)$', ln)
            if hit:
                listed[hit.group(1).strip()] = int(hit.group(2))
        foot = [w[4] for w in pg.get_text('words') if w[1] > pg.rect.height * 0.9]
        pages.append((lines, listed, foot))
    doc.close()
    return pages


def _page_of(pages, *first):
    """Index of the page whose text opens with these lines."""
    for i, (lines, _listed, _foot) in enumerate(pages):
        if lines[:len(first)] == list(first):
            return i
    return None


def test_contents_pages():
    print("\ncontents and the pages around them")
    filler = ' '.join(['Water rises in the old stones and falls again.'] * 40)
    plain = ''.join(f'# {t}\n\n{filler}\n\n' for t in ('One', 'Two', 'Three'))
    parts = (f'=== The Valley\n\n# One\n\n{filler}\n\n# Two\n\n{filler}\n\n'
             f'=== The Hills\n\n# Three\n\n{filler}\n')

    # chapters that start on any page (the game styles) once set the first part
    # divider, or the first chapter, on the contents page itself
    pg = _pages(parts, 'any', True, name='fm-parts')
    _check("contents keep their page to themselves when chapters start anywhere",
           pg[0][0][0] == 'Contents' and not any('Part 1' in l for l in pg[0][0]),
           pg[0][0])
    _check("…the first part divider has the next page, and the chapter the one after",
           pg[1][0] == ['Part 1', 'The Valley'] and pg[2][0][:2] == ['Chapter 1', 'One'],
           [p[0][:2] for p in pg[:3]])
    pg = _pages(plain, 'any', True, name='fm-plain')
    _check("with no parts the first chapter starts the page after the contents",
           'Chapter 1' not in pg[0][0] and pg[1][0][:2] == ['Chapter 1', 'One'],
           [p[0][:2] for p in pg[:2]])
    pg = _pages(parts, 'any', True, toc=False, name='fm-ded',
                dedication='For the valley.')
    _check("a dedication keeps its page too",
           pg[0][0] == ['For the valley.'] and pg[1][0] == ['Part 1', 'The Valley'],
           [p[0][:3] for p in pg[:2]])
    pg = _pages(plain, 'any', True, name='fm-both', dedication='For the valley.')
    ded = _page_of(pg, 'For the valley.')
    _check("contents, then the dedication, then the first chapter",
           pg[0][0][0] == 'Contents' and ded is not None
           and pg[ded][0] == ['For the valley.']
           and pg[ded + 1][0][:2] == ['Chapter 1', 'One'], [p[0][:2] for p in pg[:5]])

    # no forced right-hand pages: nothing asks for a blank page before the contents
    pg = _pages(plain, 'recto', False, name='fm-rhs-off')
    _check("right-hand starts off: the book opens on its contents, not a blank page",
           pg[0][0][:1] == ['Contents'] and pg[1][0][:2] == ['Chapter 1', 'One'],
           [p[0][:2] for p in pg[:3]])
    pg = _pages(plain, 'any', False, name='fm-rhs-off-full', front_matter='full')
    _check("…and with a title and copyright page there is no blank page among them",
           all(p[0] for p in pg) and pg[3][0][:1] == ['Contents'],
           [p[0][:1] for p in pg[:5]])
    pg = _pages(plain, 'any', False, toc=False, name='fm-rhs-off-ded',
                front_matter='full', dedication='For the valley.')
    _check("…nor before a dedication",
           all(p[0] for p in pg) and pg[3][0] == ['For the valley.'],
           [p[0][:1] for p in pg[:5]])

    # a book with forced right-hand pages is laid out as it always was
    pg = _pages(parts, 'recto', True, name='fm-recto', front_matter='full')
    _check("right-hand starts on: contents, divider and chapter each on a right-hand page",
           [i for i, p in enumerate(pg) if p[0][:1] in (['Contents'], ['Part 1'],
                                                         ['Chapter 1'])] == [4, 6, 8],
           [p[0][:1] for p in pg[:9]])

    # the number the contents give a chapter is the number on its page: page 1
    # is the first chapter's opener (which prints none), so the page after an
    # opener carries the opener's number plus one
    for label, md, start, rhs, meta in (
            ('right-hand starts', plain, 'recto', True, {'front_matter': 'full'}),
            ('chapters anywhere', parts, 'any', True, {}),
            ('right-hand starts off', plain, 'any', False, {'front_matter': 'full'}),
            ('a dedication between', plain, 'any', True,
             {'dedication': 'For the valley.'})):
        pg = _pages(md, start, rhs, name='fm-folio', **meta)
        listed = next(p[1] for p in pg if p[0][:1] == ['Contents'])
        got, want = [], []
        for n, title in enumerate(('One', 'Two', 'Three'), start=1):
            i = _page_of(pg, f'Chapter {n}', title)
            got.append(listed.get(title))
            want.append(int(pg[i + 1][2][0]) - 1 if i is not None and pg[i + 1][2] else None)
        _check(f"contents give each chapter the number on its page ({label})",
               got == want and got[0] == 1, f'contents {got}, pages {want}')

    # footnotes take room pass 1 never measured: the contents still say where
    # each chapter landed
    note = ' '.join(['A note long enough to take its share of the foot of the page.'] * 3)
    body = ' '.join(f'Water rises in the old stones[^{n}] and falls again.'
                    for n in range(1, 13))
    notes = '\n'.join(f'[^{n}]: {note}' for n in range(1, 13))
    md = ''.join(f'# {t}\n\n{body}\n\n{filler}\n\n{notes}\n\n' for t in ('One', 'Two', 'Three'))
    p = _preset(chapter__start='any', endnotes__placement='foot')
    out, _ = _build(md, p, {'include_toc': True}, name='fm-notes')
    import fitz
    doc = fitz.open(out)
    listed = {}
    for ln in doc[0].get_text().splitlines():
        hit = re.match(r'(.+?)\s*\.{4,}\s*(\d+)$', ln.strip())
        if hit:
            listed[hit.group(1).strip()] = int(hit.group(2))
    marks = {title: page for _l, title, page in doc.get_toc()}
    start = marks.get('One')
    _check("…with footnotes at the foot of the page as well",
           start and [listed.get(t) for t in ('One', 'Two', 'Three')]
           == [marks[t] - start + 1 for t in ('One', 'Two', 'Three')],
           f'contents {listed}, bookmarks {marks}')
    doc.close()


def test_epub():
    print("\nepub")
    import epub
    import test_outputs
    out = os.path.join(TMP, 'ref.epub')
    epub.build_epub(manuscript.parse_markdown(_fixture()), _preset(toc__depth=3), out,
                    {'title': 'The Valley Book', 'author': 'A. Writer', 'include_toc': True})
    problems = test_outputs.validate(out)
    _check("the EPUB validates", not problems, problems)
    z = zipfile.ZipFile(out)
    ch = z.read('OEBPS/chapter001.xhtml').decode('utf-8')
    _check("`###` is an h3 and `####` an h4, with ids",
           # each holds the empty target a link to it lands on (#74 Phase 5b)
           '<h3 id="h2"><span id="at-a1-the-porch"></span>A1. The Porch</h3>' in ch
           and '<h4 id="h3"><span id="at-hazards"></span>Hazards</h4>' in ch, ch[:1200])
    _check("the tagline is under the title",
           '<p class="chapter-tagline">Where the bells still ring below the water.</p>' in ch)
    nav = z.read('OEBPS/nav.xhtml').decode('utf-8')
    _check("the navigation nests sections under their subhead",
           re.search(r'Approaching the Chapel</a><ol><li><a href="chapter001.xhtml#h2">'
                     r'A1. The Porch</a></li>', nav) is not None, nav)
    _check("…and leaves `####` out at depth 3", 'Hazards' not in nav)
    toc = z.read('OEBPS/toc.xhtml').decode('utf-8')
    _check("the contents page links to sections", 'chapter001.xhtml#h2' in toc)
    _check("a sub-section straight under a chapter nests one step",
           'chapter003.xhtml">Untagged</a></li>' in nav, nav[-600:])
    css = z.read('OEBPS/style.css').decode('utf-8')
    _check("heading styles reach the stylesheet", re.search(r'h3 \{[^}]*bold', css) is not None)


def _docx(path, levels, title=None):
    from docx import Document
    doc = Document()
    if title:
        doc.add_heading(title[1], level=title[0])
    for lvl, text in levels:
        doc.add_heading(text, level=lvl)
        doc.add_paragraph(f'Prose under {text}.')
    doc.save(path)


def test_word():
    print("\nword headings by level")
    p = os.path.join(TMP, 'levels.docx')
    _docx(p, [(1, 'Chapter A'), (2, 'Sub'), (3, 'Room'), (4, 'Detail'), (5, 'Deep')])
    md = manuscript.import_docx(p)
    heads = [ln for ln in md.split('\n') if ln.startswith('#')]
    _check("Heading 1–4 import as `#` to `####`; deeper stays `####`",
           heads == ['# Chapter A', '## Sub', '### Room', '#### Detail', '#### Deep'], heads)

    _docx(p, [(2, 'Encounter One'), (3, 'The Setup'), (4, 'Read Aloud'),
              (2, 'Encounter Two'), (3, 'Hazards')])
    md = manuscript.import_docx(p)
    heads = [ln for ln in md.split('\n') if ln.startswith('#') or ln.startswith('~~~ ')]
    _check("no Heading 1: the top level used becomes the chapters",
           heads == ['# Encounter One', '## The Setup', '~~~ readaloud title="Read Aloud"',
                     '# Encounter Two', '## Hazards'], heads)

    _docx(p, [(3, 'Encounter One'), (4, 'The Setup'), (3, 'Encounter Two')],
          title=(2, 'Volume One'))
    rep = {}
    md = manuscript.import_docx(p, rep)
    heads = [ln for ln in md.split('\n') if ln.startswith('#')]
    _check("a lone first top heading is the book's title, chapters a level down",
           heads == ['#* Volume One', '# Encounter One', '## The Setup', '# Encounter Two'],
           heads)
    _check("…and its words are kept", rep.get('chapters') == 3, rep)

    _docx(p, [(1, 'One'), (4, 'Pacing Note')])
    md = manuscript.import_docx(p)
    _check("a Pacing heading at any level is boxed",
           '~~~ sidebar title="Pacing Note" style="note"' in md, md)

    if os.path.isdir(LOCAL):
        md = manuscript.import_docx(os.path.join(LOCAL, 'Edenfall Vol1.docx'))
        ms = manuscript.parse_markdown(md)
        titled = [c for c in ms['chapters'] if c['title']]
        boxed = md.count('~~~ readaloud') + md.count('style="note"')
        _check("the author's adventure imports as chapters with its boxes",
               len(titled) >= 8 and ms['chapters'][0].get('unnumbered') and boxed == 5,
               (len(titled), boxed))
    else:
        print("  skip the author's adventure (not on this machine)")


def test_style_form():
    print("\nstyle form")
    import app
    form = {'rh_content': 'section', 'hd_section_style': 'italic',
            'hd_section_align': 'center', 'hd_section_size': '13',
            'hd_subsection_style': 'nonsense', 'toc_depth': '3'}
    with app.app.test_request_context():
        p = app.parse_preset_form(form)
    _check("the running head choice is saved", p['running_head']['content'] == 'section')
    _check("heading settings are saved",
           p['headings']['section_style'] == 'italic' and p['headings']['section_align'] == 'center'
           and p['headings']['section_size'] == 13.0, p['headings'])
    _check("an unknown choice falls back", p['headings']['subsection_style'] == 'italic')
    _check("the contents depth is saved", p['toc']['depth'] == 3)
    with app.app.test_request_context():
        p = app.parse_preset_form({'toc_depth': '9', 'rh_content': 'x'})
    _check("out-of-range choices fall back",
           p['toc']['depth'] == 1 and p['running_head']['content'] == 'book')


def test_back_compat():
    print("\nback-compat")
    # every book here was written when `###`, `####` and `#>` printed literally;
    # none uses them outside a fence, so none changes
    found = []
    for folder in ('sample', os.path.join('projects', 'manuscripts'),
                   os.path.join('test_fixtures', 'ttrpg')):
        d = os.path.join(HERE, folder)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            # reference.md is this phase's own; statblock_formats.md holds
            # Homebrewery text pasted with no fence on purpose, which only the
            # paste or the Word import wraps (its `### Actions` reads as a
            # heading outside one, as Phase 1 planned)
            if not fn.endswith('.md') or fn in ('reference.md', 'statblock_formats.md'):
                continue
            fence = False
            with open(os.path.join(d, fn), encoding='utf-8') as f:
                for ln in f:
                    if manuscript.DOCBLOCK_RE.match(ln):
                        fence = not fence
                    elif not fence and (manuscript.SECTION_RE.match(ln)
                                        or manuscript.SUBSECTION_RE.match(ln)
                                        or manuscript.TAGLINE_RE.match(ln)):
                        found.append(f'{folder}/{fn}: {ln.strip()}')
    _check("no existing book has a `###`, `####` or `#>` line outside a fence",
           not found, found[:5])


if __name__ == "__main__":
    test_parse()
    test_round_trip()
    test_pdf()
    test_contents_pages()
    test_epub()
    test_word()
    test_style_form()
    test_back_compat()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
