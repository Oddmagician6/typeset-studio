"""Wrap designer spike server  (run: python spikes/wrap_designer/server.py [port]).

Not part of the app. Serves the SVG editor, the font files and their width
tables, builds proofs with model.build_pdf, and hosts the measurement harness
(/measure) that compares browser text measurement against ReportLab's.
"""

import os, sys, json, base64, glob, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model
import engine
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__)
OUT = tempfile.mkdtemp(prefix='wrap-spike-')


def ensure_art():
    """A generated stand-in for cover art: a dusk gradient with a sun disc."""
    os.makedirs(model.ART_DIR, exist_ok=True)
    path = os.path.join(model.ART_DIR, 'art.png')
    if os.path.exists(path):
        return
    from PIL import Image, ImageDraw
    w, h = 1800, 2700
    im = Image.new('RGB', (w, h))
    px = im.load()
    for yy in range(h):
        t = yy / h
        col = (int(40 + 180 * t), int(50 + 90 * t), int(110 - 40 * t))
        for xx in range(w):
            px[xx, yy] = col
    d = ImageDraw.Draw(im)
    d.ellipse((w * 0.3, h * 0.45, w * 0.7, h * 0.45 + w * 0.4), fill=(250, 214, 140))
    d.polygon([(0, h), (0, h * 0.72), (w * 0.35, h * 0.62), (w * 0.7, h * 0.74),
               (w, h * 0.66), (w, h)], fill=(30, 26, 40))
    im.save(path)


@app.route('/')
def editor():
    return send_from_directory(HERE, 'editor.html')


@app.route('/wd.js')
def wd_js():
    return send_from_directory(HERE, 'wd.js')


@app.route('/fonts/<path:f>')
def font_file(f):
    return send_from_directory(model.FONT_DIR, os.path.basename(f))


@app.route('/art/<path:f>')
def art_file(f):
    return send_from_directory(model.ART_DIR, os.path.basename(f))


@app.route('/fontlist')
def fontlist():
    return jsonify(sorted(os.path.basename(p) for p in glob.glob(os.path.join(model.FONT_DIR, '*.ttf'))))


@app.route('/metrics/<path:f>')
def metrics(f):
    return jsonify(model.metrics(os.path.basename(f)))


@app.route('/geometry', methods=['POST'])
def geometry():
    return jsonify(engine.wrap_geometry(request.get_json()))


@app.route('/build', methods=['POST'])
def build():
    """Build the real PDF from a design and hand back a picture of it."""
    import fitz
    body = request.get_json()
    path = os.path.join(OUT, 'proof.pdf')
    lines = model.build_pdf(body['design'], body['dims'], path)
    with fitz.open(path) as doc:
        png = doc[0].get_pixmap(dpi=body.get('dpi', 40)).tobytes('png')
    return jsonify(lines=lines, png='data:image/png;base64,' + base64.b64encode(png).decode())


@app.route('/proof.pdf')
def proof_pdf():
    return send_from_directory(OUT, 'proof.pdf')


# ---- measurement harness ---------------------------------------------------

def corpus():
    """Real prose for blurbs: paragraphs from the sample and local manuscripts."""
    root = model.ROOT
    paras = []
    for p in [os.path.join(root, 'sample', 'sample.md')] + sorted(
            glob.glob(os.path.join(root, 'projects', 'manuscripts', '*.md'))):
        for block in open(p, encoding='utf-8').read().split('\n\n'):
            b = ' '.join(block.split())
            if len(b) > 120 and not b.startswith(('#', '~', '[^', '===')):
                paras.append(b)
    return paras[:60]


@app.route('/measure')
def measure_page():
    return send_from_directory(HERE, 'measure.html')


@app.route('/measure/data')
def measure_data():
    return jsonify(fonts=json.loads(fontlist().get_data()), corpus=corpus())


RESULT = {}


@app.route('/measure/result', methods=['POST'])
def measure_result():
    RESULT.clear()
    RESULT.update(request.get_json())
    out = os.environ.get('WD_RESULT')
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(RESULT, f)
    return 'ok'


if __name__ == '__main__':
    ensure_art()
    app.run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 5099, debug=False)
