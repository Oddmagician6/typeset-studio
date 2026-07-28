"""Manuscript loading.

Canonical input is a light Markdown convention that writers can produce from any
tool. A .docx can be imported and converted to the same convention.

Conventions
-----------
  # Chapter Title        -> starts a new chapter (the title line is optional text)
  # Title | Author        -> chapter with an anthology byline under the title
  ##  Subhead            -> a centered subhead inside a chapter
  * * *  /  ***  /  ---  -> a scene break (on its own line)
  blank line             -> paragraph separator
  *italic*  **bold**     -> inline emphasis
  ~~~                    -> plain document block (indented / ruled / boxed per preset)
  ~~~ type key="value"   -> typed epistolary block; supported types:
                            letter   from="…" to="…" date="…"
                            journal  date="…" author="…"
                            telegram to="…"
                            newspaper headline="…" date="…" source="…"
                            redacted classification="…"

Anything before the first "# " is treated as the opening of an untitled first
chapter, so a plain manuscript with no headings still works.
"""

import os
import re
import html


# Fenced blocks whose content is line-oriented: every source line is its own item
# (a list), its own line (an alignment block) or its own row (a table), instead of
# being wrapped into a paragraph. Poems are line-oriented too but keep stanzas, so
# they're handled separately. doc_model.py and static/doc_model.js mirror this set.
LINE_BLOCKS = ('list', 'center', 'centre', 'right', 'left', 'table')

# A table row's cells are split on `|` at parse time — *before* inline markup is
# applied — and each cell is inlined on its own, then rejoined with this marker.
# Splitting the finished markup instead would break a link whose URL contains a
# pipe, and would make the renderers re-implement the emphasis rules. The marker
# never reaches ReportLab or the XHTML: both builders split it back out first.
# There is deliberately no escape for a literal `|` inside a cell — see the
# ROADMAP note; a context-free escape can't express it without teaching the
# round-trip model about cells.
CELL_SEP = '<cell/>'

SCENE_BREAK_RE = re.compile(r'^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$')
CHAPTER_RE     = re.compile(r'^#\s+(.*)$')

# `#* Prologue` — a chapter that takes no number and doesn't advance the count,
# so the chapter after it is still Chapter One. That's what a prologue, epilogue
# or interlude actually is: body text, not a matter page. `#` requires a space
# after it, so `#*` was previously an ordinary paragraph — nothing existing
# changes meaning.
UNNUMBERED_RE  = re.compile(r'^#\*\s+(.*)$')

# Anthology byline: "# Piece Title | Author Name" attaches a per-chapter byline
# (rendered under the title). The " | " separator is the KDP "Title | Subtitle"
# idiom; a title that genuinely contains " | " is vanishingly rare. Only the
# first separator splits, so any remainder stays with the byline (round-trip
# stable). No byline => the chapter behaves exactly as before.
BYLINE_SEP     = ' | '
SUBHEAD_RE     = re.compile(r'^##\s+(.*)$')
DOCBLOCK_RE    = re.compile(r'^\s*~~~(.*)')
PART_RE        = re.compile(r'^\s*===\s*(.*)')
_ATTR_RE       = re.compile(r'(\w+)="([^"]*)"')


# Backslash escapes for literal emphasis / marker characters. A writer (or the
# structured editor via doc_model) can type a literal '*' or '_' as \* or \_, a
# literal backslash as \\, or start a paragraph line with a block marker via
# \# / \~~~ / \=== . Escaped emphasis chars are parked on private-use codepoints
# across the emphasis substitutions, then restored to literals. This is inert on
# existing manuscripts, which contain no backslashes.
_BSL        = chr(92)
_PARK_STAR  = chr(0xE000)
_PARK_UNDER = chr(0xE001)
_PARK_BSL   = chr(0xE002)
_PARK_BRK   = chr(0xE003)


def _park_escapes(text):
    text = text.replace(_BSL + _BSL, _PARK_BSL)      # \\  -> literal backslash
    text = text.replace(_BSL + '*', _PARK_STAR)      # \*  -> literal *
    text = text.replace(_BSL + '_', _PARK_UNDER)     # \_  -> literal _
    text = text.replace(_BSL + '[', _PARK_BRK)       # \[  -> literal [
    return text


def _restore_escapes(text):
    return (text.replace(_PARK_STAR, '*')
                .replace(_PARK_UNDER, '_')
                .replace(_PARK_BRK, '[')
                .replace(_PARK_BSL, _BSL))


# A link is `[text](target)`. The target is deliberately restricted to things that
# are unambiguously links — a web address, an email, or an in-book `#anchor`. That
# keeps ordinary prose like "[sic](ibid)" from silently becoming a link, which a
# permissive rule would do to manuscripts that predate this feature.
LINK_TARGET = r'(?:https?://[^\s)]+|mailto:[^\s)]+|#[A-Za-z0-9][\w\-]*)'
LINK_RE = re.compile(r'\[([^\[\]]+)\]\((' + LINK_TARGET + r')\)')

# Endnotes. A reference `[^label]` sits in the sentence; its text is a paragraph
# `[^label]: …` anywhere in the same chapter. The label is the author's handle for
# the note — the *number* is assigned per chapter at parse time, so the PDF and the
# EPUB can never disagree about it.
NOTE_REF_RE = re.compile(r'\[\^([\w\-]+)\]')
NOTE_DEF_RE = re.compile(r'^\s*\[\^([\w\-]+)\]:\s*(.*)$')
_NOTE_TAG_RE = re.compile(r'<note n="(\d+)" id="([\w\-]+)"/>')


def _is_block_line(line):
    """True if a line would be parsed as a structural block (not a paragraph)."""
    return bool(
        SCENE_BREAK_RE.match(line) or CHAPTER_RE.match(line)
        or UNNUMBERED_RE.match(line)
        or SUBHEAD_RE.match(line) or DOCBLOCK_RE.match(line)
        or PART_RE.match(line)
    )


def _smarten(text):
    """Convert ASCII punctuation to typographic equivalents.

    Applied before html.escape so we work on plain characters only.
    """
    # em dashes — must do --- before -- to avoid double-converting
    text = text.replace('---', '—')
    text = text.replace('--',  '—')
    # ellipsis
    text = re.sub(r'\.{3,}', '…', text)
    # double quotes
    # opening: preceded by start-of-string, whitespace, open bracket, or em dash
    text = re.sub(r'(^|[\s(\[{—])"', r'\1“', text, flags=re.MULTILINE)
    text = text.replace('"', '”')                         # remaining → closing
    # single quotes / apostrophes
    text = re.sub(r"(\w)'(\w)", r'\1’\2', text)          # contractions first
    text = re.sub(r"(^|[\s(\[{—])'", r'\1‘', text, flags=re.MULTILINE)
    text = text.replace("'", '’')                         # remaining → closing/apostrophe
    # collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text


def _inline(text, smartquotes=True):
    """Escape XML, then re-introduce ReportLab markup for *italic* / **bold**.

    Backslash-escaped emphasis chars (\\* \\_ \\\\) are parked before the emphasis
    substitutions and restored as literals afterwards, so a deliberately typed
    asterisk or underscore renders literally instead of triggering markup.
    """
    text = _park_escapes(text)
    if smartquotes:
        text = _smarten(text)
    text = html.escape(text, quote=False)

    # Pull link targets out before the emphasis passes: a URL may contain
    # underscores or asterisks, which would otherwise be read as markup.
    targets = []

    def _stash(m):
        targets.append(m.group(2))
        return f'\x00{len(targets) - 1}\x00{m.group(1)}\x01'

    text = LINK_RE.sub(_stash, text)

    # Endnote references become a neutral marker; the number is filled in by
    # _number_notes once the whole chapter is known, and each builder decides
    # how to draw it.
    text = NOTE_REF_RE.sub(lambda m: f'<note id="{m.group(1)}"/>', text)

    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'_(?!\s)(.+?)(?<!\s)_', r'<i>\1</i>', text)

    if targets:
        # the link text keeps whatever emphasis it was given
        text = re.sub(
            r'\x00(\d+)\x00(.*?)\x01',
            lambda m: f'<a href="{html.escape(targets[int(m.group(1))], quote=True)}">'
                      f'{m.group(2)}</a>',
            text, flags=re.S)
    return _restore_escapes(text)


def _walk_block_texts(blocks):
    """Yield (setter, text) for every markup-bearing string in a chapter's blocks.

    Blocks are tuples, so a rewrite has to rebuild the list — the setter hides
    that from callers.
    """
    for i, block in enumerate(blocks):
        kind = block[0]
        if kind in ('para', 'subhead'):
            def _set(new, i=i, block=block):
                blocks[i] = (block[0], new)
            yield _set, block[1]
        elif kind == 'doc_block':
            for j, (_k, _t) in enumerate(block[1]):
                def _set(new, i=i, j=j, block=block):
                    inner = list(block[1])
                    inner[j] = (inner[j][0], new)
                    blocks[i] = (block[0], inner) + tuple(block[2:])
                yield _set, _t


def map_block_texts(chapters, fn):
    """Return a copy of `chapters` with every markup string passed through `fn`.

    Used by both builders to turn the neutral `<note …/>` marker into their own
    superscript. Returns a copy rather than editing in place: app.py parses once
    and hands the same structure to the PDF *and* the EPUB build.
    """
    out = []
    for ch in chapters:
        new = dict(ch)
        new['blocks'] = list(ch.get('blocks', []))
        for setter, text in _walk_block_texts(new['blocks']):
            new_text = fn(text, ch)
            if new_text != text:
                setter(new_text)
        out.append(new)
    return out


def _number_notes(chapter):
    """Assign endnote numbers in reading order and attach `chapter['notes']`.

    Numbers restart per chapter — the book convention, and what the Endnotes page
    groups by. Both builders read the number straight out of the marker, so they
    cannot drift apart. A reference with no `[^label]: …` still gets a number and
    a visible placeholder: a silently vanishing note is worse than an obvious one.
    """
    defs = chapter.pop('note_defs', {}) or {}
    seen, notes = {}, []

    def renumber(text):
        def sub(m):
            label = m.group(1)
            if label not in seen:
                seen[label] = len(seen) + 1
                notes.append({'n': seen[label], 'label': label,
                              'text': defs.get(label, '')})
            return f'<note n="{seen[label]}" id="{label}"/>'
        return re.sub(r'<note id="([\w\-]+)"/>', sub, text)

    for setter, text in _walk_block_texts(chapter.get('blocks', [])):
        if '<note id=' in text:
            setter(renumber(text))

    # a definition nobody referenced is still the author's writing — keep it,
    # numbered after the referenced ones, rather than dropping it
    for label, text in defs.items():
        if label not in seen:
            seen[label] = len(seen) + 1
            notes.append({'n': seen[label], 'label': label, 'text': text})

    if notes:
        chapter['notes'] = notes


def _split_byline(title_line):
    """Split a chapter heading body into (title|None, byline|None).

    'The Lottery | Shirley Jackson' -> ('The Lottery', 'Shirley Jackson').
    A heading with no ' | ' separator returns (title, None).
    """
    if title_line is None:
        return None, None
    if BYLINE_SEP in title_line:
        title, byline = title_line.split(BYLINE_SEP, 1)
        return (title.strip() or None), (byline.strip() or None)
    return (title_line.strip() or None), None


def _parse_block_header(header):
    """Parse '~~~ type key="value" …' into (type_str, attrs_dict).

    Returns ('', {}) for a plain ~~~ fence with no header text.
    """
    parts = header.strip().split(None, 1)
    if not parts:
        return '', {}
    block_type = parts[0].lower()
    attrs = dict(_ATTR_RE.findall(parts[1])) if len(parts) > 1 else {}
    return block_type, attrs


def parse_markdown(raw, smartquotes=True):
    """Return {'chapters': [{'title': str|None, 'byline': str|None, 'part': dict|None, 'blocks': [...] }]}.

    Each block is:
      ('para', text) | ('subhead', text) | ('scene', None)
      | ('doc_block', [('para', text), ...])
      | ('doc_block', [('para', text), ...], {'_type': str, attr: str, ...})

    'part' on each chapter is {'title': str|None, 'number': int} or None.
    """
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    chapters  = []
    cur       = None
    para_buf  = []

    # part tracking
    current_part = None
    part_number  = 0

    # endnote-definition state (`[^label]: …`, continued on following lines)
    note_label     = None
    note_buf       = []

    # doc-block state
    in_block       = False
    block_buf      = []
    block_para_buf = []
    block_type     = ''
    block_attrs    = {}

    def flush_note():
        nonlocal note_label, note_buf
        if note_label is not None:
            body = ' '.join(s.strip() for s in note_buf).strip()
            cur['note_defs'][note_label] = _inline(body, smartquotes)
            note_label, note_buf = None, []

    def flush_para():
        nonlocal para_buf
        flush_note()                            # a note ends where a paragraph does
        if para_buf:
            joined = ' '.join(s.strip() for s in para_buf).strip()
            if joined:
                cur['blocks'].append(('para', _inline(joined, smartquotes)))
            para_buf = []

    def flush_block_para():
        nonlocal block_para_buf
        if block_para_buf:
            if block_type == 'poem':
                # Verse: preserve line breaks. Each source line is a line of
                # verse; the blank-line-delimited group is one stanza, emitted as
                # a single 'para' with <br/> between lines. Keeps the doc_block
                # tuple contract intact for the engine / epub / round-trip layers.
                verse = [_inline(s.strip(), smartquotes) for s in block_para_buf
                         if s.strip()]
                if verse:
                    block_buf.append(('para', '<br/>'.join(verse)))
            elif block_type == 'table':
                # One source line = one row; cells split on `|`. Each cell is
                # inlined separately so emphasis and links work inside a cell.
                for s in block_para_buf:
                    if not s.strip():
                        continue
                    cells = [_inline(c.strip(), smartquotes) for c in s.split('|')]
                    block_buf.append(('para', CELL_SEP.join(cells)))
            elif block_type in LINE_BLOCKS:
                # One line = one item / one line of the block. Wrapping prose into
                # a paragraph is wrong here: a list's items and a sign's lines are
                # authored one per line, exactly as they read.
                for s in block_para_buf:
                    if s.strip():
                        block_buf.append(('para', _inline(s.strip(), smartquotes)))
            else:
                joined = ' '.join(s.strip() for s in block_para_buf).strip()
                if joined:
                    block_buf.append(('para', _inline(joined, smartquotes)))
            block_para_buf = []

    def new_chapter(title, byline=None, unnumbered=False):
        nonlocal cur
        flush_para() if cur else None
        cur = {'title': title, 'byline': byline, 'part': current_part, 'blocks': [],
               'note_defs': {}}
        if unnumbered:
            cur['unnumbered'] = True
        chapters.append(cur)

    for line in lines:
        # A leading backslash guarding a block marker => literal paragraph text.
        if not in_block and line[:1] == _BSL and _is_block_line(line[1:]):
            if cur is None:
                new_chapter(None)
            para_buf.append(line[1:])
            continue

        # `[^label]: …` — an endnote's text. Matched per line, not per paragraph:
        # notes are usually written as a consecutive run, and joining them first
        # would swallow every definition after the first into the one above it.
        if not in_block:
            m_ndef = NOTE_DEF_RE.match(line)
            if m_ndef:
                flush_para()
                if cur is None:
                    new_chapter(None)
                note_label, note_buf = m_ndef.group(1), [m_ndef.group(2)]
                continue
            if note_label is not None:
                if line.strip():                # a wrapped continuation line
                    note_buf.append(line)
                else:
                    flush_note()
                continue

        # === Part marker (only outside doc blocks)
        if not in_block:
            m_part = PART_RE.match(line)
            if m_part:
                flush_para()
                part_number += 1
                part_title = m_part.group(1).strip() or None
                current_part = {'title': part_title, 'number': part_number}
                continue

        # ~~~ fence — toggle doc-block mode; optional type + attrs on opening line
        m_doc = DOCBLOCK_RE.match(line)
        if m_doc:
            if in_block:
                flush_block_para()
                # A *typed* block is kept even when it has no content: a figure
                # usually has no caption, and dropping it would lose the
                # illustration. A plain empty ~~~ fence is still discarded.
                if block_buf or block_type:
                    blk = ('doc_block', list(block_buf))
                    if block_type:
                        blk = blk + ({'_type': block_type, **block_attrs},)
                    cur['blocks'].append(blk)
                block_buf[:] = []
                block_type = ''
                block_attrs = {}
                in_block = False
            else:
                flush_para()
                if cur is None:
                    new_chapter(None)
                block_type, block_attrs = _parse_block_header(m_doc.group(1))
                in_block = True
            continue

        # Inside a doc block: only paragraph text
        if in_block:
            if line.strip() == '':
                flush_block_para()
            else:
                block_para_buf.append(line)
            continue

        m_un  = UNNUMBERED_RE.match(line)
        m_ch  = m_un or CHAPTER_RE.match(line)
        m_sub = SUBHEAD_RE.match(line)
        if m_ch:
            _t, _by = _split_byline(m_ch.group(1))
            new_chapter(_t, _by, unnumbered=bool(m_un))
            continue
        if cur is None:
            new_chapter(None)
        if SCENE_BREAK_RE.match(line):
            flush_para()
            cur['blocks'].append(('scene', None))
            continue
        if m_sub:
            flush_para()
            cur['blocks'].append(('subhead', _inline(m_sub.group(1).strip(), smartquotes)))
            continue
        if line.strip() == '':
            flush_para()
        else:
            para_buf.append(line)

    # close any unclosed block
    if in_block:
        flush_block_para()
        if block_buf or block_type:
            blk = ('doc_block', list(block_buf))
            if block_type:
                blk = blk + ({'_type': block_type, **block_attrs},)
            cur['blocks'].append(blk)
    flush_para()

    chapters = [c for c in chapters if c['blocks'] or c['title']]
    for c in chapters:
        _number_notes(c)
    return {'chapters': chapters}


# ---------------------------------------------------------------- .docx import

# Images pulled out of a Word file are stored here as figures. app.py points this
# at the writable data dir (same arrangement as engine.FIGURE_DIR); manuscript.py
# never imports app or engine.
FIGURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures')

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def slugify(name):
    """'The Salt Road' -> 'the-salt-road'. Also the id used by `#anchor` links."""
    return _SLUG_RE.sub('-', (name or '').lower()).strip('-')


def chapter_numbers(chapters):
    """Displayed chapter numbers, `None` for an unnumbered one.

    Position (`idx`) and number are different things once `#*` exists: position
    still identifies the chapter — its file, its anchors, its notes — while the
    number is what the reader sees, and a prologue doesn't consume one. Both
    builders read from here so they can't drift.
    """
    out, n = [], 0
    for ch in chapters:
        if ch.get('unnumbered'):
            out.append(None)
        else:
            n += 1
            out.append(n)
    return out


def chapter_anchors(chapter, idx):
    """Link destinations for a chapter: `#chapter-N`, plus `#<title-slug>`.

    Lives here rather than in the engine because both outputs need the same
    answer — the PDF plants these as named destinations, the EPUB maps them to
    the chapter's file — and neither builder should have to import the other.
    The positional form is always present, so a chapter with no title (or a
    title that slugs to nothing) can still be linked to.
    """
    names = [f'chapter-{idx}']
    slug = slugify(chapter.get('title') or '')
    if slug and slug not in names:
        names.append(slug)
    return names


def _slug(name):
    return slugify(name) or 'image'


def _emph(runs):
    """Word runs -> Markdown emphasis, mirroring the old importer's rules."""
    out = []
    for r in runs:
        t = r.text
        if not t:
            continue
        if r.bold:
            t = f'**{t}**'
        elif r.italic:
            t = f'*{t}*'
        out.append(t)
    return ''.join(out)


def _one_line(text):
    """Collapse a Word paragraph's manual line breaks. Right for a heading, a
    list item or a table cell; wrong for body text, where the break is the
    author saying "break here" — see the poem/aligned handling in import_docx."""
    return ' '.join((text or '').split())


def _link_md(text, address):
    """`[text](url)` if the address is one this convention accepts, else None.

    ``LINK_TARGET`` is deliberately narrow (see the note beside it), so a Word
    link to a bookmark or a local file keeps its words and loses its address
    rather than producing a link the parser would not read back. Brackets in
    the text would break ``LINK_RE``'s own bracket matching, so those fall back
    too — rarer than a link, and a wrong link is worse than a plain phrase.
    """
    address = (address or '').strip()
    if not text or not address or '[' in text or ']' in text:
        return None
    if not re.fullmatch(LINK_TARGET, address):
        return None
    return f'[{text}]({address})'


def _notes_map(doc):
    """{(kind, word_id): note_text} from word/footnotes.xml and endnotes.xml.

    python-docx has no footnote API, so the parts are read straight off the
    package. Separator pseudo-notes (the little rule Word draws above the note
    area) carry a ``w:type`` and are skipped — they are furniture, not notes.
    """
    from docx.oxml.ns import qn
    from docx.oxml import parse_xml
    from docx.text.paragraph import Paragraph

    try:
        parts = list(doc.part.package.iter_parts())
    except Exception:
        return {}

    out = {}
    for part in parts:
        name = str(getattr(part, 'partname', ''))
        kind = ('footnote' if name.endswith('/footnotes.xml')
                else 'endnote' if name.endswith('/endnotes.xml') else '')
        if not kind:
            continue
        try:
            root = parse_xml(part.blob)
        except Exception:
            continue
        for el in root.findall(qn('w:' + kind)):
            if el.get(qn('w:type')):          # separator / continuationSeparator
                continue
            paras = [_one_line(_emph(Paragraph(pe, part).runs))
                     for pe in el.findall(qn('w:p'))]
            text = ' '.join(t for t in paras if t).strip()
            if text:
                out[(kind, el.get(qn('w:id')))] = text
    return out


def _run_note_refs(run):
    """(kind, word_id) for every footnote/endnote reference inside one run."""
    from docx.oxml.ns import qn
    found = []
    for kind in ('footnote', 'endnote'):
        for el in run._r.findall('.//' + qn(f'w:{kind}Reference')):
            found.append((kind, el.get(qn('w:id'))))
    return found


def _para_md(p, report, notes=None):
    """Paragraph text with emphasis, links and note references.

    ``Paragraph.runs`` skips runs nested in a ``w:hyperlink``, so the old
    importer silently dropped every linked phrase. ``iter_inner_content`` walks
    runs and hyperlinks in document order, which is also what lets a note
    reference land at the right point in the sentence rather than at the end.

    `notes` is the note context from ``import_docx``; pass None to skip note
    handling entirely (the table-cell path does).
    """
    try:
        parts = list(p.iter_inner_content())
    except AttributeError:                       # older python-docx
        return _emph(p.runs) or p.text

    chunks = []
    for item in parts:
        if hasattr(item, 'address'):             # Hyperlink
            text = _emph(item.runs)
            md = _link_md(text, getattr(item, 'address', ''))
            if md:
                report['links_kept'] += 1
                chunks.append(md)
            else:
                report['links'] += 1
                chunks.append(text)
            continue
        chunks.append(_emph([item]))
        if notes is not None:
            for ref in _run_note_refs(item):
                chunks.append(_note_ref(ref, notes, report))
    return ''.join(chunks) or p.text


def _note_ref(ref, notes, report):
    """A `[^label]` marker for one Word note, registering its text for output.

    Labels are allocated here rather than reused from Word's ids, which are
    sparse and start at 2. The same note cited twice keeps one label, exactly
    as the endnote convention already handles.
    """
    if ref in notes['seen']:
        return f'[^{notes["seen"][ref]}]'
    text = notes['texts'].get(ref)
    if not text:
        report['notes_lost'] += 1
        return ''
    notes['n'] += 1
    label = f'note{notes["n"]}'
    notes['seen'][ref] = label
    notes['defs'].append((label, text))
    report['notes'] += 1
    return f'[^{label}]'


def _para_images(p, stem, report):
    """Save every image embedded in a paragraph; yield (filename, alt) pairs.

    Names are content-addressed (``<docx>-<hash>.png``) so re-importing the same
    Word file overwrites the same figure instead of piling up duplicates — the
    project build path re-imports on every rebuild.
    """
    from docx.oxml.ns import qn
    import hashlib
    found = []
    blips = p._p.findall('.//' + qn('a:blip'))
    if not blips:
        return found
    # Real alt text lives in docPr/@descr, one per image, in document order.
    # @name is ignored on purpose — Word fills it with "Picture 1", which is
    # noise, not a description.
    descrs = [(el.get('descr') or '') for el in p._p.findall('.//' + qn('wp:docPr'))]
    for i, blip in enumerate(blips):
        rid = blip.get(qn('r:embed')) or blip.get(qn('r:link'))
        if not rid:
            continue
        try:
            part = p.part.related_parts[rid]
            blob = part.blob
        except Exception:
            report['images_failed'] += 1
            continue
        ext = os.path.splitext(str(part.partname))[1].lower() or '.png'
        if ext not in ('.png', '.jpg', '.jpeg', '.gif'):
            report['images_failed'] += 1
            continue
        fn = f'{stem}-{hashlib.sha1(blob).hexdigest()[:8]}{ext}'
        dest = os.path.join(FIGURE_DIR, fn)
        try:
            os.makedirs(FIGURE_DIR, exist_ok=True)
            if not os.path.exists(dest):
                with open(dest, 'wb') as f:
                    f.write(blob)
        except OSError:
            report['images_failed'] += 1
            continue
        found.append((fn, descrs[i] if i < len(descrs) else ''))
    return found


def _table_md(tbl, report):
    """A Word table -> a `~~~ table` block, one line per row.

    Cells keep their columns now that there is a table block to import into.
    A pipe inside a cell would read as a column break, so it becomes a slash —
    the one substitution made here, and vanishingly rare in a Word table.
    """
    rows = []
    for row in tbl.rows:
        cells = [' '.join(c.text.split()).replace('|', '/') for c in row.cells]
        # a merged row repeats the same cell object; collapse the repeats
        dedup = [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]
        if any(dedup):
            rows.append(' | '.join(dedup))
    if not rows:
        return []
    report['tables'] += 1
    # Word marks a header row in tblHeader; absent that, assume the first row is
    # one only when every cell in it is non-empty and the table has body rows
    header = len(rows) > 1 and all(c.strip() for c in rows[0].split('|'))
    fence = '~~~ table' + ('' if header else ' header="no"')
    return ['', fence] + rows + ['~~~', '']


def _new_report():
    return {'chapters': 0, 'subheads': 0, 'figures': 0, 'tables': 0,
            'quotes': 0, 'lists': 0, 'aligned': 0, 'poems': 0,
            'links': 0,        # kept their words, lost the address
            'links_kept': 0,   # kept the address too
            'notes': 0,        # Word footnotes/endnotes imported as endnotes
            'notes_lost': 0,   # a reference whose note text could not be read
            'breaks': 0,       # paragraphs whose manual line breaks were kept
            'images_failed': 0}


def import_docx(path, report=None):
    """Best-effort .docx -> canonical Markdown string.

    Heading 1/Title become chapters, other headings subheads; centered short
    asterisk paragraphs become scene breaks; bold/italic survive. Beyond that:

    * **images** are extracted to the figure library and placed as ``~~~ figure``
      blocks, with a following Caption-styled paragraph used as the caption;
    * **tables** become ``~~~ table`` blocks, columns intact, instead of being
      dropped — ``doc.paragraphs`` skips them entirely;
    * **hyperlinks** keep their address when it is one this convention accepts
      (see ``_link_md``), otherwise just their words;
    * **footnotes and endnotes** become ``[^label]`` references with their text
      collected at the end of the chapter that cites them;
    * **verse** (a Verse/Poem/Poetry paragraph style) becomes a ``~~~ poem``;
    * **manual line breaks** elsewhere are kept with a ``~~~ left`` block rather
      than being joined into a paragraph;
    * **Quote** styles become ``~~~ quote`` blocks;
    * **list items** become ``~~~ list`` blocks.

    Pass a dict as ``report`` to receive counts of what was imported and what
    could not be — ``import_summary`` turns it into a sentence for the UI.
    """
    from docx import Document
    from docx.table import Table

    rep = report if report is not None else {}
    rep.update({k: v for k, v in _new_report().items() if k not in rep})

    doc = Document(path)
    stem = _slug(os.path.splitext(os.path.basename(path))[0])
    # note text is read once up front; `defs` collects what the current chapter
    # cites, so the definitions land in the chapter that owns them
    notes = {'texts': _notes_map(doc), 'seen': {}, 'defs': [], 'n': 0}

    out = []
    quote_buf = []          # consecutive Quote-styled paragraphs -> one block
    list_buf = []           # consecutive list paragraphs -> one ~~~ list block
    poem_buf = []           # consecutive verse paragraphs -> one ~~~ poem
    list_numbered = False
    fig_caption_at = None   # index in `out` where a Caption paragraph can land

    def flush_quotes():
        nonlocal quote_buf
        if quote_buf:
            rep['quotes'] += 1
            out.extend(['', '~~~ quote'])
            for i, q in enumerate(quote_buf):
                if i:
                    out.append('')
                out.append(q)
            out.extend(['~~~', ''])
            quote_buf = []

    def flush_list():
        nonlocal list_buf
        if list_buf:
            header = '~~~ list type="number"' if list_numbered else '~~~ list'
            out.extend(['', header])
            for i, item in enumerate(list_buf):
                if i:
                    out.append('')
                out.append(item)
            out.extend(['~~~', ''])
            list_buf = []

    def flush_poem():
        nonlocal poem_buf
        if poem_buf:
            rep['poems'] += 1
            out.extend(['', '~~~ poem'])
            for i, stanza in enumerate(poem_buf):
                if i:
                    out.append('')            # a blank line starts a new stanza
                out.extend(stanza)
            out.extend(['~~~', ''])
            poem_buf = []

    def flush_notes():
        """Emit this chapter's note texts. They must sit in the chapter that
        cites them — numbering restarts per chapter — so this runs at every
        chapter boundary, not at the end of the document."""
        if notes['defs']:
            out.append('')
            for label, text in notes['defs']:
                out.append(f'[^{label}]: {text}')
            out.append('')
            notes['defs'] = []

    def flush_all():
        flush_quotes()
        flush_list()
        flush_poem()

    try:
        body = list(doc.iter_inner_content())
    except AttributeError:                        # older python-docx: no tables
        body = list(doc.paragraphs)

    for item in body:
        if isinstance(item, Table):
            # every buffer, not just quotes: whatever is still buffered came
            # *before* this table in the document and must be emitted first
            flush_all()
            fig_caption_at = None
            out.extend(_table_md(item, rep))
            continue

        p = item
        style = (p.style.name or '').lower()
        # keep the manual line breaks for now; each branch below decides whether
        # they mean anything (verse, an address block) or should be collapsed
        raw = _para_md(p, rep, notes).strip()
        lines = [ln.strip() for ln in raw.split('\n') if ln.strip()]
        text = _one_line(raw)

        images = _para_images(p, stem, rep)
        if images:
            flush_all()
            for fn, alt in images:
                rep['figures'] += 1
                alt_attr = f' alt="{alt}"' if alt and '"' not in alt else ''
                out.extend(['', f'~~~ figure src="{fn}"{alt_attr}', ''])
                fig_caption_at = len(out) - 1     # the blank line is the caption slot
                out.extend(['~~~', ''])
            if not text:
                continue                          # image-only paragraph

        if style.startswith('caption') and fig_caption_at is not None and text:
            out[fig_caption_at] = text            # caption belongs to the figure
            fig_caption_at = None
            continue
        if text:
            fig_caption_at = None

        if style.startswith('heading 1') or style == 'title':
            flush_all()
            flush_notes()                     # the outgoing chapter's notes
            rep['chapters'] += 1
            out.extend(['', '# ' + text, ''])
            continue
        if style.startswith('heading'):
            flush_all()
            rep['subheads'] += 1
            out.extend(['', '## ' + text, ''])
            continue
        if not text:
            continue
        if SCENE_BREAK_RE.match(text):
            flush_all()
            out.extend(['', '* * *', ''])
            continue
        # Word has no verse element; a style named for it is the only explicit
        # signal an author can give, so it is the only one trusted here
        if any(w in style for w in ('verse', 'poem', 'poetry')):
            flush_quotes()
            flush_list()
            poem_buf.append(lines)
            continue
        if 'quote' in style:
            flush_list()
            flush_poem()
            quote_buf.append(text)
            continue

        # a run of list paragraphs becomes one ~~~ list block
        is_list = ('list' in style
                   or (p._p.pPr is not None and p._p.pPr.numPr is not None))
        if is_list:
            numbered = 'number' in style
            if list_buf and numbered != list_numbered:
                flush_list()                  # bullets and numbers are separate lists
            flush_quotes()
            flush_poem()
            list_numbered = numbered
            rep['lists'] += 1
            list_buf.append(text)
            continue

        flush_all()

        # a centred paragraph that isn't a scene break becomes an alignment block
        try:
            centred = p.alignment is not None and 'CENTER' in str(p.alignment)
        except Exception:
            centred = False
        if centred:
            rep['aligned'] += 1
            out.extend(['', '~~~ center'] + lines + ['~~~', ''])
            continue

        # A manual line break is the author saying "break here" — Word's only
        # way to say it. Joining those lines into a paragraph loses the one
        # thing they were for, so they go in the line-preserving block that
        # claims the least: alignment only, no change of size or face.
        if len(lines) > 1:
            rep['breaks'] += 1
            out.extend(['', '~~~ left'] + lines + ['~~~', ''])
            continue

        out.extend([text, ''])

    flush_all()
    flush_notes()
    return '\n'.join(out)


def import_summary(rep):
    """Human-readable '…imported, …not imported' lines for a report dict."""
    if not rep:
        return '', ''
    got = []
    if rep.get('chapters'):
        got.append(f"{rep['chapters']} chapter" + ('s' if rep['chapters'] != 1 else ''))
    if rep.get('subheads'):
        got.append(f"{rep['subheads']} subhead" + ('s' if rep['subheads'] != 1 else ''))
    if rep.get('figures'):
        got.append(f"{rep['figures']} image" + ('s' if rep['figures'] != 1 else ''))
    if rep.get('tables'):
        got.append(f"{rep['tables']} table" + ('s' if rep['tables'] != 1 else ''))
    if rep.get('quotes'):
        got.append(f"{rep['quotes']} quotation" + ('s' if rep['quotes'] != 1 else ''))
    if rep.get('lists'):
        got.append(f"{rep['lists']} list item" + ('s' if rep['lists'] != 1 else ''))
    if rep.get('aligned'):
        got.append(f"{rep['aligned']} centred passage"
                   + ('s' if rep['aligned'] != 1 else ''))
    if rep.get('poems'):
        got.append(f"{rep['poems']} poem" + ('s' if rep['poems'] != 1 else ''))
    if rep.get('links_kept'):
        got.append(f"{rep['links_kept']} link" + ('s' if rep['links_kept'] != 1 else ''))
    if rep.get('notes'):
        got.append(f"{rep['notes']} note" + ('s' if rep['notes'] != 1 else '')
                   + ' (as endnotes)')
    if rep.get('breaks'):
        got.append(f"{rep['breaks']} passage" + ('s' if rep['breaks'] != 1 else '')
                   + ' with kept line breaks')

    lost = []
    if rep.get('links'):
        n = rep['links']
        lost.append(f"{n} link kept its text but not the address" if n == 1
                    else f"{n} links kept their text but not the addresses")
    if rep.get('notes_lost'):
        n = rep['notes_lost']
        lost.append(f"{n} note reference had no readable text" if n == 1
                    else f"{n} note references had no readable text")
    if rep.get('images_failed'):
        lost.append(f"{rep['images_failed']} image"
                    + ('s' if rep['images_failed'] != 1 else '') + ' could not be read')
    return ', '.join(got), '; '.join(lost)
