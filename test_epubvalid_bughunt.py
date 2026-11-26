"""EPUB validity and accessibility  (run: python test_epubvalid_bughunt.py).

Joint bug hunt, round 5, section 23:

    23.1  a control character in the book settings doesn't break the EPUB
    23.2  overlapping bold and bold-italic stay well-formed (PDF too)
    23.3  a page whose art can't be drawn stops the export, naming the page
    23.4  a blank title or author makes no empty metadata
    23.6  a picture-only page with no description is named by the check
    23.7  a figure's alt is its own or its caption, never the file name, and
          the OPF only claims text alternatives the book has
    23.8  a fixed-layout page reads top to bottom, whatever the layer order
    23.9  a WebP figure goes in as a PNG, labelled as one
    23.10 a chapter's first heading is never more than one level below h1
    23.14 an unused scene-break picture is left out
    (21.8 a zero-width right-aligned line crossing the fold keeps its left half)
"""

import copy, io, os, re, sys, shutil, tempfile, zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.WARNING)

import app as A
import engine
import epub
import fixed_epub as F
import manuscript

fails = []
TMP = tempfile.mkdtemp(prefix='epubvalid_bughunt_')
META = {'title': 'The Drowned Bell', 'author': 'Test Fixture', 'front_matter': 'none',
        'include_toc': False, 'index_statblocks': False, 'index_cr': False}
L = 'The tide comes in over the causeway twice a day and the bell answers it.'


def check(label, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f'         {detail}')
        fails.append(label)


def preset(**kw):
    p = copy.deepcopy(A.DEFAULTS)
    for k, v in kw.items():
        p[k] = dict(p.get(k) or {}, **v) if isinstance(v, dict) else v
    return p


def read(out):
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode('utf-8') for n in z.namelist()
                if n.endswith(('.xhtml', '.opf', '.xml'))}, z.namelist()


def build(md, name, p=None, **meta):
    out = os.path.join(TMP, name + '.epub')
    epub.build_epub(manuscript.parse_markdown(md), p or preset(), out, dict(META, **meta))
    docs, names = read(out)
    return out, docs, names


def bad_xml(docs):
    bad = []
    for n, s in docs.items():
        try:
            minidom.parseString(s.encode('utf-8'))
        except Exception as e:
            bad.append(f'{n}: {e}')
    return bad


def row(out, label):
    return next((r for r in epub.check(out) if r['label'] == label), None)


# ---- 23.1 -------------------------------------------------------------------
print('23.1 control characters')
out, docs, _ = build(f'# One\n\n{L}\n', 'ctl', title='Salt\x01Road',
                     about_author='She writes\x0b by the sea.')
check('every document parses', not bad_xml(docs), bad_xml(docs))
check('the title keeps its words', '<dc:title>SaltRoad</dc:title>' in docs['OEBPS/content.opf'])

# ---- 23.2 -------------------------------------------------------------------
print('23.2 overlapping emphasis')
out, docs, _ = build(f'# One\n\n***bold **a*** b** and {L}\n', 'emph')
check('the chapter is well-formed', not bad_xml(docs), bad_xml(docs))
check('the inline markup nests', manuscript._inline('***bold **a*** b**')
      == '<b><i>bold **a</i></b> b**', manuscript._inline('***bold **a*** b**'))
pdf = os.path.join(TMP, 'emph.pdf')
try:
    engine.build_pdf(manuscript.parse_markdown(f'# One\n\n***bold **a*** b** {L}\n'),
                     preset(), pdf, dict(META))
    check('the PDF builds too', os.path.exists(pdf))
except Exception as e:
    check('the PDF builds too', False, e)

# ---- 23.4 -------------------------------------------------------------------
print('23.4 blank title and author')
out, docs, _ = build(f'# One\n\n{L}\n', 'blank', title='', author='  ', year='')
opf = docs['OEBPS/content.opf']
check('an empty title is "Untitled"', '<dc:title>Untitled</dc:title>' in opf)
check('no empty creator', '<dc:creator' not in opf, opf[:600])
check('no empty date', '<dc:date' not in opf)
out, docs, _ = build(f'# One\n\n{L}\n', 'named', year='2026')
check('a given author and year stay', '<dc:creator>Test Fixture</dc:creator>' in docs['OEBPS/content.opf']
      and '<dc:date>2026</dc:date>' in docs['OEBPS/content.opf'])

# ---- 23.7 / 23.9 / 23.14 ----------------------------------------------------
print('23.7 / 23.9 / 23.14 figures')
from PIL import Image
pic = os.path.join(TMP, 'map.png')
Image.new('RGB', (40, 30), '#336699').save(pic)
webp = os.path.join(TMP, 'harbor.webp')
Image.new('RGB', (40, 30), '#993333').save(webp, 'WEBP')

out, docs, names = build(f'# One\n\n{L}\n\n~~~ figure src="{pic}"\n~~~\n', 'noalt')
ch = docs['OEBPS/chapter001.xhtml']
alts = re.findall(r'<img[^>]*\balt="([^"]*)"', ch)
check('a figure without alt or caption is not named by its file', alts == [''], alts)
r = row(out, 'Image alt text')
check('the check names it', r is not None and not r['ok'], r)
opf = docs['OEBPS/content.opf']
check('the OPF claims no text alternative it lacks',
      'alternativeText' not in opf and 'textual,visual</meta>' in opf
      and 'Some illustrations have no text alternative' in opf, opf)

out, docs, _ = build(f'# One\n\n{L}\n\n~~~ figure src="{pic}"\nThe harbour & the bell.\n~~~\n', 'caption')
ch = docs['OEBPS/chapter001.xhtml']
check('a captioned figure takes its caption as alt', 'alt="The harbour &amp; the bell."' in ch,
      re.findall(r'<img[^>]*>', ch))
opf = docs['OEBPS/content.opf']
check('and then the OPF may claim it', 'alternativeText' in opf
      and 'accessModeSufficient">textual</meta>' in opf)

out, docs, names = build(f'# One\n\n{L}\n\n~~~ figure src="{webp}" alt="The harbour"\n~~~\n', 'webp')
opf = docs['OEBPS/content.opf']
check('a WebP goes in as a PNG', 'images/fig001.png' in opf and 'media-type="image/png"' in opf,
      re.findall(r'<item [^>]*fig[^>]*>', opf))
with zipfile.ZipFile(out) as z:
    head = z.read('OEBPS/images/fig001.png')[:8]
check('its bytes are a PNG', head == b'\x89PNG\r\n\x1a\n', head)
r = row(out, 'Media types') or {'ok': True}
check('and the check agrees', all(x['ok'] for x in epub.check(out)
                                  if 'ype' in x['label'] or 'edia' in x['label']),
      [x for x in epub.check(out) if not x['ok']])

orn = os.path.join(TMP, 'fleuron.png')
Image.new('RGB', (30, 10), '#000000').save(orn)
p = preset(scene_break={'type': 'image', 'image': orn})
out, docs, names = build(f'# One\n\n{L}\n', 'noscene', p=p)
check('an unused scene-break picture is not packaged',
      not [n for n in names if n.startswith('OEBPS/images/')], names)
check('and the book stays textual', 'accessMode">visual' not in docs['OEBPS/content.opf'])
out, docs, names = build(f'# One\n\n{L}\n\n* * *\n\n{L}\n', 'scene', p=p)
check('a used one is', [n for n in names if n.startswith('OEBPS/images/')], names)

# the cover is named by the book
cover = os.path.join(TMP, 'cover.jpg')
Image.new('RGB', (60, 90), '#224466').save(cover)
out, docs, _ = build(f'# One\n\n{L}\n', 'cover', cover_image=cover)
check('the cover\'s alt names the book', 'alt="Cover: The Drowned Bell"' in docs['OEBPS/cover.xhtml'])

# ---- 23.10 ------------------------------------------------------------------
print('23.10 heading levels')
out, docs, _ = build(f'# Harbor\n\n### Arrival\n\n{L}\n\n#### Docks\n\n{L}\n\n## Later\n\n{L}\n',
                     'heads')
ch = docs['OEBPS/chapter001.xhtml']
tags = re.findall(r'<(h\d) id="h\d+" class="hd-(\w+)"', ch)
check('no level is skipped', tags == [('h2', 'section'), ('h3', 'subsection'), ('h2', 'subhead')],
      tags)
css = epub._style_css(preset())
check('the section style follows the class', '.hd-section' in css and '.hd-subsection' in css)

# ---- fixed layout: 23.3 / 23.6 / 23.8 / 21.8 --------------------------------
print('23.3 / 23.6 / 23.8 / 21.8 fixed layout')
TRIM = {'trim': {'w': 8.5, 'h': 8.5}}


def text(id_, y, words, x=0.75, w=7.0, **kw):
    el = {'id': id_, 'type': 'text', 'anchor': 'front', 'x': x, 'y': y, 'w': w,
          'text': words, 'font': 'Andika-Regular.ttf', 'size': 22, 'leading': 1.3,
          'color': '#000000', 'align': 'left', 'tracking': 0}
    el.update(kw)
    return el


def fxl(md, designs, name):
    out = os.path.join(TMP, name + '.epub')
    epub.build_epub(manuscript.parse_markdown(md), TRIM, out,
                    {'title': 'T', 'author': 'A', 'page_designs': designs,
                     'ebook_layout': 'fixed', 'front_matter': 'none'})
    return out, read(out)[0]


art_only = {'name': 'fox-key', 'saved': 's', 'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#c08040'}]}
out, docs = fxl('~~~ page src="fox-key"\n~~~\n', [art_only], 'artonly')
page = next(v for k, v in docs.items() if 'page0' in k)
img = re.search(r'<img class="art"[^>]*>', page).group(0)
check('undescribed picture-only art is not hidden as decorative', 'presentation' not in img, img)
r = row(out, 'Image alt text')
check('the check names it', r is not None and not r['ok'], r)

worded = {'name': 'fox-words', 'saved': 's', 'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#c08040'},
    text('a', 6.0, 'Then turn the key.'), text('b', 1.0, 'First, unlock the door.')]}
out, docs = fxl('~~~ page src="fox-words"\n~~~\n', [worded], 'order')
page = next(v for k, v in docs.items() if 'page0' in k)
img = re.search(r'<img class="art"[^>]*>', page).group(0)
check('beside its own words the art stays decorative', 'role="presentation"' in img, img)
first, then = page.find('First,'), page.find('Then')
check('the top box is read first', 0 <= first < then, (first, then))
zs = re.findall(r'z-index:(\d+)', page)
check('each box keeps its layer', zs == ['3', '2'], zs)

real = F._render_art
F._render_art = lambda *a, **k: (_ for _ in ()).throw(OSError(28, 'No space left on device'))
try:
    fxl('~~~ page src="fox-key"\n~~~\n', [art_only], 'noart')
    check('a failed render stops the export', False)
except RuntimeError as e:
    check('a failed render stops the export, naming the page',
          'page 1' in str(e) and 'fox-key' in str(e), e)
finally:
    F._render_art = real

# 21.8 a right-aligned line in a box of no width, its origin just right of the
# fold, runs back across it: the left page shows its part
fold = {'name': 'fold-line', 'spread': True, 'saved': 's', 'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'sheet', 'color': '#ffffff'},
    {'id': 't', 'type': 'text', 'anchor': 'sheet', 'x': 8.75, 'y': 2.0, 'w': 0,
     'text': 'a long line that runs back over the fold', 'font': 'Andika-Regular.ttf',
     'size': 30, 'color': '#000000', 'align': 'right'}]}
out, docs = fxl('~~~ page src="fold-line"\n~~~\n', [fold], 'fold')
pages = sorted((k, v) for k, v in docs.items() if re.search(r'page\d+\.xhtml', k))
with_words = [k for k, v in pages if 'over the fold' in v or 'runs' in v]
check('both pages of the spread carry the line', len(with_words) == 2, [k for k, _ in pages])

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
