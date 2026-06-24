"""Typesetting engine: manuscript + preset -> print-ready interior PDF.

Single-pass build. Page furniture (running heads + folios) is drawn at page
*end*, when we already know whether the page is a chapter opener or a
deliberately blank page, so no guessing or pre-pass is needed.

Imposition produced:
  * configurable trim with mirrored (gutter) margins
  * optional front matter (half title / title / copyright), unnumbered
  * arabic body folios beginning at 1 on the first body page
  * running heads: author on verso, title on recto; suppressed on openers/blanks
  * chapter openers, optionally forced to a recto page (blank verso inserted)
  * scene breaks, subheads, four chapter-open initial styles
  * embedded TrueType fonts (KDP / IngramSpark friendly)
"""

import os
import re
import tempfile

try:
    import pyphen as _pyphen
    _HAVE_PYPHEN = True
except ImportError:
    _HAVE_PYPHEN = False

from manuscript import _inline as _ms_inline
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    PageBreak, Flowable, NextPageTemplate, Table, TableStyle,
)
from reportlab.platypus.paragraph import Paragraph as _P
from reportlab.lib import colors as _colors

try:
    from PIL import Image as PILImage, ImageOps
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')


# ---------------------------------------------------------------- fonts
def register_fonts(preset):
    fam   = preset.get('font_family', 'Book')
    files = preset.get('font_files', {
        'regular': 'Book-Regular.ttf',
        'bold': 'Book-Bold.ttf',
        'italic': 'Book-Italic.ttf',
    })
    roles   = {}
    details = {}  # role -> {'file': str, 'ok': bool, 'error': str|None}

    for role, fname in files.items():
        path = fname if os.path.isabs(fname) else os.path.join(FONT_DIR, fname)
        name = f'{fam}-{role}'
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                roles[role]   = name
                details[role] = {'file': fname, 'ok': True, 'error': None}
            except Exception as e:
                details[role] = {'file': fname, 'ok': False, 'error': str(e)}
        else:
            details[role] = {'file': fname, 'ok': False, 'error': 'file not found'}

    fallback = 'regular' not in roles
    if fallback:
        roles = {'regular': 'Times-Roman', 'bold': 'Times-Bold',
                 'italic': 'Times-Italic'}
        fam = 'Times'
    else:
        pdfmetrics.registerFontFamily(
            fam, normal=roles['regular'],
            bold=roles.get('bold', roles['regular']),
            italic=roles.get('italic', roles['regular']),
            boldItalic=roles.get('bold', roles['regular']))

    return {
        'family':   fam,
        'regular':  roles['regular'],
        'bold':     roles.get('bold',   roles['regular']),
        'italic':   roles.get('italic', roles['regular']),
        'fallback': fallback,
        'details':  details,
    }


# ---------------------------------------------------------------- flowables
class SceneBreak(Flowable):
    def __init__(self, glyph, font, size, gap, image_path=None):
        super().__init__()
        self.glyph, self.font, self.size, self.gap = glyph, font, size, gap
        self.image_path = image_path

    def wrap(self, w, h):
        self.width = w
        self.height = self.gap * 2 + self.size
        return (w, self.height)

    def draw(self):
        if self.image_path and os.path.exists(self.image_path):
            try:
                from reportlab.lib.utils import ImageReader
                ir  = ImageReader(self.image_path)
                iw, ih = ir.getSize()
                img_h = self.size
                img_w = img_h * (iw / ih)
                x = (self.width - img_w) / 2.0
                self.canv.drawImage(self.image_path, x, self.gap,
                                    width=img_w, height=img_h, mask='auto')
                return
            except Exception:
                pass
        # Fallback: text glyph
        self.canv.setFont(self.font, self.size)
        self.canv.drawCentredString(self.width / 2.0, self.gap, self.glyph)


class RectoBreak(Flowable):
    width = height = 0
    def wrap(self, w, h): return (0, 0)
    def draw(self): pass


class BlankMarker(Flowable):
    width = height = 0
    def wrap(self, w, h): return (0, 0)
    def draw(self): self.canv._is_blank = True


class OpenerMarker(Flowable):
    width = height = 0
    def wrap(self, w, h): return (0, 0)
    def draw(self): self.canv._is_opener = True


class HRule(Flowable):
    """Thin horizontal rule for framing document blocks."""
    def __init__(self, color=(0.55, 0.55, 0.55), thickness=0.5):
        super().__init__()
        self.color, self.thickness = color, thickness

    def wrap(self, w, h):
        self.width = w
        self.height = self.thickness + 4
        return (w, self.height)

    def draw(self):
        c = self.canv
        c.setStrokeColorRGB(*self.color)
        c.setLineWidth(self.thickness)
        y = self.thickness / 2 + 1
        c.line(0, y, self.width, y)


class DropCap(Flowable):
    """Sunken drop cap: first lines set beside the initial, rest flows below."""
    def __init__(self, text, body_style, cap_font, lines=3):
        super().__init__()
        self.text, self.body, self.cap_font, self.lines = text, body_style, cap_font, lines
        self._cap = text[:1]
        self._rest = text[1:].lstrip()

    def wrap(self, availWidth, availHeight):
        leading = self.body.leading
        self.cap_size = leading * self.lines * 0.92
        cw = stringWidth(self._cap, self.cap_font, self.cap_size)
        self.cap_w = cw + self.body.fontSize * 0.16
        narrow = ParagraphStyle('beside', parent=self.body,
                                leftIndent=self.cap_w, firstLineIndent=0)
        self._full = ParagraphStyle('below', parent=self.body, firstLineIndent=0)
        beside_h = leading * self.lines
        para = _P(self._rest, narrow)
        para.wrap(availWidth, availHeight)
        parts = para.split(availWidth, beside_h)
        if len(parts) == 2:
            self._beside, self._below = parts
            self._beside.wrap(availWidth, beside_h)
            self._below.style = self._full
            _, blh = self._below.wrap(availWidth, availHeight)
            self.height = beside_h + blh
        else:
            self._beside, self._below = para, None
            self._beside.wrap(availWidth, availHeight)
            self.height = max(self.cap_size, beside_h)
        self.width = availWidth
        return (availWidth, self.height)

    def draw(self):
        c = self.canv
        leading = self.body.leading
        top = self.height
        c.setFont(self.cap_font, self.cap_size)
        c.drawString(0, top - self.cap_size * 0.82, self._cap)
        if self._beside:
            self._beside.drawOn(c, 0, top - leading * self.lines)
        if self._below:
            c2 = self._below
            c2.drawOn(c, 0, top - leading * self.lines - c2.height)


# ---------------------------------------------------------------- doc template
class BookDoc(BaseDocTemplate):
    def __init__(self, filename, preset, meta, head_font, cover=None, **kw):
        self.preset, self.meta = preset, meta
        self.head_font = head_font
        self._body_start = None            # page number of the first chapter opener
        self._cover = cover or {}          # {path, overlay, color, title_font}
        trim = preset['trim']
        pw, ph = trim['w'] * inch, trim['h'] * inch
        m = preset['margins']
        top, bottom = m['top'] * inch, m['bottom'] * inch
        inside, outside = m['inside'] * inch, m['outside'] * inch
        tw, th = pw - inside - outside, ph - top - bottom
        self._pw, self._ph = pw, ph
        self._top, self._bottom = top, bottom
        self._inside, self._outside = inside, outside
        recto = Frame(inside, bottom, tw, th, id='recto',
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        verso = Frame(outside, bottom, tw, th, id='verso',
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        full = Frame(0, 0, pw, ph, id='full',
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        super().__init__(filename, pagesize=(pw, ph), **kw)
        templates = []
        if self._cover.get('path'):
            # cover first, so page 1 paints the artwork full-bleed
            templates.append(PageTemplate(id='cover', frames=[full],
                                          onPage=self._draw_cover, onPageEnd=self._furniture))
        templates += [
            PageTemplate(id='recto', frames=[recto], onPageEnd=self._furniture),
            PageTemplate(id='verso', frames=[verso], onPageEnd=self._furniture),
            PageTemplate(id='blank', frames=[recto], onPageEnd=self._furniture),
        ]
        self.addPageTemplates(templates)

    def _draw_cover(self, canv, doc):
        if canv.getPageNumber() != 1:
            return
        cv = self._cover
        path = cv.get('path')
        if not path or not os.path.exists(path):
            return
        canv.drawImage(path, 0, 0, width=self._pw, height=self._ph,
                       preserveAspectRatio=False, mask=None)
        if not cv.get('overlay'):
            return
        light = cv.get('color', 'light') == 'light'
        title = self.meta.get('title', '')
        author = self.meta.get('author', '')
        tfont = cv.get('title_font', self.head_font)
        afont = self.head_font
        cx = self._pw / 2.0
        ty = self._ph * 0.30
        # soft scrim band for legibility
        canv.saveState()
        canv.setFillColorRGB(0, 0, 0) if light else canv.setFillColorRGB(1, 1, 1)
        canv.setFillAlpha(0.32)
        band_h = self._ph * 0.26
        canv.rect(0, ty - band_h * 0.42, self._pw, band_h, stroke=0, fill=1)
        canv.setFillAlpha(1)
        canv.setFillColorRGB(1, 1, 1) if light else canv.setFillColorRGB(0.06, 0.06, 0.06)
        tsize = min(34, self._pw / max(len(title), 8) * 1.6) if title else 28
        canv.setFont(tfont, tsize)
        canv.drawCentredString(cx, ty, title)
        if author:
            canv.setFont(afont, tsize * 0.5)
            canv.drawCentredString(cx, ty - tsize * 0.95, author)
        canv.restoreState()

    def handle_pageBegin(self):
        self.canv._is_opener = False
        self.canv._is_blank = False
        self._handle_pageBegin()

    def handle_flowable(self, flowables):
        f = flowables[0]
        if isinstance(f, RectoBreak):
            flowables.pop(0)
            at_top = getattr(self.frame, '_atTop', False)
            cur = self.page                # page currently being composed
            cur_odd = (cur % 2 == 1)
            if at_top:
                if cur_odd:
                    seq = []               # empty recto -> start right here
                else:                      # empty verso -> blank it, move to recto
                    seq = [BlankMarker(), NextPageTemplate('recto'), PageBreak()]
            else:
                if cur_odd:                # content on recto -> blank verso, then recto
                    seq = [NextPageTemplate('blank'), PageBreak(), BlankMarker(),
                           NextPageTemplate('recto'), PageBreak()]
                else:                      # content on verso -> next page is recto
                    seq = [NextPageTemplate('recto'), PageBreak()]
            for item in reversed(seq):
                flowables.insert(0, item)
            return
        BaseDocTemplate.handle_flowable(self, flowables)

    def _furniture(self, canv, doc):
        p = self.preset
        page = canv.getPageNumber()
        if getattr(canv, '_is_blank', False):
            return
        # the first chapter opener defines folio 1; everything before it is front matter
        if getattr(canv, '_is_opener', False) and self._body_start is None:
            self._body_start = page
        if self._body_start is None or page < self._body_start:
            return
        folio = page - self._body_start + 1
        recto = (page % 2 == 1)
        opener = getattr(canv, '_is_opener', False)
        tw = self._pw - self._inside - self._outside
        text_left = self._inside if recto else self._outside
        cx = text_left + tw / 2.0

        rh = p['running_head']
        if rh['show'] and not opener:
            y = self._ph - self._top + rh['gap'] * inch
            canv.setFont(self.head_font, rh['size'])
            canv.setFillGray(0.2)
            txt = self.meta.get('title', '') if recto else self.meta.get('author', '')
            if rh.get('caps'):
                txt = txt.upper()
            canv.drawCentredString(cx, y, txt)

        fo = p['folio']
        if fo['show'] and not (opener and fo.get('hide_on_opener')):
            y = self._bottom - fo['gap'] * inch
            canv.setFont(self.head_font, fo['size'])
            canv.setFillGray(0.2)
            if fo['position'] == 'outer':
                if recto:
                    canv.drawRightString(self._pw - self._outside, y, str(folio))
                else:
                    canv.drawString(self._outside, y, str(folio))
            else:
                canv.drawCentredString(cx, y, str(folio))


# ---------------------------------------------------------------- styles
def _styles(preset, fonts):
    b = preset['body']
    body = ParagraphStyle('body', fontName=fonts['regular'], fontSize=b['size'],
                          leading=b['leading'],
                          alignment=TA_JUSTIFY if b['justify'] else TA_LEFT,
                          firstLineIndent=b['indent'] * inch,
                          allowWidows=0, allowOrphans=0)
    first = ParagraphStyle('first', parent=body, firstLineIndent=0)
    c = preset['chapter']
    chap_title = ParagraphStyle('chap', fontName=fonts.get('bold', fonts['regular']),
                                fontSize=c['title_size'], leading=c['title_size'] * 1.15,
                                alignment=TA_CENTER)
    chap_num = ParagraphStyle('cnum', fontName=fonts['regular'],
                              fontSize=c['number_size'], leading=c['number_size'] * 1.2,
                              alignment=TA_CENTER, textColor=(0.3, 0.3, 0.3))
    subhead = ParagraphStyle('sub', parent=body, fontName=fonts.get('bold', fonts['regular']),
                             firstLineIndent=0, alignment=TA_CENTER,
                             spaceBefore=b['leading'], spaceAfter=b['leading'] * 0.5)
    pd = preset.get('part_divider', {})
    part_num_style = ParagraphStyle('partnum', fontName=fonts['regular'],
                                    fontSize=pd.get('number_size', 13.0),
                                    leading=pd.get('number_size', 13.0) * 1.2,
                                    alignment=TA_CENTER, textColor=(0.35, 0.35, 0.35))
    part_title_style = ParagraphStyle('parttitle', fontName=fonts.get('bold', fonts['regular']),
                                      fontSize=pd.get('title_size', 26.0),
                                      leading=pd.get('title_size', 26.0) * 1.15,
                                      alignment=TA_CENTER)
    return dict(body=body, first=first, chap_title=chap_title, chap_num=chap_num,
                subhead=subhead, part_num=part_num_style, part_title=part_title_style)


_TAG_RE = re.compile(r'<[^>]+>')


def _plain(text):
    """Strip ReportLab XML tags; leave XML entities (&amp; etc.) intact."""
    return _TAG_RE.sub('', text)


_SHY = '­'  # soft hyphen recognised by ReportLab as a valid line-break point

def _hyphenate_markup(text, dic):
    """Insert soft hyphens into text nodes of ReportLab XML markup.

    Tags are left untouched; only runs of 5+ letter words in text nodes
    are hyphenated (short words and numbers aren't worth breaking).
    """
    parts  = re.split(r'(<[^>]+>)', text)
    result = []
    for part in parts:
        if part.startswith('<'):
            result.append(part)
        else:
            result.append(re.sub(
                r'\b[A-Za-z]{5,}\b',
                lambda m: dic.inserted(m.group(), hyphen=_SHY),
                part,
            ))
    return ''.join(result)


def _opening_para(text, st, preset, fonts, hyph=None):
    style = preset['chapter']['open_style']
    plain = _plain(text)
    if style == 'dropcap':
        plain_h = _hyphenate_markup(plain, hyph) if hyph else plain
        return [DropCap(plain_h, st['first'], fonts.get('bold', fonts['regular']),
                        lines=preset['chapter'].get('dropcap_lines', 3))]
    if style == 'raised_initial':
        big  = int(st['first'].fontSize * 1.9)
        rest = _hyphenate_markup(plain[1:], hyph) if hyph else plain[1:]
        return [Paragraph(f'<font size="{big}">{plain[:1]}</font>{rest}', st['first'])]
    if style == 'smallcaps_leadin':
        words = plain.split(' ')
        n     = preset['chapter'].get('leadin_words', 4)
        lead, rest = ' '.join(words[:n]), ' '.join(words[n:])
        big   = int(st['first'].fontSize * 1.05)
        rest  = _hyphenate_markup(rest, hyph) if hyph else rest
        return [Paragraph(f'<font size="{big}">{lead.upper()}</font> {rest}', st['first'])]
    text_h = _hyphenate_markup(text, hyph) if hyph else text
    return [Paragraph(text_h, st['first'])]


def _default_copyright(meta):
    lines = [f"Copyright \u00a9 {meta.get('year','')} {meta.get('author','')}".strip(), '',
             'All rights reserved. No part of this book may be reproduced in any form '
             'without written permission from the publisher, except brief quotations '
             'in a review.', '',
             'This is a work of fiction. Names, characters, places, and incidents are '
             'the products of the author\u2019s imagination or used fictitiously.', '']
    if meta.get('publisher'):
        lines.append(meta['publisher'])
    return '\n'.join(lines)


def _render_doc_block(block_paras, preset, fonts, st, avail_w, hyph=None):
    """Return flowables for one ~~~ … ~~~ document block."""
    db     = preset.get('document_block', {})
    frame  = db.get('frame', 'ruled')
    indent = db.get('indent', 0.25) * inch
    size   = db.get('font_size', 0) or st['body'].fontSize
    lead   = size * 1.45
    fi     = db.get('first_indent', 0.0) * inch
    space  = db.get('space_around', 12.0)

    db_style = ParagraphStyle(
        'dbpara', parent=st['body'],
        fontName=fonts['regular'],
        fontSize=size, leading=lead,
        firstLineIndent=fi,
        leftIndent=indent, rightIndent=indent,
        spaceBefore=0, spaceAfter=2,
    )
    # first paragraph of the block never has first-line indent (no indent on opening line of a letter)
    db_first = ParagraphStyle('dbfirst', parent=db_style, firstLineIndent=0)

    out = [Spacer(1, space)]

    if frame in ('ruled', 'box'):
        out += [HRule(), Spacer(1, 5)]

    if frame == 'box':
        col_w = avail_w - 2 * indent
        rows  = [[Paragraph(_hyphenate_markup(text, hyph) if hyph else text,
                             db_first if i == 0 else db_style)]
                 for i, (_, text) in enumerate(block_paras)]
        t = Table(rows, colWidths=[col_w])
        t.setStyle(TableStyle([
            ('BOX',          (0, 0), (-1, -1), 0.5,  _colors.Color(.55, .55, .55)),
            ('BACKGROUND',   (0, 0), (-1, -1),       _colors.Color(.97, .96, .94)),
            ('LEFTPADDING',  (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING',   (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ]))
        out.append(t)
    else:
        for i, (_, text) in enumerate(block_paras):
            t = _hyphenate_markup(text, hyph) if hyph else text
            out.append(Paragraph(t, db_first if i == 0 else db_style))

    if frame in ('ruled', 'box'):
        out += [Spacer(1, 5), HRule()]

    out.append(Spacer(1, space))
    return out


def _matter_page(heading, text, fonts, st, smartquotes, style='body'):
    """Flowables for one front/back matter page. Caller handles page breaks."""
    # Split on blank lines into raw paragraph strings
    blocks = [' '.join(l.strip() for l in b.split('\n') if l.strip()).strip()
              for b in text.replace('\r\n', '\n').split('\n\n')]
    blocks = [b for b in blocks if b]

    out = [BlankMarker()]

    if style == 'dedication':
        s = ParagraphStyle('ded', fontName=fonts['italic'],
                           fontSize=st['body'].fontSize, leading=st['body'].leading,
                           alignment=TA_CENTER, firstLineIndent=0)
        out.append(Spacer(1, 2.2 * inch))
        for b in blocks:
            out.append(Paragraph(_ms_inline(b, smartquotes), s))

    elif style == 'epigraph':
        s_q = ParagraphStyle('epiq', fontName=fonts['regular'],
                              fontSize=st['body'].fontSize - 0.5, leading=st['body'].leading,
                              leftIndent=1.2*inch, rightIndent=0.5*inch, firstLineIndent=0)
        s_a = ParagraphStyle('epia', parent=s_q, leftIndent=0.5*inch, alignment=TA_RIGHT,
                              fontSize=st['body'].fontSize - 1.5, textColor=(0.4, 0.4, 0.4))
        out.append(Spacer(1, 2.2 * inch))
        _attr = ('—', '–', '--', '-')
        for i, b in enumerate(blocks):
            is_attr = i == len(blocks) - 1 and any(b.startswith(m) for m in _attr)
            out.append(Paragraph(_ms_inline(b, smartquotes), s_a if is_attr else s_q))

    elif style == 'also_by':
        s = ParagraphStyle('aby', fontName=fonts['regular'],
                           fontSize=st['body'].fontSize, leading=st['body'].leading + 4,
                           alignment=TA_CENTER, firstLineIndent=0)
        out.append(Spacer(1, 1.0 * inch))
        if heading:
            out.append(Paragraph(heading, st['chap_title']))
            out.append(Spacer(1, 0.4 * inch))
        for b in blocks:
            out.append(Paragraph(_ms_inline(b, smartquotes), s))

    else:  # body: acknowledgments, about_author
        out.append(Spacer(1, 1.0 * inch))
        if heading:
            out.append(Paragraph(heading, st['chap_title']))
            out.append(Spacer(1, 0.4 * inch))
        s_first = ParagraphStyle('mb1', parent=st['body'], firstLineIndent=0)
        for i, b in enumerate(blocks):
            out.append(Paragraph(_ms_inline(b, smartquotes), s_first if i == 0 else st['body']))

    return out


def _build_story(manuscript, preset, meta, fonts, st, head_font, has_cover=False, avail_w=0, hyph=None):
    glyph = preset['scene_break']['glyph']
    story = []

    # ---- cover page (full-bleed art drawn by the page template) ----
    if has_cover:
        story += [Spacer(1, 2), NextPageTemplate('verso'), PageBreak()]

    # ---- front matter ----
    level = meta.get('front_matter', 'full')
    if level is True:
        level = 'full'
    elif level is False:
        level = 'none'
    rhs = meta.get('right_hand_starts', True)

    if level != 'none':
        big = ParagraphStyle('tb', fontName=fonts.get('bold', fonts['regular']),
                             fontSize=26, leading=30, alignment=TA_CENTER)
        auth = ParagraphStyle('ta', fontName=fonts['regular'], fontSize=13,
                              leading=18, alignment=TA_CENTER)
        half = ParagraphStyle('hf', fontName=fonts['regular'], fontSize=15, leading=20,
                              alignment=TA_CENTER, textColor=(0.3, 0.3, 0.3))
        small = ParagraphStyle('sm', fontName=fonts['regular'], fontSize=8.5, leading=12.5)

        def title_page():
            s = [Spacer(1, 1.8 * inch), Paragraph(meta.get('title', ''), big),
                 Spacer(1, 0.3 * inch)]
            if meta.get('subtitle'):
                s += [Paragraph(meta['subtitle'], auth), Spacer(1, 0.2 * inch)]
            s += [Spacer(1, 0.2 * inch), Paragraph(meta.get('author', ''), auth), PageBreak()]
            return s

        def copyright_page():
            cp = meta.get('copyright') or _default_copyright(meta)
            return [BlankMarker(), Spacer(1, 5.6 * inch),
                    Paragraph(cp.replace('\n', '<br/>'), small), PageBreak()]

        if level == 'full':
            story += [Spacer(1, 2.2 * inch), Paragraph(meta.get('title', ''), half), PageBreak()]
            if rhs:                                    # blank verso so title lands recto
                story += [BlankMarker(), PageBreak()]
            story += title_page()
            story += copyright_page()
        elif level == 'title':
            story += title_page()
            story += copyright_page()
        elif level == 'copyright':
            story += copyright_page()

    # ---- front matter extras (dedication, epigraph) ----
    sq = meta.get('smartquotes', True)
    _fm_need_break = len(story) > 0
    for _key, _mstyle in [('dedication', 'dedication'), ('epigraph', 'epigraph')]:
        _txt = meta.get(_key, '').strip()
        if not _txt:
            continue
        if _fm_need_break:
            story.append(RectoBreak() if rhs else PageBreak())
        _fm_need_break = True
        story.extend(_matter_page(None, _txt, fonts, st, sq, _mstyle))

    # ---- body ----
    c  = preset['chapter']
    pd = preset.get('part_divider', {})
    m  = preset['margins']
    text_h = (preset['trim']['h'] - m['top'] - m['bottom']) * inch

    need_break      = False   # True after the first body element is placed
    current_part_num = None

    for idx, ch in enumerate(manuscript['chapters'], start=1):
        ch_part     = ch.get('part')
        ch_part_num = ch_part['number'] if ch_part else None

        # --- part divider when a new part starts ---
        if ch_part_num is not None and ch_part_num != current_part_num:
            if c['start'] == 'recto' and rhs:
                story.append(RectoBreak())
            elif need_break:
                story.append(PageBreak())
            story.append(BlankMarker())   # suppress folio/running-head on divider
            sink_pts = pd.get('sink', 0.38) * text_h
            story.append(Spacer(1, sink_pts))
            if pd.get('show_number', True):
                label = pd.get('number_format', 'Part {n}').format(n=ch_part_num)
                story.append(Paragraph(label, st['part_num']))
                story.append(Spacer(1, 0.15 * inch))
            if ch_part.get('title'):
                story.append(Paragraph(ch_part['title'], st['part_title']))
            current_part_num = ch_part_num
            need_break = True

        # --- chapter break ---
        if c['start'] == 'recto' and rhs:
            story.append(RectoBreak())
        elif need_break:
            story.append(PageBreak())
        need_break = True

        story.append(OpenerMarker())
        story.append(Spacer(1, c['sink'] * inch))
        if c.get('show_number', True):
            label = c.get('number_format', 'Chapter {n}').format(n=idx)
            story.append(Paragraph(label, st['chap_num']))
            story.append(Spacer(1, 0.12 * inch))
        if ch['title']:
            story.append(Paragraph(ch['title'], st['chap_title']))
        story.append(Spacer(1, c['after_title'] * inch))
        opened = False
        flush_next = False  # paragraph right after scene/subhead: no indent
        for kind, val in ch['blocks']:
            if kind == 'scene':
                sb = preset['scene_break']
                img_path = None
                if sb.get('type') == 'image' and sb.get('image', '').strip():
                    raw_img = sb['image'].strip()
                    img_path = raw_img if os.path.isabs(raw_img) else os.path.join(FONT_DIR, raw_img)
                story.append(SceneBreak(glyph, head_font, sb['size'], sb['gap'],
                                        image_path=img_path))
                flush_next = True
            elif kind == 'subhead':
                story.append(Paragraph(val, st['subhead']))
                flush_next = True
            elif kind == 'doc_block':
                if not opened:
                    opened = True
                story.extend(_render_doc_block(val, preset, fonts, st, avail_w, hyph=hyph))
                flush_next = True
            else:
                if not opened:
                    story.extend(_opening_para(val, st, preset, fonts, hyph=hyph))
                    opened = True
                elif flush_next:
                    val_h = _hyphenate_markup(val, hyph) if hyph else val
                    story.append(Paragraph(val_h, st['first']))
                else:
                    val_h = _hyphenate_markup(val, hyph) if hyph else val
                    story.append(Paragraph(val_h, st['body']))
                flush_next = False

    # ---- back matter (acknowledgments, about author, also by) ----
    _author = meta.get('author', '')
    _back = [
        ('acknowledgments', 'Acknowledgments',                    'body'),
        ('about_author',    'About the Author',                   'body'),
        ('also_by',         f'Also by {_author}'.strip() or 'Also By', 'also_by'),
    ]
    for _key, _heading, _mstyle in _back:
        _txt = meta.get(_key, '').strip()
        if not _txt:
            continue
        story.append(RectoBreak() if rhs else PageBreak())
        story.extend(_matter_page(_heading, _txt, fonts, st, sq, _mstyle))

    return story


def _prepare_cover(meta, preset):
    """Crop/scale the cover art to the trim at 300 dpi. Returns a temp path or None."""
    src = meta.get('cover_image')
    if not src or not os.path.exists(src) or not _HAVE_PIL:
        return None
    try:
        trim = preset['trim']
        dpi = 300
        w_px = int(round(trim['w'] * dpi))
        h_px = int(round(trim['h'] * dpi))
        img = PILImage.open(src).convert('RGB')
        img = ImageOps.fit(img, (w_px, h_px), method=PILImage.LANCZOS)
        fd, tmp = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        img.save(tmp, 'JPEG', quality=92)
        return tmp
    except Exception:
        return None


def build_pdf(manuscript, preset, out_path, meta):
    fonts = register_fonts(preset)
    st = _styles(preset, fonts)
    head_font = fonts['regular']

    cover = None
    cover_path = _prepare_cover(meta, preset)
    if cover_path:
        cover = {'path': cover_path,
                 'overlay': meta.get('cover_overlay', False),
                 'color': meta.get('cover_color', 'light'),
                 'title_font': fonts.get('bold', fonts['regular'])}

    m       = preset['margins']
    avail_w = (preset['trim']['w'] - m['inside'] - m['outside']) * inch
    hyph    = _pyphen.Pyphen(lang='en_US') if (preset['body'].get('hyphenate') and _HAVE_PYPHEN) else None
    story   = _build_story(manuscript, preset, meta, fonts, st, head_font,
                           has_cover=bool(cover), avail_w=avail_w, hyph=hyph)
    doc = BookDoc(out_path, preset, meta, head_font, cover=cover,
                  title=meta.get('title', ''), author=meta.get('author', ''))
    doc.build(story)
    page_count = doc.page
    if cover_path:
        try:
            os.remove(cover_path)
        except OSError:
            pass
    return {
        'page_count':     page_count,
        'font_family':    fonts['family'],
        'font_fallback':  fonts['fallback'],
        'font_details':   fonts['details'],
        'fonts_embedded': not fonts['fallback'],
    }
