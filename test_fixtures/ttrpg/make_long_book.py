"""Generate large TTRPG manuscripts for stress tests (ROADMAP #74).

    python test_fixtures/ttrpg/make_long_book.py [out_dir]

Writes, into out_dir (default: this folder's generated/, which is gitignored
by its own .gitignore):

  long_book.md        ~300 pages at 6 x 9 in one column (about half that in two
                      columns on Letter): 22 chapters of keyed rooms, each room
                      with boxed text, a sidebar every few rooms and a stat block
                      every other room. For Phase 1's "builds and loses no words"
                      check, and Phase 4's two-column timing check (gate 6).
  long_statblock.md   one stat block with 120 entries: taller than any page, so
                      it must split (Phase 1) and cross columns (Phase 4).
  words.json          each file's whitespace-separated token count, markup
                      included: a rough size check, not a "words in = words out"
                      count (strip the markup first for that).

Deterministic: the same seed gives the same text, so a timing or page count
can be compared between runs. Uses only the syntax planned for Phase 1
(readaloud / sidebar / statblock) plus what exists today (## subheads, tables).
"""

import json
import os
import random
import sys

SEED = 74
WORDS = ("the old stair leads down into a cellar where water stands knee deep and "
         "something has scratched a tally of days into the plaster beside the door "
         "a lantern hangs from a hook its glass cracked and the smell of peat smoke "
         "lingers though no fire has burned here for many years the floorboards "
         "creak under any weight and a careful search turns up a rusted key a "
         "child's shoe and a letter sealed with green wax").split()
NAMES = ("Gatehouse Cellar Chapel Kitchen Well Library Crypt Belfry Larder Barracks "
         "Armoury Cistern Gallery Vestry Dormitory Infirmary Scriptorium Kennels "
         "Stable Brewhouse Smithy Granary Chantry Undercroft").split()
CREATURES = ("Bog-Thrall Reed Stalker Lantern Moth Marsh Ghoul Drowned Monk "
             "Silt Crab Heron-Wight Eel Swarm").split()


def sentence(rng, n=None):
    n = n or rng.randint(9, 22)
    words = [rng.choice(WORDS) for _ in range(n)]
    words[0] = words[0].capitalize()
    return ' '.join(words) + '.'


def paragraph(rng, sentences=None):
    return ' '.join(sentence(rng) for _ in range(sentences or rng.randint(3, 6)))


def statblock(rng, name, entries=None):
    scores = ' | '.join('%s %d' % (s, rng.randint(3, 20))
                        for s in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'))
    lines = ['~~~ statblock name="%s" meta="Medium undead, unaligned"' % name,
             'Armor Class: %d' % rng.randint(9, 18),
             'Hit Points: %d (%dd8 + %d)' % (rng.randint(10, 120), rng.randint(2, 15),
                                            rng.randint(0, 40)),
             'Speed: 30 ft.',
             scores,
             'Senses: passive Perception %d' % rng.randint(8, 16),
             'Challenge: %d' % rng.randint(1, 10),
             '--- Traits']
    count = entries or rng.randint(2, 5)
    for i in range(count):
        if i == count // 2:
            lines.append('--- Actions')
        lines.append('***%s.*** %s' % (rng.choice(WORDS).capitalize(), sentence(rng)))
    lines.append('~~~')
    return '\n'.join(lines)


def long_book(rng):
    out = []
    for ch in range(1, 23):
        out.append('# Chapter %d: Level %d' % (ch, ch))
        out.append(paragraph(rng, 8))
        for room in range(1, 13):
            key = '%s%d' % (chr(64 + ch), room)
            out.append('## %s. %s' % (key, rng.choice(NAMES)))
            out.append('~~~ readaloud\n%s\n~~~' % paragraph(rng, 3))
            out.append(paragraph(rng))
            out.append(paragraph(rng))
            if room % 4 == 0:
                out.append('~~~ sidebar title="Variant: %s"\n%s\n\n%s\n~~~'
                           % (rng.choice(NAMES), paragraph(rng, 3), paragraph(rng, 2)))
            if room % 2 == 0:
                out.append(statblock(rng, rng.choice(CREATURES)))
            if room % 6 == 0:
                rows = '\n'.join('%d | %s' % (i, sentence(rng, 6)) for i in range(1, 7))
                out.append('~~~ table\nd6 | Result\n%s\n~~~' % rows)
    return '\n\n'.join(out) + '\n'


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, 'generated')
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(SEED)
    files = {
        'long_book.md': long_book(rng),
        'long_statblock.md': '# The Long One\n\n%s\n' % statblock(rng, 'Endless Horror',
                                                                   entries=120),
    }
    counts = {}
    for name, text in files.items():
        with open(os.path.join(out_dir, name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        counts[name] = len(text.split())
    with open(os.path.join(out_dir, 'words.json'), 'w', encoding='utf-8') as f:
        json.dump(counts, f, indent=1)
    print(out_dir, counts)


if __name__ == '__main__':
    main()
