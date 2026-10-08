"""Game blocks (ROADMAP #74, Phase 1)  (run: python test_game_blocks.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

The stat block reader is checked against the specs prepared before any code:
`test_fixtures/ttrpg/statblock_lines.json` a line at a time, and
`statblock_formats.json` + `.md` a whole block at a time (every accepted format
reads into one model). Then the three blocks are built end to end.
"""

import collections
import copy
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import logging; logging.disable(logging.INFO)
import statblock
import manuscript
import doc_model

FIX = os.path.join(HERE, 'test_fixtures', 'ttrpg')
# the author's own books, kept local and never committed; tests that read them
# skip when the folder is absent
LOCAL = os.path.join(HERE, 'Edenfall for test')
TMP = tempfile.mkdtemp(prefix='ts-gameblocks-')

_failures = []


def _check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        if detail:
            print(f"         {detail}")
        _failures.append(label)


def _load(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as f:
        return f.read()


def _joined(name, text):
    """An entry as the specs write it: a name is `***Name.***` before the text."""
    if not name:
        return text
    return f'***{name}*** {text}' if text else f'***{name}***'


def test_lines():
    print("stat block lines (statblock_lines.json)")
    spec = json.loads(_load('statblock_lines.json'))
    for c in spec['cases']:
        r = statblock.classify(c['line'], c['at'])
        e = c['expect']
        k = e['kind']
        ok = False
        if k == 'ignore':
            ok = r['kind'] == 'ignore'
        elif k == 'section':
            ok = r == {'kind': 'section', 'name': e['name']}
        elif k == 'field':
            ok = r['kind'] == 'fields' and r['fields'] == [
                {'label': e['label'], 'value': e['value']}]
        elif k == 'fields':
            ok = r['kind'] == 'fields' and r['fields'] == e['fields']
        elif k == 'entry':
            ok = (r['kind'] == 'entry' and _joined(r['name'], r['text'])
                  == _joined(e.get('name', ''), e['text']))
        elif k == 'scores' and r['kind'] == 'scores':
            cells = [dict(x) for x in r['cells']]
            auto = statblock._finish_scores(cells)
            want = [dict(x, save=x.get('save', '')) for x in e['cells']]
            ok = cells == want and auto == e['auto']
        _check(f"{c['at']:7} {c['line'][:60]!r}", ok, f"got {r}")


def _fences(md):
    """Every `~~~ statblock` fence in a file: (attrs, body lines)."""
    import manuscript
    out = []
    for hdr, body in re.findall(r'^~~~ *(statblock[^\n]*)\n(.*?)\n~~~ *$', md,
                                flags=re.S | re.M | re.I):
        _, attrs = manuscript._parse_block_header(hdr)
        out.append((attrs, body.split('\n')))
    return out


def _model_view(m, plain=False):
    strip = (lambda t: re.sub(r'[*_]', '', t)) if plain else (lambda t: t)
    return {'name': m['name'], 'meta': m['meta'], 'fields': m['fields'],
            'scores': m['scores'],
            'sections': [{'name': s['name'],
                          'entries': [strip(_joined(e['name'], e['text']))
                                      for e in s['entries']]}
                         for s in m['sections']]}


def test_formats():
    print("stat block formats (statblock_formats.json)")
    spec = json.loads(_load('statblock_formats.json'))
    fences = _fences(_load('statblock_formats.md'))
    labels = ['1a', '1b', '2a', '2b', '3', '4', '5']
    _check("the formats file has one fence per format", len(fences) == len(labels))
    for lab, (attrs, body) in zip(labels, fences):
        m = statblock.read(body, attrs.get('name', ''), attrs.get('meta', ''))
        want = spec['models'][spec['expect'][lab].split()[0]]
        plain = lab == '1b'
        got = _model_view(m, plain)
        if plain:
            want = dict(want, sections=[
                {'name': s['name'],
                 'entries': [re.sub(r'[*_]', '', x) for x in s['entries']]}
                for s in want['sections']])
        diff = next((f"{k}: got {got.get(k)} want {want[k]}"
                     for k in want if got.get(k) != want[k]), '')
        _check(f"format {lab} reads into {spec['expect'][lab].split()[0]}",
               not diff, diff)


def test_unfenced():
    print("Homebrewery blocks pasted with no fence")
    md = _load('statblock_formats.md')
    tail = md[md.index('## Pasted with no fence'):]
    wrapped = statblock.wrap_unfenced(tail)
    fences = _fences(wrapped)
    _check("exactly two blocks are found and wrapped", len(fences) == 2,
           f"{len(fences)} found")
    for attrs, body in fences:
        m = statblock.read(body)
        labels = [f['label'] for f in m['fields']]
        _check(f"a wrapped block reads as the Bog-Thrall ({len(m['scores'])} scores)",
               m['name'] == 'Bog-Thrall' and 'Armor Class' in labels
               and 'Challenge' in labels and len(m['scores']) == 6
               and [s['name'] for s in m['sections']] == ['Actions'],
               f"{m}")
    for para in ('A paragraph between the two blocks', 'A closing paragraph'):
        line = next(ln for ln in wrapped.split('\n') if ln.startswith(para))
        _check(f"'{para[:24]}…' stays outside a fence",
               not any(line in '\n'.join(b) for _, b in fences))
    md_fenced = _load('statblock_formats.md')
    head = md_fenced[:md_fenced.index('## Pasted with no fence')]
    _check("blocks already in a fence are left alone",
           statblock.wrap_unfenced(head) == head)
    novel = "Chapter text.\n\n___\n\n> A quotation in a novel.\n\nMore."
    _check("a rule and a quotation in prose are not a stat block",
           statblock.wrap_unfenced(novel) == novel)


def test_modifiers():
    print("the modifier rule")
    for score, mod in ((1, '−5'), (3, '−4'), (8, '−1'), (9, '−1'), (10, '+0'),
                       (11, '+0'), (12, '+1'), (18, '+4'), (30, '+10'), (0, '−5')):
        _check(f"{score} -> {mod}", statblock.modifier(score) == mod)


def _blocks(ms, btype):
    return [b for ch in ms['chapters'] for b in ch['blocks']
            if b[0] == 'doc_block' and len(b) > 2 and b[2].get('_type') == btype]


def _build(md, name, trim=None, preset=None):
    """Build `md` to a PDF and an EPUB; (parsed, pdf text, epub problems)."""
    import app as A
    import engine
    import epub
    import fitz
    import test_outputs
    preset = copy.deepcopy(preset or A.DEFAULTS)
    if trim:
        preset['trim'] = {'w': trim[0], 'h': trim[1]}
    meta = {'title': 'Game Blocks', 'author': 'Test', 'year': '2026',
            'front_matter': 'none', 'include_toc': False, 'smartquotes': True}
    ms = manuscript.parse_markdown(md)
    pdf = os.path.join(TMP, name + '.pdf')
    engine.build_pdf(ms, preset, pdf, dict(meta))
    with fitz.open(pdf) as d:
        text = '\n'.join(p.get_text() for p in d)
        pages = d.page_count
    ep = os.path.join(TMP, name + '.epub')
    epub.build_epub(ms, preset, ep, dict(meta))
    return ms, text, pages, test_outputs.validate(ep)


def _words(text):
    # Latin script only: the bundled body faces have no Greek, Cyrillic or CJK
    # glyphs, which is a font question older than these blocks
    return re.findall(r"[A-Za-z\u00c0-\u024f]+", text)


def test_parse():
    print("the parser")
    ms = manuscript.parse_markdown(_load('edge_cases.md'))
    sbs = _blocks(ms, 'statblock')
    names = [b[2]['_statblock']['name'] for b in sbs]
    _check("every stat block in the edge cases is one block",
           len(sbs) == 16, f"{len(sbs)}: {names}")
    by = {b[2]['_statblock']['name']: b[2]['_statblock'] for b in sbs}
    _check("an empty stat block keeps its name", 'Nameless Thing' in by)
    _check("no attributes and a field: no name, one field",
           any(not m['name'] and m['fields'] == [{'label': 'Armor Class', 'value': '10'}]
               for m in by.values()))
    _check("curly-quoted attributes are read (case 13)",
           by.get('Curly Quotes', {}).get('meta') == 'Medium fey')
    _check("a block type in capitals is the same block (case 19)", 'Shouty' in by)
    _check("the name attribute is escaped, not read as markup (case 12)",
           'Tom &amp; Jerry &lt;the twins&gt;' in by)
    _check("... and the meta keeps its asterisks",
           by['Tom &amp; Jerry &lt;the twins&gt;']['meta'] == 'Small *humanoid*, 50% evil')
    rules = by['Rules']['sections']
    _check("`---` and `--- ` are bare rules; `\\---` is an entry with its hyphens",
           [s['name'] for s in rules] == ['', '', 'Actions']
           and rules[1]['entries'][0]['text'] == '--- not a section', rules)
    marked = by['Marked Up']
    _check("emphasis and links inside a field are inlined",
           '<i>Common</i>' in marked['fields'][0]['value']
           and '<a href="https://example.com/aquan">' in marked['fields'][0]['value'])
    _check("an endnote inside an entry is numbered",
           '<note n="1" id="strike"/>' in marked['sections'][0]['entries'][0]['text'])
    _check("a stat block left open at the end of the file is closed",
           by['Unclosed']['sections'][0]['entries'][0]['name'] == 'Last Word.')
    ra = _blocks(ms, 'readaloud')
    _check("an empty read-aloud box is kept, and one with two paragraphs keeps both",
           [len(b[1]) for b in ra] == [0, 2, 1], [len(b[1]) for b in ra])
    sd = _blocks(ms, 'sidebar')
    _check("sidebars keep their titles", [b[2].get('title') for b in sd][:3]
           == ["Rule #1: Don't Panic & Don't Run", 'Empty', None])
    fig = manuscript.parse_markdown('~~~ figure src=\u201cmap.png\u201d\nCap.\n~~~\n')
    _check("a curly-quoted figure src is read (it was silently dropped)",
           _blocks(fig, 'figure')[0][2].get('src') == 'map.png')


def test_round_trip():
    print("the editor's round trip")
    for name in ('adventure.md', 'statblocks.md', 'statblock_formats.md', 'edge_cases.md'):
        md = _load(name)
        for sq in (True, False):
            m = doc_model.from_markdown(md, sq)
            back = doc_model.to_markdown(m)
            _check(f"{name} (smart quotes {'on' if sq else 'off'}): fidelity and stability",
                   manuscript.parse_markdown(md, sq) == manuscript.parse_markdown(back, sq)
                   and doc_model.from_markdown(back, sq) == m)
    md = _load('statblock_formats.md')
    body = md[md.index('\n~~~ statblock\n') + 1:md.index('## Format 3')]
    back = doc_model.to_markdown(doc_model.from_markdown(body))
    _check("stat block lines come back exactly as written (formats 1 and 2)",
           all(ln in back.split('\n') for ln in body.split('\n')
               if ln.strip() and not ln.startswith('## Format')))   # a subhead is smartened
    esc = '~~~ statblock\n\\--- literal\n--- Actions\n~~~\n'
    _check("`\\---` keeps one backslash through the round trip",
           doc_model.to_markdown(doc_model.from_markdown(esc)) == esc)
    curly = '~~~ statblock name=\u201cA\u201d\nAC: 1\n~~~\n'
    _check("curly-quoted attributes are written back with straight quotes",
           doc_model.to_markdown(doc_model.from_markdown(curly)).startswith(
               '~~~ statblock name="A"'))


def test_builds():
    print("the PDF and the EPUB")
    for name in ('adventure.md', 'statblocks.md', 'statblock_formats.md', 'edge_cases.md'):
        try:
            ms, text, pages, probs = _build(_load(name), name[:-3], trim=(5, 8))
        except Exception as exc:
            _check(f"{name} builds", False, f"{type(exc).__name__}: {exc}")
            continue
        _check(f"{name} builds ({pages} pages) and its EPUB is valid", not probs, probs)
        # every entry and every field value of every stat block is printed
        missing = []
        for b in _blocks(ms, 'statblock'):
            m = b[2]['_statblock']
            for piece in [f['value'] for f in m['fields']] + [
                    e['text'] for s in m['sections'] for e in s['entries']]:
                words = _words(re.sub(r'<[^>]+>', '', piece))
                if words and not all(w in text for w in words):
                    missing.append(piece[:40])
        _check(f"{name}: every field and entry is printed", not missing, missing[:3])
    _, text, _, _ = _build(_load('edge_cases.md'), 'edge-text')
    _check("an escaped `---` prints as hyphens, not an em dash",
           '--- not a section' in text)
    _check("a stat block's name prints in capitals, escaped characters as written",
           'TOM & JERRY <THE TWINS>' in text and 'Small *humanoid*, 50% evil' in text)
    _check("worked-out modifiers print with a true minus", '1 (\u22125)' in text)


def test_splits():
    print("a stat block taller than a page")
    lines = ['~~~ statblock name="Long Thing" meta="Huge test, unaligned"',
             'Armor Class: 10', 'STR 10 | DEX 10 | CON 10 | INT 10 | WIS 10 | CHA 10',
             '--- Actions']
    lines += [f'***Entry {i}.*** Ability number {i} of the long thing, with words to wrap '
              f'over a line or two in a narrow column marker{i}x.' for i in range(1, 121)]
    lines += ['~~~', '']
    md = '# Long\n\n' + '\n'.join(lines)
    _, text, pages, _ = _build(md, 'long', trim=(5, 8))
    lost = [i for i in range(1, 121) if f'marker{i}x' not in text]
    _check(f"120 entries split over {pages} pages and none is lost", pages > 3 and not lost, lost)
    huge = '# Huge\n\n~~~ statblock name="Wall"\n--- Actions\n***Wall.*** ' + \
           ('word ' * 3000) + '\n~~~\n'
    try:
        _, text, pages, _ = _build(huge, 'huge', trim=(5, 8))
        _check(f"one entry taller than a page splits too ({pages} pages)",
               text.count('word') >= 3000)
    except Exception as exc:
        _check("one entry taller than a page splits too", False, f"{type(exc).__name__}: {exc}")


def test_style():
    print("the style: defaults, the form and large print")
    import app as A
    import engine
    from werkzeug.datastructures import MultiDict
    for sec in ('readaloud', 'sidebar', 'statblock'):
        _check(f"DEFAULTS has the {sec} section", A.DEFAULTS.get(sec) ==
               engine.GAME_BLOCK_DEFAULTS[sec])
        d = engine.GAME_BLOCK_DEFAULTS[sec]
        prints = [k for k in d if k.startswith('print_')]
        _check(f"every {sec} colour has a print twin",
               all('print_' + k in d for k in d if k in ('fill', 'rule_color', 'border_color',
                                                         'title_fill', 'title_color',
                                                         'name_color')) and prints)
    out = A.parse_preset_form(MultiDict({'sk_scores': 'grid', 'sk_print_fill': '#eeeeee',
                                          'sk_rule_width': '99', 'sk__form': '1',
                                          'sk_print_rule_color': 'red'}))
    sk = out['statblock']
    _check("the form reads a stat block setting", sk['scores'] == 'grid'
           and sk['print_fill'] == '#eeeeee')
    _check("a number is held to its range", sk['rule_width'] == 12.0)
    _check("a colour that isn't #rrggbb keeps the default",
           sk['print_rule_color'] == engine.GAME_BLOCK_DEFAULTS['statblock']['print_rule_color'])
    _check("an unticked box with the form's marker is off", sk['name_caps'] is False)
    _check("a form without the section keeps every default",
           A.parse_preset_form(MultiDict())['sidebar'] == engine.GAME_BLOCK_DEFAULTS['sidebar'])
    _check("hidden screen colours ride along",
           A.parse_preset_form(MultiDict({'ra_fill': '#123456'}))['readaloud']['fill']
           == '#123456')
    lp = A.make_large_print(dict(A.DEFAULTS, statblock=dict(
        engine.GAME_BLOCK_DEFAULTS['statblock'], font_size=9.0, name_size=12.0)))
    _check("large print scales a stat block's sizes",
           lp['statblock']['font_size'] > 9.0 and lp['statblock']['name_size'] > 12.0)
    with A.app.test_client() as c:
        page = c.get('/editor/new').get_data(as_text=True)
    _check("the style editor shows the three sections",
           all(f'name="{p}__form"' in page for p in ('ra', 'sd', 'sk')))
    old = copy.deepcopy(A.DEFAULTS)
    for sec in ('readaloud', 'sidebar', 'statblock'):
        old.pop(sec)
    try:
        _, _, _, probs = _build(_load('adventure.md'), 'old-style', preset=old)
        _check("a style from before the game blocks builds them with the defaults", not probs)
    except Exception as exc:
        _check("a style from before the game blocks builds them", False, str(exc))


def _make_docx(path):
    """A small Word game book in the author's shape: a bold name, an italic
    meta line, bold labels with no colon, a one-row score table, a bold
    section paragraph, bold-italic entries, then a Lore paragraph; and a
    "Read Aloud" heading over boxed text."""
    from docx import Document
    doc = Document()
    doc.add_heading('Creatures', level=1)
    doc.add_paragraph('An introduction that is not a stat block.')

    def bold_para(text, italic=False):
        r = doc.add_paragraph().add_run(text)
        r.bold, r.italic = True, italic

    def labelled(label, value):
        p = doc.add_paragraph()
        p.add_run(label).bold = True
        p.add_run(' ' + value)

    for name in ('Mire Hound', 'Reed Wisp'):
        bold_para(name)
        doc.add_paragraph().add_run('Medium beast, unaligned').italic = True
        labelled('Armor Class', '12')
        labelled('Hit Points', '9 (2d8)')
        t = doc.add_table(rows=1, cols=6)
        for cell, txt in zip(t.rows[0].cells, ('STR 12 (+1)', 'DEX 14 (+2)', 'CON 10 (+0)',
                                               'INT 3 (-4)', 'WIS 12 (+1)', 'CHA 6 (-2)')):
            cell.text = txt
        labelled('Challenge', '1/4 (50 XP)')
        bold_para('Actions')
        p = doc.add_paragraph()
        r = p.add_run('Bite.')
        r.bold = r.italic = True
        p.add_run(' Melee Weapon Attack: +3 to hit.')
        bold_para('Lore', italic=True)
        doc.add_paragraph(f'The {name.lower()} is prose about the creature, outside the block.')
    doc.add_heading('Read Aloud', level=2)
    doc.add_paragraph('The mist parts. Something waits on the causeway.')
    doc.add_paragraph('It does not move.')
    doc.add_heading('What Happens Next', level=2)
    doc.add_paragraph('Prose for the game master.')
    doc.add_heading('Pacing', level=2)
    doc.add_paragraph('This should take ten minutes.')
    doc.save(path)


def test_word_import():
    print("Word import of game blocks")
    path = os.path.join(TMP, 'game.docx')
    _make_docx(path)
    rep = {}
    md = manuscript.import_docx(path, rep)
    ms = manuscript.parse_markdown(md)
    sbs = _blocks(ms, 'statblock')
    _check("two stat blocks in, two out", len(sbs) == 2 and rep.get('statblocks') == 2, rep)
    m = sbs[0][2]['_statblock']
    _check("the name, meta, fields and scores are read",
           m['name'] == 'Mire Hound' and m['meta'] == 'Medium beast, unaligned'
           and [f['label'] for f in m['fields']] == ['Armor Class', 'Hit Points', 'Challenge']
           and len(m['scores']) == 6 and m['scores'][3]['mod'] == '\u22124', m)
    _check("the block ends before the Lore paragraph",
           [s['name'] for s in m['sections']] == ['Actions']
           and 'prose about the creature' not in json.dumps(m))
    paras = [b[1] for ch in ms['chapters'] for b in ch['blocks'] if b[0] == 'para']
    _check("the introduction and the Lore stay prose",
           any('introduction' in p for p in paras)
           and sum('prose about the creature' in p for p in paras) == 2)
    ra = _blocks(ms, 'readaloud')
    _check("a Read Aloud heading boxes the paragraphs under it",
           len(ra) == 1 and len(ra[0][1]) == 2 and ra[0][2].get('title') == 'Read Aloud')
    _check("... and only those", any('Prose for the game master' in p for p in paras))
    note = _blocks(ms, 'sidebar')
    _check("a Pacing heading becomes a note",
           len(note) == 1 and note[0][2].get('style') == 'note')
    _check("the summary counts them",
           'stat block' in ' '.join(manuscript.import_summary(rep)), manuscript.import_summary(rep))

    best = os.path.join(LOCAL, 'Edenfall Bestiary Volume 1.docx')
    if not os.path.exists(best):
        print("  skip the author's Bestiary (not on this machine)")
        return
    rep = {}
    keep = manuscript.game_blocks_from_import
    manuscript.game_blocks_from_import = lambda lines, r: lines
    try:
        plain = manuscript.import_docx(best, {})
    finally:
        manuscript.game_blocks_from_import = keep
    md = manuscript.import_docx(best, rep)
    tables = plain.count('~~~ table')
    sbs = _blocks(manuscript.parse_markdown(md), 'statblock')
    _check(f"the Bestiary: {tables} score tables in, the same number of stat blocks out",
           len(sbs) == tables == 71 and all(len(b[2]['_statblock']['scores']) == 6 for b in sbs),
           f"{len(sbs)} of {tables}")

    def words(t):
        t = re.sub(r'^~~~.*$', '', t, flags=re.M)
        return collections.Counter(re.findall(r'[^\s|*]+', t))
    _check("... every word kept", words(plain) == words(md))
    _check("... and nothing else turned into a block",
           not _blocks(manuscript.parse_markdown(md), 'readaloud')
           and not _blocks(manuscript.parse_markdown(md), 'sidebar'))


if __name__ == "__main__":
    test_lines()
    test_formats()
    test_unfenced()
    test_modifiers()
    test_parse()
    test_round_trip()
    test_builds()
    test_splits()
    test_style()
    test_word_import()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
