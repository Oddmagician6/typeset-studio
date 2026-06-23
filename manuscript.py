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

Anything before the first "# " is treated as the opening of an untitled first
chapter, so a plain manuscript with no headings still works.
"""

import re
import html


SCENE_BREAK_RE = re.compile(r'^\s*(\*\s*\*\s*\*|\*{3,}|-{3,}|#{3,})\s*$')
CHAPTER_RE = re.compile(r'^#\s+(.*)$')
SUBHEAD_RE = re.compile(r'^##\s+(.*)$')


def _inline(text):
    """Escape XML, then re-introduce ReportLab markup for *italic* / **bold**."""
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'_(?!\s)(.+?)(?<!\s)_', r'<i>\1</i>', text)
    return text


def parse_markdown(raw):
    """Return {'chapters': [{'title': str|None, 'blocks': [...] }]}.

    Each block is ('para', text) | ('subhead', text) | ('scene', None).
    """
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    chapters = []
    cur = None
    para_buf = []

    def flush_para():
        nonlocal para_buf
        if para_buf:
            joined = ' '.join(s.strip() for s in para_buf).strip()
            if joined:
                cur['blocks'].append(('para', _inline(joined)))
            para_buf = []

    def new_chapter(title):
        nonlocal cur
        flush_para() if cur else None
        cur = {'title': title, 'blocks': []}
        chapters.append(cur)

    for line in lines:
        m_ch = CHAPTER_RE.match(line)
        m_sub = SUBHEAD_RE.match(line)
        if m_ch:
            new_chapter(m_ch.group(1).strip() or None)
            continue
        if cur is None:
            new_chapter(None)  # untitled opening chapter
        if SCENE_BREAK_RE.match(line):
            flush_para()
            cur['blocks'].append(('scene', None))
            continue
        if m_sub:
            flush_para()
            cur['blocks'].append(('subhead', _inline(m_sub.group(1).strip())))
            continue
        if line.strip() == '':
            flush_para()
        else:
            para_buf.append(line)
    flush_para()

    # Drop fully-empty chapters that can appear from leading headings
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
