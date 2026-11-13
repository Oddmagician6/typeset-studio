"""75c spike: does live text over a text-less art picture, in headless Chrome,
land where the PDF draws it? Run from the repo root:
    python <this> <out_dir>
"""
import html, os, subprocess, sys

REPO = os.getcwd()
sys.path.insert(0, REPO)
import engine, wrap_design as W
from reportlab.pdfbase import pdfmetrics
from PIL import Image, ImageChops

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
W.FONT_DIR = os.path.join(REPO, 'fonts')
PX = 150                # px per inch in the viewport
TW = TH = 8.5

design = {'name': 'spike', 'elements': [
    {'id': 'bg', 'type': 'rect', 'fill': 'front', 'color': '#f4ecd8'},
    {'id': 'sun', 'type': 'ellipse', 'anchor': 'front', 'x': 5.6, 'y': 0.6, 'w': 2, 'h': 2,
     'color': '#e8a33a'},
    {'id': 'title', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 0.9, 'w': 7,
     'text': 'The Fox Who Counted Stars', 'font': 'Andika-Bold.ttf', 'size': 40,
     'leading': 1.1, 'color': '#2a2622', 'align': 'center', 'tracking': 0},
    {'id': 'body', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 3.4, 'w': 5.2,
     'text': ('Every night the little fox climbed the hill behind the farm and counted '
              'the stars, one by one, until her eyes grew heavy and the owls began to sing.\n'
              '\nShe never got past a hundred.'),
     'font': 'EBGaramond-Regular.ttf', 'size': 16, 'leading': 1.35, 'color': '#1b2a4a',
     'align': 'justify', 'tracking': 0.4},
    {'id': 'side', 'type': 'text', 'anchor': 'front', 'x': 7.6, 'y': 3.0,
     'text': 'CHAPTER ONE', 'font': 'Cinzel-Regular.ttf', 'size': 18, 'rotate': 90,
     'color': '#7a3020', 'tracking': 2},
    {'id': 'right', 'type': 'text', 'anchor': 'front', 'x': 0.75, 'y': 7.2, 'w': 7,
     'text': 'Andika italic, set right', 'font': 'Andika-Italic.ttf', 'size': 20,
     'color': '#000000', 'align': 'right', 'opacity': 0.8},
]}

# 1. the reference: the whole page as the PDF draws it
W.render_page(design, TW, TH, os.path.join(OUT, 'ref.png'.replace('.png', '.jpg')), dpi=PX)
# 2. the art: the same page without its words
art = {'elements': [e for e in design['elements'] if e['type'] != 'text']}
W.render_page(art, TW, TH, os.path.join(OUT, 'art.jpg'), dpi=PX)

# 3. the words, as live text
g = W.design_geometry(design, TW, TH)
faces, css = {}, []
for el in design['elements']:
    if el['type'] == 'text' and el['font'] not in faces:
        face = pdfmetrics.getFont(W.font_name(el['font'])).face
        fam = 'f%d' % len(faces)
        faces[el['font']] = (fam, face.ascent, -face.descent if face.descent < 0 else face.descent)
        css.append("@font-face{font-family:%s;src:url('%s');ascent-override:%.3f%%;"
                   "descent-override:%.3f%%;line-gap-override:0%%}"
                   % (fam, 'file:///' + W.font_file(el['font']).replace('\\', '/'),
                      face.ascent / 10.0, faces[el['font']][2] / 10.0))
k = PX / 72.0
spans = []
for el in design['elements']:
    if el['type'] != 'text':
        continue
    fam, asc, desc = faces[el['font']]
    x, y, w, h = W.el_rect(g, el)
    X, Y = (x - g['bleed']) * PX, (y - g['bleed']) * PX
    size = el['size'] * k
    lh = size * (asc + desc) / 1000.0
    rot = 'transform:rotate(90deg);transform-origin:0 0;' if el.get('rotate') == 90 else ''
    inner = []
    for line, dx, base, words in W.text_layout(el):
        for run, rx in (words or [(line, dx)]):
            top = base * k - size * asc / 1000.0
            inner.append('<span style="left:%.2fpx;top:%.2fpx">%s</span>'
                         % (rx * k, top, html.escape(run)))
    spans.append('<div class="t" style="left:%.2fpx;top:%.2fpx;%sfont-family:%s;'
                 'font-size:%.3fpx;line-height:%.3fpx;letter-spacing:%.3fpx;color:%s;'
                 'opacity:%s">%s</div>'
                 % (X, Y, rot, fam, size, lh, el.get('tracking', 0) * k,
                    el.get('color', '#000'), el.get('opacity', 1), ''.join(inner)))
vw, vh = round(TW * PX), round(TH * PX)
page = f'''<!DOCTYPE html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width={vw}, height={vh}"/>
<style>{''.join(css)}
html,body{{margin:0;padding:0;width:{vw}px;height:{vh}px;overflow:hidden}}
img{{position:absolute;left:0;top:0;width:{vw}px;height:{vh}px}}
.t{{position:absolute;width:0;height:0}}
.t span{{position:absolute;white-space:pre;font-kerning:none;font-variant-ligatures:none;
font-feature-settings:"kern" 0,"liga" 0,"clig" 0,"calt" 0}}
</style></head><body><img src="art.jpg" alt=""/>{''.join(spans)}</body></html>'''
with open(os.path.join(OUT, 'page.html'), 'w', encoding='utf-8') as f:
    f.write(page)

browser = os.environ.get('TS_BROWSER') or next(p for p in (
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe') if os.path.exists(p))
shot = os.path.join(OUT, 'shot.png')
subprocess.run([browser, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                '--force-device-scale-factor=1', f'--window-size={vw},{vh}',
                '--allow-file-access-from-files', '--virtual-time-budget=5000',
                '--user-data-dir=' + os.path.join(OUT, 'prof'),
                f'--screenshot={shot}', 'file:///' + os.path.join(OUT, 'page.html').replace('\\', '/')],
               capture_output=True, timeout=120)

ref = Image.open(os.path.join(OUT, 'ref.jpg')).convert('L')
got = Image.open(shot).convert('L').crop((0, 0, ref.width, ref.height))
print('sizes', ref.size, got.size)
diff = ImageChops.difference(ref, got)
diff.point(lambda v: 255 if v > 60 else 0).save(os.path.join(OUT, 'diff.png'))
hist = diff.histogram()
print('pixels differing >60: %.3f%%' % (100.0 * sum(hist[61:]) / (ref.width * ref.height)))

# per text box: the shift that best lines the screenshot up with the PDF
for el in design['elements']:
    if el['type'] != 'text':
        continue
    x, y, w, h = W.el_rect(g, el)
    lines = W.text_layout(el)
    bw = (w or 1.0) * PX if not el.get('rotate') else el['size'] * k * 1.5
    bh = (lines[-1][2] / 72.0 * PX + el['size'] * k * 0.4) if not el.get('rotate') else 3.5 * PX
    if el.get('align') == 'right' and not w:
        pass
    X0, Y0 = int((x - g['bleed']) * PX), int((y - g['bleed']) * PX)
    if el.get('rotate'):
        X0 -= int(bw)
    box = (max(X0 - 6, 0), max(Y0 - 6, 0), min(X0 + int(bw) + 6, ref.width),
           min(Y0 + int(bh) + 6, ref.height))
    r = ref.crop(box)
    best = None
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            s = got.crop((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
            d = sum(i * v for i, v in enumerate(ImageChops.difference(r, s).histogram()))
            if best is None or d < best[0]:
                best = (d, dx, dy)
    d0 = sum(i * v for i, v in enumerate(ImageChops.difference(r, got.crop(box)).histogram()))
    print('%-6s best shift dx=%+d dy=%+d  (error at 0,0: %d, at best: %d)'
          % (el['id'], best[1], best[2], d0, best[0]))
