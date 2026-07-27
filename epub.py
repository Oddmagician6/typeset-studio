"""EPUB 3 builder: manuscript + preset -> .epub file.

Stdlib-only (zipfile, uuid, datetime) — no extra dependencies.
Reuses the same parsed manuscript structure as engine.py.
"""

import html
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone


# ---------------------------------------------------------------- markup
def _markup_to_html(text):
    """Convert ReportLab XML tags to HTML equivalents."""
    text = text.replace('<b>', '<strong>').replace('</b>', '</strong>')
    text = text.replace('<i>', '<em>').replace('</i>', '</em>')
    return text


def _md_emph_to_html(text):
    """Escape XML, then convert Markdown emphasis to HTML (bold before italic).

    Mirrors manuscript._inline's emphasis substitutions, for the few places that
    render raw author text (e.g. the contributors page) rather than already-parsed
    manuscript blocks.
    """
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'_(?!\s)(.+?)(?<!\s)_', r'<em>\1</em>', text)
    return text


# ---------------------------------------------------------------- CSS
def _style_css():
    return """\
body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 100%;
  line-height: 1.6;
  margin: 0;
  padding: 0;
}
.chapter { margin: 0 5%; }
h1.chapter-num {
  font-size: 0.85em;
  font-weight: normal;
  text-align: center;
  color: #666;
  margin: 3em 0 0.4em;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
h1.chapter-title {
  font-size: 1.4em;
  font-weight: bold;
  text-align: center;
  margin: 0.3em 0 1.5em;
}
p.chapter-byline {
  font-style: italic;
  text-align: center;
  text-indent: 0;
  color: #444;
  margin: -1em 0 1.6em;
}
p { margin: 0; text-indent: 1.5em; }
p.no-indent { text-indent: 0; }
h2 {
  font-size: 1em;
  font-weight: bold;
  text-align: center;
  margin: 1.5em 0 0.8em;
}
p.scene-break {
  text-align: center;
  text-indent: 0;
  margin: 1.2em 0;
  color: #666;
}
.front { margin: 0 5%; text-align: center; }
.front h1.main { font-size: 1.8em; margin: 3em 0 0.4em; }
.front p.subtitle { font-size: 1.1em; font-style: italic; margin: 0.3em 0; }
.front p.author { font-size: 1.1em; margin: 0.8em 0 2em; }
.copyright { margin: 0 5%; font-size: 0.8em; line-height: 1.5; margin-top: 40%; }
.cover-page { text-align: center; margin: 0; padding: 0; }
.cover-page img { max-width: 100%; max-height: 100vh; }
.doc-block {
  margin: 1.2em 8%;
  border-top: 1px solid #aaa;
  border-bottom: 1px solid #aaa;
  padding: 0.7em 0;
  font-size: 0.95em;
}
.doc-block p { text-indent: 0; margin: 0.4em 0; }
.doc-block header { font-style: italic; font-size: 0.9em; color: #555; margin-bottom: 0.5em; border-bottom: 1px solid #ccc; padding-bottom: 0.3em; }
.doc-block-journal { font-style: italic; }
.doc-block-telegram { font-family: monospace; border: 1px solid #888; padding: 0.7em 1em; }
.doc-block-telegram header { font-family: serif; font-weight: bold; font-style: normal; text-align: center; font-size: 1em; color: #222; border-bottom: 1px solid #888; }
.doc-block-newspaper header { font-size: 1.05em; font-weight: bold; font-style: normal; text-align: center; color: #111; border-bottom: 2px solid #333; padding-bottom: 0.2em; }
.doc-block-newspaper header span.byline { display: block; font-size: 0.85em; font-weight: normal; font-style: italic; color: #555; }
.doc-block-redacted { border: 1px solid #333; }
.doc-block-redacted header { font-weight: bold; font-style: normal; text-align: center; background: #e8e8e8; color: #111; padding: 0.3em; margin: -0.7em -0em 0.5em; font-size: 0.85em; letter-spacing: 0.05em; }
.doc-block-poem { border: 0; padding: 0; margin: 1.4em 6%; font-size: 1em; }
.doc-block-poem header.poem-title { font-style: italic; font-weight: bold; text-align: left; color: #222; border-bottom: 0; margin-bottom: 0.6em; font-size: 1.05em; }
.doc-block-poem p { text-align: left; margin: 0 0 0.8em; padding-left: 1.4em; text-indent: -1.4em; }
ul.block-list, ol.block-list { margin: 1em 0 1em 1.4em; padding-left: 1em; }
ul.block-list li, ol.block-list li { margin: 0.25em 0; text-indent: 0; }
blockquote.block-quote { margin: 1.1em 6%; font-size: 0.95em; }
blockquote.block-quote p { text-indent: 0; margin: 0 0 0.4em; }
blockquote.block-quote p.quote-source { text-align: right; font-style: italic; font-size: 0.9em; color: #555; margin-top: 0.3em; }
.align p { text-indent: 0; margin: 0.2em 0; }
.align-center { text-align: center; }
.align-right { text-align: right; }
.align-left { text-align: left; }
figure.figure { margin: 1.4em 0; padding: 0; text-align: center; page-break-inside: avoid; }
figure.figure img { max-width: 100%; height: auto; }
figure.figure-full { page-break-before: always; page-break-after: always; margin: 0; }
figure.figure-full img { max-height: 92vh; }
figure.figure figcaption { font-size: 0.85em; font-style: italic; color: #555; text-indent: 0; margin-top: 0.5em; }
p.figure-missing { text-indent: 0; color: #777; font-size: 0.85em; }
.part-page { margin: 0 5%; text-align: center; padding-top: 30%; }
.part-page .part-num { font-size: 0.9em; color: #666; margin: 0 0 0.5em; letter-spacing: 0.06em; }
.part-page .part-title { font-size: 1.6em; font-weight: bold; margin: 0; }
.matter-body .matter-head { font-size: 1.4em; font-weight: bold; text-align: center; margin: 2em 0 1em; }
.matter-body p { margin: 0; text-indent: 1.5em; }
.matter-body p.no-indent { text-indent: 0; }
.matter-dedication { text-align: center; padding-top: 25%; font-style: italic; }
.matter-dedication p { text-indent: 0; margin: 0.4em 0; }
.matter-epigraph { margin: 0 10%; padding-top: 25%; }
.matter-epigraph p { text-indent: 0; margin: 0.3em 0; }
.matter-epigraph .attr { text-align: right; color: #555; font-size: 0.9em; margin-top: 0.6em; }
.toc-list { list-style: none; padding: 0; margin: 0; }
.toc-list li { padding: 0.25em 0; border-bottom: 1px solid #eee; }
.toc-list li a { text-decoration: none; color: inherit; }
.toc-part { font-weight: bold; margin-top: 0.8em; border-bottom: none !important; }
.toc-indent { padding-left: 1.5em; }
.matter-alsoby { text-align: center; }
.matter-alsoby .matter-head { font-size: 1.2em; font-weight: bold; margin: 2em 0 1em; }
.matter-alsoby p { text-indent: 0; margin: 0.3em 0; }
.matter-contributors .matter-head { font-size: 1.4em; font-weight: bold; text-align: center; margin: 2em 0 1em; }
.matter-contributors p { text-indent: 0; margin: 0.8em 0; }
"""


# ---------------------------------------------------------------- XHTML helpers
def _xhtml(title, body_content, css_href='style.css'):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8"/>\n'
        f'  <title>{title}</title>\n'
        f'  <link rel="stylesheet" type="text/css" href="{css_href}"/>\n'
        '</head>\n'
        '<body>\n'
        + body_content +
        '</body>\n</html>\n'
    )


def _default_copyright(meta):
    lines = [
        f"Copyright © {meta.get('year', '')} {meta.get('author', '')}".strip(),
        '', 'All rights reserved.', '',
        'This is a work of fiction. Names, characters, places, and incidents are '
        'the products of the author’s imagination or used fictitiously.',
    ]
    if meta.get('publisher'):
        lines += ['', meta['publisher']]
    return '\n'.join(lines)


def _toc_page_xhtml(chapters, preset):
    """In-text TOC page for EPUB — chapter links, no page numbers."""
    c        = preset.get('chapter', {})
    show_num = c.get('show_number', True)
    num_fmt  = c.get('number_format', 'Chapter {n}')
    pd       = preset.get('part_divider', {})
    pd_fmt   = pd.get('number_format', 'Part {n}')

    body = '<div class="matter-body">\n  <h1 class="matter-head">Contents</h1>\n  <ul class="toc-list">\n'
    current_part_num = None
    for idx, ch in enumerate(chapters, start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None
        if ch_part_num is not None and ch_part_num != current_part_num:
            part_label = ch_part.get('title') or pd_fmt.format(n=ch_part_num)
            body += f'    <li class="toc-part"><a href="part{ch_part_num:03d}.xhtml">{part_label}</a></li>\n'
            current_part_num = ch_part_num
        label = ch.get('title') or (num_fmt.format(n=idx) if show_num else f'Chapter {idx}')
        indent = ' class="toc-indent"' if ch_part_num is not None else ''
        body += f'    <li{indent}><a href="chapter{idx:03d}.xhtml">{label}</a></li>\n'
    body += '  </ul>\n</div>\n'
    return _xhtml('Contents', body)


def _part_xhtml(part_num, title, preset):
    pd       = preset.get('part_divider', {})
    show_num = pd.get('show_number', True)
    num_fmt  = pd.get('number_format', 'Part {n}')
    body = '<div class="part-page">\n'
    if show_num:
        body += f'  <p class="part-num">{num_fmt.format(n=part_num)}</p>\n'
    if title:
        body += f'  <h1 class="part-title">{title}</h1>\n'
    body += '</div>\n'
    return _xhtml(title or f'Part {part_num}', body)


def _cover_xhtml(img_filename):
    body = (
        '<div class="cover-page">\n'
        f'  <img src="{img_filename}" alt="Cover"/>\n'
        '</div>\n'
    )
    return _xhtml('Cover', body)


def _front_xhtml(meta):
    level    = meta.get('front_matter', 'full')
    title    = meta.get('title', '')
    subtitle = meta.get('subtitle', '')
    author   = meta.get('author', '')
    cp_text  = meta.get('copyright') or _default_copyright(meta)
    cp_html  = cp_text.replace('\n', '<br/>')

    body = '<div class="front">\n'

    if level == 'full':
        body += f'  <h1 class="main">{title}</h1>\n'
        body += '  <hr style="margin: 2em auto; width: 30%"/>\n'

    if level in ('full', 'title'):
        body += f'  <h1 class="main">{title}</h1>\n'
        if subtitle:
            body += f'  <p class="subtitle">{subtitle}</p>\n'
        body += f'  <p class="author">{author}</p>\n'

    body += '</div>\n'

    if level in ('full', 'title', 'copyright'):
        body += f'<div class="copyright"><p>{cp_html}</p></div>\n'

    return _xhtml(title or 'Front Matter', body)


def _matter_xhtml(heading, text, css_class):
    """XHTML page for a front/back matter section."""
    blocks = [b.strip() for b in text.replace('\r\n', '\n').split('\n\n') if b.strip()]
    body   = f'<div class="{css_class}">\n'
    if heading:
        body += f'  <h1 class="matter-head">{heading}</h1>\n'
    _attr_markers = ('—', '–', '--', '-')
    for i, b in enumerate(blocks):
        cls = ''
        if css_class == 'matter-epigraph':
            if i == len(blocks) - 1 and any(b.startswith(m) for m in _attr_markers):
                cls = ' class="attr"'
        elif css_class == 'matter-body' and i == 0:
            cls = ' class="no-indent"'
        elif css_class == 'matter-contributors':
            # Bold the name (text before an em dash / '--'); rest is the bio.
            name, bio = b, ''
            for sep in ('—', '--'):
                if sep in b:
                    name, bio = b.split(sep, 1)
                    break
            md = '**' + name.strip() + '**'
            if bio.strip():
                md += ' — ' + bio.strip()
            body += f'  <p>{_md_emph_to_html(md)}</p>\n'
            continue
        body += f'  <p{cls}>{_markup_to_html(b)}</p>\n'
    body += '</div>\n'
    return _xhtml(heading or 'Front Matter', body)


def _figure_html(caption_paras, attrs, figures):
    """<figure> for a ~~~ figure block. `figures` maps src -> in-zip href."""
    src   = (attrs.get('src', '') or '').strip()
    href  = (figures or {}).get(src)
    alt   = html.escape(attrs.get('alt', '') or src, quote=True)
    width = (attrs.get('width', '') or '').strip()
    style = ''
    if width:
        try:                                     # fraction of the column, as a %
            style = f' style="width:{min(100.0, max(5.0, float(width) * 100)):.0f}%"'
        except (TypeError, ValueError):
            style = ''
    cls = 'figure figure-full' if str(attrs.get('full', '')).strip().lower() \
        in ('1', 'yes', 'true', 'page') else 'figure'
    out = [f'  <figure class="{cls}">']
    if href:
        out.append(f'    <img src="{href}" alt="{alt}"{style}/>')
    else:
        # keep the caption and say what is missing, rather than dropping it
        out.append(f'    <p class="figure-missing">[missing image: {html.escape(src)}]</p>')
    caption = ' '.join(_markup_to_html(t) for _, t in caption_paras if t)
    if caption:
        out.append(f'    <figcaption>{caption}</figcaption>')
    out.append('  </figure>')
    return out


def _chapter_xhtml(idx, chapter, preset, figures=None):
    c          = preset.get('chapter', {})
    show_num   = c.get('show_number', True)
    num_fmt    = c.get('number_format', 'Chapter {n}')
    scene_glyph = preset.get('scene_break', {}).get('glyph', '* * *')

    lines = ['<div class="chapter">']

    if show_num:
        lines.append(f'  <h1 class="chapter-num">{num_fmt.format(n=idx)}</h1>')

    if chapter.get('title'):
        lines.append(f'  <h1 class="chapter-title">{_markup_to_html(chapter["title"])}</h1>')

    if chapter.get('byline'):
        lines.append(f'  <p class="chapter-byline">{_markup_to_html(chapter["byline"])}</p>')

    opened         = False
    no_indent_next = False

    for block in chapter.get('blocks', []):
        kind = block[0]
        val  = block[1]
        if kind == 'scene':
            lines.append(f'  <p class="scene-break">{scene_glyph}</p>')
            no_indent_next = True
        elif kind == 'subhead':
            lines.append(f'  <h2>{_markup_to_html(val)}</h2>')
            no_indent_next = True
        elif kind == 'doc_block':
            meta   = block[2] if len(block) > 2 else {}
            btype  = meta.get('_type', '')
            attrs  = {k: v for k, v in meta.items() if k != '_type'}
            if btype == 'figure':
                lines.extend(_figure_html(val, attrs, figures))
                no_indent_next = True
                continue
            if btype == 'list':
                numbered = (attrs.get('type', '') or '').lower().startswith('num')
                tag = 'ol' if numbered else 'ul'
                start = ''
                if numbered and attrs.get('start', '').strip().isdigit():
                    start = f' start="{attrs["start"].strip()}"'
                lines.append(f'  <{tag} class="block-list"{start}>')
                for _, text in val:
                    lines.append(f'    <li>{_markup_to_html(text)}</li>')
                lines.append(f'  </{tag}>')
                no_indent_next = True
                continue
            if btype == 'quote':
                lines.append('  <blockquote class="block-quote">')
                for _, text in val:
                    lines.append(f'    <p>{_markup_to_html(text)}</p>')
                source = (attrs.get('source', '') or '').strip()
                if source:
                    lines.append(f'    <p class="quote-source">{_md_emph_to_html(source)}</p>')
                lines.append('  </blockquote>')
                no_indent_next = True
                continue
            if btype in ('center', 'centre', 'right', 'left'):
                how = 'center' if btype in ('center', 'centre') else btype
                lines.append(f'  <div class="align align-{how}">')
                for _, text in val:
                    lines.append(f'    <p>{_markup_to_html(text)}</p>')
                lines.append('  </div>')
                no_indent_next = True
                continue
            cls    = f'doc-block doc-block-{btype}' if btype else 'doc-block'
            lines.append(f'  <div class="{cls}">')
            # Per-type header element
            if btype == 'letter':
                parts = []
                if attrs.get('from') and attrs.get('to'):
                    parts.append(f'{attrs["from"]} to {attrs["to"]}')
                elif attrs.get('from'):
                    parts.append(attrs['from'])
                elif attrs.get('to'):
                    parts.append(f'To: {attrs["to"]}')
                if attrs.get('date'):
                    parts.append(attrs['date'])
                if parts:
                    lines.append(f'    <header>{" · ".join(parts)}</header>')
            elif btype == 'journal':
                parts = [p for p in (attrs.get('date', ''), attrs.get('author', '')) if p]
                if parts:
                    lines.append(f'    <header>{" · ".join(parts)}</header>')
            elif btype == 'telegram':
                lines.append('    <header>TELEGRAM</header>')
                if attrs.get('to'):
                    lines.append(f'    <p class="no-indent">To: {attrs["to"].upper()}</p>')
            elif btype == 'newspaper':
                hl = attrs.get('headline', '')
                src = attrs.get('source', '')
                date = attrs.get('date', '')
                byline_parts = [p for p in (src, date) if p]
                hdr = (f'<span class="headline">{hl.upper()}</span>' if hl else '') + \
                      (f'<span class="byline">{" · ".join(byline_parts)}</span>' if byline_parts else '')
                if hdr:
                    lines.append(f'    <header>{hdr}</header>')
            elif btype == 'redacted':
                classification = attrs.get('classification', '')
                if classification:
                    lines.append(f'    <header>{classification.upper()}</header>')
            elif btype == 'poem':
                ptitle = attrs.get('title', '')
                if ptitle:
                    ptitle = (ptitle.replace('&', '&amp;')
                                    .replace('<', '&lt;').replace('>', '&gt;'))
                    lines.append(f'    <header class="poem-title">{ptitle}</header>')
            for bi, (_, btext) in enumerate(val):
                body_text = btext.upper() if btype == 'telegram' else _markup_to_html(btext)
                cls_p = ' class="no-indent"' if bi == 0 else ''
                lines.append(f'    <p{cls_p}>{body_text}</p>')
            lines.append('  </div>')
            no_indent_next = True
        else:
            html_val = _markup_to_html(val)
            cls = 'no-indent' if (not opened or no_indent_next) else None
            attr = f' class="{cls}"' if cls else ''
            lines.append(f'  <p{attr}>{html_val}</p>')
            opened = True
            no_indent_next = False

    lines.append('</div>\n')
    ch_title = chapter.get('title') or (num_fmt.format(n=idx) if show_num else f'Chapter {idx}')
    return _xhtml(ch_title, '\n'.join(lines))


# ---------------------------------------------------------------- OPF / NAV
def _container_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:schemas:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf"'
        ' media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    )


def _content_opf(uid, meta, manifest_items, spine_items, modified):
    title  = meta.get('title', 'Untitled')
    author = meta.get('author', '')
    year   = meta.get('year', '')

    def _item(i):
        props = f' properties="{i["props"]}"' if i.get('props') else ''
        return (f'    <item id="{i["id"]}" href="{i["href"]}"'
                f' media-type="{i["type"]}"{props}/>')
    manifest_xml = '\n'.join(_item(i) for i in manifest_items)
    spine_xml = '\n'.join(f'    <itemref idref="{s}"/>' for s in spine_items)

    # Legacy cover pointer. EPUB 3 readers use the manifest's
    # properties="cover-image", but Kindle tooling and older readers only look for
    # this <meta>; emitting both is what every mainstream tool does.
    cover_id = next((i['id'] for i in manifest_items
                     if 'cover-image' in (i.get('props') or '')), '')
    cover_meta_xml = (f'    <meta name="cover" content="{cover_id}"/>\n'
                      if cover_id else '')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="uid" xml:lang="en">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
        f'    <dc:title>{title}</dc:title>\n'
        f'    <dc:creator>{author}</dc:creator>\n'
        '    <dc:language>en</dc:language>\n'
        f'    <dc:date>{year}</dc:date>\n'
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        + cover_meta_xml +
        '  </metadata>\n'
        '  <manifest>\n'
        + manifest_xml + '\n'
        '  </manifest>\n'
        '  <spine>\n'
        + spine_xml + '\n'
        '  </spine>\n'
        '</package>\n'
    )


def _nav_xhtml(chapters, has_cover, has_front, preset, meta=None):
    c        = preset.get('chapter', {})
    show_num = c.get('show_number', True)
    num_fmt  = c.get('number_format', 'Chapter {n}')
    pd       = preset.get('part_divider', {})
    pd_fmt   = pd.get('number_format', 'Part {n}')

    meta = meta or {}
    toc = []
    if has_cover:
        toc.append(('cover.xhtml', 'Cover'))
    if has_front:
        toc.append(('front.xhtml', 'Front Matter'))
    if meta.get('include_toc'):
        toc.append(('toc.xhtml', 'Contents'))
    if meta.get('dedication', '').strip():
        toc.append(('dedication.xhtml', 'Dedication'))
    if meta.get('epigraph', '').strip():
        toc.append(('epigraph.xhtml', 'Epigraph'))
    current_part_num = None
    for idx, ch in enumerate(chapters, start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None
        if ch_part_num is not None and ch_part_num != current_part_num:
            part_label = ch_part.get('title') or pd_fmt.format(n=ch_part_num)
            toc.append((f'part{ch_part_num:03d}.xhtml', part_label))
            current_part_num = ch_part_num
        label = ch.get('title') or (num_fmt.format(n=idx) if show_num else f'Chapter {idx}')
        toc.append((f'chapter{idx:03d}.xhtml', label))

    author = meta.get('author', '')
    _back_nav = [
        ('acknowledgments', 'acknowledgments.xhtml', 'Acknowledgments'),
        ('contributors',    'contributors.xhtml',    'Contributors'),
        ('about_author',    'about.xhtml',           'About the Author'),
        ('also_by',         'alsoby.xhtml',          f'Also by {author}'.strip() or 'Also By'),
    ]
    for _key, _href, _label in _back_nav:
        if meta.get(_key, '').strip():
            toc.append((_href, _label))

    items = '\n'.join(
        f'      <li><a href="{href}">{label}</a></li>' for href, label in toc
    )
    body = (
        '<nav epub:type="toc" id="toc">\n'
        '  <h1>Contents</h1>\n'
        '  <ol>\n'
        + items + '\n'
        '  </ol>\n'
        '</nav>\n'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8"/>\n'
        '  <title>Contents</title>\n'
        '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
        '</head>\n'
        '<body>\n'
        + body +
        '</body>\n</html>\n'
    )


# Interior figures live here; app.py points this at the writable data dir. Kept
# as a module global (like engine.FIGURE_DIR) so this stays import-free of app.
FIGURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures')

_FIG_MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
             '.gif': 'image/gif', '.svg': 'image/svg+xml'}


def _collect_figures(chapters):
    """Find every ~~~ figure src="…" that resolves to a real file.

    Returns {src: {'href', 'path', 'id', 'mime'}} — one entry per distinct src,
    so the same illustration used twice is stored once.
    """
    found = {}
    for ch in chapters:
        for block in ch.get('blocks', []):
            if block[0] != 'doc_block' or len(block) < 3:
                continue
            m = block[2]
            if m.get('_type') != 'figure':
                continue
            src = (m.get('src', '') or '').strip()
            if not src or src in found:
                continue
            path = src if os.path.isabs(src) else os.path.join(FIGURE_DIR, src)
            if not os.path.exists(path):
                continue                          # _figure_html writes a note
            ext = os.path.splitext(path)[1].lower()
            n = len(found) + 1
            found[src] = {'path': path, 'href': f'images/fig{n:03d}{ext}',
                          'id': f'fig{n:03d}',
                          'mime': _FIG_MIME.get(ext, 'image/png')}
    return found


# ---------------------------------------------------------------- public API
def build_epub(manuscript, preset, out_path, meta):
    """Write an EPUB 3 file to out_path. Returns out_path."""
    uid      = 'urn:uuid:' + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    chapters = manuscript['chapters']
    figures  = _collect_figures(chapters)
    fig_href = {src: f['href'] for src, f in figures.items()}

    level = meta.get('front_matter', 'full')
    if level is True:  level = 'full'
    if level is False: level = 'none'

    cover_src   = meta.get('cover_image', '')
    has_cover   = bool(cover_src and os.path.exists(cover_src))
    cover_ext   = os.path.splitext(cover_src)[1].lower() if has_cover else ''
    cover_mime  = 'image/jpeg' if cover_ext in ('.jpg', '.jpeg') else 'image/png'
    cover_img_fn = 'cover' + cover_ext if has_cover else ''
    has_front   = level != 'none'

    manifest_items = [
        {'id': 'nav',   'href': 'nav.xhtml',  'type': 'application/xhtml+xml', 'props': 'nav'},
        {'id': 'style', 'href': 'style.css',   'type': 'text/css'},
    ]
    spine_items = []

    if has_cover:
        manifest_items.append({'id': 'cover-img',  'href': cover_img_fn,
                                'type': cover_mime, 'props': 'cover-image'})
        manifest_items.append({'id': 'cover-page', 'href': 'cover.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('cover-page')

    for f in figures.values():
        manifest_items.append({'id': f['id'], 'href': f['href'], 'type': f['mime']})

    if has_front:
        manifest_items.append({'id': 'front', 'href': 'front.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('front')

    if meta.get('include_toc'):
        manifest_items.append({'id': 'toc-page', 'href': 'toc.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('toc-page')

    _front_extras = [('dedication', 'ded'), ('epigraph', 'epi')]
    for _fkey, _fid in _front_extras:
        if meta.get(_fkey, '').strip():
            manifest_items.append({'id': _fid, 'href': f'{_fkey}.xhtml',
                                    'type': 'application/xhtml+xml'})
            spine_items.append(_fid)

    current_part_num = None
    for idx, ch in enumerate(chapters, start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None
        if ch_part_num is not None and ch_part_num != current_part_num:
            pid = f'pt{ch_part_num:03d}'
            manifest_items.append({'id': pid, 'href': f'part{ch_part_num:03d}.xhtml',
                                    'type': 'application/xhtml+xml'})
            spine_items.append(pid)
            current_part_num = ch_part_num
        manifest_items.append({'id': f'ch{idx:03d}', 'href': f'chapter{idx:03d}.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append(f'ch{idx:03d}')

    _author = meta.get('author', '')
    _back_items = [
        ('acknowledgments', 'ack',   'acknowledgments.xhtml', 'Acknowledgments'),
        ('contributors',    'contrib', 'contributors.xhtml',  'Contributors'),
        ('about_author',    'about', 'about.xhtml',           'About the Author'),
        ('also_by',         'aby',   'alsoby.xhtml',          f'Also by {_author}'.strip() or 'Also By'),
    ]
    for _bkey, _bid, _bhref, _bhead in _back_items:
        if meta.get(_bkey, '').strip():
            manifest_items.append({'id': _bid, 'href': _bhref,
                                    'type': 'application/xhtml+xml'})
            spine_items.append(_bid)

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and stored uncompressed
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/container.xml', _container_xml())
        zf.writestr('OEBPS/content.opf',
                    _content_opf(uid, meta, manifest_items, spine_items, modified))
        zf.writestr('OEBPS/nav.xhtml',
                    _nav_xhtml(chapters, has_cover, has_front, preset, meta=meta))
        zf.writestr('OEBPS/style.css', _style_css())

        if has_cover:
            zf.write(cover_src, f'OEBPS/{cover_img_fn}')
            zf.writestr('OEBPS/cover.xhtml', _cover_xhtml(cover_img_fn))

        for f in figures.values():
            zf.write(f['path'], f'OEBPS/{f["href"]}')

        if has_front:
            zf.writestr('OEBPS/front.xhtml', _front_xhtml(meta))

        if meta.get('include_toc'):
            zf.writestr('OEBPS/toc.xhtml', _toc_page_xhtml(chapters, preset))

        if meta.get('dedication', '').strip():
            zf.writestr('OEBPS/dedication.xhtml',
                        _matter_xhtml(None, meta['dedication'], 'matter-dedication'))
        if meta.get('epigraph', '').strip():
            zf.writestr('OEBPS/epigraph.xhtml',
                        _matter_xhtml(None, meta['epigraph'], 'matter-epigraph'))

        current_part_num = None
        for idx, ch in enumerate(chapters, start=1):
            ch_part     = ch.get('part')
            ch_part_num = ch_part['number'] if ch_part else None
            if ch_part_num is not None and ch_part_num != current_part_num:
                zf.writestr(f'OEBPS/part{ch_part_num:03d}.xhtml',
                            _part_xhtml(ch_part_num, ch_part.get('title') or '', preset))
                current_part_num = ch_part_num
            zf.writestr(f'OEBPS/chapter{idx:03d}.xhtml',
                        _chapter_xhtml(idx, ch, preset, figures=fig_href))

        for _bkey, _bid, _bhref, _bhead in _back_items:
            _btxt = meta.get(_bkey, '').strip()
            if not _btxt:
                continue
            _css = {'also_by': 'matter-alsoby',
                    'contributors': 'matter-contributors'}.get(_bkey, 'matter-body')
            zf.writestr(f'OEBPS/{_bhref}', _matter_xhtml(_bhead, _btxt, _css))

    return out_path
