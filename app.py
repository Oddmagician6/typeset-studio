"""Typeset Studio - local web app.

Run:  python app.py   (a browser tab opens at http://127.0.0.1:5050)

This is a single-user tool meant to run on your own machine. Presets live as
plain JSON files in ./presets so you can clone one per customer and tweak it.
"""

import io
import os
import re
import sys
import json
import base64
import shutil
import logging
import tempfile
import threading
import traceback
import webbrowser
import contextlib
from datetime import datetime

# Verbose in development; quiet in a frozen/installed build (the packaged app
# shows a console window, so keep it to warnings/errors there).
logging.basicConfig(
    level=logging.WARNING if getattr(sys, 'frozen', False) else logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s')

from flask import (Flask, request, redirect, url_for, render_template,
                   send_from_directory, abort, flash, jsonify, Response)
from werkzeug.utils import secure_filename

import engine
import epub
import manuscript
import checker

HERE = os.path.dirname(os.path.abspath(__file__))
IS_FROZEN = getattr(sys, 'frozen', False)


def resource_path(*parts):
    """Path to a read-only bundled asset (works under PyInstaller and in dev)."""
    base = getattr(sys, '_MEIPASS', HERE)
    return os.path.join(base, *parts)


def _user_data_root():
    """Writable per-user data directory.

    In dev (running from source) this is the repo folder, so behaviour and any
    existing data are unchanged. When frozen into an installed app it is a
    per-user app-data folder, because the install location is read-only.
    """
    if not IS_FROZEN:
        return HERE
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'Typeset Studio')


DATA_DIR = _user_data_root()

# read-only bundled assets
TEMPLATE_DIR = resource_path('templates')
STATIC_DIR   = resource_path('static')
SAMPLE       = resource_path('sample', 'sample.md')

# writable, user-editable data — presets/covers/fonts are edited in-app, so they
# live under DATA_DIR (seeded from the bundled defaults on first run), not in the
# read-only install location.
PRESET_DIR    = os.path.join(DATA_DIR, 'presets')
COVER_DIR     = os.path.join(DATA_DIR, 'covers')
COVER_ASSET_DIR = os.path.join(COVER_DIR, 'assets')   # background art + emblems/logos
FONT_DIR      = os.path.join(DATA_DIR, 'fonts')
FIGURE_DIR    = os.path.join(DATA_DIR, 'figures')     # interior illustrations
OUT_DIR       = os.path.join(DATA_DIR, 'out')
UPLOAD_DIR    = os.path.join(DATA_DIR, 'uploads')
PROJECT_DIR   = os.path.join(DATA_DIR, 'projects')
PROJECT_MS_DIR = os.path.join(PROJECT_DIR, 'manuscripts')
COVER_THUMB_DIR = os.path.join(OUT_DIR, '_cover_thumbs')   # cached gallery-picker tiles
PROJECT_THUMB_DIR = os.path.join(OUT_DIR, '_project_thumbs')  # cached project cards (page 1 of last PDF)
for d in (PRESET_DIR, COVER_DIR, COVER_ASSET_DIR, FONT_DIR, FIGURE_DIR, OUT_DIR, UPLOAD_DIR,
          PROJECT_DIR, PROJECT_MS_DIR, COVER_THUMB_DIR, PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)


def _seed_defaults():
    """First-run seeding: copy bundled default presets/covers/fonts into the
    user data dir when a file is missing there. No-op in dev, where the bundled
    and data locations are the same folder."""
    for name in ('presets', 'covers', 'fonts'):
        src = resource_path(name)
        dst = os.path.join(DATA_DIR, name)
        if os.path.abspath(src) == os.path.abspath(dst) or not os.path.isdir(src):
            continue
        for fn in os.listdir(src):
            s, d = os.path.join(src, fn), os.path.join(dst, fn)
            if os.path.isfile(s) and not os.path.exists(d):
                try:
                    shutil.copy2(s, d)
                except OSError:
                    pass


_seed_defaults()

# the engine resolves font (and scene-break ornament) filenames against the same
# writable font library, and cover-art assets against the cover asset dir
engine.FONT_DIR = FONT_DIR
engine.COVER_ASSET_DIR = COVER_ASSET_DIR
engine.FIGURE_DIR = FIGURE_DIR
epub.FIGURE_DIR = FIGURE_DIR
manuscript.FIGURE_DIR = FIGURE_DIR    # where .docx images are extracted to

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
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

# Per-retailer print-wrap presets. Bleed and the spine-text minimum are the
# differences that actually change the exported wrap; paper calipers (spine
# thickness) are standard by weight and stay in _PAPER. Always verify against
# the retailer's own downloadable cover template for a given trim.
WRAP_RETAILERS = {
    'kdp': {
        'label': 'Amazon KDP', 'bleed': 0.125, 'spine_text_min': 100,
        'note': 'KDP allows spine text at 100+ pages · 0.125" bleed. '
                'Confirm spine width with KDP’s cover template for your trim.',
    },
    'ingramspark': {
        'label': 'IngramSpark', 'bleed': 0.125, 'spine_text_min': 48,
        'note': 'IngramSpark perfect-bound spine text from ~48 pages · 0.125" bleed. '
                'Download IngramSpark’s cover template to confirm the spine.',
    },
    'generic': {
        'label': 'Generic / other POD', 'bleed': 0.125, 'spine_text_min': 80,
        'note': 'General POD defaults · 0.125" bleed. Verify bleed, spine, and safe '
                'margins against your printer’s template.',
    },
}


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
    'poem': {'font_size': 0, 'line_leading': 1.32, 'indent': 0.5,
             'runover_indent': 0.28, 'stanza_spacing': 9.0, 'space_around': 14.0,
             'align': 'left', 'title_size': 0, 'title_style': 'italic',
             'title_space': 8.0},
    'figure': {'width': 0.8, 'align': 'center', 'max_height': 0.8,
               'space_around': 12.0, 'caption_size': 0, 'caption_style': 'italic',
               'caption_align': 'center', 'caption_gap': 5.0},
    'scene_break': {'type': 'glyph', 'glyph': '* * *', 'size': 11.0, 'gap': 9.0, 'image': ''},
    'running_head': {'show': True, 'caps': True, 'size': 8.5, 'gap': 0.28},
    'folio': {'show': True, 'position': 'outer', 'size': 9.5, 'gap': 0.42,
              'hide_on_opener': True},
}


COVER_DEFAULTS = {
    'name': 'Untitled cover', 'description': '',
    'fonts': {'display': 'Book-Bold.ttf', 'serif': 'Book-Regular.ttf',
              'italic': 'Book-Italic.ttf'},
    'palette': {'bg_top': '#101a29', 'bg_bottom': '#080d15', 'gold': '#c6a866',
                'teal': '#5fb2b2', 'ink': '#ece3d0', 'muted': '#8b93a3'},
    'border': {'color': 'gold', 'inset': 0.42, 'gap': 0.055, 'line': 1.0,
               'corner': 0.5, 'corner_line': 1.3},
    'collection': {'size': 12.5, 'tracking': 3.4, 'color': 'gold',
                   'top': 0.70, 'bottom': 0.115},
    'kicker': {'size': 11, 'tracking': 0.4, 'color': 'muted', 'y': 0.665},
    'title': {'size': 40, 'leading': 46, 'tracking': 0.6, 'color': 'gold', 'y': 0.585},
    'accent': {'size': 21, 'tracking': 1.4, 'color': 'teal', 'gap': 0.008},
    'ornament': {'color': 'gold', 'size': 2.4, 'spacing': 9, 'rule': 0.8,
                 'rule_len': 0.8, 'gap': 0.05},
    'epigraph': {'size': 10.5, 'leading': 15, 'tracking': 0.2, 'color': 'muted',
                 'width': 0.62, 'top': 0.375},
    'studio': {'size': 8.5, 'tracking': 2.4, 'color': 'muted', 'y': 0.088},
    # --- enrichment (all optional, backward-compatible) ---
    'design': 'classic-frame',                   # classic-frame | photographic (design family)
    'layout': 'centered',                        # centered | top | bottom | band
    'background': {'image': '', 'vignette': 0.0,
                   'overlay': {'color': 'bg_bottom', 'opacity': 0.0}},
    'panel': {'enabled': False, 'color': 'bg_bottom', 'opacity': 0.55,
              'top': 0.66, 'bottom': 0.34},      # translucent title panel
    'emblems': [],                               # positioned logo/badge slots
}

# cover design families (front-cover renderer selected by the template's `design` key)
COVER_DESIGNS = ['classic-frame', 'photographic', 'typographic', 'geometric', 'vintage',
                 'minimal', 'stripe', 'postcard']

# gallery categories: templates are grouped by their design family, in this order, each
# with a display label + one-line blurb. Any template whose `design` isn't a known family
# falls under Classic Frame. (key, label, blurb)
COVER_CATEGORIES = [
    ('classic-frame', 'Classic Frame', 'Ornamented border, centred title'),
    ('photographic',  'Photographic',  'Full-bleed cover art'),
    ('typographic',   'Typographic',   'Type-forward, no frame'),
    ('geometric',     'Geometric',     'Flat colour blocks'),
    ('vintage',       'Vintage',       'Retro paperback'),
    ('minimal',       'Minimal',       'Quiet, lots of whitespace'),
    ('stripe',        'Stripe',        'Side colour band, editorial'),
    ('postcard',      'Postcard',      'Framed inset art'),
]
COVER_LAYOUTS = ['centered', 'top', 'bottom', 'band']
# palette keys an image overlay / panel may tint with (in addition to the 4 accents)
COVER_FILL_KEYS = ['bg_bottom', 'bg_top', 'ink', 'gold', 'teal', 'muted']
EMBLEM_SLOTS = ['top-center', 'top-left', 'top-right',
                'center', 'bottom-center', 'bottom-left', 'bottom-right']

# palette keys an element's colour may reference (the editor offers these as a dropdown)
COVER_PALETTE_KEYS = ['gold', 'teal', 'ink', 'muted']


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


def group_cover_templates(items):
    """Group listed cover templates by design family for the gallery picker, in
    COVER_CATEGORIES order. Returns [{key, label, blurb, tiles:[...]}]; empty groups
    drop out; an unknown `design` lands under Classic Frame. `tiles` (not `items`) so
    Jinja `g.tiles` never collides with dict.items()."""
    known = {k for k, _, _ in COVER_CATEGORIES}
    buckets = {k: [] for k, _, _ in COVER_CATEGORIES}
    for item in items:
        d = item.get('data', {}).get('design') or 'classic-frame'
        buckets[d if d in known else 'classic-frame'].append(item)
    groups = []
    for key, label, blurb in COVER_CATEGORIES:
        tiles = sorted(buckets[key],
                       key=lambda it: (it['data'].get('name') or it['id']).lower())
        if tiles:
            groups.append({'key': key, 'label': label, 'blurb': blurb, 'tiles': tiles})
    return groups


def load_cover_template(cid):
    if not cid:
        return None
    path = os.path.join(COVER_DIR, secure_filename(cid) + '.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_cover_template(cid, data):
    path = os.path.join(COVER_DIR, secure_filename(cid) + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def unique_cover_id(base):
    cid, n = base, 2
    existing = {i['id'] for i in list_cover_templates()}
    while cid in existing:
        cid = f'{base}-{n}'
        n += 1
    return cid


# Book faces that ship with the app, each with a Regular/Bold/Italic. The shipped
# presets point at these; every one is OFL (licence texts in fonts/licenses/), so
# they may be embedded in a book. Protected from deletion/overwrite in the Fonts
# manager — deleting one would silently drop a preset back to Times.
BUILTIN_FAMILIES = ('Book',          # Libre Baskerville
                    'EBGaramond', 'Vollkorn', 'Alegreya',
                    'CrimsonPro', 'Lora', 'Spectral')
BUILTIN_FONTS = {f'{fam}-{role}.ttf'
                 for fam in BUILTIN_FAMILIES
                 for role in ('Regular', 'Bold', 'Italic')}
FONT_EXTS = ('.ttf', '.otf')


def _projects_for_wrap():
    """Summaries used by the cover editor's 'From a book' wrap picker."""
    out = []
    for item in list_projects():
        p = item['data']
        trim = _load_preset_or_default(p.get('preset', '')).get('trim', {})
        out.append({
            'id': item['id'],
            'name': p.get('name') or p.get('title') or item['id'],
            'page_count': p.get('last_page_count', ''),
            'trim_w': trim.get('w', 6.0),
            'trim_h': trim.get('h', 9.0),
            'title': p.get('title', ''),
            'author': p.get('author', ''),
            'publisher': p.get('publisher', ''),
        })
    return out


def list_fonts():
    """Embeddable faces available in fonts/, for the editors' font pickers."""
    try:
        return sorted(f for f in os.listdir(FONT_DIR)
                      if f.lower().endswith(FONT_EXTS))
    except OSError:
        return []


def _is_embeddable_font(path):
    """True if ReportLab can register the file (i.e. it will embed in a PDF)."""
    try:
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase import pdfmetrics
        pdfmetrics.registerFont(TTFont(f'_probe_{os.path.basename(path)}', path))
        return True
    except Exception:
        return False


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
        'figure': {
            'width':          _f(form, 'fig_width', 0.8),
            'align':          form.get('fig_align', 'center'),
            'max_height':     _f(form, 'fig_max_height', 0.8),
            'space_around':   _f(form, 'fig_space_around', 12.0),
            'caption_size':   _f(form, 'fig_caption_size', 0),
            'caption_style':  form.get('fig_caption_style', 'italic'),
            'caption_align':  form.get('fig_caption_align', 'center'),
            'caption_gap':    _f(form, 'fig_caption_gap', 5.0),
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


def _hexf(form, key, default):
    """Read a colour field; keep a valid #rrggbb, else fall back."""
    v = (form.get(key, '') or '').strip()
    return v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else default


def _existing_photo(form):
    """Preserve a template's advanced photographic `photo` block across a browser save.
    The editor has no per-field photo controls yet, so it round-trips the whole block as
    a hidden JSON field; absent/invalid -> {} (the renderer then uses its own defaults)."""
    raw = (form.get('photo_json') or '').strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def parse_cover_form(form):
    """Flat cover-editor form fields -> the nested covers/*.json schema."""
    d = COVER_DEFAULTS
    return {
        'name': form.get('name', '').strip() or 'Untitled cover',
        'description': form.get('description', '').strip(),
        'fonts': {
            'display': form.get('font_display', d['fonts']['display']) or d['fonts']['display'],
            'serif':   form.get('font_serif',   d['fonts']['serif'])   or d['fonts']['serif'],
            'italic':  form.get('font_italic',  d['fonts']['italic'])  or d['fonts']['italic'],
        },
        'palette': {
            'bg_top':    _hexf(form, 'pal_bg_top',    d['palette']['bg_top']),
            'bg_bottom': _hexf(form, 'pal_bg_bottom', d['palette']['bg_bottom']),
            'gold':      _hexf(form, 'pal_gold',      d['palette']['gold']),
            'teal':      _hexf(form, 'pal_teal',      d['palette']['teal']),
            'ink':       _hexf(form, 'pal_ink',       d['palette']['ink']),
            'muted':     _hexf(form, 'pal_muted',     d['palette']['muted']),
        },
        'border': {
            'color':       form.get('bd_color', 'gold'),
            'inset':       _f(form, 'bd_inset', d['border']['inset']),
            'gap':         _f(form, 'bd_gap', d['border']['gap']),
            'line':        _f(form, 'bd_line', d['border']['line']),
            'corner':      _f(form, 'bd_corner', d['border']['corner']),
            'corner_line': _f(form, 'bd_corner_line', d['border']['corner_line']),
        },
        'collection': {
            'size':     _f(form, 'col_size', d['collection']['size']),
            'tracking': _f(form, 'col_tracking', d['collection']['tracking']),
            'color':    form.get('col_color', 'gold'),
            'top':      _f(form, 'col_top', d['collection']['top']),
            'bottom':   _f(form, 'col_bottom', d['collection']['bottom']),
        },
        'kicker': {
            'size':     _f(form, 'kick_size', d['kicker']['size']),
            'tracking': _f(form, 'kick_tracking', d['kicker']['tracking']),
            'color':    form.get('kick_color', 'muted'),
            'y':        _f(form, 'kick_y', d['kicker']['y']),
        },
        'title': {
            'size':     _f(form, 'title_size', d['title']['size']),
            'leading':  _f(form, 'title_leading', d['title']['leading']),
            'tracking': _f(form, 'title_tracking', d['title']['tracking']),
            'color':    form.get('title_color', 'gold'),
            'y':        _f(form, 'title_y', d['title']['y']),
        },
        'accent': {
            'size':     _f(form, 'acc_size', d['accent']['size']),
            'tracking': _f(form, 'acc_tracking', d['accent']['tracking']),
            'color':    form.get('acc_color', 'teal'),
            'gap':      _f(form, 'acc_gap', d['accent']['gap']),
        },
        'ornament': {
            'color':    form.get('orn_color', 'gold'),
            'size':     _f(form, 'orn_size', d['ornament']['size']),
            'spacing':  _f(form, 'orn_spacing', d['ornament']['spacing']),
            'rule':     _f(form, 'orn_rule', d['ornament']['rule']),
            'rule_len': _f(form, 'orn_rule_len', d['ornament']['rule_len']),
            'gap':      _f(form, 'orn_gap', d['ornament']['gap']),
        },
        'epigraph': {
            'size':     _f(form, 'epi_size', d['epigraph']['size']),
            'leading':  _f(form, 'epi_leading', d['epigraph']['leading']),
            'tracking': _f(form, 'epi_tracking', d['epigraph']['tracking']),
            'color':    form.get('epi_color', 'muted'),
            'width':    _f(form, 'epi_width', d['epigraph']['width']),
            'top':      _f(form, 'epi_top', d['epigraph']['top']),
        },
        'studio': {
            'size':     _f(form, 'std_size', d['studio']['size']),
            'tracking': _f(form, 'std_tracking', d['studio']['tracking']),
            'color':    form.get('std_color', 'muted'),
            'y':        _f(form, 'std_y', d['studio']['y']),
        },
        'design': (form.get('design', 'classic-frame')
                   if form.get('design', 'classic-frame') in COVER_DESIGNS else 'classic-frame'),
        # advanced photographic fine-tuning (`photo` dict) is JSON-only for now; preserve
        # it verbatim if a hand-authored template carries it so a browser save won't drop it.
        'photo': _existing_photo(form),
        'layout': (form.get('layout', 'centered')
                   if form.get('layout', 'centered') in COVER_LAYOUTS else 'centered'),
        'background': {
            'image':    form.get('bg_image', '').strip(),
            'vignette': _f(form, 'bg_vignette', 0.0),
            'overlay': {
                'color':   form.get('bg_overlay_color', 'bg_bottom'),
                'opacity': _f(form, 'bg_overlay_opacity', 0.0),
            },
        },
        'panel': {
            'enabled': 'panel_enabled' in form,
            'color':   form.get('panel_color', 'bg_bottom'),
            'opacity': _f(form, 'panel_opacity', 0.55),
            'top':     _f(form, 'panel_top', 0.66),
            'bottom':  _f(form, 'panel_bottom', 0.34),
        },
        'emblems': _parse_emblems(form),
    }


def _parse_emblems(form):
    """Up to two positioned emblem slots from the flat cover form."""
    out = []
    for i in (1, 2):
        img = form.get(f'emblem{i}_image', '').strip()
        if not img:
            continue
        slot = form.get(f'emblem{i}_slot', 'top-center')
        out.append({
            'image': img,
            'slot':  slot if slot in EMBLEM_SLOTS else 'top-center',
            'w':     _f(form, f'emblem{i}_w', 0.7),
        })
    return out


# ----------------------------------------------------------------- routes
@app.context_processor
def _inject_cover_templates():
    items = list_cover_templates()
    return {'cover_templates': items,
            'cover_groups': group_cover_templates(items)}


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(resource_path(), 'app.ico',
                               mimetype='image/vnd.microsoft.icon')


@app.route('/')
def index():
    return render_template('index.html', presets=list_presets())


@app.route('/editor/new')
def editor_new():
    return render_template('editor.html', pid=None, p=DEFAULTS, is_new=True,
                           fonts=list_fonts())


@app.route('/editor/<pid>')
def editor(pid):
    return render_template('editor.html', pid=pid, p=load_preset(pid), is_new=False,
                           fonts=list_fonts())


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


# ------------------------------------------------------- cover template routes
@app.route('/covers')
def covers():
    return render_template('covers.html', covers=list_cover_templates())


@app.route('/cover/new')
def cover_new():
    return render_template('cover_editor.html', cid=None, c=COVER_DEFAULTS,
                           is_new=True, fonts=list_fonts(),
                           palette_keys=COVER_PALETTE_KEYS, fill_keys=COVER_FILL_KEYS,
                           layouts=COVER_LAYOUTS, designs=COVER_DESIGNS,
                           emblem_slots=EMBLEM_SLOTS,
                           wrap_projects=_projects_for_wrap(),
                           wrap_retailers=WRAP_RETAILERS)


@app.route('/cover/<cid>')
def cover_editor(cid):
    data = load_cover_template(cid)
    if data is None:
        abort(404)
    return render_template('cover_editor.html', cid=cid, c=data, is_new=False,
                           fonts=list_fonts(), palette_keys=COVER_PALETTE_KEYS,
                           fill_keys=COVER_FILL_KEYS, layouts=COVER_LAYOUTS,
                           designs=COVER_DESIGNS, emblem_slots=EMBLEM_SLOTS,
                           wrap_projects=_projects_for_wrap(),
                           wrap_retailers=WRAP_RETAILERS)


@app.route('/cover/save', methods=['POST'])
@app.route('/cover/save/<cid>', methods=['POST'])
def cover_save(cid=None):
    data = parse_cover_form(request.form)
    if cid is None:
        cid = unique_cover_id(slugify(data['name']))
    save_cover_template(cid, data)
    flash(f'Saved “{data["name"]}”.')
    return redirect(url_for('covers'))


@app.route('/cover/clone/<cid>', methods=['POST'])
def cover_clone(cid):
    data = load_cover_template(cid)
    if data is None:
        abort(404)
    data['name'] = data.get('name', 'Cover') + ' (copy)'
    new_id = unique_cover_id(slugify(data['name']))
    save_cover_template(new_id, data)
    flash('Created a copy you can rename and tweak.')
    return redirect(url_for('cover_editor', cid=new_id))


@app.route('/cover/delete/<cid>', methods=['POST'])
def cover_delete(cid):
    path = os.path.join(COVER_DIR, secure_filename(cid) + '.json')
    if os.path.exists(path):
        os.remove(path)
        flash('Cover template deleted.')
    return redirect(url_for('covers'))


def _cover_thumb_bytes(cid):
    """Front-cover PNG for a template, cached to disk and keyed by the JSON's mtime
    (an edit/save bumps mtime → the tile regenerates). Returns None if the template
    is missing or the rasterizer isn't available. Powers the gallery picker."""
    cid = secure_filename(cid)
    src = os.path.join(COVER_DIR, cid + '.json')
    if not cid or not os.path.exists(src):
        return None
    cache = os.path.join(COVER_THUMB_DIR, cid + '.png')
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(src):
        try:
            with open(cache, 'rb') as f:
                return f.read()
        except OSError:
            pass
    try:
        import fitz
    except ImportError:
        return None
    tpl = load_cover_template(cid)
    if tpl is None:
        return None
    preset = dict(DEFAULTS)
    preset['trim'] = {'w': 6.0, 'h': 9.0}
    meta = {
        'title': 'The Salt Road', 'author': 'Ellinor Vale',
        'year': '2026', 'publisher': 'Studio',
        'front_matter': 'none', 'right_hand_starts': False, 'smartquotes': True,
        'cover_mode': 'designed', 'cover_template': cid, 'cover_template_data': tpl,
        'cover_collection': 'Sample Series', 'cover_kicker': '',
        'cover_accent': '', 'cover_epigraph': '', 'cover_studio': 'Studio',
        'cover_image': '', 'cover_overlay': False, 'cover_color': 'light',
        'dedication': '', 'epigraph': '', 'acknowledgments': '',
        'about_author': '', 'also_by': '',
    }
    ms = manuscript.parse_markdown(PREVIEW_SAMPLE, smartquotes=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        engine.build_pdf(ms, preset, tmp_path, meta)
        doc = fitz.open(tmp_path)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.9, 0.9), alpha=False)
        png = pix.tobytes('png')
        doc.close()
        try:
            with open(cache, 'wb') as f:
                f.write(png)
        except OSError:
            pass
        return png
    except Exception:
        logging.exception('cover thumbnail build failed for %s', cid)
        return None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.route('/cover/thumb/<cid>.png')
def cover_thumb(cid):
    """Cached front-cover thumbnail for the gallery picker."""
    png = _cover_thumb_bytes(cid)
    if png is None:
        abort(404)
    # revalidate each load (cheap on localhost) so an edited template shows fresh art
    return Response(png, mimetype='image/png',
                    headers={'Cache-Control': 'no-cache'})


EPUB_COVER_H = 2560   # px; the long edge KDP asks for on an ebook cover


@contextlib.contextmanager
def _epub_cover(preset, meta):
    """Yield a meta whose ``cover_image`` an EPUB build can use for a designed cover.

    ``epub.py`` is deliberately stdlib-only and image-only, so a book set with a
    designed cover (``cover_mode == 'designed'``) used to lose its cover in the
    ebook entirely. Here page 1 of that cover is rasterised to a temp JPEG and the
    yielded meta points at it; the temp files are removed on exit. Same PyMuPDF
    path as ``_cover_thumb_bytes`` (#34), run over a **stub** manuscript so we
    typeset one cover page instead of rebuilding the whole book (which a TOC would
    make a two-pass build on top).

    Any failure — no PyMuPDF/Pillow, no template, a render error — yields the meta
    unchanged, so the EPUB still builds, coverless, exactly as it did before.
    """
    if meta.get('cover_mode') != 'designed' or not meta.get('cover_template_data'):
        yield meta
        return
    try:
        import fitz
        from PIL import Image
    except ImportError:
        yield meta
        return

    pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(pdf_fd)
    jpg_fd, jpg_path = tempfile.mkstemp(suffix='.jpg')
    os.close(jpg_fd)
    try:
        try:
            cover_meta = dict(meta)
            cover_meta.update(front_matter='none', include_toc=False,
                              right_hand_starts=False)
            stub = manuscript.parse_markdown('# Cover\n\nCover.', smartquotes=False)
            engine.build_pdf(stub, preset, pdf_path, cover_meta)

            doc  = fitz.open(pdf_path)
            page = doc[0]
            scale = EPUB_COVER_H / page.rect.height if page.rect.height else 1.0
            png = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                  alpha=False).tobytes('png')
            doc.close()
            # JPEG, else a photographic-family cover makes a multi-megabyte ebook.
            Image.open(io.BytesIO(png)).convert('RGB').save(
                jpg_path, 'JPEG', quality=88, optimize=True)
            img_path = jpg_path
        except Exception:
            logging.exception('designed cover for EPUB failed; building without one')
            img_path = ''

        if img_path:
            out = dict(meta)
            out['cover_image'] = img_path
            yield out
        else:
            yield meta
    finally:
        for p in (pdf_path, jpg_path):
            try:
                os.remove(p)
            except OSError:
                pass


def project_last_pdf_path(data):
    """Absolute path to a project's most recent built PDF, or None if it has none."""
    last_pdf = (data or {}).get('last_pdf', '')
    if not last_pdf:
        return None
    path = os.path.join(OUT_DIR, os.path.basename(last_pdf))
    return path if os.path.exists(path) else None


def _project_thumb_bytes(pid):
    """Page-1 thumbnail of a project's last built PDF (its cover, or the first
    front-matter page), cached to disk and keyed by the PDF's mtime. Returns None
    when the project has never been built or the rasteriser is unavailable."""
    pid = secure_filename(pid)
    src = os.path.join(PROJECT_DIR, pid + '.json')
    if not pid or not os.path.exists(src):
        return None
    try:
        with open(src, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    pdf_path = project_last_pdf_path(data)
    if not pdf_path:
        return None
    cache = os.path.join(PROJECT_THUMB_DIR, pid + '.png')
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(pdf_path):
        try:
            with open(cache, 'rb') as f:
                return f.read()
        except OSError:
            pass
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(pdf_path)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.7, 0.7), alpha=False)
        png = pix.tobytes('png')
        doc.close()
        try:
            with open(cache, 'wb') as f:
                f.write(png)
        except OSError:
            pass
        return png
    except Exception:
        logging.exception('project thumbnail build failed for %s', pid)
        return None


@app.route('/project/<pid>/thumb.png')
def project_thumb(pid):
    """Cached page-1 thumbnail for a project card."""
    png = _project_thumb_bytes(pid)
    if png is None:
        abort(404)
    return Response(png, mimetype='image/png',
                    headers={'Cache-Control': 'no-cache'})


@app.route('/cover/preview', methods=['POST'])
def cover_preview():
    try:
        import fitz
    except ImportError:
        return jsonify({'ok': False,
                        'error': 'pymupdf not installed - run: pip install pymupdf'})
    try:
        form = request.form
        preset = dict(DEFAULTS)
        preset['trim'] = {'w': _f(form, 'prev_w', 6.0), 'h': _f(form, 'prev_h', 9.0)}
        meta = {
            'title':  form.get('prev_title', 'What the Monk Saw'),
            'author': form.get('prev_author', 'Matthias Moore'),
            'year': '2026', 'publisher': form.get('prev_studio', 'Edenfall Fiction'),
            'front_matter': 'none', 'right_hand_starts': False,
            'smartquotes': True,
            'cover_mode': 'designed',
            'cover_template': 'preview',
            'cover_template_data': parse_cover_form(form),
            'cover_collection': form.get('prev_collection', 'Edenfall Fiction'),
            'cover_kicker': form.get('prev_kicker', ''),
            'cover_accent': form.get('prev_accent', ''),
            'cover_epigraph': form.get('prev_epigraph', ''),
            'cover_studio': form.get('prev_studio', 'Ashforge Studio'),
            'cover_image': '', 'cover_overlay': False, 'cover_color': 'light',
            'dedication': '', 'epigraph': '', 'acknowledgments': '',
            'about_author': '', 'also_by': '',
        }
        ms = manuscript.parse_markdown(PREVIEW_SAMPLE, smartquotes=True)
        fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        try:
            engine.build_pdf(ms, preset, tmp_path, meta)
            doc = fitz.open(tmp_path)
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            b64 = base64.b64encode(pix.tobytes('png')).decode()
            doc.close()
            return jsonify({'ok': True, 'image': f'data:image/png;base64,{b64}'})
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        logging.error('cover preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})


IMAGE_EXTS = ('.jpg', '.jpeg', '.png')


@app.route('/cover/asset/upload', methods=['POST'])
def cover_asset_upload():
    """Store a cover-art asset (background image or emblem/logo) in the asset
    library and return its filename for the template to reference."""
    f = request.files.get('asset')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No file provided.'})
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in IMAGE_EXTS:
        return jsonify({'ok': False, 'error': 'Use a .jpg or .png image.'})
    base = secure_filename(os.path.splitext(f.filename)[0]) or 'asset'
    fn, dest, i = base + ext, os.path.join(COVER_ASSET_DIR, base + ext), 1
    while os.path.exists(dest):
        fn = f'{base}-{i}{ext}'
        dest = os.path.join(COVER_ASSET_DIR, fn)
        i += 1
    f.save(dest)
    try:                                             # reject anything Pillow can't read
        from PIL import Image
        Image.open(dest).verify()
    except Exception:
        try:
            os.remove(dest)
        except OSError:
            pass
        return jsonify({'ok': False, 'error': 'That file is not a readable image.'})
    return jsonify({'ok': True, 'filename': fn})


def _save_back_image(f):
    """Save an uploaded back-cover image (photo/logo) to a temp file. Returns path or None."""
    if not f or not f.filename:
        return None
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png'):
        return None
    fd, tmp = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    f.save(tmp)
    return tmp


def _wrap_from_form(form, out_path, back_image=None):
    """Build a full print wrap (back + spine + front + bleed) from the cover editor form."""
    tpl = parse_cover_form(form)
    interior = engine.register_fonts(DEFAULTS)
    cf = engine._register_cover_fonts(tpl, interior)
    try:
        pages = max(int(_f(form, 'wrap_pages', 200)), 0)
    except (TypeError, ValueError):
        pages = 200
    paper = form.get('wrap_paper', 'white')
    ppi = _PAPER.get(paper, _PAPER['white'])['ppi']
    rc = WRAP_RETAILERS.get(form.get('wrap_retailer', 'kdp'), WRAP_RETAILERS['kdp'])
    dims = {
        'trim_w': _f(form, 'wrap_trim_w', 6.0),
        'trim_h': _f(form, 'wrap_trim_h', 9.0),
        'spine_w': pages * ppi,
        'bleed':  _f(form, 'wrap_bleed', rc['bleed']),
        'pages':  pages,
        'spine_text_min': rc['spine_text_min'],
    }
    meta = {
        'title':  form.get('prev_title', ''),
        'author': form.get('prev_author', ''),
        'publisher': form.get('prev_studio', ''),
        'cover_collection': form.get('prev_collection', ''),
        'cover_kicker':     form.get('prev_kicker', ''),
        'cover_accent':     form.get('prev_accent', ''),
        'cover_epigraph':   form.get('prev_epigraph', ''),
        'cover_studio':     form.get('prev_studio', ''),
        'cover_blurb':      form.get('wrap_blurb', ''),
        'cover_back_image':   back_image or '',
        'cover_back_image_w': _f(form, 'wrap_back_w', 1.5),
        'cover_back_image_y': _f(form, 'wrap_back_y', 0.4),
    }
    guides = form.get('wrap_guides') == '1'
    res = engine.build_cover_wrap(tpl, cf, meta, dims, out_path, guides=guides)
    return res, dims


@app.route('/cover/wrap', methods=['POST'])
def cover_wrap():
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    back = _save_back_image(request.files.get('wrap_back_image'))
    try:
        _wrap_from_form(request.form, tmp, back_image=back)
        with open(tmp, 'rb') as f:
            data = f.read()
    finally:
        for p in (tmp, back):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    name = slugify(request.form.get('name', 'cover')) + '-wrap.pdf'
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})


@app.route('/cover/wrap/preview', methods=['POST'])
def cover_wrap_preview():
    try:
        import fitz
    except ImportError:
        return jsonify({'ok': False,
                        'error': 'pymupdf not installed - run: pip install pymupdf'})
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    back = _save_back_image(request.files.get('wrap_back_image'))
    try:
        res, dims = _wrap_from_form(request.form, tmp, back_image=back)
        doc = fitz.open(tmp)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.1, 1.1), alpha=False)
        b64 = base64.b64encode(pix.tobytes('png')).decode()
        doc.close()
        spine_txt = 'spine text on' if res.get('spine_text') else 'spine text off (too few pages)'
        info = (f"{dims['trim_w']:g}×{dims['trim_h']:g}\" · spine {res['spine_w']:g}\" · "
                f"full {res['wrap_w']:g}×{res['wrap_h']:g}\" · {spine_txt}")
        return jsonify({'ok': True, 'image': f'data:image/png;base64,{b64}', 'info': info})
    except Exception as exc:
        logging.error('wrap preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})
    finally:
        for p in (tmp, back):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# ------------------------------------------------------------- font manager
@app.route('/fonts')
def fonts_page():
    items = [{'name': f, 'builtin': f in BUILTIN_FONTS} for f in list_fonts()]
    return render_template('fonts.html', fonts=items)


@app.route('/fonts/upload', methods=['POST'])
def fonts_upload():
    saved, skipped = [], []
    for up in request.files.getlist('fonts'):
        if not up or not up.filename:
            continue
        fn = secure_filename(up.filename)
        if not fn.lower().endswith(FONT_EXTS):
            skipped.append(f'{up.filename} (not a .ttf/.otf)')
            continue
        if fn in BUILTIN_FONTS:
            skipped.append(f'{fn} (built-in name is protected)')
            continue
        dest = os.path.join(FONT_DIR, fn)
        up.save(dest)
        if _is_embeddable_font(dest):
            saved.append(fn)
        else:
            try:
                os.remove(dest)
            except OSError:
                pass
            skipped.append(f'{fn} (not an embeddable font — OTF/CFF outlines aren’t supported)')
    if saved:
        flash('Added ' + ', '.join(saved) + '.')
    if skipped:
        flash('Skipped ' + '; '.join(skipped) + '.')
    if not saved and not skipped:
        flash('Choose one or more .ttf or .otf files to upload.')
    return redirect(url_for('fonts_page'))


@app.route('/fonts/delete/<name>', methods=['POST'])
def fonts_delete(name):
    fn = secure_filename(name)
    if fn in BUILTIN_FONTS:
        flash('That font ships with the app and can’t be deleted.')
        return redirect(url_for('fonts_page'))
    path = os.path.join(FONT_DIR, fn)
    if os.path.exists(path) and fn.lower().endswith(FONT_EXTS):
        os.remove(path)
        flash(f'Removed {fn}. Styles or covers that referenced it fall back to Times.')
    return redirect(url_for('fonts_page'))


def _flash_import(rep):
    """Tell the user what came out of a Word file — and what didn't.

    Silently dropping half a manuscript is the worst failure mode an importer
    has, so both halves of the summary are surfaced.
    """
    got, lost = manuscript.import_summary(rep)
    if got:
        flash(f'Imported from Word: {got}.')
    if lost:
        flash(f'Note: {lost}.')


FIGURE_EXTS = ('.jpg', '.jpeg', '.png', '.gif')


def list_figures():
    """Illustrations available to `~~~ figure src="…"`, newest first."""
    try:
        names = [f for f in os.listdir(FIGURE_DIR)
                 if f.lower().endswith(FIGURE_EXTS)]
    except OSError:
        return []
    names.sort(key=lambda f: os.path.getmtime(os.path.join(FIGURE_DIR, f)),
               reverse=True)
    return names


def _save_figure(up):
    """Validate and store one uploaded illustration. Returns (filename, error)."""
    fn = secure_filename(up.filename or '')
    if not fn.lower().endswith(FIGURE_EXTS):
        return None, f'{up.filename} (not a .jpg/.png/.gif)'
    dest = os.path.join(FIGURE_DIR, fn)
    up.save(dest)
    try:                                   # must actually be an image
        from PIL import Image
        with Image.open(dest) as im:
            im.verify()
    except Exception:
        try:
            os.remove(dest)
        except OSError:
            pass
        return None, f'{fn} (not a readable image)'
    return fn, None


@app.route('/figures')
def figures():
    items = []
    for f in list_figures():
        path = os.path.join(FIGURE_DIR, f)
        w = h = 0
        try:
            from PIL import Image
            with Image.open(path) as im:
                w, h = im.size
        except Exception:
            pass
        items.append({'name': f, 'w': w, 'h': h,
                      'kb': os.path.getsize(path) / 1024.0})
    return render_template('figures.html', figures=items)


@app.route('/figures/upload', methods=['POST'])
def figures_upload():
    saved, skipped = [], []
    for up in request.files.getlist('figures'):
        if not up or not up.filename:
            continue
        fn, err = _save_figure(up)
        (saved if fn else skipped).append(fn or err)
    # XHR (the manuscript editor's Figure button) wants the filename back
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify({'ok': bool(saved), 'saved': saved, 'skipped': skipped})
    if saved:
        flash('Added ' + ', '.join(saved) + '.')
    if skipped:
        flash('Skipped ' + '; '.join(skipped) + '.')
    if not saved and not skipped:
        flash('Choose one or more images to upload.')
    return redirect(url_for('figures'))


@app.route('/figures/delete/<name>', methods=['POST'])
def figures_delete(name):
    fn = secure_filename(name)
    path = os.path.join(FIGURE_DIR, fn)
    if os.path.exists(path) and fn.lower().endswith(FIGURE_EXTS):
        os.remove(path)
        flash(f'Removed {fn}. Figures referencing it will show a "missing image" box.')
    return redirect(url_for('figures'))


@app.route('/figures/file/<name>')
def figure_file(name):
    """Serve an illustration, for the manager page and the editor's rich view."""
    return send_from_directory(FIGURE_DIR, secure_filename(name))


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
                rep = {}
                raw = manuscript.import_docx(dest, report=rep)
                _flash_import(rep)
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
        'contributors':   form.get('contributors', '').strip(),
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
            with _epub_cover(preset, meta) as emeta:
                epub.build_epub(ms, preset, os.path.join(OUT_DIR, epub_name), emeta)
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


# How much of the real book the "Set a book" preview renders. Only the first few
# chapters are built (so a 400-page manuscript still previews in a second or two),
# and only the first handful of rendered pages are rasterised and returned.
PREVIEW_MAX_CHAPTERS = 2
PREVIEW_MAX_PAGES    = 8


@app.route('/generate/preview', methods=['POST'])
def generate_preview():
    """Render the user's *actual* manuscript + settings to page images.

    Mirrors /generate's reading of the compose form, but persists nothing:
    uploads and the built PDF go to temp files that are deleted before returning.
    """
    try:
        import fitz
    except ImportError:
        return jsonify({'ok': False,
                        'error': 'PDF preview needs pymupdf — run: pip install pymupdf'})

    tmp_files = []
    try:
        form = request.form
        pid  = form.get('preset')
        if not pid:
            return jsonify({'ok': False, 'error': 'Pick a style first.'})
        preset = load_preset(pid)

        # ---- manuscript source (upload / paste / sample), nothing persisted ----
        raw = None
        up = request.files.get('manuscript')
        if up and up.filename:
            fn = secure_filename(up.filename)
            fd, tmp_ms = tempfile.mkstemp(suffix='_' + fn)
            os.close(fd)
            up.save(tmp_ms)
            tmp_files.append(tmp_ms)
            if fn.lower().endswith('.docx'):
                try:
                    raw = manuscript.import_docx(tmp_ms)
                except ModuleNotFoundError:
                    return jsonify({'ok': False,
                                    'error': 'python-docx is not installed. Run: pip install python-docx'})
                except Exception as exc:
                    return jsonify({'ok': False, 'error': f'Could not read the Word file: {exc}'})
            else:
                raw = open(tmp_ms, encoding='utf-8', errors='replace').read()
        elif form.get('pasted', '').strip():
            raw = form['pasted']
        elif form.get('use_sample'):
            raw = open(SAMPLE, encoding='utf-8').read()

        if not raw:
            return jsonify({'ok': False,
                            'error': 'Add a manuscript first — upload a file, paste text, or tick the sample.'})

        # ---- cover (designed template or uploaded art), same as /generate ----
        cover_mode = form.get('cover_mode', 'none')
        cover_path = ''
        cov = request.files.get('cover')
        if cov and cov.filename:
            cfn = secure_filename(cov.filename)
            fd, tmp_cov = tempfile.mkstemp(suffix='_' + cfn)
            os.close(fd)
            cov.save(tmp_cov)
            tmp_files.append(tmp_cov)
            cover_path = tmp_cov
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
            'contributors':   form.get('contributors', '').strip(),
            'about_author':   form.get('about_author', '').strip(),
            'also_by':        form.get('also_by', '').strip(),
        }

        ms = manuscript.parse_markdown(raw, smartquotes=meta['smartquotes'])
        chapters_total = len(ms['chapters'])
        truncated = chapters_total > PREVIEW_MAX_CHAPTERS
        if truncated:
            ms = {'chapters': ms['chapters'][:PREVIEW_MAX_CHAPTERS]}

        fd, tmp_pdf = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        tmp_files.append(tmp_pdf)
        engine.build_pdf(ms, preset, tmp_pdf, meta)

        doc = fitz.open(tmp_pdf)
        built_pages = doc.page_count
        images = []
        for i, page in enumerate(doc):
            if i >= PREVIEW_MAX_PAGES:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)  # ~144 dpi
            b64 = base64.b64encode(pix.tobytes('png')).decode()
            images.append(f'data:image/png;base64,{b64}')
        doc.close()

        return jsonify({
            'ok': True,
            'images': images,
            'shown': len(images),
            'built_pages': built_pages,
            'chapters_total': chapters_total,
            'chapters_shown': len(ms['chapters']),
            'truncated': truncated,
        })
    except Exception as exc:
        logging.error('generate preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})
    finally:
        for f in tmp_files:
            try:
                os.remove(f)
            except OSError:
                pass


# ----------------------------------------------------------------- project routes
@app.route('/projects')
def projects():
    preset_map = {p['id']: p['data'] for p in list_presets()}
    items = list_projects()
    for it in items:
        it['has_thumb'] = project_last_pdf_path(it['data']) is not None
    return render_template('projects.html', projects=items,
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
        'cover_mode':     form.get('cover_mode', 'none'),
        'cover_template': form.get('cover_template', ''),
        'cover_collection': form.get('cover_collection', '').strip(),
        'cover_kicker':     form.get('cover_kicker', '').strip(),
        'cover_accent':     form.get('cover_accent', '').strip(),
        'cover_epigraph':   form.get('cover_epigraph', '').strip(),
        'cover_studio':     form.get('cover_studio', '').strip(),
        'format':      form.get('fmt', 'pdf'),
        'include_toc': form.get('include_toc') == '1',
        'smartquotes': form.get('smartquotes') == '1',
        'dedication':     form.get('dedication', '').strip(),
        'epigraph':       form.get('epigraph', '').strip(),
        'acknowledgments': form.get('acknowledgments', '').strip(),
        'contributors':   form.get('contributors', '').strip(),
        'about_author':   form.get('about_author', '').strip(),
        'also_by':        form.get('also_by', '').strip(),
        'manuscript_file': ms_file,
        'manuscript_type': ms_type,
        'cover_file': cover_file,
        'last_pdf': form.get('last_pdf', ''),
        'last_epub': form.get('last_epub', ''),
        'last_page_count': form.get('page_count', ''),
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
            'contributors':   form.get('contributors', '').strip(),
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
            'cover_mode':       form.get('cover_mode', 'none'),
            'cover_template':   form.get('cover_template', ''),
            'cover_collection': form.get('cover_collection', '').strip(),
            'cover_kicker':     form.get('cover_kicker', '').strip(),
            'cover_accent':     form.get('cover_accent', '').strip(),
            'cover_epigraph':   form.get('cover_epigraph', '').strip(),
            'cover_studio':     form.get('cover_studio', '').strip(),
            'updated':          datetime.now().isoformat(timespec='seconds'),
        })
        save_project_file(pid, proj)
        flash('Project updated.')
        return redirect(url_for('projects'))

    return render_template('project_edit.html', pid=pid, proj=proj, presets=presets)


# ---------------------------------------------------------- manuscript editor
STARTER_DRAFT = ("# Chapter One\n\n"
                 "Your story starts here. Delete this line and begin writing.\n\n"
                 "Use a blank line between paragraphs. Mark emphasis with *italics* or "
                 "**bold**, start a new chapter with a line like `# Chapter Two`, and drop a "
                 "scene break with `* * *` on its own line.\n")


def _project_manuscript_text(proj):
    """Return a project's manuscript as editable Markdown text ('' if none)."""
    ms_type = proj.get('manuscript_type', 'file')
    ms_file = proj.get('manuscript_file', '')
    if ms_type == 'sample':
        try:
            return open(SAMPLE, encoding='utf-8').read()
        except OSError:
            return ''
    if ms_file:
        path = os.path.join(PROJECT_MS_DIR, ms_file)
        if os.path.exists(path):
            if ms_file.lower().endswith('.docx'):
                try:
                    rep = {}
                    text = manuscript.import_docx(path, report=rep)
                    _flash_import(rep)     # only route calling this renders a page
                    return text
                except Exception:
                    return ''
            return open(path, encoding='utf-8', errors='replace').read()
    return ''


def _load_preset_or_default(pid):
    """Load a preset by id, falling back to DEFAULTS (never 404s — for previews)."""
    if pid:
        path = os.path.join(PRESET_DIR, secure_filename(pid) + '.json')
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return DEFAULTS


def _wordcount(text):
    return len(re.findall(r"\b[\w'’-]+\b", text or ''))


@app.route('/project/new-draft', methods=['POST'])
def project_new_draft():
    name = request.form.get('name', '').strip() or 'Untitled draft'
    pid = unique_project_id(slugify(name) or 'draft')
    presets = list_presets()
    ms_file = pid + '.md'
    with open(os.path.join(PROJECT_MS_DIR, ms_file), 'w', encoding='utf-8') as f:
        f.write(STARTER_DRAFT)
    now = datetime.now().isoformat(timespec='seconds')
    data = {
        'name': name, 'preset': presets[0]['id'] if presets else '',
        'title': name, 'subtitle': '', 'author': '', 'year': '', 'publisher': '',
        'front_matter': 'full', 'right_hand_starts': True,
        'cover_overlay': False, 'cover_color': 'light',
        'format': 'pdf', 'include_toc': False, 'smartquotes': True,
        'dedication': '', 'epigraph': '', 'acknowledgments': '',
        'about_author': '', 'also_by': '',
        'manuscript_file': ms_file, 'manuscript_type': 'markdown',
        'cover_file': '', 'last_pdf': '', 'last_epub': '',
        'created': now, 'updated': now,
    }
    save_project_file(pid, data)
    return redirect(url_for('project_write', pid=pid))


@app.route('/project/<pid>/write')
def project_write(pid):
    proj = load_project(pid)
    text = _project_manuscript_text(proj)
    parsed = manuscript.parse_markdown(text, smartquotes=False)
    return render_template('manuscript_editor.html', pid=pid, proj=proj, text=text,
                           words=_wordcount(text), chapters=len(parsed['chapters']))


@app.route('/project/<pid>/write/save', methods=['POST'])
def project_write_save(pid):
    proj = load_project(pid)
    text = request.form.get('text', '')
    new_file = pid + '.md'
    with open(os.path.join(PROJECT_MS_DIR, new_file), 'w', encoding='utf-8') as f:
        f.write(text)
    old = proj.get('manuscript_file', '')
    if old and old != new_file:
        old_path = os.path.join(PROJECT_MS_DIR, old)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
    proj['manuscript_file'] = new_file
    proj['manuscript_type'] = 'markdown'
    proj['updated'] = datetime.now().isoformat(timespec='seconds')
    save_project_file(pid, proj)
    parsed = manuscript.parse_markdown(text, smartquotes=False)
    return jsonify({'ok': True, 'saved_at': datetime.now().strftime('%H:%M:%S'),
                    'words': _wordcount(text), 'chapters': len(parsed['chapters'])})


@app.route('/project/<pid>/write/preview', methods=['POST'])
def project_write_preview(pid):
    try:
        import fitz
    except ImportError:
        return jsonify({'ok': False,
                        'error': 'pymupdf not installed - run: pip install pymupdf'})
    proj = load_project(pid)
    preset = _load_preset_or_default(proj.get('preset', ''))
    text = request.form.get('text', '')
    meta = {
        'title': proj.get('title', ''), 'subtitle': proj.get('subtitle', ''),
        'author': proj.get('author', ''),
        'year': proj.get('year', '') or str(datetime.now().year),
        'publisher': proj.get('publisher', ''),
        'front_matter': proj.get('front_matter', 'full'),
        'right_hand_starts': proj.get('right_hand_starts', True),
        'cover_image': '', 'cover_overlay': False, 'cover_color': 'light',
        'include_toc': False, 'smartquotes': proj.get('smartquotes', True),
        'dedication': proj.get('dedication', ''), 'epigraph': proj.get('epigraph', ''),
        'acknowledgments': proj.get('acknowledgments', ''),
        'contributors': proj.get('contributors', ''),
        'about_author': proj.get('about_author', ''), 'also_by': proj.get('also_by', ''),
    }
    ms = manuscript.parse_markdown(text, smartquotes=meta['smartquotes'])
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        engine.build_pdf(ms, preset, tmp, meta)
        doc = fitz.open(tmp)
        images = []
        for page in doc:
            if len(images) >= 6:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            images.append('data:image/png;base64,' +
                          base64.b64encode(pix.tobytes('png')).decode())
        total = doc.page_count
        doc.close()
        return jsonify({'ok': True, 'images': images, 'pages': total,
                        'chapters': len(ms['chapters']), 'words': _wordcount(text)})
    except Exception as exc:
        logging.error('manuscript preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


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

    cover_mode = proj.get('cover_mode', 'none')
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
        'cover_mode':       cover_mode,
        'cover_template':   proj.get('cover_template', ''),
        'cover_template_data': (load_cover_template(proj.get('cover_template', ''))
                                if cover_mode == 'designed' else None),
        'cover_collection': proj.get('cover_collection', ''),
        'cover_kicker':     proj.get('cover_kicker', ''),
        'cover_accent':     proj.get('cover_accent', ''),
        'cover_epigraph':   proj.get('cover_epigraph', ''),
        'cover_studio':     proj.get('cover_studio', ''),
        'include_toc':   proj.get('include_toc', False),
        'smartquotes':   proj.get('smartquotes', True),
        'dedication':     proj.get('dedication', ''),
        'epigraph':       proj.get('epigraph', ''),
        'acknowledgments': proj.get('acknowledgments', ''),
        'contributors':   proj.get('contributors', ''),
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
            with _epub_cover(preset, meta) as emeta:
                epub.build_epub(ms_parsed, preset, os.path.join(OUT_DIR, epub_name), emeta)
        except Exception as exc:
            logging.error('EPUB build failed: %s', traceback.format_exc())
            flash(f'EPUB build failed: {exc}')
            epub_name = ''

    proj['last_pdf']  = out_name
    proj['last_epub'] = epub_name
    if page_count:
        proj['last_page_count'] = page_count
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


def _free_port(preferred=5050):
    """Return the preferred port if free, else an OS-assigned one."""
    import socket
    for p in (preferred, 0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', p))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            continue
    return preferred


def _serve(port):
    """Run the server (no reloader) — used as the background thread for the window."""
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


def _want_window():
    """Show a native desktop window (pywebview) instead of a browser tab?

    On by default in a frozen/installed build; off when running from source
    (set TS_WINDOW=1 to try it in dev). TS_NO_WINDOW=1 forces the browser.
    """
    if os.environ.get('TS_NO_WINDOW') == '1':
        return False
    if not IS_FROZEN and os.environ.get('TS_WINDOW') != '1':
        return False
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


if __name__ == '__main__':
    if _want_window():
        # native window: serve in a background thread, show the app in an OS
        # webview on the main thread. Closing the window quits (server is a
        # daemon thread). Falls back to the browser if the window can't start.
        port = _free_port(5050)
        url = f'http://127.0.0.1:{port}/'
        threading.Thread(target=_serve, args=(port,), daemon=True).start()
        try:
            import webview
            webview.create_window('Typeset Studio', url,
                                  width=1180, height=820, min_size=(900, 640))
            webview.start()
        except Exception:
            logging.exception('Native window failed; opening in the browser instead.')
            webbrowser.open(url)
            threading.Event().wait()
    else:
        # browser tab. In dev, keep Flask's debug + auto-reloader; a frozen build
        # runs them off (the reloader re-execs the interpreter, which breaks in a
        # bundle).
        dev = not IS_FROZEN
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            threading.Timer(1.0, _open_browser).start()
        app.run(host='127.0.0.1', port=5050, debug=dev, use_reloader=dev, threaded=True)
