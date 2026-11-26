"""Stat blocks and game blocks end to end  (run: python test_gameblocks_bughunt.py).

Joint bug hunt, round 5, section 22 (the editor's side of 22.1-22.4, 22.11-22.13
is in test_rich_editor.js, scenarios "bh22-*"):

    22.1  a block missing its ~~~ ends at the next opening fence or chapter,
          and preflight says so
    22.2  an unterminated Homebrewery monster doesn't swallow the next one
    22.5  a Word STR..CHA table with no creature around it stays a table
    22.6  a long creature name in a heading is still the name
    22.7  a dash score doesn't break a multi-line score table
    22.8  a quoted Word read-aloud heading keeps its title
    22.9  a read-aloud title keeps the first lines of its text in a column
    22.10 plain `AC 15  Initiative +2 (12)` is two fields
    22.11 a blank line after the legacy rule still finds the monster
    22.12 a link in a stat block keeps its address through the doc model
    22.13 a stat block's blank lines survive the doc model
    22.14 a box title's emphasis reads the same in the PDF and the EPUB
"""

import copy, os, re, sys, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import doc_model
import engine
import epub
import manuscript as M
import statblock

fails = []
TMP = tempfile.mkdtemp(prefix='gameblocks_bughunt_')
META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it.'


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def kinds(parsed):
    return [(c['title'], [(b[0], b[2].get('_type') if len(b) > 2 else None) for b in c['blocks']])
            for c in parsed['chapters']]


# ---- 22.1 -------------------------------------------------------------------
print('22.1 a block missing its closing fence')
MD = ('# One\n\n~~~ statblock\n## Ash Drake\nAC: 15\n\n# Next Room\n\nProse here.\n\n'
      '~~~ sidebar title="Pacing" style="note"\nKeep it moving.\n~~~\n\nAfter.\n')
p = M.parse_markdown(MD)
k = kinds(p)
check('the chapter after it is kept', [t for t, _ in k] == ['One', 'Next Room'], k)
check('the sidebar keeps its type', ('doc_block', 'sidebar') in k[1][1], k)
side = next(b for b in p['chapters'][1]['blocks'] if len(b) > 2 and b[2].get('_type') == 'sidebar')
check('and its attributes', side[2].get('title') == 'Pacing' and side[2].get('style') == 'note', side[2])
check('the prose after it is prose', k[1][1][-1] == ('para', None), k)
check('the missing fence is reported', p.get('blocks_unclosed') == [(3, 'statblock')], p.get('blocks_unclosed'))
# a stat block's `# Name` is still its name
p = M.parse_markdown('# One\n\n~~~ statblock\n# Ash Drake\nAC: 15\n~~~\n')
sb = p['chapters'][0]['blocks'][0]
check('a stat block\'s own "# Name" stays inside it',
      len(p['chapters']) == 1 and sb[2]['_statblock']['name'] == 'Ash Drake' and not p.get('blocks_unclosed'))
# an escaped `\# ` line in a poem is text
p = M.parse_markdown('# One\n\n~~~ poem\n\\# not a chapter\n~~~\n')
check('"\\# " in a block is a line of text', len(p['chapters']) == 1
      and '# not a chapter' in p['chapters'][0]['blocks'][0][1][0][1], p['chapters'][0]['blocks'])
# the doc model reads it the same way, and writes a `# ` line in a block guarded
dm = doc_model.from_markdown(MD)
types = [(b['type'], b.get('block_type')) for b in dm]
check('the doc model ends the block there too',
      types == [('chapter', None), ('docblock', 'statblock'), ('chapter', None), ('para', None),
                ('docblock', 'sidebar'), ('para', None)], types)
md2 = doc_model.to_markdown(doc_model.from_markdown('# One\n\n~~~ poem\n\\# not a chapter\n~~~\n'))
check('a "# " line in a block round-trips guarded', '\\# not a chapter' in md2, md2)
# preflight
pdf = os.path.join(TMP, 'unclosed.pdf')
res = engine.build_pdf(M.parse_markdown(MD), copy.deepcopy(A.DEFAULTS), pdf, dict(META))
rows = A._preflight(res, copy.deepcopy(A.DEFAULTS), res['page_count'])
row = next((r for r in rows if r['label'] == 'Blocks'), None)
check('preflight names the block', row and not row['ok'] and 'statblock block at line 3' in row['detail'],
      row)

# ---- 22.2 / 22.11 -----------------------------------------------------------
print('22.2 / 22.11 Homebrewery paste')
src = ('{{monster,frame\n## Ash Drake\n**AC** :: 15\n\nSome prose between.\n\n'
       '{{monster,frame\n## Bog-Thrall\n**AC** :: 9\n}}\n')
w = statblock.wrap_unfenced(src)
check('the complete monster is wrapped on its own',
      '~~~ statblock\n{{monster,frame\n## Bog-Thrall' in w and w.count('~~~ statblock') == 1, w)
check('the prose stays outside', w.index('Some prose between.') < w.index('~~~ statblock'), w)
w = statblock.wrap_unfenced('___\n\n> ## Ash Drake\n> *Large dragon*\n> - **AC** 15\n\nAfter.\n')
check('a blank line after the rule still finds the monster',
      w.startswith('~~~ statblock\n___\n> ## Ash Drake') and '~~~\n\nAfter.' in w, w)

# ---- 22.6 / 22.7 / 22.10 ----------------------------------------------------
print('22.6 / 22.7 / 22.10 reading stat blocks')
m = statblock.read(['## The Keeper of the Seven Gates Beneath the Salt Sea', '*Huge construct, unaligned*',
                    'AC: 15', 'STR 20 | DEX 10 | CON 18 | INT 3 | WIS 11 | CHA 1'], '', '')
check('a long heading is the name', m['name'] == 'The Keeper of the Seven Gates Beneath the Salt Sea', m['name'])
check('and the header stays structured', m['meta'] == 'Huge construct, unaligned'
      and len(m['scores']) == 6 and m['fields'][0]['label'] == 'AC', (m['meta'], m['fields']))
m = statblock.read(['## Ash Drake', '|STR|DEX|CON|INT|WIS|CHA|', '|:---:|:---:|:---:|:---:|:---:|:---:|',
                    '|—|0|30|10|10|10|'], '', '')
got = [(c['name'], c['score'], c['mod']) for c in m['scores']]
check('a dash score keeps the table', got[:3] == [('STR', '—', ''), ('DEX', '0', '−5'), ('CON', '30', '+10')],
      got)
m = statblock.read(['## Ash Drake', 'AC 15  Initiative +2 (12)'], '', '')
check('AC and Initiative are two fields',
      m['fields'] == [{'label': 'AC', 'value': '15'}, {'label': 'Initiative', 'value': '+2 (12)'}],
      m['fields'])
m = statblock.read(['## Ash Drake', 'Armor Class 15 (natural armor)'], '', '')
check('an AC note stays in the AC', m['fields'] == [{'label': 'Armor Class', 'value': '15 (natural armor)'}],
      m['fields'])

# ---- 22.5 / 22.8 ------------------------------------------------------------
print('22.5 / 22.8 Word import')
from docx import Document


def imported(build, name):
    path = os.path.join(TMP, name)
    d = Document()
    build(d)
    d.save(path)
    md = M.import_docx(path, report={})
    return md, M.parse_markdown(md, smartquotes=False)


def scores_chapter(d):
    d.add_heading('Making a Character', 1)
    d.add_paragraph('Roll your scores and write them down.')
    t = d.add_table(rows=2, cols=6)
    for i, n in enumerate(['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']):
        t.cell(0, i).text = n
        t.cell(1, i).text = str(10 + i)
    d.add_paragraph('Each score gives a modifier: subtract ten and halve it.')
    d.add_paragraph('A high score is rare; most heroes have one or two.')
    d.add_heading('Classes', 1)


md, p = imported(scores_chapter, 'scores.docx')
b = [x for c in p['chapters'] for x in c['blocks']]
check('a score table with no creature is not a stat block',
      not any(len(x) > 2 and x[2].get('_type') == 'statblock' for x in b), md)
check('the paragraphs after it stay paragraphs',
      sum(1 for x in b if x[0] == 'para') >= 3, [x[0] for x in b])


def creature(d):
    d.add_heading('Bestiary', 1)
    para = d.add_paragraph()
    para.add_run('Ash Drake').bold = True
    d.add_paragraph('Armor Class 15')
    t = d.add_table(rows=2, cols=6)
    for i, n in enumerate(['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']):
        t.cell(0, i).text = n
        t.cell(1, i).text = str(10 + i)


md, p = imported(creature, 'creature.docx')
b = [x for c in p['chapters'] for x in c['blocks']]
check('a named creature\'s table still makes a stat block',
      any(len(x) > 2 and x[2].get('_type') == 'statblock' for x in b), md)


def quoted_readaloud(d):
    d.add_heading('The Inn', 1)
    d.add_heading('Read Aloud — The "Silent" Door', 2)
    d.add_paragraph('The door does not creak.')


md, p = imported(quoted_readaloud, 'readaloud.docx')
ra = next((x for c in p['chapters'] for x in c['blocks']
           if len(x) > 2 and x[2].get('_type') == 'readaloud'), None)
check('a quoted read-aloud heading keeps its title',
      ra is not None and ra[2].get('title') == 'Read Aloud — The "Silent" Door', md)

# ---- 22.9 -------------------------------------------------------------------
print('22.9 a read-aloud title and its first lines')
import fitz
long_para = ' '.join([L] * 70)
# nine paragraphs leave a little under two inches of the first page: the box
# used to go over whole, leaving the space blank; now its title and first
# lines start there
MD9 = ('# One\n\n' + '\n\n'.join([L] * 9)
       + f'\n\n~~~ readaloud title="The Silent Door"\n{long_para}\n~~~\n\nAfter.\n')
pdf = os.path.join(TMP, 'readaloud.pdf')
engine.build_pdf(M.parse_markdown(MD9), copy.deepcopy(A.DEFAULTS), pdf, dict(META))
with fitz.open(pdf) as doc:
    pages = [pg.get_text() for pg in doc]
title_pg = next(i for i, t in enumerate(pages) if 'Silent Door' in t.replace('\n', ' ')
                or 'SILENT DOOR' in t.replace('\n', ' ').upper())
after_title = pages[title_pg].upper().split('SILENT DOOR', 1)[-1]
check('the title is followed by its text on the same page', 'TIDE COMES IN' in after_title,
      (title_pg, after_title[:120]))
check('the box starts where there is room for its first lines', title_pg == 0, title_pg)

# ---- 22.12 / 22.13 ----------------------------------------------------------
print('22.12 / 22.13 stat blocks through the doc model')
MD13 = '# One\n\n~~~ statblock\n## Ash Drake\nSTR DEX CON INT WIS CHA\n\n14 8 15 3 8 5\n~~~\n'
back = doc_model.to_markdown(doc_model.from_markdown(MD13))
check('a blank line between lines survives', 'STR DEX CON INT WIS CHA\n\n14 8 15 3 8 5' in back, back)
before = M.parse_markdown(MD13)['chapters'][0]['blocks'][0][2]['_statblock']['scores']
after = M.parse_markdown(back)['chapters'][0]['blocks'][0][2]['_statblock']['scores']
check('and the scores read the same', before == after, (before, after))
blocks = doc_model.from_markdown('# One\n\n~~~ statblock\n## Ash Drake\nLanguages: Aquan\n~~~\n')
sbk = next(b for b in blocks if b.get('block_type') == 'statblock')
line = sbk['children'][1]
line['runs'] = [dict(line['runs'][0], text='Languages: '),
                dict(line['runs'][0], text='Aquan', link='https://example.com/aquan')]
back = doc_model.to_markdown(blocks)
check('a link keeps its address', 'Languages: [Aquan](https://example.com/aquan)' in back, back)

# ---- 22.14 ------------------------------------------------------------------
print('22.14 box titles in both outputs')
MD14 = '# One\n\n~~~ sidebar title="*The Watch* & <Gate>" style="note"\nText.\n~~~\n'
out = os.path.join(TMP, 'title.epub')
epub.build_epub(M.parse_markdown(MD14), copy.deepcopy(A.DEFAULTS), out, dict(META))
with zipfile.ZipFile(out) as z:
    ch = z.read('OEBPS/chapter001.xhtml').decode('utf-8')
check('the EPUB title is in italics, not asterisks',
      '<p class="block-title"><em>The Watch</em> &amp; &lt;Gate&gt;</p>' in ch,
      re.findall(r'<p class="block-title">.*?</p>', ch))
MD14b = '# One\n\n~~~ statblock count="*2*" cr="**3**"\n## Ash Drake\nAC: 15\n~~~\n'
out = os.path.join(TMP, 'sb.epub')
epub.build_epub(M.parse_markdown(MD14b), copy.deepcopy(A.DEFAULTS), out, dict(META))
with zipfile.ZipFile(out) as z:
    ch = z.read('OEBPS/chapter001.xhtml').decode('utf-8')
check('a stat block\'s count and CR read their emphasis', '<em>2</em>' in ch and '<strong>3</strong>' in ch,
      re.findall(r'<p class="sb-name".*?</p>', ch))

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
