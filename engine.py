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
import math
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


# ---------------------------------------------------------------- cover helpers
def _hex(s):
    """'#rrggbb' / '#rgb' -> reportlab Color. Falls back to black."""
    s = str(s).lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    try:
        return _colors.Color(int(s[0:2], 16) / 255.0,
                             int(s[2:4], 16) / 255.0,
                             int(s[4:6], 16) / 255.0)
    except Exception:
        return _colors.black


def _tracked_centre(canv, cx, y, text, font, size, tracking=0.0):
    """Draw letterspaced text centred on cx at baseline y."""
    if not text:
        return
    w = stringWidth(text, font, size) + tracking * max(len(text) - 1, 0)
    to = canv.beginText(cx - w / 2.0, y)
    to.setFont(font, size)
    to.setCharSpace(tracking)
    to.textOut(text)
    canv.drawText(to)


def _wrap_tracked(text, font, size, max_w, tracking=0.0):
    """Word-wrap text to max_w, honouring the tracking already applied."""
    out = []
    for para in (str(text).splitlines() or ['']):
        words = para.split()
        if not words:
            out.append('')
            continue
        cur = ''
        for wd in words:
            trial = (cur + ' ' + wd).strip()
            w = stringWidth(trial, font, size) + tracking * max(len(trial) - 1, 0)
            if w <= max_w or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = wd
        if cur:
            out.append(cur)
    return out


def _diamond(canv, cx, cy, r):
    p = canv.beginPath()
    p.moveTo(cx, cy + r)
    p.lineTo(cx + r, cy)
    p.lineTo(cx, cy - r)
    p.lineTo(cx - r, cy)
    p.close()
    canv.drawPath(p, stroke=0, fill=1)


def _register_cover_fonts(tpl, interior):
    """Register the cover template's own faces; fall back to the interior fonts."""
    files = tpl.get('fonts', {})
    out = {}
    for role in ('display', 'serif', 'italic'):
        fname = files.get(role)
        if not fname:
            continue
        path = fname if os.path.isabs(fname) else os.path.join(FONT_DIR, fname)
        name = f'Cover-{role}'
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                out[role] = name
            except Exception:
                pass
    out.setdefault('serif', interior.get('regular', 'Times-Roman'))
    out.setdefault('display', out['serif'])
    out.setdefault('italic', interior.get('italic', 'Times-Italic'))
    return out


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


class TocMarker(Flowable):
    """Chapter opener marker that also records its page for TOC generation."""
    width = height = 0

    def __init__(self, idx, title, part=None):
        super().__init__()
        self.idx, self.title, self.part = idx, title, part

    def wrap(self, w, h): return (0, 0)

    def draw(self):
        self.canv._is_opener = True
        doc = self.canv._doctemplate
        if hasattr(doc, '_toc_entries'):
            doc._toc_entries.append({
                'idx':   self.idx,
                'title': self.title,
                'part':  self.part,
                'page':  self.canv.getPageNumber(),
            })


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
        self._body_start  = None           # page number of the first chapter opener
        self._toc_entries = []             # filled by TocMarker during build
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
        if self._cover.get('path') or self._cover.get('mode') == 'designed':
            # cover first, so page 1 paints the artwork / designed layout full-bleed
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
        if cv.get('mode') == 'designed':
            self._draw_designed_cover(canv)
            return
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

    def _draw_designed_cover(self, canv):
        """Render a text-driven cover from a covers/*.json template on page 1."""
        cv   = self._cover
        tpl  = cv.get('template', {})
        cf   = cv.get('fonts', {'display': self.head_font,
                                'serif': self.head_font, 'italic': self.head_font})
        meta = self.meta
        pw, ph = self._pw, self._ph
        cx = pw / 2.0
        pal = tpl.get('palette', {})

        def C(name):
            """Resolve a palette key or literal hex to a Color."""
            v = pal.get(name, name)
            return _hex(v if isinstance(v, str) else '#000000')

        canv.saveState()

        # -- background: solid base + vertical gradient (navy top -> darker bottom)
        canv.setFillColor(_hex(pal.get('bg_bottom', '#080d15')))
        canv.rect(0, 0, pw, ph, stroke=0, fill=1)
        try:
            canv.linearGradient(0, ph, 0, 0,
                                [_hex(pal.get('bg_top', '#101a29')),
                                 _hex(pal.get('bg_bottom', '#080d15'))],
                                extend=True)
        except Exception:
            pass

        # -- border: double gold rule with outward corner brackets
        b = tpl.get('border', {})
        inset = b.get('inset', 0.42) * inch
        gap   = b.get('gap', 0.055) * inch
        gold  = C(b.get('color', 'gold'))
        x0, y0, x1, y1 = inset, inset, pw - inset, ph - inset
        canv.setStrokeColor(gold)
        canv.setLineWidth(b.get('line', 1.0))
        canv.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)
        canv.rect(x0 + gap, y0 + gap, (x1 - x0) - 2 * gap, (y1 - y0) - 2 * gap,
                  stroke=1, fill=0)
        bl = b.get('corner', 0.5) * inch
        bo = gap * 1.6
        canv.setLineWidth(b.get('corner_line', 1.3))
        for (px, py, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                                 (x0, y1, 1, -1), (x1, y1, -1, -1)):
            ox, oy = px - sx * bo, py - sy * bo
            canv.line(ox, oy, ox + sx * bl, oy)
            canv.line(ox, oy, ox, oy + sy * bl)

        inner_w = (x1 - x0) - 2 * gap

        # -- collection line (top) — letterspaced small caps
        cc = tpl.get('collection', {})
        coll = (meta.get('cover_collection') or '').upper()
        if coll:
            canv.setFillColor(C(cc.get('color', 'gold')))
            _tracked_centre(canv, cx, ph * cc.get('top', 0.70), coll,
                            cf['serif'], cc.get('size', 12.5), cc.get('tracking', 3.4))

        # -- kicker ("player options") — italic, muted
        kk = tpl.get('kicker', {})
        kick = meta.get('cover_kicker', '')
        if kick:
            canv.setFillColor(C(kk.get('color', 'muted')))
            _tracked_centre(canv, cx, ph * kk.get('y', 0.665), kick,
                            cf['italic'], kk.get('size', 11), kk.get('tracking', 0.4))

        # -- title — big display serif, wrapped, letterspaced
        tt = tpl.get('title', {})
        title = (meta.get('title') or '').upper()
        last_y = ph * tt.get('y', 0.585)
        tsize = tt.get('size', 40)
        if title:
            maxw = inner_w - 0.4 * inch
            trk = tt.get('tracking', 0.6)
            # shrink to fit: the longest word must not cross the border
            lines = _wrap_tracked(title, cf['display'], tsize, maxw, trk)
            while tsize > 14 and any(
                    stringWidth(ln, cf['display'], tsize) + trk * max(len(ln) - 1, 0) > maxw
                    for ln in lines):
                tsize -= 1
                lines = _wrap_tracked(title, cf['display'], tsize, maxw, trk)
            leading = tt.get('leading', 46) * (tsize / tt.get('size', 40))
            canv.setFillColor(C(tt.get('color', 'gold')))
            yy = ph * tt.get('y', 0.585)
            for ln in lines:
                _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
                last_y = yy
                yy -= leading

        # -- accent line — teal, cleared below the title.
        # Defaults to the Author; the cover_accent field overrides it (e.g. "& Feats").
        ac = tpl.get('accent', {})
        accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
        if accent:
            asize = ac.get('size', 21)
            # clearance = title descender room + this line's cap height + tunable gap
            clearance = tsize * 0.42 + asize * 0.55 + ac.get('gap', 0.008) * ph
            last_y = last_y - clearance
            canv.setFillColor(C(ac.get('color', 'teal')))
            _tracked_centre(canv, cx, last_y, accent, cf['display'],
                            asize, ac.get('tracking', 1.4))

        # -- ornament — three vector diamonds flanked by thin rules
        orn = tpl.get('ornament', {})
        oy = last_y - orn.get('gap', 0.05) * ph
        ocol = C(orn.get('color', 'gold'))
        canv.setFillColor(ocol)
        canv.setStrokeColor(ocol)
        r = orn.get('size', 2.4)
        sp = orn.get('spacing', 9)
        for i, dx in enumerate((-sp, 0, sp)):
            _diamond(canv, cx + dx, oy, r * (1.25 if i == 1 else 1.0))
        rl = orn.get('rule_len', 0.8) * inch
        if orn.get('rule', 0.8):
            canv.setLineWidth(orn.get('rule', 0.8))
            inner = sp + r + 7
            canv.line(cx - inner - rl, oy, cx - inner, oy)
            canv.line(cx + inner, oy, cx + inner + rl, oy)

        # -- epigraph — italic, muted, centred, wrapped to a narrow column
        ep = tpl.get('epigraph', {})
        epi = meta.get('cover_epigraph') or meta.get('epigraph') or ''
        if epi:
            ew = (x1 - x0) * ep.get('width', 0.62)
            lines = _wrap_tracked(epi, cf['italic'], ep.get('size', 10.5),
                                  ew, ep.get('tracking', 0.2))
            canv.setFillColor(C(ep.get('color', 'muted')))
            yy = ph * ep.get('top', 0.375)
            for ln in lines:
                _tracked_centre(canv, cx, yy, ln, cf['italic'],
                                ep.get('size', 10.5), ep.get('tracking', 0.2))
                yy -= ep.get('leading', 15)

        # -- collection line (bottom) + studio footer
        if coll:
            canv.setFillColor(C(cc.get('color', 'gold')))
            _tracked_centre(canv, cx, ph * cc.get('bottom', 0.115), coll,
                            cf['serif'], cc.get('size', 12.5) * 0.82, cc.get('tracking', 3.4))
        st = tpl.get('studio', {})
        studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
        if studio:
            canv.setFillColor(C(st.get('color', 'muted')))
            _tracked_centre(canv, cx, ph * st.get('y', 0.088), studio,
                            cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

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


# ---------------------------------------------------------------- epistolary helpers

_EP_TAG_RE = re.compile(r'<[^>]+>')


def _ep_plain(markup):
    """Strip ReportLab XML tags for plain-text extraction (used by telegram)."""
    s = _EP_TAG_RE.sub('', markup)
    return s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')


def _ep_dfont(fonts, dateline_style):
    return fonts['bold'] if dateline_style in ('bold', 'smallcaps') else fonts['italic']


def _ep_dtext(s, dateline_style):
    return s.upper() if dateline_style == 'smallcaps' else s


def _render_letter_block(block_paras, attrs, db, fonts, st, avail_w, hyph,
                          header_size, dateline_style):
    """Letter: From/To/Date header between rules, body with no first-line indent."""
    indent  = db.get('indent', 0.25) * inch
    space   = db.get('space_around', 12.0)
    size    = db.get('font_size', 0) or st['body'].fontSize
    lead    = size * 1.45
    dfont   = _ep_dfont(fonts, dateline_style)

    hdr_s = ParagraphStyle('ltr-hdr', parent=st['body'],
                            fontName=dfont, fontSize=header_size,
                            leading=header_size * 1.45,
                            leftIndent=indent, rightIndent=indent,
                            firstLineIndent=0, spaceBefore=0, spaceAfter=1)
    body_s = ParagraphStyle('ltr-body', parent=st['body'],
                             fontName=fonts['regular'],
                             fontSize=size, leading=lead,
                             leftIndent=indent, rightIndent=indent,
                             firstLineIndent=0, spaceBefore=0, spaceAfter=2)

    out = [Spacer(1, space), HRule(), Spacer(1, 6)]

    sender    = attrs.get('from', '').strip()
    recipient = attrs.get('to',   '').strip()
    date      = attrs.get('date', '').strip()
    parts = []
    if sender and recipient:
        parts.append(f'{sender} to {recipient}')
    elif sender:
        parts.append(sender)
    elif recipient:
        parts.append(f'To {recipient}')
    if date:
        parts.append(date)
    if parts:
        hdr_text = '  ·  '.join(_ep_dtext(p, dateline_style) for p in parts)
        out += [Paragraph(hdr_text, hdr_s), Spacer(1, 6)]

    out += [HRule(), Spacer(1, 8)]
    for _, text in block_paras:
        t = _hyphenate_markup(text, hyph) if hyph else text
        out.append(Paragraph(t, body_s))
    out += [Spacer(1, 5), HRule(), Spacer(1, space)]
    return out


def _render_journal_block(block_paras, attrs, db, fonts, st, avail_w, hyph,
                           header_size, dateline_style):
    """Journal entry: date/author header between rules, body in italic."""
    indent  = db.get('indent', 0.25) * inch
    space   = db.get('space_around', 12.0)
    size    = db.get('font_size', 0) or st['body'].fontSize
    lead    = size * 1.45
    dfont   = _ep_dfont(fonts, dateline_style)

    hdr_s = ParagraphStyle('jnl-hdr', parent=st['body'],
                            fontName=dfont, fontSize=header_size,
                            leading=header_size * 1.45,
                            leftIndent=indent, rightIndent=indent,
                            firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    body_s = ParagraphStyle('jnl-body', parent=st['body'],
                             fontName=fonts['italic'],
                             fontSize=size, leading=lead,
                             leftIndent=indent, rightIndent=indent,
                             firstLineIndent=0, spaceBefore=0, spaceAfter=2)

    out = [Spacer(1, space), HRule(), Spacer(1, 6)]

    date   = attrs.get('date',   '').strip()
    author = attrs.get('author', '').strip()
    parts  = []
    if date:
        parts.append(date)
    if author:
        parts.append(author)
    if parts:
        hdr_text = '  ·  '.join(_ep_dtext(p, dateline_style) for p in parts)
        out += [Paragraph(hdr_text, hdr_s), Spacer(1, 6)]

    out += [HRule(), Spacer(1, 8)]
    for _, text in block_paras:
        t = _hyphenate_markup(text, hyph) if hyph else text
        out.append(Paragraph(t, body_s))
    out += [Spacer(1, 5), HRule(), Spacer(1, space)]
    return out


def _render_telegram_block(block_paras, attrs, db, fonts, st, avail_w, hyph,
                            header_size, dateline_style):
    """Telegram: boxed with 'TELEGRAM' banner, Courier uppercase body."""
    indent  = db.get('indent', 0.25) * inch
    space   = db.get('space_around', 12.0)
    size    = db.get('font_size', 0) or st['body'].fontSize
    lead    = size * 1.45

    banner_s = ParagraphStyle('tel-banner', parent=st['body'],
                               fontName=fonts['bold'], fontSize=header_size + 1,
                               leading=(header_size + 1) * 1.4,
                               alignment=TA_CENTER,
                               firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    meta_s   = ParagraphStyle('tel-meta', parent=st['body'],
                               fontName=fonts['regular'], fontSize=header_size - 1,
                               leading=header_size * 1.4,
                               firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    body_s   = ParagraphStyle('tel-body', parent=st['body'],
                               fontName='Courier', fontSize=size - 0.5,
                               leading=lead,
                               firstLineIndent=0, spaceBefore=0, spaceAfter=2)

    col_w   = avail_w - 2 * indent
    to_val  = attrs.get('to', '').strip()
    rows    = [[Paragraph('TELEGRAM', banner_s)]]
    n_hdr   = 1
    if to_val:
        rows.append([Paragraph(f'To: {to_val.upper()}', meta_s)])
        n_hdr = 2
    for _, text in block_paras:
        rows.append([Paragraph(_ep_plain(text).upper(), body_s)])

    t = Table(rows, colWidths=[col_w])
    t.setStyle(TableStyle([
        ('BOX',          (0, 0),           (-1, -1),         1.0, _colors.Color(.3, .3, .3)),
        ('LINEBELOW',    (0, n_hdr - 1),   (0, n_hdr - 1),   0.5, _colors.Color(.4, .4, .4)),
        ('BACKGROUND',   (0, 0),           (0, 0),                _colors.Color(.93, .93, .93)),
        ('LEFTPADDING',  (0, 0),           (-1, -1),         10),
        ('RIGHTPADDING', (0, 0),           (-1, -1),         10),
        ('TOPPADDING',   (0, 0),           (-1, -1),          4),
        ('BOTTOMPADDING',(0, 0),           (-1, -1),          4),
    ]))
    return [Spacer(1, space), t, Spacer(1, space)]


def _render_newspaper_block(block_paras, attrs, db, fonts, st, avail_w, hyph,
                             header_size, dateline_style):
    """Newspaper clipping: bold headline, source/date, ruled separator, body."""
    indent  = db.get('indent', 0.25) * inch
    space   = db.get('space_around', 12.0)
    size    = db.get('font_size', 0) or st['body'].fontSize
    lead    = size * 1.45
    hl_size = min(st['body'].fontSize * 1.4, 15.0)

    hl_s = ParagraphStyle('np-hl', parent=st['body'],
                           fontName=fonts['bold'], fontSize=hl_size,
                           leading=hl_size * 1.25, alignment=TA_CENTER,
                           firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    byline_s = ParagraphStyle('np-byline', parent=st['body'],
                               fontName=fonts['italic'], fontSize=header_size - 0.5,
                               leading=header_size * 1.4, alignment=TA_CENTER,
                               firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    body_s = ParagraphStyle('np-body', parent=st['body'],
                             fontName=fonts['regular'],
                             fontSize=size - 0.5, leading=lead,
                             leftIndent=indent, rightIndent=indent,
                             firstLineIndent=0, spaceBefore=0, spaceAfter=2)

    out = [Spacer(1, space), HRule(thickness=1.0), Spacer(1, 5)]

    headline = attrs.get('headline', '').strip()
    if headline:
        out += [Paragraph(headline.upper(), hl_s), Spacer(1, 3)]

    byline_parts = [p for p in (attrs.get('source', '').strip(),
                                 attrs.get('date',   '').strip()) if p]
    if byline_parts:
        out += [Paragraph('  ·  '.join(byline_parts), byline_s), Spacer(1, 4)]

    out += [HRule(), Spacer(1, 6)]
    for _, text in block_paras:
        t = _hyphenate_markup(text, hyph) if hyph else text
        out.append(Paragraph(t, body_s))
    out += [Spacer(1, 4), HRule(thickness=1.0), Spacer(1, space)]
    return out


def _render_redacted_block(block_paras, attrs, db, fonts, st, avail_w, hyph,
                            header_size, dateline_style):
    """Redacted document: classification banner + dark-bordered box body."""
    indent  = db.get('indent', 0.25) * inch
    space   = db.get('space_around', 12.0)
    size    = db.get('font_size', 0) or st['body'].fontSize
    lead    = size * 1.45
    col_w   = avail_w - 2 * indent

    class_s = ParagraphStyle('red-class', parent=st['body'],
                              fontName=fonts['bold'], fontSize=header_size,
                              leading=header_size * 1.45, alignment=TA_CENTER,
                              firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    body_s  = ParagraphStyle('red-body', parent=st['body'],
                              fontName=fonts['regular'],
                              fontSize=size, leading=lead,
                              firstLineIndent=0, spaceBefore=0, spaceAfter=2)

    classification = attrs.get('classification', '').strip()
    rows = []
    if classification:
        rows.append([Paragraph(classification.upper(), class_s)])
    for _, text in block_paras:
        t = _hyphenate_markup(text, hyph) if hyph else text
        rows.append([Paragraph(t, body_s)])

    t_styles = [
        ('BOX',          (0, 0), (-1, -1), 1.0, _colors.Color(.2, .2, .2)),
        ('LEFTPADDING',  (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING',   (0, 0), (-1, -1),  4),
        ('BOTTOMPADDING',(0, 0), (-1, -1),  4),
    ]
    if classification:
        t_styles += [
            ('BACKGROUND', (0, 0), (0, 0),        _colors.Color(.85, .85, .85)),
            ('LINEBELOW',  (0, 0), (0, 0), 0.75,  _colors.Color(.2, .2, .2)),
        ]

    tbl = Table(rows, colWidths=[col_w])
    tbl.setStyle(TableStyle(t_styles))
    return [Spacer(1, space), tbl, Spacer(1, space)]


def _render_doc_block(block_paras, preset, fonts, st, avail_w, hyph=None, block_meta=None):
    """Return flowables for one ~~~ … ~~~ document block."""
    meta  = block_meta or {}
    btype = meta.get('_type', '')
    if btype:
        attrs          = {k: v for k, v in meta.items() if k != '_type'}
        db             = preset.get('document_block', {})
        header_size    = db.get('header_size', 9.5)
        dateline_style = db.get('dateline_style', 'italic')
        dispatch = {
            'letter':    _render_letter_block,
            'journal':   _render_journal_block,
            'telegram':  _render_telegram_block,
            'newspaper': _render_newspaper_block,
            'redacted':  _render_redacted_block,
        }
        fn = dispatch.get(btype)
        if fn:
            return fn(block_paras, attrs, db, fonts, st, avail_w, hyph,
                      header_size, dateline_style)

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


def _build_story(manuscript, preset, meta, fonts, st, head_font,
                 has_cover=False, avail_w=0, hyph=None, toc_flowables=None):
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

    # ---- table of contents (inserted after copyright, before front extras) ----
    if toc_flowables:
        story.append(RectoBreak() if rhs else PageBreak())
        story.extend(toc_flowables)

    # ---- front matter extras (dedication, epigraph) ----
    sq = meta.get('smartquotes', True)
    _fm_need_break = len(story) > 0
    _fm_first = True   # only the first extra page gets recto-forced
    for _key, _mstyle in [('dedication', 'dedication'), ('epigraph', 'epigraph')]:
        _txt = meta.get(_key, '').strip()
        if not _txt:
            continue
        if _fm_need_break:
            story.append((RectoBreak() if rhs else PageBreak()) if _fm_first else PageBreak())
        _fm_need_break = True
        _fm_first = False
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

        story.append(TocMarker(idx, ch.get('title'), ch.get('part')))
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
        for block in ch['blocks']:
            kind = block[0]
            val  = block[1]
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
                blk_meta = block[2] if len(block) > 2 else {}
                story.extend(_render_doc_block(val, preset, fonts, st, avail_w,
                                               hyph=hyph, block_meta=blk_meta))
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
    _bm_first = True   # only the first back-matter page gets recto-forced
    for _key, _heading, _mstyle in _back:
        _txt = meta.get(_key, '').strip()
        if not _txt:
            continue
        story.append((RectoBreak() if rhs else PageBreak()) if _bm_first else PageBreak())
        _bm_first = False
        story.extend(_matter_page(_heading, _txt, fonts, st, sq, _mstyle))

    return story


def _build_toc(entries, body_start, avail_w, preset, fonts, st, folio_offset=0):
    """Return flowables for the Contents page(s)."""
    c       = preset['chapter']
    num_fmt = c.get('number_format', 'Chapter {n}')
    size    = st['body'].fontSize
    lead    = st['body'].leading
    font    = fonts['regular']

    toc_ch  = ParagraphStyle('toc_ch',  fontName=font, fontSize=size,   leading=lead,    firstLineIndent=0)
    toc_pt  = ParagraphStyle('toc_pt',  fontName=fonts.get('bold', font),
                              fontSize=size, leading=lead + 2, firstLineIndent=0,
                              spaceBefore=4, textColor=(0.2, 0.2, 0.2))

    out = [BlankMarker(), Paragraph('Contents', st['chap_title']), Spacer(1, 0.4 * inch)]

    dot_char = '.'
    last_part = None

    for e in entries:
        folio = (e['page'] - (body_start or 1) + 1) + folio_offset
        if folio < 1:
            folio = 1

        # Part heading (no page number)
        part = e.get('part')
        if part and part != last_part:
            out.append(Paragraph(part.get('title') or
                                 f"Part {part['number']}", toc_pt))
            last_part = part

        # Chapter line with dot leaders
        label    = e.get('title') or num_fmt.format(n=e['idx'])
        folio_s  = str(folio)
        lw       = stringWidth(label + '  ',  font, size)
        fw       = stringWidth('  ' + folio_s, font, size)
        n_dots   = max(3, int((avail_w - lw - fw) / stringWidth(dot_char, font, size)))
        line     = f'{label}  {dot_char * n_dots}  {folio_s}'
        indent   = 0.18 * inch if part else 0
        s = ParagraphStyle('toc_line', parent=toc_ch, leftIndent=indent)
        out.append(Paragraph(line, s))

    return out


def _estimate_toc_pages(toc_flowables, preset):
    m  = preset['margins']
    ph = (preset['trim']['h'] - m['top'] - m['bottom']) * inch
    pw = (preset['trim']['w'] - m['inside'] - m['outside']) * inch
    total = sum(f.wrap(pw, ph)[1] for f in toc_flowables if hasattr(f, 'wrap'))
    return max(1, math.ceil(total / ph))


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
    cover_path = None            # temp image path to clean up (image mode only)
    if meta.get('cover_mode') == 'designed' and meta.get('cover_template_data'):
        ctpl = meta['cover_template_data']
        cover = {'mode': 'designed',
                 'template': ctpl,
                 'fonts': _register_cover_fonts(ctpl, fonts)}
    else:
        cover_path = _prepare_cover(meta, preset)
        if cover_path:
            cover = {'mode': 'image',
                     'path': cover_path,
                     'overlay': meta.get('cover_overlay', False),
                     'color': meta.get('cover_color', 'light'),
                     'title_font': fonts.get('bold', fonts['regular'])}

    m       = preset['margins']
    avail_w = (preset['trim']['w'] - m['inside'] - m['outside']) * inch
    hyph    = _pyphen.Pyphen(lang='en_US') if (preset['body'].get('hyphenate') and _HAVE_PYPHEN) else None

    def _make_doc(path):
        return BookDoc(path, preset, meta, head_font, cover=cover,
                       title=meta.get('title', ''), author=meta.get('author', ''))

    if meta.get('include_toc'):
        # Pass 1 — no TOC, just capture chapter positions
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        story1 = _build_story(manuscript, preset, meta, fonts, st, head_font,
                              has_cover=bool(cover), avail_w=avail_w, hyph=hyph)
        doc1 = _make_doc(tmp)
        doc1.build(story1)
        body_start = doc1._body_start or 1
        entries    = doc1._toc_entries
        try:
            os.remove(tmp)
        except OSError:
            pass

        # Estimate TOC page count, then rebuild TOC with adjusted folios
        toc_draft = _build_toc(entries, body_start, avail_w, preset, fonts, st)
        toc_pages = _estimate_toc_pages(toc_draft, preset)
        toc_final = _build_toc(entries, body_start, avail_w, preset, fonts, st,
                                folio_offset=toc_pages)

        # Pass 2 — with TOC injected
        story2 = _build_story(manuscript, preset, meta, fonts, st, head_font,
                               has_cover=bool(cover), avail_w=avail_w, hyph=hyph,
                               toc_flowables=toc_final)
        doc2 = _make_doc(out_path)
        doc2.build(story2)
        page_count = doc2.page
    else:
        story = _build_story(manuscript, preset, meta, fonts, st, head_font,
                             has_cover=bool(cover), avail_w=avail_w, hyph=hyph)
        doc = _make_doc(out_path)
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
