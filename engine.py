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

import matter as _matter
import ornaments as _orn
from manuscript import (_inline as _ms_inline, chapter_anchors as _ms_anchors,
                        chapter_numbers as _ms_numbers,
                        map_block_texts as _ms_map_texts,
                        CELL_SEP as _MS_CELL)
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    PageBreak, Flowable, NextPageTemplate, Table, TableStyle, KeepTogether,
)
from reportlab.platypus.paragraph import Paragraph as _P
from reportlab.lib import colors as _colors

try:
    from PIL import Image as PILImage, ImageOps
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
# Cover art assets (background images, emblems/logos). App points this at the
# writable data dir; falls back to the repo folder in dev.
COVER_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'covers', 'assets')
# Interior figures (~~~ figure src="…"). Same arrangement as the cover assets.
FIGURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures')


# ---------------------------------------------------------------- cover helpers
def _num(v, default=0.0):
    """Best-effort float, for optional numeric template fields."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _cover_asset_path(name):
    """Resolve a cover-asset filename against the asset dir, font dir, or abs path."""
    if not name:
        return None
    if os.path.isabs(name):
        return name
    for base in (COVER_ASSET_DIR, FONT_DIR):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return os.path.join(COVER_ASSET_DIR, name)   # default (may not exist yet)


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


# ---------------------------------------------------------------- cover panels
# The designed cover is drawn into an arbitrary rectangle so the same code paints
# a standalone front cover (page 1 of the interior) and the front panel of a full
# print wrap (back + spine + front + bleed).

def _pal_color(tpl, name):
    """Resolve a palette key (e.g. 'gold') or a literal hex to a Color."""
    pal = tpl.get('palette', {})
    v = pal.get(name, name)
    return _hex(v if isinstance(v, str) else '#000000')


def _paint_gradient(canv, pal, x, y, w, h):
    """Fill a rect with the vertical background gradient (solid base as a safety net)."""
    canv.saveState()
    canv.setFillColor(_hex(pal.get('bg_bottom', '#080d15')))
    canv.rect(x, y, w, h, stroke=0, fill=1)
    try:
        p = canv.beginPath()
        p.rect(x, y, w, h)
        canv.clipPath(p, stroke=0, fill=0)
        canv.linearGradient(x, y + h, x, y,
                            [_hex(pal.get('bg_top', '#101a29')),
                             _hex(pal.get('bg_bottom', '#080d15'))],
                            extend=True)
    except Exception:
        pass
    canv.restoreState()


# Layout archetypes: each supplies vertical fractions for the title cluster and
# the epigraph. 'centered' is empty so the template's own y-values (and the six
# shipped covers) are used verbatim — fully backward-compatible.
_COVER_LAYOUTS = {
    'centered': {},
    'top':    {'collection_top': 0.90, 'kicker': 0.865, 'title': 0.805, 'epigraph': 0.30},
    'bottom': {'collection_top': 0.90, 'kicker': 0.475, 'title': 0.415, 'epigraph': 0.82},
    'band':   {'collection_top': 0.90, 'kicker': 0.585, 'title': 0.525, 'epigraph': 0.30},
}


def _draw_image_cover(canv, path, x0, y0, w, h):
    """Draw an image cover-fit (fill then crop) into (x0,y0,w,h), clipped to the rect.
    Shared by the full-bleed background and the postcard family's inset panel."""
    try:
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(path)
        iw, ih = ir.getSize()
        scale = max(w / iw, h / ih) if iw and ih else 1.0
        dw, dh = iw * scale, ih * scale                  # cover-fit: fill then crop
        canv.saveState()
        p = canv.beginPath()
        p.rect(x0, y0, w, h)
        canv.clipPath(p, stroke=0, fill=0)
        canv.drawImage(ir, x0 + (w - dw) / 2.0, y0 + (h - dh) / 2.0,
                       width=dw, height=dh, mask='auto')
        canv.restoreState()
    except Exception:
        pass


def _paint_background(canv, tpl, x0, y0, w, h):
    """Optional full-bleed background inside (x0,y0,w,h): art image (cover-fit),
    edge vignette, then a flat colour overlay. Drawn over the base gradient and
    under the border + text, so the frame and type stay crisp on top of art."""
    bg = tpl.get('background', {})
    if not isinstance(bg, dict) or not bg:
        return
    img = bg.get('image', '')
    if isinstance(img, str) and img.strip():
        path = _cover_asset_path(img.strip())
        if path and os.path.exists(path):
            _draw_image_cover(canv, path, x0, y0, w, h)
    vig = _num(bg.get('vignette', 0))
    if vig > 0:
        _paint_vignette(canv, x0, y0, w, h, min(vig, 1.0))
    ov = bg.get('overlay', {})
    op = _num(ov.get('opacity', 0)) if isinstance(ov, dict) else 0.0
    if op > 0:
        canv.saveState()
        canv.setFillColor(_pal_color(tpl, ov.get('color', '#000000')))
        canv.setFillAlpha(min(op, 1.0))
        canv.rect(x0, y0, w, h, stroke=0, fill=1)
        canv.setFillAlpha(1.0)
        canv.restoreState()


def _paint_vignette(canv, x0, y0, w, h, strength):
    """Soft edge-darkening: concentric translucent frame bands, darker at the edge.
    Each band is four non-overlapping strips, so alpha never double-composites."""
    rings = 10
    canv.saveState()
    canv.setFillColorRGB(0, 0, 0)
    for i in range(rings):
        ta = i / float(rings)                            # 0 outer .. ->1 centre
        tb = (i + 1) / float(rings)
        alpha = strength * 0.13 * (1.0 - ta)             # outer bands darker
        if alpha <= 0.002:
            continue
        ax, ay = (w * 0.5) * ta, (h * 0.5) * ta
        bx, by = (w * 0.5) * tb, (h * 0.5) * tb
        canv.setFillAlpha(alpha)
        canv.rect(x0 + ax, y0 + ay, bx - ax, h - 2 * ay, stroke=0, fill=1)          # left
        canv.rect(x0 + w - bx, y0 + ay, bx - ax, h - 2 * ay, stroke=0, fill=1)      # right
        canv.rect(x0 + bx, y0 + h - by, w - 2 * bx, by - ay, stroke=0, fill=1)      # top
        canv.rect(x0 + bx, y0 + ay, w - 2 * bx, by - ay, stroke=0, fill=1)          # bottom
    canv.setFillAlpha(1.0)
    canv.restoreState()


def _paint_title_panel(canv, tpl, x0, y0, w, h):
    """Translucent panel behind the title cluster (layout 'band' / explicit 'panel').
    Keeps the title legible over background art regardless of the art's tones."""
    pn = tpl.get('panel', {})
    pn = pn if isinstance(pn, dict) else {}
    top = _num(pn.get('top', 0.66), 0.66)
    bot = _num(pn.get('bottom', 0.34), 0.34)
    opacity = _num(pn.get('opacity', 0.55), 0.55)
    b = tpl.get('border', {})
    inset = b.get('inset', 0.42) * inch
    gap = b.get('gap', 0.055) * inch
    px0 = x0 + inset + gap * 2
    px1 = x0 + w - inset - gap * 2
    py0 = y0 + h * min(top, bot)
    py1 = y0 + h * max(top, bot)
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, pn.get('color', 'bg_bottom')))
    canv.setFillAlpha(min(max(opacity, 0.0), 1.0))
    canv.rect(px0, py0, px1 - px0, py1 - py0, stroke=0, fill=1)
    canv.setFillAlpha(1.0)
    canv.restoreState()


def _slot_xy(slot, x0, y0, w, h, tw, th, margin):
    """Lower-left corner for an emblem of size (tw,th) at a named slot."""
    slot = (slot or 'top-center').lower()
    if 'left' in slot:
        x = x0 + margin
    elif 'right' in slot:
        x = x0 + w - margin - tw
    else:
        x = x0 + (w - tw) / 2.0
    if 'top' in slot:
        y = y0 + h - margin - th
    elif 'bottom' in slot:
        y = y0 + margin
    else:
        y = y0 + (h - th) / 2.0
    return x, y


def _paint_emblems(canv, tpl, x0, y0, w, h):
    """Positioned image slots (logo, series badge, author mark) — fixed slots, not
    freeform placement. Drawn on top of the panel so a small mark reads clearly."""
    ems = tpl.get('emblems', [])
    if not isinstance(ems, list):
        return
    b = tpl.get('border', {})
    margin = (b.get('inset', 0.42) + 0.14) * inch
    from reportlab.lib.utils import ImageReader
    for em in ems:
        if not isinstance(em, dict):
            continue
        name = (em.get('image') or '').strip()
        if not name:
            continue
        path = _cover_asset_path(name)
        if not path or not os.path.exists(path):
            continue
        try:
            ir = ImageReader(path)
            iw, ih = ir.getSize()
            tw = max(_num(em.get('w', 0.7), 0.7), 0.1) * inch
            th = tw * (ih / iw) if iw else tw
            fx, fy = _slot_xy(em.get('slot'), x0, y0, w, h, tw, th, margin)
            canv.drawImage(ir, fx, fy, width=tw, height=th,
                           preserveAspectRatio=True, mask='auto')
        except Exception:
            pass


def _paint_border(canv, tpl, x0, y0, w, h):
    """Double rule + outward corner brackets inset into (x0,y0,w,h). Returns inner box."""
    b = tpl.get('border', {})
    inset = b.get('inset', 0.42) * inch
    gap = b.get('gap', 0.055) * inch
    gold = _pal_color(tpl, b.get('color', 'gold'))
    bx0, by0, bx1, by1 = x0 + inset, y0 + inset, x0 + w - inset, y0 + h - inset
    canv.saveState()
    canv.setStrokeColor(gold)
    canv.setLineWidth(b.get('line', 1.0))
    canv.rect(bx0, by0, bx1 - bx0, by1 - by0, stroke=1, fill=0)
    canv.rect(bx0 + gap, by0 + gap, (bx1 - bx0) - 2 * gap, (by1 - by0) - 2 * gap,
              stroke=1, fill=0)
    bl = b.get('corner', 0.5) * inch
    bo = gap * 1.6
    canv.setLineWidth(b.get('corner_line', 1.3))
    for (px, py, sx, sy) in ((bx0, by0, 1, 1), (bx1, by0, -1, 1),
                             (bx0, by1, 1, -1), (bx1, by1, -1, -1)):
        ox, oy = px - sx * bo, py - sy * bo
        canv.line(ox, oy, ox + sx * bl, oy)
        canv.line(ox, oy, ox, oy + sy * bl)
    canv.restoreState()
    return bx0, by0, bx1, by1, gap


def _paint_cover_panel(canv, tpl, cf, meta, x0, y0, w, h):
    """The full designed front cover, drawn inside (x0,y0,w,h)."""
    cx = x0 + w / 2.0
    canv.saveState()
    bx0, by0, bx1, by1, gap = _paint_border(canv, tpl, x0, y0, w, h)
    inner_w = (bx1 - bx0) - 2 * gap

    # layout archetype: supplies vertical fractions for the title cluster; an
    # empty dict ('centered') defers to the template's own y-values.
    layname = tpl.get('layout', 'centered')
    lay = _COVER_LAYOUTS.get(layname, {})

    # translucent title panel: implicit for the 'band' archetype, else opt-in
    pn = tpl.get('panel')
    if layname == 'band' or (isinstance(pn, dict) and pn.get('enabled')):
        _paint_title_panel(canv, tpl, x0, y0, w, h)

    def yat(frac):
        return y0 + h * frac

    # collection line (top)
    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, cc.get('color', 'gold')))
        _tracked_centre(canv, cx, yat(lay.get('collection_top', cc.get('top', 0.70))), coll,
                        cf['serif'], cc.get('size', 12.5), cc.get('tracking', 3.4))

    # kicker (italic)
    kk = tpl.get('kicker', {})
    kick = meta.get('cover_kicker', '')
    if kick:
        canv.setFillColor(_pal_color(tpl, kk.get('color', 'muted')))
        _tracked_centre(canv, cx, yat(lay.get('kicker', kk.get('y', 0.665))), kick,
                        cf['italic'], kk.get('size', 11), kk.get('tracking', 0.4))

    # title — wrapped, letterspaced, shrink-to-fit
    tt = tpl.get('title', {})
    title_y = lay.get('title', tt.get('y', 0.585))
    title = (meta.get('title') or '').upper()
    last_y = yat(title_y)
    tsize = tt.get('size', 40)
    if title:
        maxw = inner_w - 0.4 * inch
        trk = tt.get('tracking', 0.6)
        lines = _wrap_tracked(title, cf['display'], tsize, maxw, trk)
        while tsize > 14 and any(
                stringWidth(ln, cf['display'], tsize) + trk * max(len(ln) - 1, 0) > maxw
                for ln in lines):
            tsize -= 1
            lines = _wrap_tracked(title, cf['display'], tsize, maxw, trk)
        leading = tt.get('leading', 46) * (tsize / tt.get('size', 40))
        canv.setFillColor(_pal_color(tpl, tt.get('color', 'gold')))
        yy = yat(title_y)
        for ln in lines:
            _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
            last_y = yy
            yy -= leading

    # accent line (author) — cleared below the title
    ac = tpl.get('accent', {})
    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        asize = ac.get('size', 21)
        clearance = tsize * 0.42 + asize * 0.55 + ac.get('gap', 0.008) * h
        last_y = last_y - clearance
        canv.setFillColor(_pal_color(tpl, ac.get('color', 'teal')))
        _tracked_centre(canv, cx, last_y, accent, cf['display'],
                        asize, ac.get('tracking', 1.4))

    # ornament
    orn = tpl.get('ornament', {})
    oy = last_y - orn.get('gap', 0.05) * h
    ocol = _pal_color(tpl, orn.get('color', 'gold'))
    canv.setFillColor(ocol)
    canv.setStrokeColor(ocol)
    r = orn.get('size', 2.4)
    sp = orn.get('spacing', 9)
    for i, dx in enumerate((-sp, 0, sp)):
        _diamond(canv, cx + dx, oy, r * (1.25 if i == 1 else 1.0))
    rl = orn.get('rule_len', 0.8) * inch
    if orn.get('rule', 0.8):
        canv.setLineWidth(orn.get('rule', 0.8))
        inn = sp + r + 7
        canv.line(cx - inn - rl, oy, cx - inn, oy)
        canv.line(cx + inn, oy, cx + inn + rl, oy)

    # epigraph
    ep = tpl.get('epigraph', {})
    epi = meta.get('cover_epigraph') or meta.get('epigraph') or ''
    if epi:
        ew = (bx1 - bx0) * ep.get('width', 0.62)
        lines = _wrap_tracked(epi, cf['italic'], ep.get('size', 10.5),
                              ew, ep.get('tracking', 0.2))
        canv.setFillColor(_pal_color(tpl, ep.get('color', 'muted')))
        yy = yat(lay.get('epigraph', ep.get('top', 0.375)))
        for ln in lines:
            _tracked_centre(canv, cx, yy, ln, cf['italic'],
                            ep.get('size', 10.5), ep.get('tracking', 0.2))
            yy -= ep.get('leading', 15)

    # collection (bottom) + studio footer
    if coll:
        canv.setFillColor(_pal_color(tpl, cc.get('color', 'gold')))
        _tracked_centre(canv, cx, yat(cc.get('bottom', 0.115)), coll,
                        cf['serif'], cc.get('size', 12.5) * 0.82, cc.get('tracking', 3.4))
    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, st.get('color', 'muted')))
        _tracked_centre(canv, cx, yat(st.get('y', 0.088)), studio,
                        cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    # positioned emblem/logo slots (on top of everything)
    _paint_emblems(canv, tpl, x0, y0, w, h)
    canv.restoreState()


# ---------------------------------------------------------------- cover design families
# A cover's optional `design` key selects a complete front-cover renderer. Absent ->
# the classic ornamented frame (`_paint_cover_panel`), so the six shipped covers — which
# set no `design` — render byte-identically. Each family draws into (x0,y0,w,h), the same
# rect contract as the classic panel, so both the standalone page-1 cover and the print
# wrap's front panel dispatch through one entry point (`_paint_cover_front`). This is a
# small, curated set of opinionated layouts — NOT a freeform canvas (ROADMAP strategy note).

def _paint_bottom_scrim(canv, x0, y0, w, h, color, height_frac=0.55, max_alpha=0.82):
    """Foot-anchored darkening gradient so type stays legible over full-bleed art:
    stacked non-overlapping horizontal strips, densest at the foot, fading to clear.
    Non-overlapping so alpha never double-composites (same trick as _paint_vignette)."""
    bands = 26
    sh = h * min(max(height_frac, 0.0), 1.0)
    canv.saveState()
    canv.setFillColor(color)
    for i in range(bands):
        t = i / float(bands)                     # 0 at the foot .. ->1 at the band's top
        a = max_alpha * (1.0 - t) ** 1.7
        if a <= 0.003:
            continue
        canv.setFillAlpha(min(a, 1.0))
        canv.rect(x0, y0 + sh * t, w, sh / bands + 0.5, stroke=0, fill=1)
    canv.setFillAlpha(1.0)
    canv.restoreState()


def _design_photographic(canv, tpl, cf, meta, x0, y0, w, h):
    """Full-bleed photographic cover: the background art (set via `background.image` and
    painted before dispatch) fills the panel; a soft foot scrim carries a large lower-
    anchored title, an author line over a short rule, a top series line, and a studio
    footer. A genuinely different family from the ornamented frame — no border, no diamond
    ornament, type driven low over the image. Fine-tuning lives in an optional `photo` dict."""
    ph = tpl.get('photo', {})
    ph = ph if isinstance(ph, dict) else {}
    cx = x0 + w / 2.0
    ink = _pal_color(tpl, ph.get('ink', 'ink'))

    # foot scrim (set photo.scrim_opacity = 0 to skip it for already-dark art)
    sop = _num(ph.get('scrim_opacity', 0.82), 0.82)
    if sop > 0:
        _paint_bottom_scrim(canv, x0, y0, w, h,
                            _pal_color(tpl, ph.get('scrim', 'bg_bottom')),
                            _num(ph.get('scrim_height', 0.55), 0.55), min(sop, 1.0))

    inner_w = w - 0.9 * inch

    # series / collection line, near the top
    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, ph.get('collection_color', 'ink')))
        _tracked_centre(canv, cx, y0 + h * _num(ph.get('collection_y', 0.90), 0.90), coll,
                        cf['serif'], cc.get('size', 12.5), cc.get('tracking', 3.4))

    # title — large, anchored in the lower third, shrink-to-fit, growing downward
    tt = tpl.get('title', {})
    title = (meta.get('title') or '').upper()
    title_y = y0 + h * _num(ph.get('title_y', 0.30), 0.30)
    tsize = _num(ph.get('title_size', 52), 52)
    trk = _num(tt.get('tracking', 1.0), 1.0)
    last_y = title_y
    if title:
        lines = _wrap_tracked(title, cf['display'], tsize, inner_w, trk)
        while tsize > 16 and any(
                stringWidth(ln, cf['display'], tsize) + trk * max(len(ln) - 1, 0) > inner_w
                for ln in lines):
            tsize -= 1
            lines = _wrap_tracked(title, cf['display'], tsize, inner_w, trk)
        leading = tsize * _num(ph.get('title_leading', 1.08), 1.08)
        canv.setFillColor(_pal_color(tpl, ph.get('title_color', 'ink')))
        yy = title_y
        for ln in lines:
            _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
            last_y = yy
            yy -= leading

    # author line over a short centred rule
    ac = tpl.get('accent', {})
    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        asize = _num(ph.get('author_size', 18), 18)
        last_y = last_y - (tsize * 0.42 + asize * 1.1)
        if ph.get('rule', True):
            rl = w * _num(ph.get('rule_len', 0.11), 0.11)
            canv.setStrokeColor(ink)
            canv.setLineWidth(_num(ph.get('rule_line', 1.0), 1.0))
            ry = last_y + asize * 1.28
            canv.line(cx - rl, ry, cx + rl, ry)
        canv.setFillColor(_pal_color(tpl, ph.get('author_color', 'ink')))
        _tracked_centre(canv, cx, last_y, accent, cf['display'], asize,
                        _num(ac.get('tracking', 2.0), 2.0))

    # studio footer
    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, ph.get('studio_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(st.get('y', 0.06), 0.06), studio,
                        cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    # positioned emblem/logo slots (on top of everything)
    _paint_emblems(canv, tpl, x0, y0, w, h)


def _tracked_left(canv, x, y, text, font, size, tracking=0.0):
    """Draw letterspaced text left-aligned from x at baseline y."""
    if not text:
        return
    to = canv.beginText(x, y)
    to.setFont(font, size)
    to.setCharSpace(tracking)
    to.textOut(text)
    canv.drawText(to)


def _fit_title_lines(text, font, size, max_w, tracking, min_size=16):
    """Word-wrap an uppercase display title and shrink-to-fit within max_w.
    Returns (lines, size). Shared by the type-forward design families."""
    if not text:
        return [], size
    lines = _wrap_tracked(text, font, size, max_w, tracking)
    while size > min_size and any(
            stringWidth(ln, font, size) + tracking * max(len(ln) - 1, 0) > max_w
            for ln in lines):
        size -= 1
        lines = _wrap_tracked(text, font, size, max_w, tracking)
    return lines, size


def _design_typographic(canv, tpl, cf, meta, x0, y0, w, h):
    """The title IS the cover: an oversized left-aligned display title filling the upper
    page, a heavy accent rule, a tagline, and author + series in tracked caps. No frame,
    no ornament, no art — pure type. Tuned via an optional `typo` dict."""
    ty = tpl.get('typo', {})
    ty = ty if isinstance(ty, dict) else {}
    margin = _num(ty.get('margin', 0.9), 0.9) * inch
    lx = x0 + margin
    inner_w = w - 2 * margin
    ink = _pal_color(tpl, ty.get('ink', 'ink'))

    # series line, top
    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(ink)
        _tracked_left(canv, lx, y0 + h * _num(ty.get('series_y', 0.90), 0.90), coll,
                      cf['serif'], cc.get('size', 12), cc.get('tracking', 3.2))

    # giant title, left-aligned, grown to fill the width, anchored high
    title = (meta.get('title') or '').upper()
    tt = tpl.get('title', {})
    trk = _num(ty.get('title_tracking', tt.get('tracking', 0.5)), 0.5)
    lines, tsize = _fit_title_lines(title, cf['display'], _num(ty.get('title_size', 96), 96),
                                    inner_w, trk, min_size=22)
    leading = tsize * _num(ty.get('title_leading', 0.98), 0.98)
    canv.setFillColor(_pal_color(tpl, ty.get('title_color', 'gold')))
    yy = y0 + h * _num(ty.get('title_top', 0.74), 0.74)
    last_y = yy
    for ln in lines:
        _tracked_left(canv, lx, yy, ln, cf['display'], tsize, trk)
        last_y = yy
        yy -= leading

    # heavy accent rule under the title
    ruley = last_y - tsize * 0.42
    canv.setStrokeColor(_pal_color(tpl, ty.get('rule_color', 'gold')))
    canv.setLineWidth(_num(ty.get('rule_line', 3.0), 3.0))
    canv.line(lx, ruley, lx + inner_w * _num(ty.get('rule_len', 0.5), 0.5), ruley)

    # tagline (kicker) under the rule
    kk = tpl.get('kicker', {})
    kick = meta.get('cover_kicker') or ''
    if kick:
        canv.setFillColor(_pal_color(tpl, ty.get('kicker_color', 'muted')))
        ksz = kk.get('size', 13)
        ky = ruley - _num(ty.get('kicker_gap', 30), 30)
        for ln in _wrap_tracked(kick, cf['italic'], ksz, inner_w, 0.2):
            _tracked_left(canv, lx, ky, ln, cf['italic'], ksz, 0.2)
            ky -= kk.get('leading', 18)

    # author near the foot, left-aligned
    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        canv.setFillColor(ink)
        _tracked_left(canv, lx, y0 + h * _num(ty.get('author_y', 0.10), 0.10), accent,
                      cf['display'], _num(ty.get('author_size', 20), 20),
                      _num(ac.get('tracking', 2.0), 2.0))

    # studio, very bottom
    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, ty.get('studio_color', 'muted')))
        _tracked_left(canv, lx, y0 + h * _num(ty.get('studio_y', 0.055), 0.055), studio,
                      cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    _paint_emblems(canv, tpl, x0, y0, w, h)


def _design_geometric(canv, tpl, cf, meta, x0, y0, w, h):
    """Flat colour-blocked modern cover: a solid ground with a bold horizontal band
    carrying the title reversed out of it; series above, author below. No gradient, no
    frame — geometric flat colour. Tuned via an optional `blocks` dict."""
    bl = tpl.get('blocks', {})
    bl = bl if isinstance(bl, dict) else {}
    cx = x0 + w / 2.0

    # flat ground (overpaint the gradient so the cover reads as flat colour)
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, bl.get('ground', 'bg_bottom')))
    canv.rect(x0, y0, w, h, stroke=0, fill=1)
    canv.restoreState()

    # bold title band
    band_mid = _num(bl.get('band_y', 0.5), 0.5)
    band_h = h * _num(bl.get('band_height', 0.26), 0.26)
    by0 = y0 + h * band_mid - band_h / 2.0
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, bl.get('band', 'gold')))
    canv.rect(x0, by0, w, band_h, stroke=0, fill=1)
    canv.restoreState()

    inner_w = w - 1.1 * inch
    # title reversed inside the band, vertically centred
    title = (meta.get('title') or '').upper()
    tt = tpl.get('title', {})
    trk = _num(tt.get('tracking', 0.8), 0.8)
    lines, tsize = _fit_title_lines(title, cf['display'], _num(bl.get('title_size', 40), 40),
                                    inner_w, trk, min_size=16)
    leading = tsize * 1.06
    yy = y0 + h * band_mid + leading * max(len(lines) - 1, 0) / 2.0 - tsize * 0.34
    canv.setFillColor(_pal_color(tpl, bl.get('title_color', 'ink')))
    for ln in lines:
        _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
        yy -= leading

    # series above the band
    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, bl.get('series_color', 'ink')))
        _tracked_centre(canv, cx, by0 + band_h + h * _num(bl.get('series_gap', 0.08), 0.08),
                        coll, cf['serif'], cc.get('size', 12.5), cc.get('tracking', 3.4))

    # author below the band
    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        canv.setFillColor(_pal_color(tpl, bl.get('author_color', 'ink')))
        _tracked_centre(canv, cx, by0 - h * _num(bl.get('author_gap', 0.09), 0.09), accent,
                        cf['display'], _num(bl.get('author_size', 18), 18),
                        _num(ac.get('tracking', 2.0), 2.0))

    # studio at the foot
    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, bl.get('studio_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(st.get('y', 0.06), 0.06), studio,
                        cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    _paint_emblems(canv, tpl, x0, y0, w, h)


def _design_vintage(canv, tpl, cf, meta, x0, y0, w, h):
    """Vintage paperback: a top-anchored title bracketed by double rules, an italic
    tagline, and a filled author band across the foot with the author reversed. A
    heavier, older look. Tuned via an optional `vintage` dict."""
    vg = tpl.get('vintage', {})
    vg = vg if isinstance(vg, dict) else {}
    cx = x0 + w / 2.0
    inner_w = w - 1.2 * inch
    gold = _pal_color(tpl, vg.get('rule_color', 'gold'))

    def drule(yy):
        canv.setStrokeColor(gold)
        rl = inner_w * _num(vg.get('rule_len', 0.86), 0.86)
        canv.setLineWidth(_num(vg.get('rule_line', 2.2), 2.2))
        canv.line(cx - rl / 2, yy, cx + rl / 2, yy)
        canv.setLineWidth(_num(vg.get('rule_line2', 0.9), 0.9))
        canv.line(cx - rl / 2, yy - 4.5, cx + rl / 2, yy - 4.5)

    # series line at the very top
    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, vg.get('series_color', 'gold')))
        _tracked_centre(canv, cx, y0 + h * _num(vg.get('series_y', 0.925), 0.925), coll,
                        cf['serif'], cc.get('size', 12), cc.get('tracking', 3.6))

    drule(y0 + h * _num(vg.get('top_rule_y', 0.855), 0.855))

    # title, top third
    title = (meta.get('title') or '').upper()
    tt = tpl.get('title', {})
    trk = _num(tt.get('tracking', 0.6), 0.6)
    lines, tsize = _fit_title_lines(title, cf['display'], _num(vg.get('title_size', 46), 46),
                                    inner_w, trk, min_size=18)
    leading = tsize * _num(vg.get('title_leading', 1.05), 1.05)
    yy = y0 + h * _num(vg.get('title_y', 0.77), 0.77)
    canv.setFillColor(_pal_color(tpl, vg.get('title_color', 'ink')))
    last_y = yy
    for ln in lines:
        _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
        last_y = yy
        yy -= leading

    drule(last_y - tsize * 0.5)

    # italic tagline in the mid
    kk = tpl.get('kicker', {})
    tag = meta.get('cover_kicker') or meta.get('cover_epigraph') or meta.get('epigraph') or ''
    if tag:
        canv.setFillColor(_pal_color(tpl, vg.get('tagline_color', 'muted')))
        tsz = kk.get('size', 13)
        tgy = y0 + h * _num(vg.get('tagline_y', 0.46), 0.46)
        for ln in _wrap_tracked(tag, cf['italic'], tsz, inner_w * 0.8, 0.2):
            _tracked_centre(canv, cx, tgy, ln, cf['italic'], tsz, 0.2)
            tgy -= kk.get('leading', 18)

    # filled author band across the foot, author reversed
    band_h = h * _num(vg.get('band_height', 0.12), 0.12)
    by0 = y0 + h * _num(vg.get('band_y', 0.06), 0.06)
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, vg.get('band', 'gold')))
    canv.rect(x0 + 0.5 * inch, by0, w - 1.0 * inch, band_h, stroke=0, fill=1)
    canv.restoreState()
    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        asz = _num(vg.get('author_size', 17), 17)
        canv.setFillColor(_pal_color(tpl, vg.get('author_color', 'bg_bottom')))
        _tracked_centre(canv, cx, by0 + band_h / 2 - asz * 0.34, accent,
                        cf['display'], asz, _num(ac.get('tracking', 2.2), 2.2))

    _paint_emblems(canv, tpl, x0, y0, w, h)


def _design_minimal(canv, tpl, cf, meta, x0, y0, w, h):
    """Quiet, upscale minimalism: a modest tracked serif title high-centre over lots of
    whitespace, a short hairline rule, small-caps series + author. No frame, no ornament.
    Uses whatever ground the palette gradient supplies. Tuned via an optional `minimal` dict."""
    mn = tpl.get('minimal', {})
    mn = mn if isinstance(mn, dict) else {}
    cx = x0 + w / 2.0
    inner_w = w - 1.6 * inch
    ink = _pal_color(tpl, mn.get('ink', 'ink'))

    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, mn.get('series_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(mn.get('series_y', 0.82), 0.82), coll,
                        cf['serif'], cc.get('size', 10.5), cc.get('tracking', 4.0))

    title = (meta.get('title') or '').upper()
    trk = _num(mn.get('title_tracking', 2.0), 2.0)
    lines, tsize = _fit_title_lines(title, cf['serif'], _num(mn.get('title_size', 30), 30),
                                    inner_w, trk, min_size=14)
    leading = tsize * _num(mn.get('title_leading', 1.35), 1.35)
    canv.setFillColor(_pal_color(tpl, mn.get('title_color', 'ink')))
    yy = y0 + h * _num(mn.get('title_y', 0.60), 0.60)
    last_y = yy
    for ln in lines:
        _tracked_centre(canv, cx, yy, ln, cf['serif'], tsize, trk)
        last_y = yy
        yy -= leading

    ry = last_y - tsize * 0.95
    canv.setStrokeColor(ink)
    canv.setLineWidth(_num(mn.get('rule_line', 0.7), 0.7))
    rl = w * _num(mn.get('rule_len', 0.09), 0.09)
    canv.line(cx - rl, ry, cx + rl, ry)

    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        canv.setFillColor(_pal_color(tpl, mn.get('author_color', 'muted')))
        _tracked_centre(canv, cx, ry - _num(mn.get('author_gap', 26), 26), accent,
                        cf['serif'], _num(mn.get('author_size', 12), 12),
                        _num(ac.get('tracking', 3.0), 3.0))

    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, mn.get('studio_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(st.get('y', 0.06), 0.06), studio,
                        cf['serif'], st.get('size', 8), st.get('tracking', 2.4))

    _paint_emblems(canv, tpl, x0, y0, w, h)


def _design_stripe(canv, tpl, cf, meta, x0, y0, w, h):
    """Editorial asymmetry: a full-height colour band down one side, with a large
    left-aligned title, series, and author set in the open field beside it. Flat colour
    (overpaints the gradient). Tuned via an optional `stripe` dict."""
    sp = tpl.get('stripe', {})
    sp = sp if isinstance(sp, dict) else {}
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, sp.get('ground', 'bg_bottom')))
    canv.rect(x0, y0, w, h, stroke=0, fill=1)
    canv.restoreState()

    band_w = w * _num(sp.get('band_width', 0.34), 0.34)
    side = sp.get('side', 'left')
    bx = x0 if side == 'left' else x0 + w - band_w
    canv.saveState()
    canv.setFillColor(_pal_color(tpl, sp.get('band', 'gold')))
    canv.rect(bx, y0, band_w, h, stroke=0, fill=1)
    canv.restoreState()

    tx0 = (x0 + band_w + 0.4 * inch) if side == 'left' else (x0 + 0.4 * inch)
    tw = w - band_w - 0.8 * inch

    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, sp.get('series_color', 'muted')))
        _tracked_left(canv, tx0, y0 + h * _num(sp.get('series_y', 0.88), 0.88), coll,
                      cf['serif'], cc.get('size', 11), cc.get('tracking', 3.0))

    title = (meta.get('title') or '').upper()
    tt = tpl.get('title', {})
    trk = _num(sp.get('title_tracking', tt.get('tracking', 0.5)), 0.5)
    lines, tsize = _fit_title_lines(title, cf['display'], _num(sp.get('title_size', 44), 44),
                                    tw, trk, min_size=18)
    leading = tsize * _num(sp.get('title_leading', 1.04), 1.04)
    canv.setFillColor(_pal_color(tpl, sp.get('title_color', 'ink')))
    yy = y0 + h * _num(sp.get('title_y', 0.60), 0.60)
    last_y = yy
    for ln in lines:
        _tracked_left(canv, tx0, yy, ln, cf['display'], tsize, trk)
        last_y = yy
        yy -= leading

    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        canv.setFillColor(_pal_color(tpl, sp.get('author_color', 'muted')))
        _tracked_left(canv, tx0, last_y - _num(sp.get('author_gap', 34), 34), accent,
                      cf['display'], _num(sp.get('author_size', 15), 15),
                      _num(ac.get('tracking', 2.0), 2.0))

    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, sp.get('studio_color', 'muted')))
        _tracked_left(canv, tx0, y0 + h * _num(st.get('y', 0.06), 0.06), studio,
                      cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    _paint_emblems(canv, tpl, x0, y0, w, h)


def _design_postcard(canv, tpl, cf, meta, x0, y0, w, h):
    """A framed-photo look: cover art (from `background.image`) sits in an inset mat +
    frame in the upper cover, with the title, series, and author on the flat ground below.
    An alternative to full-bleed for uploaded art. Tuned via an optional `postcard` dict."""
    pc = tpl.get('postcard', {})
    pc = pc if isinstance(pc, dict) else {}
    cx = x0 + w / 2.0

    canv.saveState()                                     # flat ground over the full-bleed art
    canv.setFillColor(_pal_color(tpl, pc.get('ground', 'bg_bottom')))
    canv.rect(x0, y0, w, h, stroke=0, fill=1)
    canv.restoreState()

    margin = _num(pc.get('margin', 0.7), 0.7) * inch
    px0, px1 = x0 + margin, x0 + w - margin
    py0 = y0 + h * _num(pc.get('panel_bottom', 0.42), 0.42)
    py1 = y0 + h * _num(pc.get('panel_top', 0.92), 0.92)
    pw_, ph_ = px1 - px0, py1 - py0
    canv.saveState()                                     # mat
    canv.setFillColor(_pal_color(tpl, pc.get('mat', 'muted')))
    canv.rect(px0, py0, pw_, ph_, stroke=0, fill=1)
    canv.restoreState()

    matb = _num(pc.get('mat_border', 0.12), 0.12) * inch
    ix0, iy0, iw_, ih_ = px0 + matb, py0 + matb, pw_ - 2 * matb, ph_ - 2 * matb
    bg = tpl.get('background', {})
    img = (bg.get('image') or '').strip() if isinstance(bg, dict) else ''
    path = _cover_asset_path(img) if img else None
    if path and os.path.exists(path):
        _draw_image_cover(canv, path, ix0, iy0, iw_, ih_)
    else:                                                # placeholder art field
        canv.saveState()
        canv.setFillColor(_pal_color(tpl, pc.get('placeholder', 'bg_top')))
        canv.rect(ix0, iy0, iw_, ih_, stroke=0, fill=1)
        canv.restoreState()
    canv.saveState()                                     # thin frame around the panel
    canv.setStrokeColor(_pal_color(tpl, pc.get('frame', 'ink')))
    canv.setLineWidth(_num(pc.get('frame_line', 1.0), 1.0))
    canv.rect(px0, py0, pw_, ph_, stroke=1, fill=0)
    canv.restoreState()

    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, pc.get('series_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(pc.get('series_y', 0.365), 0.365), coll,
                        cf['serif'], cc.get('size', 11), cc.get('tracking', 3.4))

    inner_w = w - 1.4 * inch
    title = (meta.get('title') or '').upper()
    tt = tpl.get('title', {})
    trk = _num(pc.get('title_tracking', tt.get('tracking', 0.8)), 0.8)
    lines, tsize = _fit_title_lines(title, cf['display'], _num(pc.get('title_size', 30), 30),
                                    inner_w, trk, min_size=14)
    leading = tsize * 1.08
    canv.setFillColor(_pal_color(tpl, pc.get('title_color', 'ink')))
    yy = y0 + h * _num(pc.get('title_y', 0.29), 0.29)
    last_y = yy
    for ln in lines:
        _tracked_centre(canv, cx, yy, ln, cf['display'], tsize, trk)
        last_y = yy
        yy -= leading

    accent = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if accent:
        ac = tpl.get('accent', {})
        canv.setFillColor(_pal_color(tpl, pc.get('author_color', 'muted')))
        _tracked_centre(canv, cx, last_y - _num(pc.get('author_gap', 28), 28), accent,
                        cf['display'], _num(pc.get('author_size', 15), 15),
                        _num(ac.get('tracking', 2.0), 2.0))

    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, pc.get('studio_color', 'muted')))
        _tracked_centre(canv, cx, y0 + h * _num(st.get('y', 0.06), 0.06), studio,
                        cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))

    _paint_emblems(canv, tpl, x0, y0, w, h)


# design-family registry + dispatch (all renderers are defined above)
_COVER_DESIGNS = {
    'classic-frame': _paint_cover_panel,
    'photographic':  _design_photographic,
    'typographic':   _design_typographic,
    'geometric':     _design_geometric,
    'vintage':       _design_vintage,
    'minimal':       _design_minimal,
    'stripe':        _design_stripe,
    'postcard':      _design_postcard,
}


def _paint_cover_front(canv, tpl, cf, meta, x0, y0, w, h):
    """Dispatch to the template's cover design family (default 'classic-frame')."""
    fn = _COVER_DESIGNS.get(tpl.get('design') or 'classic-frame', _paint_cover_panel)
    fn(canv, tpl, cf, meta, x0, y0, w, h)


def _paint_back_panel(canv, tpl, cf, meta, x0, y0, w, h):
    """Back cover: border, collection line, blurb, studio footer, and a barcode zone."""
    cx = x0 + w / 2.0
    canv.saveState()
    bx0, by0, bx1, by1, gap = _paint_border(canv, tpl, x0, y0, w, h)

    def yat(frac):
        return y0 + h * frac

    cc = tpl.get('collection', {})
    coll = (meta.get('cover_collection') or '').upper()
    if coll:
        canv.setFillColor(_pal_color(tpl, cc.get('color', 'gold')))
        _tracked_centre(canv, cx, yat(0.86), coll,
                        cf['serif'], cc.get('size', 12.5) * 0.85, cc.get('tracking', 3.4))

    # blurb — centred serif block in the upper-middle
    blurb = meta.get('cover_blurb') or ''
    if blurb:
        size = 11.0
        lead = 16.0
        colw = (bx1 - bx0) * 0.82
        canv.setFillColor(_pal_color(tpl, 'ink'))
        yy = yat(0.72)
        for para in blurb.split('\n'):
            if not para.strip():
                yy -= lead * 0.6
                continue
            for ln in _wrap_tracked(para, cf['serif'], size, colw, 0.0):
                _tracked_centre(canv, cx, yy, ln, cf['serif'], size, 0.0)
                yy -= lead

    # optional author photo / publisher logo — centred, aspect preserved
    bimg = meta.get('cover_back_image')
    if bimg and os.path.exists(bimg):
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(bimg)
            iw, ih = ir.getSize()
            tw = max(meta.get('cover_back_image_w', 1.5), 0.25) * inch
            tw = min(tw, (bx1 - bx0) - 2 * gap)          # keep inside the frame
            thh = tw * (ih / iw) if iw else tw
            icx = cx
            icy = y0 + h * min(max(meta.get('cover_back_image_y', 0.4), 0.0), 1.0)
            canv.drawImage(ir, icx - tw / 2.0, icy - thh / 2.0, width=tw, height=thh,
                           preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # barcode reserve zone — white box, lower-right, KDP-style ~2.0" x 1.2"
    bw, bh = 2.0 * inch, 1.2 * inch
    bxr = bx1 - gap - bw
    byr = by0 + gap + 0.15 * inch
    canv.setFillColorRGB(1, 1, 1)
    canv.setStrokeGray(0.6)
    canv.setLineWidth(0.6)
    canv.rect(bxr, byr, bw, bh, stroke=1, fill=1)
    canv.setFillGray(0.55)
    canv.setFont(cf['serif'], 7.5)
    canv.drawCentredString(bxr + bw / 2.0, byr + bh / 2.0 - 2, 'ISBN / barcode area')

    # studio footer — centred in the space to the LEFT of the barcode so they never collide
    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        foot_cx = (bx0 + gap + (bxr - 0.12 * inch)) / 2.0
        canv.setFillColor(_pal_color(tpl, st.get('color', 'muted')))
        _tracked_centre(canv, foot_cx, byr + bh / 2.0 - st.get('size', 8.5) * 0.35, studio,
                        cf['serif'], st.get('size', 8.5), st.get('tracking', 2.4))
    canv.restoreState()


def _paint_flap(canv, tpl, cf, meta, x0, y0, w, h, side):
    """A dust-jacket flap: the front one sells the book, the back one the author.

    A flap is a tall, narrow column — under three inches of measure once it is
    inset — so it takes the back panel's serif at a smaller size and none of
    its furniture: no border (the fold is its edge), no ornament. The book's
    title heads the front flap, the way a jacket does, because the flap is what
    a browser reads with the book open in their hands.
    """
    pad = min(0.42 * inch, w * 0.14)
    colw = w - 2 * pad
    if colw <= 24:                       # a flap too narrow to set type in
        return
    cx = x0 + w / 2.0
    size, lead = 9.5, 13.5
    canv.saveState()

    top = y0 + h - 0.9 * inch
    if side == 'front':
        title = (meta.get('title') or '').upper()
        if title:
            canv.setFillColor(_pal_color(tpl, tpl.get('title', {}).get('color', 'gold')))
            for ln in _wrap_tracked(title, cf['display'], 13, colw, 1.2):
                _tracked_centre(canv, cx, top, ln, cf['display'], 13, 1.2)
                top -= 17
            top -= 10
        body = meta.get('cover_jacket_blurb') or meta.get('cover_blurb') or ''
    else:
        label = 'ABOUT THE AUTHOR' if (meta.get('cover_author_bio') or '').strip() else ''
        if label:
            canv.setFillColor(_pal_color(tpl, tpl.get('collection', {}).get('color', 'gold')))
            _tracked_centre(canv, cx, top, label, cf['serif'], 8.0, 2.6)
            top -= 20
        # the author photo belongs on the back flap of a jacket, not the panel
        bimg = meta.get('cover_back_image')
        if bimg and os.path.exists(bimg):
            try:
                from reportlab.lib.utils import ImageReader
                ir = ImageReader(bimg)
                iw, ih = ir.getSize()
                tw = min(max(meta.get('cover_back_image_w', 1.5), 0.25) * inch, colw)
                thh = tw * (ih / iw) if iw else tw
                canv.drawImage(ir, cx - tw / 2.0, top - thh, width=tw, height=thh,
                               preserveAspectRatio=True, mask='auto')
                top -= thh + 14
            except Exception:
                pass
        body = meta.get('cover_author_bio') or ''

    if body:
        canv.setFillColor(_pal_color(tpl, 'ink'))
        yy = top
        for para in body.split('\n'):
            if not para.strip():
                yy -= lead * 0.6
                continue
            for ln in _wrap_tracked(para, cf['serif'], size, colw, 0.0):
                # _tracked_left, not drawString: character spacing is part of the
                # PDF text state, so the tracking set by the line above would
                # still be in force and the flap copy would run past its fold
                _tracked_left(canv, x0 + pad, yy, ln, cf['serif'], size, 0.0)
                yy -= lead

    st = tpl.get('studio', {})
    studio = (meta.get('cover_studio') or meta.get('publisher') or '').upper()
    if studio:
        canv.setFillColor(_pal_color(tpl, st.get('color', 'muted')))
        _tracked_centre(canv, cx, y0 + 0.55 * inch, studio,
                        cf['serif'], min(st.get('size', 8.5), 8.0),
                        st.get('tracking', 2.4))
    canv.restoreState()


def _paint_spine(canv, tpl, cf, meta, x0, y0, w, h, draw_text=True):
    """Rotated spine text (title + author), if allowed and wide enough to carry it."""
    if not draw_text or w < 0.10 * inch:   # retailer minimum not met, or physically too thin
        return
    title = (meta.get('title') or '').upper()
    author = (meta.get('cover_accent') or meta.get('author') or '').upper()
    if not title and not author:
        return
    cx = x0 + w / 2.0
    cy = y0 + h / 2.0
    avail = h * 0.82               # length available along the spine
    # size the title to the spine width, but no longer than the spine allows
    tsize = min(w * 0.55, 15.0)
    while tsize > 6 and stringWidth(title, cf['display'], tsize) > avail:
        tsize -= 0.5
    asize = tsize * 0.62
    canv.saveState()
    canv.translate(cx, cy)
    canv.rotate(-90)               # reads top-to-bottom (US/UK convention)
    if title:
        canv.setFillColor(_pal_color(tpl, tpl.get('title', {}).get('color', 'gold')))
        canv.setFont(cf['display'], tsize)
        canv.drawCentredString(0, w * 0.10, title)
    if author:
        canv.setFillColor(_pal_color(tpl, tpl.get('accent', {}).get('color', 'teal')))
        canv.setFont(cf['display'], asize)
        canv.drawCentredString(0, -w * 0.28, author)
    canv.restoreState()


def _paint_wrap_guides(canv, W, H, folds, y0, panel_h, wrap=0.0):
    """Dashed proof guides for the folds and the zones art must not rely on.

    Magenta marks every vertical the press folds or trims at — two on a
    paperback, four on a case laminate, six on a jacket — plus the top and
    bottom of the panels. A second, blue rectangle marks the **turn-in**:
    everything outside it is glued around the board and will never be seen, so
    it is a different kind of boundary from a trim line and is drawn as one.
    Proof only — never send a guided PDF to print.
    """
    canv.saveState()
    canv.setLineWidth(0.5)
    canv.setDash(4, 3)
    if wrap:
        canv.setStrokeColorRGB(0.25, 0.55, 0.85)
        canv.rect(wrap, wrap, W - 2 * wrap, H - 2 * wrap, stroke=1, fill=0)
    canv.setStrokeColorRGB(0.85, 0.2, 0.5)
    for x in sorted(set(round(v, 4) for v in folds)):
        canv.line(x, 0, x, H)
    canv.line(0, y0, W, y0)
    canv.line(0, y0 + panel_h, W, y0 + panel_h)
    canv.restoreState()


def build_cover_wrap(tpl, cf, meta, dims, out_path, guides=False):
    """Render a standalone print-ready wrap PDF: back + spine + front + bleed.

    dims: {'trim_w','trim_h','spine_w','bleed'} in inches, plus optional
    'pages' and 'spine_text_min' (retailer rule for when spine text is allowed).

    A **case laminate** hardcover (`binding: 'hardcover'`) is the same three
    panels with two more allowances, and is laid out by the retailers' own
    formula — `wrap + bleed + back + hinge + spine + hinge + front + bleed +
    wrap` across, `wrap + bleed + trim + bleed + wrap` down:
      * `wrap`  — the turn-in glued around the boards (0.625" at both KDP and
        IngramSpark). Nothing that must be seen may sit in it.
      * `hinge` — the channel each side of the spine where the case bends.
        It is a *gap*, not a panel: the panel painters are handed their own
        rectangles, so type stays out of the crease without knowing about it.
    A paperback passes neither, making both zero and the geometry identical to
    what it was before hardcover existed.

    A **dust jacket** (`binding: 'jacket'`) wraps the finished case rather than
    the block, so its panels are the *board* — trim plus `board_ext` on the
    fore-edge, and on both the head and the tail — and it gains a folded flap
    at each end instead of a turn-in:
    `bleed + flap + panel + hinge + spine + hinge + panel + flap + bleed`
    across, `bleed + trim + 2·board_ext + bleed` down. Laid flat and printed
    side up the order is back flap, back, spine, front, front flap — the flaps
    fold in behind the covers they adjoin.

    Returns the finished wrap dimensions (inches) and whether spine text was drawn.
    """
    from reportlab.pdfgen import canvas as _canvas
    tw = dims['trim_w'] * inch
    th = dims['trim_h'] * inch
    sp = max(dims.get('spine_w', 0.0), 0.0) * inch
    bl = dims.get('bleed', 0.125) * inch
    binding = dims.get('binding', 'paperback')
    hard = binding == 'hardcover'
    jacket = binding == 'jacket'
    wrap = max(dims.get('wrap', 0.625) * inch, 0.0) if hard else 0.0
    hinge = max(dims.get('hinge', 0.375) * inch, 0.0) if (hard or jacket) else 0.0
    flap = max(dims.get('flap', 3.5) * inch, 0.0) if jacket else 0.0
    bext = max(dims.get('board_ext', 0.125) * inch, 0.0) if jacket else 0.0
    pages = dims.get('pages')
    smin = dims.get('spine_text_min', 0) or 0
    draw_spine = (pages is None or pages >= smin) and sp >= 0.10 * inch
    edge = wrap + bl                       # outer allowance before a panel starts
    pw = tw + bext                         # panel width: the board, on a jacket
    ph = th + 2 * bext                     # panel height, likewise
    W = 2 * edge + 2 * flap + 2 * pw + 2 * hinge + sp
    H = 2 * edge + ph
    c = _canvas.Canvas(out_path, pagesize=(W, H))
    pal = tpl.get('palette', {})
    _paint_gradient(c, pal, 0, 0, W, H)
    back_x = edge + flap
    spine_x = back_x + pw + hinge
    front_x = spine_x + sp + hinge
    panel_meta = meta
    if jacket:
        # On a jacket the flaps own the author photo and — unless the jacket
        # has copy of its own — the blurb, so the back panel doesn't print the
        # same paragraph twice on one piece of paper. Set a jacket blurb and
        # the back panel keeps its own text.
        panel_meta = dict(meta)
        panel_meta.pop('cover_back_image', None)
        if not (meta.get('cover_jacket_blurb') or '').strip():
            panel_meta.pop('cover_blurb', None)
    _paint_back_panel(c, tpl, cf, panel_meta, back_x, edge, pw, ph)
    _paint_spine(c, tpl, cf, meta, spine_x, edge, sp, ph, draw_text=draw_spine)
    _paint_background(c, tpl, front_x, edge, pw, ph)
    _paint_cover_front(c, tpl, cf, meta, front_x, edge, pw, ph)
    if flap:
        _paint_flap(c, tpl, cf, meta, edge, edge, flap, ph, 'back')
        _paint_flap(c, tpl, cf, meta, front_x + pw, edge, flap, ph, 'front')
    if guides:
        folds = [edge, edge + flap, back_x + pw, spine_x, spine_x + sp,
                 front_x, front_x + pw, front_x + pw + flap]
        _paint_wrap_guides(c, W, H, folds, edge, ph, wrap=wrap)
    c.showPage()
    c.save()
    return {'wrap_w': round(W / inch, 3), 'wrap_h': round(H / inch, 3),
            'spine_w': round(sp / inch, 4), 'spine_text': bool(draw_spine),
            'binding': binding if binding in ('hardcover', 'jacket') else 'paperback',
            'wrap': round(wrap / inch, 4), 'hinge': round(hinge / inch, 4),
            'flap': round(flap / inch, 4), 'panel_w': round(pw / inch, 4)}


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
def _draw_ornament(canv, oid, x0, y0, w, h):
    """Paint a bundled vector ornament into the box (x0, y0, w, h).

    Walks the same primitive list `ornaments.svg()` walks, so the mark in the
    PDF and the one in the EPUB come from one definition. The box maps the
    ornament's own coordinates (x 0→aspect, y 0→1) with a single uniform
    scale, which is why line widths and radii can be given in box-height units.
    """
    d = _orn.get(oid)
    if not d:
        return False
    s = h  # uniform: the ornament box is `aspect` wide by 1 tall
    def P(x, y):
        return (x0 + x * s, y0 + y * s)

    canv.saveState()
    canv.setFillColorRGB(0, 0, 0)
    canv.setStrokeColorRGB(0, 0, 0)
    canv.setLineCap(1)
    canv.setLineJoin(1)
    for op in d['ops']:
        kind = op[0]
        if kind == 'poly':
            p = canv.beginPath()
            p.moveTo(*P(*op[1][0]))
            for pt in op[1][1:]:
                p.lineTo(*P(*pt))
            p.close()
            canv.drawPath(p, fill=1, stroke=0)
        elif kind == 'dot':
            canv.circle(*P(op[1], op[2]), op[3] * s, fill=1, stroke=0)
        elif kind == 'line':
            canv.setLineWidth(op[5] * s)
            canv.line(*P(op[1], op[2]), *P(op[3], op[4]))
        else:  # fill / stroke path
            p = canv.beginPath()
            for seg in op[1]:
                if seg[0] == 'm':
                    p.moveTo(*P(seg[1], seg[2]))
                elif seg[0] == 'l':
                    p.lineTo(*P(seg[1], seg[2]))
                elif seg[0] == 'c':
                    p.curveTo(*P(seg[1], seg[2]), *P(seg[3], seg[4]), *P(seg[5], seg[6]))
                else:
                    p.close()
            if kind == 'fill':
                canv.drawPath(p, fill=1, stroke=0)
            else:
                canv.setLineWidth(op[2] * s)
                canv.drawPath(p, fill=0, stroke=1)
    canv.restoreState()
    return True


class SceneBreak(Flowable):
    def __init__(self, glyph, font, size, gap, image_path=None,
                 ornament=None, ornament_width=0.0):
        super().__init__()
        self.glyph, self.font, self.size, self.gap = glyph, font, size, gap
        self.image_path = image_path
        self.ornament = ornament
        self.ornament_width = ornament_width
        self.orn_size = (0.0, 0.0)

    def wrap(self, w, h):
        self.width = w
        mark_h = self.size
        if self.ornament:
            self.orn_size = _orn.size(self.ornament, w, self.ornament_width)
            if self.orn_size[1]:
                mark_h = self.orn_size[1]
        self.height = self.gap * 2 + mark_h
        return (w, self.height)

    def draw(self):
        if self.ornament and self.orn_size[1]:
            ow, oh = self.orn_size
            if _draw_ornament(self.canv, self.ornament,
                              (self.width - ow) / 2.0, self.gap, ow, oh):
                return
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


class FnProbe(Flowable):
    """Zero-size marker recording which page a chapter's opening notes fell on.

    Everywhere else the measuring pass finds a reference by its link annotation,
    but `_opening_para` re-sets the first words as plain text for the drop-cap /
    raised-initial / small-caps treatments, and strips the link with everything
    else. This rides just before that paragraph and reports the page it starts
    on — which is where a chapter's first paragraph is, split or not.
    """
    def __init__(self, sink, chapter_idx, numbers):
        super().__init__()
        self._sink, self._ch, self._numbers = sink, chapter_idx, numbers

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        page = self.canv.getPageNumber()
        for n in self._numbers:
            self._sink.setdefault((self._ch, n), page)


class RaisedInitial(Flowable):
    """Opening paragraph whose first letter is set large on the first baseline.

    Done as a flowable rather than an oversized ``<font size>`` run inside a
    Paragraph because ReportLab drops the first baseline to clear a tall run but
    still reports ``lines x leading`` from ``wrap()`` — so the paragraph draws
    lower than the height it reserved and runs into the next one. (``autoLeading``
    narrows that gap but does not close it: its measure and its draw disagree.)
    Owning the geometry, as DropCap does, makes the two agree exactly.
    """
    SCALE = 1.9          # initial size as a multiple of the body size

    def __init__(self, cap, rest, body_style, cap_font, _part=None):
        super().__init__()
        self.body, self.cap_font = body_style, cap_font
        self._cap, self._rest = cap, rest
        self._part = _part          # already-split paragraph, set by split()
        self._para = None

    def wrap(self, availWidth, availHeight):
        b = self.body
        self.cap_size = b.fontSize * self.SCALE
        # the first line is indented past the initial; the rest sets normally
        self.cap_w = stringWidth(self._cap, self.cap_font, self.cap_size)
        if self._part is None:
            st = ParagraphStyle('raised_body', parent=b,
                                firstLineIndent=self.cap_w,
                                spaceBefore=0, spaceAfter=0)
            self._para = _P(self._rest.lstrip(), st)
        else:
            self._para = self._part
        _, ph = self._para.wrap(availWidth, availHeight)
        # room above the first line for the part of the initial that rises past
        # the body's own ascent
        self._extra = max(0.0, pdfmetrics.getAscent(self.cap_font, self.cap_size)
                             - pdfmetrics.getAscent(b.fontName, b.fontSize))
        self.width, self.height = availWidth, ph + self._extra
        return (availWidth, self.height)

    def split(self, availWidth, availHeight):
        """Split like the plain Paragraph this replaced.

        An opening paragraph can be longer than a page, so refusing to split
        (as DropCap does) would raise LayoutError instead of just flowing on.
        The initial stays with the first part; the remainder is an ordinary
        paragraph.
        """
        if availHeight >= self.height:
            return [self]
        if self._para is None or availHeight <= self._extra + 2 * self.body.leading:
            return []                    # too little room here; move it on whole
        parts = self._para.split(availWidth, availHeight - self._extra)
        if len(parts) != 2:
            return []
        head, tail = parts
        return [RaisedInitial(self._cap, '', self.body, self.cap_font, _part=head),
                tail]

    def draw(self):
        c = self.canv
        self._para.drawOn(c, 0, 0)
        # ReportLab puts the first baseline one font-size below the paragraph top
        baseline = self._para.height - self.body.fontSize
        c.setFont(self.cap_font, self.cap_size)
        c.drawString(0, baseline, self._cap)


# ---------------------------------------------------------------- doc template
class BookDoc(BaseDocTemplate):
    def __init__(self, filename, preset, meta, head_font, cover=None, **kw):
        self.preset, self.meta = preset, meta
        self.head_font = head_font
        self._body_start  = None           # page number of the first chapter opener
        self._toc_entries = []             # filled by TocMarker during build
        # footnotes: page -> points to keep free at the foot, and the notes to
        # draw there. Both are worked out by build_pdf's measuring passes.
        self._fn_reserve  = {}
        self._fn_assign   = {}
        self._fn_flow     = {}
        self._fn_drawn    = set()   # notes actually set on a page
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
        cv  = self._cover
        tpl = cv.get('template', {})
        cf  = cv.get('fonts', {'display': self.head_font,
                               'serif': self.head_font, 'italic': self.head_font})
        _paint_gradient(canv, tpl.get('palette', {}), 0, 0, self._pw, self._ph)
        _paint_background(canv, tpl, 0, 0, self._pw, self._ph)
        _paint_cover_front(canv, tpl, cf, self.meta, 0, 0, self._pw, self._ph)

    def handle_pageBegin(self):
        """Reset the page's markers, then shrink the frame if notes go at the foot.

        ReportLab frames are fixed at template time, so the frame is mutated in
        place each page and re-`_geom()`'d — the one hook that lets the text
        block end higher on some pages than others. Its full height is stashed
        the first time so the reservation is always measured from the original.
        """
        self.canv._is_opener = False
        self.canv._is_blank = False
        self._handle_pageBegin()
        f = self.frame
        if '_fullHeight' not in f.__dict__:
            f.__dict__['_fullHeight'] = f._height
            f.__dict__['_fullY1'] = f._y1
        keep = self._fn_reserve.get(self.page, 0)
        f.__dict__['_y1'] = f._fullY1 + keep
        f.__dict__['_height'] = f._fullHeight - keep
        f._geom()
        f._reset()

    def _draw_footnotes(self, canv, page):
        """Set this page's notes into the space handle_pageBegin kept free."""
        keys = self._fn_assign.get(page)
        if not keys:
            return
        em = self.preset.get('endnotes', {})
        recto = (page % 2 == 1)
        x = self._inside if recto else self._outside
        w = self._pw - self._inside - self._outside
        top = self._bottom + self._fn_reserve.get(page, 0) - em.get('foot_gap', 10.0)

        if em.get('foot_rule', True):
            rl = w * em.get('foot_rule_width', 0.3)
            canv.setStrokeGray(0.45)
            canv.setLineWidth(0.5)
            canv.line(x, top, x + rl, top)
            top -= 6

        y = top
        floor = self._bottom * 0.35        # never print into the trim edge
        for key in keys:
            fl = self._fn_flow.get(key)
            if fl is None:
                continue
            _, h = fl.wrapOn(canv, w, self._ph)
            if y - h < floor:
                continue        # no room left: never print into the trim edge
            y -= h
            fl.drawOn(canv, x, y)
            self._fn_drawn.add(key)
            y -= fl.style.spaceAfter

    _press_canvas = None          # set by build_pdf for a press-ready build

    def build(self, flowables, **kw):
        """Route a press build through the CMYK canvas, measuring passes included.

        Every pass has to use it: a colour the press canvas would refuse must
        surface on the first build, not after the footnote pass has already
        laid the book out.
        """
        if self._press_canvas is not None:
            kw.setdefault('canvasmaker', self._press_canvas)
        return BaseDocTemplate.build(self, flowables, **kw)

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

        self._draw_footnotes(canv, page)

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
    # Links are clickable but unstyled in print by default — a coloured or
    # underlined link is a screen idiom, and a POD interior is usually black.
    # The style can turn the underline on; colour is an ebook-only setting.
    body = ParagraphStyle('body', fontName=fonts['regular'], fontSize=b['size'],
                          leading=b['leading'],
                          alignment=TA_JUSTIFY if b['justify'] else TA_LEFT,
                          firstLineIndent=b['indent'] * inch,
                          linkUnderline=1 if preset.get('link', {}).get('underline') else 0,
                          allowWidows=0, allowOrphans=0)
    first = ParagraphStyle('first', parent=body, firstLineIndent=0)
    c = preset['chapter']
    chap_title = ParagraphStyle('chap', fontName=fonts.get('bold', fonts['regular']),
                                fontSize=c['title_size'], leading=c['title_size'] * 1.15,
                                alignment=TA_CENTER)
    chap_num = ParagraphStyle('cnum', fontName=fonts['regular'],
                              fontSize=c['number_size'], leading=c['number_size'] * 1.2,
                              alignment=TA_CENTER, textColor=(0.3, 0.3, 0.3))
    # Anthology byline: author line under the piece title.
    chap_byline = ParagraphStyle('cbyl', fontName=fonts.get('italic', fonts['regular']),
                                 fontSize=b['size'] + 1, leading=(b['size'] + 1) * 1.3,
                                 alignment=TA_CENTER, textColor=(0.28, 0.28, 0.28))
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
                chap_byline=chap_byline,
                subhead=subhead, part_num=part_num_style, part_title=part_title_style)


_TAG_RE = re.compile(r'<[^>]+>')
_NOTE_MARK_RE = re.compile(r'<note n="(\d+)" id="[\w\-]+"/>')
# the same number once _apply_note_markers has made it a linked <super>
# the rendered marker, with or without its link — a footnote's marker has no
# anchor to point at, and the opening-paragraph fix has to catch both forms
_NOTE_SUPER_RE = re.compile(
    r'(?:<a href="#note-\d+-\d+">)?<super[^>]*>(\d+)</super>(?:</a>)?')


def _esc_markup(text):
    """Escape a raw string for ReportLab paragraph markup."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;'))


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


_SUP_DIGITS = {'0': '⁰', '1': '¹', '2': '²', '3': '³',
               '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷',
               '8': '⁸', '9': '⁹'}


def _unicode_super(n, font_name):
    """'12' -> '¹²' if the face has those glyphs, else None.

    The decorative openings re-set their first words as plain text, so a
    `<super>` tag there is stripped and an endnote number would land mid-sentence
    at full size, reading like a typo. A real superscript *character* survives
    the stripping — where the font has one. Lora, for instance, only carries 1–4.
    """
    try:
        cmap = pdfmetrics.getFont(font_name).face.charToGlyph
    except Exception:
        return None
    out = []
    for d in str(n):
        c = _SUP_DIGITS.get(d)
        if c is None or ord(c) not in cmap:
            return None
        out.append(c)
    return ''.join(out)


def _opening_para(text, st, preset, fonts, hyph=None):
    style = preset['chapter']['open_style']
    if style != 'none':
        # swap note markers for superscript characters before the tags are stripped
        text = _NOTE_SUPER_RE.sub(
            lambda m: _unicode_super(m.group(1), fonts['regular']) or m.group(1),
            text)
    plain = _plain(text)
    if style == 'dropcap':
        plain_h = _hyphenate_markup(plain, hyph) if hyph else plain
        return [DropCap(plain_h, st['first'], fonts.get('bold', fonts['regular']),
                        lines=preset['chapter'].get('dropcap_lines', 3))]
    if style == 'raised_initial':
        rest = _hyphenate_markup(plain[1:], hyph) if hyph else plain[1:]
        return [RaisedInitial(plain[:1], rest, st['first'], fonts['regular'])]
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


def _render_poem_block(block_paras, attrs, preset, fonts, st, avail_w):
    """Flowables for a ~~~ poem … ~~~ block: optional title + line-preserved verse.

    Each stanza arrives as one ('para', 'line<br/>line') tuple (see
    manuscript.parse_markdown), so we split on <br/> and render every verse line
    as its own flowable with a hanging *runover* indent (a line too long to fit
    wraps under an indent instead of back to the margin). Verse is never
    hyphenated. All style comes from preset['poem'] with sensible fallbacks, so
    poems render even for presets that predate this block.
    """
    pm         = preset.get('poem', {})
    size       = pm.get('font_size', 0) or st['body'].fontSize
    lead       = size * pm.get('line_leading', 1.32)
    indent     = pm.get('indent', 0.5) * inch
    runover    = pm.get('runover_indent', 0.28) * inch
    stanza_gap = pm.get('stanza_spacing', 9.0)
    space      = pm.get('space_around', 14.0)
    centered   = pm.get('align', 'left') == 'center'
    alignment  = TA_CENTER if centered else TA_LEFT

    verse_style = ParagraphStyle(
        'poemline', parent=st['body'], fontName=fonts['regular'],
        fontSize=size, leading=lead, alignment=alignment,
        leftIndent=indent + (0 if centered else runover),
        firstLineIndent=(0 if centered else -runover),
        rightIndent=indent, spaceBefore=0, spaceAfter=0,
    )

    out = [Spacer(1, space)]

    title = (attrs.get('title', '') or '').strip()
    if title:
        title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        tsize = pm.get('title_size', 0) or (size + 1.5)
        tstyle_name = pm.get('title_style', 'italic')
        if tstyle_name == 'bold':
            tfont = fonts.get('bold', fonts['regular'])
        elif tstyle_name == 'regular':
            tfont = fonts['regular']
        else:
            tfont = fonts.get('italic', fonts['regular'])
        tstyle = ParagraphStyle(
            'poemtitle', parent=st['body'], fontName=tfont,
            fontSize=tsize, leading=tsize * 1.2, alignment=alignment,
            leftIndent=indent, rightIndent=indent,
            spaceBefore=0, spaceAfter=pm.get('title_space', 8.0),
        )
        out.append(Paragraph(title, tstyle))

    for si, (_, stanza) in enumerate(block_paras):
        if si > 0:
            out.append(Spacer(1, stanza_gap))
        for ln in stanza.split('<br/>'):
            out.append(Paragraph(ln or '&#160;', verse_style))

    out.append(Spacer(1, space))
    return out


def _figure_asset_path(name):
    """Resolve a figure filename against the figure dir, or an absolute path.

    Returns None when the file is missing, so the renderer can draw a visible
    placeholder — a silently dropped illustration is worse than an obvious gap.
    """
    if not name:
        return None
    p = name if os.path.isabs(name) else os.path.join(FIGURE_DIR, name)
    return p if os.path.exists(p) else None


def _figure_size(path, box_w, max_h):
    """Fit an image inside (box_w, max_h), preserving its aspect ratio."""
    ratio = 0.75                                  # 4:3 fallback if unreadable
    try:
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(path).getSize()
        if iw > 0 and ih > 0:
            ratio = float(ih) / float(iw)
    except Exception:
        pass
    w, h = box_w, box_w * ratio
    if max_h and h > max_h:                       # too tall: fit by height instead
        h, w = max_h, max_h / ratio
    return w, h


class FigureImage(Flowable):
    """An illustration scaled into a box, aspect preserved, aligned in the column.

    Draws a labelled placeholder instead when the file is missing, so a broken
    src shows up in the proof rather than vanishing from the page.
    """
    def __init__(self, path, width, height, avail_w, align='center', label=''):
        super().__init__()
        self.path, self.align, self.label = path, align, label
        self._w, self._h, self._avail = width, height, avail_w

    def wrap(self, availWidth, availHeight):
        self._avail = availWidth
        self.width, self.height = availWidth, self._h
        return (availWidth, self._h)

    def _x(self):
        if self.align == 'left':
            return 0
        if self.align == 'right':
            return self._avail - self._w
        return (self._avail - self._w) / 2.0

    def draw(self):
        c, x = self.canv, self._x()
        if self.path:
            try:
                c.drawImage(self.path, x, 0, width=self._w, height=self._h,
                            mask='auto')
                return
            except Exception:
                pass                              # fall through to the placeholder
        c.setStrokeColor(_colors.Color(.6, .6, .6))
        c.setFillColor(_colors.Color(.94, .94, .94))
        c.rect(x, 0, self._w, self._h, stroke=1, fill=1)
        c.setFillColor(_colors.Color(.35, .35, .35))
        c.setFont('Helvetica', 8)
        c.drawCentredString(x + self._w / 2.0, self._h / 2.0 - 3,
                            f'missing image: {self.label}'[:90])


def _render_figure_block(block_paras, attrs, preset, fonts, st, avail_w):
    """Flowables for a ~~~ figure src="…" … ~~~ block: the image + its caption.

    The block's paragraphs are the caption (a figure may have none). Placement
    comes from the attrs — ``width`` (fraction of the text width), ``align``,
    and ``full`` (its own page) — falling back to preset['figure'], so a figure
    renders sensibly for presets that predate this block.
    """
    fg      = preset.get('figure', {})
    src     = (attrs.get('src', '') or '').strip()
    path    = _figure_asset_path(src)
    align   = (attrs.get('align', '') or fg.get('align', 'center')).lower()
    full    = str(attrs.get('full', '')).strip().lower() in ('1', 'yes', 'true', 'page')
    space   = fg.get('space_around', 12.0)

    # the text area, so a figure can never be taller than the page it sits on
    trim, mar = preset['trim'], preset['margins']
    text_h = (trim['h'] - mar['top'] - mar['bottom']) * inch

    csize   = fg.get('caption_size', 0) or (st['body'].fontSize - 1.0)
    cstyle_name = fg.get('caption_style', 'italic')
    cfont   = (fonts.get('italic', fonts['regular']) if cstyle_name == 'italic'
               else fonts.get('bold', fonts['regular']) if cstyle_name == 'bold'
               else fonts['regular'])
    calign  = {'left': TA_LEFT, 'right': TA_RIGHT}.get(
        fg.get('caption_align', 'center'), TA_CENTER)
    cap_style = ParagraphStyle(
        'figcaption', parent=st['body'], fontName=cfont, fontSize=csize,
        leading=csize * 1.3, alignment=calign, firstLineIndent=0,
        spaceBefore=fg.get('caption_gap', 5.0), spaceAfter=0,
    )
    caption = [Paragraph(text, cap_style) for _, text in block_paras if text]
    # a caption on a full-page plate needs room reserved under the image
    cap_h = sum(p.wrap(avail_w, text_h)[1] + cap_style.spaceBefore
                for p in caption) if caption else 0.0

    if full:
        box_w = avail_w
        max_h = text_h - cap_h
    else:
        try:
            frac = float(attrs.get('width', '') or fg.get('width', 0.8))
        except (TypeError, ValueError):
            frac = fg.get('width', 0.8)
        box_w = avail_w * max(0.05, min(1.0, frac))
        max_h = (text_h - cap_h) * fg.get('max_height', 0.8)

    w, h = _figure_size(path, box_w, max_h) if path else (box_w, box_w * 0.62)
    img = FigureImage(path, w, h, avail_w, align=align, label=src or '(no src)')

    if full:
        # its own page: break, plate, caption, break
        return [PageBreak(), img] + caption + [PageBreak()]
    # image and caption must not be separated by a page break
    return [Spacer(1, space), KeepTogether([img] + caption), Spacer(1, space)]


def chapter_art_src(preset):
    """The image a style prints on every chapter opener, or ''.

    Read off the preset in one place because three callers need the same
    answer: the PDF opener, the EPUB (which must also *package* the file), and
    the style card. A style that names a file no longer on disk still returns
    it — the renderer draws its placeholder, so a lost illustration shows up in
    the proof instead of disappearing.
    """
    return (preset.get('chapter_art', {}).get('image', '') or '').strip()


def chapter_art_position(preset):
    """'above' (over the chapter number) or 'below' (under the title)."""
    pos = (preset.get('chapter_art', {}).get('position', 'above') or 'above').lower()
    return 'below' if pos == 'below' else 'above'


def _chapter_art(preset, avail_w, text_h):
    """The chapter-opener illustration as flowables, gap included, or [].

    Sized like a figure — a fraction of the text column, the height following
    from the aspect — and then clamped twice: by the style's own `max_height`
    (inches) and by half the text height, so a mis-sized file can crowd the
    opener but can never push the chapter title off its own page. The gap sits
    between the art and the heading, so which side it goes on follows the
    position.
    """
    ca  = preset.get('chapter_art', {})
    src = chapter_art_src(preset)
    if not src:
        return []
    frac  = max(0.05, min(float(ca.get('width', 0.32) or 0.32), 1.0))
    max_h = min(float(ca.get('max_height', 1.6) or 1.6) * inch, text_h * 0.5)
    path  = _figure_asset_path(src)
    box_w = avail_w * frac
    w, h  = _figure_size(path, box_w, max_h) if path else (box_w, box_w * 0.35)
    align = (ca.get('align', 'center') or 'center').lower()
    gap   = float(ca.get('gap', 0.16) or 0.0) * inch
    art   = FigureImage(path, w, h, avail_w, align=align, label=src)
    if not gap:
        return [art]
    return [Spacer(1, gap), art] if chapter_art_position(preset) == 'below' \
        else [art, Spacer(1, gap)]


_ALIGN_MAP = {'left': TA_LEFT, 'center': TA_CENTER, 'centre': TA_CENTER,
              'right': TA_RIGHT}


def _render_list_block(block_paras, attrs, preset, fonts, st, avail_w, hyph=None):
    """Flowables for `~~~ list` — one item per paragraph in the block.

    Items hang: the marker sits in the first line's negative indent, so wrapped
    lines align under the item text rather than back at the margin.
    """
    lm      = preset.get('list', {})
    size    = lm.get('font_size', 0) or st['body'].fontSize
    lead    = size * lm.get('line_leading', 1.35)
    indent  = lm.get('indent', 0.25) * inch
    hang    = lm.get('marker_gap', 0.22) * inch
    gap     = lm.get('item_gap', 3.0)
    space   = lm.get('space_around', 10.0)
    bullet  = lm.get('bullet', '•')

    numbered = (attrs.get('type', '') or '').lower().startswith('num')
    try:
        n = int(attrs.get('start', 1))
    except (TypeError, ValueError):
        n = 1

    item_style = ParagraphStyle(
        'listitem', parent=st['body'], fontName=fonts['regular'],
        fontSize=size, leading=lead, alignment=TA_LEFT,
        leftIndent=indent + hang, firstLineIndent=-hang,
        spaceBefore=0, spaceAfter=gap,
    )
    out = [Spacer(1, space)]
    for i, (_, text) in enumerate(block_paras):
        marker = (lm.get('number_format', '{n}.').format(n=n + i) if numbered
                  else bullet)
        body = _hyphenate_markup(text, hyph) if hyph else text
        # a real tab would need tabstops; a fixed-width space keeps it simple
        out.append(Paragraph(f'{marker}<font size="{size}">&#160;&#160;</font>{body}',
                             item_style))
    out.append(Spacer(1, space - gap if space > gap else 0))
    return out


def _render_quote_block(block_paras, attrs, preset, fonts, st, avail_w, hyph=None):
    """Flowables for `~~~ quote` — an inset block quotation, optional source."""
    qm     = preset.get('quote', {})
    size   = qm.get('font_size', 0) or (st['body'].fontSize - 0.5)
    lead   = size * qm.get('line_leading', 1.35)
    indent = qm.get('indent', 0.35) * inch
    right  = qm.get('right_indent', qm.get('indent', 0.35)) * inch
    space  = qm.get('space_around', 11.0)
    style_name = qm.get('style', 'regular')
    font = (fonts.get('italic', fonts['regular']) if style_name == 'italic'
            else fonts['regular'])

    body_style = ParagraphStyle(
        'quotepara', parent=st['body'], fontName=font,
        fontSize=size, leading=lead,
        leftIndent=indent, rightIndent=right,
        firstLineIndent=qm.get('first_indent', 0.0) * inch,
        spaceBefore=0, spaceAfter=qm.get('para_gap', 4.0),
    )
    first_style = ParagraphStyle('quotefirst', parent=body_style,
                                 firstLineIndent=0)

    out = [Spacer(1, space)]
    for i, (_, text) in enumerate(block_paras):
        body = _hyphenate_markup(text, hyph) if hyph else text
        out.append(Paragraph(body, first_style if i == 0 else body_style))

    source = (attrs.get('source', '') or '').strip()
    if source:
        attr_style = ParagraphStyle(
            'quotesource', parent=body_style,
            fontName=(fonts.get('italic', fonts['regular'])
                      if qm.get('source_style', 'italic') == 'italic'
                      else fonts['regular']),
            fontSize=size - 0.5,
            alignment=_ALIGN_MAP.get(qm.get('source_align', 'right'), TA_RIGHT),
            spaceBefore=qm.get('source_gap', 3.0), spaceAfter=0,
        )
        out.append(Paragraph(_ms_inline(source, False), attr_style))
    out.append(Spacer(1, space))
    return out


def _render_align_block(block_paras, how, preset, fonts, st, avail_w, hyph=None):
    """Flowables for `~~~ center` / `~~~ right` / `~~~ left`.

    Deliberately only changes alignment (and drops the paragraph indent) — the
    style still owns size, face and leading, so an alignment block can't be used
    to smuggle in ad-hoc formatting.
    """
    am    = preset.get('align', {})
    space = am.get('space_around', 9.0)
    style = ParagraphStyle(
        'alignpara', parent=st['body'], fontName=fonts['regular'],
        alignment=_ALIGN_MAP.get(how, TA_CENTER),
        firstLineIndent=0, leftIndent=am.get('indent', 0.0) * inch,
        rightIndent=am.get('indent', 0.0) * inch,
        spaceBefore=0, spaceAfter=am.get('para_gap', 3.0),
    )
    out = [Spacer(1, space)]
    for _, text in block_paras:
        body = _hyphenate_markup(text, hyph) if hyph else text
        out.append(Paragraph(body, style))
    out.append(Spacer(1, space))
    return out


def _table_rows(block_paras):
    """The block's paragraphs -> a rectangular grid of cell markup.

    Each paragraph is one row, cells already split at parse time and rejoined
    with `manuscript.CELL_SEP`. Short rows are padded rather than dropped: a
    ragged table is an authoring slip, and losing the words is worse than an
    empty cell.
    """
    rows = [text.split(_MS_CELL) for _, text in block_paras if text is not None]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    cols = max(len(r) for r in rows)
    return [r + [''] * (cols - len(r)) for r in rows]


def _table_widths(measured, attrs, target_w, size, pad):
    """Column widths in points, summing to target_w.

    `measured` is the grid as it will actually be set — (plain text, font name)
    per cell — because the header is bold (or uppercased small caps) and
    measuring it in the body face underestimates it enough to break a short
    heading like "Sum" in half.

    An explicit `widths="3,1,1"` gives relative shares and is taken literally:
    the author asked for it. Otherwise the rule that matters is **no column is
    narrower than its longest word**. A purely proportional split hands a column
    of prose so much of the measure that a neighbouring "Briars Hollow" gets
    force-broken mid-word, which reads as a bug in the book. So each column
    starts at its longest word and the slack is shared out in proportion to how
    much more each column could use.
    """
    cols = len(measured[0])
    raw = (attrs.get('widths', '') or '').strip()
    if raw:
        try:
            shares = [max(0.0, float(v)) for v in re.split(r'[,\s]+', raw) if v]
        except ValueError:
            shares = []
        if shares and sum(shares) > 0:
            shares = (shares + [shares[-1]] * cols)[:cols]
            return [target_w * s / sum(shares) for s in shares]

    nat, minw = [], []
    for c in range(cols):
        col = [row[c] for row in measured]
        nat.append(max((stringWidth(t, f, size) for t, f in col), default=0.0) + pad)
        words = [(w, f) for t, f in col for w in t.split()]
        # +1pt: ReportLab's own wrap is not bit-identical to stringWidth, and a
        # column exactly as wide as its longest word still breaks it
        minw.append(max((stringWidth(w, f, size) for w, f in words), default=0.0)
                    + pad + 1.0)

    total_nat = sum(nat) or 1.0
    # everything fits unwrapped (or nothing can): share the measure out by need
    if total_nat <= target_w or sum(minw) >= target_w:
        return [target_w * n / total_nat for n in nat]

    slack = target_w - sum(minw)
    extra = [max(0.0, nat[c] - minw[c]) for c in range(cols)]
    total_extra = sum(extra) or 1.0
    return [minw[c] + slack * extra[c] / total_extra for c in range(cols)]


def _render_table_block(block_paras, attrs, preset, fonts, st, avail_w, hyph=None):
    """Flowables for `~~~ table` — one row per line, cells split on `|`.

    The first row is a header unless `header="no"`; it repeats at the top of
    every continuation page, which is the whole reason a table gets a real
    `Table` flowable rather than a formatted paragraph. Column alignment comes
    from `align="left,right,…"`; the caption sits *above* the table, which is
    the book convention (figure captions sit below).
    """
    tm     = preset.get('table', {})
    size   = tm.get('font_size', 0) or (st['body'].fontSize - 1.0)
    lead   = size * tm.get('line_leading', 1.3)
    space  = tm.get('space_around', 12.0)
    padx   = tm.get('cell_pad_x', 5.0)
    pady   = tm.get('cell_pad_y', 3.0)
    rules  = tm.get('rules', 'header')
    rule_w = tm.get('rule_width', 0.5)

    rows = _table_rows(block_paras)
    if not rows:
        return []
    cols = len(rows[0])

    header = str(attrs.get('header', 'yes')).strip().lower() not in ('no', 'false', '0')
    header = header and len(rows) > 1

    # per-column alignment; a short list repeats its last entry
    aligns = [a.strip().lower() for a in (attrs.get('align', '') or '').split(',') if a.strip()]
    if aligns:
        aligns = (aligns + [aligns[-1]] * cols)[:cols]
    else:
        aligns = ['left'] * cols

    hstyle_name = tm.get('header_style', 'bold')
    hfont = (fonts.get('bold', fonts['regular']) if hstyle_name == 'bold'
             else fonts.get('italic', fonts['regular']) if hstyle_name == 'italic'
             else fonts['regular'])

    # the grid exactly as it will be set — text and face per cell — so the width
    # measurement and the render can't disagree
    def cell_text(text, is_head):
        if is_head and hstyle_name == 'smallcaps':
            return _plain(text).upper()
        return text

    measured = [[(_plain(cell_text(t, header and r == 0)),
                  hfont if (header and r == 0) else fonts['regular'])
                 for t in row]
                for r, row in enumerate(rows)]

    target_w = avail_w * max(0.2, min(1.0, tm.get('width', 1.0)))
    widths = _table_widths(measured, attrs, target_w, size, padx * 2)

    def cell_style(col, is_head):
        return ParagraphStyle(
            f'tcell{col}{int(is_head)}', parent=st['body'],
            fontName=hfont if is_head else fonts['regular'],
            fontSize=size, leading=lead,
            alignment=_ALIGN_MAP.get(aligns[col], TA_LEFT),
            firstLineIndent=0, leftIndent=0, rightIndent=0,
            spaceBefore=0, spaceAfter=0,
        )

    data = []
    for r, row in enumerate(rows):
        is_head = header and r == 0
        line = []
        for c, text in enumerate(row):
            body = cell_text(text, is_head)
            if hyph and not is_head:
                body = _hyphenate_markup(body, hyph)
            line.append(Paragraph(body, cell_style(c, is_head)))
        data.append(line)

    tbl = Table(data, colWidths=widths, repeatRows=1 if header else 0,
                hAlign=tm.get('align', 'CENTER').upper())
    style = [
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), padx),
        ('RIGHTPADDING',  (0, 0), (-1, -1), padx),
        ('TOPPADDING',    (0, 0), (-1, -1), pady),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pady),
    ]
    ink = _colors.black
    if rules == 'all':
        style.append(('GRID', (0, 0), (-1, -1), rule_w, ink))
    elif rules == 'horizontal':
        style.append(('LINEBELOW', (0, 0), (-1, -2), rule_w, ink))
        style.append(('LINEABOVE', (0, 0), (-1, 0), rule_w, ink))
        style.append(('LINEBELOW', (0, -1), (-1, -1), rule_w, ink))
    elif rules != 'none':                       # 'header' — the book default
        style.append(('LINEABOVE', (0, 0), (-1, 0), rule_w * 1.6, ink))
        if header:
            style.append(('LINEBELOW', (0, 0), (-1, 0), rule_w, ink))
        style.append(('LINEBELOW', (0, -1), (-1, -1), rule_w * 1.6, ink))
    tbl.setStyle(TableStyle(style))

    out = [Spacer(1, space)]
    caption = (attrs.get('caption', '') or '').strip()
    if caption:
        csize = tm.get('caption_size', 0) or size
        cfont = (fonts.get('italic', fonts['regular'])
                 if tm.get('caption_style', 'italic') == 'italic'
                 else fonts.get('bold', fonts['regular'])
                 if tm.get('caption_style', 'italic') == 'bold' else fonts['regular'])
        cap_style = ParagraphStyle(
            'tabcaption', parent=st['body'], fontName=cfont, fontSize=csize,
            leading=csize * 1.3, firstLineIndent=0,
            alignment=_ALIGN_MAP.get(tm.get('caption_align', 'center'), TA_CENTER),
            spaceBefore=0, spaceAfter=tm.get('caption_gap', 5.0),
        )
        cap = Paragraph(_ms_inline(caption, False), cap_style)
        # keep the caption with the table's first rows; never KeepTogether the
        # whole table, which must be free to split across pages
        cap.keepWithNext = True
        out.append(cap)
    out += [tbl, Spacer(1, space)]
    return out


def _render_doc_block(block_paras, preset, fonts, st, avail_w, hyph=None, block_meta=None):
    """Return flowables for one ~~~ … ~~~ document block."""
    meta  = block_meta or {}
    btype = meta.get('_type', '')
    if btype:
        attrs          = {k: v for k, v in meta.items() if k != '_type'}
        if btype == 'poem':
            return _render_poem_block(block_paras, attrs, preset, fonts, st, avail_w)
        if btype == 'figure':
            return _render_figure_block(block_paras, attrs, preset, fonts, st, avail_w)
        if btype == 'list':
            return _render_list_block(block_paras, attrs, preset, fonts, st, avail_w, hyph)
        if btype == 'quote':
            return _render_quote_block(block_paras, attrs, preset, fonts, st, avail_w, hyph)
        if btype == 'table':
            return _render_table_block(block_paras, attrs, preset, fonts, st, avail_w, hyph)
        if btype in ('center', 'centre', 'right', 'left'):
            return _render_align_block(block_paras, btype, preset, fonts, st, avail_w, hyph)
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


def _note_anchor(ch_idx, n):
    return f'note-{ch_idx}-{n}'


_FN_SCHEME = 'tsfn://'          # measuring-pass marker; never reaches a real build


def _footnote_style(preset, fonts, st):
    em   = preset.get('endnotes', {})
    size = em.get('font_size', 0) or (st['body'].fontSize - 2.0)
    return ParagraphStyle(
        'footnote', parent=st['body'], fontName=fonts['regular'],
        fontSize=size, leading=size * em.get('line_leading', 1.25),
        leftIndent=em.get('indent', 0.22) * inch,
        firstLineIndent=-em.get('indent', 0.22) * inch,
        alignment=TA_LEFT, spaceBefore=0, spaceAfter=em.get('entry_gap', 2.0))


def _footnote_flowables(chapters, preset, fonts, st):
    """A Paragraph per note, keyed (chapter index, number) — laid out at the foot."""
    style = _footnote_style(preset, fonts, st)
    out = {}
    for i, ch in enumerate(chapters, start=1):
        for note in ch.get('notes') or []:
            body = note['text'] or '<i>[no note text]</i>'
            out[(i, note['n'])] = Paragraph(
                f'{note["n"]}.&#160;&#160;{body}', style)
    return out


def _footnote_pages(pdf_path):
    """Read a measuring build back: {(chapter, n): page} from the marker links.

    The reference's *page* is simply the page its link annotation sits on, so no
    destination has to exist — which matters, because in footnote mode there is
    no endnotes page for it to point at. Needs PyMuPDF; the caller falls back to
    endnotes if it isn't installed.
    """
    import fitz
    found = {}
    with fitz.open(pdf_path) as doc:
        found['#pages'] = doc.page_count
        for pno, page in enumerate(doc, start=1):
            for link in page.get_links():
                uri = link.get('uri') or ''
                if not uri.startswith(_FN_SCHEME):
                    continue
                try:
                    ch, n = uri[len(_FN_SCHEME):].split('-')
                    found.setdefault((int(ch), int(n)), pno)
                except ValueError:
                    continue
    return found


def _plan_footnotes(pages, flowables, avail_w, text_h, preset, last_page=None):
    """Turn {note: page} into per-page (reserved height, notes) plans.

    A page whose notes would eat more than `max_height` of the text block keeps
    what fits and pushes the rest onto the next page — which is what a
    typesetter does with an overlong note rather than letting it swallow the
    page.
    """
    em = preset.get('endnotes', {})
    cap = text_h * em.get('foot_max_height', 0.4)
    gap = em.get('foot_gap', 10.0)
    rule = em.get('foot_rule', True)

    by_page = {}
    for key, page in pages.items():
        by_page.setdefault(page, []).append(key)
    for page in by_page:
        by_page[page].sort()

    reserve, assign, spill = {}, {}, []
    # walk contiguous pages from the first with notes, so an overflow lands on
    # the very next page rather than skipping to the next page that has its own
    # Spill runs one page past the end of today's document on purpose: reserving
    # room pushes body text along, so the next pass usually has the page to hold
    # it. Anything still homeless after that is reported, never dropped quietly.
    stop = (last_page or (max(by_page) if by_page else 0)) + 1
    for page in range(min(by_page) if by_page else 0, stop + 1):
        queue = spill + by_page.get(page, [])
        spill = []
        if not queue:
            continue
        # The cap keeps notes from swallowing a page — but only where there is a
        # later page to push them onto. On the last one the notes take whatever
        # room they need: a crowded foot is a real book, a dropped note is a bug.
        may_spill = page < stop - 1
        used, keep = 0.0, []
        for key in queue:
            fl = flowables.get(key)
            if fl is None:
                continue
            _, h = fl.wrap(avail_w, text_h)
            h += fl.style.spaceAfter
            if keep and used + h > cap and may_spill:
                spill.append(key)          # doesn't fit: it runs on to the next page
                continue
            used += h
            keep.append(key)
        if keep:
            assign[page] = keep
            reserve[page] = min(used + gap + (6 if rule else 0), text_h - 24)
    return reserve, assign, list(spill)


def _apply_note_markers(chapters, preset, measure=False):
    """Turn `<note n=… id=…/>` into a linked superscript, per chapter.

    Must happen before anything reaches ReportLab: the neutral marker is not
    valid paragraph markup, so leaving one behind is a build error rather than a
    cosmetic slip. The size is set explicitly — ReportLab's default `<super>`
    keeps the full body size, which next to a real superscript character (what
    the decorative chapter openings fall back to) reads as two different things.
    """
    index = {id(ch): i for i, ch in enumerate(chapters, start=1)}
    em = preset.get('endnotes', {})
    size = round(preset['body']['size'] * em.get('marker_scale', 0.62), 2)
    foot = em.get('placement', 'end') == 'foot'

    def render(text, ch):
        i = index[id(ch)]

        def one(m):
            mark = f'<super size="{size}">{m.group(1)}</super>'
            if measure:
                # A throwaway URI, because the *page its link lands on* is
                # exactly what the measuring pass needs to learn.
                return f'<a href="{_FN_SCHEME}{i}-{m.group(1)}">{mark}</a>'
            if foot:
                # No link: the note is on this very page, and there is no
                # endnotes page for a destination to live on — ReportLab refuses
                # to save a link whose target does not exist.
                return mark
            return f'<a href="#{_note_anchor(i, m.group(1))}">{mark}</a>'

        return _NOTE_MARK_RE.sub(one, text)

    return _ms_map_texts(chapters, render)


def _endnotes_page(chapters, fonts, st, preset):
    """Flowables for the Notes back-matter page, grouped by chapter."""
    em      = preset.get('endnotes', {})
    heading = em.get('heading', 'Notes')
    size    = em.get('font_size', 0) or (st['body'].fontSize - 1.0)
    lead    = size * em.get('line_leading', 1.35)
    indent  = em.get('indent', 0.3) * inch

    head_style = ParagraphStyle(
        'notegroup', parent=st['body'],
        fontName=fonts.get('bold', fonts['regular']),
        fontSize=size + 0.5, leading=(size + 0.5) * 1.3, firstLineIndent=0,
        spaceBefore=em.get('group_gap', 12.0), spaceAfter=4.0)
    entry_style = ParagraphStyle(
        'noteentry', parent=st['body'], fontName=fonts['regular'],
        fontSize=size, leading=lead,
        leftIndent=indent, firstLineIndent=-indent,     # hanging number
        spaceBefore=0, spaceAfter=em.get('entry_gap', 3.0))

    out = [BlankMarker(), Paragraph(heading, st['chap_title']),
           Spacer(1, 0.3 * inch)]
    for i, ch in enumerate(chapters, start=1):
        notes = ch.get('notes') or []
        if not notes:
            continue
        if em.get('group_by_chapter', True):
            label = ch.get('title') or f'Chapter {i}'
            out.append(Paragraph(_esc_markup(label), head_style))
        for note in notes:
            body = note['text'] or '<i>[no note text]</i>'
            out.append(Paragraph(
                f'<a name="{_note_anchor(i, note["n"])}"/>{note["n"]}.&#160;&#160;{body}',
                entry_style))
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
        # A heading turns the same setting into a Praise page: quoted blocks,
        # each with an optional source line. An epigraph passes none.
        if heading:
            out.append(Spacer(1, 0.6 * inch))
            out.append(Paragraph(heading, st['chap_title']))
            out.append(Spacer(1, 0.35 * inch))
        else:
            out.append(Spacer(1, 2.2 * inch))
        _attr = ('—', '–', '--', '-')
        for i, b in enumerate(blocks):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else ''
            # last block, or the one before another block's source line
            is_attr = any(b.startswith(m) for m in _attr)
            out.append(Paragraph(_ms_inline(b, smartquotes), s_a if is_attr else s_q))
            if heading and is_attr and nxt:
                out.append(Spacer(1, 8))          # breathing room between quotes

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

    elif style == 'contributors':
        # One contributor per blank-line-separated block. The name (text before an
        # em dash / '--' separator) is set bold; any remainder is the bio.
        out.append(Spacer(1, 1.0 * inch))
        if heading:
            out.append(Paragraph(heading, st['chap_title']))
            out.append(Spacer(1, 0.4 * inch))
        s = ParagraphStyle('contrib', parent=st['body'], firstLineIndent=0,
                           spaceAfter=st['body'].leading * 0.6)
        for b in blocks:
            name, bio = b, ''
            for sep in ('—', '--'):
                if sep in b:
                    name, bio = b.split(sep, 1)
                    break
            md = '**' + name.strip() + '**'
            if bio.strip():
                md += ' — ' + bio.strip()
            out.append(Paragraph(_ms_inline(md, smartquotes), s))

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
                 has_cover=False, avail_w=0, hyph=None, toc_flowables=None,
                 fn_measure=False, fn_probe=None):
    glyph = preset['scene_break']['glyph']
    story = []
    # note markers are neutral in the parsed model; make them superscripts before
    # any of this text reaches ReportLab
    manuscript = dict(manuscript)
    manuscript['chapters'] = _apply_note_markers(manuscript['chapters'], preset,
                                                 measure=fn_measure)

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
            # Anchor the block near the bottom, but leave enough room that the
            # whole thing (incl. the publisher line) stays on this page — a fixed
            # tall spacer overflows the last line onto the next page on shorter trims.
            text_h = (preset['trim']['h'] - preset['margins']['top']
                      - preset['margins']['bottom']) * inch
            top_gap = max(text_h - 2.4 * inch, 0.5 * inch)
            return [BlankMarker(), Spacer(1, top_gap),
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

    # ---- front matter extras (order comes from matter.SECTIONS) ----
    sq = meta.get('smartquotes', True)
    _fm_need_break = len(story) > 0
    _fm_first = True   # only the first extra page gets recto-forced
    for _sec in _matter.present(meta, 'front'):
        if _fm_need_break:
            story.append((RectoBreak() if rhs else PageBreak()) if _fm_first else PageBreak())
        _fm_need_break = True
        _fm_first = False
        story.extend(_matter_page(_matter.heading(_sec, meta.get('author', '')),
                                  meta[_sec['key']].strip(),
                                  fonts, st, sq, _sec['style']))

    # ---- body ----
    c  = preset['chapter']
    pd = preset.get('part_divider', {})
    m  = preset['margins']
    text_h = (preset['trim']['h'] - m['top'] - m['bottom']) * inch

    need_break      = False   # True after the first body element is placed
    current_part_num = None

    _numbers = _ms_numbers(manuscript['chapters'])
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
        # chapter-opening art: over the number, or under the title/byline
        art = _chapter_art(preset, avail_w, text_h)
        art_pos = chapter_art_position(preset)
        if art and art_pos == 'above':
            story.extend(art)
        # Destinations for in-book links: `[see](#chapter-2)` or the title's slug.
        anchors = ''.join(f'<a name="{a}"/>' for a in _ms_anchors(ch, idx))
        if c.get('show_number', True) and _numbers[idx - 1] is not None:
            label = c.get('number_format', 'Chapter {n}').format(n=_numbers[idx - 1])
            story.append(Paragraph(anchors + label, st['chap_num']))
            anchors = ''
            story.append(Spacer(1, 0.12 * inch))
        if ch['title']:
            story.append(Paragraph(anchors + ch['title'], st['chap_title']))
            anchors = ''
        if anchors:                       # no number and no title: park them here
            story.append(Paragraph(anchors, st['chap_num']))
        if ch.get('byline'):
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph(_ms_inline(ch['byline'], sq), st['chap_byline']))
        if art and art_pos == 'below':
            story.extend(art)
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
                orn = sb.get('ornament', '') if sb.get('type') == 'ornament' else ''
                story.append(SceneBreak(glyph, head_font, sb['size'], sb['gap'],
                                        image_path=img_path, ornament=orn,
                                        ornament_width=sb.get('ornament_width', 0.0)))
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
                    if fn_probe is not None:
                        nums = _NOTE_SUPER_RE.findall(val) or                                re.findall(r'{}(\d+)-(\d+)'.format(re.escape(_FN_SCHEME)), val)
                        nums = [n[-1] if isinstance(n, tuple) else n for n in nums]
                        if nums:
                            story.append(FnProbe(fn_probe, idx, [int(n) for n in nums]))
                    story.extend(_opening_para(val, st, preset, fonts, hyph=hyph))
                    opened = True
                elif flush_next:
                    val_h = _hyphenate_markup(val, hyph) if hyph else val
                    story.append(Paragraph(val_h, st['first']))
                else:
                    val_h = _hyphenate_markup(val, hyph) if hyph else val
                    story.append(Paragraph(val_h, st['body']))
                flush_next = False

    # ---- back matter (order comes from matter.SECTIONS) ----
    _author = meta.get('author', '')
    _bm_first = True   # only the first back-matter page gets recto-forced

    # Notes come first in the back matter, right after the last chapter — they
    # belong to the text in a way acknowledgments and author bios don't.
    if (any(ch.get('notes') for ch in manuscript['chapters'])
            and preset.get('endnotes', {}).get('placement', 'end') != 'foot'):
        story.append(RectoBreak() if rhs else PageBreak())
        _bm_first = False
        story.extend(_endnotes_page(manuscript['chapters'], fonts, st, preset))

    for _sec in _matter.present(meta, 'back'):
        story.append((RectoBreak() if rhs else PageBreak()) if _bm_first else PageBreak())
        _bm_first = False
        story.extend(_matter_page(_matter.heading(_sec, _author),
                                  meta[_sec['key']].strip(),
                                  fonts, st, sq, _sec['style']))

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


def _resolve_footnotes(build, chapters, preset, fonts, st, avail_w, text_h,
                       passes=3, probe=None):
    """Work out what to keep free at the foot of each page, and what goes there.

    Reserving space pushes text down, which can move a reference onto the next
    page, which changes the reservation — so this iterates. Reservations only
    ever grow between passes (`max`), which stops the two states of a reference
    sitting on a page boundary from flipping back and forth forever. Three
    passes settles every book tested; whatever it has after that is used, and a
    stale note simply sits one page from its reference rather than breaking.

    `build(reserve, assign)` must build to a temp path and return it.
    """
    flow = _footnote_flowables(chapters, preset, fonts, st)
    if not flow:
        return {}, {}
    reserve, assign, seen, unplaced = {}, {}, None, []
    last_seen = 0
    for _ in range(passes):
        tmp = build(reserve, assign)
        try:
            pages = _footnote_pages(tmp)
            if probe:
                # opening paragraphs report themselves; links cover the rest
                for key, page in probe.items():
                    pages.setdefault(key, page)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not pages:
            break
        # Deliberately re-plan even when every reference sits where it did:
        # the reservation may have grown the book, and the extra pages are
        # exactly where overflowing notes go. `merged == reserve` below is
        # the real stopping condition.
        seen = pages
        doc_pages = pages.pop('#pages', None)
        last_seen = doc_pages or last_seen
        new_reserve, assign, unplaced = _plan_footnotes(
            pages, flow, avail_w, text_h, preset, last_page=doc_pages)
        merged = dict(reserve)
        for page, h in new_reserve.items():        # monotone: damps oscillation
            merged[page] = max(merged.get(page, 0), h)
        if merged == reserve:
            break
        reserve = merged

    # A page the book doesn't have can't show a note. Drop those assignments
    # and count them, so the build reports the shortfall instead of quietly
    # swallowing it — there is no honest way to fit more notes than page.
    if last_seen:
        for page in [pg for pg in assign if pg > last_seen]:
            unplaced.extend(assign.pop(page))
            reserve.pop(page, None)
    return reserve, assign, unplaced


_RGB_OP_RE = re.compile(r'(?<![A-Za-z/])(rg|RG)(?![A-Za-z])')


def press_check(path):
    """Read a built PDF back and report how close it is to press standard.

    Measured off the file, not inferred from the build: the point of a press
    check is to describe the artefact that will actually be uploaded. Returns
    the same {label, ok, detail} rows the other preflight cards use, or None if
    PyMuPDF isn't installed.

    The honest headline is in the last row: this is a **press-friendly** PDF,
    not a certified PDF/X-1a, because the standard also wants an embedded CMYK
    output intent — an ICC profile we don't ship (see the README).
    """
    try:
        import fitz
    except ImportError:
        return None

    rgb_ops = links = rgb_imgs = 0
    transparency = False
    with fitz.open(path) as doc:
        for page in doc:
            rgb_ops += len(_RGB_OP_RE.findall(page.read_contents().decode('latin-1')))
            links += len(page.get_links())
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=True) or ''
            except Exception:
                continue
            if '/Image' in obj and '/DeviceRGB' in obj:
                rgb_imgs += 1
            if '/SMask' in obj or '/ExtGState' in obj:
                transparency = True
    # the boxes live on the page objects; the file itself is the simplest read
    with open(path, 'rb') as fh:
        trimbox = b'/TrimBox' in fh.read()

    out = [
        {'label': 'Colour', 'ok': rgb_ops == 0,
         'detail': ('Text and rules are K-only black — one ink under body type'
                    if rgb_ops == 0 else
                    f'{rgb_ops} RGB colour operations — a printer converts these, and '
                    'RGB black usually becomes a four-ink black that mis-registers')},
        {'label': 'Illustrations', 'ok': rgb_imgs == 0,
         'detail': ('No RGB images' if rgb_imgs == 0 else
                    f'{rgb_imgs} image(s) are RGB — POD printers convert them for you, '
                    'but a press wants CMYK done deliberately')},
        {'label': 'Transparency', 'ok': not transparency,
         'detail': ('None — nothing to flatten' if not transparency else
                    'Transparency present — PDF/X-1a requires it flattened')},
        {'label': 'Annotations', 'ok': links == 0,
         'detail': ('No annotations — nothing that only works on a screen'
                    if links == 0 else
                    f'{links} link annotation(s) — harmless in print, but PDF/X-1a '
                    'forbids them inside the trim box')},
        {'label': 'Trim box', 'ok': trimbox,
         'detail': ('Declared, so a prepress check knows where the page ends'
                    if trimbox else 'Not declared — printers fall back to the page box')},
        {'label': 'Output intent', 'ok': False,
         'detail': ('No embedded ICC profile, so this is press-friendly rather than '
                    'certified PDF/X-1a. KDP and IngramSpark both accept it as is.')},
    ]
    return out


def _press_canvasmaker(pw, ph):
    """A canvas that emits what a printer wants, and refuses what it doesn't.

    Two things happen here that can't be done after the fact:

    * `enforceColorSpace='cmyk'` — ReportLab converts every grey to **K-only**
      CMYK and raises on anything chromatic. That is the whole point: an RGB
      black (`0 0 0 rg`) is what makes a POD printer lay down four inks under
      body text and produce the muddy, mis-registered page authors complain
      about. Our interiors are black and grey throughout, so the conversion is
      exact — no colour is approximated, and a style that ever introduced a
      chromatic colour raises rather than being silently converted.
    * `TrimBox`/`BleedBox` — declared equal to the page, which is the truth for
      an interior with no bleed, and is what a prepress check looks for first.

    Links are dropped: PDF/X forbids annotations inside the trim box, and a URL
    you cannot click is nothing on paper. The words survive, the annotation
    doesn't.
    """
    from reportlab.pdfgen import canvas as _canvas

    class PressCanvas(_canvas.Canvas):
        def __init__(self, *a, **kw):
            kw['enforceColorSpace'] = 'cmyk'
            kw['trimBox'] = (0, 0, pw, ph)
            kw['bleedBox'] = (0, 0, pw, ph)
            _canvas.Canvas.__init__(self, *a, **kw)

        def linkURL(self, *a, **kw):
            pass

        def linkRect(self, *a, **kw):
            pass

        def linkAbsolute(self, *a, **kw):
            pass

    return PressCanvas


def build_pdf(manuscript, preset, out_path, meta, press=False):
    """Build the interior. `press=True` asks for the press-ready variant.

    A press build that hits a colour it cannot express falls back to a normal
    one and says so in `press_error`, because a book that builds in RGB beats
    a book that doesn't build.
    """
    if not press:
        return _build_pdf(manuscript, preset, out_path, meta)
    try:
        return _build_pdf(manuscript, preset, out_path, meta, press=True)
    except ValueError as exc:
        if 'color' not in str(exc).lower():
            raise
        res = _build_pdf(manuscript, preset, out_path, meta)
        res['press'] = False
        res['press_error'] = str(exc)
        return res


def _build_pdf(manuscript, preset, out_path, meta, press=False):
    fonts = register_fonts(preset)
    st = _styles(preset, fonts)
    head_font = fonts['regular']

    cover = None
    cover_path = None            # temp image path to clean up (image mode only)
    if press:
        # A press interior carries no cover: KDP and IngramSpark both want the
        # cover as its own file, and a designed cover is chromatic by nature —
        # it would be the one thing in the book the CMYK canvas refused.
        meta = dict(meta, cover_mode='none', cover_image='')
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

    text_h = (preset['trim']['h'] - m['top'] - m['bottom']) * inch
    foot_notes = (preset.get('endnotes', {}).get('placement', 'end') == 'foot'
                  and any(ch.get('notes') for ch in manuscript['chapters']))
    fn_reserve, fn_assign, unplaced_notes = {}, {}, []
    fn_flow = _footnote_flowables(manuscript['chapters'], preset, fonts, st)         if foot_notes else {}

    def _make_doc(path):
        doc = BookDoc(path, preset, meta, head_font, cover=cover,
                      title=meta.get('title', ''), author=meta.get('author', ''))
        doc._fn_reserve, doc._fn_assign, doc._fn_flow = fn_reserve, fn_assign, fn_flow
        if press:
            doc._press_canvas = _press_canvasmaker(doc._pw, doc._ph)
        return doc

    def _resolve_foot(make_toc=None):
        """Measure and plan the footnotes, with the TOC already in place.

        The contents pages shift every page number after them, so measuring
        without them would put every note one spread out.
        """
        probe = {}

        def _measure(reserve, assign):
            fd, tmp = tempfile.mkstemp(suffix='.pdf')
            os.close(fd)
            probe.clear()
            story = _build_story(manuscript, preset, meta, fonts, st, head_font,
                                 has_cover=bool(cover), avail_w=avail_w, hyph=hyph,
                                 fn_measure=True, fn_probe=probe,
                                 toc_flowables=make_toc() if make_toc else None)
            d = _make_doc(tmp)
            d._fn_reserve, d._fn_assign = reserve, assign
            d.build(story)
            return tmp
        found_reserve, found_assign, homeless = _resolve_footnotes(
            _measure, manuscript['chapters'], preset, fonts, st, avail_w, text_h,
            probe=probe)
        fn_reserve.clear(); fn_reserve.update(found_reserve)
        fn_assign.clear(); fn_assign.update(found_assign)
        unplaced_notes.clear(); unplaced_notes.extend(homeless)

    if foot_notes and not meta.get('include_toc'):
        try:
            _resolve_foot()
        except ImportError:
            # no PyMuPDF: keep the notes, at the back, rather than lose them
            preset = dict(preset)
            preset['endnotes'] = dict(preset.get('endnotes', {}), placement='end')
            foot_notes = False

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

        if foot_notes:
            try:
                # a fresh TOC per pass: platypus flowables carry layout state, and
                # a list already drawn once comes out blank the second time
                _resolve_foot(lambda: _build_toc(entries, body_start, avail_w,
                                                 preset, fonts, st,
                                                 folio_offset=toc_pages))
            except ImportError:
                preset = dict(preset)
                preset['endnotes'] = dict(preset.get('endnotes', {}), placement='end')
                foot_notes = False

        # Pass 2 — with TOC injected
        story2 = _build_story(manuscript, preset, meta, fonts, st, head_font,
                               has_cover=bool(cover), avail_w=avail_w, hyph=hyph,
                               toc_flowables=_build_toc(entries, body_start, avail_w,
                                                        preset, fonts, st,
                                                        folio_offset=toc_pages))
        doc2 = _make_doc(out_path)
        doc2.build(story2)
        page_count = doc2.page
        unplaced_notes.extend(set(fn_flow) - doc2._fn_drawn)
    else:
        story = _build_story(manuscript, preset, meta, fonts, st, head_font,
                             has_cover=bool(cover), avail_w=avail_w, hyph=hyph)
        doc = _make_doc(out_path)
        doc.build(story)
        page_count = doc.page
        unplaced_notes.extend(set(fn_flow) - doc._fn_drawn)
    if cover_path:
        try:
            os.remove(cover_path)
        except OSError:
            pass
    return {
        'page_count':     page_count,
        'notes_unplaced': len(unplaced_notes),
        'font_family':    fonts['family'],
        'font_fallback':  fonts['fallback'],
        'font_details':   fonts['details'],
        'fonts_embedded': not fonts['fallback'],
        'press':          bool(press),
    }
