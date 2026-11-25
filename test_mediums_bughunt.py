"""Joint bug hunt, the Mediums left from sections 1-3  (run: python test_mediums_bughunt.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

  2.10 a narrow table keeps its alignment inside a column;
  2.11 2024 scores pasted with spaces ("Str 14 +2 +2 ...") read as scores;
  2.12 an index marker in a stat block's section heading reaches the index;
  2.13 a decimal rating ("0.5") is its own group, not CR 0;
  2.14 an entry led by a sign comes first, under no letter;
  2.N1 page references still moving after the last pass are reported.
"""
import copy, os, re, sys, tempfile, traceback

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)
import fitz
import manuscript, statblock, bookindex, engine, app as A

TMP = tempfile.mkdtemp(prefix='ts-mediums-')
results = []

META = {'title': 'The Salt Road', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True}
LOREM = ("The carts go down the salt road at dawn and come back before the tide. "
         "Nobody counts them twice. ")


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


def build(md, p, name, **meta):
    out = os.path.join(TMP, name + '.pdf')
    engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta))
    return out


def index_lines(pdf):
    with fitz.open(pdf) as d:
        texts = [pg.get_text() for pg in d]
    at = max(i for i, t in enumerate(texts) if re.search(r'^\s*Index\s*$', t, re.M))
    return [l.strip() for t in texts[at:] for l in t.split('\n') if l.strip()]


# ------------------------------------------------------------------ 2.10
def test_table_align():
    print('\n2.10 A narrow table in a column')
    md = ('# One\n\n' + LOREM * 3 + '\n\n~~~ table\nKey | Value\nQzalpha | 1\nQzbeta | 2\n~~~\n\n'
          + LOREM * 3)
    xs = {}
    for align in ('left', 'right', 'center'):
        pdf = build(md, preset(2, table={'width': 0.6, 'align': align}), 'table-' + align)
        with fitz.open(pdf) as d:
            for pg in d:
                r = pg.search_for('Qzalpha')
                if r:
                    xs[align] = r[0].x0
                    break
    check('right and centre sit right of left, right furthest',
          xs.get('left', 0) < xs.get('center', 0) < xs.get('right', 0), xs)


# ------------------------------------------------------------------ 2.11
def test_spaced_scores():
    print('\n2.11 2024 scores pasted with spaces')
    model = statblock.read(['Salt Hound', 'Medium beast, unaligned', 'AC 13',
                            'Str 14 +2 +2 Dex 8 -1 -1 Con 15 +2 +4'])
    cells = model.get('scores') or []
    check('three cells, each with its modifier and save',
          [(c['name'], c['score'], c['mod'], c['save']) for c in cells]
          == [('Str', '14', '+2', '+2'), ('Dex', '8', '−1', '−1'), ('Con', '15', '+2', '+4')],
          cells)
    model = statblock.read(['Salt Hound', 'Medium beast', 'Str 14 (+2) Dex 8 (-1)'])
    check('the older "Str 14 (+2)" still reads, with no save',
          [(c['mod'], c['save']) for c in model.get('scores') or []] == [('+2', ''), ('−1', '')],
          model.get('scores'))


# ------------------------------------------------------------------ 2.12-2.14
def test_index():
    print('\n2.12-2.14 The index')
    md = '\n'.join([
        '# Beasts', '', LOREM * 2,
        '', '~~~ statblock cr="0.5"', 'Salt Hound', 'Medium beast, unaligned', 'Armor Class 13',
        '--- Actions {index: Hounds > attacks}', '***Bite.*** It bites.', '~~~',
        '', '~~~ statblock cr="0"', 'Gull', 'Tiny beast, unaligned', 'Armor Class 11', '~~~',
        '', 'Signs {index: +Ziggurat} and {index: _Vault} and {index: Atlas} '
            'and {index: 7 Bells} and {index: Zebra}.',
    ])
    blocks = manuscript.parse_markdown(md)
    found = []
    for ch in blocks['chapters'] if isinstance(blocks, dict) else blocks:
        for b in ch['blocks']:
            attrs = b[2] if len(b) > 2 and isinstance(b[2], dict) else {}
            sb = attrs.get('_statblock')
            if sb:
                found += [s['name'] for s in sb['sections']]
    check('the heading keeps its marker in the model',
          any('<index item="Hounds &gt; attacks"/>' in n or 'index item=' in n for n in found), found)
    pdf = build(md, preset(1), 'index', index_statblocks=True, index_cr=True)
    lines = index_lines(pdf)
    check('2.12: the heading\'s marker is in the index',
          any(l.startswith('attacks') for l in lines) and 'Hounds' in ' '.join(lines), lines)
    cr = lines[lines.index(bookindex.CR_HEADING) + 1:]
    heads = [l for l in cr if l.startswith('CR ')]
    check('2.13: CR 0.5 is its own group, after CR 0', heads == ['CR 0', 'CR 0.5'], heads)
    body = lines[:lines.index(bookindex.CR_HEADING)]
    order = [w for w in ('+Ziggurat', '_Vault', '7 Bells', 'Atlas', 'Zebra')
             for l in body if l.startswith(w)]
    first_letter = next((i for i, l in enumerate(body) if re.fullmatch(r'[A-Z]', l)), None)
    check('2.14: sign- and digit-led entries come first',
          order[-2:] == ['Atlas', 'Zebra'] and len(order) == 5, (order, body))
    check('... under no letter',
          first_letter is not None
          and all(body.index(next(l for l in body if l.startswith(w))) < first_letter
                  for w in ('+Ziggurat', '_Vault', '7 Bells')), body)
    check('letter() files them under no letter, the rest under their own',
          [bookindex.letter(t) for t in ('+Ziggurat', '_Vault', '7 Bells', 'Ålesund', 'atlas')]
          == ['', '', '', 'A', 'A'])
    check('cr_order puts 0.5 between 1/4 and 1',
          sorted(['1', '0.5', '1/4', '0'], key=bookindex.cr_order) == ['0', '1/4', '0.5', '1'])


# ------------------------------------------------------------------ 2.N1
def test_unsettled():
    print('\n2.N1 References that never settle')
    md = '# One\n\nThe hall{#hall} is here. ' + LOREM * 3 + '\n\nSee page {page: hall}.\n'
    real = engine._refs_found
    pdf = os.path.join(TMP, 'settled.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), preset(1), pdf, dict(META))
    check('a book that settles is not flagged', res.get('refs_unsettled') is False, res.get('refs_unsettled'))
    labels = [c['label'] for c in A._preflight(res, preset(1), res['page_count'])]
    check('... and preflight has no Page references row', 'Page references' not in labels, labels)
    calls = [0]

    def moving(doc):
        calls[0] += 1
        got = real(doc)
        return dict(got, hall=calls[0]) if isinstance(got, dict) else {'hall': calls[0]}
    engine._refs_found = moving
    try:
        for toc in (False, True):
            res = engine.build_pdf(manuscript.parse_markdown(md), preset(1), pdf,
                                   dict(META, include_toc=toc))
            check(f'one still moving is flagged (contents {"on" if toc else "off"})',
                  res.get('refs_unsettled') is True, res.get('refs_unsettled'))
    finally:
        engine._refs_found = real
    rows = [c for c in A._preflight(res, preset(1), res['page_count']) if c['label'] == 'Page references']
    check('preflight shows a failing Page references row', rows and not rows[0]['ok'], rows)


def main():
    for t in (test_table_align, test_spaced_scores, test_index, test_unsettled):
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
