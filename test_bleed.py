"""Full-bleed interiors (ROADMAP #74, Phase 6a)  (run: python test_bleed.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.

A book's `bleed` switch builds its print pages 0.125" bigger on the outer
edge, the top and the bottom, with the trim declared on every page. What is
held here:

  1. off (the default): pages are the trim, as before;
  2. on: every page is trim + bleed, its TrimBox sits in from the outer edge
     (the right of a recto, the left of a verso), and every word stands where
     it stood without bleed, measured from the trim; press-ready too;
  3. `full="bleed"` figures: out to the paper's edge on the outer side, with
     no folio; inside the margins and reported in a book without bleed; to
     the page edge on the screen PDF; across both columns; in the ebook;
  4. the style's page background prints, to the edge, in a book with bleed;
  5. the switch through the app: off unless set, never written into a book
     that doesn't use it, and reported in the checks and the print package.
"""
import copy, json, os, shutil, sys, tempfile, traceback, zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)
import logging; logging.disable(logging.INFO)
import fitz
from PIL import Image
import manuscript, engine, epub, app as A
from test_project_edit import form_of


def _form_of(html):
    return form_of(html, '/project/g/edit')

TMP = tempfile.mkdtemp(prefix='ts-bleed-')
results = []
B = 0.125 * 72          # the bleed, in points
FIG, FIG_RGB = '_bleed_fig.png', (30, 90, 160)
BG, BG_RGB = '_bleed_bg.png', (200, 150, 60)


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (('\n         ' + str(detail)) if detail and not cond else ''))
    results.append((label, bool(cond)))


def preset(cols=1, **sections):
    p = copy.deepcopy(A.DEFAULTS)
    p['body'] = dict(p['body'], hyphenate=False)
    if cols == 2:
        p['trim'] = {'w': 8.5, 'h': 11.0}
        p['columns'] = {'count': 2, 'gap': 0.25}
    for k, v in sections.items():
        p[k] = {**p.get(k, {}), **v}
    return p


META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'year': '2026',
        'front_matter': 'none', 'include_toc': False, 'smartquotes': True,
        'index_statblocks': False, 'index_cr': False}

LOREM = ("The tide comes in over the causeway twice a day and the bell under the "
         "water answers it. Nobody in the village will say who hung it there. ")


def book(figs=()):
    """Three chapters of running text; `figs` are figure blocks, each set
    after the first chapter's second paragraph."""
    md = ['# The Approach', '', LOREM * 6, '', LOREM * 5]
    md += [f for f in figs]
    md += ['', LOREM * 8, '', '# The Keep', '', LOREM * 9, '', LOREM * 7,
           '', '# The Way Out', '', LOREM * 4]
    return '\n'.join(md)


def fig(full, caption='', src=FIG):
    return f'\n~~~ figure src="{src}" full="{full}"\n{caption}\n~~~\n'


def build(md, p, name, press=False, screen=False, **meta):
    out = os.path.join(TMP, name + '.pdf')
    res = engine.build_pdf(manuscript.parse_markdown(md), p, out, dict(META, **meta),
                           press=press, screen=screen)
    return out, res


def pixel(page, x, y, dpi=36):
    """The colour at (x, y) points from the page's top-left."""
    pm = page.get_pixmap(dpi=dpi)
    s = dpi / 72.0
    px = pm.pixel(min(int(x * s), pm.width - 1), min(int(y * s), pm.height - 1))
    return tuple(px[:3])


def near(c, want, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(c, want))


def words_from_trim(page):
    """Each word on the page, placed from its trim's top-left corner."""
    t = page.trimbox
    return [(w[4], round(w[0] - t.x0, 1), round(w[1] - t.y0, 1)) for w in page.get_text('words')]


def plate_pages(pdf):
    """The pages a plate fills (the ones the picture's colour reaches the
    middle of)."""
    with fitz.open(pdf) as d:
        return [i for i, pg in enumerate(d)
                if near(pixel(pg, pg.rect.width / 2, pg.rect.height / 2), FIG_RGB)]


# ---------------------------------------------------------------- 1 and 2
def test_pages():
    print('\nthe page and the trim')
    p = preset()
    plain, r0 = build(book(), p, 'plain')
    bled, r1 = build(book(), p, 'bled', bleed=True)
    tw, th = p['trim']['w'] * 72, p['trim']['h'] * 72
    with fitz.open(plain) as d0, fitz.open(bled) as d1:
        check('off: every page is the trim',
              all(abs(pg.rect.width - tw) < .01 and abs(pg.rect.height - th) < .01 for pg in d0))
        check('off: the result says no bleed', r0['bleed'] is False and r0['bleed_wanted'] == [])
        check('on: the same number of pages', len(d0) == len(d1), (len(d0), len(d1)))
        check('on: every page is trim + bleed on the outer edge, top and bottom',
              all(abs(pg.rect.width - tw - B) < .01 and abs(pg.rect.height - th - 2 * B) < .01
                  for pg in d1), [tuple(pg.rect) for pg in d1][:2])
        check('on: the result says so', r1['bleed'] is True)
        bad = []
        for i, pg in enumerate(d1):
            want_x = 0 if i % 2 == 0 else B          # page 1 (index 0) is a recto
            t = pg.trimbox
            if not (abs(t.x0 - want_x) < .01 and abs(t.y0 - B) < .01
                    and abs(t.width - tw) < .01 and abs(t.height - th) < .01):
                bad.append((i + 1, tuple(t)))
        check('each page declares its trim, in from the outer edge', not bad, bad[:3])
        bad = [i + 1 for i, pg in enumerate(d1) if abs(pg.bleedbox.width - tw - B) > .01]
        check('and its bleed, the whole page', not bad, bad)
        moved = [i + 1 for i in range(len(d0))
                 if words_from_trim(d0[i]) != words_from_trim(d1[i])]
        check('every word stands where it did, measured from the trim', not moved, moved[:5])
        check('the folios are kept', any('2' == w[4] for w in d1[1].get_text('words')))

    pr, r2 = build(book(), p, 'press', press=True, bleed=True)
    rows = {r['label']: r for r in engine.press_check(pr)}
    check('press-ready with bleed: still built press-ready', r2['press'], r2.get('press_error'))
    check('press-ready with bleed: the trim box row passes', rows['Trim box']['ok'], rows['Trim box'])
    with fitz.open(pr) as d:
        check('press-ready with bleed: verso trims in from the left',
              abs(d[1].trimbox.x0 - B) < .01 and abs(d[0].trimbox.x0) < .01,
              (tuple(d[0].trimbox), tuple(d[1].trimbox)))

    sc, r3 = build(book(), p, 'screen', screen=True, bleed=True)
    with fitz.open(sc) as d:
        check('the screen PDF never has bleed',
              abs(d[0].rect.width - tw) < .01 and r3['bleed'] is False)


# ---------------------------------------------------------------- 3
def test_plates():
    print('\nfigures to the edge')
    p = preset()
    md = book([fig('bleed')])
    bled, r = build(md, p, 'plate-bled', bleed=True)
    pages = plate_pages(bled)
    check('a full="bleed" figure fills a page of its own', len(pages) == 1, pages)
    with fitz.open(bled) as d:
        pg = d[pages[0]]
        W, H = pg.rect.width, pg.rect.height
        recto = pages[0] % 2 == 0
        outer_x = W - 2 if recto else 2
        inner_x = 2 if recto else W - 2
        check('it reaches the outer edge of the paper, the top and the bottom',
              all(near(pixel(pg, outer_x, y), FIG_RGB) for y in (2, H / 2, H - 2)))
        check('and the spine edge', near(pixel(pg, inner_x, H / 2), FIG_RGB))
        check('no folio, running head or text on it', not pg.get_text().strip(),
              pg.get_text()[:80])
        before, after = d[pages[0] - 1].get_text(), d[pages[0] + 1].get_text()
        check('the text runs on either side of it', 'causeway' in before and 'causeway' in after)

    # a verso plate bleeds on the left: two plates in a row, one of each
    two, _ = build(book([fig('bleed'), fig('bleed')]), p, 'plate-two', bleed=True)
    pages = plate_pages(two)
    check('two plates in a row take two pages, nothing between',
          len(pages) == 2 and pages[1] == pages[0] + 1, pages)
    with fitz.open(two) as d:
        bad = []
        for i in pages:
            pg = d[i]
            ox = pg.rect.width - 2 if i % 2 == 0 else 2
            if not near(pixel(pg, ox, pg.rect.height / 2), FIG_RGB):
                bad.append(i + 1)
        check('each reaches its own outer edge, recto and verso', not bad, bad)

    capt, _ = build(book([fig('bleed', 'The causeway at low water, Xq1.')]), p, 'plate-cap',
                    bleed=True)
    pages = plate_pages(capt)
    with fitz.open(capt) as d:
        pg = d[pages[0]]
        check('a caption is set on the plate', 'Xq1' in pg.get_text())
        words = [w for w in pg.get_text('words') if 'Xq1' in w[4]]
        t = pg.trimbox
        check('inside the trim, at the foot of the text area',
              words and t.y0 + t.height * 0.75 < words[0][1] < t.y1, words)

    plain, r = build(md, p, 'plate-plain')
    check('without bleed it is reported', r['bleed_wanted'] == [FIG], r['bleed_wanted'])
    with fitz.open(plain) as d:
        hits = [i for i, pg in enumerate(d)
                if near(pixel(pg, pg.rect.width / 2, pg.rect.height / 2), FIG_RGB)]
        pg = d[hits[0]] if hits else None
        check('and set on its own page inside the margins, as full="yes" is',
              pg is not None and not near(pixel(pg, 2, pg.rect.height / 2), FIG_RGB)
              and not near(pixel(pg, pg.rect.width - 2, pg.rect.height / 2), FIG_RGB))

    sc, r = build(md, p, 'plate-screen', screen=True)
    pages = plate_pages(sc)
    with fitz.open(sc) as d:
        pg = d[pages[0]] if pages else None
        check('on the screen PDF it fills the page to its edge',
              pg is not None and near(pixel(pg, 2, 2), FIG_RGB)
              and near(pixel(pg, pg.rect.width - 2, pg.rect.height - 2), FIG_RGB))
    check('and is not reported there', r['bleed_wanted'] == [])

    two_col, _ = build(book([fig('bleed')]), preset(cols=2), 'plate-cols', bleed=True)
    pages = plate_pages(two_col)
    with fitz.open(two_col) as d:
        pg = d[pages[0]] if pages else None
        check('in a two-column book it takes the whole page too',
              pg is not None and near(pixel(pg, 2, 2), FIG_RGB)
              and near(pixel(pg, pg.rect.width - 2, pg.rect.height - 2), FIG_RGB))

    yes, _ = build(book([fig('yes')]), p, 'plate-yes', bleed=True)
    with fitz.open(yes) as d:
        hits = [i for i, pg in enumerate(d)
                if near(pixel(pg, pg.rect.width / 2, pg.rect.height / 2), FIG_RGB)]
        pg = d[hits[0]]
        check('full="yes" stays inside the margins in a book with bleed',
              not near(pixel(pg, 2, pg.rect.height / 2), FIG_RGB)
              and not near(pixel(pg, pg.rect.width - 2, pg.rect.height / 2), FIG_RGB))

    out = os.path.join(TMP, 'plate.epub')
    epub.build_epub(manuscript.parse_markdown(md), p, out, dict(META))
    with zipfile.ZipFile(out) as z:
        body = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xhtml'))
    check('the ebook sets it as a page of its own', 'figure figure-full' in body)


# ---------------------------------------------------------------- 4
def test_background():
    print('\nthe page background in print')
    p = preset(page_background={'image': BG, 'color': '', 'opacity': 1.0})
    plain, _ = build(book(), p, 'bg-plain')
    bled, _ = build(book(), p, 'bg-bled', bleed=True)
    with fitz.open(plain) as d:
        check('a print book without bleed leaves it out',
              not near(pixel(d[1], 2, 2), BG_RGB))
    with fitz.open(bled) as d:
        bad = [i + 1 for i, pg in enumerate(d)
               if not all(near(pixel(pg, x, y), BG_RGB)
                          for x, y in ((2, 2), (pg.rect.width - 2, pg.rect.height - 2)))]
        check('a print book with bleed prints it, to every edge of the paper', not bad, bad[:5])


# ---------------------------------------------------------------- 5
def test_app():
    print('\nthe switch in the app')
    saved = {k: getattr(A, k) for k in ('PROJECT_DIR', 'PROJECT_MS_DIR', 'OUT_DIR')}
    tmp = tempfile.mkdtemp(prefix='ts-bleed-app-')
    try:
        A.PROJECT_DIR = os.path.join(tmp, 'projects')
        A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
        A.OUT_DIR = os.path.join(tmp, 'out')
        for d in (A.PROJECT_MS_DIR, A.OUT_DIR):
            os.makedirs(d)
        with open(os.path.join(A.PROJECT_MS_DIR, 'g.md'), 'w', encoding='utf-8') as f:
            f.write(book([fig('bleed')]))
        proj = {'name': 'G', 'title': 'G', 'preset': 'classic-literary',
                'manuscript_file': 'g.md', 'manuscript_type': 'markdown', 'format': 'pdf'}
        with open(os.path.join(A.PROJECT_DIR, 'g.json'), 'w', encoding='utf-8') as f:
            json.dump(proj, f)

        meta, _ = A._project_meta(A.load_project('g'))
        check('a book that never set it has no bleed', meta.get('bleed') is False)
        res = A._build_project('g', A.load_project('g'))
        check('it builds', not res['error'], res['error'])
        trim = A.load_preset('classic-literary')['trim']
        with fitz.open(os.path.join(A.OUT_DIR, res['out_name'])) as d:
            check('at the trim', abs(d[0].rect.width - trim['w'] * 72) < .01
                  and abs(d[0].rect.height - trim['h'] * 72) < .01)
        with A.app.test_client() as c:
            page = c.post('/project/g/generate').get_data(as_text=True)
        check('the result page says the plate wants bleed', 'paper' in page and FIG in page,
              [l for l in page.splitlines() if 'bleed' in l.lower()][:3])

        # the edit page: the box is there, unticked; saving leaves the book as it was
        with A.app.test_client() as c:
            form_page = c.get('/project/g/edit').get_data(as_text=True)
        check('the book page has the switch, off', 'name="bleed"' in form_page
              and 'id="bleed" name="bleed" checked' not in form_page)

        # saving the book page as it came leaves the book without the key
        with A.app.test_client() as c:
            c.post('/project/g/edit', data=_form_of(form_page), follow_redirects=True)
        check('saving the book page as it is writes no switch into it',
              'bleed' not in A.load_project('g'), A.load_project('g').get('bleed'))
        with A.app.test_client() as c:
            c.post('/project/g/edit', data=dict(_form_of(form_page), bleed='on'),
                   follow_redirects=True)
        check('ticking it saves it', A.load_project('g').get('bleed') is True)

        res = A._build_project('g', A.load_project('g'))
        with fitz.open(os.path.join(A.OUT_DIR, res['out_name'])) as d:
            check('switched on, the book is built with bleed',
                  abs(d[0].rect.height - d[0].trimbox.height - 2 * B) < .01)
        with A.app.test_client() as c:
            page = c.post('/project/g/generate').get_data(as_text=True)
        check('and the result page says so', 'with bleed' in page.lower())
    finally:
        for k, v in saved.items():
            setattr(A, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    Image.new('RGB', (600, 900), FIG_RGB).save(os.path.join(A.FIGURE_DIR, FIG))
    Image.new('RGB', (400, 520), BG_RGB).save(os.path.join(A.FIGURE_DIR, BG))
    try:
        for t in (test_pages, test_plates, test_background, test_app):
            try:
                t()
            except Exception:
                traceback.print_exc()
                results.append((t.__name__, False))
    finally:
        for n in (FIG, BG):
            try:
                os.remove(os.path.join(A.FIGURE_DIR, n))
            except OSError:
                pass
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [l for l, ok in results if not ok]
    print(f'\n{len(results) - len(bad)}/{len(results)} passed')
    sys.exit(1 if bad else 0)
