"""Wrap designer spike (#72 phase A) - the design document and its PDF.

A design is JSON: a list of elements, each placed in inches relative to the
panel it is anchored to, so a change of page count (a wider spine) moves the
front-panel elements with the front panel. The engine's `wrap_geometry` is the
single source of every measurement, exactly as for the template wraps.

    {"elements": [
      {"id": "bg-front", "type": "rect", "anchor": "front", "fill": "front",
       "color": "#1f2a44", "opacity": 1},
      {"id": "art", "type": "image", "anchor": "front", "x": 0.5, "y": 1, "w": 5,
       "h": 4, "src": "art.png"},
      {"id": "title", "type": "text", "anchor": "front", "x": 0.5, "y": 5.4,
       "w": 5, "text": "The Salt Road", "font": "EBGaramond-Bold.ttf",
       "size": 40, "leading": 1.1, "color": "#f4e9d0", "align": "center",
       "tracking": 1.5, "rotate": 0}
    ]}

`fill` on a rect or image ignores x/y/w/h and covers that panel out to the
bleed (`front`, `back`, `spine`, `sheet`).

Text is broken into lines by `engine._wrap_tracked` - the cover code's own
greedy breaker - measured with ReportLab's TTF advance widths. The editor gets
those same width tables from `metrics()` and runs the same algorithm, which is
the point the spike exists to test.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import engine
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

FONT_DIR = os.path.join(ROOT, 'fonts')
ART_DIR = os.path.join(HERE, 'art')


def font_name(fname):
    """Register a font-library file with ReportLab once; return its face name."""
    name = 'WD-' + os.path.splitext(os.path.basename(fname))[0]
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, os.path.basename(fname))))
    return name


def metrics(fname):
    """The advance widths ReportLab measures with, for the browser to measure with too.

    Widths are in 1/1000 em, keyed by code point; `default` covers anything
    missing. ReportLab's `stringWidth` for a TTF is 0.001 * size * the sum of
    these, with no kerning and no ligatures - so the editor turns both off.
    """
    face = pdfmetrics.getFont(font_name(fname)).face
    vals = list(face.charWidths.values()) + [face.defaultWidth]
    return {'widths': {str(cp): w for cp, w in face.charWidths.items()},
            'default': face.defaultWidth, 'ascent': face.ascent, 'descent': face.descent,
            # Python sums floats with compensation; the editor must too (wd.js)
            'float': any(isinstance(v, float) for v in vals)}


def break_lines(el):
    """The lines a text element is set in: the engine's breaker, or its own lines."""
    text = el.get('text', '')
    if not el.get('w'):
        return text.splitlines() or ['']
    return engine._wrap_tracked(text, font_name(el['font']), el['size'],
                                el['w'] * 72.0, el.get('tracking', 0.0))


def line_width(line, el):
    tr = el.get('tracking', 0.0)
    return (pdfmetrics.stringWidth(line, font_name(el['font']), el['size'])
            + tr * max(len(line) - 1, 0))


def origin(g, anchor):
    """Top-left of an anchor's panel on the sheet, in inches (y down)."""
    top = g['edge']
    return {'back': (g['back_x'], top), 'spine': (g['spine_x'], top),
            'front': (g['front_x'], top)}.get(anchor, (0.0, 0.0))


def fill_rect(g, which):
    """A panel's rectangle out to the bleed, in inches (x, y, w, h; y down)."""
    H = g['wrap_h']
    if which == 'front':
        return g['front_x'], 0.0, g['wrap_w'] - g['front_x'], H
    if which == 'back':
        return 0.0, 0.0, g['back_x'] + g['panel_w'], H
    if which == 'spine':
        return g['spine_x'], 0.0, g['spine_w'], H
    return 0.0, 0.0, g['wrap_w'], H


def panel_width(g, anchor):
    return {'back': g['panel_w'], 'front': g['panel_w'],
            'spine': g['spine_w']}.get(anchor, g['wrap_w'])


def el_rect(g, el):
    """An element's (x, y, w, h) on the sheet, in inches. `cx` places it from the
    centre of its panel instead of the left edge, so spine text stays centred as
    the spine widens with the page count."""
    if el.get('fill'):
        return fill_rect(g, el['fill'])
    anchor = el.get('anchor', 'sheet')
    ox, oy = origin(g, anchor)
    x = panel_width(g, anchor) / 2 + el['cx'] if 'cx' in el else el.get('x', 0)
    return ox + x, oy + el.get('y', 0), el.get('w', 0), el.get('h', 0)


def text_layout(el):
    """[(line, x offset, baseline offset)] in points from the element's top-left."""
    face = pdfmetrics.getFont(font_name(el['font'])).face
    size, lead = el['size'], el.get('leading', 1.2)
    asc = face.ascent / 1000.0 * size
    box = el.get('w', 0) * 72.0
    out = []
    for i, line in enumerate(break_lines(el)):
        lw = line_width(line, el)
        align = el.get('align', 'left')
        if align == 'center':
            dx = (box - lw) / 2.0 if box else -lw / 2.0
        elif align == 'right':
            dx = (box - lw) if box else -lw
        else:
            dx = 0.0
        out.append((line, dx, asc + i * size * lead))
    return out


def _hex(c):
    from reportlab.lib.colors import HexColor
    return HexColor(c or '#000000')


def build_pdf(design, dims, out_path):
    """Render a design to a print-size wrap PDF. Returns {id: lines} for checking."""
    g = engine.wrap_geometry(dims)
    W, H = g['wrap_w'] * inch, g['wrap_h'] * inch
    c = rl_canvas.Canvas(out_path, pagesize=(W, H))
    lines = {}
    for el in design.get('elements', []):
        x, y, w, h = el_rect(g, el)
        X, Ytop = x * inch, H - y * inch
        c.saveState()
        c.setFillAlpha(el.get('opacity', 1.0))
        if el['type'] == 'rect':
            c.setFillColor(_hex(el.get('color')))
            c.rect(X, Ytop - h * inch, w * inch, h * inch, stroke=0, fill=1)
        elif el['type'] == 'image':
            img = ImageReader(os.path.join(ART_DIR, os.path.basename(el['src'])))
            iw, ih = img.getSize()
            s = max(w * inch / iw, h * inch / ih)            # cover-fit
            dw, dh = iw * s, ih * s
            p = c.beginPath(); p.rect(X, Ytop - h * inch, w * inch, h * inch)
            c.clipPath(p, stroke=0, fill=0)
            c.drawImage(img, X + (w * inch - dw) / 2, Ytop - h * inch + (h * inch - dh) / 2,
                        dw, dh)
        elif el['type'] == 'text':
            layout = text_layout(el)
            lines[el['id']] = [ln for ln, _, _ in layout]
            c.translate(X, Ytop)
            if el.get('rotate') == 90:                        # reads top to bottom
                c.rotate(-90)
            c.setFillColor(_hex(el.get('color')))
            for line, dx, base in layout:
                t = c.beginText(dx, -base)
                t.setFont(font_name(el['font']), el['size'])
                t.setCharSpace(el.get('tracking', 0.0))
                t.textOut(line)
                c.drawText(t)
        c.restoreState()
    c.showPage()
    c.save()
    return lines
