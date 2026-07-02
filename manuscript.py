"""Manuscript loading.

Canonical input is a light Markdown convention that writers can produce from any
tool. A .docx can be imported and converted to the same convention.

Conventions
-----------
  # Chapter Title        -> starts a new chapter (the title line is optional text)
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

import re
import html


SCENE_BREAK_RE = re.compile(r'^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$')
CHAPTER_RE     = re.compile(r'^#\s+(.*)$')
SUBHEAD_RE     = re.compile(r'^##\s+(.*)$')
DOCBLOCK_RE    = re.compile(r'^\s*~~~(.*)')
PART_RE        = re.compile(r'^\s*===\s*(.*)')
_ATTR_RE       = re.compile(r'(\w+)="([^"]*)"')


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
    """Escape XML, then re-introduce ReportLab markup for *italic* / **bold**."""
    if smartquotes:
        text = _smarten(text)
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'_(?!\s)(.+?)(?<!\s)_', r'<i>\1</i>', text)
    return text


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
    """Return {'chapters': [{'title': str|None, 'part': dict|None, 'blocks': [...] }]}.

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
            joined = ' '.join(s.strip() for s in block_para_buf).strip()
            if joined:
                block_buf.append(('para', _inline(joined, smartquotes)))
            block_para_buf = []

    def new_chapter(title):
        nonlocal cur
        flush_para() if cur else None
        cur = {'title': title, 'part': current_part, 'blocks': []}
        chapters.append(cur)

    for line in lines:
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
                if block_buf:
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
            new_chapter(m_ch.group(1).strip() or None)
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
        if block_buf:
            blk = ('doc_block', list(block_buf))
            if block_type:
                blk = blk + ({'_type': block_type, **block_attrs},)
            cur['blocks'].append(blk)
    flush_para()

    chapters = [c for c in chapters if c['blocks'] or c['title']]
    return {'chapters': chapters}


def import_docx(path):
    """Best-effort .docx -> canonical Markdown string.

    Heading 1/Title styles become chapters; centered short asterisk/blank
    paragraphs become scene breaks; bold/italic runs are preserved.
    """
    from docx import Document
    doc = Document(path)
    out = []
    for p in doc.paragraphs:
        style = (p.style.name or '').lower()
        text = p.text.strip()
        if style.startswith('heading 1') or style == 'title':
            out.append('')
            out.append('# ' + text)
            out.append('')
            continue
        if style.startswith('heading'):
            out.append('')
            out.append('## ' + text)
            out.append('')
            continue
        if not text:
            continue
        if SCENE_BREAK_RE.match(text):
            out.append('')
            out.append('* * *')
            out.append('')
            continue
        # rebuild inline emphasis from runs
        chunks = []
        for r in p.runs:
            t = r.text
            if not t:
                continue
            if r.bold:
                t = f'**{t}**'
            elif r.italic:
                t = f'*{t}*'
            chunks.append(t)
        out.append(''.join(chunks) if chunks else text)
        out.append('')
    return '\n'.join(out)
