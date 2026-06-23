"""Typeset Studio - local web app.

Run:  python app.py   (a browser tab opens at http://127.0.0.1:5050)

This is a single-user tool meant to run on your own machine. Presets live as
plain JSON files in ./presets so you can clone one per customer and tweak it.
"""

import os
import re
import json
import logging
import threading
import traceback
import webbrowser
from datetime import datetime

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s')

from flask import (Flask, request, redirect, url_for, render_template,
                   send_from_directory, abort, flash)
from werkzeug.utils import secure_filename

import engine
import manuscript

HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR = os.path.join(HERE, 'presets')
OUT_DIR = os.path.join(HERE, 'out')
UPLOAD_DIR = os.path.join(HERE, 'uploads')
SAMPLE = os.path.join(HERE, 'sample', 'sample.md')
for d in (PRESET_DIR, OUT_DIR, UPLOAD_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'typeset-studio-local'


# ----------------------------------------------------------------- presets
DEFAULTS = {
    'name': 'Untitled style', 'description': '',
    'trim': {'w': 6.0, 'h': 9.0},
    'margins': {'top': 0.75, 'bottom': 0.8, 'inside': 0.85, 'outside': 0.6},
    'font_family': 'Book',
    'font_files': {'regular': 'Book-Regular.ttf', 'bold': 'Book-Bold.ttf',
                   'italic': 'Book-Italic.ttf'},
    'body': {'size': 11.0, 'leading': 15.5, 'indent': 0.3, 'justify': True,
             'hyphenate': False},
    'chapter': {'start': 'recto', 'sink': 1.1, 'show_number': True,
                'number_format': 'Chapter {n}', 'number_size': 12.0,
                'title_size': 18.0, 'after_title': 0.45,
                'open_style': 'smallcaps_leadin', 'leadin_words': 4,
                'dropcap_lines': 3},
    'scene_break': {'glyph': '* * *', 'size': 11.0, 'gap': 9.0},
    'running_head': {'show': True, 'caps': True, 'size': 8.5, 'gap': 0.28},
    'folio': {'show': True, 'position': 'outer', 'size': 9.5, 'gap': 0.42,
              'hide_on_opener': True},
}


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or 'style'


def list_presets():
    items = []
    for fn in sorted(os.listdir(PRESET_DIR)):
        if fn.endswith('.json'):
            try:
                with open(os.path.join(PRESET_DIR, fn), encoding='utf-8') as f:
                    data = json.load(f)
                items.append({'id': fn[:-5], 'data': data})
            except Exception:
                pass
    return items


def load_preset(pid):
    path = os.path.join(PRESET_DIR, secure_filename(pid) + '.json')
    if not os.path.exists(path):
        abort(404)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_preset(pid, data):
    path = os.path.join(PRESET_DIR, secure_filename(pid) + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def unique_id(base):
    pid, n = base, 2
    existing = {i['id'] for i in list_presets()}
    while pid in existing:
        pid = f'{base}-{n}'
        n += 1
    return pid


def _f(form, key, default):
    try:
        return float(form.get(key, default))
    except (TypeError, ValueError):
        return default


def parse_preset_form(form):
    return {
        'name': form.get('name', '').strip() or 'Untitled style',
        'description': form.get('description', '').strip(),
        'trim': {'w': _f(form, 'trim_w', 6.0), 'h': _f(form, 'trim_h', 9.0)},
        'margins': {'top': _f(form, 'm_top', 0.75), 'bottom': _f(form, 'm_bottom', 0.8),
                    'inside': _f(form, 'm_inside', 0.85), 'outside': _f(form, 'm_outside', 0.6)},
        'font_family': form.get('font_family', 'Book').strip() or 'Book',
        'font_files': {
            'regular': form.get('font_regular', 'Book-Regular.ttf').strip() or 'Book-Regular.ttf',
            'bold': form.get('font_bold', 'Book-Bold.ttf').strip() or 'Book-Bold.ttf',
            'italic': form.get('font_italic', 'Book-Italic.ttf').strip() or 'Book-Italic.ttf',
        },
        'body': {'size': _f(form, 'b_size', 11.0), 'leading': _f(form, 'b_leading', 15.5),
                 'indent': _f(form, 'b_indent', 0.3),
                 'justify': 'b_justify' in form, 'hyphenate': 'b_hyphenate' in form},
        'chapter': {
            'start': form.get('c_start', 'recto'),
            'sink': _f(form, 'c_sink', 1.1),
            'show_number': 'c_show_number' in form,
            'number_format': form.get('c_number_format', 'Chapter {n}') or 'Chapter {n}',
            'number_size': _f(form, 'c_number_size', 12.0),
            'title_size': _f(form, 'c_title_size', 18.0),
            'after_title': _f(form, 'c_after_title', 0.45),
            'open_style': form.get('c_open_style', 'smallcaps_leadin'),
            'leadin_words': int(_f(form, 'c_leadin_words', 4)),
            'dropcap_lines': int(_f(form, 'c_dropcap_lines', 3)),
        },
        'scene_break': {'glyph': form.get('s_glyph', '* * *') or '* * *',
                        'size': _f(form, 's_size', 11.0), 'gap': _f(form, 's_gap', 9.0)},
        'running_head': {'show': 'rh_show' in form, 'caps': 'rh_caps' in form,
                         'size': _f(form, 'rh_size', 8.5), 'gap': _f(form, 'rh_gap', 0.28)},
        'folio': {'show': 'fo_show' in form, 'position': form.get('fo_position', 'outer'),
                  'size': _f(form, 'fo_size', 9.5), 'gap': _f(form, 'fo_gap', 0.42),
                  'hide_on_opener': 'fo_hide_on_opener' in form},
    }


# ----------------------------------------------------------------- routes
@app.route('/')
def index():
    return render_template('index.html', presets=list_presets())


@app.route('/editor/new')
def editor_new():
    return render_template('editor.html', pid=None, p=DEFAULTS, is_new=True)


@app.route('/editor/<pid>')
def editor(pid):
    return render_template('editor.html', pid=pid, p=load_preset(pid), is_new=False)


@app.route('/save', methods=['POST'])
@app.route('/save/<pid>', methods=['POST'])
def save(pid=None):
    data = parse_preset_form(request.form)
    if pid is None:
        pid = unique_id(slugify(data['name']))
    save_preset(pid, data)
    flash(f'Saved \u201c{data["name"]}\u201d.')
    return redirect(url_for('index'))


@app.route('/clone/<pid>', methods=['POST'])
def clone(pid):
    data = load_preset(pid)
    data['name'] = data.get('name', 'Style') + ' (copy)'
    new_id = unique_id(slugify(data['name']))
    save_preset(new_id, data)
    flash('Created a copy you can rename and tweak.')
    return redirect(url_for('editor', pid=new_id))


@app.route('/delete/<pid>', methods=['POST'])
def delete(pid):
    path = os.path.join(PRESET_DIR, secure_filename(pid) + '.json')
    if os.path.exists(path):
        os.remove(path)
        flash('Style deleted.')
    return redirect(url_for('index'))


@app.route('/generate', methods=['GET', 'POST'])
def generate():
    presets = list_presets()
    if request.method == 'GET':
        return render_template('generate.html', presets=presets, form={})

    form = request.form
    pid = form.get('preset')
    if not pid:
        flash('Pick a style first.')
        return render_template('generate.html', presets=presets, form=form)
    preset = load_preset(pid)

    # manuscript source: uploaded file, pasted text, or the bundled sample
    raw = None
    up = request.files.get('manuscript')
    if up and up.filename:
        fn = secure_filename(up.filename)
        dest = os.path.join(UPLOAD_DIR, fn)
        up.save(dest)
        if fn.lower().endswith('.docx'):
            try:
                raw = manuscript.import_docx(dest)
            except ModuleNotFoundError:
                flash('python-docx is not installed. Run: pip install python-docx')
                return render_template('generate.html', presets=presets, form=form)
            except Exception as exc:
                logging.error('docx import failed: %s', traceback.format_exc())
                flash(f'Could not read the Word file: {exc}')
                return render_template('generate.html', presets=presets, form=form)
        else:
            raw = open(dest, encoding='utf-8', errors='replace').read()
    elif form.get('pasted', '').strip():
        raw = form['pasted']
    elif form.get('use_sample'):
        raw = open(SAMPLE, encoding='utf-8').read()

    if not raw:
        flash('Add a manuscript: upload a file, paste text, or use the sample.')
        return render_template('generate.html', presets=presets, form=form)

    # optional cover art
    cover_path = ''
    cov = request.files.get('cover')
    if cov and cov.filename:
        cfn = secure_filename(cov.filename)
        cover_path = os.path.join(UPLOAD_DIR, cfn)
        cov.save(cover_path)

    ms = manuscript.parse_markdown(raw)
    meta = {
        'title': form.get('title', '').strip(),
        'subtitle': form.get('subtitle', '').strip(),
        'author': form.get('author', '').strip(),
        'year': form.get('year', '').strip() or str(datetime.now().year),
        'publisher': form.get('publisher', '').strip(),
        'front_matter': form.get('front_matter', 'full'),
        'right_hand_starts': 'right_hand_starts' in form,
        'cover_image': cover_path,
        'cover_overlay': 'cover_overlay' in form,
        'cover_color': form.get('cover_color', 'light'),
    }
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base = slugify(meta['title'] or 'book')
    out_name = f'{base}-{stamp}.pdf'
    try:
        engine.build_pdf(ms, preset, os.path.join(OUT_DIR, out_name), meta)
    except Exception as exc:
        logging.error('PDF build failed: %s', traceback.format_exc())
        flash(f'PDF build failed: {exc}')
        return render_template('generate.html', presets=presets, form=form)

    chapters = len(ms['chapters'])
    return render_template('result.html', out_name=out_name, meta=meta,
                           preset=preset, chapters=chapters)


@app.route('/out/<path:fn>')
def out_file(fn):
    return send_from_directory(OUT_DIR, fn)


@app.route('/download/<path:fn>')
def download(fn):
    return send_from_directory(OUT_DIR, fn, as_attachment=True)


def _open_browser():
    webbrowser.open('http://127.0.0.1:5050/')


if __name__ == '__main__':
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Timer(1.0, _open_browser).start()
    app.run(host='127.0.0.1', port=5050, debug=True)
