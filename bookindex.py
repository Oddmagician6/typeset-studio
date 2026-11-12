"""The book's index (ROADMAP #74, Phase 5a): what both builders share.

A writer marks a place with `{index: Owlbear}` or `{index: Monsters > Owlbear}`;
`manuscript._inline` carries it through the parsed text as the neutral
`<index item="…"/>`. This module gives every marker a key, lets the builder
write its own anchor in the marker's place, and turns "where each key landed"
into the index as data. The PDF's "where" is a page number, the ebook's a
chapter, so each sets its own page from the same tree.

A book's stat blocks join in unless the book turns them off: `index_statblocks`
lists each by name, `index_cr` adds a list by challenge rating. Both are on when
a book doesn't say (`on`).

Stdlib-only, like `matter.py`, so the ebook can use it without ReportLab.
"""
import html
import re
import unicodedata

from manuscript import (INDEX_TAG_RE, index_path, map_block_texts)

HEADING = 'Index'
CR_HEADING = 'By Challenge Rating'

_TAG_RE = re.compile(r'<[^>]+>')
_CR_RE = re.compile(r'\d+(?:\s*/\s*\d+)?')


def on(meta, key):
    """A stat-block index option: on unless the book turns it off."""
    return bool(meta.get(key, True))


def _words(markup):
    """Markup as the plain words a reader sees."""
    return ' '.join(html.unescape(_TAG_RE.sub('', markup or '')).split())


def statblock_cr(attrs, model):
    """A stat block's challenge rating as written ("5", "1/4"), or ''. It is
    the block's `cr="…"`, or else its Challenge line ("5 (1,800 XP)")."""
    text = (attrs.get('cr', '') or '').strip()
    if not text:
        for f in model.get('fields', []):
            label = _words(f.get('label', '')).rstrip('.:').lower()
            if label in ('challenge', 'challenge rating', 'cr'):
                text = _words(f.get('value', ''))
                break
    m = _CR_RE.match(text)
    return re.sub(r'\s+', '', m.group(0)) if m else text


def cr_order(cr):
    """Sort key for a challenge rating: by its number ("1/4" before "1"),
    anything that isn't a number last."""
    m = _CR_RE.match(cr)
    if m:
        num, _, den = m.group(0).partition('/')
        try:
            return (0, int(num) / int(den) if den.strip() else float(num), '')
        except (ValueError, ZeroDivisionError):
            pass
    return (1, 0.0, cr.casefold())


def assign(chapters, meta, tag):
    """Give every index marker a key: `(chapters, marks)`.

    `tag(key)` is the builder's own markup for a marker in the text; it takes
    the neutral tag's place. `marks[key]` is `{'path': (main, sub, …),
    'chapter': n}` for a marker, and `{'path': (name,), 'chapter': n,
    'stat': True, 'cr': '5'}` for a stat block. A stat block is keyed only
    when the book lists them (`index_statblocks`, `index_cr`, see `on`); its key is left
    on the block as `_ix` for the builder to anchor its name with. The
    chapters come back as a copy; `chapter` counts from 1.
    """
    marks = []
    number = {id(ch): n for n, ch in enumerate(chapters, start=1)}

    def render(text, ch):
        if '<index ' not in text:
            return text

        def one(m):
            path = index_path(m.group(1))
            if not path:
                return ''
            marks.append({'path': path, 'chapter': number[id(ch)]})
            return tag(len(marks) - 1)
        return INDEX_TAG_RE.sub(one, text)

    out = map_block_texts(chapters, render)
    if on(meta, 'index_statblocks') or on(meta, 'index_cr'):
        for n, ch in enumerate(out):
            blocks = None
            for i, block in enumerate(ch.get('blocks', [])):
                attrs = block[2] if block[0] == 'doc_block' and len(block) > 2 else None
                if not attrs or attrs.get('_type') != 'statblock':
                    continue
                model = attrs.get('_statblock') or {}
                name = _words(model.get('name', ''))
                if not name:
                    continue
                marks.append({'path': (name,), 'chapter': n + 1, 'stat': True,
                              'cr': statblock_cr(attrs, model)})
                if blocks is None:
                    blocks = list(ch['blocks'])
                blocks[i] = (block[:2] + (dict(attrs, _ix=len(marks) - 1),)
                             + tuple(block[3:]))
            if blocks is not None:
                out[n] = dict(ch, blocks=blocks)
    return out, marks


def wanted(marks, meta):
    """Whether the book gets an Index page: it has something to list."""
    return any(not m.get('stat') or on(meta, 'index_statblocks')
               or (on(meta, 'index_cr') and m.get('cr')) for m in marks)


def sort_key(text):
    """Order for an entry: letters and digits only, accents and case aside."""
    flat = unicodedata.normalize('NFKD', text)
    flat = ''.join(c for c in flat if not unicodedata.combining(c)).casefold()
    return (re.sub(r'[^\w\s]', '', flat).strip() or flat, text)


def letter(text):
    """The letter an entry is filed under, or '' for one that starts with a
    digit or a sign (those come first, under no letter)."""
    head = sort_key(text)[0][:1].upper()
    return head if head.isalpha() else ''


def tree(marks, found, meta):
    """The index as data: `(entries, challenges)`.

    `found` is `[(key, where)]`, a marker's key and where the builder put it.
    `entries` is `[(main, hits, [(sub, hits), …]), …]` in index order and
    `challenges` is `[(cr, [(name, hits), …]), …]`, lowest first; each `hits`
    is that entry's `[(where, key)]`. A deeper path (`A > B > C`) is filed as
    the sub-entry "B, C".
    """
    by_key = {}
    for key, where in found:
        by_key.setdefault(key, []).append((where, key))
    mains, ratings = {}, {}
    for key, mark in enumerate(marks):
        hits = by_key.get(key)
        if not hits:
            continue
        if mark.get('stat'):
            if on(meta, 'index_cr') and mark.get('cr'):
                (ratings.setdefault(mark['cr'], {})
                        .setdefault(mark['path'][0], []).extend(hits))
            if not on(meta, 'index_statblocks'):
                continue
        path = mark['path']
        node = mains.setdefault(path[0], {'hits': [], 'subs': {}})
        if len(path) == 1:
            node['hits'].extend(hits)
        else:
            node['subs'].setdefault(', '.join(path[1:]), []).extend(hits)
    entries = [(main, node['hits'],
                sorted(node['subs'].items(), key=lambda kv: sort_key(kv[0])))
               for main, node in sorted(mains.items(), key=lambda kv: sort_key(kv[0]))]
    challenges = [(cr, sorted(names.items(), key=lambda kv: sort_key(kv[0])))
                  for cr, names in sorted(ratings.items(), key=lambda kv: cr_order(kv[0]))]
    return entries, challenges
