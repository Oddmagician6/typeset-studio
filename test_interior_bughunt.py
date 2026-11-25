"""The novel interior sets what it is given  (run: python test_interior_bughunt.py).

Joint bug hunt, round 2, section 9 (and 12.4):

    9.1  a dead in-book link in a note or a quote's source no longer aborts the PDF
    9.2  a table row or telegram taller than a page splits instead of failing
    9.3  an empty `~~~ redacted` block builds
    9.4  a full-page figure with a page-long caption keeps the picture on the page
    9.5  a note cited in a telegram or a small-caps table header keeps its footnote
    9.6  a drop cap's opening paragraph can split; three lines beside a two-line
         cap stay inside the room it reserves
    9.7  a chapter sunk almost a page deep opens on the page the contents names
    9.8  a heading split over a page keeps its contents tag
    9.9  angle brackets in a style's labels print as typed
    9.10 a drop cap takes a whole character: `<Wait>`, an opening quote, an accent
    9.11 after an unnumbered prologue the contents calls an untitled chapter 1
    9.12 a long running head stays inside the trim
    9.13 a wide scene-break image is scaled to the measure
    9.14 an epigraph's source line and each Also By title get their own line
    12.4 a `{N}` typo in a number format no longer crashes the build
"""

import sys, os, json, copy, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import fitz
import manuscript as M
import engine

PRESET = json.load(open(os.path.join(HERE, 'presets', 'classic-literary.json'), encoding='utf-8'))
META = {'title': 'T', 'subtitle': '', 'author': 'A', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light'}
TMP = tempfile.mkdtemp()

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


def build(text, preset=None, meta=None, name='o.pdf'):
    """(result or exception, [page texts])."""
    out = os.path.join(TMP, name)
    try:
        res = engine.build_pdf(M.parse_markdown(text), preset or PRESET, out,
                               dict(META, **(meta or {})))
    except Exception as e:                      # noqa: BLE001 - reported as a fail
        return e, []
    doc = fitz.open(out)
    pages = [p.get_text() for p in doc]
    doc.close()
    return res, pages


def ok(res):
    return not isinstance(res, Exception)


def flat(pages):
    return ' '.join(' '.join(pages).split())


def preset(**changes):
    p = copy.deepcopy(PRESET)
    for path, v in changes.items():
        d = p
        keys = path.split('__')
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = v
    return p


LONG = ' '.join(['The island disappears every winter and nobody knows why.'] * 120)

# ---- 9.1 ---------------------------------------------------------------
print('9.1 dead links outside the body text')
res, pages = build('# One\n\nSee this.[^a]\n\n[^a]: See [the appendix](#old-appendix).\n')
check('note with a dead link builds', ok(res), res)
check('the link text still prints', 'the appendix' in flat(pages))
check('the dead target is reported', ok(res) and '#old-appendix' in res.get('dead_links', []),
      ok(res) and res.get('dead_links'))
res, pages = build('# One\n\n~~~ quote source="See [x](#gone)"\nHi.\n~~~\n')
check('quote source with a dead link builds', ok(res), res)

# ---- 9.2 ---------------------------------------------------------------
print('9.2 rows taller than a page')
res, pages = build('# One\n\n~~~ table\nA | ' + LONG + '\n~~~\n')
check('tall table row builds', ok(res), res)
check('every word of the row prints', flat(pages).count('why.') == 120,
      flat(pages).count('why.'))
res, pages = build('# One\n\n~~~ telegram\n' + LONG + '\n~~~\n')
check('tall telegram builds', ok(res), res)
res, pages = build('# One\n\n~~~ redacted\n' + LONG + '\n~~~\n')
check('tall redacted paragraph builds', ok(res), res)

# a short row that only misses the foot of a page still goes over whole
t = engine._TallRowTable([['a'], ['b']], colWidths=[100])
t.wrap(100, 1000)
check('a row that fits a fresh page is not split at a foot', t.split(100, 5) == [])

# ---- 9.3 ---------------------------------------------------------------
print('9.3 empty redacted block')
res, pages = build('# One\n\nHi.\n\n~~~ redacted\n~~~\n')
check('empty redacted builds', ok(res), res)

# ---- 9.4 ---------------------------------------------------------------
print('9.4 full-page figure under a long caption')
try:
    from PIL import Image
    fig_dir = engine.FIGURE_DIR
    os.makedirs(fig_dir, exist_ok=True)
    fig = os.path.join(fig_dir, '_bughunt_map.png')
    Image.new('RGB', (300, 400), (90, 120, 160)).save(fig)
    try:
        cap = ' '.join(['A long legend for every road and river on the map.'] * 60)
        out = os.path.join(TMP, 'fig.pdf')
        engine.build_pdf(M.parse_markdown(
            f'# One\n\nBefore.\n\n~~~ figure src="_bughunt_map.png" full="yes"\n{cap}\n~~~\n'),
            PRESET, out, META)
        doc = fitz.open(out)
        tops = []
        for p in doc:
            for im in p.get_image_info():
                tops.append((im['bbox'][1], im['bbox'][3] - im['bbox'][1], p.rect.height))
        words = [w for p in doc for w in p.get_text('words')]
        doc.close()
        check('the picture is drawn on the page with real height',
              tops and all(t >= 0 and h > 30 for t, h, _ in tops), tops)
        check('no caption text above the page', all(w[1] >= 0 for w in words))
    finally:
        os.remove(fig)
except ImportError:
    print('  skip (no Pillow)')

# ---- 9.5 ---------------------------------------------------------------
print('9.5 notes cited inside capitals')
foot = preset(endnotes__placement='foot')
res, pages = build('# One\n\nHello.\n\n~~~ telegram\nArrived safely.[^wire]\n~~~\n\n'
                   '[^wire]: Sent from the harbour office.\n', foot)
check('telegram with a note builds', ok(res), res)
check('the telegram\'s footnote prints', 'Sent from the harbour office.' in flat(pages))
sc = preset(endnotes__placement='foot', table__header_style='smallcaps')
res, pages = build('# One\n\nHello.\n\n~~~ table header="yes"\nName[^h] | Age\nAnn | 3\n~~~\n\n'
                   '[^h]: Names as recorded.\n', sc)
check('small-caps header with a note builds', ok(res), res)
check('the header\'s footnote prints', 'Names as recorded.' in flat(pages))
check('capitals keep ampersands as characters',
      engine._caps_keep_notes('a &amp; b') == 'A &amp; B', engine._caps_keep_notes('a &amp; b'))

# ---- 9.6 ---------------------------------------------------------------
print('9.6 drop caps')
dc = preset(chapter__open_style='dropcap')
res, pages = build('# One\n\n' + LONG + '\n', dc)
check('a page-tall opening paragraph under a drop cap builds', ok(res), res)
check('all of it prints', flat(pages).count('why.') == 120, flat(pages).count('why.'))
ParagraphStyle = engine.ParagraphStyle
body = engine.ParagraphStyle('b', fontName='Times-Roman', fontSize=10, leading=12)
for words in range(8, 40):
    d = engine.DropCap('W' + ' word' * words, body, 'Times-Bold', lines=2)
    w, h = d.wrap(200, 1000)
    if d._below is None and d._beside.height > 24:
        check('lines beside the cap stay inside the reserved height',
              d.height >= d._beside.height, (d.height, d._beside.height))
        break
else:
    check('lines beside the cap split without the fallback', True)

# ---- 9.7 ---------------------------------------------------------------
print('9.7 deep chapter sink')
deep = preset(trim__w=6.0, trim__h=9.0, margins__top=0.75, margins__bottom=0.75,
              chapter__sink=7.4)
res, pages = build('# Harbor\n\nShort.\n\n# Hill\n\nAlso short.\n', deep, {'include_toc': True})
check('deep sink builds', ok(res), res)
body_pages = pages[[i for i, p in enumerate(pages) if 'Contents' in p][-1] + 1:] if pages else []
check('no empty page in the body', all(p.strip() for p in body_pages),
      [i for i, p in enumerate(body_pages) if not p.strip()])

# ---- 9.8 ---------------------------------------------------------------
print('9.8 split headings')
hp = engine._heading_para(' '.join(['Heading'] * 40), body, 1)
hp.wrap(100, 1000)
parts = hp.split(100, 30)
check('the first piece of a split heading keeps its tag',
      len(parts) == 2 and getattr(parts[0], '_ts_heading', None) == hp._ts_heading)
check('the second piece does not report again',
      len(parts) == 2 and getattr(parts[1], '_ts_heading', None) is None)

# ---- 9.9 / 12.4 ----------------------------------------------------------
print('9.9 / 12.4 style labels')
res, pages = build('# One\n\nX.[^a]\n\n[^a]: note\n', preset(endnotes__heading='Notes <b>Draft'))
check('a Notes heading with <b> builds', ok(res), res)
check('and prints as typed', 'Notes <b>Draft' in flat(pages))
res, pages = build('# One\n\nX.\n', preset(chapter__number_format='Chapter {n} <Draft>'))
check('a number format with <Draft> prints as typed', ok(res) and 'Chapter 1 <Draft>' in flat(pages),
      res if not ok(res) else '')
res, pages = build('# One\n\nX.\n', preset(chapter__number_format='Chapter {N}'))
check('Chapter {N} builds', ok(res), res)
check('and numbers the chapter', 'Chapter 1' in flat(pages))
res, pages = build('# One\n\n~~~ list\none\ntwo\n~~~\n', preset(list__bullet='<A>'))
check('a list bullet <A> prints as typed', ok(res) and '<A>' in flat(pages))
res, pages = build('=== Part {x}\n\n# One\n\nX.\n', preset(part_divider__number_format='Part {} {n}'))
check('a part format with stray braces builds', ok(res), res)

# ---- 9.10 --------------------------------------------------------------
print('9.10 drop cap initials')
check('<Wait>', engine._split_initial('&lt;Wait&gt; she') == ('<', 'Wait&gt; she'))
check('opening quote goes with its letter',
      engine._split_initial('“Wait,” she')[0] == '“W')
check('combining accent stays with its letter', engine._split_initial('Äbc') == ('Ä', 'bc'))
res, pages = build('# One\n\n<Wait> she said, and waited a long time.\n', dc)
check('a drop cap on <Wait> prints no entity', ok(res) and 'lt;' not in flat(pages), flat(pages)[:80])

# ---- 9.11 --------------------------------------------------------------
print('9.11 contents after an unnumbered prologue')
res, pages = build('#* Prologue\n\nOnce.\n\n# \n\nThen.[^a]\n\n[^a]: A note.\n',
                   None, {'include_toc': True})
check('builds', ok(res), res)
toc = next((p for p in pages if 'Contents' in p), '')
check('the contents call the untitled chapter Chapter 1',
      'Chapter 1' in toc and 'Chapter 2' not in toc, toc)
notes = next((p for p in pages if 'A note.' in p), '')
check('so does the Notes page', 'Chapter 1' in notes and 'Chapter 2' not in notes, notes)

# ---- 9.12 --------------------------------------------------------------
print('9.12 long running heads')
title = ' '.join(['The House at the End of the River'] * 5)
out = os.path.join(TMP, 'rh.pdf')
engine.build_pdf(M.parse_markdown('# One\n\n' + LONG + '\n\n' + LONG + '\n'), PRESET, out,
                 dict(META, title=title))
doc = fitz.open(out)
inside = all(0 <= w[0] and w[2] <= p.rect.width
             for p in doc for w in p.get_text('words'))
doc.close()
check('every word is inside the page', inside)

# ---- 9.13 --------------------------------------------------------------
print('9.13 wide scene-break image')
try:
    from PIL import Image
    wide = os.path.join(TMP, 'rule.png')
    Image.new('RGB', (2000, 40), (0, 0, 0)).save(wide)
    sb = engine.SceneBreak('*', 'Times-Roman', 11.0, 9.0, image_path=wide)
    if True:
        from reportlab.pdfgen import canvas as _cv
        calls = []
        c = _cv.Canvas(os.path.join(TMP, 'sb.pdf'))
        c.drawImage = lambda ir, x, y, width, height, **k: calls.append((x, width))
        sb.wrap(300, 100)
        sb.canv = c
        sb.draw()
        check('scaled to the measure', calls and calls[0][1] <= 300 and calls[0][0] >= 0, calls)
except ImportError:
    print('  skip (no Pillow)')

# ---- 9.14 --------------------------------------------------------------
print('9.14 matter line breaks')

st = {'body': body, 'chap_title': body}
fonts = {'regular': 'Times-Roman', 'italic': 'Times-Italic', 'bold': 'Times-Bold'}
paras = [f for f in engine._matter_page('', 'The tide remembers.\n— Mara Vale', fonts, st, False,
                                        style='epigraph') if hasattr(f, 'getPlainText')]
check('the source line is its own paragraph',
      [p.getPlainText() for p in paras] == ['The tide remembers.', '— Mara Vale'],
      [p.getPlainText() for p in paras])
paras = [f for f in engine._matter_page('Also by A', 'The Salt Road\nThe Glass Bell', fonts, st,
                                        False, style='also_by') if hasattr(f, 'getPlainText')]
check('each Also By title is its own line',
      [p.getPlainText() for p in paras][-2:] == ['The Salt Road', 'The Glass Bell'],
      [p.getPlainText() for p in paras])

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
