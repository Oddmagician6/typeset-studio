"""Two columns (ROADMAP #74, Phase 4)  (run: python test_columns.py [gates, e.g. 1,2,5]).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

This is the Phase 4 spike, kept as the feature's test: the six gates the
roadmap set before any feature code. Each builds real books through
`engine.build_pdf` with a style whose `columns.count` is 2 and measures the PDF:

  1. mirrored margins: each column's x on recto and verso, and a balanced end;
  2. every block type at column width, nothing across the gutter, nothing scaled,
     headings in a run still in the contents and the bookmarks;
  3. spanning elements (the opener, `span="yes"`) between balanced runs;
  4. footnotes at the foot of a two-column page, each on its reference's page;
  5. no words lost, and no loop on something taller than a column;
  6. a long book in two columns, timed against one (needs the generated long
     book: `python test_fixtures/ttrpg/make_long_book.py`; skipped without it).

Gate 7 is the feature built on them: the style editor's Columns fields,
`balance_end`, the two bundled two-column styles in print and on screen, and
the headings of a boxed block kept off the foot of a column.
"""
import copy, json, os, re, sys, tempfile, time, traceback
from collections import Counter

REPO = os.path.dirname(os.path.abspath(__file__))
GATES = set(sys.argv[1].split(',')) if len(sys.argv) > 1 else set('1234567')
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, engine, app as A

TMP = tempfile.mkdtemp(prefix='ts-cols-')
FIX = os.path.join(REPO, 'test_fixtures', 'ttrpg')
INCH = 72.0
results = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (('\n         ' + str(detail)) if detail and not cond else ''))
    results.append((label, bool(cond)))


def preset(cols=2, **sections):
    p = copy.deepcopy(A.DEFAULTS)
    p['trim'] = {'w': 8.5, 'h': 11.0}
    p['margins'] = dict(p['margins'], top=0.85, bottom=0.85, inside=1.0, outside=0.7)
    p['body'] = dict(p['body'], hyphenate=False)
    if cols == 2:
        p['columns'] = {'count': 2, 'gap': 0.25}
    for k, v in sections.items():
        p[k] = {**p.get(k, {}), **v}
    return p


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True,
        # these tests read the body's pages; the stat-block index (on by
        # default since 1.5.0) would add an Index page to every game book
        'index_statblocks': False, 'index_cr': False}


def build(md, p, name, **meta):
    out = os.path.join(TMP, name + '.pdf')
    t = time.time()
    res = engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta))
    res['seconds'] = round(time.time() - t, 2)
    return out, res


def words(pdf):
    with fitz.open(pdf) as d:
        text = '\n'.join(pg.get_text() for pg in d)
    return Counter(re.findall(r"[A-Za-z0-9']+", text))


def body_words(pdf, p):
    """Words inside the text block only (no running heads or folios)."""
    top = p['margins']['top'] * INCH - 2
    bot = (p['trim']['h'] - p['margins']['bottom']) * INCH + 2
    c = Counter()
    with fitz.open(pdf) as d:
        for pg in d:
            for x0, y0, x1, y1, w, *_ in pg.get_text('words'):
                if y0 >= top - 4 and y1 <= bot + 6:
                    c.update(re.findall(r"[A-Za-z0-9']+", w))
    return c


def spans(pdf):
    with fitz.open(pdf) as d:
        for pno, pg in enumerate(d, start=1):
            for b in pg.get_text('dict')['blocks']:
                for ln in b.get('lines', []):
                    for sp in ln['spans']:
                        if sp['text'].strip():
                            yield pno, sp


def read(name):
    return open(os.path.join(FIX, name), encoding='utf-8').read()


LOREM = ("The tide comes in over the causeway twice a day and the bell under the "
         "water answers it. Nobody in the village will say who hung it there. ")


def para(n, tag=''):
    return ' '.join((LOREM + f'Marker{tag}x{i}. ') for i in range(n))


def picture(name, w, h):
    from PIL import Image
    path = os.path.join(TMP, name)
    Image.new('RGB', (w, h), (120, 140, 160)).save(path)
    return path.replace('\\', '/')


# ---------------------------------------------------------------- gate 1
def gate1():
    print('\nGate 1: mirrored margins, column x positions on recto and verso')
    md = '# The Causeway\n\n' + '\n\n'.join(para(3, f'p{i}') for i in range(60))
    p = preset()
    pdf, res = build(md, p, 'g1')
    m = p['margins']
    tw = (p['trim']['w'] - m['inside'] - m['outside']) * INCH
    gap = 0.25 * INCH
    cw = (tw - gap) / 2
    bad, seen = [], Counter()
    with fitz.open(pdf) as d:
        n = d.page_count
        for pno, pg in enumerate(d, start=1):
            left = (m['inside'] if pno % 2 else m['outside']) * INCH
            exp = [left, left + cw + gap]
            top = m['top'] * INCH
            bot = (p['trim']['h'] - m['bottom']) * INCH
            xs = Counter()
            first_body = min([ln['bbox'][1] for b in pg.get_text('dict')['blocks'] for ln in b.get('lines', [])
                              if 'tide comes' in ''.join(sp['text'] for sp in ln['spans'])] or [0])
            for b in pg.get_text('dict')['blocks']:
                for ln in b.get('lines', []):
                    x0, y0, x1, y1 = ln['bbox']
                    if y0 < top - 1 or y1 > bot + 1:
                        continue
                    if pno == 1 and 'Marker' not in ''.join(sp['text'] for sp in ln['spans']) and y1 < first_body:
                        continue
                    col = min(range(2), key=lambda i: abs(exp[i] - x0))
                    # a line starts at its column's left edge (or its indent)
                    if not (exp[col] - 0.6 <= x0 and x1 <= exp[col] + cw + 0.6):
                        bad.append((pno, round(x0, 1), round(x1, 1), [round(e, 1) for e in exp]))
                    xs[col] += 1
            if pno < n and not (xs[0] and xs[1]):
                bad.append((pno, 'a column is empty', dict(xs)))
            seen[pno % 2] += 1
    check(f'{n} pages, both parities seen', n >= 4 and seen[0] and seen[1], seen)
    # one column mirrors too: the text block's left edge follows the page's parity
    p1 = preset(1)
    pdf1, _ = build(md, p1, 'g1-one')
    off = []
    with fitz.open(pdf1) as d:
        for pno, pg in enumerate(d, start=1):
            xs = [b[0] for b in pg.get_text('blocks') if b[2] - b[0] > 200 and 'tide comes' in b[4]]
            want = (m['inside'] if pno % 2 else m['outside']) * INCH
            if xs and abs(min(xs) - want) > 0.6:
                off.append((pno, round(min(xs), 1), want))
    check('one column: inside margin at the spine on recto and verso', not off, off[:4])
    check('every line sits inside its column, recto and verso', not bad, bad[:5])
    # the last page is balanced: both columns end within two lines of each other
    with fitz.open(pdf) as d:
        pg = d[-1]
        left = (m['inside'] if d.page_count % 2 else m['outside']) * INCH
        ends = [0, 0]
        for b in pg.get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                x0, y0, x1, y1 = ln['bbox']
                if m['top'] * INCH <= y0 and y1 <= (p['trim']['h'] - m['bottom']) * INCH:
                    ends[0 if x0 < left + cw + gap / 2 else 1] = max(ends[0 if x0 < left + cw + gap / 2 else 1], y1)
    check('the run is balanced at its end', abs(ends[0] - ends[1]) <= 3 * 15, ends)


# ---------------------------------------------------------------- gate 2
def all_blocks_md():
    pic = picture('wide.png', 1200, 500)
    tall = picture('tall.png', 400, 1400)
    return f'''# The Guard Room

{para(2, 'open')}

## Approaching the gate

{para(2, 'a')}

### A1. Gatehouse

{para(1, 'b')}

#### Treasure

{para(1, 'c')}

~~~ readaloud title="At the door"
The door stands open and the lamp inside has burned down to a blue point. Something breathes behind the racks.
~~~

{para(2, 'd')}

~~~ sidebar title="Running the watch"
The watch changes at the bell. A party that waits for it meets half as many guards and twice as much suspicion.
~~~

~~~ sidebar style="note" title="Pacing"
Keep this scene short.
~~~

~~~ statblock cr="2"
Gate Warden
Medium humanoid, lawful neutral

Armor Class: 16 (chain)
Hit Points: 39 (6d8 + 12)
Speed: 30 ft.

STR 15 DEX 11 CON 14 INT 10 WIS 13 CHA 9

Senses: passive Perception 13
Languages: Common

### Actions
***Halberd.*** Melee weapon attack: +4 to hit, reach 10 ft. Hit: 7 (1d10 + 2) slashing damage.
***Horn.*** The warden sounds the horn and the gate begins to close.
~~~

{para(1, 'e')}

~~~ figure src="{pic}" width="1.0"
The gatehouse from the causeway.
~~~

{para(1, 'f')}

~~~ figure src="{tall}"
A tall plate, taller than it is wide.
~~~

~~~ table
Roll | Encounter | Notes
1 | Two wardens on patrol | They carry a horn
2 | A pedlar with a lame mule | Knows the tide tables by heart
3 | Nothing but gulls | The bell rings once
4 | A drowned lantern, still lit | It is cold to the touch
~~~

~~~ list
- A coil of tarred rope
- Three iron spikes
- A lantern with a cracked pane and enough oil for one more night of walking
~~~

~~~ quote
We rang it for the dead and then the dead rang back.
~~~

~~~ poem
Low water, slow water,
bell below the stone,
count the steps you came by
and go back alone.
~~~

~~~ letter
Warden, the tide tables are wrong again. Send the boy before the bell.
~~~

~~~ center
Here the causeway ends.
~~~

{para(2, 'g')}

* * *

{para(3, 'h')}
'''


def gate2():
    print('\nGate 2: every block type at column width')
    md = all_blocks_md()
    p1, p2 = preset(1), preset(2)
    try:
        pdf1, _ = build(md, p1, 'g2-one')
        pdf2, res = build(md, p2, 'g2-two')
    except Exception as exc:
        check('builds', False, traceback.format_exc()[-900:])
        return
    check('builds', True)
    m = p2['margins']
    tw = (p2['trim']['w'] - m['inside'] - m['outside']) * INCH
    gap = 0.25 * INCH
    cw = (tw - gap) / 2
    cross, sizes2 = [], Counter()
    with fitz.open(pdf2) as d:
        for pno, pg in enumerate(d, start=1):
            left = (m['inside'] if pno % 2 else m['outside']) * INCH
            gut0, gut1 = left + cw, left + cw + gap
            top = m['top'] * INCH
            bot = (p2['trim']['h'] - m['bottom']) * INCH
            opener_bottom = 0
            for b in pg.get_text('dict')['blocks']:
                for ln in b.get('lines', []):
                    for sp in ln['spans']:
                        if not sp['text'].strip():
                            continue
                        x0, y0, x1, y1 = sp['bbox']
                        if y0 < top - 1 or y1 > bot + 1:
                            continue
                        if 'Guard Room' in sp['text'] or sp['text'].strip().startswith('Chapter'):
                            opener_bottom = max(opener_bottom, y1)
                            continue
                        sizes2[round(sp['size'], 1)] += 1
                        if x0 < gut0 - 0.6 and x1 > gut1 + 0.6:
                            cross.append((pno, sp['text'][:30]))
                        elif x0 < left - 0.6 or x1 > left + tw + 0.6:
                            cross.append((pno, 'outside the text block', sp['text'][:30]))
                        elif gut0 + 0.6 < x1 < gut1 - 0.6 and x0 < gut0:
                            cross.append((pno, 'ends in the gutter', sp['text'][:30]))
            # pictures and boxes stay in a column too
            for img in pg.get_image_info():
                x0, y0, x1, y1 = img['bbox']
                if x0 < gut0 - 0.6 and x1 > gut1 + 0.6:
                    cross.append((pno, 'image across the gutter'))
                if y1 > bot + 1 or y0 < top - 1:
                    cross.append((pno, 'image outside the text block', round(y0), round(y1)))
            for dr in pg.get_drawings():
                r = dr['rect']
                if top < r.y0 and r.y1 < bot and r.x0 < gut0 - 1 and r.x1 > gut1 + 1 and r.height > 2:
                    cross.append((pno, 'box across the gutter', [round(v) for v in r]))
    check('nothing crosses the gutter or leaves the text block', not cross, cross[:6])
    sizes1 = Counter()
    for _, sp in spans(pdf1):
        sizes1[round(sp['size'], 1)] += 1
    odd = sorted(s for s in sizes2 if s not in sizes1)
    check('no text was scaled (every size also occurs in one column)', not odd, (odd, sorted(sizes1)))
    w1, w2 = body_words(pdf1, p1), body_words(pdf2, p2)
    for k in ('Roll', 'Encounter', 'Notes'):      # a split table repeats its header
        w1.pop(k, None); w2.pop(k, None)
    check('same words as one column', w1 == w2, ((w1 - w2).most_common(8), (w2 - w1).most_common(8)))
    # fixtures
    for name in ('edge_cases.md', 'adventure.md', 'statblocks.md', 'reference.md'):
        try:
            a, _ = build(read(name), preset(1), 'g2-1-' + name[:-3])
            b, _ = build(read(name), preset(2), 'g2-2-' + name[:-3])
            wa, wb = body_words(a, p1), body_words(b, p2)
            hdr = set()
            src = read(name).splitlines()
            for i, line in enumerate(src):
                if line.startswith('~~~ table') and i + 1 < len(src):
                    hdr.update(re.findall(r"[A-Za-z0-9']+", src[i + 1]))
            for k in hdr:
                wa.pop(k, None); wb.pop(k, None)
            check(f'{name}: builds, same words as one column', wa == wb,
                  ((wa - wb).most_common(8), (wb - wa).most_common(8)))
        except Exception as exc:
            check(f'{name}: builds', False, '%s: %s' % (type(exc).__name__, str(exc)[:400]))
    # headings inside a run still reach the contents, the bookmarks, the running head
    try:
        pdf, _ = build(md, preset(2, toc={'depth': 4}, running_head={'content': 'section'}),
                       'g2-toc', include_toc=True)
        with fitz.open(pdf) as d:
            toc = [t[1] for t in d.get_toc()]
            first = d[0].get_text() + d[1].get_text()
        check('bookmarks reach the headings in a run',
              any('Approaching' in t for t in toc) and any('Gatehouse' in t for t in toc), toc)
        check('the contents page lists them', 'Approaching the gate' in first and 'A1. Gatehouse' in first, first[:300])
    except Exception as exc:
        check('contents and bookmarks build', False, traceback.format_exc()[-600:])


# ---------------------------------------------------------------- gate 3
def gate3():
    print('\nGate 3: spanning elements')
    pic = picture('span.png', 1600, 500)
    md = f'''# The Long Stair

{para(6, 'before')}

~~~ table span="yes"
Step | What waits there | How it is passed | What it costs
1 | A warden asleep at his post | Quietly | Nothing
2 | A gate with no lock | By asking | A name
3 | The bell rope | By leaving it alone | Nothing at all
~~~

{para(6, 'between')}

~~~ figure src="{pic}" span="yes" width="1.0"
The stair in section.
~~~

{para(6, 'after')}
'''
    p = preset()
    try:
        pdf, res = build(md, p, 'g3')
    except Exception:
        check('builds', False, traceback.format_exc()[-900:])
        return
    m = p['margins']
    tw = (p['trim']['w'] - m['inside'] - m['outside']) * INCH
    cw = (tw - 18) / 2
    with fitz.open(pdf) as d:
        pg = d[0]
        left = m['inside'] * INCH
        mid = left + tw / 2
        ys = {}
        for b in pg.get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                for sp in ln['spans']:
                    t = sp['text']
                    for tag in ('before', 'between', 'after'):
                        if 'Marker' + tag in t:
                            col = 0 if sp['bbox'][0] < mid else 1
                            k = (tag, col)
                            lo, hi = ys.get(k, (9e9, 0))
                            ys[k] = (min(lo, sp['bbox'][1]), max(hi, sp['bbox'][3]))
                    if 'What waits there' in t:
                        ys['table'] = sp['bbox']
                    if 'The Long Stair' in t:
                        ys['title'] = sp['bbox']
        imgs = [i['bbox'] for i in pg.get_image_info()]
        n = d.page_count
    check('one page, title set across the measure', n >= 1 and 'title' in ys
          and abs((ys['title'][0] + ys['title'][2]) / 2 - mid) < 4, ys.get('title'))
    ok = all((t, c) in ys for t in ('before', 'between') for c in (0, 1))
    check('the runs before and between use both columns', ok, sorted(k for k in ys if isinstance(k, tuple)))
    if ok and 'table' in ys:
        b_end = max(ys[('before', 0)][1], ys[('before', 1)][1])
        t_y = ys['table'][1]
        bt_start = min(ys[('between', 0)][0], ys[('between', 1)][0])
        check('order down the page: run, spanning table, run',
              b_end < t_y < bt_start, (b_end, t_y, bt_start))
        check('the run above the table is balanced',
              abs(ys[('before', 0)][1] - ys[('before', 1)][1]) <= 45,
              (ys[('before', 0)], ys[('before', 1)]))
    check('the spanning figure is wider than a column', bool(imgs) and
          any(b[2] - b[0] > cw + 20 for b in imgs), imgs) if n == 1 else None
    if n > 1:
        with fitz.open(pdf) as d:
            imgs = [i['bbox'] for pg in d for i in pg.get_image_info()]
        check('the spanning figure is wider than a column', any(b[2] - b[0] > cw + 20 for b in imgs), imgs)
    w = words(pdf)
    check('all three runs are in the PDF', all(w['Marker%sx5' % t] == 1 for t in ('before', 'between', 'after')),
          [w['Marker%sx5' % t] for t in ('before', 'between', 'after')])


# ---------------------------------------------------------------- gate 4
def gate4():
    print('\nGate 4: footnotes at the foot of a two-column page')
    paras, notes = [], []
    for i in range(40):
        t = para(2, f'n{i}')
        if i % 3 == 0:
            t += f' It is written in the tide book.[^n{i}]'
            notes.append(f'[^n{i}]: Note {i}: the tide book is kept by the warden and nobody else may read it.')
        paras.append(t)
    md = ('# The Tide Book\n\nFirst words of the chapter carry a note.[^first] ' + para(1, 'o') + '\n\n'
          + '\n\n'.join(paras) + '\n\n[^first]: The opening note.\n' + '\n'.join(notes) + '\n')
    p = preset(2, endnotes={'placement': 'foot'})
    try:
        pdf, res = build(md, p, 'g4')
    except Exception:
        check('builds', False, traceback.format_exc()[-900:])
        return
    check('no note left without a page', res['notes_unplaced'] == 0, res['notes_unplaced'])
    m = p['margins']
    bot = (p['trim']['h'] - m['bottom']) * INCH
    wrong, overlap, total = [], [], 0
    with fitz.open(pdf) as d:
        for pno, pg in enumerate(d, start=1):
            text = pg.get_text()
            refs = set()
            for link in pg.get_links():
                uri = link.get('uri') or ''
                if uri.startswith(engine._FN_SCHEME):
                    refs.add(int(uri[len(engine._FN_SCHEME):].split('-')[1]))
            note_y, body_y = 9e9, 0
            for b in pg.get_text('dict')['blocks']:
                for ln in b.get('lines', []):
                    s = ''.join(sp['text'] for sp in ln['spans'])
                    y0, y1 = ln['bbox'][1], ln['bbox'][3]
                    if y1 > bot + 2 or y0 < m['top'] * INCH - 2:
                        continue
                    if re.match(r'\s*\d+\.\s+(Note \d+|The opening note)', s):
                        note_y = min(note_y, y0)
                    elif 'Marker' in s:
                        body_y = max(body_y, y1)
            shown = set(int(x) for x in re.findall(r'(?m)^\s*(\d+)\.\s+(?:Note|The opening)', text))
            total += len(shown)
            if pno == 1 and 1 not in shown:
                wrong.append((pno, 'the opening note is not on page 1', sorted(shown)))
            if refs - shown:
                wrong.append((pno, 'referenced but not set here', sorted(refs - shown)))
            if note_y < 9e9 and body_y > note_y - 2:
                overlap.append((pno, round(body_y), round(note_y)))
    check(f'all {len(notes) + 1} notes set ({total})', total == len(notes) + 1, total)
    check('each note is on its reference\'s page', not wrong, wrong[:6])
    check('the columns stop above the notes', not overlap, overlap[:6])


# ---------------------------------------------------------------- gate 5
def gate5():
    print('\nGate 5: no words lost, no loop on something taller than a column')
    for name in ('generated/long_statblock.md',):
        if not os.path.exists(os.path.join(FIX, name)):
            print('  skip the long stat block (not generated)')
            continue
        try:
            a, ra = build(read(name), preset(1), 'g5-1')
            b, rb = build(read(name), preset(2), 'g5-2')
            p = preset()
            wa, wb = body_words(a, p), body_words(b, p)
            check(f'a 120-entry stat block crosses columns and pages ({ra["page_count"]} -> {rb["page_count"]} pages, {rb["seconds"]}s)',
                  wa == wb, ((wa - wb).most_common(6), (wb - wa).most_common(6)))
        except Exception as exc:
            check('long stat block builds', False, '%s: %s' % (type(exc).__name__, str(exc)[:500]))
    # unsplittable things taller than a column
    tall = picture('very-tall.png', 300, 3000)
    cases = {
        'a very tall figure': f'# One\n\n{para(2)}\n\n~~~ figure src="{tall}" width="1.0"\nCaption.\n~~~\n\n{para(2, "z")}\n',
        'a table with one enormous cell': '# One\n\n' + para(1) + '\n\n~~~ table\nA | B\n1 | ' + para(30, 'cell').replace('\n', ' ') + '\n~~~\n\n' + para(1, 'z') + '\n',
        'a boxed letter longer than a page': '# One\n\n' + para(1) + '\n\n~~~ readaloud\n' + para(40, 'box') + '\n~~~\n\n' + para(1, 'z') + '\n',
        'a 300-line poem': '# One\n\n~~~ poem\n' + '\n'.join(f'Line {i} of the long song' for i in range(300)) + '\n~~~\n\n' + para(1, 'z') + '\n',
    }
    for label, md in cases.items():
        t = time.time()
        try:
            one = None
            try:
                a, _ = build(md, preset(1), 'g5-c1')
                one = body_words(a, preset(1))
            except Exception as exc:
                one = '%s' % type(exc).__name__
            b, r = build(md, preset(2), 'g5-c2')
            wb = body_words(b, preset(2))
            same = (one == wb) if isinstance(one, Counter) else None
            check(f'{label}: builds in {r["seconds"]}s, words {"kept" if same else "DIFFER" if same is False else "(one column: " + str(one) + ")"}',
                  same is not False, ((one - wb).most_common(5) if isinstance(one, Counter) else one))
        except Exception as exc:
            dt = round(time.time() - t, 1)
            kind = type(exc).__name__
            clean = isinstance(exc, engine.DoesNotFit)
            check(f'{label}: {"a clean does-not-fit" if clean else "ERROR " + kind} after {dt}s (one column: {"ok" if isinstance(one, Counter) else one})',
                  clean or not isinstance(one, Counter), str(exc)[:300])


# ---------------------------------------------------------------- gate 6
def gate6():
    print('\nGate 6: a long book in two columns, timed')
    if not os.path.exists(os.path.join(FIX, 'generated', 'long_book.md')):
        print('  skip (the long book is not generated)')
        return
    md = read('generated/long_book.md')
    rows = {}
    for label, p, meta in (
        ('one column', preset(1), {}),
        ('two columns', preset(2), {}),
        ('one column + contents', preset(1), {'include_toc': True}),
        ('two columns + contents', preset(2), {'include_toc': True}),
    ):
        try:
            pdf, r = build(md, p, 'g6-' + label.replace(' ', '-').replace('+', ''), **meta)
            rows[label] = (r['seconds'], r['page_count'], pdf)
            print(f'    {label}: {r["seconds"]}s, {r["page_count"]} pages')
        except Exception as exc:
            rows[label] = None
            print(f'    {label}: {type(exc).__name__}: {str(exc)[:300]}')
    if rows.get('one column') and rows.get('two columns'):
        a, b = rows['one column'], rows['two columns']
        check(f'two columns within 3x of one column ({a[0]}s vs {b[0]}s)', b[0] <= 3 * a[0] + 5)
        wa, wb = body_words(a[2], preset(1)), body_words(b[2], preset(2))
        for k in ('d6', 'Result'):        # a split table repeats its header
            wa.pop(k, None); wb.pop(k, None)
        check('the long book keeps every word', wa == wb, ((wa - wb).most_common(6), (wb - wa).most_common(6)))
    else:
        check('long book builds in both', False)
    if rows.get('two columns'):
        p = preset(2)
        m = p['margins']
        tw = (p['trim']['w'] - m['inside'] - m['outside']) * INCH
        top, bot = m['top'] * INCH, (p['trim']['h'] - m['bottom']) * INCH
        heads = set(l.lstrip('#').strip() for l in md.splitlines() if l.startswith('##'))
        stranded, nheads = [], 0
        with fitz.open(rows['two columns'][2]) as d:
            for pno, pg in enumerate(d, start=1):
                left = (m['inside'] if pno % 2 else m['outside']) * INCH
                mid = left + tw / 2
                last = {}
                for b in pg.get_text('dict')['blocks']:
                    for ln in b.get('lines', []):
                        x0, y0, x1, y1 = ln['bbox']
                        if y0 < top - 1 or y1 > bot + 1:
                            continue
                        t = ''.join(sp['text'] for sp in ln['spans']).strip()
                        if not t:
                            continue
                        col = 0 if x0 < mid - 4 else 1
                        if t in heads:
                            nheads += 1
                        if col not in last or y1 > last[col][0]:
                            last[col] = (y1, t)
                for col, (y, t) in last.items():
                    if t in heads:
                        stranded.append((pno, col, t))
        check(f'no heading is the last line of a column ({nheads} headings)', not stranded and nheads > 50,
              (len(stranded), stranded[:5]))
    if rows.get('one column + contents') and rows.get('two columns + contents'):
        a, b = rows['one column + contents'], rows['two columns + contents']
        check(f'with contents: within 3x ({a[0]}s vs {b[0]}s)', b[0] <= 3 * a[0] + 5)


# ---------------------------------------------------------------- gate 7
def column_ends(pdf, p, gap=0.25):
    """Per page: {column: (y of its last line, that line's text)} for the lines
    inside the text block."""
    m = p['margins']
    tw = (p['trim']['w'] - m['inside'] - m['outside']) * INCH
    top, bot = m['top'] * INCH, (p['trim']['h'] - m['bottom']) * INCH
    out = []
    with fitz.open(pdf) as d:
        for pno, pg in enumerate(d, start=1):
            left = (m['inside'] if pno % 2 else m['outside']) * INCH
            mid = left + tw / 2
            last = {}
            for b in pg.get_text('dict')['blocks']:
                for ln in b.get('lines', []):
                    x0, y0, x1, y1 = ln['bbox']
                    t = ''.join(sp['text'] for sp in ln['spans']).strip()
                    if not t or y0 < top - 1 or y1 > bot + 1:
                        continue
                    col = 0 if x0 < mid - 4 else 1
                    if col not in last or y1 > last[col][0]:
                        last[col] = (y1, t)
            out.append(last)
    return out


def gate7():
    print('\nGate 7: the feature (the style editor\'s form, balance_end, the styles, kept headings)')
    from werkzeug.datastructures import MultiDict
    form = lambda **kw: A.parse_preset_form(MultiDict(kw))['columns']
    c = form()
    check('a form from before the section: one column, balanced',
          c['count'] == 1 and c['balance_end'] is True and c['rule'] is False, c)
    c = form(col__form='1', col_count='2', col_gap='0.3', col_rule='on')
    check('two columns, a rule, the balance box unticked',
          c == {'count': 2, 'gap': 0.3, 'rule': True, 'balance_end': False}, c)
    c = form(col__form='1', col_count='7', col_gap='9', col_balance_end='on')
    check('a count that is not 1 or 2 is 1, and the gap is held to its range',
          c['count'] == 1 and c['gap'] == 1.0 and c['balance_end'] is True, c)
    c = form(col__form='1', col_count='2', col_gap='nonsense')
    check('a gap that is not a number takes the default', c['gap'] == 0.25, c)
    check('every style starts at one column', A.DEFAULTS['columns'] == engine.COLUMNS_DEFAULTS
          and engine.COLUMNS_DEFAULTS['count'] == 1, A.DEFAULTS['columns'])

    # balance_end: a short chapter's two columns end level, or the first fills first
    md = '# The Causeway\n\n' + '\n\n'.join(para(2, f'p{i}') for i in range(4))
    even = column_ends(build(md, preset(), 'g7-even')[0], preset())[-1]
    p_off = preset(columns={'balance_end': False})
    off = column_ends(build(md, p_off, 'g7-off')[0], p_off)[-1]
    check('balance_end on: both columns used and level', set(even) == {0, 1}
          and abs(even[0][0] - even[1][0]) <= 45, even)
    check('balance_end off: the first column takes it all', set(off) == {0}, off)
    # ...but a run that stops for a spanning block is balanced either way
    md = (f'# The Long Stair\n\n{para(6, "before")}\n\n~~~ table span="yes"\nStep | What waits there\n'
          f'1 | A warden asleep at his post\n~~~\n\n{para(2, "after")}\n')
    pdf, _ = build(md, p_off, 'g7-off-span')
    m = p_off['margins']
    mid = (m['inside'] + (p_off['trim']['w'] - m['inside'] - m['outside']) / 2) * INCH
    ends, after = {}, set()
    with fitz.open(pdf) as d:
        for b in d[0].get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                t = ''.join(sp['text'] for sp in ln['spans'])
                col = 0 if ln['bbox'][0] < mid - 4 else 1
                if 'Markerbefore' in t:
                    ends[col] = max(ends.get(col, 0), ln['bbox'][3])
                if 'Markerafter' in t:
                    after.add(col)
    check('balance_end off: the run above a spanning table is still balanced',
          set(ends) == {0, 1} and abs(ends[0] - ends[1]) <= 45, ends)
    check('balance_end off: the run that ends the chapter is not', after == {0}, after)

    # the two bundled styles: two columns in print and on screen, nothing lost
    for pid in ('game-rulebook-two-column', 'game-dark-two-column'):
        try:
            p = A.load_preset(pid)
            n, gap = engine.columns_of(p)
            check(f'{pid}: a two-column style', n == 2 and gap > 0, (n, gap))
            # hyphens off for the count: a word broken at a line's end reads as two
            p['body'] = dict(p['body'], hyphenate=False)
            one = copy.deepcopy(p)
            one['columns'] = dict(one['columns'], count=1)
            md = all_blocks_md()
            outs = {}
            for label, pp, screen in (('one', one, False), ('print', p, False), ('screen', p, True)):
                out = os.path.join(TMP, f'g7-{pid}-{label}.pdf')
                engine.build_pdf(manuscript.parse_markdown(md), pp, out, dict(META), screen=screen)
                outs[label] = out
            w = {k: body_words(v, p) for k, v in outs.items()}
            for k in ('Roll', 'Encounter', 'Notes'):
                for c in w.values():
                    c.pop(k, None)
            check(f'{pid}: print and screen keep the one-column words',
                  w['one'] == w['print'] == w['screen'],
                  ((w['one'] - w['print']).most_common(6), (w['print'] - w['one']).most_common(6),
                   (w['one'] - w['screen']).most_common(6)))
            both = [set(e) for e in column_ends(outs['print'], p, gap / INCH)]
            check(f'{pid}: its pages are set in two columns', both and all(s == {0, 1} for s in both), both)
        except Exception:
            check(f'{pid}: builds', False, traceback.format_exc()[-900:])

    # a box's title, a stat block's name and its section headings never end a column
    parts = ['# The Watch']
    for i in range(40):
        parts.append(para(1 + i % 3, f'k{i}'))
        parts.append(f'~~~ sidebar title="Wardnote{i}"\n{LOREM * (1 + i % 4)}\n~~~')
        parts.append(f'~~~ readaloud title="Doorvoice{i}"\n{LOREM * (1 + i % 2)}\n~~~')
        parts.append(f'~~~ statblock\nBellkeeper{i}\nMedium humanoid, lawful neutral\n\n'
                     f'Armor Class: 16 (chain)\nHit Points: 39 (6d8 + 12)\n\n'
                     f'### Actions\n***Halberd.*** {LOREM}\n***Horn.*** {LOREM}\n\n'
                     f'### Reactions\n***Parry.*** {LOREM}\n~~~')
    md = '\n\n'.join(parts) + '\n'
    is_head = re.compile(r'^(wardnote\d+|doorvoice\d+|bellkeeper\d+|actions|reactions|'
                         r'medium humanoid, lawful neutral)$', re.I)
    for cols in (2, 1):
        p = preset(cols)
        pdf, _ = build(md, p, f'g7-keep-{cols}')
        ends = column_ends(pdf, p)
        stranded = [(pno, col, t) for pno, last in enumerate(ends, start=1)
                    for col, (_, t) in last.items() if is_head.match(t)]
        if cols == 1:        # one column: a page's last line is its lowest in either half
            stranded = [(pno, t) for pno, last in enumerate(ends, start=1) if last
                        for t in [max(last.values())[1]] if is_head.match(t)]
        with fitz.open(pdf) as d:
            text = '\n'.join(pg.get_text() for pg in d)
        seen = len(re.findall(r'(?i)wardnote\d+|doorvoice\d+|bellkeeper\d+', text))
        check(f'{"two columns" if cols == 2 else "one column"}: no title or section heading '
              f'ends a {"column" if cols == 2 else "page"} ({seen} titles, {len(ends)} pages)',
              not stranded and seen == 120, (seen, stranded[:6]))


for g, fn in (('1', gate1), ('2', gate2), ('3', gate3), ('4', gate4), ('5', gate5), ('6', gate6),
              ('7', gate7)):
    if g in GATES:
        try:
            fn()
        except Exception:
            check(f'gate {g} ran', False, traceback.format_exc()[-1200:])
bad = [l for l, ok in results if not ok]
import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('\nALL PASS' if not bad else f'\n{len(bad)} FAILED: ' + '; '.join(bad))
sys.exit(1 if bad else 0)
