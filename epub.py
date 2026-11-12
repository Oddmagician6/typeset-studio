"""EPUB 3 builder: manuscript + preset -> .epub file.

Stdlib-only (zipfile, uuid, datetime) — no extra dependencies.
Reuses the same parsed manuscript structure as engine.py.
"""

import html
import os
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone

# Both project imports are stdlib-only modules, so epub.py stays dependency-free:
# `matter` is the shared front/back-matter vocabulary (same order and headings as
# the PDF), and `manuscript` supplies the link-anchor rule so `[see](#slug)`
# resolves to the same chapter in both outputs.
import matter as _matter
import bookindex as _bookindex
import ornaments as _orn
from manuscript import (book_anchors as _ms_book_anchors, LINK_RE as _LINK_RE,
                        chapter_numbers as _ms_numbers,
                        map_block_texts as _ms_map_texts,
                        INDEX_RE as _MS_INDEX_SRC_RE,
                        strip_index as _ms_strip_index,
                        book_targets as _ms_targets,
                        ANCHOR_RE as _MS_ANCHOR_SRC_RE,
                        PAGE_RE as _MS_PAGE_SRC_RE,
                        ANCHOR_TAG_RE as _MS_ANCHOR_TAG_RE,
                        PAGEREF_TAG_RE as _MS_PAGEREF_TAG_RE,
                        CELL_SEP as _MS_CELL)

_NOTE_MARK_RE = re.compile(r'<note n="(\d+)" id="[\w\-]+"/>')

# matter.SECTIONS' `style` -> the CSS class the page body carries
_MATTER_CSS = {'dedication': 'matter-dedication', 'epigraph': 'matter-epigraph',
               'also_by': 'matter-alsoby', 'contributors': 'matter-contributors',
               'body': 'matter-body'}


def _apply_note_markers(chapters):
    """Neutral `<note …/>` -> a superscript that links to the Notes page.

    The reference also carries an id, so the note can link *back* to the exact
    sentence it belongs to — the thing an ebook can do that a printed page can't.
    """
    index = {id(ch): i for i, ch in enumerate(chapters, start=1)}
    seen = set()          # a label may be cited twice; ids must stay unique

    def render(text, ch):
        i = index[id(ch)]

        def one(m):
            n = m.group(1)
            key = (i, n)
            anchor = '' if key in seen else f' id="noteref-{i}-{n}"'
            seen.add(key)
            return (f'<sup class="noteref"{anchor}>'
                    f'<a href="endnotes.xhtml#note-{i}-{n}">{n}</a></sup>')

        return _NOTE_MARK_RE.sub(one, text)

    return _ms_map_texts(chapters, render)


def _endnotes_xhtml(chapters, preset):
    """The Notes page: entries grouped by chapter, each linking back."""
    em = preset.get('endnotes', {})
    heading = em.get('heading', 'Notes')
    body = ['<div class="matter-body endnotes">',
            f'  <h1 class="matter-head">{html.escape(heading)}</h1>']
    # Only a note the body cites has a reference to link back to. One cited only
    # from inside another note, or never cited, gets a plain number: a back-link
    # to an id that isn't there is a broken link the EPUB check reports.
    cited = set()

    def collect(text, ch):
        cited.update(re.findall(r'id="noteref-(\d+-\d+)"', text))
        return text
    _ms_map_texts(chapters, collect)

    for i, ch in enumerate(chapters, start=1):
        notes = ch.get('notes') or []
        if not notes:
            continue
        if em.get('group_by_chapter', True):
            label = ch.get('title') or f'Chapter {i}'
            body.append(f'  <h2 class="note-group">{_text_to_html(label)}</h2>')
        for note in notes:
            # a note citing a note links to that entry, here on the same page
            text = _NOTE_MARK_RE.sub(
                lambda m: f'<sup class="noteref"><a href="#note-{i}-{m.group(1)}">'
                          f'{m.group(1)}</a></sup>',
                _markup_to_html(note['text'])) if note['text'] \
                else '<em>[no note text]</em>'
            num = (f'<a class="note-back" href="chapter{i:03d}.xhtml#noteref-{i}-{note["n"]}">'
                   f'{note["n"]}.</a>' if f'{i}-{note["n"]}' in cited
                   else f'<span class="note-back">{note["n"]}.</span>')
            body.append(f'  <p class="note" id="note-{i}-{note["n"]}">{num} {text}</p>')
    body.append('</div>')
    return _xhtml(heading, '\n'.join(body))


def _index_id(key):
    return f'ix-{key}'


def _apply_index_markers(chapters, meta):
    """Every index marker as an empty anchor the Index page links to:
    (chapters, marks). See `bookindex.assign`."""
    return _bookindex.assign(
        chapters, meta, lambda key: f'<span class="ix" id="{_index_id(key)}"></span>')


def _index_xhtml(chapters, marks, meta, preset):
    """The Index page. An ebook has no page numbers, so each entry links to
    the chapters it is marked in, by name, and to the first marker in each."""
    c = preset.get('chapter', {})
    num_fmt = c.get('number_format', 'Chapter {n}')
    nums = _ms_numbers(chapters)

    def label(n):
        ch = chapters[n - 1]
        return ch.get('title') or (num_fmt.format(n=nums[n - 1])
                                   if nums[n - 1] else f'Section {n}')

    def links(hits):
        first = {}
        for where, key in sorted(hits):
            first.setdefault(where, key)
        return ', '.join(
            f'<a href="chapter{n:03d}.xhtml#{_index_id(key)}">{_text_to_html(label(n))}</a>'
            for n, key in sorted(first.items()))

    def line(text, hits, cls):
        found = links(hits)
        return (f'  <p class="{cls}">{_text_to_html(text)}'
                + (f': {found}' if found else '') + '</p>')

    entries, challenges = _bookindex.tree(
        marks, [(key, m['chapter']) for key, m in enumerate(marks)], meta)
    body = ['<div class="matter-body book-index">',
            f'  <h1 class="matter-head">{_text_to_html(_bookindex.HEADING)}</h1>']
    at = None
    for main, hits, subs in entries:
        head = _bookindex.letter(main)
        if head != at:
            at = head
            if head:
                body.append(f'  <h2 class="ix-letter">{_text_to_html(head)}</h2>')
        body.append(line(main, hits, 'ix-entry'))
        body.extend(line(text, sub_hits, 'ix-sub') for text, sub_hits in subs)
    if challenges:
        body.append(f'  <h2 class="ix-part">{_text_to_html(_bookindex.CR_HEADING)}</h2>')
        for cr, names in challenges:
            body.append(f'  <h2 class="ix-letter">CR {_text_to_html(cr)}</h2>')
            body.extend(line(name, hits, 'ix-entry') for name, hits in names)
    body.append('</div>')
    return _xhtml(_bookindex.HEADING, '\n'.join(body))


def _target_id(name):
    """A heading's or a `{#name}`'s id in its chapter's file: prefixed, so a
    writer's name can never be one of the ids the ebook makes itself."""
    return f'at-{name}'


def _apply_page_refs(chapters, meta, preset):
    """Link targets and page references in an ebook (#74 Phase 5b), which has
    no page numbers: `(chapters, hrefs)`.

    Each heading and each `{#name}` becomes an empty `<span>` with an id, and
    `hrefs[name]` is where it is (`chapter002.xhtml#at-name`; a chapter's own
    names are its file). A `{page: name}` becomes a link reading the target's
    name: a chapter's title, a heading's words, or for a `{#name}` the heading
    above it. A page reference that names nothing prints "??", as in print.
    """
    targets = _ms_targets(chapters)
    num_fmt = (preset.get('chapter') or {}).get('number_format', 'Chapter {n}')
    nums = _ms_numbers(chapters)
    hrefs, labels = {}, {}
    for n, names in enumerate(targets['chapters'], 1):
        ch = chapters[n - 1]
        label = ch.get('title') or (num_fmt.format(n=nums[n - 1])
                                    if nums[n - 1] else f'Section {n}')
        for name in names:
            hrefs[name], labels[name] = f'chapter{n:03d}.xhtml', label
    own = set(targets['own'])
    out = []
    for n, ch in enumerate(chapters, 1):
        file = f'chapter{n:03d}.xhtml'
        label = labels[targets['chapters'][n - 1][0]]
        heads = targets['headings'][n - 1]
        blocks = list(ch.get('blocks', []))
        for i, block in enumerate(blocks):
            if i in heads:
                name = heads[i]
                label = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', block[1])).split())
                hrefs[name], labels[name] = f'{file}#{_target_id(name)}', label
                blocks[i] = (block[0], f'<anchor name="{name}"/>' + block[1]) + tuple(block[2:])
                own_here = blocks[i]
            else:
                own_here = block

            def collect(text, _ch, label=label):
                for m in _MS_ANCHOR_TAG_RE.finditer(text):
                    if m.group(1) in own and m.group(1) not in hrefs:
                        hrefs[m.group(1)] = f'{file}#{_target_id(m.group(1))}'
                        labels[m.group(1)] = label
                return text
            _ms_map_texts([{'blocks': [own_here]}], collect)
        out.append(dict(ch, blocks=blocks))

    planted = set()

    def render(text, _ch):
        def plant(m):
            name = m.group(1)
            if name in hrefs and '#' in hrefs[name] and name not in planted:
                planted.add(name)
                return f'<span id="{_target_id(name)}"></span>'
            return ''

        def ref(m):
            name = m.group(1)
            if name not in labels:
                return '??'
            return f'<a href="#{name}">{html.escape(labels[name], quote=False)}</a>'
        if '<anchor ' in text:
            text = _MS_ANCHOR_TAG_RE.sub(plant, text)
        if '<pageref ' in text:
            text = _MS_PAGEREF_TAG_RE.sub(ref, text)
        return text
    return _ms_map_texts(out, render), hrefs


# In-book links (`[see](#the-salt-road)`) carry a bare fragment, which in a
# multi-file EPUB has to become "that chapter's file". Filled per build, and
# per thread: two books exported at once on the threaded server each need their own.
_BUILD = threading.local()

_HREF_RE = re.compile(r'(<a\s[^>]*href=")#([^"]+)(")')


def _resolve_anchors(text):
    """Point `href="#anchor"` at the chapter file that anchor lives in."""
    anchors = getattr(_BUILD, 'anchors', None)
    if not anchors:
        return text
    def sub(m):
        target = anchors.get(m.group(2))
        return m.group(1) + (target or ('#' + m.group(2))) + m.group(3)
    return _HREF_RE.sub(sub, text)


# ---------------------------------------------------------------- markup
def _markup_to_html(text):
    """Convert ReportLab XML tags to HTML equivalents.

    `<a href="…">` is already valid XHTML and passes straight through, except
    that in-book `#anchor` targets are rewritten to the file that holds them.
    """
    text = text.replace('<b>', '<strong>').replace('</b>', '</strong>')
    text = text.replace('<i>', '<em>').replace('</i>', '</em>')
    # an index marker still neutral here sits where the index can't point (a
    # note's text): it is dropped, as the PDF drops it
    return _resolve_anchors(_ms_strip_index(text))


def _text_to_html(text):
    """Escape a raw plain-text string for XHTML: a title, a byline, a heading.

    Block text reaches this module already escaped, because it came through
    `manuscript._inline`. Titles do not: a chapter or part title, the book's own
    title, subtitle and author, the matter-page headings and the number formats
    out of the preset are all carried as plain text and emitted directly. So a
    bare `&` in "Salt & Ash" — an ordinary title, and an ordinary co-author line —
    made every page carrying it malformed, which the validator rejects and a
    strict reader refuses to open. The PDF was unaffected; only the ebook.

    Not to be confused with `_markup_to_html`, which takes text that is already
    escaped and only renames its tags.
    """
    return html.escape(text or '', quote=False)


_EMPH_TAG_RE = re.compile(r'</?(?:strong|em)>')


def _sub_between_emph(pattern, repl, text):
    """Apply an emphasis substitution to the stretches between the tags emitted so far.

    Mirrors manuscript._sub_between_tags: an unpaired marker earlier in the line
    would otherwise pair with one inside a span already emitted, producing tags
    that cross — which is not well-formed XHTML.
    """
    out, pos = [], 0
    for m in _EMPH_TAG_RE.finditer(text):
        out.append(re.sub(pattern, repl, text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(re.sub(pattern, repl, text[pos:]))
    return ''.join(out)


def _md_emph_to_html(text):
    """Escape XML, then convert Markdown links and emphasis to HTML.

    Mirrors manuscript._inline (links carved out first, then bold-italic, bold,
    italic) for the places that render **raw author text** — the matter pages and
    the contributors list — rather than already-parsed manuscript blocks. The PDF
    runs the same text through `_ms_inline`, so without this the ebook showed
    literal asterisks and dropped every link on the Also By page.
    """
    # an index marker on a matter page has nowhere to point: it prints nothing,
    # and so do an anchor and a page reference there
    for rx in (_MS_INDEX_SRC_RE, _MS_ANCHOR_SRC_RE, _MS_PAGE_SRC_RE):
        text = re.sub(r'(?<!\\)' + rx.pattern, '', text)
    text = html.escape(text, quote=False)

    targets = []

    def _stash(m):
        targets.append(m.group(2))
        return f'\x00{len(targets) - 1}\x00{m.group(1)}\x01'

    text = _LINK_RE.sub(_stash, text)
    # Bold-italic first, and as one span — the same reason manuscript._inline
    # does. Left to the ** and * passes below, ***x*** comes out cross-nested
    # (<strong><em>x</strong></em>): not well-formed XHTML, so the page fails
    # epubcheck and strict readers refuse it. ___x___ needs the same pass or its
    # underscores survive into the text as literals.
    text = re.sub(r'\*\*\*(?!\s)(.+?)(?<!\s)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'___(?!\s)(.+?)(?<!\s)___', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = _sub_between_emph(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<em>\1</em>', text)
    text = _sub_between_emph(r'_(?!\s)(.+?)(?<!\s)_', r'<em>\1</em>', text)
    if targets:
        text = re.sub(
            r'\x00(\d+)\x00(.*?)\x01',
            lambda m: '<a href="%s">%s</a>'
                      % (html.escape(targets[int(m.group(1))], quote=True), m.group(2)),
            text, flags=re.S)
    return _resolve_anchors(text)


# ---------------------------------------------------------------- CSS
def _style_css(preset=None):
    lm = (preset or {}).get('link', {})
    colour = (lm.get('color') or '').strip()
    rules = ['a { color: %s; }' % (colour or 'inherit'),
             'a { text-decoration: %s; }'
             % ('underline' if lm.get('epub_underline', True) else 'none')]
    hd = (preset or {}).get('headings', {}) or {}
    _weight = {'bold': 'font-weight: bold; font-style: normal;',
               'italic': 'font-weight: normal; font-style: italic;',
               'regular': 'font-weight: normal; font-style: normal;'}
    for tag, key, dflt in (('h3', 'section', 'bold'), ('h4', 'subsection', 'italic')):
        align = 'center' if hd.get(key + '_align') == 'center' else 'left'
        rules.append('%s { font-size: 1em; text-align: %s; %s margin: 1.2em 0 0.4em; }'
                     % (tag, align, _weight.get(hd.get(key + '_style'), _weight[dflt])))
    return '\n'.join(rules) + '\n' + """\
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
p.chapter-tagline {
  font-style: italic;
  text-align: center;
  text-indent: 0;
  color: #444;
  margin: -1em 0 1.6em;
}
p.chapter-byline + p.chapter-tagline { margin-top: -1.2em; }
p.chapter-art { text-align: center; text-indent: 0; margin: 0 0 1em; }
p.chapter-art-below { margin: 1em 0 1.6em; }
p.chapter-art img { max-width: 100%; height: auto; }
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
/* a bundled vector ornament: the SVG carries its own aspect, so only the
   width is set here and the height follows on any screen size */
p.scene-break img.scene-orn { display: inline-block; height: auto; }
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
table.block-table { border-collapse: collapse; width: 100%; margin: 1.2em auto; font-size: 0.92em; }
table.block-table caption { font-style: italic; font-size: 0.9em; color: #555; text-align: center; margin-bottom: 0.4em; caption-side: top; }
table.block-table th, table.block-table td { padding: 0.3em 0.5em; text-align: left; vertical-align: top; text-indent: 0; }
table.block-table th { font-weight: bold; }
table.block-table.head-italic th { font-weight: normal; font-style: italic; }
table.block-table.head-regular th { font-weight: normal; }
table.block-table.head-smallcaps th { font-weight: normal; font-variant: small-caps; }
table.block-table.rules-all th, table.block-table.rules-all td { border: 1px solid #444; }
table.block-table.rules-horizontal tr { border-bottom: 1px solid #444; }
table.block-table.rules-horizontal { border-top: 1px solid #444; }
table.block-table.rules-header { border-top: 1.5px solid #222; border-bottom: 1.5px solid #222; }
table.block-table.rules-header thead tr { border-bottom: 1px solid #444; }
/* game blocks (#74): read-aloud box, sidebar (and its note form), stat block */
.readaloud { margin: 1.2em 0; padding: 0.5em 0.8em; background: #eeeeee; border-left: 3px solid #555555; font-style: italic; }
.readaloud p { text-indent: 0; margin: 0.35em 0; }
.readaloud p.block-title { font-style: normal; font-weight: bold; font-variant: small-caps; }
.sidebar { margin: 1.2em 0; border: 1px solid #000; background: #f0f0f0; }
.sidebar p { text-indent: 0; margin: 0.35em 0.8em; }
.sidebar p.block-title { margin: 0; padding: 0.3em 0.8em; font-weight: bold; text-transform: uppercase; letter-spacing: 0.03em; border-bottom: 1px solid #000; }
.sidebar-note { margin: 1.2em 0; border-left: 1px solid #000; padding-left: 0.8em; }
.sidebar-note p { text-indent: 0; margin: 0.3em 0; }
.sidebar-note p.block-title { font-weight: bold; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 0.1em; }
section.statblock { margin: 1.4em 0; padding: 0.4em 0.6em; border-top: 2px solid #000; border-bottom: 2px solid #000; font-size: 0.95em; }
section.statblock p { text-indent: 0; margin: 0.25em 0; }
section.statblock .sb-name { font-weight: bold; font-size: 1.25em; text-transform: uppercase; margin: 0; }
section.statblock .sb-cr { float: right; font-weight: bold; font-size: 0.85em; }
section.statblock .sb-meta { font-style: italic; margin: 0 0 0.3em; }
section.statblock hr { border: 0; border-top: 1px solid #000; margin: 0.4em 0; }
section.statblock dl { margin: 0.2em 0; }
section.statblock dt { display: inline; font-weight: bold; }
section.statblock dd { display: inline; margin: 0; }
section.statblock dd:after { content: ""; display: block; }
section.statblock table.sb-scores { width: 100%; border-collapse: collapse; text-align: center; margin: 0.3em 0; }
section.statblock table.sb-scores th, section.statblock table.sb-scores td { padding: 0.1em 0.2em; text-align: center; text-indent: 0; }
section.statblock h3 { font-size: 1.05em; font-variant: small-caps; font-weight: bold; text-align: left; border-bottom: 1px solid #000; margin: 0.7em 0 0.3em; }
section.statblock .sb-entry-name { font-weight: bold; font-style: italic; }
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
sup.noteref { font-size: 0.7em; line-height: 0; vertical-align: super; }
sup.noteref a { text-decoration: none; }
.endnotes h2.note-group { font-size: 1em; font-weight: bold; text-align: left; margin: 1.4em 0 0.5em; }
.endnotes p.note { text-indent: -1.2em; padding-left: 1.2em; margin: 0 0 0.4em; font-size: 0.9em; }
.endnotes .note-back { text-decoration: none; font-weight: bold; }
.book-index h2.ix-letter { font-size: 1em; font-weight: bold; text-align: left; margin: 1.1em 0 0.3em; }
.book-index h2.ix-part { font-size: 1.15em; font-weight: bold; text-align: center; margin: 2em 0 0.6em; }
.book-index p.ix-entry { text-indent: -1.2em; padding-left: 1.2em; margin: 0 0 0.15em; text-align: left; }
.book-index p.ix-sub { text-indent: -1.2em; padding-left: 2.4em; margin: 0 0 0.15em; text-align: left; }
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
.toc-list li.toc-sec { border-bottom: none; padding: 0.1em 0; font-size: 0.95em; }
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
        f'  <title>{_text_to_html(title)}</title>\n'
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


_HEAD_LEVEL = {'subhead': 2, 'section': 3, 'subsection': 4}


def _toc_depth(preset):
    """How deep the contents go (the style's `toc.depth`): 1 = chapters."""
    try:
        return int((preset.get('toc') or {}).get('depth', 1) or 1)
    except (TypeError, ValueError):
        return 1


def chapter_headings(chapter):
    """[(id, level, plain text)] for the headings inside a chapter, in order.
    `_chapter_xhtml` gives each heading the same id, so the contents can link
    to it."""
    out = []
    for block in chapter.get('blocks', []):
        level = _HEAD_LEVEL.get(block[0])
        if level:
            text = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', block[1])).split())
            out.append((f'h{len(out) + 1}', level, text))
    return out


def _toc_page_xhtml(chapters, preset):
    """In-text TOC page for EPUB — chapter links, no page numbers."""
    c        = preset.get('chapter', {})
    show_num = c.get('show_number', True)
    num_fmt  = c.get('number_format', 'Chapter {n}')
    pd       = preset.get('part_divider', {})
    pd_fmt   = pd.get('number_format', 'Part {n}')

    body = '<div class="matter-body">\n  <h1 class="matter-head">Contents</h1>\n  <ul class="toc-list">\n'
    depth = _toc_depth(preset)
    _nums = _ms_numbers(chapters)
    current_part_num = None
    for idx, ch in enumerate(chapters, start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None
        if ch_part_num is not None and ch_part_num != current_part_num:
            part_label = ch_part.get('title') or pd_fmt.format(n=ch_part_num)
            body += ('    <li class="toc-part">'
                     f'<a href="part{ch_part_num:03d}.xhtml">'
                     f'{_text_to_html(part_label)}</a></li>\n')
            current_part_num = ch_part_num
        label = ch.get('title') or (num_fmt.format(n=_nums[idx - 1])
                                   if show_num and _nums[idx - 1] else f'Section {idx}')
        indent = ' class="toc-indent"' if ch_part_num is not None else ''
        body += (f'    <li{indent}><a href="chapter{idx:03d}.xhtml">'
                 f'{_text_to_html(label)}</a></li>\n')
        for hid, level, text in chapter_headings(ch):
            if level > depth:
                continue
            pad = 1.5 * (level - 1) + (1.5 if ch_part_num is not None else 0)
            body += (f'    <li class="toc-sec" style="padding-left: {pad:g}em">'
                     f'<a href="chapter{idx:03d}.xhtml#{hid}">'
                     f'{_text_to_html(text)}</a></li>\n')
    body += '  </ul>\n</div>\n'
    return _xhtml('Contents', body)


def _part_xhtml(part_num, title, preset):
    pd       = preset.get('part_divider', {})
    show_num = pd.get('show_number', True)
    num_fmt  = pd.get('number_format', 'Part {n}')
    body = '<div class="part-page">\n'
    if show_num:
        body += ('  <p class="part-num">'
                 f'{_text_to_html(num_fmt.format(n=part_num))}</p>\n')
    if title:
        body += f'  <h1 class="part-title">{_text_to_html(title)}</h1>\n'
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
    # escaped before the breaks go in, or the <br/> would be escaped too
    cp_html  = _text_to_html(cp_text).replace('\n', '<br/>')

    body = '<div class="front">\n'

    if level == 'full':
        body += f'  <h1 class="main">{_text_to_html(title)}</h1>\n'
        body += '  <hr style="margin: 2em auto; width: 30%"/>\n'

    if level in ('full', 'title'):
        body += f'  <h1 class="main">{_text_to_html(title)}</h1>\n'
        if subtitle:
            body += f'  <p class="subtitle">{_text_to_html(subtitle)}</p>\n'
        body += f'  <p class="author">{_text_to_html(author)}</p>\n'

    body += '</div>\n'

    if level in ('full', 'title', 'copyright'):
        body += f'<div class="copyright"><p>{cp_html}</p></div>\n'

    return _xhtml(title or 'Front Matter', body)


def _matter_xhtml(heading, text, css_class):
    """XHTML page for a front/back matter section."""
    blocks = [b.strip() for b in text.replace('\r\n', '\n').split('\n\n') if b.strip()]
    body   = f'<div class="{css_class}">\n'
    if heading:
        body += f'  <h1 class="matter-head">{_text_to_html(heading)}</h1>\n'
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
        body += f'  <p{cls}>{_md_emph_to_html(b)}</p>\n'
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


_TABLE_RULES = ('all', 'horizontal', 'header', 'none')


def _table_html(rows_paras, attrs, tm=None):
    """A `~~~ table` block as a real `<table>`.

    Cells were split at parse time and rejoined with `manuscript.CELL_SEP`, so
    the emphasis inside a cell is already markup and only needs converting.
    Short rows are padded, matching the PDF — the two outputs must agree on the
    shape of the grid. The style's rule and header choices ride on class names
    rather than being written into the stylesheet, so the CSS stays static.
    """
    tm = tm or {}
    rows = [text.split(_MS_CELL) for _, text in rows_paras if text is not None]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    cols = max(len(r) for r in rows)
    rows = [r + [''] * (cols - len(r)) for r in rows]

    header = str(attrs.get('header', 'yes')).strip().lower() not in ('no', 'false', '0')
    header = header and len(rows) > 1
    aligns = [a.strip().lower() for a in (attrs.get('align', '') or '').split(',') if a.strip()]
    aligns = ((aligns + [aligns[-1]] * cols)[:cols] if aligns else ['left'] * cols)

    def cell(tag, text, col):
        style = (f' style="text-align:{aligns[col]}"'
                 if aligns[col] in ('right', 'center') else '')
        return f'      <{tag}{style}>{_markup_to_html(text)}</{tag}>'

    rules = tm.get('rules', 'header')
    if rules not in _TABLE_RULES:
        rules = 'header'
    head_cls = tm.get('header_style', 'bold')
    width = max(0.2, min(1.0, tm.get('width', 1.0)))
    wstyle = f' style="width:{width * 100:.0f}%"' if width < 1.0 else ''
    out = [f'  <table class="block-table rules-{rules} head-{head_cls}"{wstyle}>']
    caption = (attrs.get('caption', '') or '').strip()
    if caption:
        out.append(f'    <caption>{_md_emph_to_html(caption)}</caption>')
    body = rows
    if header:
        out.append('    <thead>')
        out.append('    <tr>')
        out += [cell('th', t, c) for c, t in enumerate(rows[0])]
        out.append('    </tr>')
        out.append('    </thead>')
        body = rows[1:]
    out.append('    <tbody>')
    for row in body:
        out.append('    <tr>')
        out += [cell('td', t, c) for c, t in enumerate(row)]
        out.append('    </tr>')
    out.append('    </tbody>')
    out.append('  </table>')
    return out


SCENE_ORN_HREF = 'images/scene-break.svg'


def scene_ornament(preset):
    """The bundled ornament this style marks scene breaks with, or ''.

    Returns '' for the glyph and image types, and for an id no longer in the
    library — a style that names a retired ornament falls back to its glyph
    rather than failing the build.
    """
    sb = preset.get('scene_break', {})
    if sb.get('type') != 'ornament':
        return ''
    oid = (sb.get('ornament') or '').strip()
    return oid if _orn.get(oid) else ''


def _scene_orn_html(preset, oid):
    """The scene break as an `<img>` at the ornament's own width.

    An `<img>` pointing at an SVG file (rather than SVG inlined in the page)
    keeps the content documents plain XHTML — no `properties="svg"` on the
    manifest item — and one file serves every break in the book.
    """
    sb   = preset.get('scene_break', {})
    frac = sb.get('ornament_width', 0.0) or _orn.get(oid)['width']
    pct  = max(0.02, min(float(frac), 1.0)) * 100.0
    return (f'  <p class="scene-break"><img class="scene-orn" '
            f'src="{SCENE_ORN_HREF}" alt="Scene break" '
            f'style="width:{pct:.1f}%"/></p>')


def chapter_art_src(preset):
    """The image a style prints on every chapter opener, or ''.

    Read locally rather than imported from `engine` — this module stays
    stdlib-only and engine-free (see the note on the imports above); the same
    two lines live in `engine.chapter_art_src` / `chapter_art_position`.
    """
    return (preset.get('chapter_art', {}).get('image', '') or '').strip()


def chapter_art_position(preset):
    """'above' (over the chapter number) or 'below' (under the title)."""
    pos = (preset.get('chapter_art', {}).get('position', 'above') or 'above').lower()
    return 'below' if pos == 'below' else 'above'


def _chapter_art_html(preset, href, position):
    """The chapter-opening illustration as a paragraph-wrapped `<img>`.

    Decorative by definition — the same mark opens every chapter — so it takes
    an empty `alt` and `role="presentation"`, which is what a screen reader
    wants: silence, not "chapter ornament" forty times over. Width is a
    percentage of the text so it reflows with the reader's page.
    """
    ca   = preset.get('chapter_art', {})
    frac = max(0.05, min(float(ca.get('width', 0.32) or 0.32), 1.0))
    cls  = 'chapter-art' + (' chapter-art-below' if position == 'below' else '')
    return (f'  <p class="{cls}"><img src="{html.escape(href)}" alt="" '
            f'role="presentation" style="width:{frac * 100:.1f}%"/></p>')


def _chapter_xhtml(idx, chapter, preset, figures=None, number=None, art_href=''):
    c          = preset.get('chapter', {})
    show_num   = c.get('show_number', True)
    num_fmt    = c.get('number_format', 'Chapter {n}')
    scene_glyph = preset.get('scene_break', {}).get('glyph', '* * *')
    scene_orn   = scene_ornament(preset)
    art_pos     = chapter_art_position(preset)

    lines = ['<div class="chapter">']

    if art_href and art_pos == 'above':
        lines.append(_chapter_art_html(preset, art_href, 'above'))

    if show_num and number is not None:
        lines.append('  <h1 class="chapter-num">'
                     f'{_text_to_html(num_fmt.format(n=number))}</h1>')

    if chapter.get('title'):
        lines.append('  <h1 class="chapter-title">'
                     f'{_text_to_html(chapter["title"])}</h1>')

    if chapter.get('byline'):
        lines.append('  <p class="chapter-byline">'
                     f'{_text_to_html(chapter["byline"])}</p>')

    if chapter.get('tagline'):
        lines.append('  <p class="chapter-tagline">'
                     f'{_text_to_html(chapter["tagline"])}</p>')

    if art_href and art_pos == 'below':
        lines.append(_chapter_art_html(preset, art_href, 'below'))

    opened         = False
    no_indent_next = False
    n_head         = 0              # heading ids: see chapter_headings

    for block in chapter.get('blocks', []):
        kind = block[0]
        val  = block[1]
        if kind == 'scene':
            lines.append(_scene_orn_html(preset, scene_orn) if scene_orn else
                         f'  <p class="scene-break">{_text_to_html(scene_glyph)}</p>')
            no_indent_next = True
        elif kind in _HEAD_LEVEL:
            n_head += 1
            tag = f'h{_HEAD_LEVEL[kind]}'
            lines.append(f'  <{tag} id="h{n_head}">{_markup_to_html(val)}</{tag}>')
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
            if btype == 'table':
                lines.extend(_table_html(val, attrs, preset.get('table', {})))
                no_indent_next = True
                continue
            if btype in ('readaloud', 'sidebar', 'statblock'):
                lines.extend(_game_block_html(btype, val, attrs))
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
                # attribute values are plain text, escaped: `from="A & B"`
                # made the whole chapter file malformed
                a = {k: _text_to_html(v) for k, v in attrs.items()}
                if a.get('from') and a.get('to'):
                    parts.append(f'{a["from"]} to {a["to"]}')
                elif a.get('from'):
                    parts.append(a['from'])
                elif a.get('to'):
                    parts.append(f'To: {a["to"]}')
                if a.get('date'):
                    parts.append(a['date'])
                if parts:
                    lines.append(f'    <header>{" · ".join(parts)}</header>')
            elif btype == 'journal':
                parts = [_text_to_html(p) for p in (attrs.get('date', ''), attrs.get('author', ''))
                         if p]
                if parts:
                    lines.append(f'    <header>{" · ".join(parts)}</header>')
            elif btype == 'telegram':
                lines.append('    <header>TELEGRAM</header>')
                if attrs.get('to'):
                    lines.append(f'    <p class="no-indent">To: {_text_to_html(attrs["to"].upper())}</p>')
            elif btype == 'newspaper':
                hl = _text_to_html(attrs.get('headline', '').upper())
                src = _text_to_html(attrs.get('source', ''))
                date = _text_to_html(attrs.get('date', ''))
                byline_parts = [p for p in (src, date) if p]
                hdr = (f'<span class="headline">{hl}</span>' if hl else '') + \
                      (f'<span class="byline">{" · ".join(byline_parts)}</span>' if byline_parts else '')
                if hdr:
                    lines.append(f'    <header>{hdr}</header>')
            elif btype == 'redacted':
                classification = attrs.get('classification', '')
                if classification:
                    lines.append(f'    <header>{_text_to_html(classification.upper())}</header>')
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
    ch_title = chapter.get('title') or (num_fmt.format(n=number)
                                        if show_num and number else f'Section {idx}')
    return _xhtml(ch_title, '\n'.join(lines))


def _game_block_html(btype, paras, attrs):
    """XHTML for the game blocks (#74). A stat block is a <section> with a
    definition list for its fields and a <table> for its scores, read from the
    model statblock.py made of it; attribute values are plain text, escaped."""
    out = []
    if btype in ('readaloud', 'sidebar'):
        note = btype == 'sidebar' and (attrs.get('style', '') or '').strip().lower() == 'note'
        cls = 'sidebar-note' if note else btype
        title = (attrs.get('title', '') or '').strip()
        out.append(f'  <aside class="{cls}">' if btype == 'sidebar'
                   else f'  <div class="{cls}">')
        if title:
            out.append(f'    <p class="block-title">{_text_to_html(title)}</p>')
        for _, text in paras:
            out.append(f'    <p>{_markup_to_html(text)}</p>')
        out.append('  </aside>' if btype == 'sidebar' else '  </div>')
        return out

    m = attrs.get('_statblock') or {}
    out.append('  <section class="statblock">')
    name, cr = m.get('name', ''), (attrs.get('cr', '') or '').strip()
    count = (attrs.get('count', '') or '').strip()
    if name or cr or count:
        head = _markup_to_html(name)
        if count:
            head += f' × {_text_to_html(count)}'
        if cr:
            head = f'<span class="sb-cr">CR {_text_to_html(cr)}</span>' + head
        anchor = (f' id="{_index_id(attrs["_ix"])}"'
                  if attrs.get('_ix') is not None else '')     # it is in the index
        out.append(f'    <p class="sb-name"{anchor}>{head}</p>')
    if m.get('meta'):
        out.append(f'    <p class="sb-meta">{_markup_to_html(m["meta"])}</p>')
    fields, scores = m.get('fields', []), m.get('scores', [])
    at = min(m.get('scores_at', 0), len(fields)) if scores else len(fields)

    def dl(fs):
        if not fs:
            return []
        rows = ['    <dl>']
        for f in fs:
            rows.append(f'      <dt>{_markup_to_html(f["label"])}</dt>'
                        f' <dd>{_markup_to_html(f["value"])}</dd>')
        rows.append('    </dl>')
        return rows

    if fields or scores:
        out.append('    <hr/>')
    out += dl(fields[:at])
    if scores:
        saves = any(c.get('save') for c in scores)
        out.append('    <table class="sb-scores">')
        if saves:
            out.append('      <tr><th></th><th></th><th>Mod</th><th>Save</th></tr>')
            for c in scores:
                out.append(f'      <tr><th>{c["name"]}</th><td>{c["score"]}</td>'
                           f'<td>{c.get("mod", "")}</td><td>{c.get("save", "")}</td></tr>')
        else:
            out.append('      <tr>' + ''.join(f'<th>{c["name"]}</th>' for c in scores)
                       + '</tr>')
            out.append('      <tr>' + ''.join(
                f'<td>{c["score"]} ({c["mod"]})</td>' if c.get('mod')
                else f'<td>{c["score"]}</td>' for c in scores) + '</tr>')
        out.append('    </table>')
        out += dl(fields[at:])
    for k, sec in enumerate(m.get('sections', [])):
        if sec['name']:
            out.append(f'    <h3>{_markup_to_html(sec["name"])}</h3>')
        elif k or fields or scores:
            out.append('    <hr/>')
        for e in sec['entries']:
            lead = (f'<span class="sb-entry-name">{_markup_to_html(e["name"])}</span> '
                    if e['name'] else '')
            out.append(f'    <p>{lead}{_markup_to_html(e["text"])}</p>')
    out.append('  </section>')
    return out


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


def check(path):
    """Inspect a built .epub and report what a reader or a shop would object to.

    Deliberately checks the *file we just wrote* rather than the data we wrote it
    from: the point is to catch a builder mistake, and a self-check that trusts
    the builder's own view of the world can't. Stdlib-only, like the rest of this
    module — `epubcheck` proper is Java, and is folded in separately when present.

    Returns [{label, ok, detail}] in the same shape as app._preflight's checks.
    """
    from xml.dom import minidom
    import posixpath

    out = []

    def add(label, ok, detail):
        out.append({'label': label, 'ok': bool(ok), 'detail': detail})

    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        return [{'label': 'EPUB file', 'ok': False, 'detail': f'Could not open: {exc}'}]

    with zf:
        names = zf.namelist()
        infos = {i.filename: i for i in zf.infolist()}

        # --- the container rules readers actually enforce ---
        first_ok = bool(names) and names[0] == 'mimetype'
        stored_ok = ('mimetype' in infos
                     and infos['mimetype'].compress_type == zipfile.ZIP_STORED)
        add('Container', first_ok and stored_ok,
            'mimetype is first and uncompressed' if first_ok and stored_ok else
            'mimetype must be the first entry and stored uncompressed')

        try:
            container = minidom.parseString(zf.read('META-INF/container.xml'))
            opf_path = container.getElementsByTagName('rootfile')[0] \
                                .getAttribute('full-path')
        except Exception as exc:
            add('Package document', False, f'container.xml unreadable: {exc}')
            return out
        if opf_path not in names:
            add('Package document', False, f'container.xml points at {opf_path}, which is missing')
            return out

        base = posixpath.dirname(opf_path)
        opf_raw = zf.read(opf_path)
        try:
            opf = minidom.parseString(opf_raw)
        except Exception as exc:
            add('Package document', False, f'{opf_path} is not well-formed: {exc}')
            return out

        items = {}
        for el in opf.getElementsByTagName('item'):
            items[el.getAttribute('id')] = {
                'href': el.getAttribute('href'),
                'type': el.getAttribute('media-type'),
                'props': el.getAttribute('properties') or '',
            }
        spine = [el.getAttribute('idref')
                 for el in opf.getElementsByTagName('itemref')]

        def full(href):
            return posixpath.normpath(posixpath.join(base, href)) if base else href

        # --- manifest <-> zip must agree in both directions ---
        missing = [i['href'] for i in items.values() if full(i['href']) not in names]
        add('Manifest', not missing,
            f'{len(items)} items, all present'
            if not missing else 'Missing from the file: ' + ', '.join(missing[:4]))

        manifested = {full(i['href']) for i in items.values()} | {opf_path}
        stray = [n for n in names
                 if n not in manifested
                 and not n.startswith('META-INF/') and n != 'mimetype'
                 and not n.endswith('/')]
        add('No stray files', not stray,
            'Every file is declared in the manifest'
            if not stray else 'Not in the manifest: ' + ', '.join(stray[:4]))

        bad_spine = [s for s in spine if s not in items]
        add('Spine', spine and not bad_spine,
            f'{len(spine)} documents in reading order'
            if spine and not bad_spine else
            ('Spine is empty' if not spine
             else 'Spine references unknown ids: ' + ', '.join(bad_spine[:4])))

        nav = [i for i in items.values() if 'nav' in i['props'].split()]
        add('Navigation', bool(nav),
            'Navigation document declared' if nav else
            'No item carries properties="nav" — readers will show no table of contents')

        # --- every content document must actually parse ---
        docs = [i for i in items.values() if i['type'] == 'application/xhtml+xml']
        broken, ids, imgs, no_alt = [], {}, 0, []
        for d in docs:
            name = full(d['href'])
            if name not in names:
                continue
            try:
                dom = minidom.parseString(zf.read(name))
            except Exception as exc:
                broken.append(f'{d["href"]} ({exc})')
                continue
            ids[d['href']] = {el.getAttribute('id')
                              for el in dom.getElementsByTagName('*')
                              if el.getAttribute('id')}
            for img in dom.getElementsByTagName('img'):
                imgs += 1
                # a decorative image (the chapter ornament) is *supposed* to
                # have an empty alt — announcing it at every chapter is noise,
                # so an explicit role="presentation" answers the check
                if (img.getAttribute('role') == 'presentation'
                        or img.getAttribute('aria-hidden') == 'true'):
                    continue
                if not (img.getAttribute('alt') or '').strip():
                    no_alt.append(img.getAttribute('src') or '?')
        add('Content documents', not broken,
            f'{len(docs)} documents, all well-formed XHTML'
            if not broken else 'Not well-formed: ' + '; '.join(broken[:3]))

        if imgs:
            add('Image alt text', not no_alt,
                f'All {imgs} images carry alt text' if not no_alt else
                f'{len(no_alt)} of {imgs} images have no alt text: ' + ', '.join(no_alt[:3]))

        # --- internal links must land somewhere ---
        dangling = []
        for d in docs:
            name = full(d['href'])
            if name not in names:
                continue
            body = zf.read(name).decode('utf-8', 'replace')
            for href in re.findall(r'<a\s[^>]*href="([^"]+)"', body):
                if href.startswith(('http://', 'https://', 'mailto:')):
                    continue
                target, _, frag = href.partition('#')
                target = target or d['href']
                if full(target) not in names:
                    dangling.append(href)
                elif frag and frag not in ids.get(target, set()):
                    dangling.append(href)
        add('Internal links', not dangling,
            'Every in-book link resolves' if not dangling else
            f'{len(dangling)} link(s) point nowhere: ' + ', '.join(sorted(set(dangling))[:3]))

        # --- the two things shops look at ---
        cover = [i for i in items.values() if 'cover-image' in i['props'].split()]
        legacy = b'<meta name="cover"' in opf_raw
        if cover or legacy:
            add('Cover', bool(cover) and legacy,
                'Declared for both modern and older readers' if cover and legacy else
                'Declared only one way — some readers will show no cover')

        a11y = opf_raw.count(b'schema:access')
        add('Accessibility metadata', a11y >= 3,
            'Access modes, features and summary declared' if a11y >= 3 else
            'Missing — shops increasingly require it (EAA)')

    return out


def _a11y_meta(manifest_items):
    """Accessibility metadata for the OPF.

    This is what ACE (and, increasingly, the retailers) look for, and what the
    European Accessibility Act now expects a shop to be able to show. A reflowable
    text book generated from a semantic model is genuinely accessible — the claim
    just has to be *stated*, and an EPUB with no accessibility metadata reads to a
    checker as an unknown quantity rather than a good one.
    """
    has_images = any(i['type'].startswith('image/') for i in manifest_items)
    modes = ['textual'] + (['visual'] if has_images else [])
    lines = []
    for m in modes:
        lines.append(f'    <meta property="schema:accessMode">{m}</meta>')
    # text alone is enough to read the whole book, images being illustrative
    lines.append('    <meta property="schema:accessModeSufficient">textual</meta>')
    for feature in ('structuralNavigation', 'tableOfContents', 'readingOrder'):
        lines.append(f'    <meta property="schema:accessibilityFeature">{feature}</meta>')
    if has_images:
        lines.append('    <meta property="schema:accessibilityFeature">alternativeText</meta>')
    # no known hazards: no flashing, sound or motion in a typeset book
    lines.append('    <meta property="schema:accessibilityHazard">none</meta>')
    summary = ('Reflowable text with a full navigation document and reading order. '
               'All illustrations carry alternative text.' if has_images else
               'Reflowable text with a full navigation document and reading order.')
    lines.append(f'    <meta property="schema:accessibilitySummary">{summary}</meta>')
    return '\n'.join(lines) + '\n'


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
        f'    <dc:title>{_text_to_html(title)}</dc:title>\n'
        f'    <dc:creator>{_text_to_html(author)}</dc:creator>\n'
        '    <dc:language>en</dc:language>\n'
        f'    <dc:date>{_text_to_html(year)}</dc:date>\n'
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        + _a11y_meta(manifest_items) +
        cover_meta_xml +
        '  </metadata>\n'
        '  <manifest>\n'
        + manifest_xml + '\n'
        '  </manifest>\n'
        '  <spine>\n'
        + spine_xml + '\n'
        '  </spine>\n'
        '</package>\n'
    )


def _nav_li(href, label, kids=()):
    """One entry of the navigation document, with a chapter's headings nested
    under it by level (EPUB 3 wants each `<ol>` inside the `<li>` it belongs
    to). A level that skips one, a `###` straight under a chapter, nests one
    step, under the nearest heading above it."""
    out = f'      <li><a href="{href}">{_text_to_html(label)}</a>'
    if kids:
        stack = []                    # levels of the open lists
        for k_href, k_label, level in kids:
            while stack and stack[-1] > level:
                if len(stack) == 1 or stack[-2] < level:
                    stack[-1] = level   # shallower than its list: a sibling in it
                else:
                    out += '</li></ol>'
                    stack.pop()
            if stack and stack[-1] == level:
                out += '</li>'
            else:
                out += '<ol>'
                stack.append(level)
            out += f'<li><a href="{k_href}">{_text_to_html(k_label)}</a>'
        out += '</li></ol>' * len(stack)
    return out + '</li>'


def _nav_xhtml(chapters, has_cover, has_front, preset, meta=None, has_notes=False,
               has_index=False):
    c        = preset.get('chapter', {})
    show_num = c.get('show_number', True)
    num_fmt  = c.get('number_format', 'Chapter {n}')
    pd       = preset.get('part_divider', {})
    pd_fmt   = pd.get('number_format', 'Part {n}')

    meta = meta or {}
    depth = _toc_depth(preset)
    toc = []
    if has_cover:
        toc.append(('cover.xhtml', 'Cover'))
    if has_front:
        toc.append(('front.xhtml', 'Front Matter'))
    if meta.get('include_toc'):
        toc.append(('toc.xhtml', 'Contents'))
    for _sec in _matter.present(meta, 'front'):
        toc.append((_sec['href'],
                    _matter.heading(_sec, (meta or {}).get('author', ''))
                    or _sec['key'].replace('_', ' ').title()))
    _nums = _ms_numbers(chapters)
    current_part_num = None
    for idx, ch in enumerate(chapters, start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None
        if ch_part_num is not None and ch_part_num != current_part_num:
            part_label = ch_part.get('title') or pd_fmt.format(n=ch_part_num)
            toc.append((f'part{ch_part_num:03d}.xhtml', part_label))
            current_part_num = ch_part_num
        label = ch.get('title') or (num_fmt.format(n=_nums[idx - 1])
                                   if show_num and _nums[idx - 1] else f'Section {idx}')
        kids = [(f'chapter{idx:03d}.xhtml#{hid}', text, level)
                for hid, level, text in chapter_headings(ch) if level <= depth]
        toc.append((f'chapter{idx:03d}.xhtml', label, kids))

    if has_notes:
        toc.append(('endnotes.xhtml', preset.get('endnotes', {}).get('heading', 'Notes')))

    author = meta.get('author', '')
    for _sec in _matter.present(meta, 'back'):
        toc.append((_sec['href'],
                    _matter.heading(_sec, author) or _sec['key'].title()))
    if has_index:
        toc.append(('bookindex.xhtml', _bookindex.HEADING))

    items = '\n'.join(_nav_li(*entry) for entry in toc)
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


def _collect_figures(chapters, extra=()):
    """Find every ~~~ figure src="…" that resolves to a real file.

    Returns {src: {'href', 'path', 'id', 'mime'}} — one entry per distinct src,
    so the same illustration used twice is stored once. `extra` carries srcs
    that aren't figure blocks (the style's chapter-opening art) through the
    same resolve-and-manifest path; used as a chapter ornament it is stored
    once and referenced from every chapter.
    """
    found = {}

    def add(src):
        src = (src or '').strip()
        if not src or src in found:
            return
        path = src if os.path.isabs(src) else os.path.join(FIGURE_DIR, src)
        if not os.path.exists(path):
            return                                # _figure_html writes a note
        ext = os.path.splitext(path)[1].lower()
        n = len(found) + 1
        found[src] = {'path': path, 'href': f'images/fig{n:03d}{ext}',
                      'id': f'fig{n:03d}',
                      'mime': _FIG_MIME.get(ext, 'image/png')}

    for ch in chapters:
        for block in ch.get('blocks', []):
            if block[0] != 'doc_block' or len(block) < 3:
                continue
            m = block[2]
            if m.get('_type') != 'figure':
                continue
            add(m.get('src', ''))
    for src in extra:
        add(src)
    return found


# ---------------------------------------------------------------- public API
def build_epub(manuscript, preset, out_path, meta):
    """Write an EPUB 3 file to out_path. Returns out_path."""
    uid      = 'urn:uuid:' + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    chapters = _apply_note_markers(manuscript['chapters'])
    has_notes = any(ch.get('notes') for ch in chapters)
    chapters, ix_marks = _apply_index_markers(chapters, meta)
    has_index = _bookindex.wanted(ix_marks, meta)
    art_src  = chapter_art_src(preset)
    figures  = _collect_figures(chapters, extra=[art_src] if art_src else [])
    fig_href = {src: f['href'] for src, f in figures.items()}
    # '' when the style names a file that isn't there — the ebook simply opens
    # without the ornament, where the PDF proof draws its placeholder box
    art_href = fig_href.get(art_src, '')

    # anchor -> chapter file, so `[see](#slug)` resolves across the spine;
    # a heading or a `{#name}` -> its place in that file (#74 Phase 5b)
    chapters, ref_hrefs = _apply_page_refs(chapters, meta, preset)
    _BUILD.anchors = anchors = {}
    for _i, _names in enumerate(_ms_book_anchors(chapters), start=1):
        for _a in _names:
            anchors.setdefault(_a, f'chapter{_i:03d}.xhtml')
    for _a, _href in ref_hrefs.items():
        anchors.setdefault(_a, _href)

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

    # one SVG serves every scene break in the book; only ship it if the style
    # asks for an ornament *and* the manuscript actually breaks a scene
    scene_orn = scene_ornament(preset)
    if scene_orn and not any(b[0] == 'scene'
                             for ch in chapters for b in ch.get('blocks', [])):
        scene_orn = ''
    if scene_orn:
        manifest_items.append({'id': 'scene-orn', 'href': SCENE_ORN_HREF,
                               'type': 'image/svg+xml'})

    if has_front:
        manifest_items.append({'id': 'front', 'href': 'front.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('front')

    if meta.get('include_toc'):
        manifest_items.append({'id': 'toc-page', 'href': 'toc.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('toc-page')

    for _sec in _matter.present(meta, 'front'):
        manifest_items.append({'id': _sec['eid'], 'href': _sec['href'],
                                'type': 'application/xhtml+xml'})
        spine_items.append(_sec['eid'])

    _nums = _ms_numbers(chapters)
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
    if has_notes:
        manifest_items.append({'id': 'endnotes', 'href': 'endnotes.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('endnotes')

    for _sec in _matter.present(meta, 'back'):
        manifest_items.append({'id': _sec['eid'], 'href': _sec['href'],
                                'type': 'application/xhtml+xml'})
        spine_items.append(_sec['eid'])

    if has_index:                      # the last page of the book, as in print
        manifest_items.append({'id': 'bookindex', 'href': 'bookindex.xhtml',
                                'type': 'application/xhtml+xml'})
        spine_items.append('bookindex')

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and stored uncompressed
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/container.xml', _container_xml())
        zf.writestr('OEBPS/content.opf',
                    _content_opf(uid, meta, manifest_items, spine_items, modified))
        zf.writestr('OEBPS/nav.xhtml',
                    _nav_xhtml(chapters, has_cover, has_front, preset, meta=meta,
                               has_notes=has_notes, has_index=has_index))
        zf.writestr('OEBPS/style.css', _style_css(preset))

        if scene_orn:
            zf.writestr(f'OEBPS/{SCENE_ORN_HREF}',
                        _orn.svg(scene_orn, color='#666666', xml_decl=True))

        if has_cover:
            zf.write(cover_src, f'OEBPS/{cover_img_fn}')
            zf.writestr('OEBPS/cover.xhtml', _cover_xhtml(cover_img_fn))

        for f in figures.values():
            zf.write(f['path'], f'OEBPS/{f["href"]}')

        if has_front:
            zf.writestr('OEBPS/front.xhtml', _front_xhtml(meta))

        if meta.get('include_toc'):
            zf.writestr('OEBPS/toc.xhtml', _toc_page_xhtml(chapters, preset))

        for _sec in _matter.present(meta, 'front'):
            zf.writestr(f'OEBPS/{_sec["href"]}',
                        _matter_xhtml(_matter.heading(_sec, _author) or None,
                                      meta[_sec['key']].strip(),
                                      _MATTER_CSS.get(_sec['style'], 'matter-body')))

        current_part_num = None
        _numbers = _ms_numbers(chapters)
        for idx, ch in enumerate(chapters, start=1):
            ch_part     = ch.get('part')
            ch_part_num = ch_part['number'] if ch_part else None
            if ch_part_num is not None and ch_part_num != current_part_num:
                zf.writestr(f'OEBPS/part{ch_part_num:03d}.xhtml',
                            _part_xhtml(ch_part_num, ch_part.get('title') or '', preset))
                current_part_num = ch_part_num
            zf.writestr(f'OEBPS/chapter{idx:03d}.xhtml',
                        _chapter_xhtml(idx, ch, preset, figures=fig_href,
                                       number=_numbers[idx - 1],
                                       art_href=art_href))

        if has_notes:
            zf.writestr('OEBPS/endnotes.xhtml', _endnotes_xhtml(chapters, preset))

        for _sec in _matter.present(meta, 'back'):
            zf.writestr(f'OEBPS/{_sec["href"]}',
                        _matter_xhtml(_matter.heading(_sec, _author),
                                      meta[_sec['key']].strip(),
                                      _MATTER_CSS.get(_sec['style'], 'matter-body')))

        if has_index:
            zf.writestr('OEBPS/bookindex.xhtml',
                        _index_xhtml(chapters, ix_marks, meta, preset))

    return out_path
