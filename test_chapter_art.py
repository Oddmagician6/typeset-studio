"""Chapter-opening art tests  (run: python test_chapter_art.py).

The art is one image printed at the top of every chapter, chosen by the style.
What can go wrong is therefore geometry (a picture that shoves the chapter
title off its own page), packaging (the ebook referencing a file it never
stored), and regression (a style written before the feature opening any
differently than it used to) — so those are what this file checks, on real
PDFs and a real EPUB.
"""

import sys, os, io, json, re, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import engine, epub, manuscript, matter
import app as A
from reportlab.lib.units import inch

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


MS = """\
# The Salt Road

The opening paragraph of the first chapter, long enough to fill more than one
line of body text under whatever ornament the style prints above it.

# The Long Water

A second chapter, so the art has to be placed more than once in a single build.
"""

META = {'title': 'T', 'subtitle': '', 'author': 'E', 'year': '2026', 'publisher': '',
        'front_matter': 'none', 'right_hand_starts': False, 'include_toc': False,
        'smartquotes': True, 'cover_mode': 'none', 'cover_image': '',
        'cover_overlay': False, 'cover_color': 'light', **{k: '' for k in matter.KEYS}}

ART = 'test-chapter-art.png'
ART_PATH = os.path.join(A.FIGURE_DIR, ART)


def styled(**art):
    p = json.loads(json.dumps(A.DEFAULTS))
    p['chapter_art'].update(art)
    return p


def make_art():
    """A wide, short PNG — the shape a chapter ornament actually is."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (600, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line((10, 60, 590, 60), fill=(30, 30, 30, 255), width=6)
    d.ellipse((280, 30, 320, 90), fill=(30, 30, 30, 255))
    img.save(ART_PATH)


make_art()
ms = manuscript.parse_markdown(MS, smartquotes=True)
COL = (6.0 - 0.85 - 0.6) * inch          # the text column of the default 6x9
TEXT_H = (9.0 - 0.75 - 0.8) * inch

try:
    # ------------------------------------------------------------ the style
    print('the style')
    check('the default style prints no art', A.DEFAULTS['chapter_art']['image'] == '')
    check('a style written before the feature reads as no art',
          engine.chapter_art_src({}) == '' and epub.chapter_art_src({}) == '')
    check('the two readers agree on the image',
          engine.chapter_art_src(styled(image=ART))
          == epub.chapter_art_src(styled(image=ART)) == ART)
    check('the two readers agree on the position',
          all(engine.chapter_art_position(p) == epub.chapter_art_position(p) == e
              for p, e in ((styled(position='below'), 'below'),
                           (styled(position='above'), 'above'),
                           (styled(position='nonsense'), 'above'),
                           ({}, 'above'))))

    parsed = A.parse_preset_form({'ca_image': ' ' + ART + ' ', 'ca_position': 'below',
                                  'ca_width': '0.5', 'ca_align': 'left',
                                  'ca_gap': '0.3', 'ca_max_height': '2'})['chapter_art']
    check('the style editor reads the picker',
          parsed == {'image': ART, 'position': 'below', 'width': 0.5,
                     'align': 'left', 'gap': 0.3, 'max_height': 2.0}, parsed)
    check('a form with no art fields still parses',
          A.parse_preset_form({})['chapter_art']['image'] == '')

    # ------------------------------------------------------------ geometry
    print('the geometry')
    check('no image means no flowables', engine._chapter_art(styled(), COL, TEXT_H) == [])
    check('a style without the section means no flowables',
          engine._chapter_art({}, COL, TEXT_H) == [])

    flow = engine._chapter_art(styled(image=ART, width=0.5, gap=0.2), COL, TEXT_H)
    art = flow[0]
    check('the art is the width the style asked for',
          abs(art._w - COL * 0.5) < 0.01, (art._w, COL * 0.5))
    check('the height follows the image aspect',
          abs(art._h - COL * 0.5 * (120 / 600.0)) < 0.01, art._h)
    check('the gap follows the art when it sits above',
          len(flow) == 2 and abs(flow[1].height - 0.2 * inch) < 0.01)
    below = engine._chapter_art(styled(image=ART, position='below', gap=0.2), COL, TEXT_H)
    check('the gap leads when the art sits below',
          len(below) == 2 and below[0].__class__.__name__ == 'Spacer'
          and below[1].__class__.__name__ == 'FigureImage',
          [f.__class__.__name__ for f in below])
    check('a zero gap adds no spacer',
          len(engine._chapter_art(styled(image=ART, gap=0), COL, TEXT_H)) == 1)

    tall = engine._chapter_art(styled(image=ART, width=1.0, max_height=0.4), COL, TEXT_H)[0]
    check('a tall image is capped by the style maximum',
          abs(tall._h - 0.4 * inch) < 0.01, tall._h)
    huge = engine._chapter_art(styled(image=ART, width=1.0, max_height=99), COL, TEXT_H)[0]
    check('and can never take more than half the page',
          huge._h <= TEXT_H * 0.5 + 0.01, (huge._h, TEXT_H * 0.5))
    missing = engine._chapter_art(styled(image='not-here.png'), COL, TEXT_H)[0]
    check('a missing file still reserves a box, to draw the placeholder in',
          missing.path is None and missing._h > 0 and missing.label == 'not-here.png')

    # ------------------------------------------------------------ the PDF
    print('the built book')
    import fitz
    fd, pdf_path = tempfile.mkstemp(suffix='.pdf'); os.close(fd)

    plain = engine.build_pdf(ms, styled(), pdf_path, dict(META))
    with fitz.open(pdf_path) as doc:
        plain_imgs = sum(len(p.get_images()) for p in doc)
        plain_text = doc[0].get_text()
    check('a style with no art ships no images at all', plain_imgs == 0, plain_imgs)

    engine.build_pdf(ms, styled(image=ART), pdf_path, dict(META))
    with fitz.open(pdf_path) as doc:
        opener_pages = [i for i, p in enumerate(doc) if p.get_images()]
        first = doc[0]
        art_rects = first.get_image_rects(first.get_images()[0][0]) if first.get_images() else []
        title_rect = first.search_for('The Salt Road')
        first_text = first.get_text()
    check('the art lands on each of the two chapter openers',
          len(opener_pages) == 2 and opener_pages[0] == 0, opener_pages)
    check('above the chapter heading', art_rects and title_rect
          and art_rects[0].y1 <= title_rect[0].y0 + 1,
          (art_rects, title_rect))
    check('the chapter still opens with its own text',
          'The Salt Road' in first_text and 'line of body text' in first_text,
          first_text[:120])

    engine.build_pdf(ms, styled(image=ART, position='below'), pdf_path, dict(META))
    with fitz.open(pdf_path) as doc:
        first = doc[0]
        art_rects = first.get_image_rects(first.get_images()[0][0])
        title_rect = first.search_for('The Salt Road')
    check('the below position sets the art under the title',
          art_rects[0].y0 >= title_rect[0].y1 - 1, (art_rects, title_rect))

    # a style that names a file that has gone missing must still build
    gone = engine.build_pdf(ms, styled(image='not-here.png'), pdf_path, dict(META))
    check('a missing image builds the book anyway', gone['page_count'] >= 2)

    # the regression that matters: a style with no art opens as it always did
    engine.build_pdf(ms, styled(), pdf_path, dict(META))
    with fitz.open(pdf_path) as doc:
        check('an art-free build is unchanged', doc[0].get_text() == plain_text)
    check('the page count is unchanged by an art-free style',
          plain['page_count'] == 2, plain['page_count'])
    os.remove(pdf_path)

    # ------------------------------------------------------------ the EPUB
    print('the built ebook')
    fd, epub_path = tempfile.mkstemp(suffix='.epub'); os.close(fd)

    epub.build_epub(ms, styled(image=ART), epub_path, dict(META))
    with zipfile.ZipFile(epub_path) as zf:
        names = zf.namelist()
        opf = zf.read('OEBPS/content.opf').decode()
        ch1 = zf.read('OEBPS/chapter001.xhtml').decode()
        ch2 = zf.read('OEBPS/chapter002.xhtml').decode()
        css = zf.read('OEBPS/style.css').decode()
    href = re.search(r'src="(images/[^"]+)"', ch1)
    check('the art file is in the zip', href and f'OEBPS/{href.group(1)}' in names, names)
    check('and is manifested as an image',
          href and href.group(1) in opf and 'image/png' in opf)
    check('one file serves every chapter',
          href and href.group(1) in ch2
          and len([n for n in names if n.startswith('OEBPS/images/')]) == 1)
    check('it is marked decorative, not given a name to read out',
          'alt=""' in ch1 and 'role="presentation"' in ch1)
    check('the width is a percentage, so it reflows',
          re.search(r'class="chapter-art"><img[^>]*style="width:(\d+(?:\.\d+)?)%"', ch1),
          re.search(r'<p class="chapter-art[^>]*>[^<]*<img[^>]*>', ch1))
    check('the art precedes the heading', ch1.index('chapter-art') < ch1.index('chapter-num'))
    check('the stylesheet styles it', 'p.chapter-art' in css)
    report = epub.check(epub_path)
    check('the EPUB preflight is all clear', all(c['ok'] for c in report),
          [c for c in report if not c['ok']])
    check('the alt-text check still ran', any(c['label'] == 'Image alt text' for c in report),
          [c['label'] for c in report])

    epub.build_epub(ms, styled(image=ART, position='below'), epub_path, dict(META))
    with zipfile.ZipFile(epub_path) as zf:
        ch1 = zf.read('OEBPS/chapter001.xhtml').decode()
    check('the below position follows the title in the ebook too',
          'chapter-art-below' in ch1
          and ch1.index('chapter-title') < ch1.index('chapter-art'))

    epub.build_epub(ms, styled(), epub_path, dict(META))
    with zipfile.ZipFile(epub_path) as zf:
        check('an art-free style ships no images',
              not any(n.startswith('OEBPS/images/') for n in zf.namelist()))
        check('and references none',
              'chapter-art' not in zf.read('OEBPS/chapter001.xhtml').decode())

    epub.build_epub(ms, styled(image='not-here.png'), epub_path, dict(META))
    with zipfile.ZipFile(epub_path) as zf:
        check('a missing image leaves the ebook whole, not broken',
              '<img' not in zf.read('OEBPS/chapter001.xhtml').decode())
    check('and still passes preflight', all(c['ok'] for c in epub.check(epub_path)),
          [c for c in epub.check(epub_path) if not c['ok']])
    os.remove(epub_path)

    # ------------------------------------------------------------ the app
    print('the style editor')
    A.app.config['TESTING'] = True
    client = A.app.test_client()

    page = client.get('/editor/new').get_data(as_text=True)
    check('the library appears in the picker', f'<option value="{ART}"' in page)
    check('the picker offers no art as the default',
          'None — plain chapter openings' in page)
    check('every art field renders',
          all(f'name="ca_{f}"' in page
              for f in ('image', 'position', 'width', 'align', 'gap', 'max_height')))

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

        form['ca_image'] = ART
        form['ca_position'] = 'below'
        client.post('/save/classic-literary', data=form, follow_redirects=True)
        after = A.load_preset('classic-literary')
        check('the choice survives a real editor save',
              after['chapter_art']['image'] == ART
              and after['chapter_art']['position'] == 'below', after.get('chapter_art'))
        changed = {k: (before[k], after.get(k)) for k in before
                   if k != 'chapter_art' and before[k] != after.get(k)}
        check('nothing else in the style changed', not changed, changed)

        r = client.post('/preview', data=form)
        check('the live style preview builds with the art',
              r.get_json().get('ok'), r.get_json())
    finally:
        open(PRESET, 'wb').write(snapshot)
finally:
    if os.path.exists(ART_PATH):
        os.remove(ART_PATH)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
