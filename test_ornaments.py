"""Scene-break ornament tests  (run: python test_ornaments.py).

The ornaments are defined once, in `ornaments.py`, and drawn by two independent
renderers — ReportLab canvas ops in `engine._draw_ornament`, and SVG in
`ornaments.svg()`. Most of what can go wrong is therefore either geometry (a
shape that leaves its own box and collides with the paragraph above it) or the
two renderers disagreeing, so those are what this file checks — followed by a
real PDF and a real EPUB, because a mark that never reaches the artefact is no
ornament at all.
"""

import sys, os, io, json, re, tempfile, zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import ornaments, engine, epub, manuscript, matter
import app as A
from reportlab.pdfgen import canvas as _canvas

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


MS = """\
# The Salt Road

The opening paragraph of the chapter, long enough to fill more than one line of
body text so the scene break has real prose above it.

* * *

After the break the story continues on a flush paragraph, which is how the
engine sets the line following a scene break in every one of the styles.
"""

META = {'title': 'T', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light', **{k: '' for k in matter.KEYS}}


def styled(**scene_break):
    p = json.loads(json.dumps(A.DEFAULTS))
    p['scene_break'].update(scene_break)
    return p


# ---------------------------------------------------------------- geometry
print('the definitions')
check('twelve ornaments ship', len(ornaments.DEFS) == 12, len(ornaments.DEFS))
check('ids are unique', len(set(ornaments.IDS)) == len(ornaments.DEFS))
check('every ornament has a positive aspect and a sane width',
      all(d['aspect'] > 0 and 0 < d['width'] <= 1 for d in ornaments.DEFS))
check('every ornament is named and described',
      all(d['name'] and d['note'] for d in ornaments.DEFS))
check('an unknown id returns None', ornaments.get('nope') is None)
check('an unknown id has no size', ornaments.size('nope', 400) == (0.0, 0.0))


def extent(d):
    """The bounding box actually covered by an ornament's primitives."""
    xs, ys = [], []
    for op in d['ops']:
        if op[0] == 'poly':
            for x, y in op[1]:
                xs.append(x); ys.append(y)
        elif op[0] == 'dot':
            xs += [op[1] - op[3], op[1] + op[3]]
            ys += [op[2] - op[3], op[2] + op[3]]
        elif op[0] == 'line':
            xs += [op[1], op[3]]
            ys += [op[2] - op[5] / 2, op[4] + op[5] / 2]
        else:                       # fill / stroke path (bézier hull is enough)
            for s in op[1]:
                if s[0] == 'z':
                    continue
                xs += list(s[1::2]); ys += list(s[2::2])
    return min(xs), max(xs), min(ys), max(ys)


# a shape that leaves its box would collide with the paragraph above it, since
# SceneBreak reserves exactly the box
out_of_box = []
for d in ornaments.DEFS:
    x0, x1, y0, y1 = extent(d)
    if x0 < -0.02 or x1 > d['aspect'] + 0.02 or y0 < -0.02 or y1 > 1.02:
        out_of_box.append((d['id'], round(x0, 2), round(x1, 2), round(y0, 2), round(y1, 2)))
check('every ornament stays inside its own box', not out_of_box, out_of_box)

COL = 324.0     # the text column of a 6x9 at the shipped margins
sizes = {d['id']: ornaments.size(d['id'], COL) for d in ornaments.DEFS}
check('the recommended widths are printable in a 6x9 column',
      all(1.5 <= h <= 22 and 6 <= w <= COL for w, h in sizes.values()),
      {k: (round(w), round(h, 1)) for k, (w, h) in sizes.items()})
check('a width override is honoured', ornaments.size('diamond', COL, 0.5)[0] == COL * 0.5)
check('an absurd override is clamped to the column',
      ornaments.size('diamond', COL, 9)[0] == COL)

# ---------------------------------------------------------------- the two renderers
print('svg')
malformed = [d['id'] for d in ornaments.DEFS
             if not ornaments.svg(d['id']).startswith('<svg')
             or 'viewBox' not in ornaments.svg(d['id'])
             or 'nan' in ornaments.svg(d['id']).lower()]
check('every ornament emits an svg element', not malformed, malformed)
unparsed = []
for d in ornaments.DEFS:
    try:
        minidom.parseString(ornaments.svg(d['id'], xml_decl=True))
    except Exception as e:
        unparsed.append((d['id'], str(e)))
check('every ornament parses as XML', not unparsed, unparsed)
check('an unknown id yields no svg', ornaments.svg('nope') == '')
# the SVG walk and the ReportLab walk read the same op list; if one grows a
# case the other doesn't handle, the element count is where it shows
check('svg emits one element per primitive',
      all(ornaments.svg_body(d['id']).count('<') == len(d['ops'])
          for d in ornaments.DEFS))

print('the engine')
canv = _canvas.Canvas(io.BytesIO())
drew = [d['id'] for d in ornaments.DEFS
        if not engine._draw_ornament(canv, d['id'], 10, 10, 100, 100 / d['aspect'])]
check('the engine draws every ornament', not drew, drew)
check('the engine reports an unknown ornament rather than raising',
      engine._draw_ornament(canv, 'gone', 10, 10, 100, 15) is False)

sb = engine.SceneBreak('* * *', 'Helvetica', 11, 9, ornament='swelled-rule')
check('SceneBreak reserves the drawn height',
      abs(sb.wrap(COL, 700)[1] - (18 + COL * 0.42 / 34.0)) < 0.01, sb.wrap(COL, 700))
# a style may name an ornament a later version retired; falling back beats failing
sb = engine.SceneBreak('* * *', 'Helvetica', 11, 9, ornament='retired-mark')
check('a retired ornament falls back to the glyph height', sb.wrap(COL, 700)[1] == 29)

# ---------------------------------------------------------------- the artefacts
print('the built book')
ms = manuscript.parse_markdown(MS, smartquotes=True)

fd, pdf_path = tempfile.mkstemp(suffix='.pdf'); os.close(fd)
built = []
for d in ornaments.DEFS:
    try:
        engine.build_pdf(ms, styled(type='ornament', ornament=d['id']),
                         pdf_path, dict(META))
    except Exception as e:
        built.append((d['id'], str(e)))
check('a real book builds with every ornament', not built, built)

# an ornament must not change pagination beyond its own height
r_glyph = engine.build_pdf(ms, styled(type='glyph'), pdf_path, dict(META))
r_orn = engine.build_pdf(ms, styled(type='ornament', ornament='swelled-rule'),
                         pdf_path, dict(META))
check('an ornament does not disturb the page count',
      r_glyph['page_count'] == r_orn['page_count'],
      (r_glyph['page_count'], r_orn['page_count']))
os.remove(pdf_path)

print('the built ebook')
check('the ornament is read off the preset',
      epub.scene_ornament(styled(type='ornament', ornament='wave')) == 'wave')
check('a glyph style ignores a leftover ornament id',
      epub.scene_ornament(styled(type='glyph', ornament='wave')) == '')
check('a retired ornament id is ignored',
      epub.scene_ornament(styled(type='ornament', ornament='gone')) == '')

fd, epub_path = tempfile.mkstemp(suffix='.epub'); os.close(fd)
epub.build_epub(ms, styled(type='ornament', ornament='arabesque'), epub_path, dict(META))
with zipfile.ZipFile(epub_path) as zf:
    names = zf.namelist()
    opf = zf.read('OEBPS/content.opf').decode()
    ch = zf.read('OEBPS/chapter001.xhtml').decode()
    svg = zf.read(f'OEBPS/{epub.SCENE_ORN_HREF}').decode()
check('the svg is in the zip', f'OEBPS/{epub.SCENE_ORN_HREF}' in names)
check('the svg is manifested as image/svg+xml',
      epub.SCENE_ORN_HREF in opf and 'image/svg+xml' in opf)
check('the svg is a standalone document', svg.startswith('<?xml'))
check('the chapter references it with alt text',
      f'src="{epub.SCENE_ORN_HREF}"' in ch and 'alt="Scene break"' in ch)
check('the width is a percentage, so it reflows',
      re.search(r'style="width:(\d+(?:\.\d+)?)%"', ch)
      and 0 < float(re.search(r'style="width:([\d.]+)%"', ch).group(1)) <= 100,
      re.search(r'style="width:[^"]*"', ch))
report = epub.check(epub_path)
check('the EPUB preflight is all clear', all(c['ok'] for c in report),
      [c for c in report if not c['ok']])
os.remove(epub_path)

# the glyph path must be untouched: no SVG anywhere, same markup as before
epub.build_epub(ms, styled(type='glyph', glyph='* * *'), epub_path, dict(META))
with zipfile.ZipFile(epub_path) as zf:
    check('a glyph style ships no svg',
          not any('scene-break.svg' in n for n in zf.namelist()))
    check('a glyph style emits the glyph unchanged',
          '<p class="scene-break">* * *</p>' in
          zf.read('OEBPS/chapter001.xhtml').decode())
os.remove(epub_path)

# a book with no scene break must not carry an unused ornament file
epub.build_epub(manuscript.parse_markdown('# One\n\nJust prose.\n', smartquotes=True),
                styled(type='ornament', ornament='wave'), epub_path, dict(META))
with zipfile.ZipFile(epub_path) as zf:
    check('a book with no scene break ships no ornament',
          not any('scene-break.svg' in n for n in zf.namelist()))
os.remove(epub_path)

# ---------------------------------------------------------------- the app
print('the style editor')
check('DEFAULTS carries the new keys', A.DEFAULTS['scene_break']['ornament'] == '')
parsed = A.parse_preset_form({'sb_type': 'ornament', 'sb_ornament': 'fleuron',
                              'sb_ornament_width': '0.2'})['scene_break']
check('parse_preset_form reads the picker',
      parsed['type'] == 'ornament' and parsed['ornament'] == 'fleuron'
      and parsed['ornament_width'] == 0.2, parsed)
check('a form with no ornament fields still parses',
      A.parse_preset_form({})['scene_break']['ornament'] == '')
check('the spec card names the ornament',
      A.scene_break_label(styled(type='ornament', ornament='wave')) == 'Wave')
check('the spec card still shows a glyph',
      A.scene_break_label(styled(type='glyph', glyph='§')) == '§')

A.app.config['TESTING'] = True
client = A.app.test_client()

page = client.get('/editor/new').get_data(as_text=True)
check('every ornament has a tile in the picker',
      all(f'value="{i}"' in page for i in ornaments.IDS))
check('the tiles carry inline svg', page.count('<svg') >= len(ornaments.DEFS),
      page.count('<svg'))
check('the width field renders', 'sb_ornament_width' in page)
check('the styles page names the ornament on the card',
      'Swelled rule' in client.get('/').get_data(as_text=True))

# a real editor save must round-trip the choice and disturb nothing else
PRESET = os.path.join(A.PRESET_DIR, 'classic-literary.json')
snapshot = open(PRESET, 'rb').read()
try:
    before = A.load_preset('classic-literary')
    page = client.get('/editor/classic-literary').get_data(as_text=True)
    form = {}
    for m in re.finditer(r'<input[^>]*?\sname="([^"]+)"[^>]*>', page):
        tag, name = m.group(0), m.group(1)
        if 'type="radio"' in tag or 'type="checkbox"' in tag:
            if 'checked' in tag:
                v = re.search(r'value="([^"]*)"', tag)
                form[name] = v.group(1) if v else 'on'
        else:
            v = re.search(r'value="([^"]*)"', tag)
            form[name] = v.group(1) if v else ''
    for m in re.finditer(r'<select[^>]*?\sname="([^"]+)"[^>]*>(.*?)</select>', page, re.S):
        sel = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(2))
        form[m.group(1)] = sel.group(1) if sel else ''
    for m in re.finditer(r'<textarea[^>]*?\sname="([^"]+)"[^>]*>(.*?)</textarea>', page, re.S):
        form[m.group(1)] = m.group(2)

    client.post('/save/classic-literary', data=form, follow_redirects=True)
    after = A.load_preset('classic-literary')
    check('the ornament survives a real editor save',
          after['scene_break']['type'] == 'ornament'
          and after['scene_break']['ornament'] == 'swelled-rule',
          after['scene_break'])
    # a save also writes out sections that were falling back to DEFAULTS, which
    # is pre-existing behaviour; compare only what the style already carried
    changed = {k: (before[k], after.get(k)) for k in before
               if k != 'scene_break' and before[k] != after.get(k)}
    check('nothing else in the style changed', not changed, changed)

    r = client.post('/preview', data=form)
    check('the live style preview builds', r.get_json().get('ok'), r.get_json())
finally:
    open(PRESET, 'wb').write(snapshot)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
