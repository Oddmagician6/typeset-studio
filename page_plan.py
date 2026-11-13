"""The page plan (#75b-2): a book's designed pages in order, as a storyboard.

The manuscript stays the one record of where things go. A plan is read out of
it and written back into it, and only its `~~~ page src="…"` fences move:

    split(text)   -> [item]   each {'kind': 'page', 'src', 'side', 'text'}
                              or {'kind': 'text', 'text'} (everything else,
                              word for word: headings, typed prose, other
                              blocks, kept as one locked piece between pages)
    join(items)   -> text     the pieces again, a blank line between each

`split` reads fences the way `manuscript.parse_markdown` does (any line that
starts with ~~~ opens a block, or closes the one that is open; a backslash
before it makes it text), and `plan_of` checks the result against the parser
itself, so a manuscript the plan can't read the same way is never rewritten.

`layout` works out which printed page each design lands on, as the engine sets
them (`engine.BookDoc.handle_flowable`'s SideBreak): the first page is a right
one, a spread opens on a left page, `side=` asks for one, and a blank page
goes in where that takes one.
"""

import re

FENCE_RE = re.compile(r'^\s*~~~(.*)$')
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_SIDES = {'right': 'right', 'recto': 'right', 'left': 'left', 'verso': 'left'}

# Picture-book page counts (#75b-2): KDP prints no fewer than 24 pages; 32 is
# the classic book; a picture book much past 48 is a different kind of book.
# Printers fold sheets in fours (offset printers in eights), so the count
# wants to be a multiple of 4.
PB_MIN, PB_MAX, PB_STEP = 24, 48, 4


def _header(line):
    """(type, attrs) of a fence's opening line."""
    m = FENCE_RE.match(line)
    parts = (m.group(1) if m else '').strip().split(None, 1)
    if not parts:
        return '', {}
    return parts[0].lower(), dict(_ATTR_RE.findall(parts[1])) if len(parts) > 1 else {}


def side_of(attrs):
    return _SIDES.get(str((attrs or {}).get('side', '')).strip().lower(), 'any')


def split(text):
    """The manuscript as pieces: each page fence, and the text between them."""
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    items, buf = [], []

    def flush():
        # a text piece without the blank lines around it; nothing but blank
        # lines is no piece at all
        while buf and not buf[0].strip():
            buf.pop(0)
        while buf and not buf[-1].strip():
            buf.pop()
        if buf:
            items.append({'kind': 'text', 'text': '\n'.join(buf)})
        buf.clear()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if FENCE_RE.match(line):
            # a block runs to the next ~~~ line, or to the end
            j = i + 1
            while j < n and not FENCE_RE.match(lines[j]):
                j += 1
            block = lines[i:min(j, n - 1) + 1] if j < n else lines[i:]
            kind, attrs = _header(line)
            if kind == 'page':
                flush()
                items.append({'kind': 'page', 'src': (attrs.get('src') or '').strip(),
                              'side': side_of(attrs), 'text': '\n'.join(block)})
            else:
                buf.extend(block)
            i = j + 1
            continue
        buf.append(line)
        i += 1
    flush()
    return items


def rename(text, old, new, key=lambda s: s):
    """The manuscript with every page fence that places `old` placing `new`
    instead, nothing else touched. `key` compares names (wrap_design.page_name)."""
    lines = (text or '').split('\n')
    in_block, changed = False, False
    for i, line in enumerate(lines):
        if not FENCE_RE.match(line):
            continue
        if in_block:
            in_block = False
            continue
        in_block = True
        kind, attrs = _header(line)
        if kind == 'page' and key(attrs.get('src', '')) == key(old):
            lines[i] = re.sub(r'(\bsrc=")[^"]*(")', lambda m: m.group(1) + new + m.group(2),
                              line, count=1)
            changed = True
    return '\n'.join(lines) if changed else text


def join(items):
    """The pieces back into one manuscript."""
    text = '\n\n'.join(it['text'] for it in items if it.get('text', '').strip())
    return text + '\n' if text else ''


def fence(src, side='any'):
    """A new page fence."""
    s = f' side="{side}"' if side in ('left', 'right') else ''
    return f'~~~ page src="{src}"{s}\n~~~'


def readable(text, items=None):
    """Whether `split` reads the manuscript's page fences as the parser does:
    the same pages, in the same order (a page fence swallowed by a note, say,
    would otherwise be moved by the plan while the book ignores it)."""
    import manuscript, engine
    items = split(text) if items is None else items
    mine = [it['src'] for it in items if it['kind'] == 'page']
    try:
        theirs = engine.page_blocks(manuscript.parse_markdown(text, smartquotes=False))
    except Exception:
        return False
    return mine == theirs


def layout(items, designs, find, is_spread):
    """Where each piece lands: [{'item': i, 'pages': [n, …]}] plus the blank
    pages a design's side puts in ({'blank': n, 'why': …}), in page order, and
    the page count. `find(designs, name)` and `is_spread(design)` are
    wrap_design's. Text has no known length, so numbering stops at the first
    piece of it (`known` False from there)."""
    slots, p, known = [], 1, True
    for i, it in enumerate(items):
        if it['kind'] != 'page':
            known = False
            slots.append({'item': i, 'pages': []})
            continue
        if not known:
            slots.append({'item': i, 'pages': []})
            continue
        d = find(designs, it['src'])
        if d is not None and is_spread(d):
            if p % 2 == 1:
                slots.append({'blank': p, 'why': 'a spread opens on a left page'})
                p += 1
            slots.append({'item': i, 'pages': [p, p + 1]})
            p += 2
            continue
        want = it.get('side', 'any')
        if (want == 'right' and p % 2 == 0) or (want == 'left' and p % 2 == 1):
            slots.append({'blank': p, 'why': f'this page asks for a {want}-hand page'})
            p += 1
        slots.append({'item': i, 'pages': [p]})
        p += 1
    return slots, (p - 1 if known else None)


def count_problem(pages):
    """What is wrong with a picture book's page count, or ''."""
    if pages is None:
        return ''
    if pages < PB_MIN:
        return (f'{pages} pages: a picture book needs at least {PB_MIN} '
                f'(KDP\'s minimum); {PB_MIN - pages} more to go')
    if pages > PB_MAX:
        return (f'{pages} pages: longer than a picture book usually runs '
                f'({PB_MIN}-{PB_MAX}); fine for a longer illustrated book')
    if pages % PB_STEP:
        more = PB_STEP - pages % PB_STEP
        return (f'{pages} pages: printers fold picture books in fours, so add {more} '
                f'page{"s" if more > 1 else ""} (or take {pages % PB_STEP} away) to make '
                f'{pages + more}')
    return ''


# ---- art across the fold ------------------------------------------------------------
# On a perfect-bound paperback the middle of a spread disappears into the
# binding: glue takes the spine edge and the page curves into it. A picture or
# drawing that crosses the fold loses its middle; a flat colour doesn't matter.
FOLD_ZONE = 0.375          # inches each side of the fold that the binding eats


def art_across_fold(design, trim_w, trim_h):
    """Whether a spread has a picture or drawing reaching into the binding
    zone from both sides of the fold (a flat colour field is left alone)."""
    import wrap_design
    if not wrap_design.is_spread(design):
        return False
    g = wrap_design.design_geometry(design, trim_w, trim_h)
    fold = g['spine_x']
    for el in (design or {}).get('elements', []):
        if not isinstance(el, dict) or el.get('hidden') \
                or el.get('type') not in ('image', 'vector'):
            continue
        try:
            x, y, w, h = wrap_design.el_rect(g, el)
        except Exception:
            continue
        if w > 0 and x < fold - 0.01 and x + w > fold + 0.01:
            return True
    return False
