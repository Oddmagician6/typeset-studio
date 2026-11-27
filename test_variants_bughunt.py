"""Edition variants agree with each other  (run: python test_variants_bughunt.py).

Joint bug hunt, round 7, section 30 (edition variants):

    30.1  a press-ready PDF keeps the foot-of-page note of a later paragraph
    30.2  a dead link in a `#>` tagline (or a byline, 31.1) is unlinked, not fatal
    30.3  keep-whole + drop cap: an opener's footnote moves with its paragraph
    30.4  the screen PDF's own preflight problems are reported
    30.5  two `###` with no `##` are siblings in the PDF outline and the EPUB
    30.6  the RGB fallback of a press build still has no links or live fields
    30.7  the fixed-layout EPUB's left-out check names the notes
    30.8  Large Print stat-block small caps keep the size floor
    30.9  an italic `###` stays italic under a display face
"""

import sys, os, re, shutil, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix='ts-bh30-')

import app as A
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(TMP, 'presets'))
shutil.copytree(os.path.join(HERE, 'covers'), os.path.join(TMP, 'covers'),
                ignore=shutil.ignore_patterns('assets'))
A.PRESET_DIR, A.COVER_DIR = os.path.join(TMP, 'presets'), os.path.join(TMP, 'covers')
A.PROJECT_DIR = os.path.join(TMP, 'projects')
A.OUT_DIR = os.path.join(TMP, 'out')
os.makedirs(A.OUT_DIR)

import engine, epub, fixed_epub, manuscript
import fitz

META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False}
PARA = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 3


def foot(preset):
    return dict(preset, endnotes=dict(preset.get('endnotes') or {}, placement='foot'))


def pages_text(pdf):
    with fitz.open(pdf) as doc:
        return [p.get_text() for p in doc]


classic = A.load_preset('classic-literary')

# ---- 30.1 -------------------------------------------------------------------
print('30.1 a press-ready PDF keeps a later paragraph\'s footnote')
ms = manuscript.parse_markdown('# One\n\n' + PARA + '\n\nA second paragraph cites this.[^map]\n\n'
                               '[^map]: The harbour map is in the back.\n')
pdf = os.path.join(TMP, 'press.pdf')
res = engine.build_pdf(ms, foot(classic), pdf, dict(META), press=True)
check('it built press-ready', res.get('press'), res.get('press_error'))
check('no note ran out of pages', not res.get('notes_unplaced'), res.get('notes_unplaced'))
check('the note is printed', any('harbour map' in t for t in pages_text(pdf)))
with fitz.open(pdf) as doc:
    links = [l for p in doc for l in p.get_links()]
check('and the press PDF has no links', not links, links[:3])

# ---- 30.2 -------------------------------------------------------------------
print('30.2 a dead link under a chapter title is left as text')
for label, md in (('tagline', '# Arrival\n#> [See the map](#old-map)\n\n' + PARA + '\n'),
                  ('byline (31.1)', '# Arrival | [Ann Vale](#old-map)\n\n' + PARA + '\n')):
    ms = manuscript.parse_markdown(md)
    pdf = os.path.join(TMP, 'dead.pdf')
    try:
        res = engine.build_pdf(ms, classic, pdf, dict(META))
        err = None
    except Exception as exc:
        res, err = {}, exc
    check(f'{label}: the PDF builds', err is None, err)
    check(f'{label}: the dead target is reported', '#old-map' in (res.get('dead_links') or []),
          res.get('dead_links'))
    if err is None:
        words = 'See the map' if label == 'tagline' else 'Ann Vale'
        check(f'{label}: its words still print', any(words in t for t in pages_text(pdf)))

# ---- 30.3 -------------------------------------------------------------------
print('30.3 keep-whole + drop cap: the opener\'s footnote goes with it')
dc = foot(classic)
dc = dict(dc, chapter=dict(dc['chapter'], open_style='dropcap', sink=4.6),
          body=dict(dc['body'], keep_whole=True))
OPEN = ('The tide came in over the stones while the bell kept its silence, and the '
        'keeper counted the hours by the gulls that settled on the rail. ') * 5
ms = manuscript.parse_markdown('# One\n\n' + OPEN + 'The end of it.[^n]\n\n'
                               '[^n]: Short note.\n')
pdf = os.path.join(TMP, 'dropcap.pdf')
res = engine.build_pdf(ms, dc, pdf, dict(META))
texts = pages_text(pdf)
note_pg = [i for i, t in enumerate(texts) if 'Short note' in t]
body_pg = [i for i, t in enumerate(texts) if 'end of it' in t]
check('the opening paragraph moved off the title page',
      body_pg and not any('end of it' in t and 'One' in t for t in texts[:1]), body_pg)
check('the note is on the paragraph\'s page', note_pg and note_pg == body_pg[-1:],
      (note_pg, body_pg))

# ---- 30.4 -------------------------------------------------------------------
print('30.4 the screen PDF reports its own problems')
gone = dict(classic, page_background={'image': 'gone-30.png'})
ms = manuscript.parse_markdown('# One\n\n' + PARA + '\n')
meta = dict(META, screen_pdf=True)
printed = engine.build_pdf(ms, gone, os.path.join(TMP, 'p.pdf'), dict(meta))
try:
    name, warns = A._screen_build(ms, gone, meta, 'bh30', 'x', printed)
except TypeError:                      # (before the fix: no print result taken)
    name, warns = A._screen_build(ms, gone, meta, 'bh30', 'x')
warns = [warns] if isinstance(warns, str) and warns else warns or []
check('the screen PDF was made', bool(name), warns)
check('its missing page background is a warning',
      any('Page background' in w for w in warns), warns)
check('nothing about printing comes with it',
      not any(k in w for w in warns for k in ('Cover on page 1', 'Page count')), warns)

# ---- 30.5 -------------------------------------------------------------------
print('30.5 two ### in a row are siblings')
md = '# The Keep\n\n### Gate\n\n' + PARA + '\n\n### Hall\n\n' + PARA + '\n'
ms = manuscript.parse_markdown(md)
pdf = os.path.join(TMP, 'outline.pdf')
engine.build_pdf(ms, classic, pdf, dict(META))
with fitz.open(pdf) as doc:
    toc = [(lvl, t) for lvl, t, _ in doc.get_toc()]
check('the PDF outline has them side by side',
      toc[-3:] == [(1, 'The Keep'), (2, 'Gate'), (2, 'Hall')], toc)
ep = os.path.join(TMP, 'outline.epub')
epub.build_epub(ms, classic, ep, dict(META))
with zipfile.ZipFile(ep) as z:
    body = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml'))
tags = re.findall(r'<(h\d)[^>]*>(?:<span[^>]*></span>)?(Gate|Hall)</h\d>', body)
check('the EPUB sets both as h2', tags == [('h2', 'Gate'), ('h2', 'Hall')], tags)

# ---- 30.6 -------------------------------------------------------------------
print('30.6 the RGB fallback is still a print edition')
real = engine._build_pdf
calls = []
def colour_once(manuscript_, preset_, out_path, meta_, press=False, screen=False):
    calls.append((press, bool(meta_.get('colour_interior'))))
    if press and not meta_.get('colour_interior'):
        raise ValueError('cmyk enforcement, non-CMYK colors are not allowed')
    return real(manuscript_, preset_, out_path, meta_, press=press, screen=screen)
engine._build_pdf = colour_once
try:
    # (not in the opening paragraph: its lead-in is set as plain text)
    ms = manuscript.parse_markdown('# One\n\n' + PARA + '\n\nSee [the site](https://example.com)'
                                   ' and [the start](#one).\n')
    pdf = os.path.join(TMP, 'fallback.pdf')
    res = engine.build_pdf(ms, classic, pdf, dict(META))
    with fitz.open(pdf) as doc:
        plain_links = [l for p in doc for l in p.get_links()]
    res = engine.build_pdf(ms, classic, pdf, dict(META), press=True)
finally:
    engine._build_pdf = real
check('it fell back', res.get('press_error') and not res.get('press'), res.get('press_error'))
check('not claimed as a colour interior', not res.get('colour'))
with fitz.open(pdf) as doc:
    links = [l for p in doc for l in p.get_links()]
    trim = doc[0].trimbox
check('the ordinary build has the links', len(plain_links) >= 2, plain_links)
check('the fallback has none', not links, links[:3])
check('it still declares a trim box', trim is not None and trim.width > 0)

# ---- 30.7 -------------------------------------------------------------------
print('30.7 the page-by-page ebook says the notes are left out')
ms = manuscript.parse_markdown('# One\n\n~~~ page src="map"\n~~~\n\n'
                               '[^source]: Adapted from the town archive.\n')
check('the note definition is kept', any(ch.get('notes') for ch in ms['chapters']),
      ms['chapters'])
rows = fixed_epub.notes(ms, dict(META, ebook_fixed=True), classic)
left = ' '.join(r['detail'] for r in rows if r['label'] == 'Text between pages')
check('Notes is named', 'Notes' in left, rows)
rows = fixed_epub.notes(ms, dict(META), foot(classic))
left = ' '.join(r['detail'] for r in rows if r['label'] == 'Text between pages')
check('and footnotes, when they go at the foot', 'Footnotes' in left, rows)

# ---- 30.8 -------------------------------------------------------------------
print('30.8 Large Print stat-block small caps stay at the floor')
game = A.load_preset('game-light-rulebook')
game = dict(game, body=dict(game['body'], size=11.0))
sb = dict(game.get('statblock') or {}, font_size=0, field_label_style='smallcaps',
          entry_name_style='smallcaps')
lp = A.make_large_print(dict(game, statblock=sb))
floor = float(lp.get('min_text_size') or 0)
check('the Large Print style has a floor', floor >= 16, floor)
ms = manuscript.parse_markdown(
    '# One\n\n' + PARA + '\n\n~~~ statblock cr="2"\nGate Warden\nMedium humanoid, lawful '
    'neutral\n\nArmor Class: 16 (chain)\nHit Points: 39 (6d8 + 12)\n\n### Actions\n'
    '***Halberd.*** Melee weapon attack: +4 to hit.\n~~~\n')
pdf = os.path.join(TMP, 'lp.pdf')
engine.build_pdf(ms, lp, pdf, dict(META))
small = []
with fitz.open(pdf) as doc:
    for page in doc:
        for b in page.get_text('dict')['blocks']:
            for line in b.get('lines', []):
                for s in line['spans']:
                    if s['text'].strip().upper() in ('ARMOR CLASS', 'HIT POINTS',
                                                     'HALBERD.'):
                        small.append((s['text'], round(s['size'], 1)))
check('the labels were found', bool(small), small)
check('none is under the floor', all(sz >= floor - 0.05 for _, sz in small), small)

# ---- 30.9 -------------------------------------------------------------------
print('30.9 a ### set in italic stays italic with a display face')
fonts = engine.register_fonts(game)
check('the style has a display face', bool(fonts.get('display')))
it = dict(game, headings=dict(game.get('headings') or {}, section_style='italic'))
st = engine._styles(it, fonts)
check('an italic ### is set in the italic', st['section'].fontName == fonts['italic'],
      (st['section'].fontName, fonts['italic']))
bold = dict(game, headings=dict(game.get('headings') or {}, section_style='bold'))
check('a bold one still takes the display face',
      engine._styles(bold, fonts)['section'].fontName == fonts['display'])

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
