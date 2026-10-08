"""The colour screen PDF (ROADMAP #74, Phases 3a and 3b)  (run: python test_screen.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

The contrast test came first: every fixture is built on a dark screen palette
and every span of text is measured against the pixels actually behind it, so
any ink the engine sets without asking the palette (a hard-coded grey, a black
default) shows up as text too dark to read. Then the print build of the same
style is checked to be the ordinary light book, and the pieces around it: the
display face, the role colours, game blocks on their fills, the cover left
alone, the bundled dark style and the app's "also make a screen PDF" option.
"""

import copy
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import logging; logging.disable(logging.INFO)
import manuscript

TMP = tempfile.mkdtemp(prefix='ts-screen-')
FIX = os.path.join(HERE, 'test_fixtures', 'ttrpg')

# the dark palette measured from the author's own book (ROADMAP #74 Phase 3)
DARK = {'page': '#0c1116', 'text': '#ddd5c2', 'heading': '#c2a35e', 'accent': '#62c3c8'}
FLOOR = 3.0          # WCAG's floor for large text; body text here measures far above

_failures = []


def _check(label, cond, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        if detail:
            print(f"         {detail}")
        _failures.append(label)


def _preset(screen=DARK, **sections):
    import app
    p = copy.deepcopy(app.DEFAULTS)
    p['screen'] = dict(screen)
    for k, v in sections.items():
        p[k] = {**p.get(k, {}), **v}
    return p


def _build(md, preset, name, screen=True, meta=None):
    import engine
    out = os.path.join(TMP, name + '.pdf')
    m = {'title': 'The Valley Book', 'author': 'A. Writer', 'include_toc': True}
    m.update(meta or {})
    res = engine.build_pdf(manuscript.parse_markdown(md), preset, out, m, screen=screen)
    return out, res


def _rgb(n):
    return ((n >> 16) & 255) / 255.0, ((n >> 8) & 255) / 255.0, (n & 255) / 255.0


def _low_contrast(path, floor=FLOOR, dpi=48):
    """[(page, text, ratio)] for every span under `floor` against the most
    common colour in its box (the text itself is the minority). Pixels are
    grouped by near colour first and the winning group averaged: on a textured
    page background (Phase 3b's parchment) no two pixels match exactly, and a
    solid heading would otherwise outvote the page behind it."""
    import collections
    import fitz
    from reportlab.lib.colors import Color
    import engine
    bad = []
    doc = fitz.open(path)
    for pno, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        sx, sy = pix.width / page.rect.width, pix.height / page.rect.height
        for blk in page.get_text('dict')['blocks']:
            for line in blk.get('lines', []):
                for span in line['spans']:
                    if not span['text'].strip():
                        continue
                    x0, y0, x1, y1 = span['bbox']
                    seen = collections.defaultdict(list)
                    for px in range(max(0, int(x0 * sx)), min(pix.width, int(x1 * sx) + 1)):
                        for py in range(max(0, int(y0 * sy)), min(pix.height, int(y1 * sy) + 1)):
                            rgb = pix.pixel(px, py)[:3]
                            seen[tuple(v // 24 for v in rgb)].append(rgb)
                    if not seen:
                        continue
                    group = max(seen.values(), key=len)
                    bg = Color(*[sum(c[i] for c in group) / len(group) / 255.0 for i in range(3)])
                    ratio = engine.contrast(Color(*_rgb(span['color'])), bg)
                    if ratio < floor:
                        bad.append((pno + 1, span['text'][:30], round(ratio, 2)))
    return bad


def _fixtures():
    names = ['adventure.md', 'statblocks.md', 'edge_cases.md', 'reference.md']
    out = [(n, open(os.path.join(FIX, n), encoding='utf-8').read()) for n in names]
    sample = os.path.join(HERE, 'sample', 'sample.md')
    if os.path.exists(sample):
        out.append(('sample.md', open(sample, encoding='utf-8').read()))
    return out


def test_contrast():
    print("contrast: every fixture on a dark page")
    for name, md in _fixtures():
        out, res = _build(md, _preset(), 'dark-' + name[:-3],
                          meta={'front_matter': 'full'})
        bad = _low_contrast(out)
        _check(f"{name}: every span reads on the dark page ({res['page_count']} pages)",
               not bad, bad[:6])
    # the game blocks keep their light default fills on a dark page: their text
    # follows the fill, not the page
    md = ('# Blocks\n\n~~~ readaloud title="Read This"\nThe door creaks.\n~~~\n\n'
          '~~~ sidebar title="Side"\nA box.\n~~~\n\n~~~ sidebar title="Pace" style="note"\n'
          'Ten minutes.\n~~~\n\n~~~ statblock cr="1"\nBog Hound\n*Medium beast*\n'
          'Armor Class: 12\nSTR 10 | DEX 14 | CON 12 | INT 3 | WIS 10 | CHA 5\n'
          '--- Actions\n***Bite.*** +4 to hit.\n~~~\n')
    out, _ = _build(md, _preset(), 'dark-blocks')
    bad = _low_contrast(out)
    _check("light block fills on a dark page keep readable text", not bad, bad)
    # and the measure itself catches what it is for: a heading set in the page colour
    out, _ = _build('# Lost\n\nText.\n', _preset(screen=dict(DARK, heading='#14191e')),
                    'dark-lost', meta={'include_toc': False, 'front_matter': 'none'})
    _check("the contrast measure flags unreadable text",
           [b[1] for b in _low_contrast(out)] == ['Lost'], _low_contrast(out))


def test_print_stays_light():
    print("\nthe print build of a dark style")
    import fitz
    md = open(os.path.join(FIX, 'reference.md'), encoding='utf-8').read()
    out, res = _build(md, _preset(), 'print-of-dark', screen=False,
                      meta={'front_matter': 'none'})
    doc = fitz.open(out)
    pix = doc[2].get_pixmap(dpi=20)
    _check("the page is white", pix.pixel(2, 2)[:3] == (255, 255, 255), pix.pixel(2, 2))
    colours = {s['color'] for p in doc for b in p.get_text('dict')['blocks']
               for l in b.get('lines', []) for s in l['spans']}
    _check("no text is in a screen colour",
           not colours & {0xddd5c2, 0xc2a35e, 0x62c3c8}, sorted(hex(c) for c in colours))
    _check("the build says it is not the screen one", res['screen'] is False)

    out2, res2 = _build(md, _preset(), 'screen-of-dark', meta={'front_matter': 'none'})
    d2 = fitz.open(out2)
    pix = d2[2].get_pixmap(dpi=20)
    _check("the screen build paints the page", pix.pixel(2, 2)[:3] == (12, 17, 22),
           pix.pixel(2, 2))
    _check("…and says so", res2['screen'] is True)
    _check("the two lay out alike", res2['page_count'] == res['page_count'],
           (res['page_count'], res2['page_count']))


def _span_colours(path, text):
    import fitz
    return {s['color'] for p in fitz.open(path) for b in p.get_text('dict')['blocks']
            for l in b.get('lines', []) for s in l['spans'] if text in s['text']}


def test_roles_and_fonts():
    print("\nrole colours and the display face")
    import fitz
    md = ('=== The Valley\n\n# The Drowned Chapel\n#> Bells under water.\n\n'
          'Body text here.\n\n## Approach\n\n### A1. Porch\n\nMore text.\n')
    p = _preset(font_files={'display': 'Cinzel-Bold.ttf'})
    out, _ = _build(md, p, 'roles', meta={'include_toc': False, 'front_matter': 'none'})
    _check("titles take the heading colour",
           _span_colours(out, 'The Drowned Chapel') == {0xc2a35e}
           and _span_colours(out, 'Approach') == {0xc2a35e},
           [hex(c) for c in _span_colours(out, 'Approach')])
    _check("chapter number, tagline and section take the accent",
           _span_colours(out, 'Chapter 1') == {0x62c3c8}
           and _span_colours(out, 'Bells under water.') == {0x62c3c8}
           and _span_colours(out, 'A1. Porch') == {0x62c3c8})
    _check("body text takes the text colour", _span_colours(out, 'More text.') == {0xddd5c2})
    fonts = {s['font'] for pg in fitz.open(out) for b in pg.get_text('dict')['blocks']
             for l in b.get('lines', []) for s in l['spans'] if 'Drowned' in s['text']}
    _check("the display face sets the title", any('Cinzel' in f for f in fonts), fonts)

    unset = _preset(screen={'page': '#0c1116', 'text': '#ddd5c2', 'heading': '', 'accent': ''})
    out, _ = _build(md, unset, 'no-roles', meta={'include_toc': False, 'front_matter': 'none'})
    _check("no heading colour: titles are text-coloured",
           _span_colours(out, 'The Drowned Chapel') == {0xddd5c2})

    plain = _preset(screen={})
    out, _ = _build(md, plain, 'plain-screen', meta={'include_toc': False, 'front_matter': 'none'})
    pix = fitz.open(out)[0].get_pixmap(dpi=20)
    _check("an empty palette is the print look on screen",
           pix.pixel(2, 2)[:3] == (255, 255, 255)
           and _span_colours(out, 'More text.') == {0})


def test_blocks_screen_colours():
    print("\ngame blocks use their screen colours")
    md = '# B\n\n~~~ readaloud\nThe door creaks.\n~~~\n'
    p = _preset(screen={}, readaloud={'fill': '#204060', 'print_fill': '#eeeeee'})
    import fitz
    for screen, want in ((True, (32, 64, 96)), (False, (238, 238, 238))):
        out, _ = _build(md, p, f'ra-{screen}', screen=screen,
                        meta={'include_toc': False, 'front_matter': 'none'})
        page = fitz.open(out)[0]
        r = [s for b in page.get_text('dict')['blocks'] for l in b.get('lines', [])
             for s in l['spans'] if 'creaks' in s['text']][0]['bbox']
        pix = page.get_pixmap(dpi=72)
        got = pix.pixel(int(r[0]) - 3, int((r[1] + r[3]) / 2))[:3]
        _check(f"{'screen' if screen else 'print'} build: the {'screen' if screen else 'print'} fill",
               all(abs(a - b) <= 2 for a, b in zip(got, want)), got)
    out, _ = _build(md, p, 'ra-text', meta={'include_toc': False, 'front_matter': 'none'})
    bad = _low_contrast(out)
    _check("black text on a dark fill turns light", not bad, bad)


def test_cover_kept():
    print("\nthe cover keeps its own colours")
    import fitz
    import app
    tpl = app.load_cover_template(app.list_cover_templates()[0]['id'])
    meta = {'include_toc': False, 'front_matter': 'none', 'cover_mode': 'designed',
            'cover_template': 'x', 'cover_template_data': tpl}
    md = '# One\n\nText.\n'
    a, _ = _build(md, _preset(), 'cover-screen', meta=meta)
    b, _ = _build(md, _preset(), 'cover-print', screen=False, meta=meta)
    pa = fitz.open(a)[0].get_pixmap(dpi=20)
    pb = fitz.open(b)[0].get_pixmap(dpi=20)
    _check("the cover page is the same in both builds", pa.samples == pb.samples)


def test_bundled_style():
    print("\nthe bundled dark style")
    import app
    import fitz
    p = app.load_preset('game-dark-screen')
    _check("it is US Letter", (p['trim']['w'], p['trim']['h']) == (8.5, 11.0), p['trim'])
    _check("it has a dark screen palette",
           p['screen']['page'] and app.engine.contrast(
               app.engine._hex(p['screen']['page']), app.engine._hex('#ffffff')) > 12)
    _check("its display face is bundled", p['font_files'].get('display') in app.BUILTIN_FONTS)
    md = open(os.path.join(FIX, 'adventure.md'), encoding='utf-8').read()
    out, _ = _build(md, p, 'bundled-screen', meta={'front_matter': 'full'})
    bad = _low_contrast(out)
    _check("an adventure in it reads on screen", not bad, bad[:6])
    out, _ = _build(md, p, 'bundled-print', screen=False, meta={'front_matter': 'full'})
    pix = fitz.open(out)[4].get_pixmap(dpi=20)
    _check("its print build is light", pix.pixel(2, 2)[:3] == (255, 255, 255))
    bad = _low_contrast(out)
    _check("…and reads", not bad, bad[:6])


PARCH = {'page': '#f3e9d2', 'text': '#2a2118', 'heading': '#6b1d14', 'accent': '#7d3a12'}


def test_backgrounds():
    print("\npage backgrounds (Phase 3b)")
    import fitz
    import engine
    a, b = os.path.join(TMP, 'p1.jpg'), os.path.join(TMP, 'p2.jpg')
    engine.make_parchment(a)
    engine.make_parchment(b)
    _check("the parchment is the same file every time",
           open(a, 'rb').read() == open(b, 'rb').read())
    _check("the app has put it in the figure library",
           os.path.exists(os.path.join(engine.FIGURE_DIR, engine.PARCHMENT)))
    bg = {'image': engine.PARCHMENT, 'color': '', 'opacity': 1.0}
    for name, md in _fixtures():
        out, res = _build(md, _preset(screen=PARCH, page_background=bg), 'parch-' + name[:-3],
                          meta={'front_matter': 'full'})
        bad = _low_contrast(out)
        _check(f"{name}: every span reads on parchment ({res['page_count']} pages)",
               not bad, bad[:6])
    md = open(os.path.join(FIX, 'adventure.md'), encoding='utf-8').read()
    out, _ = _build(md, _preset(screen=PARCH, page_background=bg), 'parch-imgs')
    d = fitz.open(out)
    _check("every page of the screen PDF has the picture under it",
           all(p.get_images() for p in d), [i for i, p in enumerate(d) if not p.get_images()])
    _check("…embedded once", len({x[0] for p in d for x in p.get_images()}) == 1)
    out, _ = _build(md, _preset(screen=PARCH, page_background=bg), 'parch-print', screen=False)
    d = fitz.open(out)
    _check("the print build has no background",
           not any(p.get_images() for p in d) and d[4].get_pixmap(dpi=20).pixel(2, 2)[:3]
           == (255, 255, 255))
    # a faint parchment over the dark page still reads
    out, _ = _build(md, _preset(page_background=dict(bg, opacity=0.1)), 'parch-dark')
    bad = _low_contrast(out)
    _check("a faint background on the dark page reads", not bad, bad[:6])
    # the colour under it, and a picture that is gone
    out, _ = _build('# One\n\nText.\n', _preset(page_background={'image': 'gone.png',
                                                                'color': '#203040'}),
                    'bg-colour', meta={'include_toc': False, 'front_matter': 'none'})
    px = fitz.open(out)[0].get_pixmap(dpi=20).pixel(2, 2)[:3]
    _check("a missing picture leaves the colour under it",
           all(abs(v - w) <= 2 for v, w in zip(px, (0x20, 0x30, 0x40))), px)
    # and the measure sees a background that drowns the text: light ink on parchment
    out, _ = _build('# Lost\n\nText.\n', _preset(page_background=bg), 'parch-lost',
                    meta={'include_toc': False, 'front_matter': 'none'})
    _check("the contrast measure flags text the background drowns",
           len(_low_contrast(out)) >= 2, _low_contrast(out))


def test_furniture():
    print("\npage furniture (Phase 3b)")
    import fitz
    import engine
    import ornaments
    _check("every piece has a known slot",
           all(d['slot'] in ornaments.FURNITURE_SLOTS for d in ornaments.FURNITURE))
    _check("no piece shares an id with a scene-break ornament",
           not set(ornaments.FURNITURE_BY_ID) & set(ornaments.BY_ID))
    _check("each draws as SVG for the picker",
           all(ornaments.svg(d['id']).startswith('<svg') for d in ornaments.FURNITURE))
    md = open(os.path.join(FIX, 'reference.md'), encoding='utf-8').read()
    for hd, ft, co in (('bar-tapered', 'band-solid', 'corner-bracket'),
                       ('bar-diamond', 'band-double', 'corner-flourish'),
                       ('bar-studded', 'band-tapered', 'corner-wedge')):
        fu = {'header': hd, 'footer': ft, 'corner': co, 'color': ''}
        out, _ = _build(md, _preset(furniture=fu), 'fu-' + hd)
        bad = _low_contrast(out)
        _check(f"{hd} / {ft} / {co}: the text still reads", not bad, bad[:6])
    fu = {'header': 'bar-tapered', 'footer': 'band-solid', 'corner': 'corner-wedge',
          'color': '#c2a35e'}
    plain, _ = _build(md, _preset(), 'fu-none')
    out, _ = _build(md, _preset(furniture=fu), 'fu-gold')
    a, b = fitz.open(plain), fitz.open(out)

    def corner(page):
        """The pixel just inside the bottom-left corner piece (inset 0.25in)."""
        pix = page.get_pixmap(dpi=72)
        return pix.pixel(int(0.29 * 72), pix.height - int(0.29 * 72))[:3]
    gold = [i for i, p in enumerate(b) if corner(p)[0] > 150 and corner(p)[2] < 130]
    _check("corner pieces are drawn in the style's colour", gold, [corner(p) for p in b])
    _check("…on body pages only: the first pages are as they were",
           gold and all(a[i].get_pixmap(dpi=20).samples == b[i].get_pixmap(dpi=20).samples
                        for i in range(min(gold))))
    out, _ = _build(md, _preset(furniture=fu), 'fu-print', screen=False)
    px = [corner(p) for i, p in enumerate(fitz.open(out)) if i in gold]
    _check("the print build draws them grey",
           px and all(c[0] == c[1] == c[2] and c[0] < 200 for c in px), px[:3])
    try:
        engine.build_pdf(manuscript.parse_markdown(md), _preset(furniture=fu),
                         os.path.join(TMP, 'fu-press.pdf'),
                         {'title': 'T', 'author': 'A'}, press=True)
        ok = True
    except Exception as e:        # the CMYK canvas refuses any colour
        ok = str(e)
    _check("…and the press build accepts them", ok is True, ok)
    out, _ = _build('# One\n\nText.\n', _preset(furniture={'header': 'corner-wedge',
                                                            'footer': 'nonsense'}), 'fu-bad')
    _check("a piece in the wrong slot, or unknown, is ignored", os.path.exists(out))


def test_bundled_3b():
    print("\nthe light rulebook and the A5 zine")
    import app
    import fitz
    md = open(os.path.join(FIX, 'adventure.md'), encoding='utf-8').read()
    for pid, trim in (('game-light-rulebook', (8.5, 11.0)), ('game-zine-a5', (5.83, 8.27))):
        p = app.load_preset(pid)
        _check(f"{pid}: its trim", (p['trim']['w'], p['trim']['h']) == trim, p['trim'])
        _check(f"{pid}: no poem section (the style editor can't save one)", 'poem' not in p)
        out, _ = _build(md, p, pid + '-screen', meta={'front_matter': 'full'})
        bad = _low_contrast(out)
        _check(f"{pid}: its screen PDF reads", not bad, bad[:6])
        out, _ = _build(md, p, pid + '-print', screen=False, meta={'front_matter': 'full'})
        d = fitz.open(out)
        _check(f"{pid}: its print build is light, no background",
               d[4].get_pixmap(dpi=20).pixel(2, 2)[:3] == (255, 255, 255)
               and not any(pg.get_images() for pg in d))
        bad = _low_contrast(out)
        _check(f"{pid}: …and reads", not bad, bad[:6])
    p = app.load_preset('game-light-rulebook')
    _check("the rulebook's screen PDF is on parchment",
           p['page_background']['image'] == app.engine.PARCHMENT)


def test_style_form():
    print("\nthe style form")
    import app
    with app.app.test_request_context():
        p = app.parse_preset_form({'sc_page': '#0c1116', 'sc_text': 'nonsense',
                                   'sc_heading': '#C2A35E', 'font_display': 'Cinzel-Bold.ttf'})
    _check("the screen palette is saved, a bad colour cleared",
           p['screen'] == {'page': '#0c1116', 'text': '', 'heading': '#C2A35E', 'accent': ''},
           p['screen'])
    _check("the display face is saved", p['font_files'].get('display') == 'Cinzel-Bold.ttf')
    with app.app.test_request_context():
        p = app.parse_preset_form({})
    _check("no display face: the key is left out", 'display' not in p['font_files'])
    _check("no background or furniture by default",
           p['page_background'] == app.engine.PAGE_BACKGROUND_DEFAULTS
           and p['furniture'] == app.engine.FURNITURE_DEFAULTS, (p['page_background'], p['furniture']))
    with app.app.test_request_context():
        p = app.parse_preset_form({'pb_image': 'parchment.jpg', 'pb_opacity': '1.7',
                                   'pb_color': 'brown', 'fu_header': 'bar-diamond',
                                   'fu_footer': 'corner-wedge', 'fu_corner': 'corner-flourish',
                                   'fu_color': '#6b1d14'})
    _check("the background is saved, its strength clamped, a bad colour cleared",
           p['page_background'] == {'image': 'parchment.jpg', 'color': '', 'opacity': 1.0},
           p['page_background'])
    _check("furniture is saved, a piece in the wrong slot cleared",
           p['furniture'] == {'header': 'bar-diamond', 'footer': '', 'corner': 'corner-flourish',
                              'color': '#6b1d14'}, p['furniture'])
    with app.app.test_client() as c:
        page = c.get('/editor/game-light-rulebook').get_data(as_text=True)
    _check("the editor shows the background and furniture pickers",
           'name="pb_image"' in page and 'name="fu_corner"' in page
           and 'value="bar-tapered" selected' in page, '')
    _check("deleting the parchment would warn which style uses it",
           any('page background' in u for u in app._figure_uses(app.engine.PARCHMENT)))


def test_app_builds_both():
    print("\nthe app: also make a screen PDF")
    import json
    import shutil
    import app as A
    tmp = tempfile.mkdtemp(prefix='ts-screen-app-')
    saved = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR')}
    try:
        A.PROJECT_DIR = os.path.join(tmp, 'projects')
        A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
        A.OUT_DIR = os.path.join(tmp, 'out')
        for d in (A.PROJECT_MS_DIR, A.OUT_DIR):
            os.makedirs(d)
        with open(os.path.join(A.PROJECT_MS_DIR, 'g.md'), 'w', encoding='utf-8') as f:
            f.write('# One\n\nText.\n')
        proj = {'name': 'G', 'title': 'G', 'preset': 'game-dark-screen',
                'manuscript_file': 'g.md', 'manuscript_type': 'markdown',
                'format': 'pdf', 'screen_pdf': True}
        with open(os.path.join(A.PROJECT_DIR, 'g.json'), 'w', encoding='utf-8') as f:
            json.dump(proj, f)
        res = A._build_project('g', A.load_project('g'))
        _check("the build has no error", not res['error'], res['error'])
        screen = res.get('screen_name')
        _check("a screen PDF is made beside the print one",
               screen and screen != res['out_name'] and screen.endswith('-screen.pdf')
               and os.path.exists(os.path.join(A.OUT_DIR, screen)), screen)
        _check("the project remembers it", A.load_project('g').get('last_screen_pdf') == screen)
        with A.app.test_client() as c:
            page = c.post('/project/g/generate').get_data(as_text=True)
        _check("the result page offers it", 'Download screen PDF' in page)
        proj['screen_pdf'] = False
        with open(os.path.join(A.PROJECT_DIR, 'g.json'), 'w', encoding='utf-8') as f:
            json.dump(proj, f)
        res = A._build_project('g', A.load_project('g'))
        _check("off: only the print PDF", not res.get('screen_name'))
    finally:
        for k, v in saved.items():
            setattr(A, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_contrast()
    test_print_stays_light()
    test_roles_and_fonts()
    test_blocks_screen_colours()
    test_cover_kept()
    test_bundled_style()
    test_backgrounds()
    test_furniture()
    test_bundled_3b()
    test_style_form()
    test_app_builds_both()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        sys.exit(1)
    print("ALL PASS")
