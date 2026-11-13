"""The page-by-page ebook (#75c): a fixed-layout EPUB 3 for picture books.

A reflowable ebook can't hold a picture book, and a page that is one picture
with its words baked in fails the shops' rule that a children's ebook's words
be real text. So each designed page (`~~~ page src=`) becomes an XHTML page of
the book's trim size:

  - the art is one JPG of the design drawn without its text elements;
  - the words are live text over it, every line placed where the PDF puts it,
    from `wrap_design.text_layout` (the PDF's own breaks, offsets, tracking and
    justified word positions), in the design's own fonts, embedded.

The baseline is pinned the same way in every reader: each `@font-face` sets
`ascent-override` / `descent-override` to ReportLab's ascent and descent, with
no line gap, and each line box is exactly ascent + descent tall, so the
baseline sits at top + ascent. Kerning and ligatures are off, because
ReportLab sets neither. The spike (spikes/fixed_layout/spike.py) measured every
text box within 1 px of the PDF at 150 px per inch.

A spread is a left page and a right page (`page-spread-left/right`). Both
carry their half of the art, and each places all of the spread's words, so a
line across the fold reads across it, clipped at the page edge. Blank pages
go in where the print has them (a spread opens on a left page; `side=`), so
the pairs in the ebook are the pairs in print. The cover comes first, alone.

Text typed between the pages has no place on a page, so it is left out, and
`notes()` names it for the ebook checks, as it names words a shape or
picture is drawn over (the ebook draws every word on top of the art).
"""

import html
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

PX = 150                  # viewport pixels per inch of trim
ART_PIXELS = 4_000_000    # Apple Books' ceiling for one image
ART_DPI = 225             # the art's resolution, under that ceiling


def wanted(meta):
    """Whether a book's ebook is built page by page."""
    return (meta or {}).get('ebook_layout') == 'fixed'


# ---- which pages, in what order -----------------------------------------------------

def _plain(markup):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', '', str(markup or ''))).split())


def _block_words(block):
    """The words of a manuscript block, however it holds them."""
    out = []

    def walk(v):
        # a block, or a paragraph inside one, is (kind, …): skip the kind
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            tagged = v and isinstance(v[0], str) and re.fullmatch(r'[a-z_]+', v[0])
            for x in (v[1:] if tagged else v):
                walk(x)
    walk(block)
    return _plain(' '.join(out))


def _snippet(text, n=8):
    words = text.split()
    return ' '.join(words[:n]) + ('…' if len(words) > n else '')


def sequence(ms, designs):
    """The ebook's pages from a parsed manuscript, as print sets them:
    ([{'n', 'name', 'design', 'half', 'alt'} or {'n', 'blank': True}],
     [text left out], [designs the book doesn't have])."""
    import wrap_design as W
    pages, left_out, missing = [], [], []
    p = 1
    for ch in ms.get('chapters', []):
        part = ch.get('part')
        if part and part.get('title'):
            left_out.append(_snippet(_plain(part['title'])))
        for key in ('title', 'byline', 'tagline'):
            if ch.get(key):
                left_out.append(_snippet(_plain(ch[key])))
        for block in ch.get('blocks', []):
            is_page = (block[0] == 'doc_block' and len(block) >= 3
                       and block[2].get('_type') == 'page')
            if not is_page:
                words = _block_words(block)
                if words:
                    left_out.append(_snippet(words))
                continue
            src = (block[2].get('src') or '').strip()
            name = W.page_name(src)
            d = W.find_page(designs, name)
            if not d:
                missing.append(src or '(no name)')
                continue
            alt = _plain(' '.join(t for _, t in block[1] if t))
            if W.is_spread(d):
                if p % 2 == 1:
                    pages.append({'n': p, 'blank': True})
                    p += 1
                for half in ('left', 'right'):
                    pages.append({'n': p, 'name': name, 'design': d, 'half': half, 'alt': alt})
                    p += 1
                continue
            want = str(block[2].get('side', '')).strip().lower()
            want = {'recto': 'right', 'verso': 'left'}.get(want, want)
            if (want == 'right' and p % 2 == 0) or (want == 'left' and p % 2 == 1):
                pages.append({'n': p, 'blank': True})
                p += 1
            pages.append({'n': p, 'name': name, 'design': d, 'half': None, 'alt': alt})
            p += 1
    return pages, left_out, missing


# ---- words over art -----------------------------------------------------------------

def _text_box(g, el):
    """A text element's (x, y, w, h) on the sheet in inches, as set."""
    import wrap_design as W
    x, y, _, _ = W.el_rect(g, el)
    layout = W.text_layout(el)
    wide = max((W.line_width(ln, el) for ln, _, _, _ in layout), default=0.0) / 72.0
    w = el.get('w') or wide
    if not el.get('w') and el.get('align') in ('center', 'right'):
        x -= wide / (2.0 if el.get('align') == 'center' else 1.0)
    h = (layout[-1][2] if layout else 0) / 72.0 + el['size'] * 0.3 / 72.0
    if el.get('rotate') == 90:
        return x - h, y, h, w
    return x, y, w, h


def covered_words(design, trim_w, trim_h):
    """Whether a shape or picture is drawn over words on this design: the
    ebook puts every word on top of the art, so such a page reads differently."""
    import wrap_design as W
    g = W.design_geometry(design, trim_w, trim_h)
    els = [e for e in (design or {}).get('elements', [])
           if isinstance(e, dict) and not e.get('hidden')]
    for i, el in enumerate(els):
        if el.get('type') != 'text' or not W.font_file(el.get('font')) \
                or not str(el.get('text', '')).strip():
            continue
        try:
            tx, ty, tw, th = _text_box(g, el)
        except Exception:
            continue
        for over in els[i + 1:]:
            if over.get('type') in ('text', None):
                continue
            try:
                ox, oy, ow, oh = W.el_rect(g, over)
            except Exception:
                continue
            if ow > 0 and oh > 0 and ox < tx + tw and tx < ox + ow \
                    and oy < ty + th and ty < oy + oh:
                return True
    return False


def notes(ms, meta, preset):
    """The page-by-page ebook's own rows for the ebook checks: what it left
    out, what it couldn't find, and pages whose words sit under art."""
    trim = (preset or {}).get('trim') or {'w': 6.0, 'h': 9.0}
    designs = (meta or {}).get('page_designs') or []
    pages, left_out, missing = sequence(ms, designs)
    rows = []
    if left_out:
        shown = ', '.join(f'“{t}”' for t in left_out[:3])
        more = f' and {len(left_out) - 3} more' if len(left_out) > 3 else ''
        rows.append({'label': 'Text between pages', 'ok': False,
                     'detail': (f'Left out of the page-by-page ebook, which only holds '
                                f'designed pages: {shown}{more}. Put words that should '
                                f'be in it on a page in the designer.')})
    if missing:
        rows.append({'label': 'Missing page designs', 'ok': False,
                     'detail': 'Not in this book, so not in the ebook: '
                               + ', '.join(missing[:4])})
    seen, covered = set(), []
    for pg in pages:
        if pg.get('blank') or pg['name'] in seen:
            continue
        seen.add(pg['name'])
        if covered_words(pg['design'], trim['w'], trim['h']):
            covered.append(pg['name'])
    if covered:
        rows.append({'label': 'Words under art', 'ok': False,
                     'detail': ('A shape or picture is drawn over words on '
                                + ', '.join(covered[:4])
                                + '. The ebook sets the words on top, so move the art '
                                  'behind them (or the words off it) to match print.')})
    if not [p for p in pages if not p.get('blank')]:
        rows.append({'label': 'Designed pages', 'ok': False,
                     'detail': 'This book places no page designs, so its page-by-page '
                               'ebook has nothing in it but the cover.'})
    return rows


# ---- the files ----------------------------------------------------------------------

def _fonts(designs_used):
    """{font file: (family, ascent, descent)} for every face the words use."""
    import wrap_design as W
    from reportlab.pdfbase import pdfmetrics
    out = {}
    for d in designs_used:
        for el in d.get('elements', []):
            f = el.get('font') if isinstance(el, dict) and el.get('type') == 'text' else None
            if not f or f in out or not W.font_file(f):
                continue
            face = pdfmetrics.getFont(W.font_name(f)).face
            out[f] = (f'ts{len(out)}', float(face.ascent), abs(float(face.descent)))
    return out


def _css(fonts):
    faces = ''.join(
        "@font-face{font-family:'%s';src:url('fonts/%s');"
        "ascent-override:%.3f%%;descent-override:%.3f%%;line-gap-override:0%%}\n"
        % (fam, os.path.basename(f), asc / 10.0, desc / 10.0)
        for f, (fam, asc, desc) in fonts.items())
    return faces + (
        'html,body{margin:0;padding:0;overflow:hidden;background:#ffffff}\n'
        'body{position:relative}\n'
        'img.art,img.cover{position:absolute;left:0;top:0;border:0}\n'
        '.t{position:absolute;width:0;height:0}\n'
        '.t span{position:absolute;white-space:pre;font-kerning:none;'
        'font-variant-ligatures:none;'
        'font-feature-settings:"kern" 0,"liga" 0,"clig" 0,"calt" 0}\n')


def _num(v):
    s = ('%.2f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('', '-0') else s


def words_html(design, g, fonts, shift_x=0.0):
    """The design's words as absolutely placed lines, in viewport px from the
    page's top-left. `shift_x` (inches) moves a spread's right page into view."""
    import wrap_design as W
    k = PX / 72.0
    out = []
    for el in design.get('elements', []):
        if not isinstance(el, dict) or el.get('type') != 'text' or el.get('hidden') \
                or el.get('font') not in fonts or not str(el.get('text', '')):
            continue
        fam, asc, desc = fonts[el['font']]
        x, y, _, _ = W.el_rect(g, el)
        X, Y = (x - g['bleed'] - shift_x) * PX, (y - g['bleed']) * PX
        size = el['size'] * k
        spans = []
        for line, dx, base, words in W.text_layout(el):
            top = base * k - size * asc / 1000.0
            for run, rx in (words or [(line, dx)]):
                if run:
                    spans.append(f'<span style="left:{_num(rx * k)}px;top:{_num(top)}px">'
                                 f'{html.escape(run, quote=False)}</span>')
        if not spans:
            continue
        style = [f'left:{_num(X)}px', f'top:{_num(Y)}px', f"font-family:'{fam}'",
                 f'font-size:{_num(size)}px',
                 f'line-height:{_num(size * (asc + desc) / 1000.0)}px',
                 f'color:{el.get("color") or "#000000"}']
        if el.get('tracking'):
            style.append(f'letter-spacing:{_num(float(el["tracking"]) * k)}px')
        if float(el.get('opacity', 1.0)) < 1.0:
            style.append(f'opacity:{float(el["opacity"]):.3f}')
        if el.get('rotate') == 90:
            style.append('transform:rotate(90deg);transform-origin:0 0')
        out.append(f'<div class="t" style="{";".join(style)}">' + ''.join(spans) + '</div>')
    return out


def _page_doc(title, vw, vh, body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">\n'
            f'<head>\n<meta charset="utf-8"/>\n<title>{html.escape(title)}</title>\n'
            f'<meta name="viewport" content="width={vw}, height={vh}"/>\n'
            '<link rel="stylesheet" type="text/css" href="fxl.css"/>\n</head>\n'
            f'<body style="width:{vw}px;height:{vh}px">\n' + '\n'.join(body)
            + '\n</body>\n</html>\n')


def art_dpi(trim_w, trim_h):
    """The art's resolution: ART_DPI, less for a page too big for it."""
    return int(min(ART_DPI, (ART_PIXELS / (trim_w * trim_h)) ** 0.5))


def _render_art(design, trim_w, trim_h, tmpdir, stem):
    """The design without its words, as one JPG per page: [path] (two for a
    spread, its left page then its right)."""
    import wrap_design as W
    from PIL import Image
    art = dict(design, elements=[e for e in design.get('elements', [])
                                 if not (isinstance(e, dict) and e.get('type') == 'text')])
    whole = os.path.join(tmpdir, f'{stem}-whole.jpg')
    W.render_page(art, trim_w, trim_h, whole, dpi=art_dpi(trim_w, trim_h))
    if not W.is_spread(design):
        path = os.path.join(tmpdir, f'{stem}.jpg')
        os.replace(whole, path)
        return [path]
    out = []
    with Image.open(whole) as im:
        half = im.width // 2
        for i, box in enumerate(((0, 0, half, im.height), (half, 0, im.width, im.height))):
            path = os.path.join(tmpdir, f'{stem}-{"lr"[i]}.jpg')
            im.crop(box).save(path, 'JPEG', quality=90)
            out.append(path)
    os.remove(whole)
    return out


def _opf(uid, meta, manifest, spine, modified, vw, vh):
    from epub import _text_to_html
    items = '\n'.join(
        f'    <item id="{i["id"]}" href="{i["href"]}" media-type="{i["type"]}"'
        + (f' properties="{i["props"]}"' if i.get('props') else '') + '/>'
        for i in manifest)
    refs = '\n'.join(f'    <itemref idref="{s}" properties="{p}"/>' for s, p in spine)
    cover_id = next((i['id'] for i in manifest if 'cover-image' in (i.get('props') or '')), '')
    a11y = ''.join(f'    <meta property="schema:{k}">{v}</meta>\n' for k, v in (
        ('accessMode', 'textual'), ('accessMode', 'visual'),
        ('accessModeSufficient', 'textual,visual'),
        ('accessibilityFeature', 'readingOrder'),
        ('accessibilityFeature', 'tableOfContents'),
        ('accessibilityFeature', 'pageNavigation'),
        ('accessibilityHazard', 'none'),
        ('accessibilitySummary', 'A fixed-layout picture book: the words on every page '
                                 'are live text over its illustration, in reading order.')))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
            ' unique-identifier="uid" xml:lang="en">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
            f'    <dc:title>{_text_to_html(meta.get("title") or "Untitled")}</dc:title>\n'
            f'    <dc:creator>{_text_to_html(meta.get("author", ""))}</dc:creator>\n'
            '    <dc:language>en</dc:language>\n'
            f'    <dc:date>{_text_to_html(meta.get("year", ""))}</dc:date>\n'
            f'    <meta property="dcterms:modified">{modified}</meta>\n'
            '    <meta property="rendition:layout">pre-paginated</meta>\n'
            '    <meta property="rendition:orientation">auto</meta>\n'
            '    <meta property="rendition:spread">landscape</meta>\n'
            # Kindle's own names for the same things; KDP refuses a picture
            # book without them
            '    <meta name="fixed-layout" content="true"/>\n'
            f'    <meta name="original-resolution" content="{vw}x{vh}"/>\n'
            '    <meta name="book-type" content="children"/>\n'
            '    <meta name="orientation-lock" content="none"/>\n'
            '    <meta name="primary-writing-mode" content="horizontal-lr"/>\n'
            + a11y
            + (f'    <meta name="cover" content="{cover_id}"/>\n' if cover_id else '')
            + '  </metadata>\n  <manifest>\n' + items + '\n  </manifest>\n'
            '  <spine page-progression-direction="ltr">\n' + refs + '\n  </spine>\n'
            '</package>\n')


def _nav(has_cover, first_href, pages):
    toc = []
    if has_cover:
        toc.append('<li><a href="cover.xhtml">Cover</a></li>')
    if first_href:
        toc.append(f'<li><a href="{first_href}">Beginning</a></li>')
    plist = ''.join(f'<li><a href="{href}">{n}</a></li>' for n, href in pages)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">\n'
            '<head><meta charset="utf-8"/><title>Contents</title></head>\n<body>\n'
            '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>'
            + (''.join(toc) or '<li><a href="nav.xhtml">Contents</a></li>') + '</ol></nav>\n'
            + (f'<nav epub:type="page-list" hidden="hidden"><ol>{plist}</ol></nav>\n'
               if plist else '')
            + '</body>\n</html>\n')


def build(ms, preset, out_path, meta):
    """Write the page-by-page EPUB to out_path. Returns out_path."""
    import wrap_design as W
    from PIL import Image
    trim = (preset or {}).get('trim') or {'w': 6.0, 'h': 9.0}
    tw, th = float(trim['w']), float(trim['h'])
    vw, vh = round(tw * PX), round(th * PX)
    pages, _, _ = sequence(ms, meta.get('page_designs') or [])
    used = []
    for pg in pages:
        if not pg.get('blank') and pg['design'] not in used:
            used.append(pg['design'])
    fonts = _fonts(used)

    manifest = [{'id': 'nav', 'href': 'nav.xhtml', 'type': 'application/xhtml+xml',
                 'props': 'nav'},
                {'id': 'css', 'href': 'fxl.css', 'type': 'text/css'}]
    for i, f in enumerate(fonts):
        manifest.append({'id': f'font{i + 1}', 'href': f'fonts/{os.path.basename(f)}',
                         'type': 'font/ttf'})
    spine, docs, files, plist = [], {}, {}, []

    cover_src = meta.get('cover_image', '')
    has_cover = bool(cover_src and os.path.exists(cover_src))
    if has_cover:
        ext = os.path.splitext(cover_src)[1].lower()
        mime = 'image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/png'
        with Image.open(cover_src) as im:
            cw, ch = im.size
        s = min(1.0, max(vw, vh) / float(max(cw, ch))) if max(cw, ch) else 1.0
        cvw, cvh = max(1, round(cw * s)), max(1, round(ch * s))
        manifest += [{'id': 'cover-img', 'href': 'images/cover' + ext, 'type': mime,
                      'props': 'cover-image'},
                     {'id': 'cover', 'href': 'cover.xhtml', 'type': 'application/xhtml+xml'}]
        files['images/cover' + ext] = cover_src
        title = meta.get('title') or 'Cover'
        docs['cover.xhtml'] = _page_doc('Cover', cvw, cvh, [
            f'<img class="cover" src="images/cover{ext}" width="{cvw}" height="{cvh}" '
            f'style="width:{cvw}px;height:{cvh}px" alt="{html.escape(title)}"/>'])
        spine.append(('cover', 'rendition:page-spread-center'))

    tmp = tempfile.mkdtemp(prefix='ts-fxl-')
    try:
        art = {}                               # id(design) -> [image hrefs]
        first_href = ''
        for pg in pages:
            n = pg['n']
            href, pid = f'page{n:03d}.xhtml', f'p{n:03d}'
            side = 'page-spread-right' if n % 2 else 'page-spread-left'
            if pg.get('blank'):
                body = []
            else:
                d = pg['design']
                if id(d) not in art:
                    stem = f'art{len(art) + 1:03d}'
                    try:
                        paths = _render_art(d, tw, th, tmp, stem)
                    except Exception:
                        paths = []
                    hrefs = []
                    for path in paths:
                        h = 'images/' + os.path.basename(path)
                        files[h] = path
                        manifest.append({'id': os.path.splitext(os.path.basename(path))[0],
                                         'href': h, 'type': 'image/jpeg'})
                        hrefs.append(h)
                    art[id(d)] = hrefs
                hrefs = art[id(d)]
                img = hrefs[1 if pg['half'] == 'right' and len(hrefs) > 1 else 0] \
                    if hrefs else ''
                alt = html.escape(pg['alt'], quote=True)
                body = ([f'<img class="art" src="{img}" width="{vw}" height="{vh}" '
                         f'style="width:{vw}px;height:{vh}px" alt="{alt}"'
                         + ('' if alt else ' role="presentation"') + '/>'] if img else [])
                g = W.design_geometry(d, tw, th)
                body += words_html(d, g, fonts, shift_x=tw if pg['half'] == 'right' else 0.0)
                first_href = first_href or href
            docs[href] = _page_doc(f'Page {n}', vw, vh, body)
            manifest.append({'id': pid, 'href': href, 'type': 'application/xhtml+xml'})
            spine.append((pid, side))
            plist.append((n, href))

        uid = 'urn:uuid:' + str(uuid.uuid4())
        modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                        compress_type=zipfile.ZIP_STORED)
            from epub import _container_xml
            zf.writestr('META-INF/container.xml', _container_xml())
            zf.writestr('OEBPS/content.opf', _opf(uid, meta, manifest, spine, modified, vw, vh))
            zf.writestr('OEBPS/nav.xhtml', _nav(has_cover, first_href, plist))
            zf.writestr('OEBPS/fxl.css', _css(fonts))
            for f in fonts:
                zf.write(W.font_file(f), f'OEBPS/fonts/{os.path.basename(f)}')
            for h, path in files.items():
                zf.write(path, f'OEBPS/{h}')
            for h, text in docs.items():
                zf.writestr(f'OEBPS/{h}', text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path
