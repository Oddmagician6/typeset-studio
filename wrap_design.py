"""Freeform wrap designs (#72) - the design document and its PDF.

Beta, grown from the phase A spike (spikes/wrap_designer/). A design is JSON:
a list of elements placed in inches relative to the panel they are anchored
to, so a wider spine (more pages, thicker paper) moves the front-panel elements
with the front panel. `engine.wrap_geometry` is the single source of every
measurement, as for the template wraps.

    {"elements": [
      {"id": "art", "type": "image", "fill": "front", "src": "dusk.png"},
      {"id": "title", "type": "text", "anchor": "front", "x": 0.5, "y": 0.9, "w": 5,
       "text": "The Salt Road", "font": "EBGaramond-Bold.ttf", "size": 46,
       "leading": 1.05, "color": "#fbf3e2", "align": "center", "tracking": 0.5},
      {"id": "spine", "type": "text", "anchor": "spine", "cx": 0.11, "rotate": 90, ...}
    ]}

`fill` on a rect or image covers that panel out to the bleed (`front`, `back`,
`spine`, `sheet`) and ignores x/y/w/h. `cx` places an element from the centre
of its panel instead of its left edge. `rotate: 90` sets text reading top to
bottom, for a spine.

Text is broken into lines by `engine._wrap_tracked`, measured with ReportLab's
TTF advance widths. The editor (static/wrap_text.js) is sent those same tables
by `metrics()` and runs the same algorithm, so a blurb breaks where the PDF
breaks it - measured identical over 17,640 cases in the spike.
"""

import os

import engine
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

# Set by app.py: where the font library and the art a design may use live.
FONT_DIR = ''
ART_DIRS = []

ANCHORS = ('front', 'back', 'spine', 'sheet')


def font_file(fname):
    """The path of a font-library file, or None. Only a bare .ttf name is accepted."""
    base = os.path.basename(fname or '')
    if not base.lower().endswith('.ttf'):
        return None
    path = os.path.join(FONT_DIR, base)
    return path if os.path.isfile(path) else None


def art_file(fname):
    """The path of an art file a design names, from the first folder that has it."""
    base = os.path.basename(fname or '')
    for d in ART_DIRS:
        path = os.path.join(d, base)
        if base and os.path.isfile(path):
            return path
    return None


def font_name(fname):
    """Register a font-library file with ReportLab once; return its face name."""
    path = font_file(fname)
    if not path:
        raise ValueError(f'Font not found: {fname}')
    name = 'WD-' + os.path.splitext(os.path.basename(path))[0]
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, path))
    return name


def metrics(fname):
    """The advance widths ReportLab measures with, for the editor to measure with too.

    Widths are in 1/1000 em keyed by code point, `default` covering the rest.
    ReportLab's `stringWidth` for a TTF is 0.001 * size * the sum of these, with
    no kerning and no ligatures, so the editor turns both off. `float` says the
    widths are floats, which Python sums with compensation - the editor has to
    sum them the same way or a line that just fits can break differently.
    """
    face = pdfmetrics.getFont(font_name(fname)).face
    vals = list(face.charWidths.values()) + [face.defaultWidth]
    return {'widths': {str(cp): w for cp, w in face.charWidths.items()},
            'default': face.defaultWidth, 'ascent': face.ascent, 'descent': face.descent,
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


def panel_width(g, anchor):
    return {'back': g['panel_w'], 'front': g['panel_w'],
            'spine': g['spine_w']}.get(anchor, g['wrap_w'])


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


def el_rect(g, el):
    """An element's (x, y, w, h) on the sheet, in inches."""
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


def build_pdf(design, dims, out_path):
    """Render a design to a print-size wrap PDF. Returns {element id: lines}.

    An element that names a font or image that isn't there is skipped rather
    than failing the whole wrap; the editor flags it before it gets here.
    """
    g = engine.wrap_geometry(dims)
    W, H = g['wrap_w'] * inch, g['wrap_h'] * inch
    c = rl_canvas.Canvas(out_path, pagesize=(W, H))
    lines = {}
    for el in design.get('elements', []):
        kind = el.get('type')
        x, y, w, h = el_rect(g, el)
        X, Ytop = x * inch, H - y * inch
        c.saveState()
        c.setFillAlpha(float(el.get('opacity', 1.0)))
        if kind == 'rect':
            c.setFillColor(HexColor(el.get('color') or '#000000'))
            c.rect(X, Ytop - h * inch, w * inch, h * inch, stroke=0, fill=1)
        elif kind == 'image' and art_file(el.get('src')) and w > 0 and h > 0:
            img = ImageReader(art_file(el['src']))
            iw, ih = img.getSize()
            s = max(w * inch / iw, h * inch / ih)            # cover-fit
            dw, dh = iw * s, ih * s
            p = c.beginPath()
            p.rect(X, Ytop - h * inch, w * inch, h * inch)
            c.clipPath(p, stroke=0, fill=0)
            c.drawImage(img, X + (w * inch - dw) / 2, Ytop - h * inch + (h * inch - dh) / 2,
                        dw, dh)
        elif kind == 'text' and font_file(el.get('font')):
            layout = text_layout(el)
            lines[el.get('id', '')] = [ln for ln, _, _ in layout]
            c.translate(X, Ytop)
            if el.get('rotate') == 90:                        # reads top to bottom
                c.rotate(-90)
            c.setFillColor(HexColor(el.get('color') or '#000000'))
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


def stand_in_art(path):
    """A generated placeholder for cover art (a dusk sky, a sun, hills), so the
    designer has something to place before the writer uploads their own."""
    if os.path.exists(path):
        return path
    from PIL import Image, ImageDraw
    w, h = 1200, 1800
    im = Image.new('RGB', (1, h))
    for yy in range(h):
        t = yy / h
        im.putpixel((0, yy), (int(40 + 180 * t), int(50 + 90 * t), int(110 - 40 * t)))
    im = im.resize((w, h))
    d = ImageDraw.Draw(im)
    d.ellipse((w * 0.3, h * 0.45, w * 0.7, h * 0.45 + w * 0.4), fill=(250, 214, 140))
    d.polygon([(0, h), (0, h * 0.72), (w * 0.35, h * 0.62), (w * 0.7, h * 0.74),
               (w, h * 0.66), (w, h)], fill=(30, 26, 40))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path)
    return path
