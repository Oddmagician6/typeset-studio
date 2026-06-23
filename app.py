"""Typeset Studio - local web app.

Run:  python app.py   (a browser tab opens at http://127.0.0.1:5050)

This is a single-user tool meant to run on your own machine. Presets live as
plain JSON files in ./presets so you can clone one per customer and tweak it.
"""

import os
import re
import json
import shutil
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
import epub
import manuscript

HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR    = os.path.join(HERE, 'presets')
OUT_DIR       = os.path.join(HERE, 'out')
UPLOAD_DIR    = os.path.join(HERE, 'uploads')
PROJECT_DIR   = os.path.join(HERE, 'projects')
PROJECT_MS_DIR = os.path.join(PROJECT_DIR, 'manuscripts')
SAMPLE = os.path.join(HERE, 'sample', 'sample.md')
for d in (PRESET_DIR, OUT_DIR, UPLOAD_DIR, PROJECT_DIR, PROJECT_MS_DIR):
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


# ----------------------------------------------------------------- projects
def list_projects():
    items = []
    for fn in sorted(os.listdir(PROJECT_DIR)):
        if fn.endswith('.json'):
            try:
                with open(os.path.join(PROJECT_DIR, fn), encoding='utf-8') as f:
                    data = json.load(f)
                items.append({'id': fn[:-5], 'data': data})
            except Exception:
                pass
    return sorted(items, key=lambda x: x['data'].get('updated', ''), reverse=True)


def load_project(pid):
    path = os.path.join(PROJECT_DIR, secure_filename(pid) + '.json')
    if not os.path.exists(path):
        abort(404)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_project_file(pid, data):
    path = os.path.join(PROJECT_DIR, secure_filename(pid) + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def unique_project_id(base):
    pid, n = base, 2
    existing = {i['id'] for i in list_projects()}
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
    fmt = form.get('format', 'pdf')

    # manuscript source: uploaded file, pasted text, or the bundled sample
    raw = None
    ms_path = ''   # stable file path — stored with project on save
    ms_type = 'file'

    up = request.files.get('manuscript')
    if up and up.filename:
        fn = secure_filename(up.filename)
        dest = os.path.join(UPLOAD_DIR, fn)
        up.save(dest)
        ms_path, ms_type = dest, 'file'
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
        stamp_p = datetime.now().strftime('%Y%m%d-%H%M%S')
        ms_path = os.path.join(UPLOAD_DIR, f'pasted-{stamp_p}.txt')
        with open(ms_path, 'w', encoding='utf-8') as pf:
            pf.write(raw)
        ms_type = 'pasted'
    elif form.get('use_sample'):
        raw = open(SAMPLE, encoding='utf-8').read()
        ms_type = 'sample'

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
    base  = slugify(meta['title'] or 'book')

    out_name  = ''
    epub_name = ''

    if fmt in ('pdf', 'both'):
        out_name = f'{base}-{stamp}.pdf'
        try:
            engine.build_pdf(ms, preset, os.path.join(OUT_DIR, out_name), meta)
        except Exception as exc:
            logging.error('PDF build failed: %s', traceback.format_exc())
            flash(f'PDF build failed: {exc}')
            return render_template('generate.html', presets=presets, form=form)

    if fmt in ('epub', 'both'):
        epub_name = f'{base}-{stamp}.epub'
        try:
            epub.build_epub(ms, preset, os.path.join(OUT_DIR, epub_name), meta)
        except Exception as exc:
            logging.error('EPUB build failed: %s', traceback.format_exc())
            flash(f'EPUB build failed: {exc}')
            epub_name = ''

    chapters = len(ms['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=pid,
                           chapters=chapters, ms_path=ms_path, ms_type=ms_type,
                           cover_path=cover_path, from_project=None, fmt=fmt)


# ----------------------------------------------------------------- project routes
@app.route('/projects')
def projects():
    preset_map = {p['id']: p['data'] for p in list_presets()}
    return render_template('projects.html', projects=list_projects(),
                           preset_map=preset_map)


@app.route('/project/create', methods=['POST'])
def project_create():
    form = request.form
    name = form.get('project_name', '').strip() or form.get('title', '').strip() or 'Untitled'
    proj_id = unique_project_id(slugify(name) or 'project')

    ms_src  = form.get('ms_path', '')
    ms_type = form.get('ms_type', 'file')
    ms_file = ''
    if ms_type != 'sample' and ms_src and os.path.exists(ms_src):
        ext = os.path.splitext(ms_src)[1]
        ms_file = proj_id + ext
        shutil.copy2(ms_src, os.path.join(PROJECT_MS_DIR, ms_file))

    cover_src  = form.get('cover_path', '')
    cover_file = ''
    if cover_src and os.path.exists(cover_src):
        ext = os.path.splitext(cover_src)[1]
        cover_file = proj_id + '-cover' + ext
        shutil.copy2(cover_src, os.path.join(PROJECT_MS_DIR, cover_file))

    now = datetime.now().isoformat(timespec='seconds')
    data = {
        'name': name,
        'preset': form.get('preset_id', ''),
        'title': form.get('title', '').strip(),
        'subtitle': form.get('subtitle', '').strip(),
        'author': form.get('author', '').strip(),
        'year': form.get('year', '').strip(),
        'publisher': form.get('publisher', '').strip(),
        'front_matter': form.get('front_matter', 'full'),
        'right_hand_starts': form.get('right_hand_starts') == '1',
        'cover_overlay': form.get('cover_overlay') == '1',
        'cover_color': form.get('cover_color', 'light'),
        'format': form.get('fmt', 'pdf'),
        'manuscript_file': ms_file,
        'manuscript_type': ms_type,
        'cover_file': cover_file,
        'last_pdf': form.get('last_pdf', ''),
        'last_epub': form.get('last_epub', ''),
        'created': now,
        'updated': now,
    }
    save_project_file(proj_id, data)
    flash(f'“{name}” saved as a project.')
    return redirect(url_for('projects'))


@app.route('/project/<pid>/edit', methods=['GET', 'POST'])
def project_edit(pid):
    proj = load_project(pid)
    presets = list_presets()

    if request.method == 'POST':
        form = request.form

        # Optional manuscript replacement
        up = request.files.get('manuscript')
        if up and up.filename:
            fn  = secure_filename(up.filename)
            ext = os.path.splitext(fn)[1]
            dest = os.path.join(PROJECT_MS_DIR, pid + ext)
            up.save(dest)
            # Remove old file if extension changed
            old = proj.get('manuscript_file', '')
            if old and old != pid + ext:
                old_path = os.path.join(PROJECT_MS_DIR, old)
                if os.path.exists(old_path):
                    os.remove(old_path)
            proj['manuscript_file'] = pid + ext
            proj['manuscript_type'] = 'file'

        # Optional cover replacement
        cov = request.files.get('cover')
        if cov and cov.filename:
            cfn = secure_filename(cov.filename)
            ext = os.path.splitext(cfn)[1]
            dest = os.path.join(PROJECT_MS_DIR, pid + '-cover' + ext)
            cov.save(dest)
            old = proj.get('cover_file', '')
            if old and old != pid + '-cover' + ext:
                old_path = os.path.join(PROJECT_MS_DIR, old)
                if os.path.exists(old_path):
                    os.remove(old_path)
            proj['cover_file'] = pid + '-cover' + ext

        proj.update({
            'name':             form.get('name', '').strip() or proj['name'],
            'preset':           form.get('preset', proj['preset']),
            'format':           form.get('format', proj.get('format', 'pdf')),
            'title':            form.get('title', '').strip(),
            'subtitle':         form.get('subtitle', '').strip(),
            'author':           form.get('author', '').strip(),
            'year':             form.get('year', '').strip(),
            'publisher':        form.get('publisher', '').strip(),
            'front_matter':     form.get('front_matter', 'full'),
            'right_hand_starts': 'right_hand_starts' in form,
            'cover_overlay':    'cover_overlay' in form,
            'cover_color':      form.get('cover_color', 'light'),
            'updated':          datetime.now().isoformat(timespec='seconds'),
        })
        save_project_file(pid, proj)
        flash('Project updated.')
        return redirect(url_for('projects'))

    return render_template('project_edit.html', pid=pid, proj=proj, presets=presets)


@app.route('/project/<pid>/generate', methods=['POST'])
def project_generate(pid):
    proj   = load_project(pid)
    preset = load_preset(proj['preset'])

    ms_type = proj.get('manuscript_type', 'file')
    ms_file = proj.get('manuscript_file', '')
    raw = None

    if ms_type == 'sample':
        raw = open(SAMPLE, encoding='utf-8').read()
    elif ms_file:
        ms_path = os.path.join(PROJECT_MS_DIR, ms_file)
        if not os.path.exists(ms_path):
            flash('Manuscript file not found — please replace it via Edit.')
            return redirect(url_for('projects'))
        if ms_file.lower().endswith('.docx'):
            try:
                raw = manuscript.import_docx(ms_path)
            except Exception as exc:
                logging.error('docx import failed: %s', traceback.format_exc())
                flash(f'Could not read the Word file: {exc}')
                return redirect(url_for('projects'))
        else:
            raw = open(ms_path, encoding='utf-8', errors='replace').read()

    if not raw:
        flash('No manuscript found for this project.')
        return redirect(url_for('projects'))

    cover_path = ''
    cover_file = proj.get('cover_file', '')
    if cover_file:
        cp = os.path.join(PROJECT_MS_DIR, cover_file)
        if os.path.exists(cp):
            cover_path = cp

    ms_parsed = manuscript.parse_markdown(raw)
    meta = {
        'title':            proj.get('title', ''),
        'subtitle':         proj.get('subtitle', ''),
        'author':           proj.get('author', ''),
        'year':             proj.get('year', '') or str(datetime.now().year),
        'publisher':        proj.get('publisher', ''),
        'front_matter':     proj.get('front_matter', 'full'),
        'right_hand_starts': proj.get('right_hand_starts', True),
        'cover_image':      cover_path,
        'cover_overlay':    proj.get('cover_overlay', False),
        'cover_color':      proj.get('cover_color', 'light'),
    }
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base  = slugify(meta['title'] or proj.get('name', 'book'))
    fmt   = proj.get('format', 'pdf')

    out_name  = ''
    epub_name = ''

    if fmt in ('pdf', 'both'):
        out_name = f'{base}-{stamp}.pdf'
        try:
            engine.build_pdf(ms_parsed, preset, os.path.join(OUT_DIR, out_name), meta)
        except Exception as exc:
            logging.error('PDF build failed: %s', traceback.format_exc())
            flash(f'PDF build failed: {exc}')
            return redirect(url_for('projects'))

    if fmt in ('epub', 'both'):
        epub_name = f'{base}-{stamp}.epub'
        try:
            epub.build_epub(ms_parsed, preset, os.path.join(OUT_DIR, epub_name), meta)
        except Exception as exc:
            logging.error('EPUB build failed: %s', traceback.format_exc())
            flash(f'EPUB build failed: {exc}')
            epub_name = ''

    proj['last_pdf']  = out_name
    proj['last_epub'] = epub_name
    proj['updated']   = datetime.now().isoformat(timespec='seconds')
    save_project_file(pid, proj)

    chapters = len(ms_parsed['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=proj['preset'],
                           chapters=chapters, ms_path='', ms_type=ms_type,
                           cover_path=cover_path, from_project=pid, fmt=fmt)


@app.route('/project/<pid>/delete', methods=['POST'])
def project_delete(pid):
    try:
        proj = load_project(pid)
        for field in ('manuscript_file', 'cover_file'):
            fn = proj.get(field, '')
            if fn:
                fp = os.path.join(PROJECT_MS_DIR, fn)
                if os.path.exists(fp):
                    os.remove(fp)
    except Exception:
        pass
    path = os.path.join(PROJECT_DIR, secure_filename(pid) + '.json')
    if os.path.exists(path):
        os.remove(path)
    flash('Project deleted.')
    return redirect(url_for('projects'))


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
