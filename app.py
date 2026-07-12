"""Typeset Studio - local web app.

Run:  python app.py   (a browser tab opens at http://127.0.0.1:5050)

This is a single-user tool meant to run on your own machine. Presets live as
plain JSON files in ./presets so you can clone one per customer and tweak it.
"""

import os
import re
import json
import base64
import shutil
import logging
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s')

from flask import (Flask, request, redirect, url_for, render_template,
                   send_from_directory, abort, flash, jsonify)
from werkzeug.utils import secure_filename

import engine
import epub
import manuscript
import checker

HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR    = os.path.join(HERE, 'presets')
COVER_DIR     = os.path.join(HERE, 'covers')
OUT_DIR       = os.path.join(HERE, 'out')
UPLOAD_DIR    = os.path.join(HERE, 'uploads')
PROJECT_DIR   = os.path.join(HERE, 'projects')
PROJECT_MS_DIR = os.path.join(PROJECT_DIR, 'manuscripts')
SAMPLE = os.path.join(HERE, 'sample', 'sample.md')
for d in (PRESET_DIR, COVER_DIR, OUT_DIR, UPLOAD_DIR, PROJECT_DIR, PROJECT_MS_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'typeset-studio-local'

PREVIEW_SAMPLE = """\
# The First Chapter

The opening paragraph of the first chapter, with enough words to fill more than
one line of body text at normal settings and demonstrate the chapter-open style.

A second paragraph shows line spacing and justification. The quick brown fox
jumps over the lazy dog. Pack my box with five dozen liquor jugs.

A third paragraph adds volume so the body pages look realistic and the reader
can appreciate how leading and margins interact across a full column of prose.

* * *

After the scene break the story continues, showing the post-break paragraph
set flush-left just as it would appear in a finished book.

One more paragraph of body text, long enough to reach the second line so that
justification and hyphenation behaviour are visible in the preview.

# The Second Chapter

The second chapter opener demonstrates the sink, number label, chapter title
typography, and the opening-paragraph treatment all in one place.
"""


# ----------------------------------------------------------------- print spec
# Pages-per-inch factors for spine width calculation (source: KDP / IngramSpark docs)
_PAPER = {
    'white': {'label': 'White (60 lb)',  'ppi': 0.002252},
    'cream': {'label': 'Cream (60 lb)',  'ppi': 0.0025},
    'color': {'label': 'Color',          'ppi': 0.002347},
}

# (min_pages, max_pages, min_inside_inches)
_KDP_MARGINS    = [(24,150,.375),(151,300,.5),(301,500,.625),(501,700,.75),(701,828,.875)]
_INGRAM_MARGINS = [(1,100,.375),(101,200,.5),(201,300,.625),(301,400,.75),(401,600,.875),(601,9999,1.0)]


def _min_inside(pages, table):
    for lo, hi, m in table:
        if lo <= pages <= hi:
            return m
    return None


def _preflight(build_result, preset, page_count):
    """Return a list of preflight check dicts: {label, ok, detail}."""
    checks = []
    requested = preset.get('font_family', 'Book')

    if build_result.get('font_fallback'):
        checks.append({'label': f'Fonts ({requested})', 'ok': False,
                       'detail': 'Font files not found — fell back to Times Roman (not embedded)'})
    else:
        checks.append({'label': f'Fonts ({build_result["font_family"]})', 'ok': True,
                       'detail': 'Custom fonts loaded'})
        for role, info in build_result.get('font_details', {}).items():
            if not info['ok']:
                checks.append({'label': f'  {role.capitalize()} weight', 'ok': False,
                               'detail': f'{info["file"]} — {info["error"]}'})

    checks.append({'label': 'Fonts embedded', 'ok': build_result.get('fonts_embedded', True),
                   'detail': ('Embedded & subsetted — upload-ready'
                              if build_result.get('fonts_embedded')
                              else 'Standard PDF fonts not embedded — platforms may reject')})

    if page_count:
        kdp_ok = 24 <= page_count <= 828
        checks.append({'label': 'Page count', 'ok': kdp_ok,
                       'detail': (f'{page_count} pages — within KDP range (24–828)'
                                  if kdp_ok else
                                  f'{page_count} pages — outside KDP range (24–828)')})

    return checks


def print_spec(page_count, preset):
    """Return a dict of spine widths and minimum inside-margin info for the result page."""
    inside    = preset['margins']['inside']
    kdp_min   = _min_inside(page_count, _KDP_MARGINS)
    ingram_min = _min_inside(page_count, _INGRAM_MARGINS)
    return {
        'page_count': page_count,
        'inside':     round(inside, 3),
        'spines':     {k: round(page_count * v['ppi'], 3) for k, v in _PAPER.items()},
        'paper':      {k: v['label'] for k, v in _PAPER.items()},
        'kdp_min':    kdp_min,
        'ingram_min': ingram_min,
        'kdp_ok':     (inside >= kdp_min)    if kdp_min    else None,
        'ingram_ok':  (inside >= ingram_min) if ingram_min else None,
    }


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
    'part_divider': {'show_number': True, 'number_format': 'Part {n}',
                     'number_size': 13.0, 'title_size': 26.0, 'sink': 0.38},
    'document_block': {'frame': 'ruled', 'indent': 0.25, 'font_size': 0,
                       'first_indent': 0.0, 'space_around': 12.0,
                       'header_size': 9.5, 'dateline_style': 'italic'},
    'scene_break': {'type': 'glyph', 'glyph': '* * *', 'size': 11.0, 'gap': 9.0, 'image': ''},
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


def list_cover_templates():
    """Text-driven cover templates from ./covers, one JSON per house style."""
    items = []
    for fn in sorted(os.listdir(COVER_DIR)):
        if fn.endswith('.json'):
            try:
                with open(os.path.join(COVER_DIR, fn), encoding='utf-8') as f:
                    data = json.load(f)
                items.append({'id': fn[:-5], 'data': data})
            except Exception:
                pass
    return items


def load_cover_template(cid):
    if not cid:
        return None
    path = os.path.join(COVER_DIR, secure_filename(cid) + '.json')
    if not os.path.exists(path):
        return None
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
        'part_divider': {
            'show_number':   'pd_show_number' in form,
            'number_format':  form.get('pd_number_format', 'Part {n}') or 'Part {n}',
            'number_size':   _f(form, 'pd_number_size', 13.0),
            'title_size':    _f(form, 'pd_title_size', 26.0),
            'sink':          _f(form, 'pd_sink', 0.38),
        },
        'document_block': {
            'frame':          form.get('db_frame', 'ruled'),
            'indent':         _f(form, 'db_indent', 0.25),
            'font_size':      _f(form, 'db_font_size', 0),
            'first_indent':   _f(form, 'db_first_indent', 0.0),
            'space_around':   _f(form, 'db_space_around', 12.0),
            'header_size':    _f(form, 'db_header_size', 9.5),
            'dateline_style': form.get('db_dateline_style', 'italic'),
        },
        'scene_break': {
            'type':  form.get('sb_type', 'glyph'),
            'glyph': form.get('s_glyph', '* * *') or '* * *',
            'size':  _f(form, 's_size', 11.0),
            'gap':   _f(form, 's_gap', 9.0),
            'image': form.get('sb_image', '').strip(),
        },
        'running_head': {'show': 'rh_show' in form, 'caps': 'rh_caps' in form,
                         'size': _f(form, 'rh_size', 8.5), 'gap': _f(form, 'rh_gap', 0.28)},
        'folio': {'show': 'fo_show' in form, 'position': form.get('fo_position', 'outer'),
                  'size': _f(form, 'fo_size', 9.5), 'gap': _f(form, 'fo_gap', 0.42),
                  'hide_on_opener': 'fo_hide_on_opener' in form},
    }


# ----------------------------------------------------------------- routes
@app.context_processor
def _inject_cover_templates():
    return {'cover_templates': list_cover_templates()}


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
    cover_mode = form.get('cover_mode', 'none')
    cover_path = ''
    cov = request.files.get('cover')
    if cov and cov.filename:
        cfn = secure_filename(cov.filename)
        cover_path = os.path.join(UPLOAD_DIR, cfn)
        cov.save(cover_path)
    if cover_mode == 'none':
        cover_path = ''

    cover_template = form.get('cover_template', '') or 'ashforge-house'
    cover_template_data = load_cover_template(cover_template) if cover_mode == 'designed' else None

    meta = {
        'title': form.get('title', '').strip(),
        'subtitle': form.get('subtitle', '').strip(),
        'author': form.get('author', '').strip(),
        'year': form.get('year', '').strip() or str(datetime.now().year),
        'publisher': form.get('publisher', '').strip(),
        'front_matter': form.get('front_matter', 'full'),
        'right_hand_starts': 'right_hand_starts' in form,
        'cover_image': cover_path,
        'cover_mode': cover_mode,
        'cover_template': cover_template,
        'cover_template_data': cover_template_data,
        'cover_collection': form.get('cover_collection', '').strip(),
        'cover_kicker': form.get('cover_kicker', '').strip(),
        'cover_accent': form.get('cover_accent', '').strip(),
        'cover_epigraph': form.get('cover_epigraph', '').strip(),
        'cover_studio': form.get('cover_studio', '').strip(),
        'cover_overlay': 'cover_overlay' in form,
        'cover_color': form.get('cover_color', 'light'),
        'include_toc':    'include_toc' in form,
        'smartquotes':    'smartquotes' in form,
        'dedication':     form.get('dedication', '').strip(),
        'epigraph':       form.get('epigraph', '').strip(),
        'acknowledgments': form.get('acknowledgments', '').strip(),
        'about_author':   form.get('about_author', '').strip(),
        'also_by':        form.get('also_by', '').strip(),
    }
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base  = slugify(meta['title'] or 'book')

    ms = manuscript.parse_markdown(raw, smartquotes=meta['smartquotes'])

    out_name  = ''
    epub_name = ''

    build_result = None
    page_count   = 0
    if fmt in ('pdf', 'both'):
        out_name = f'{base}-{stamp}.pdf'
        try:
            build_result = engine.build_pdf(ms, preset, os.path.join(OUT_DIR, out_name), meta)
            page_count   = build_result['page_count']
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

    spec      = print_spec(page_count, preset) if page_count else None
    preflight = _preflight(build_result, preset, page_count) if build_result else None
    chapters  = len(ms['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=pid,
                           chapters=chapters, ms_path=ms_path, ms_type=ms_type,
                           cover_path=cover_path, from_project=None, fmt=fmt,
                           spec=spec, preflight=preflight)


# ----------------------------------------------------------------- preview
@app.route('/preview', methods=['POST'])
def preview():
    try:
        import fitz
    except ImportError:
        return jsonify({'ok': False,
                        'error': 'pymupdf not installed — run: pip install pymupdf'})
    try:
        preset = parse_preset_form(request.form)
        ms     = manuscript.parse_markdown(PREVIEW_SAMPLE, smartquotes=True)
        meta   = {
            'title': 'Preview', 'subtitle': '', 'author': 'Author Name',
            'year': '2026', 'publisher': '',
            'front_matter': 'none', 'right_hand_starts': False,
            'cover_image': '', 'cover_overlay': False, 'cover_color': 'light',
            'smartquotes': True,
            'dedication': '', 'epigraph': '', 'acknowledgments': '',
            'about_author': '', 'also_by': '',
        }
        fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        try:
            engine.build_pdf(ms, preset, tmp_path, meta)
            doc    = fitz.open(tmp_path)
            images = []
            for page in doc:
                mat = fitz.Matrix(1.5, 1.5)   # ~108 dpi
                pix = page.get_pixmap(matrix=mat, alpha=False)
                b64 = base64.b64encode(pix.tobytes('png')).decode()
                images.append(f'data:image/png;base64,{b64}')
            doc.close()
            return jsonify({'ok': True, 'images': images})
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        logging.error('preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})


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
        'format':      form.get('fmt', 'pdf'),
        'include_toc': form.get('include_toc') == '1',
        'smartquotes': form.get('smartquotes') == '1',
        'dedication':     form.get('dedication', '').strip(),
        'epigraph':       form.get('epigraph', '').strip(),
        'acknowledgments': form.get('acknowledgments', '').strip(),
        'about_author':   form.get('about_author', '').strip(),
        'also_by':        form.get('also_by', '').strip(),
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
            'format':      form.get('format', proj.get('format', 'pdf')),
            'include_toc': 'include_toc' in form,
            'smartquotes': 'smartquotes' in form,
            'dedication':     form.get('dedication', '').strip(),
            'epigraph':       form.get('epigraph', '').strip(),
            'acknowledgments': form.get('acknowledgments', '').strip(),
            'about_author':   form.get('about_author', '').strip(),
            'also_by':        form.get('also_by', '').strip(),
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

    meta = {
        'title':            proj.get('title', ''),
        'subtitle':         proj.get('subtitle', ''),
        'author':           proj.get('author', ''),
        'year':             proj.get('year', '') or str(datetime.now().year),
        'publisher':        proj.get('publisher', ''),
        'front_matter':     proj.get('front_matter', 'full'),
        'right_hand_starts': proj.get('right_hand_starts', True),
        'cover_image':   cover_path,
        'cover_overlay': proj.get('cover_overlay', False),
        'cover_color':   proj.get('cover_color', 'light'),
        'include_toc':   proj.get('include_toc', False),
        'smartquotes':   proj.get('smartquotes', True),
        'dedication':     proj.get('dedication', ''),
        'epigraph':       proj.get('epigraph', ''),
        'acknowledgments': proj.get('acknowledgments', ''),
        'about_author':   proj.get('about_author', ''),
        'also_by':        proj.get('also_by', ''),
    }
    ms_parsed = manuscript.parse_markdown(raw, smartquotes=meta.get('smartquotes', True))
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base  = slugify(meta['title'] or proj.get('name', 'book'))
    fmt   = proj.get('format', 'pdf')

    out_name     = ''
    epub_name    = ''
    build_result = None
    page_count   = 0

    if fmt in ('pdf', 'both'):
        out_name = f'{base}-{stamp}.pdf'
        try:
            build_result = engine.build_pdf(ms_parsed, preset, os.path.join(OUT_DIR, out_name), meta)
            page_count   = build_result['page_count']
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

    spec      = print_spec(page_count, preset) if page_count else None
    preflight = _preflight(build_result, preset, page_count) if build_result else None
    chapters  = len(ms_parsed['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=proj['preset'],
                           chapters=chapters, ms_path='', ms_type=ms_type,
                           cover_path=cover_path, from_project=pid, fmt=fmt,
                           spec=spec, preflight=preflight)


@app.route('/project/<pid>/continuity', methods=['POST'])
def project_continuity(pid):
    proj = load_project(pid)

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

    parsed = manuscript.parse_markdown(raw, smartquotes=proj.get('smartquotes', True))

    issues_t1 = checker.run_tier1(parsed)

    api_key   = os.environ.get('ANTHROPIC_API_KEY', '')
    issues_t2 = checker.run_tier2(parsed, api_key) if api_key else []

    return render_template('continuity_result.html',
                           proj=proj, pid=pid,
                           issues_t1=issues_t1,
                           issues_t2=issues_t2,
                           api_enabled=bool(api_key))


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
