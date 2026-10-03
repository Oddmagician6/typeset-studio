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

`fill` on a rect, image or vector covers that panel out to the bleed (`front`,
`back`, `spine`, `sheet`) and ignores x/y/w/h. `cx` places an element from the
centre of its panel instead of its left edge. `rotate: 90` sets text reading
top to bottom, for a spine; `blank` is how tall an empty line in it is (0.6
keeps a template blurb's paragraph gap).

A `vector` element is drawing kept as paths - a template's frame, ornament or
shading, from "Customise this design" (wrap_convert.py); see `draw_vector`.

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
    blank = blank_of(el)
    out, down = [], 0.0
    for line in break_lines(el):
        lw = line_width(line, el)
        align = el.get('align', 'left')
        if align == 'center':
            dx = (box - lw) / 2.0 if box else -lw / 2.0
        elif align == 'right':
            dx = (box - lw) if box else -lw
        else:
            dx = 0.0
        out.append((line, dx, asc + down))
        down += size * lead * (blank if not line.strip() else 1.0)
    return out


def blank_of(el):
    """How tall an empty line is, in lines: 1 by default; a template's blurb
    leaves 0.6 of a line between paragraphs, and a design made from it keeps that."""
    try:
        return min(max(float(el.get('blank', 1.0)), 0.0), 2.0)
    except (TypeError, ValueError):
        return 1.0


def zoom_of(el):
    try:
        return min(max(float(el.get('zoom', 1.0)), 1.0), 8.0)
    except (TypeError, ValueError):
        return 1.0


def focus_of(el, key):
    try:
        return min(max(float(el.get(key, 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.5


def image_fit(iw, ih, bw, bh, el):
    """How a picture fills its box: (width, height, x, y), x and y from the box's
    top-left, in the box's units.

    Cover-fit, then `zoom` (1 = just covering, up to 8), then placed so the
    focal point `fx`/`fy` (0..1 across the overflow, 0.5 = centred) is what the
    box shows - CSS `object-position` in fractions. The editor's wrap_designer.js
    does the same arithmetic, so the crop on screen is the crop in print.
    """
    s = max(bw / iw, bh / ih) * zoom_of(el)
    dw, dh = iw * s, ih * s
    return dw, dh, (bw - dw) * focus_of(el, 'fx'), (bh - dh) * focus_of(el, 'fy')


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
        alpha = float(el.get('opacity', 1.0))
        c.setFillAlpha(alpha)
        if kind == 'rect':
            c.setFillColor(HexColor(el.get('color') or '#000000'), alpha=alpha)
            c.rect(X, Ytop - h * inch, w * inch, h * inch, stroke=0, fill=1)
        elif kind == 'image' and art_file(el.get('src')) and w > 0 and h > 0:
            img = ImageReader(art_file(el['src']))
            iw, ih = img.getSize()
            dw, dh, ox, oy = image_fit(iw, ih, w * inch, h * inch, el)
            p = c.beginPath()
            p.rect(X, Ytop - h * inch, w * inch, h * inch)
            c.clipPath(p, stroke=0, fill=0)
            c.drawImage(img, X + ox, Ytop - oy - dh, dw, dh)
        elif kind == 'vector' and w > 0 and h > 0:
            draw_vector(c, el, X, Ytop, w * inch, h * inch)
        elif kind == 'text' and font_file(el.get('font')):
            layout = text_layout(el)
            lines[el.get('id', '')] = [ln for ln, _, _ in layout]
            c.translate(X, Ytop)
            if el.get('rotate') == 90:                        # reads top to bottom
                c.rotate(-90)
            c.setFillColor(HexColor(el.get('color') or '#000000'), alpha=alpha)
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


def _vscale(el, bw, bh):
    """Scale from a vector element's own drawing (`vw` x `vh` inches) to its box."""
    try:
        vw, vh = float(el.get('vw') or 0), float(el.get('vh') or 0)
    except (TypeError, ValueError):
        vw = vh = 0.0
    return (bw / (vw * inch) if vw > 0 else 1.0), (bh / (vh * inch) if vh > 0 else 1.0)


def draw_vector(c, el, X, Ytop, bw, bh):
    """A `vector` element: shapes a template drew, kept as its own paths.

    `ops` are in inches from the box's top-left (y down) at the size `vw` x `vh`
    they were drawn at; a resized box stretches the paths but not the line
    widths, as the editor does. Each op carries its own fill / stroke style:
        ['path', [['M', x, y], ['L', x, y], ['C', x1, y1, x2, y2, x, y], ['Z']], style]
        ['ellipse', cx, cy, rx, ry, style]
        ['grad', x, y, w, h, top colour, bottom colour, y of top, y of bottom, style]
    """
    sx, sy = _vscale(el, bw, bh)

    def P(x, y):
        return X + float(x) * inch * sx, Ytop - float(y) * inch * sy

    for op in el.get('ops') or []:
        if not isinstance(op, list) or not op or not isinstance(op[-1], dict):
            continue
        st = op[-1]
        try:
            c.saveState()
            fill, stroke = st.get('fill'), st.get('stroke')
            op_a = float(el.get('opacity', 1.0))
            # a ReportLab colour sets its own alpha, so the alpha goes in with it
            if fill:
                c.setFillColor(HexColor(fill), alpha=op_a * float(st.get('fa', 1.0)))
            if stroke:
                c.setStrokeColor(HexColor(stroke), alpha=op_a * float(st.get('sa', 1.0)))
                c.setLineWidth(float(st.get('lw', 1.0)))
                c.setLineCap(int(st.get('cap', 0)))
                c.setLineJoin(int(st.get('join', 0)))
                if st.get('dash'):
                    c.setDash([float(v) for v in st['dash']])
            if op[0] == 'path':
                p = c.beginPath()
                for seg in op[1]:
                    if seg[0] == 'M':
                        p.moveTo(*P(seg[1], seg[2]))
                    elif seg[0] == 'L':
                        p.lineTo(*P(seg[1], seg[2]))
                    elif seg[0] == 'C':
                        p.curveTo(*P(seg[1], seg[2]), *P(seg[3], seg[4]), *P(seg[5], seg[6]))
                    elif seg[0] == 'Z':
                        p.close()
                c.drawPath(p, stroke=1 if stroke else 0, fill=1 if fill else 0)
            elif op[0] == 'ellipse':
                cx, cy = P(op[1], op[2])
                rx, ry = float(op[3]) * inch * sx, float(op[4]) * inch * sy
                c.ellipse(cx - rx, cy - ry, cx + rx, cy + ry,
                          stroke=1 if stroke else 0, fill=1 if fill else 0)
            elif op[0] == 'grad':
                x0, y0 = P(op[1], op[2])
                x1, y1 = P(float(op[1]) + float(op[3]), float(op[2]) + float(op[4]))
                p = c.beginPath()
                p.rect(x0, y1, x1 - x0, y0 - y1)
                c.clipPath(p, stroke=0, fill=0)
                c.setFillAlpha(op_a * float(st.get('fa', 1.0)))
                c.linearGradient(x0, P(0, op[7])[1], x0, P(0, op[8])[1],
                                 [HexColor(op[5]), HexColor(op[6])], extend=True)
        except (TypeError, ValueError, IndexError, KeyError):
            pass                         # a malformed op is skipped, not the wrap
        finally:
            c.restoreState()


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


# ---- a design as a book's cover (phase B) -----------------------------------------

def has_spine_text(design):
    return any(el.get('type') == 'text' and el.get('anchor') == 'spine' and
               str(el.get('text', '')).strip() for el in design.get('elements', []))


def summary(g, design):
    """What `engine.build_cover_wrap` reports about a wrap, for a designed one, so
    the print package's page and spec sheet read it the same way."""
    return {'wrap_w': round(g['wrap_w'], 3), 'wrap_h': round(g['wrap_h'], 3),
            'spine_w': round(g['spine_w'], 4), 'spine_text': has_spine_text(design),
            'binding': g['binding'], 'front': 'design',
            'wrap': round(g['wrap'], 4), 'hinge': round(g['hinge'], 4),
            'flap': round(g['flap'], 4), 'panel_w': round(g['panel_w'], 4)}


def front_trim(g):
    """The finished front cover on the sheet, in inches (x, y, w, h; y down): the
    trim, not the panel - on a jacket the panel is the board, a little larger."""
    return g['front_x'], g['edge'] + g['board_ext'], g['trim_w'], g['trim_h']


def placed_images(design, g):
    """[(path, w, h)] in inches for every picture in a design that exists - what
    a resolution check measures each one against."""
    out = []
    for el in design.get('elements', []):
        if el.get('type') != 'image':
            continue
        path = art_file(el.get('src'))
        _, _, w, h = el_rect(g, el)
        if path and w > 0 and h > 0:
            z = zoom_of(el)
            out.append((path, w * z, h * z))
    return out


def render_front(design, dims, out_path, dpi=300):
    """The front cover of a design as a JPG: page 1 of the book, the ebook's cover
    and the store listing all use it, the way they use uploaded cover art."""
    import tempfile
    import fitz
    from PIL import Image
    g = engine.wrap_geometry(dims)
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        build_pdf(design, dims, tmp)
        x, y, w, h = front_trim(g)
        with fitz.open(tmp) as doc:
            pix = doc[0].get_pixmap(dpi=dpi, alpha=False,
                                    clip=fitz.Rect(x * 72, y * 72, (x + w) * 72, (y + h) * 72))
            im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            # The panel rarely starts on a whole pixel, and the clip rounds out to
            # take the partial one: trim back to exactly the trim at this dpi.
            im.crop((0, 0, min(im.width, round(w * dpi)),
                     min(im.height, round(h * dpi)))).save(out_path, 'JPEG', quality=92)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return out_path
