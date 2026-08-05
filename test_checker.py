"""Continuity-checker tests  (run: python test_checker.py).

No test framework, like test_epub.py. The checker reads the *parsed* manuscript,
where a chapter's words may sit in a document block (a poem, a letter, a table)
rather than in loose paragraphs, and where a verse line break and a table cell
divider are markers inside the text. Both facts were missed:

  - a chapter made entirely of a poem was reported "Empty chapter", so a book of
    verse flagged every chapter it had;
  - `<br/>` and `<cell/>` were stripped like formatting tags, running the words
    either side together — "Ada|Lovelace" read out as "AdaLovelace", which is
    then a capitalised token the name-variant check can flag, and which is what
    the paid tier-2 summary was sent.

The advice this tool gives is only worth the text it reads, so these check the
reading, not the phrasing of the advice.
"""

import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import checker, manuscript

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond: fails.append(name)


def empties(src):
    return checker._check_thin_chapters(manuscript.parse_markdown(src))


def paras(src, idx=0):
    return checker._chapter_paras(manuscript.parse_markdown(src)['chapters'][idx])


# ------------------------------------------------- a chapter that is one block
print('a chapter whose words live in a document block is not empty')

POEM = ('# Sea Fever\n\n~~~ poem\nI must go down to the seas again,\n'
        'to the lonely sea and the sky,\n~~~\n')
check('a poem-only chapter is not called empty', empties(POEM) == [], empties(POEM))

for label, block in (('quote', 'quote'), ('letter', 'letter'), ('table', 'table'),
                     ('list', 'list'), ('plain fence', '')):
    src = '# Only\n\n~~~ %s\nSome real words here.\n~~~\n' % block
    check('a %s-only chapter is not called empty' % label, empties(src) == [],
          empties(src))

# ...but a chapter with nothing in it still is, which is the point of the check
check('a chapter with no text at all is still called empty',
      len(empties('# Hollow\n\n# Next\n\nWords.\n')) == 1,
      empties('# Hollow\n\n# Next\n\nWords.\n'))
check('an empty document block does not count as text',
      len(empties('# Hollow\n\n~~~ letter\n~~~\n')) == 1,
      empties('# Hollow\n\n~~~ letter\n~~~\n'))

# --------------------------------------------------------- markers are gaps
print('\nverse breaks and cell dividers read as a gap, not as nothing')

verse = paras(POEM)[0]
check('verse lines do not run together',
      'again, to the lonely' in verse, verse)
check('and no marker survives into the text',
      '<' not in verse and 'br/' not in verse, verse)

TABLE = '# Data\n\n~~~ table\nAda | Lovelace\nGrace | Hopper\n~~~\n'
cells = paras(TABLE)
check('table cells do not run together', cells == ['Ada Lovelace', 'Grace Hopper'],
      cells)

# the failure this actually caused: a fused name reaching the name-variant check
names = checker._check_name_variants(manuscript.parse_markdown(
    TABLE + '\nAda wrote the notes. Ada checked them twice. Ada again.\n'))
check('a fused cell pair is not offered as a name variant',
      not any('AdaLovelace' in i['label'] for i in names),
      [i['label'] for i in names])

# emphasis inside verse or a cell is still stripped as formatting
EMPH = '# E\n\n~~~ poem\nA *stressed* word,\nand a **loud** one.\n~~~\n'
check('emphasis tags are still stripped',
      paras(EMPH) == ['A stressed word, and a loud one.'], paras(EMPH))

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
