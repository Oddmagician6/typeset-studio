"""Bundled scene-break ornaments — one geometry, three renderers.

Every ornament is defined **once**, as a list of drawing primitives in a
normalised box: x runs 0 → `aspect`, y runs 0 → 1, origin bottom-left.
`engine.py` walks those primitives with ReportLab canvas calls; `svg()` walks
the same list to emit SVG for the EPUB and for the style editor's picker.
One definition is the point — an ornament can never look different in the
paperback and the ebook, and there is no raster artwork to ship, license or
re-render at another size.

Primitives (tuples, kind first):
    ('poly',   [(x, y), ...])                      filled polygon
    ('dot',    cx, cy, r)                          filled circle
    ('line',   x1, y1, x2, y2, lw)                 stroked line
    ('fill',   [seg, ...])                         filled path
    ('stroke', [seg, ...], lw)                     stroked path
Path segments: ('m', x, y) · ('l', x, y) ·
               ('c', x1, y1, x2, y2, x3, y3) · ('z',)
Line widths and radii are in box-height units, so they scale with the drawn
ornament like everything else.

Each ornament also carries a `width`: its recommended size as a fraction of
the text column. Sizing an ornament by *height* (as image ornaments are sized)
reads badly here — a swelled rule is 34 times wider than it is tall, so a
point-size that suits a lozenge would run it off the page. A style may
override the fraction; the aspect then fixes the height.

Stdlib-only, and imports nothing from the project, so both builders can use it.
"""

import math


# ------------------------------------------------------------------ builders
def _lozenge(cx, cy, hw, hh):
    return ('poly', [(cx - hw, cy), (cx, cy + hh), (cx + hw, cy), (cx, cy - hh)])


def _star(cx, cy, r, points=6, inner=0.40):
    pts = []
    for i in range(points * 2):
        ang = math.pi / 2 + i * math.pi / points
        rad = r if i % 2 == 0 else r * inner
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return ('poly', pts)


def _xf(ops, flip_at=None, dx=0.0):
    """Mirror ops about x=flip_at and/or shift them along x.

    Used to build the symmetric ornaments (a leaf pair, a scroll) from one
    hand-drawn half, so the two sides can never drift apart.
    """
    def px(x):
        return (flip_at * 2 - x if flip_at is not None else x) + dx

    out = []
    for op in ops:
        kind = op[0]
        if kind == 'poly':
            out.append(('poly', [(px(x), y) for x, y in op[1]]))
        elif kind == 'dot':
            out.append(('dot', px(op[1]), op[2], op[3]))
        elif kind == 'line':
            out.append(('line', px(op[1]), op[2], px(op[3]), op[4], op[5]))
        else:  # fill / stroke
            segs = []
            for s in op[1]:
                if s[0] == 'z':
                    segs.append(s)
                elif s[0] == 'c':
                    segs.append(('c', px(s[1]), s[2], px(s[3]), s[4], px(s[5]), s[6]))
                else:
                    segs.append((s[0], px(s[1]), s[2]))
            out.append((kind, segs) if kind == 'fill' else (kind, segs, op[2]))
    return out


# a single ivy leaf (hedera), tip up, stem trailing to the lower left
_LEAF = [
    ('fill', [
        ('m', 0.65, 0.22),
        ('c', 0.25, 0.39, 0.15, 0.72, 0.42, 0.89),
        ('c', 0.56, 0.98, 0.62, 0.84, 0.65, 0.74),
        ('c', 0.68, 0.84, 0.74, 0.98, 0.88, 0.89),
        ('c', 1.15, 0.72, 1.05, 0.39, 0.65, 0.22),
        ('z',)]),
    ('stroke', [
        ('m', 0.65, 0.22),
        ('c', 0.55, 0.12, 0.35, 0.04, 0.12, 0.06)], 0.055),
]

# one half of the arabesque: a C-scroll curling back on itself
_SCROLL = [
    ('stroke', [
        ('m', 3.20, 0.46),
        ('c', 4.00, 0.46, 4.30, 0.98, 5.00, 0.98),
        ('c', 5.75, 0.98, 5.95, 0.52, 5.50, 0.32),
        ('c', 5.15, 0.17, 4.85, 0.45, 5.12, 0.58)], 0.075),
]


# ------------------------------------------------------------------ the set
# Ordered: rules first (quiet, work in any genre), then geometric, then floral.
DEFS = [
    {
        'id': 'swelled-rule', 'name': 'Swelled rule',
        'note': 'the classic tapering rule — quiet, works in any genre',
        'aspect': 34.0, 'width': 0.42,
        'ops': [('fill', [
            ('m', 0.0, 0.5),
            ('c', 6.8, 0.5, 10.2, 1.0, 17.0, 1.0),
            ('c', 23.8, 1.0, 27.2, 0.5, 34.0, 0.5),
            ('c', 27.2, 0.5, 23.8, 0.0, 17.0, 0.0),
            ('c', 10.2, 0.0, 6.8, 0.5, 0.0, 0.5),
            ('z',)])],
    },
    {
        'id': 'double-rule', 'name': 'Double rule',
        'note': 'thick over thin — a traditional section divider',
        'aspect': 46.0, 'width': 0.46,
        'ops': [('line', 0.0, 0.85, 46.0, 0.85, 0.30),
                ('line', 0.0, 0.10, 46.0, 0.10, 0.13)],
    },
    {
        'id': 'dot-rule', 'name': 'Dotted rule',
        'note': 'a centre dot between hairlines with dotted terminals',
        'aspect': 24.0, 'width': 0.32,
        'ops': [('line', 1.00, 0.5, 10.20, 0.5, 0.12),
                ('line', 13.80, 0.5, 23.00, 0.5, 0.12),
                ('dot', 12.00, 0.5, 0.42),
                ('dot', 0.45, 0.5, 0.20),
                ('dot', 23.55, 0.5, 0.20)],
    },
    {
        'id': 'diamond-rule', 'name': 'Diamond rule',
        'note': 'a lozenge broken into a long hairline',
        'aspect': 22.0, 'width': 0.34,
        'ops': [('line', 0.0, 0.5, 9.30, 0.5, 0.13),
                ('line', 12.70, 0.5, 22.0, 0.5, 0.13),
                _lozenge(11.0, 0.5, 1.10, 0.5)],
    },
    {
        'id': 'diamond', 'name': 'Lozenge',
        'note': 'a single small diamond — the quietest mark of all',
        'aspect': 1.7, 'width': 0.028,
        'ops': [_lozenge(0.85, 0.5, 0.85, 0.5)],
    },
    {
        'id': 'diamond-trio', 'name': 'Three lozenges',
        'note': 'three diamonds in a row — a dinkus with more finish',
        'aspect': 7.4, 'width': 0.13,
        'ops': [_lozenge(0.85, 0.5, 0.85, 0.5),
                _lozenge(3.70, 0.5, 0.85, 0.5),
                _lozenge(6.55, 0.5, 0.85, 0.5)],
    },
    {
        'id': 'star', 'name': 'Six-point star',
        'note': 'one drawn star — cleaner than a typed asterisk',
        'aspect': 1.0, 'width': 0.026,
        'ops': [_star(0.5, 0.5, 0.5)],
    },
    {
        'id': 'asterism', 'name': 'Asterism',
        'note': 'three stars in a triangle — the traditional ⁂',
        'aspect': 1.45, 'width': 0.050,
        'ops': [_star(0.30, 0.74, 0.26),
                _star(1.15, 0.74, 0.26),
                _star(0.725, 0.26, 0.26)],
    },
    {
        'id': 'wave', 'name': 'Wave',
        'note': 'an undulating flourish — light, good for romance',
        'aspect': 13.0, 'width': 0.28,
        'ops': [('stroke', [
            ('m', 0.30, 0.5),
            ('c', 1.40, 1.0, 2.40, 1.0, 3.40, 0.5),
            ('c', 4.40, 0.0, 5.40, 0.0, 6.50, 0.5),
            ('c', 7.60, 1.0, 8.60, 1.0, 9.60, 0.5),
            ('c', 10.60, 0.0, 11.60, 0.0, 12.70, 0.5)], 0.10)],
    },
    {
        'id': 'arabesque', 'name': 'Arabesque',
        'note': 'mirrored scrolls around a lozenge — ornate',
        'aspect': 6.4, 'width': 0.20,
        'ops': _SCROLL + _xf(_SCROLL, flip_at=3.2) + [_lozenge(3.2, 0.46, 0.30, 0.26)],
    },
    {
        'id': 'fleuron', 'name': 'Ivy leaf',
        'note': 'a single hedera — the printer’s leaf',
        'aspect': 1.27, 'width': 0.038,
        'ops': _LEAF,
    },
    {
        'id': 'fleuron-pair', 'name': 'Leaf pair',
        'note': 'two leaves turned inward on a lozenge',
        'aspect': 3.7, 'width': 0.12,
        'ops': (_xf(_LEAF, flip_at=0.635)
                + [_lozenge(1.85, 0.46, 0.34, 0.40)]
                + _xf(_LEAF, dx=2.43)),
    },
]

BY_ID = {d['id']: d for d in DEFS}
IDS = [d['id'] for d in DEFS]
DEFAULT_ID = 'swelled-rule'


def get(oid):
    """The ornament with this id, or None. Callers must handle None: a preset
    may name an ornament that a later version renamed, and a scene break is
    never worth crashing a build over."""
    return BY_ID.get((oid or '').strip())


def size(oid, avail_w, width_frac=0.0):
    """(width, height) in points for `oid` drawn across `avail_w` points.

    `width_frac` of 0 means "use the ornament's own recommended fraction".
    The fraction is clamped to the column, so a bad value cannot overflow.
    """
    d = get(oid)
    if not d:
        return (0.0, 0.0)
    frac = width_frac if width_frac and width_frac > 0 else d['width']
    w = max(0.02, min(float(frac), 1.0)) * avail_w
    return (w, w / d['aspect'])


# ------------------------------------------------------------------- SVG out
def _fmt(v):
    return f'{v:.4f}'.rstrip('0').rstrip('.') or '0'


def _path_d(segs):
    out = []
    for s in segs:
        if s[0] == 'm':
            out.append('M ' + _fmt(s[1]) + ' ' + _fmt(s[2]))
        elif s[0] == 'l':
            out.append('L ' + _fmt(s[1]) + ' ' + _fmt(s[2]))
        elif s[0] == 'c':
            out.append('C ' + ' '.join(_fmt(v) for v in s[1:]))
        else:
            out.append('Z')
    return ' '.join(out)


def svg_body(oid, color='#111111'):
    """The ornament's shapes as SVG elements, in the ornament's own box
    coordinates (x 0→aspect, y 0→1, origin bottom-left) — so the caller wraps
    them in the y-flipping group below."""
    d = get(oid)
    if not d:
        return ''
    out = []
    for op in d['ops']:
        kind = op[0]
        if kind == 'poly':
            pts = ' '.join(f'{_fmt(x)},{_fmt(y)}' for x, y in op[1])
            out.append(f'<polygon points="{pts}" fill="{color}"/>')
        elif kind == 'dot':
            out.append(f'<circle cx="{_fmt(op[1])}" cy="{_fmt(op[2])}" '
                       f'r="{_fmt(op[3])}" fill="{color}"/>')
        elif kind == 'line':
            out.append(f'<line x1="{_fmt(op[1])}" y1="{_fmt(op[2])}" '
                       f'x2="{_fmt(op[3])}" y2="{_fmt(op[4])}" stroke="{color}" '
                       f'stroke-width="{_fmt(op[5])}" stroke-linecap="round"/>')
        elif kind == 'fill':
            out.append(f'<path d="{_path_d(op[1])}" fill="{color}"/>')
        else:
            out.append(f'<path d="{_path_d(op[1])}" fill="none" stroke="{color}" '
                       f'stroke-width="{_fmt(op[2])}" stroke-linecap="round" '
                       f'stroke-linejoin="round"/>')
    return ''.join(out)


def svg(oid, width=None, height=None, color='#111111', xml_decl=False,
        title='Scene break'):
    """A complete `<svg>` document for `oid`.

    `width`/`height` are CSS lengths for the element (either may be omitted;
    the viewBox keeps the aspect). `xml_decl=True` gives a standalone file, as
    the EPUB needs.
    """
    d = get(oid)
    if not d:
        return ''
    a = _fmt(d['aspect'])
    dims = ''
    if width:
        dims += f' width="{width}"'
    if height:
        dims += f' height="{height}"'
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {a} 1"'
           f'{dims} preserveAspectRatio="xMidYMid meet" role="img">'
           f'<title>{title}</title>'
           f'<g transform="translate(0,1) scale(1,-1)">{svg_body(oid, color)}</g>'
           f'</svg>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + doc) if xml_decl else doc
