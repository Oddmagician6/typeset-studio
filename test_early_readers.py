"""Early readers and chapter books (ROADMAP #75a)  (run: python test_early_readers.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.
Everything runs against throwaway folders (test_outputs' set-up, imported).

    SPACE      `para_space`: a gap between the manuscript's own paragraphs, and
               only those; none in a style that doesn't set it
    WHOLE      `keep_whole`: no paragraph split by a page turn, one taller than a
               page still breaks (no loop, no lost words), two columns unaffected
    EBOOK      the two options in the ebook's stylesheet, and nothing when unset
    EDITOR     the style editor shows, keeps and clears them, and never writes
               them into a style that never had them
    STYLES     Early Reader and Chapter Book: Andika, their sizes and trims,
               built over the sample in print, screen and ebook; their large print
    TRIMS      the square trims, and a book built on one
"""
import copy, os, re, sys, traceback, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import test_outputs as T          # points the app at throwaway folders
import app as A
import engine, epub, manuscript
import fitz

fails = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


META = {'title': 'The Kite Day', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True}
WORDS = ('the kite went up and up over the hill and the dog ran after it '
         'with a big red ball in his mouth ').split()


def para(i, n):
    """Paragraph i: n words between its own start and end markers."""
    body = ' '.join(WORDS[k % len(WORDS)] for k in range(n))
    return f'P{i:02d}a {body} P{i:02d}z.'


def build(md, p, name, screen=False):
    out = os.path.join(T.tmp, name + '.pdf')
    engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META), screen=screen)
    return out


def marker_pages(pdf):
    """{'P03a': page, 'P03z': page, ...}"""
    out = {}
    with fitz.open(pdf) as d:
        for pno, pg in enumerate(d):
            for w in pg.get_text('words'):
                m = re.match(r'(P\d\d[az])', w[4])
                if m:
                    out.setdefault(m.group(1), pno)
    return out


def split_paras(pdf, n):
    pages = marker_pages(pdf)
    return [i for i in range(n)
            if pages.get(f'P{i:02d}a') != pages.get(f'P{i:02d}z')]


def line_tops(pdf, page=0):
    """The y of each body line on a page, top to bottom."""
    with fitz.open(pdf) as d:
        ys = sorted({round(w[1], 1) for w in d[page].get_text('words')})
    return ys


def style(**body):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False, justify=False, **body)
    # a plain opening: a small-caps lead-in would print the first marker as P00A
    p['chapter'] = dict(p['chapter'], open_style='none')
    return p


# ---------------------------------------------------------------- SPACE
def space_tests():
    print('\n[para_space]')
    fonts = engine.register_fonts(style()) if hasattr(engine, 'register_fonts') else None
    st = engine._styles(style(para_space=10.0), fonts or {'regular': 'Times-Roman'})
    check('the paragraph style carries the gap', st['para'].spaceBefore == 10.0, st['para'].spaceBefore)
    check('the body style (letters, poems, lists) does not', st['body'].spaceBefore == 0,
          st['body'].spaceBefore)
    st0 = engine._styles(style(), fonts or {'regular': 'Times-Roman'})
    check('no gap in a style that does not set it', st0['para'].spaceBefore == 0)

    md = '# One\n\n' + '\n\n'.join(para(i, 12) for i in range(6)) + '\n'
    plain = build(md, style(indent=0.0), 'space-off')
    gapped = build(md, style(indent=0.0, para_space=12.0), 'space-on')
    lead = A.DEFAULTS['body']['leading']

    def steps(pdf):
        ys = line_tops(pdf)
        return [round(b - a, 1) for a, b in zip(ys, ys[1:])]
    s0, s1 = steps(plain), steps(gapped)
    check('without it every line is one leading apart',
          s0 and max(s0[2:]) <= lead + 1.5, s0)
    # (the first steps are the chapter number and title)
    gaps = [s for s in s1 if abs(s - (lead + 12)) <= 2]
    check('with it, each paragraph opens a gap of the setting', len(gaps) == 5, s1)
    check('and lines inside a paragraph stay one leading apart',
          all(s <= lead + 1.5 or abs(s - (lead + 12)) <= 2 for s in s1[2:]), s1)


# ---------------------------------------------------------------- WHOLE
def whole_tests():
    print('\n[keep_whole]')
    n = 30
    md = '# One\n\n' + '\n\n'.join(para(i, 25 + (i * 7) % 30) for i in range(n)) + '\n'
    off = build(md, style(), 'whole-off')
    on = build(md, style(keep_whole=True), 'whole-on')
    check('the test can see a split: without it some paragraphs cross a page',
          split_paras(off, n), split_paras(off, n))
    check('with it, no paragraph crosses a page', not split_paras(on, n), split_paras(on, n))
    w_off, w_on = T.collections.Counter(), T.collections.Counter()
    for pdf, c in ((off, w_off), (on, w_on)):
        with fitz.open(pdf) as d:
            for pg in d:
                c.update(re.findall(r"[a-z]+", pg.get_text()))
    check('and no word is lost', w_off == w_on, (w_off - w_on, w_on - w_off))

    # a paragraph longer than a page: it still breaks, with every word
    long_md = '# One\n\n' + para(0, 20) + '\n\n' + para(1, 900) + '\n\n' + para(2, 20) + '\n'
    try:
        pdf = build(long_md, style(keep_whole=True), 'whole-long')
        with fitz.open(pdf) as d:
            text = ' '.join(pg.get_text() for pg in d)
        check('a paragraph taller than the page still builds and breaks',
              all(f'P0{i}{e}' in text for i in range(3) for e in 'az')
              and len(set(marker_pages(pdf).values())) > 1, marker_pages(pdf))
    except Exception:
        check('a paragraph taller than the page still builds', False, traceback.format_exc()[-600:])

    # the opening paragraph and the first after a break are kept too
    md2 = ('# One\n\n' + para(0, 230) + '\n\n* * *\n\n' + para(1, 120) + '\n\n'
           + '\n\n'.join(para(i, 60) for i in range(2, 12)) + '\n')
    pdf = build(md2, style(keep_whole=True, size=14.0, leading=21.0), 'whole-first')
    check('the first paragraph and the one after a break are kept whole too',
          not split_paras(pdf, 12), split_paras(pdf, 12))

    # two columns: the option is left alone there, and nothing is lost
    p2 = style(keep_whole=True)
    p2['trim'] = {'w': 8.5, 'h': 11.0}
    p2['columns'] = {'count': 2, 'gap': 0.25}
    try:
        pdf = build(md, p2, 'whole-cols')
        with fitz.open(pdf) as d:
            text = ' '.join(pg.get_text() for pg in d)
        check('two columns with it set build and keep every paragraph',
              all(f'P{i:02d}z' in text for i in range(n)))
    except Exception:
        check('two columns with it set build', False, traceback.format_exc()[-600:])


# ---------------------------------------------------------------- EBOOK
def ebook_tests():
    print('\n[the ebook]')
    check('no rule when neither is set', epub._body_css(style()) == '')
    css = epub._body_css(style(para_space=11.0, size=11.0, keep_whole=True))
    check('block paragraphs: no indent, a gap in ems',
          'text-indent: 0' in css and 'margin-top: 1.00em' in css, css)
    check('kept whole: no break inside', 'break-inside: avoid' in css, css)
    check('only the manuscript paragraphs, not chapter art or a block',
          css.startswith('.chapter > p:not([class]), .chapter > p.no-indent'), css)
    full = epub._style_css(style(para_space=11.0))
    check('it comes after the static paragraph rule, so it wins',
          full.index('p { margin: 0; text-indent: 1.5em; }') < full.index('.chapter > p:not'))


# ---------------------------------------------------------------- EDITOR
def editor_tests():
    print('\n[the style editor]')
    C = T.C
    before = A.load_preset('early-reader')
    html = C.get('/editor/early-reader').get_data(as_text=True)
    check('it shows the gap', 'name="b_para_space" value="12.0"' in html)
    check('it shows keep whole ticked',
          re.search(r'name="b_keep_whole"\s+checked', html) is not None)
    form = T.form_of(html, '/save/')
    C.post('/save/early-reader', data=form)
    after = A.load_preset('early-reader')
    check('saved unchanged, the body is as it was', after['body'] == before['body'],
          (before['body'], after['body']))
    form['b_para_space'] = '0'
    form.pop('b_keep_whole', None)
    C.post('/save/early-reader', data=form)
    after = A.load_preset('early-reader')
    check('cleared, both keys are gone',
          'para_space' not in after['body'] and 'keep_whole' not in after['body'], after['body'])

    for pid in ('classic-literary', 'game-light-rulebook'):
        html = C.get(f'/editor/{pid}').get_data(as_text=True)
        C.post(f'/save/{pid}', data=T.form_of(html, '/save/'))
        b = A.load_preset(pid)['body']
        check(f'{pid} saved unchanged gains neither', 'para_space' not in b
              and 'keep_whole' not in b, b)


# ---------------------------------------------------------------- STYLES
def styles_tests():
    print('\n[the bundled styles]')
    check('Andika is a bundled family, protected',
          {'Andika-Regular.ttf', 'Andika-Bold.ttf', 'Andika-Italic.ttf'} <= A.BUILTIN_FONTS)
    check('its licence is filed', os.path.exists(os.path.join(HERE, 'fonts', 'licenses', 'Andika-OFL.txt')))
    want = {'early-reader': ((6.0, 9.0), 18.0, True), 'chapter-book': ((5.5, 8.5), 14.0, False)}
    sample = open(A.SAMPLE, encoding='utf-8').read()
    for pid, (trim, size, kept) in want.items():
        try:
            p = A.load_preset(pid)
            check(f'{pid}: trim, size, Andika',
                  (p['trim']['w'], p['trim']['h']) == trim and p['body']['size'] == size
                  and p['font_files']['regular'] == 'Andika-Regular.ttf', (p['trim'], p['body']))
            check(f'{pid}: ragged right, no hyphens',
                  not p['body']['justify'] and not p['body']['hyphenate'])
            check(f'{pid}: paragraphs kept whole only in the early reader',
                  bool(p['body'].get('keep_whole')) == kept)
            pdf = build(sample, p, f'style-{pid}')
            sizes, faces = T.collections.Counter(), set()
            with fitz.open(pdf) as d:
                pw, ph = d[0].rect.width, d[0].rect.height
                for pg in d:
                    for b in pg.get_text('dict')['blocks']:
                        for ln in b.get('lines', []):
                            for s in ln['spans']:
                                if len(s['text'].strip()) > 3:
                                    sizes[round(s['size'])] += len(s['text'])
                                    faces.add(s['font'])
            check(f'{pid}: the page is the trim', (round(pw), round(ph)) ==
                  (round(trim[0] * 72), round(trim[1] * 72)), (pw, ph))
            check(f'{pid}: the text is set at its size',
                  sizes.most_common(1)[0][0] == round(size), sizes.most_common(3))
            check(f'{pid}: in Andika', any('Andika' in f for f in faces), faces)
            build(sample, p, f'style-{pid}-screen', screen=True)
            out = os.path.join(T.tmp, f'style-{pid}.epub')
            epub.build_epub(manuscript.parse_markdown(sample), p, out, dict(META))
            probs = T.validate(out)
            check(f'{pid}: the ebook validates', not probs, probs[:5])
            css = zipfile.ZipFile(out).read('OEBPS/style.css').decode('utf-8')
            check(f'{pid}: the ebook carries its paragraph rule only if it sets one',
                  ('.chapter > p:not' in css) == bool(p['body'].get('para_space')))
            lp = A.make_large_print(p)
            check(f'{pid}: large print keeps at least 16pt and the trim fits',
                  lp['body']['size'] >= 16 and lp['trim']['w'] >= 7, (lp['body'], lp['trim']))
        except Exception:
            check(f'{pid}: builds', False, traceback.format_exc()[-900:])


# ---------------------------------------------------------------- TRIMS
def trims_tests():
    print('\n[square trims]')
    sizes = {(w, h) for w, h, _ in A.TRIM_PRESETS}
    check('8.25 and 8.5 square are offered', {(8.25, 8.25), (8.5, 8.5)} <= sizes)
    p = A.load_preset('early-reader')
    p['trim'] = {'w': 8.5, 'h': 8.5}
    pdf = build('# One\n\n' + para(0, 40) + '\n', p, 'square')
    with fitz.open(pdf) as d:
        r = d[0].rect
    check('a book on one is square', round(r.width) == round(r.height) == 612, r)


if __name__ == '__main__':
    # the editor tests last: they clear the early reader's options
    for t in (space_tests, whole_tests, ebook_tests, styles_tests, trims_tests, editor_tests):
        try:
            t()
        except Exception:
            check(t.__name__ + ' ran', False, traceback.format_exc()[-900:])
    print(f'\n{"ALL PASS" if not fails else str(len(fails)) + " FAILED"}')
    sys.exit(1 if fails else 0)
