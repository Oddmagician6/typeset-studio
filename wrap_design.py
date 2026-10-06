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
Shapes are `rect`, `ellipse` and `rule` (a line `w` long, `weight` points
thick), with an optional `stroke` colour and `stroke_w` in points. A picture
can be turned by quarters (`turn`: 0, 90, 180, 270, clockwise). A `barcode`
is the ISBN box (see `barcode_parts`). Any element with `hidden` is left out
of the PDF as it is left off the screen.

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


def drawable_art(fname):
    """`art_file`, or None when the file is there but can't be drawn (damaged,
    or not a picture): such a file stopped the whole wrap from being made."""
    path = art_file(fname)
    return path if path and not engine.picture_unreadable(path) else None


def font_name(fname):
    """Register a font-library file with ReportLab once; return its face name."""
    path = font_file(fname)
    if not path:
        raise ValueError(f'Font not found: {fname}')
    return engine.font_for(path)


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
    """[(line, x offset, baseline offset, words)] in points from the element's
    top-left. `words` is None, or for a justified line [(word, x offset)]: the
    line's words spread to fill the box."""
    face = pdfmetrics.getFont(font_name(el['font'])).face
    size, lead = el['size'], el.get('leading', 1.2)
    asc = face.ascent / 1000.0 * size
    box = el.get('w', 0) * 72.0
    blank = blank_of(el)
    align = el.get('align', 'left')
    lines = break_lines(el)
    ends = para_ends(el, lines) if align == 'justify' and box else None
    out, down = [], 0.0
    for i, line in enumerate(lines):
        lw = line_width(line, el)
        words = None
        if align == 'center':
            dx = (box - lw) / 2.0 if box else -lw / 2.0
        elif align == 'right':
            dx = (box - lw) if box else -lw
        else:
            dx = 0.0
            if ends and not ends[i]:
                words = justify(line, el, box)
        out.append((line, dx, asc + down, words))
        down += size * lead * (blank if not line.strip() else 1.0)
    return out


def para_ends(el, lines):
    """Whether each of a text box's lines ends its paragraph - the lines a
    justified box leaves ragged. Broken a paragraph at a time with the engine's
    own breaker, which is how `break_lines` broke them."""
    ends = []
    for para in (str(el.get('text', '')).splitlines() or ['']):
        n = len(engine._wrap_tracked(para, font_name(el['font']), el['size'],
                                     el['w'] * 72.0, el.get('tracking', 0.0)))
        ends += [False] * (n - 1) + [True]
    return ends if len(ends) == len(lines) else [True] * len(lines)


def justify(line, el, box):
    """[(word, x offset)] spreading a line's words across `box` points: the
    room left over shared equally between the spaces. None when there is
    nothing to spread (one word, or a line already as wide as the box)."""
    words = line.split(' ')
    lw = line_width(line, el)
    if len(words) < 2 or lw >= box:
        return None
    extra = (box - lw) / (len(words) - 1)
    tr, font, size = el.get('tracking', 0.0), font_name(el['font']), el['size']
    out, k = [], 0
    for i, wd in enumerate(words):
        prefix = line[:k]                  # where the word starts in the set line
        out.append((wd, pdfmetrics.stringWidth(prefix, font, size) + tr * len(prefix)
                    + extra * i))
        k += len(wd) + 1
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


def turn_of(el):
    """A picture's quarter turn, clockwise: 0, 90, 180 or 270."""
    try:
        t = int(el.get('turn', 0)) % 360
    except (TypeError, ValueError):
        return 0
    return t if t in (0, 90, 180, 270) else 0


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
        if el.get('hidden'):
            continue
        x, y, w, h = el_rect(g, el)
        X, Ytop = x * inch, H - y * inch
        c.saveState()
        alpha = float(el.get('opacity', 1.0))
        c.setFillAlpha(alpha)
        if kind in ('rect', 'ellipse') and w > 0 and h > 0:
            # no colour at all is black, as shapes always were; '' or 'none' is no fill
            fill = el['color'] if 'color' in el else (None if el.get('stroke') else '#000000')
            fill = None if fill in ('', 'none') else fill
            stroke = _stroke(c, el, alpha)
            if fill:
                c.setFillColor(HexColor(fill), alpha=alpha)
            if fill or stroke:
                if kind == 'rect':
                    c.rect(X, Ytop - h * inch, w * inch, h * inch,
                           stroke=1 if stroke else 0, fill=1 if fill else 0)
                else:
                    c.ellipse(X, Ytop - h * inch, X + w * inch, Ytop,
                              stroke=1 if stroke else 0, fill=1 if fill else 0)
        elif kind == 'rule' and w > 0:
            c.setStrokeColor(HexColor(el.get('color') or '#000000'), alpha=alpha)
            c.setLineWidth(rule_weight(el))
            mid = Ytop - rule_weight(el) / 2.0
            c.line(X, mid, X + w * inch, mid)
        elif kind == 'barcode' and w > 0 and h > 0:
            draw_barcode(c, el, X, Ytop, w * inch, h * inch)
        elif kind == 'image' and drawable_art(el.get('src')) and w > 0 and h > 0:
            img = ImageReader(art_file(el['src']))
            iw, ih = img.getSize()
            turn = turn_of(el)
            if turn in (90, 270):
                iw, ih = ih, iw                  # fitted as it will stand once turned
            dw, dh, ox, oy = image_fit(iw, ih, w * inch, h * inch, el)
            p = c.beginPath()
            p.rect(X, Ytop - h * inch, w * inch, h * inch)
            c.clipPath(p, stroke=0, fill=0)
            if turn:
                # about the centre of where the turned picture sits; clockwise
                # on the page is a negative turn in PDF space
                c.translate(X + ox + dw / 2.0, Ytop - oy - dh / 2.0)
                c.rotate(-turn)
                uw, uh = (dh, dw) if turn in (90, 270) else (dw, dh)
                c.drawImage(img, -uw / 2.0, -uh / 2.0, uw, uh)
            else:
                c.drawImage(img, X + ox, Ytop - oy - dh, dw, dh)
        elif kind == 'vector' and w > 0 and h > 0:
            draw_vector(c, el, X, Ytop, w * inch, h * inch)
        elif kind == 'text' and font_file(el.get('font')):
            layout = text_layout(el)
            lines[el.get('id', '')] = [ln for ln, _, _, _ in layout]
            c.translate(X, Ytop)
            if el.get('rotate') == 90:                        # reads top to bottom
                c.rotate(-90)
            c.setFillColor(HexColor(el.get('color') or '#000000'), alpha=alpha)
            for line, dx, base, words in layout:
                for run, x in (words or [(line, dx)]):
                    t = c.beginText(x, -base)
                    t.setFont(font_name(el['font']), el['size'])
                    t.setCharSpace(el.get('tracking', 0.0))
                    t.textOut(run)
                    c.drawText(t)
        c.restoreState()
    c.showPage()
    c.save()
    return lines


def _stroke(c, el, alpha):
    """Set a shape's outline, if it has one; return whether it does."""
    col = el.get('stroke')
    try:
        sw = float(el.get('stroke_w', 1.0))
    except (TypeError, ValueError):
        sw = 1.0
    if not col or sw <= 0:
        return False
    c.setStrokeColor(HexColor(col), alpha=alpha)
    c.setLineWidth(sw)
    return True


def rule_weight(el):
    """A rule's thickness in points."""
    try:
        return min(max(float(el.get('weight', 1.0)), 0.1), 36.0)
    except (TypeError, ValueError):
        return 1.0


# ---- the ISBN barcode -----------------------------------------------------------
# EAN-13, the barcode on a book's back cover: the ISBN-13 itself, with an
# optional five-digit add-on (EAN-5) to its right - the price code, which
# IngramSpark expects (90000 means "no price printed"). Encoded here rather
# than with ReportLab's widget so the editor can draw exactly the same bars:
# `barcode_parts` is served to it as JSON.

_L = ('0001101', '0011001', '0010011', '0111101', '0100011',
      '0110001', '0101111', '0111011', '0110111', '0001011')
_R = tuple(''.join('1' if b == '0' else '0' for b in code) for code in _L)
_G = tuple(code[::-1] for code in _R)
_PARITY13 = ('LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
             'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL')
_PARITY5 = ('GGLLL', 'GLGLL', 'GLLGL', 'GLLLG', 'LGGLL',
            'LLGGL', 'LLLGG', 'LGLGL', 'LGLLG', 'LLGLG')
_MM = 72.0 / 25.4                       # points per millimetre


def isbn13(raw):
    """(the ISBN-13 as 13 digits, None) or (None, why not). Takes an ISBN-13
    or an ISBN-10 (turned into its 978 form), with or without hyphens."""
    digits = ''.join(ch for ch in str(raw or '') if ch.isdigit() or ch in 'xX')
    if len(digits) == 10:
        body = digits[:9]
        if not body.isdigit():
            return None, 'An ISBN-10 has nine digits and a check character.'
        tens = sum((10 - i) * int(d) for i, d in enumerate(body))
        check = (11 - tens % 11) % 11
        if digits[9].upper() != ('X' if check == 10 else str(check)):
            return None, 'That ISBN-10 has the wrong check digit.'
        digits = '978' + body
        return digits + str(_ean_check(digits)), None
    if len(digits) != 13 or not digits.isdigit():
        return None, 'An ISBN has 13 digits (or 10, for an old one).'
    if not digits.startswith(('978', '979')):
        return None, 'A book ISBN starts 978 or 979.'
    if int(digits[12]) != _ean_check(digits[:12]):
        return None, 'That ISBN has the wrong check digit - one of the numbers is mistyped.'
    return digits, None


def _ean_check(twelve):
    return (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(twelve)) % 10) % 10


def _ean13_modules(code):
    left = ''.join({'L': _L, 'G': _G}[par][int(d)]
                   for par, d in zip(_PARITY13[int(code[0])], code[1:7]))
    right = ''.join(_R[int(d)] for d in code[7:])
    return '101' + left + '01010' + right + '101'


def _ean5_modules(five):
    d = [int(ch) for ch in five]
    par = _PARITY5[(3 * (d[0] + d[2] + d[4]) + 9 * (d[1] + d[3])) % 10]
    return '1011' + '01'.join({'L': _L, 'G': _G}[p][x] for p, x in zip(par, d))


def barcode_parts(el, w_in, h_in):
    """What a barcode box draws, in inches from its top-left (y down):
    {'bars': [[x, y, w, h]], 'texts': [[text, x, baseline, size, anchor]],
     'error': None or why the ISBN can't be used}. With no usable ISBN it is the
    plain reserve: an empty box, captioned unless `caption` is false."""
    out = {'bars': [], 'texts': [], 'error': None}
    raw = str(el.get('isbn') or '').strip()
    if not raw:
        if el.get('caption', True):
            out['texts'].append(['ISBN / barcode area', w_in / 2.0, h_in / 2.0 + 2 / 72.0,
                                 7.5, 'middle'])
        return out
    code, err = isbn13(raw)
    addon = ''.join(ch for ch in str(el.get('addon') or '') if ch.isdigit())
    if not err and addon and len(addon) != 5:
        err = 'The price code is five digits (90000 for none).'
    if err:
        out['error'] = err
        return out
    main = _ean13_modules(code)
    extra = _ean5_modules(addon) if addon else ''
    # quiet zones (11 and 7 modules), a 9-module gap before the add-on
    span = 11 + len(main) + (9 + len(extra) if extra else 0) + 7
    pad = 0.08
    m = min(0.33 * _MM / 72.0, (w_in - 2 * pad) / span)   # module width, inches; 100% at most
    digits = m * 9 * 72.0 / 1.0                             # digit size in points, ~9 modules
    size = min(max(digits * 0.95, 6.0), 10.0)
    top = pad + size / 72.0 * 1.25                          # room for "ISBN ..." above
    bar_h = h_in - top - pad - size / 72.0 * 1.15           # room for the digits below
    x0 = (w_in - span * m) / 2.0 + 11 * m
    out['texts'].append(['ISBN ' + code, x0 + len(main) * m / 2.0, pad + size / 72.0 * 0.95,
                         size, 'middle'])
    guards = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))
    for i, j in _runs(main):                                # guard bars run 5 modules longer
        out['bars'].append([x0 + i * m, top, (j - i) * m, bar_h + (m * 5 if i in guards else 0)])
    base = top + bar_h + size / 72.0 * 0.95
    out['texts'].append([code[0], x0 - m * 4, base, size, 'middle'])
    out['texts'].append([code[1:7], x0 + m * (3 + 21), base, size, 'middle'])
    out['texts'].append([code[7:], x0 + m * (50 + 21), base, size, 'middle'])
    if extra:
        ax = x0 + (len(main) + 9) * m
        lift = size / 72.0 * 1.15                           # its digits sit above its bars
        for i, j in _runs(extra):
            out['bars'].append([ax + i * m, top + lift, (j - i) * m, bar_h + m * 5 - lift])
        out['texts'].append([addon, ax + len(extra) * m / 2.0, top + lift - size / 72.0 * 0.25,
                             size, 'middle'])
    return out


def _runs(pattern):
    """(start, end) of each run of dark modules in a bar pattern."""
    i = 0
    while i < len(pattern):
        if pattern[i] == '1':
            j = i
            while j < len(pattern) and pattern[j] == '1':
                j += 1
            yield i, j
            i = j
        else:
            i += 1


def barcode_font(el):
    """The face a barcode's digits and label are set in: its own, or the first
    regular face in the library."""
    if font_file(el.get('font')):
        return el['font']
    lib = sorted(f for f in os.listdir(FONT_DIR) if f.lower().endswith('.ttf')) if FONT_DIR else []
    return next((f for f in lib if 'Regular' in f), lib[0] if lib else None)


def draw_barcode(c, el, X, Ytop, bw, bh):
    """The barcode box: white, outlined in grey while it is only a reserve (as
    the template wraps draw it), with the EAN-13 in black once it has an ISBN."""
    parts = barcode_parts(el, bw / inch, bh / inch)
    plain = not parts['bars']
    c.setFillColorRGB(1, 1, 1)
    if plain and el.get('outline', True):
        c.setStrokeGray(0.6)
        c.setLineWidth(0.6)
        c.rect(X, Ytop - bh, bw, bh, stroke=1, fill=1)
    else:
        c.rect(X, Ytop - bh, bw, bh, stroke=0, fill=1)
    c.setFillGray(0.55 if plain else 0.0)
    for bx, by, bw_, bh_ in parts['bars']:
        c.rect(X + bx * inch, Ytop - (by + bh_) * inch, bw_ * inch, bh_ * inch, stroke=0, fill=1)
    face = barcode_font(el)
    if not face:
        return
    for text, tx, base, size, _ in parts['texts']:
        t = c.beginText(X + tx * inch - pdfmetrics.stringWidth(text, font_name(face), size) / 2.0,
                        Ytop - base * inch)
        t.setFont(font_name(face), size)
        t.setCharSpace(0)
        t.textOut(text)
        c.drawText(t)


def reserve_box(el):
    """(x, y, w, h) relative to its panel if `el` is the engine's barcode reserve
    kept as drawing: one white rectangle with a thin grey outline, of the BARCODE
    size - what "Customise this design" makes of a template's reserve."""
    if el.get('type') != 'vector' or el.get('fill') or len(el.get('ops') or []) != 1:
        return None
    op = el['ops'][0]
    st = op[-1]
    if op[0] != 'path' or st.get('fill') != '#ffffff' or st.get('stroke') != '#999999':
        return None
    pts = [(sg[1], sg[2]) for sg in op[1] if sg[0] in ('M', 'L')]
    if not pts:
        return None
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if abs(x1 - x0 - engine.BARCODE[0]) > 0.01 or abs(y1 - y0 - engine.BARCODE[1]) > 0.01:
        return None
    base_x = el.get('x', 0) if 'cx' not in el else None
    if base_x is None:
        return None
    return base_x + x0, el.get('y', 0) + y0, x1 - x0, y1 - y0


# ---- designs saved by older versions ------------------------------------------------

def upgrade(design):
    """A design saved before 1.3.0, brought up to date; anything else unchanged.

    Before 1.3.0 there was no `barcode` element. The designer's own box was a
    white `rect` labelled "Barcode area" (1.2.5-1.2.9), and "Customise this
    design" kept a template's reserve as a grey-outlined `vector` with its
    "ISBN / barcode area" caption as a separate text (1.2.7-1.2.9). Either
    becomes a `barcode` element, so it can take an ISBN and the designer's
    checks find it. Each prints as it did: the plain rect without an outline
    or caption, the template's reserve with both. A design that already has a
    barcode (one added in 1.3.0 beside the old box) is left alone, so the two
    aren't stacked."""
    if not isinstance(design, dict) or not isinstance(design.get('elements'), list):
        return design
    els = design['elements']
    if any(isinstance(e, dict) and e.get('type') == 'barcode' for e in els):
        return design
    out = [dict(e) if isinstance(e, dict) else e for e in els]
    for i, el in enumerate(out):
        if (isinstance(el, dict) and el.get('type') == 'rect' and el.get('label') == 'Barcode area'
                and not el.get('fill') and not el.get('stroke')
                and str(el.get('color', '')).lower() in ('#ffffff', '#fff')):
            bc = {k: v for k, v in el.items() if k not in ('type', 'color', 'stroke', 'stroke_w')}
            bc.update(type='barcode', caption=False, outline=False, isbn='', addon='', locked=True)
            out[i] = bc
            return dict(design, elements=out)
    for i, el in enumerate(out):
        box = reserve_box(el) if isinstance(el, dict) else None
        if not box:
            continue
        bx, by, bw, bh = box
        cap = next((t for t in out if isinstance(t, dict) and t.get('type') == 'text'
                    and t.get('text') == 'ISBN / barcode area' and t.get('anchor') == el.get('anchor')
                    and 'cx' not in t
                    and bx <= t.get('x', 0) + t.get('w', 0) / 2.0 <= bx + bw
                    and by <= t.get('y', 0) <= by + bh), None)
        if cap is None:
            continue
        ids = {e.get('id') for e in out if isinstance(e, dict)}
        out[i] = {'id': 'barcode' if 'barcode' not in ids else el.get('id', 'barcode'),
                  'type': 'barcode', 'anchor': el.get('anchor', 'back'),
                  'x': round(bx, 6), 'y': round(by, 6), 'w': round(bw, 6), 'h': round(bh, 6),
                  'font': cap.get('font'), 'locked': True, 'label': 'Barcode area',
                  'caption': not cap.get('hidden'), 'isbn': '', 'addon': ''}
        if el.get('hidden'):
            out[i]['hidden'] = True
        out.remove(cap)
        return dict(design, elements=out)
    return design


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
    return any(el.get('type') == 'text' and el.get('anchor') == 'spine' and not el.get('hidden') and
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


def missing(design):
    """[(what, [names])] for what a design names that isn't there any more: a
    text box whose font has left the library isn't printed at all, nor is a
    picture whose file has gone - so the checks have to say so."""
    fonts, pictures = set(), set()
    for el in design.get('elements', []):
        if not isinstance(el, dict) or el.get('hidden'):
            continue
        if el.get('type') == 'text' and not font_file(el.get('font')) \
                and (el.get('text') or '').strip():
            fonts.add(os.path.basename(str(el.get('font') or '')) or '(no font)')
        elif el.get('type') == 'image' and el.get('src') and not drawable_art(el.get('src')):
            pictures.add(os.path.basename(str(el['src'])))
    out = []
    if fonts:
        out.append(('Text left off the cover - its font is not in the font library',
                    sorted(fonts)))
    if pictures:
        out.append(('Pictures left off the cover - the file is gone or can’t be read',
                    sorted(pictures)))
    return out


def placed_images(design, g):
    """[(path, w, h)] in inches for every picture in a design that can be drawn - what
    a resolution check measures each one against."""
    out = []
    for el in design.get('elements', []):
        if el.get('type') != 'image' or el.get('hidden'):
            continue
        path = drawable_art(el.get('src'))
        _, _, w, h = el_rect(g, el)
        if path and w > 0 and h > 0:
            z = zoom_of(el)
            # a quarter-turned picture spends its width on the box's height
            out.append((path, h * z, w * z) if turn_of(el) in (90, 270) else (path, w * z, h * z))
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
