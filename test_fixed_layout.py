"""Picture books, part 3: the page-by-page ebook (ROADMAP #75c)
(run: python test_fixed_layout.py).

No test framework -- keeps the app dependency-light. Exits non-zero on failure.
Everything runs against throwaway folders, set up here.

Held here:

  1. the pages: designed pages in print's order, a blank where print has one
     (the page plan's own layout agrees), a spread as a left and a right page;
     text between pages, and designs the book doesn't have, left out;
  2. the file: fixed layout declared for EPUB 3 readers and for Kindle, every
     page sized, the pages paired left and right after a lone cover, the fonts
     in the book, and the ebook checks all pass;
  3. the words: live text, in the lines the PDF sets (a justified line word
     by word), and none of it in the art; a spread places its words on both
     pages, so a line across the fold reads across it;
  4. the notes: text left out, a missing design, words a shape is drawn over;
  5. the app: the Ebook layout setting (automatic follows the picture-book
     flag, and is written only once used), a picture book's build and its
     ebook checks, Send to publish naming the ebook fixed layout;
  6. in a browser: a page drawn by headless Chrome lands within a pixel of
     the PDF.
"""
import json, os, re, shutil, subprocess, sys, tempfile, traceback, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A
import engine, epub, fixed_epub as F, manuscript, page_plan as P, wrap_design as W

fails = []


def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


# throwaway folders: the app writes nothing into the real ones
tmp = tempfile.mkdtemp(prefix='ts-fxl-test-')
ROOT = os.path.join(tmp, 'data')
os.makedirs(ROOT)
shutil.copytree(os.path.join(HERE, 'presets'), os.path.join(ROOT, 'presets'))
A.PRESET_DIR = os.path.join(ROOT, 'presets')
A.PROJECT_DIR = os.path.join(ROOT, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(ROOT, 'out')
A.UPLOAD_DIR = os.path.join(ROOT, 'uploads')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.PROJECT_THUMB_DIR = os.path.join(A.OUT_DIR, '_project_thumbs')
for d in (A.PROJECT_MS_DIR, A.HISTORY_DIR, A.UPLOAD_DIR, A.COVER_THUMB_DIR, A.PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)
A.app.config['TESTING'] = True
C = A.app.test_client()

TRIM = {'w': 8.5, 'h': 8.5}
PRESET = {'trim': TRIM}
INK = '#000000'


def words(name, text, bg='#ffffff', **kw):
    """A one-page design: a ground and one text box."""
    el = {'id': 't', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 1.0, 'w': 7.0,
          'text': text, 'font': 'Andika-Regular.ttf', 'size': 22, 'leading': 1.3,
          'color': INK, 'align': 'left', 'tracking': 0}
    el.update(kw)
    return {'name': name, 'saved': '2026-11-13T10:00:00', 'elements': [
        {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': bg}, el]}


def spread(name, text='across the fold we go'):
    return {'name': name, 'spread': True, 'saved': '2026-11-13T10:00:00', 'elements': [
        {'id': 'bg', 'type': 'rect', 'fill': 'sheet', 'color': '#a0c0ff'},
        {'id': 't', 'type': 'text', 'anchor': 'sheet', 'x': 6.0, 'y': 2.0, 'w': 6.0,
         'text': text, 'font': 'Andika-Bold.ttf', 'size': 30, 'color': INK}]}


def fence(src, side='', alt=''):
    return f'~~~ page src="{src}"' + (f' side="{side}"' if side else '') + '\n' \
        + (alt + '\n' if alt else '') + '~~~'


def build(text, designs, path, **meta):
    ms = manuscript.parse_markdown(text)
    m = {'title': 'T', 'author': 'A', 'page_designs': designs, 'ebook_layout': 'fixed', **meta}
    epub.build_epub(ms, PRESET, path, m)
    return ms, m


def spans(xhtml):
    """[(left px of its box, the run)] for every word box on a page."""
    out = []
    for box in re.finditer(r'<div class="t" style="left:([-\d.]+)px[^"]*">(.*?)</div>', xhtml):
        for m in re.finditer(r'<span style="left:([-\d.]+)px;top:([-\d.]+)px">(.*?)</span>',
                             box.group(2)):
            out.append((float(box.group(1)) + float(m.group(1)), float(m.group(2)),
                        m.group(3).replace('&amp;', '&').replace('&lt;', '<')
                        .replace('&gt;', '>')))
    return out


# ---------------------------------------------------------------- 1
def test_pages():
    print('the pages')
    designs = [words('a', 'One'), words('b', 'Two'), spread('sp'), words('c', 'Three')]
    text = '\n\n'.join([fence('a'), fence('sp'), fence('b', 'right'), fence('c')]) + '\n'
    ms = manuscript.parse_markdown(text)
    pages, left_out, missing = F.sequence(ms, designs)
    got = [(p['n'], 'blank' if p.get('blank') else p['name'] + (p['half'] or '')[:1])
           for p in pages]
    check('a | sp left, sp right | blank, b on a right page | c',
          got == [(1, 'a'), (2, 'spl'), (3, 'spr'), (4, 'blank'), (5, 'b'), (6, 'c')], got)
    slots, count = P.layout(P.split(text), designs, W.find_page, W.is_spread)
    plan = sorted([n for s in slots for n in s.get('pages', [])]
                  + [s['blank'] for s in slots if 'blank' in s])
    check('the page plan counts the same pages', count == len(pages)
          and plan == [p['n'] for p in pages], (count, plan))
    check('nothing left out', not left_out and not missing)

    text2 = '\n\n'.join(['# A title', 'Loose words here, typed between pages.', fence('a'),
                         fence('gone'), '~~~ quote\nA quote.\n~~~', fence('sp')]) + '\n'
    pages, left_out, missing = F.sequence(manuscript.parse_markdown(text2), designs)
    check('a heading, prose and a quote are left out', left_out == [
        'A title', 'Loose words here, typed between pages.', 'A quote.'], left_out)
    check('a design the book lacks is named', missing == ['gone'], missing)
    check('a spread after page 1 opens on page 2', [p['n'] for p in pages] == [1, 2, 3])


# ---------------------------------------------------------------- 2
def test_file():
    print('\nthe file')
    designs = [words('a', 'One'), spread('sp'), words('b', 'Two', font='EBGaramond-Italic.ttf')]
    cover = os.path.join(tmp, 'cover.jpg')
    from PIL import Image
    Image.new('RGB', (1600, 1600), '#336699').save(cover)
    path = os.path.join(tmp, 'file.epub')
    build('\n\n'.join([fence('a', alt='A fox on a hill'), fence('sp'), fence('b')]) + '\n',
          designs, path, cover_image=cover)
    z = zipfile.ZipFile(path)
    opf = z.read('OEBPS/content.opf').decode()
    check('EPUB 3 readers: pre-paginated, paired in landscape',
          'rendition:layout">pre-paginated' in opf and 'rendition:spread">landscape' in opf)
    check('Kindle: fixed-layout, its resolution, a children\'s book',
          'name="fixed-layout" content="true"' in opf
          and 'name="original-resolution" content="1275x1275"' in opf
          and 'name="book-type" content="children"' in opf)
    refs = re.findall(r'<itemref idref="([^"]+)" properties="([^"]+)"/>', opf)
    check('a lone cover, then pages right, left, right, left',
          [p for _, p in refs] == ['rendition:page-spread-center', 'page-spread-right',
                                   'page-spread-left', 'page-spread-right', 'page-spread-left'],
          refs)
    names = z.namelist()
    check('the two fonts are in the book', 'OEBPS/fonts/Andika-Regular.ttf' in names
          and 'OEBPS/fonts/Andika-Bold.ttf' in names
          and 'OEBPS/fonts/EBGaramond-Italic.ttf' in names, names)
    css = z.read('OEBPS/fxl.css').decode()
    check('each face pins its baseline', css.count('ascent-override') == 3
          and 'line-gap-override:0%' in css and 'font-kerning:none' in css)
    p1 = z.read('OEBPS/page001.xhtml').decode()
    check('the fence\'s words are the art\'s alt text', 'alt="A fox on a hill"' in p1)
    p3 = z.read('OEBPS/page003.xhtml').decode()
    check('art without alt words is marked as such', 'role="presentation"' in p3)
    rows = epub.check(path)
    bad = [r for r in rows if not r['ok']]
    check('every ebook check passes', not bad, bad)
    labels = [r['label'] for r in rows]
    check('with the fixed-layout rows', all(l in labels for l in ('Fixed layout', 'Page size',
                                                                   'Fonts')), labels)
    # an ordinary book is untouched by any of it
    plain = os.path.join(tmp, 'plain.epub')
    epub.build_epub(manuscript.parse_markdown('# One\n\nWords.\n'), PRESET, plain,
                    {'title': 'T', 'author': 'A'})
    check('a flowing book: no fixed-layout rows, reflowable',
          'Fixed layout' not in [r['label'] for r in epub.check(plain)]
          and b'pre-paginated' not in zipfile.ZipFile(plain).read('OEBPS/content.opf'))
    # a page with no viewport is caught
    broken = os.path.join(tmp, 'broken.epub')
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(broken, 'w') as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == 'OEBPS/page002.xhtml':
                data = re.sub(rb'<meta name="viewport"[^>]*/>', b'', data)
            if info.filename == 'OEBPS/content.opf':
                data = data.replace(b'<meta name="fixed-layout" content="true"/>', b'')
            dst.writestr(info, data)
    rows = {r['label']: r for r in epub.check(broken)}
    check('a page with no size is named', not rows['Page size']['ok']
          and 'page002.xhtml' in rows['Page size']['detail'], rows['Page size'])
    check('no Kindle declaration is caught', not rows['Fixed layout']['ok'])


# ---------------------------------------------------------------- 3
def test_words():
    print('\nthe words')
    text = ('Every night the little fox climbed the hill behind the farm and counted the '
            'stars, one by one, until her eyes grew heavy.\n\nShe never got past a hundred & '
            'one <stars>.')
    d = words('j', text, align='justify', tracking=0.4, font='EBGaramond-Regular.ttf', size=16)
    path = os.path.join(tmp, 'words.epub')
    build(fence('j') + '\n', [d], path)
    z = zipfile.ZipFile(path)
    got = spans(z.read('OEBPS/page001.xhtml').decode())
    el = d['elements'][1]
    layout = W.text_layout(el)
    lines = W.build_page_pdf(d, TRIM['w'], TRIM['h'], os.path.join(tmp, 'j.pdf'))['t']
    want = [run for line, _, _, wds in layout for run, _ in (wds or [(line, 0)]) if run]
    check('every run of the PDF, as live text', [g[2] for g in got] == want,
          ([g[2] for g in got][:5], want[:5]))
    check('in the lines the PDF set', [ln for ln, _, _, _ in layout] == lines)
    justified = [wds for _, _, _, wds in layout if wds]
    check('a justified line is set word by word', justified
          and len(got) > len(lines), len(got))
    k = F.PX / 72.0
    x0 = (0.75) * F.PX
    first = justified[0]
    xs = [round(x0 + x * k, 2) for _, x in first]
    check('at the PDF\'s word positions', [round(g[0], 2) for g in got[:len(xs)]] == xs,
          ([g[0] for g in got[:len(xs)]], xs))
    css_box = re.search(r'letter-spacing:([\d.]+)px', z.read('OEBPS/page001.xhtml').decode())
    check('the tracking carried over', css_box and abs(float(css_box.group(1)) - 0.4 * k) < 0.01)
    # the art has no words in it: white page, black words -> white art
    from PIL import Image
    art = next(n for n in z.namelist() if n.startswith('OEBPS/images/art'))
    with Image.open(z.open(art)) as im:
        lo = im.convert('L').getextrema()[0]
    check('the art is drawn without its words', lo > 240, lo)
    with Image.open(z.open(art)) as im:
        check('the art at its resolution', im.size == (round(8.5 * F.art_dpi(8.5, 8.5)),) * 2
              and im.size[0] * im.size[1] <= F.ART_PIXELS, im.size)

    # a spread: both pages place the words, the right one shifted a page over
    path = os.path.join(tmp, 'spread.epub')
    build(fence('a') + '\n\n' + fence('sp') + '\n', [words('a', 'One'), spread('sp')], path)
    z = zipfile.ZipFile(path)
    left = spans(z.read('OEBPS/page002.xhtml').decode())
    right = spans(z.read('OEBPS/page003.xhtml').decode())
    check('the spread\'s words are on both its pages', left and [s[2] for s in left]
          == [s[2] for s in right])
    check('a page apart', all(abs((l[0] - r[0]) - 8.5 * F.PX) < 0.02
                              for l, r in zip(left, right)), (left, right))
    check('the line runs across the fold', left[0][0] < 1275 < left[0][0] + 400, left)
    arts = sorted(n for n in z.namelist() if '-l.jpg' in n or '-r.jpg' in n)
    check('its art cut at the fold, one half each', len(arts) == 2, arts)
    # a rotated box turns about its corner, as the PDF does
    d = words('r', 'SIDEWAYS', rotate=90, w=0)
    path = os.path.join(tmp, 'rot.epub')
    build(fence('r') + '\n', [d], path)
    check('a rotated box is turned', 'transform:rotate(90deg);transform-origin:0 0'
          in zipfile.ZipFile(path).read('OEBPS/page001.xhtml').decode())


# ---------------------------------------------------------------- 4
def test_notes():
    print('\nthe notes')
    cover = words('cv', 'Covered words')
    cover['elements'].append({'id': 'box', 'type': 'rect', 'anchor': 'front', 'x': 1, 'y': 1,
                              'w': 1, 'h': 0.5, 'color': '#ff0000'})
    under = words('un', 'Words on top')
    under['elements'].insert(1, {'id': 'box', 'type': 'rect', 'anchor': 'front', 'x': 1,
                                 'y': 1, 'w': 1, 'h': 0.5, 'color': '#ff0000'})
    far = words('far', 'Words here')
    far['elements'].append({'id': 'box', 'type': 'rect', 'anchor': 'front', 'x': 6, 'y': 6,
                            'w': 1, 'h': 1, 'color': '#ff0000'})
    designs = [cover, under, far]
    text = '\n\n'.join([fence('cv'), 'Loose prose.', fence('un'), fence('far'),
                        fence('nope')]) + '\n'
    rows = {r['label']: r for r in F.notes(manuscript.parse_markdown(text),
                                           {'page_designs': designs}, PRESET)}
    check('text between pages, quoted', 'Text between pages' in rows
          and '“Loose prose.”' in rows['Text between pages']['detail'], rows)
    check('a missing design', 'nope' in rows.get('Missing page designs', {}).get('detail', ''))
    wa = rows.get('Words under art', {}).get('detail', '')
    check('words a shape is drawn over: that page only', 'cv' in wa and ' un' not in wa
          and 'far' not in wa, wa)
    check('none of them passes', all(not r['ok'] for r in rows.values()))
    clean = F.notes(manuscript.parse_markdown(fence('un') + '\n'), {'page_designs': designs},
                    PRESET)
    check('a clean book has no notes', clean == [], clean)
    empty = F.notes(manuscript.parse_markdown('Just prose.\n'), {'page_designs': []}, PRESET)
    check('no pages at all is said', any(r['label'] == 'Designed pages' for r in empty), empty)


# ---------------------------------------------------------------- 5
def project(pid, md, designs, **kw):
    with open(os.path.join(A.PROJECT_MS_DIR, pid + '.md'), 'w', encoding='utf-8', newline='') as f:
        f.write(md)
    A.save_project_file(pid, {'name': pid, 'title': pid, 'preset': 'picture-book',
                              'manuscript_file': pid + '.md', 'manuscript_type': 'markdown',
                              'format': 'both', 'front_matter': 'none', 'include_toc': False,
                              'right_hand_starts': False, 'bleed': True,
                              'page_designs': designs, **kw})


def test_app():
    print('\nin the app')
    check('automatic: a picture book is page by page',
          A.ebook_layout({'picture_book': True}) == 'fixed')
    check('automatic: any other book flows', A.ebook_layout({}) == 'flow')
    check('chosen: either way round', A.ebook_layout({'picture_book': True,
                                                      'ebook_layout': 'flow'}) == 'flow'
          and A.ebook_layout({'ebook_layout': 'fixed'}) == 'fixed')
    check('an unknown choice follows the flag', A.ebook_layout({'ebook_layout': 'odd'}) == 'flow')

    project('pb', '\n\n'.join([fence('a'), 'Loose prose.', fence('b')]) + '\n',
            [words('a', 'Hello'), words('b', 'World')], picture_book=True)
    form = {'name': 'pb', 'preset': 'picture-book', 'title': 'pb', 'picture_book': 'on',
            'format': 'both'}
    C.post('/project/pb/edit', data=form)
    check('a save that leaves it automatic writes nothing', 'ebook_layout'
          not in A.load_project('pb'))
    html = C.get('/project/pb/edit').get_data(as_text=True)
    check('the Edit page offers the choice', 'name="ebook_layout"' in html
          and 'Page by page (fixed layout)' in html)
    page = C.post('/project/pb/generate').get_data(as_text=True)
    proj = A.load_project('pb')
    z = zipfile.ZipFile(os.path.join(A.OUT_DIR, proj['last_epub']))
    check('a picture book builds page by page', b'pre-paginated' in z.read('OEBPS/content.opf'))
    check('its checks pass as fixed layout', 'Fixed layout' in page and 'Page size' in page)
    check('and name the text left out', 'Text between pages' in page and 'Loose prose.' in page)

    C.post('/project/pb/edit', data=dict(form, ebook_layout='flow'))
    check('chosen: written', A.load_project('pb').get('ebook_layout') == 'flow')
    C.post('/project/pb/generate')
    z = zipfile.ZipFile(os.path.join(A.OUT_DIR, A.load_project('pb')['last_epub']))
    check('flowing text when chosen', b'pre-paginated' not in z.read('OEBPS/content.opf'))
    C.post('/project/pb/edit', data=dict(form, ebook_layout=''))
    check('back to automatic: kept as automatic', A.load_project('pb').get('ebook_layout') == '')

    # Send to publish: the ebook in the package is the page-by-page one
    project('pub', '\n\n'.join([fence('a'), fence('b')]) + '\n',
            [words('a', 'Hello'), words('b', 'World')], picture_book=True,
            author='A', cover_mode='designed', cover_template='fantasy-emerald',
            print_retailer='kdp', print_binding='paperback', print_paper='color')
    C.post('/project/pub/generate')
    r = C.post('/project/pub/print-package', data={'scope': 'publish'})
    html = r.get_data(as_text=True)
    zip_name = A.load_project('pub').get('last_print_package', '')
    check('Send to publish packs it', r.status_code == 200 and zip_name, r.status_code)
    if zip_name:
        pz = zipfile.ZipFile(os.path.join(A.OUT_DIR, zip_name))
        spec = next(n for n in pz.namelist() if n.endswith('SPEC.txt'))
        check('its sheet says fixed layout', 'fixed layout' in pz.read(spec).decode('utf-8'))
        check('so does the page', 'fixed layout (page by page)' in html)
        ebook = next(n for n in pz.namelist() if n.endswith('.epub'))
        inner = zipfile.ZipFile(pz.open(ebook))
        opf = inner.read('OEBPS/content.opf').decode()
        check('the ebook in it is page by page, with its cover',
              'pre-paginated' in opf and 'cover-image' in opf)


# ---------------------------------------------------------------- 6
def test_browser():
    print('\nin a browser')
    from test_rich_editor import find_browser
    browser = find_browser()
    if not browser:
        print('  SKIP no Chrome/Edge found (set TS_BROWSER)')
        return
    from PIL import Image, ImageChops
    d = words('pg', 'The fox who counted the stars, one by one, until the owls began '
                    'to sing.', bg='#f4ecd8', align='justify', size=26, tracking=0.5,
              color='#1b2a4a')
    d['elements'].append({'id': 'side', 'type': 'text', 'anchor': 'front', 'x': 7.8, 'y': 3.0,
                          'text': 'SIDEWAYS', 'font': 'Andika-Bold.ttf', 'size': 18,
                          'rotate': 90, 'color': '#7a3020', 'tracking': 2})
    path = os.path.join(tmp, 'browser.epub')
    build(fence('pg') + '\n', [d], path)
    out = os.path.join(tmp, 'browser')
    zipfile.ZipFile(path).extractall(out)
    shot = os.path.join(tmp, 'shot.png')
    subprocess.run([browser, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--force-device-scale-factor=1', '--window-size=1275,1275',
                    '--allow-file-access-from-files', '--virtual-time-budget=5000',
                    '--user-data-dir=' + os.path.join(tmp, 'profile'), f'--screenshot={shot}',
                    'file:///' + os.path.join(out, 'OEBPS', 'page001.xhtml').replace('\\', '/')],
                   capture_output=True, timeout=180)
    check('Chrome drew the page', os.path.exists(shot))
    if not os.path.exists(shot):
        return
    ref_path = os.path.join(tmp, 'ref.jpg')
    W.render_page(d, TRIM['w'], TRIM['h'], ref_path, dpi=F.PX)
    ref = Image.open(ref_path).convert('L')
    got = Image.open(shot).convert('L').crop((0, 0, ref.width, ref.height))

    def err(dx, dy):
        box = (8, 8, ref.width - 8, ref.height - 8)
        s = got.crop((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
        return sum(i * v for i, v in enumerate(ImageChops.difference(ref.crop(box), s)
                                               .histogram()))
    best = min((err(dx, dy), dx, dy) for dx in range(-3, 4) for dy in range(-3, 4))
    check('the words land within a pixel of the PDF', abs(best[1]) <= 1 and abs(best[2]) <= 1,
          best)
    hist = ImageChops.difference(ref, got).histogram()
    off = sum(hist[61:]) / float(ref.width * ref.height)
    check('and the page matches it (only glyph edges differ)', off < 0.02, off)


def main():
    for t in (test_pages, test_file, test_words, test_notes, test_app, test_browser):
        try:
            t()
        except Exception:
            traceback.print_exc()
            fails.append(t.__name__ + ' crashed')
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print(f'{len(fails)} FAILED:')
        for f in fails:
            print('  -', f)
        sys.exit(1)
    print('all page-by-page ebook checks passed')


if __name__ == '__main__':
    main()
