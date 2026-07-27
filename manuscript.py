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
# (a list) or its own line (an alignment block), instead of being wrapped into a
# paragraph. Poems are line-oriented too but keep stanzas, so they're handled
# separately. doc_model.py and static/doc_model.js mirror this set.
LINE_BLOCKS = ('list', 'center', 'centre', 'right', 'left')

SCENE_BREAK_RE = re.compile(r'^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$')
CHAPTER_RE     = re.compile(r'^#\s+(.*)$')

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


def _park_escapes(text):
    text = text.replace(_BSL + _BSL, _PARK_BSL)      # \\  -> literal backslash
    text = text.replace(_BSL + '*', _PARK_STAR)      # \*  -> literal *
    text = text.replace(_BSL + '_', _PARK_UNDER)     # \_  -> literal _
    return text


def _restore_escapes(text):
    return (text.replace(_PARK_STAR, '*')
                .replace(_PARK_UNDER, '_')
                .replace(_PARK_BSL, _BSL))


def _is_block_line(line):
    """True if a line would be parsed as a structural block (not a paragraph)."""
    return bool(
        SCENE_BREAK_RE.match(line) or CHAPTER_RE.match(line)
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
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'_(?!\s)(.+?)(?<!\s)_', r'<i>\1</i>', text)
    return _restore_escapes(text)


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

    # doc-block state
    in_block       = False
    block_buf      = []
    block_para_buf = []
    block_type     = ''
    block_attrs    = {}

    def flush_para():
        nonlocal para_buf
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

    def new_chapter(title, byline=None):
        nonlocal cur
        flush_para() if cur else None
        cur = {'title': title, 'byline': byline, 'part': current_part, 'blocks': []}
        chapters.append(cur)

    for line in lines:
        # A leading backslash guarding a block marker => literal paragraph text.
        if not in_block and line[:1] == _BSL and _is_block_line(line[1:]):
            if cur is None:
                new_chapter(None)
            para_buf.append(line[1:])
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

        m_ch  = CHAPTER_RE.match(line)
        m_sub = SUBHEAD_RE.match(line)
        if m_ch:
            _t, _by = _split_byline(m_ch.group(1))
            new_chapter(_t, _by)
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
    return {'chapters': chapters}


# ---------------------------------------------------------------- .docx import

# Images pulled out of a Word file are stored here as figures. app.py points this
# at the writable data dir (same arrangement as engine.FIGURE_DIR); manuscript.py
# never imports app or engine.
FIGURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures')

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _slug(name):
    return _SLUG_RE.sub('-', (name or '').lower()).strip('-') or 'image'


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


def _para_md(p, report):
    """Paragraph text with emphasis, including runs inside hyperlinks.

    ``Paragraph.runs`` skips runs nested in a ``w:hyperlink``, so the old
    importer silently dropped every linked phrase. ``iter_inner_content`` walks
    runs and hyperlinks in document order. The URL itself is dropped (the book
    model has no link type yet) but the words survive, and the link is counted.
    """
    try:
        parts = list(p.iter_inner_content())
    except AttributeError:                       # older python-docx
        return _emph(p.runs) or p.text.strip()
    chunks = []
    for item in parts:
        if hasattr(item, 'address'):             # Hyperlink
            report['links'] += 1
            chunks.append(_emph(item.runs))
        else:
            chunks.append(_emph([item]))
    return ''.join(chunks) or p.text.strip()


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
    """A Word table -> a plain ~~~ block, one paragraph per row.

    There is no table block type yet, so this preserves the words (set apart from
    the body) rather than dropping them. The import summary says so plainly.
    """
    rows = []
    for row in tbl.rows:
        cells = [' '.join(c.text.split()) for c in row.cells]
        # a merged row repeats the same cell object; collapse the repeats
        dedup = [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]
        line = ' · '.join(c for c in dedup if c)
        if line:
            rows.append(line)
    if not rows:
        return []
    report['tables'] += 1
    out = ['', '~~~']
    for i, r in enumerate(rows):
        if i:
            out.append('')
        out.append(r)
    out += ['~~~', '']
    return out


def _new_report():
    return {'chapters': 0, 'subheads': 0, 'figures': 0, 'tables': 0,
            'quotes': 0, 'lists': 0, 'aligned': 0, 'links': 0, 'footnotes': 0,
            'images_failed': 0}


def import_docx(path, report=None):
    """Best-effort .docx -> canonical Markdown string.

    Heading 1/Title become chapters, other headings subheads; centered short
    asterisk paragraphs become scene breaks; bold/italic survive. Beyond that:

    * **images** are extracted to the figure library and placed as ``~~~ figure``
      blocks, with a following Caption-styled paragraph used as the caption;
    * **tables** become plain ``~~~`` blocks (no table type yet) instead of being
      dropped — ``doc.paragraphs`` skips them entirely;
    * **hyperlink text** is kept (see ``_para_md``);
    * **Quote** styles become plain ``~~~`` blocks;
    * **list items** keep a bullet or number prefix as literal text.

    Pass a dict as ``report`` to receive counts of what was imported and what
    could not be — ``import_summary`` turns it into a sentence for the UI.
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table

    rep = report if report is not None else {}
    rep.update({k: v for k, v in _new_report().items() if k not in rep})

    doc = Document(path)
    stem = _slug(os.path.splitext(os.path.basename(path))[0])
    rep['footnotes'] = (len(doc.element.body.findall('.//' + qn('w:footnoteReference')))
                        + len(doc.element.body.findall('.//' + qn('w:endnoteReference'))))

    out = []
    quote_buf = []          # consecutive Quote-styled paragraphs -> one block
    list_buf = []           # consecutive list paragraphs -> one ~~~ list block
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

    def flush_all():
        flush_quotes()
        flush_list()

    try:
        body = list(doc.iter_inner_content())
    except AttributeError:                        # older python-docx: no tables
        body = list(doc.paragraphs)

    for item in body:
        if isinstance(item, Table):
            flush_quotes()
            fig_caption_at = None
            out.extend(_table_md(item, rep))
            continue

        p = item
        style = (p.style.name or '').lower()
        text = _para_md(p, rep).strip()

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
        if 'quote' in style:
            flush_list()
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
            out.extend(['', '~~~ center', text, '~~~', ''])
            continue

        out.extend([text, ''])

    flush_all()
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

    lost = []
    if rep.get('tables'):
        lost.append('tables were kept as set-apart blocks, not laid out as tables')
    if rep.get('links'):
        n = rep['links']
        lost.append(f"{n} link kept its text but not the web address" if n == 1
                    else f"{n} links kept their text but not the web addresses")
    if rep.get('footnotes'):
        lost.append(f"{rep['footnotes']} footnote/endnote"
                    + ('s were' if rep['footnotes'] != 1 else ' was') + ' not imported')
    if rep.get('images_failed'):
        lost.append(f"{rep['images_failed']} image"
                    + ('s' if rep['images_failed'] != 1 else '') + ' could not be read')
    return ', '.join(got), '; '.join(lost)
