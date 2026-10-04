"""Customise this design (#72, phase C): a template's wrap as designer elements.

Rather than one hand-written converter per design family, the engine's own
wrap painter (`engine.build_cover_wrap`) is run against a canvas that records
instead of drawing. Every call it makes - text, pictures, rules, frames,
gradients - comes back in page points, and is turned into the elements the
designer edits (see wrap_design.py):

* each run of text in one face, size, colour and alignment becomes one text
  box, with its words re-joined so it re-flows when edited, and a box width
  that breaks it into exactly the lines the template set;
* each picture becomes a picture element, with the template's crop as zoom
  and focal point;
* everything else - frames, ornaments, scrims, bands, the background - becomes
  `vector` elements: the template's own paths, grouped into a layer per piece
  ("Frame", "Ornament", ...), which can be moved, resized and recoloured.

So all eight families (and uploaded-art wraps) convert the same way, and a
conversion is right by construction: the design builds the same picture the
template does. `test_wrap_designer.py` checks that pixel by pixel for all 24.
"""

import hashlib
import math
import os
import sys

import engine
import wrap_design
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth

# Where art the design needs but the designer can't already serve is copied:
# an author photo from the project's uploads, an EXIF-turned picture. Set by app.py.
IMPORT_DIR = ''

# A piece of drawing is named after the engine function that drew it, the
# innermost one on the stack that has a name here. Strong names keep their
# drawing as a layer of its own; weak ones merge with the drawing beside them.
_STRONG = {
    '_paint_gradient': 'Background',
    '_paint_border': 'Frame',
    '_paint_vignette': 'Vignette',
    '_paint_bottom_scrim': 'Shading',
    '_paint_title_panel': 'Title panel',
    '_paint_background': 'Tint',
}
_WEAK = {'_diamond': 'Ornament', '_draw_ornament': 'Ornament'}


def _hexof(col):
    """A ReportLab colour as '#rrggbb'."""
    r, g, b = (min(max(int(round(v * 255)), 0), 255) for v in (col.red, col.green, col.blue))
    return '#%02x%02x%02x' % (r, g, b)


def _label_here():
    f = sys._getframe(2)
    while f is not None:
        if f.f_globals is engine.__dict__:
            name = f.f_code.co_name
            if name in _STRONG:
                return _STRONG[name], True
            if name in _WEAK:
                return _WEAK[name], False
        f = f.f_back
    return 'Shapes', False


class _Path:
    """The subset of ReportLab's path object the cover painters use."""

    def __init__(self):
        self.ops = []

    def moveTo(self, x, y):
        self.ops.append(['M', x, y])

    def lineTo(self, x, y):
        self.ops.append(['L', x, y])

    def curveTo(self, x1, y1, x2, y2, x3, y3):
        self.ops.append(['C', x1, y1, x2, y2, x3, y3])

    def close(self):
        self.ops.append(['Z'])

    def rect(self, x, y, w, h):
        self.ops += [['M', x, y], ['L', x + w, y], ['L', x + w, y + h], ['L', x, y + h], ['Z']]


class _Text:
    """The subset of ReportLab's text object the cover painters use."""

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.runs = []         # ('font', name, size) | ('tc', v) | ('out', text)

    def setFont(self, name, size, leading=None):
        self.runs.append(('font', name, size))

    def setCharSpace(self, v):
        self.runs.append(('tc', v))

    def textOut(self, text):
        self.runs.append(('out', text))

    def textLine(self, text=''):
        self.runs.append(('out', text))


class Recorder:
    """A stand-in for a ReportLab canvas that records what is drawn, in page points.

    It keeps the graphics state the way a PDF does - including the text state:
    character spacing set inside one text object stays in force for the next
    one until a restore, which ReportLab's `drawCentredString` relies on without
    saying so. An unknown call fails loudly, so a painter that grows a new kind
    of drawing is caught by the conversion tests rather than silently dropped.
    """

    def __init__(self):
        self.items = []
        self._st = {'fill': '#000000', 'stroke': '#000000', 'fa': 1.0, 'sa': 1.0, 'lw': 1.0,
                    'dash': None, 'cap': 0, 'join': 0, 'font': None, 'size': 12.0, 'tc': 0.0,
                    'ctm': (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 'clip': None}
        self._stack = []

    # -- state
    def saveState(self):
        self._stack.append(dict(self._st))

    def restoreState(self):
        self._st = self._stack.pop()

    # As in ReportLab: a colour object brings its own alpha (1 for a plain
    # colour), so setting a colour after an alpha undoes the alpha.
    def setFillColor(self, c, alpha=None):
        self._st['fill'] = _hexof(c)
        a = alpha if alpha is not None else getattr(c, 'alpha', None)
        if a is not None:
            self._st['fa'] = float(a)

    def setStrokeColor(self, c, alpha=None):
        self._st['stroke'] = _hexof(c)
        a = alpha if alpha is not None else getattr(c, 'alpha', None)
        if a is not None:
            self._st['sa'] = float(a)

    def setFillColorRGB(self, r, g, b, alpha=None):
        self._st['fill'] = '#%02x%02x%02x' % tuple(int(round(v * 255)) for v in (r, g, b))
        if alpha is not None:
            self._st['fa'] = float(alpha)

    def setStrokeColorRGB(self, r, g, b, alpha=None):
        self._st['stroke'] = '#%02x%02x%02x' % tuple(int(round(v * 255)) for v in (r, g, b))
        if alpha is not None:
            self._st['sa'] = float(alpha)

    def setFillGray(self, v, alpha=None):
        self.setFillColorRGB(v, v, v, alpha)

    def setStrokeGray(self, v, alpha=None):
        self.setStrokeColorRGB(v, v, v, alpha)

    def setFillAlpha(self, a):
        self._st['fa'] = float(a)

    def setStrokeAlpha(self, a):
        self._st['sa'] = float(a)

    def setLineWidth(self, w):
        self._st['lw'] = float(w)

    def setDash(self, array=None, phase=0):
        if isinstance(array, (int, float)):
            array = [array, phase] if phase else [array]
            phase = 0
        self._st['dash'] = list(array) if array else None

    def setLineCap(self, v):
        self._st['cap'] = int(v)

    def setLineJoin(self, v):
        self._st['join'] = int(v)

    def setFont(self, name, size, leading=None):
        self._st['font'], self._st['size'] = name, float(size)

    def translate(self, dx, dy):
        a, b, c, d, e, f = self._st['ctm']
        self._st['ctm'] = (a, b, c, d, a * dx + c * dy + e, b * dx + d * dy + f)

    def rotate(self, deg):
        t = math.radians(deg)
        co, si = math.cos(t), math.sin(t)
        a, b, c, d, e, f = self._st['ctm']
        self._st['ctm'] = (a * co + c * si, b * co + d * si, -a * si + c * co, -b * si + d * co, e, f)

    def _pt(self, x, y):
        a, b, c, d, e, f = self._st['ctm']
        return a * x + c * y + e, b * x + d * y + f

    def _style(self, stroke, fill):
        st = self._st
        return {'fill': st['fill'] if fill else None, 'fa': st['fa'],
                'stroke': st['stroke'] if stroke else None, 'sa': st['sa'], 'lw': st['lw'],
                'dash': st['dash'], 'cap': st['cap'], 'join': st['join']}

    def _shape(self, op, stroke, fill):
        if not stroke and not fill:
            return
        label, strong = _label_here()
        self.items.append({'kind': 'shape', 'op': op, 'style': self._style(stroke, fill),
                           'label': label, 'strong': strong, 'clip': self._st['clip']})

    # -- shapes
    def _poly(self, pts, closed):
        out = [['M'] + list(self._pt(*pts[0]))]
        out += [['L'] + list(self._pt(*p)) for p in pts[1:]]
        if closed:
            out.append(['Z'])
        return out

    def rect(self, x, y, w, h, stroke=1, fill=0):
        self._shape(['path', self._poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)],
                    stroke, fill)

    def line(self, x1, y1, x2, y2):
        self._shape(['path', self._poly([(x1, y1), (x2, y2)], False)], 1, 0)

    def circle(self, x, y, r, stroke=1, fill=0):
        (cx, cy), (ex, _) = self._pt(x, y), self._pt(x + r, y)
        self._shape(['ellipse', cx, cy, math.hypot(ex - cx, _ - cy)], stroke, fill)

    def beginPath(self):
        return _Path()

    def drawPath(self, p, stroke=1, fill=0, fillMode=None):
        segs = []
        for o in p.ops:
            if o[0] == 'Z':
                segs.append(['Z'])
            else:
                pts = [self._pt(o[i], o[i + 1]) for i in range(1, len(o), 2)]
                segs.append([o[0]] + [v for pt in pts for v in pt])
        self._shape(['path', segs], stroke, fill)

    def clipPath(self, p, stroke=0, fill=0, fillMode=None):
        xs = [o[i] for o in p.ops if o[0] != 'Z' for i in range(1, len(o), 2)]
        ys = [o[i] for o in p.ops if o[0] != 'Z' for i in range(2, len(o), 2)]
        pts = [self._pt(x, y) for x, y in ((min(xs), min(ys)), (max(xs), max(ys)))]
        box = (min(p[0] for p in pts), min(p[1] for p in pts),
               max(p[0] for p in pts), max(p[1] for p in pts))
        old = self._st['clip']
        if old:
            box = (max(box[0], old[0]), max(box[1], old[1]), min(box[2], old[2]), min(box[3], old[3]))
        self._st['clip'] = box

    def linearGradient(self, x0, y0, x1, y1, colors, positions=None, extend=True):
        clip = self._st['clip']
        if not clip:
            raise ValueError('a gradient outside a clipping rectangle')
        (ax, ay), (bx, by) = self._pt(x0, y0), self._pt(x1, y1)
        if abs(ax - bx) > 0.01:
            raise ValueError('only vertical gradients are converted')
        top, bot = (colors[0], colors[-1]) if ay > by else (colors[-1], colors[0])
        label, strong = _label_here()
        self.items.append({'kind': 'shape', 'op': ['grad', clip, _hexof(top), _hexof(bot),
                                                   max(ay, by), min(ay, by)],
                           'style': {'fa': self._st['fa']}, 'label': label, 'strong': strong,
                           'clip': None})

    # -- pictures
    def drawImage(self, image, x, y, width=None, height=None, mask=None,
                  preserveAspectRatio=False, anchor='c', **kw):
        a, b, c, d, e, f = self._st['ctm']
        if abs(b) > 1e-9 or abs(c) > 1e-9:
            raise ValueError('a turned picture')
        x0, y0 = self._pt(x, y)
        x1, y1 = self._pt(x + width, y + height)
        self.items.append({'kind': 'image', 'image': image, 'rect': (x0, y0, x1, y1),
                           'clip': self._st['clip'], 'fa': self._st['fa'],
                           'aspect': bool(preserveAspectRatio)})

    # -- text
    def beginText(self, x=0, y=0, direction=None):
        return _Text(x, y)

    def drawText(self, t):
        x = t.x
        for run in t.runs:
            if run[0] == 'font':
                self._st['font'], self._st['size'] = run[1], float(run[2])
            elif run[0] == 'tc':
                self._st['tc'] = float(run[1])
            elif run[1]:
                self._text(x, t.y, run[1])
                x += (stringWidth(run[1], self._st['font'], self._st['size'])
                      + self._st['tc'] * len(run[1]))

    def drawString(self, x, y, text, *a, **kw):
        t = _Text(x, y)
        t.textOut(text)
        self.drawText(t)

    def drawCentredString(self, x, y, text, *a, **kw):
        self.drawString(x - stringWidth(text, self._st['font'], self._st['size']) / 2.0, y, text)

    def drawRightString(self, x, y, text, *a, **kw):
        self.drawString(x - stringWidth(text, self._st['font'], self._st['size']), y, text)

    def _text(self, x, y, text):
        a, b, c, d, e, f = self._st['ctm']
        bx, by = self._pt(x, y)
        self.items.append({'kind': 'text', 'text': text, 'x': bx, 'y': by,
                           'angle': round(math.degrees(math.atan2(b, a))) % 360,
                           'font': self._st['font'], 'size': self._st['size'],
                           'tc': self._st['tc'], 'color': self._st['fill'], 'fa': self._st['fa']})

    def showPage(self):
        pass

    def save(self):
        pass


# ---- from recorded drawing to a design ------------------------------------------

def _r(v):
    return round(v, 6)


def _font_file(name, notes):
    """The font-library file a registered face came from, or a stand-in from the
    library (noted) for a face that isn't one - a built-in PDF font, say."""
    try:
        path = pdfmetrics.getFont(name).face.filename
    except Exception:
        path = ''
    base = os.path.basename(path or '')
    if base and wrap_design.font_file(base):
        return base
    want = 'Bold' if 'Bold' in (name or '') else 'Italic' if 'Italic' in (name or '') else 'Regular'
    lib = sorted(f for f in os.listdir(wrap_design.FONT_DIR) if f.lower().endswith('.ttf'))
    pick = next((f for f in lib if f == f'Book-{want}.ttf'), None) or \
        next((f for f in lib if want in f), None) or (lib[0] if lib else '')
    notes.append(f'The face {name} is not in your font library, so {pick} stands in for it.')
    return pick


def _store(data, ext):
    """Bytes saved into IMPORT_DIR under a name made from their hash; the name."""
    name = 'imported-' + hashlib.sha1(data).hexdigest()[:12] + ext
    dest = os.path.join(IMPORT_DIR, name)
    if not os.path.exists(dest):
        os.makedirs(IMPORT_DIR, exist_ok=True)
        with open(dest, 'wb') as fh:
            fh.write(data)
    return name


def _pil_png(pil):
    import io
    buf = io.BytesIO()
    pil.convert('RGB').save(buf, 'PNG')
    return buf.getvalue()


def import_picture(path):
    """A picture file as a name the designer can serve: as it is if it already
    lives in one of the art folders, otherwise copied into IMPORT_DIR - upright,
    if it is a photo stored on its side. None if there is no such file."""
    if not path or not os.path.isfile(path):
        return None
    up = engine._upright(path)
    if not isinstance(up, str):                       # turned: the upright copy
        return _store(_pil_png(up), '.png')
    base = os.path.basename(path)
    found = wrap_design.art_file(base)
    if found and os.path.samefile(found, path):
        return base
    with open(path, 'rb') as fh:
        return _store(fh.read(), os.path.splitext(base)[1].lower())


def _art_name(image, notes):
    """A picture's name in the designer's art folders, copying it in if it isn't there."""
    src = getattr(image, 'fileName', None)
    if isinstance(src, str) and os.path.isfile(src):
        return import_picture(src)
    pil = getattr(image, '_image', None)              # an upright copy of a turned photo
    if pil is not None:
        return _store(_pil_png(pil), '.png')
    notes.append('A picture in the template could not be carried over.')
    return None


class _Sheet:
    """Page points (y up) to designer inches (y down), and which panel a point is on."""

    def __init__(self, g):
        self.g, self.H = g, g['wrap_h'] * 72.0
        sp0, sp1 = g['spine_x'], g['spine_x'] + g['spine_w']
        self.cuts = ((sp0 - g['hinge'] / 2.0, 'back'), (sp1 + g['hinge'] / 2.0, 'spine'))

    def inch(self, x, y):
        return x / 72.0, (self.H - y) / 72.0

    def panel(self, x_in):
        for cut, name in self.cuts:
            if x_in < cut:
                return name
        return 'front'

    def fill_of(self, box):
        """The `fill` a box in inches (x, y, w, h) matches, if any."""
        for which in ('sheet', 'front', 'back', 'spine'):
            fx, fy, fw, fh = wrap_design.fill_rect(self.g, which)
            if all(abs(a - b) < 0.002 for a, b in zip(box, (fx, fy, fw, fh))):
                return which
        return None

    def place(self, el, x, y, anchor=None):
        """Set an element's anchor and position from its sheet position in inches."""
        anchor = anchor or self.panel(x)
        ox, oy = wrap_design.origin(self.g, anchor)
        el['anchor'] = anchor
        if anchor == 'spine':
            el['cx'] = _r(x - ox - self.g['spine_w'] / 2.0)
        else:
            el['x'] = _r(x - ox)
        el['y'] = _r(y - oy)
        return el


def _width(text, font, size, tc):
    return stringWidth(text, font, size) + tc * max(len(text) - 1, 0)


def _text_groups(items):
    """Runs of consecutive lines set alike: one face, size, tracking, colour and
    direction, stepping down by a steady leading and sharing an alignment."""
    groups = []
    for it in items:
        if it['kind'] != 'text':
            groups.append(it)
            continue
        it['w'] = _width(it['text'], it['font'], it['size'], it['tc'])
        prev = groups[-1] if groups and isinstance(groups[-1], list) else None
        if prev and _continues(prev, it):
            prev.append(it)
        else:
            groups.append([it])
    return groups


def _along(it):
    """(across, down) for a line: x of its start and its baseline's distance down
    the page, in the line's own reading direction."""
    if it['angle'] == 270:                       # reads top to bottom
        return -it['y'], -it['x']
    return it['x'], -it['y']


def _continues(group, it):
    last = group[-1]
    if any(last[k] != it[k] for k in ('font', 'size', 'tc', 'color', 'fa', 'angle')):
        return False
    if it['angle'] not in (0, 270):
        return False
    (lx, ld), (ix, idn) = _along(last), _along(it)
    step = idn - ld
    if not (0.6 * it['size'] < step < 3.2 * it['size']):
        return False
    if len(group) > 1:
        first = _along(group[0])[1]
        ref = _along(group[1])[1] - first
        if not (abs(step - ref) < 0.5 or abs(step - ref * 1.6) < 0.6 or abs(step * 1.6 - ref) < 0.6):
            return False
    if abs(lx - ix) < 0.05:
        return True                              # left-aligned
    if abs((lx + last['w'] / 2) - (ix + it['w'] / 2)) < 0.05:
        return True                              # centred
    return abs((lx + last['w']) - (ix + it['w'])) < 0.05


def _align(group):
    if len(group) == 1:
        return 'center'
    xs = [_along(it)[0] for it in group]
    if max(xs) - min(xs) < 0.05:
        return 'left'
    cs = [x + it['w'] / 2 for x, it in zip(xs, group)]
    return 'center' if max(cs) - min(cs) < 0.05 else 'right'


def _text_element(group, sheet, notes, fonts):
    """One text box from a run of lines, sized so it breaks into those same lines."""
    first = group[0]
    font = fonts.setdefault(first['font'], _font_file(first['font'], notes))
    size, tc = first['size'], first['tc']
    rl_font = wrap_design.font_name(font)
    steps = [_along(b)[1] - _along(a)[1] for a, b in zip(group, group[1:])]
    lead = min(steps) if steps else size * 1.2
    # rejoin the words; a gap wider than the leading, or a line the next word
    # would have fitted on, was a break in the text itself
    widest = max(_width(it['text'], rl_font, size, tc) for it in group)
    box = widest + 0.01
    text, blank = group[0]['text'], None
    for i, it in enumerate(group[1:]):
        prev = group[i]['text']
        nxt = it['text'].split(' ')[0]
        if steps[i] > lead * 1.3:
            text += '\n\n' + it['text']           # a blank line, as tall as the gap was
            blank = steps[i] / lead - 1.0
        elif not it['text'].strip() or not prev.strip() or \
                _width(prev + ' ' + nxt, rl_font, size, tc) <= box:
            text += '\n' + it['text']
        else:
            text += ' ' + it['text']
    align = _align(group)
    face = pdfmetrics.getFont(rl_font).face
    asc = face.ascent / 1000.0 * size
    across = _along(first)[0]
    if align == 'center':
        mid = across + _width(first['text'], rl_font, size, tc) / 2.0
    lone = len(group) == 1 and '\n' not in text
    el = {'type': 'text', 'text': text, 'font': font, 'size': _r(size),
          'leading': _r(lead / size), 'color': first['color'], 'align': align, 'tracking': _r(tc)}
    if lone:
        # one line has no leading to keep, so its box is just the type's height:
        # on a thin spine a full line's depth would overhang the safe zone when
        # the letters themselves don't
        el['leading'] = _r((face.ascent - face.descent) / 1000.0)
    if blank is not None:
        el['blank'] = _r(blank)
    if first['fa'] < 1:
        el['opacity'] = _r(first['fa'])
    g = sheet.g
    if first['angle'] == 270:
        el['rotate'] = 90
        # The designer turns the box a quarter about its top-left corner, so the
        # first baseline sits `ascent` to the left of the box's x, and the line
        # runs down the sheet from the box's y plus its alignment offset.
        bx = first['x'] / 72.0
        width = box / 72.0
        if lone:
            width = max(width, g['panel_h'] - 2 * engine.WRAP_SAFE)
        y_start = (sheet.H + across) / 72.0      # where the first line starts, down the sheet
        if align == 'center':
            y0 = (sheet.H + mid) / 72.0 - width / 2.0
        elif align == 'right':
            y0 = y_start + _width(first['text'], rl_font, size, tc) / 72.0 - width
        else:
            y0 = y_start
        el['w'] = _r(width)
        anchor = sheet.panel(bx)
        el = sheet.place(el, bx + asc / 72.0, y0, anchor)
        return el
    x0 = across
    if align == 'center':
        x0 = mid - box / 2.0
    elif align == 'right':
        x0 = across + _width(first['text'], rl_font, size, tc) - box
    bx, top = sheet.inch(x0, first['y'] + asc)
    width = box / 72.0
    anchor = sheet.panel(bx + width / 2.0)
    if lone and align == 'center':
        # a single centred line gets room to grow either side, up to the safe zone
        ox, _ = wrap_design.origin(g, anchor)
        pw = wrap_design.panel_width(g, anchor)
        c = bx + width / 2.0 - ox
        inset = engine.WRAP_SAFE if anchor != 'spine' else engine.WRAP_SPINE_SAFE
        room = min(c - inset, pw - inset - c)
        if room * 2 > width:
            width = room * 2
            bx = ox + c - room
    el['w'] = _r(width)
    return sheet.place(el, bx, top, anchor)


def _image_element(it, sheet, notes):
    name = _art_name(it['image'], notes)
    if not name:
        return None
    x0, y0, x1, y1 = it['rect']
    clip = it['clip'] or (x0, y0, x1, y1)
    cx0, cy0 = max(x0, clip[0]), max(y0, clip[1])
    cx1, cy1 = min(x1, clip[2]), min(y1, clip[3])
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    bw, bh = cx1 - cx0, cy1 - cy0
    iw, ih = it['image'].getSize()
    dw, dh = x1 - x0, y1 - y0
    el = {'type': 'image', 'src': name}
    base = max(bw / iw, bh / ih)
    zoom = (dw / iw) / base if iw else 1.0
    if abs(zoom - 1) > 1e-4 or abs(dw / dh - iw / ih) > 1e-3 * (iw / ih):
        el['zoom'] = _r(max(zoom, 1.0))
    if dw - bw > 0.01:
        el['fx'] = _r((cx0 - x0) / (dw - bw))
    if dh - bh > 0.01:
        el['fy'] = _r((y1 - cy1) / (dh - bh))
    if it['fa'] < 1:
        el['opacity'] = _r(it['fa'])
    lx, ty = sheet.inch(cx0, cy1)
    box = (lx, ty, bw / 72.0, bh / 72.0)
    fill = sheet.fill_of(box)
    if fill:
        el['fill'] = fill
        return el
    el['w'], el['h'] = _r(box[2]), _r(box[3])
    return sheet.place(el, lx, ty)


def _op_points(op):
    if op[0] == 'path':
        return [(s[i], s[i + 1]) for s in op[1] for i in range(1, len(s), 2)]
    if op[0] == 'ellipse':
        _, cx, cy, r = op
        return [(cx - r, cy - r), (cx + r, cy + r)]
    clip = op[1]
    return [(clip[0], clip[1]), (clip[2], clip[3])]


def _vector_element(run, sheet):
    """A layer of drawing: its ops in inches from the box's top-left, y down."""
    pts = [sheet.inch(*p) for it in run for p in _op_points(it['op'])]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    # strokes reach half their width past the path, so keep them in the box
    pad = max((it['style'].get('lw', 0) / 144.0 if it['style'].get('stroke') else 0)
              for it in run)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    w, h = max(x1 - x0, 0.001), max(y1 - y0, 0.001)
    ops = []
    for it in run:
        op, st = it['op'], it['style']

        def P(x, y):
            ix, iy = sheet.inch(x, y)
            return [_r(ix - x0), _r(iy - y0)]
        style = {}
        if st.get('fill'):
            style['fill'] = st['fill']
            if st['fa'] < 1:
                style['fa'] = _r(st['fa'])
        if st.get('stroke'):
            style['stroke'] = st['stroke']
            style['lw'] = _r(st['lw'])
            if st['sa'] < 1:
                style['sa'] = _r(st['sa'])
            if st.get('dash'):
                style['dash'] = st['dash']
            if st.get('cap'):
                style['cap'] = st['cap']
            if st.get('join'):
                style['join'] = st['join']
        if op[0] == 'path':
            segs = []
            for s in op[1]:
                if s[0] == 'Z':
                    segs.append(['Z'])
                else:
                    segs.append([s[0]] + [v for i in range(1, len(s), 2) for v in P(s[i], s[i + 1])])
            ops.append(['path', segs, style])
        elif op[0] == 'ellipse':
            c = P(op[1], op[2])
            ops.append(['ellipse', c[0], c[1], _r(op[3] / 72.0), _r(op[3] / 72.0), style])
        else:
            clip, top, bot, ytop, ybot = op[1], op[2], op[3], op[4], op[5]
            a, b = P(clip[0], clip[3]), P(clip[2], clip[1])
            g0, g1 = P(0, ytop)[1], P(0, ybot)[1]
            gs = {'fa': _r(st['fa'])} if st.get('fa', 1) < 1 else {}
            ops.append(['grad', a[0], a[1], _r(b[0] - a[0]), _r(b[1] - a[1]), top, bot,
                        _r(g0), _r(g1), gs])
    el = {'type': 'vector', 'label': run[0]['label'], 'vw': _r(w), 'vh': _r(h), 'ops': ops}
    fill = sheet.fill_of((x0, y0, w, h))
    if fill:
        el['fill'] = fill
        return el
    el['w'], el['h'] = _r(w), _r(h)
    return sheet.place(el, x0, y0, sheet.panel((x0 + x1) / 2.0))


def _shape_runs(items, sheet):
    """Split consecutive shapes into layers: a new layer at every strong name
    change and wherever the drawing moves to another panel."""
    runs = []
    for it in items:
        pts = _op_points(it['op'])
        cx = sum(sheet.inch(*p)[0] for p in pts) / len(pts)
        it['panel'] = sheet.panel(cx) if it['label'] != 'Background' else 'sheet'
        last = runs[-1] if runs else None
        if last and last[-1]['panel'] == it['panel'] and (
                last[0]['label'] == it['label'] or not (last[0]['strong'] or it['strong'])):
            last.append(it)
        else:
            runs.append([it])
    return runs


def from_template(tpl, cf, meta, dims):
    """The wrap `engine.build_cover_wrap` would draw, as a design. Returns
    (design, notes) - notes are what didn't carry over exactly, in words."""
    rec = Recorder()
    engine.build_cover_wrap(tpl, cf, meta, dims, None, canv=rec)
    g = engine.wrap_geometry(dims)
    sheet = _Sheet(g)
    notes, fonts, elements = [], {}, []
    shapes = []

    def flush():
        for run in _shape_runs(shapes, sheet):
            elements.append(_vector_element(run, sheet))
        del shapes[:]

    for grp in _text_groups(rec.items):
        if isinstance(grp, list):
            flush()
            elements.append(_text_element(grp, sheet, notes, fonts))
        elif grp['kind'] == 'shape':
            shapes.append(grp)
        else:
            flush()
            el = _image_element(grp, sheet, notes)
            if el:
                elements.append(el)
    flush()
    elements = _barcodes(elements)
    seen = {}
    for el in elements:
        stem = {'text': 'text', 'image': 'picture', 'vector': 'shape',
                'barcode': 'barcode'}.get(el['type'], 'el')
        seen[stem] = seen.get(stem, 0) + 1
        el['id'] = f'{stem}-{seen[stem]}'
        if el['type'] == 'vector' and el.get('anchor') in ('back', 'front', 'spine'):
            el['label'] = f"{el['label']} ({el['anchor']})"
    return {'elements': elements}, sorted(set(notes))


def _barcodes(elements):
    """The template's barcode reserve - a white box outlined in grey with
    "ISBN / barcode area" in it - as one `barcode` element, locked like the
    designer's own, so it can take an ISBN. It draws the same box and label."""
    out, i = [], 0
    while i < len(elements):
        el = elements[i]
        nxt = elements[i + 1] if i + 1 < len(elements) else None
        box = wrap_design.reserve_box(el)
        if box and nxt and nxt['type'] == 'text' and nxt['text'] == 'ISBN / barcode area':
            x, y, w, h = box
            out.append({'type': 'barcode', 'anchor': el['anchor'], 'x': _r(x), 'y': _r(y),
                        'w': _r(w), 'h': _r(h), 'font': nxt['font'], 'locked': True,
                        'label': 'Barcode area', 'caption': True, 'isbn': '', 'addon': ''})
            i += 2
            continue
        out.append(el)
        i += 1
    return out
