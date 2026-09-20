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
import time
import tempfile
import threading
import traceback
import webbrowser
import contextlib
from datetime import datetime, timedelta

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
import matter
import ornaments

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
HISTORY_DIR   = os.path.join(PROJECT_DIR, 'history')   # one folder per project
COVER_THUMB_DIR = os.path.join(OUT_DIR, '_cover_thumbs')   # cached gallery-picker tiles
PROJECT_THUMB_DIR = os.path.join(OUT_DIR, '_project_thumbs')  # cached project cards (page 1 of last PDF)
for d in (PRESET_DIR, COVER_DIR, COVER_ASSET_DIR, FONT_DIR, FIGURE_DIR, OUT_DIR, UPLOAD_DIR,
          PROJECT_DIR, PROJECT_MS_DIR, HISTORY_DIR, COVER_THUMB_DIR, PROJECT_THUMB_DIR):
    os.makedirs(d, exist_ok=True)


def _read_version():
    """This build's version, from the VERSION file the installer also reads.

    One file, three readers — app, `.iss`, `make-installer.bat` — so a release
    cannot ship calling itself something the installer disagrees with.
    """
    for base in (HERE, DATA_DIR):
        try:
            v = open(os.path.join(base, 'VERSION'), encoding='utf-8').read().strip()
            if v:
                return v
        except OSError:
            continue
    try:
        return open(resource_path('VERSION'), encoding='utf-8').read().strip()
    except OSError:
        return '0.0.0'


APP_VERSION = _read_version()

# Where a new release announces itself. Releases are published on the studio's
# public site repo, which carries *several* products — so this reads the whole
# release list and keeps only the ones tagged for this app, rather than asking
# for "latest" and being told about somebody else's release. GitHub's API needs
# no key for a public repo. Point this at a JSON file of your own
# ({"version": "1.3.0", "url": "…"}) if you'd rather not use GitHub at all.
UPDATE_FEED = ('https://api.github.com/repos/Oddmagician6/Ashforge-Studio-LLC'
               '/releases?per_page=30')
UPDATE_PAGE = 'https://github.com/Oddmagician6/Ashforge-Studio-LLC/releases'
# Tags look like `typeset-studio-v1.2.0`; a bare `v1.2.0` is accepted too, so a
# repo dedicated to this app alone would work without changing anything.
UPDATE_TAG_RE = re.compile(r'^(?:typeset[-_ ]?studio[-_ ]?)?v?(\d+(?:\.\d+)*)$', re.I)
# Off unless asked for. This app's promise is that it runs on your machine and
# talks to nobody; a version check is still a network call, so it is the user's
# to switch on. Flip this to True to make new installs check by default.
UPDATE_CHECK_DEFAULT = False
UPDATE_INTERVAL = 86400          # at most one check a day
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_settings(data):
    _atomic_write_text(SETTINGS_PATH, json.dumps(data, indent=2))


def update_checks_on():
    return bool(load_settings().get('update_check', UPDATE_CHECK_DEFAULT))


def _version_tuple(v):
    """'v1.10.2' -> (1, 10, 2). Numeric parts only, so 1.10 sorts above 1.9."""
    parts = re.findall(r'\d+', (v or '').strip().lstrip('vV'))
    return tuple(int(p) for p in parts[:4]) or (0,)


def is_newer(candidate, current=None):
    return _version_tuple(candidate) > _version_tuple(current or APP_VERSION)


def _fetch_json(url, timeout=6):
    """Read a small JSON document. Any failure is a None, never an exception."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        'User-Agent': f'TypesetStudio/{APP_VERSION}',   # GitHub requires one
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if getattr(resp, 'status', 200) != 200:
            return None
        return json.loads(resp.read(200_000).decode('utf-8', 'replace'))


def _pick_release(data):
    """(version, url) for the newest release *of this app*, or None.

    Accepts what GitHub returns for a release list, a single release, or a
    hand-written `{"version": …, "url": …}`. The filtering matters because the
    releases live alongside other Ashforge products: asking for "latest" would
    happily report a Beholders Gazette release as a new Typeset Studio. A tag
    that doesn't parse is skipped rather than guessed at, drafts and
    pre-releases are ignored, and a link that isn't https is replaced with the
    releases page rather than handed to the UI.
    """
    entries = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    best = None
    for item in entries:
        if not isinstance(item, dict) or item.get('draft') or item.get('prerelease'):
            continue
        tag = str(item.get('tag_name') or item.get('version') or '').strip()
        m = UPDATE_TAG_RE.match(tag)
        if not m:
            continue
        version = m.group(1)
        url = str(item.get('html_url') or item.get('url') or UPDATE_PAGE)
        if not url.startswith('https://'):
            url = UPDATE_PAGE
        if best is None or _version_tuple(version) > _version_tuple(best[0]):
            best = (version, url)
    return best


def check_for_update(force=False, fetch=None):
    """Ask whether a newer release exists. Returns the cached answer, or None.

    Nothing is sent but the request itself — no identifiers, no usage, no
    telemetry. Refuses to run unless the user turned checking on (a `force`
    from the Check-now button counts as asking), and at most once a day
    otherwise. Every failure — offline, rate-limited, garbage JSON, a private
    repo — is silence: an update check must never be something that breaks
    the app you are trying to use.
    """
    if not (force or update_checks_on()):
        return None
    settings = load_settings()
    now = time.time()
    if not force and now - float(settings.get('update_checked_at') or 0) < UPDATE_INTERVAL:
        cached = settings.get('update_latest')
        return {'version': cached, 'url': settings.get('update_url') or UPDATE_PAGE,
                'newer': bool(cached and is_newer(cached))} if cached else None
    try:
        data = (fetch or _fetch_json)(UPDATE_FEED)
    except Exception:
        data = None
    found = _pick_release(data)
    if not found:
        return None
    latest, url = found
    settings.update({'update_checked_at': now, 'update_latest': latest,
                     'update_url': url})
    save_settings(settings)
    return {'version': latest, 'url': url, 'newer': is_newer(latest)}


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


def issue_rows(rows):
    """The check rows a writer still has something to do about.

    A row that failed but carries `note` is describing the file, not faulting
    it — the press check's output intent is false on every build we make. The
    browser and the spec sheet in the package both count through here, so they
    can never disagree about how many things are outstanding.
    """
    return [c for c in (rows or []) if not c['ok'] and not c.get('note')]


app.jinja_env.filters['issues'] = issue_rows

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
        'hardcover_note': 'KDP case laminate: 0.625" wrap, 0.375" hinge each side of the '
                          'spine, white paper only, 75–550 pages, and five trims '
                          '(5.5×8.5, 6×9, 6.14×9.21, 7×10, 8.25×11).',
    },
    'ingramspark': {
        'label': 'IngramSpark', 'bleed': 0.125, 'spine_text_min': 48,
        'note': 'IngramSpark perfect-bound spine text from ~48 pages · 0.125" bleed. '
                'Download IngramSpark’s cover template to confirm the spine.',
        'hardcover_note': 'IngramSpark case laminate takes the same 0.625" (16 mm) wrap; '
                          'part of it is covered by the end sheets. Generate their cover '
                          'template to confirm the hinge for your trim.',
    },
    'generic': {
        'label': 'Generic / other POD', 'bleed': 0.125, 'spine_text_min': 80,
        'note': 'General POD defaults · 0.125" bleed. Verify bleed, spine, and safe '
                'margins against your printer’s template.',
        'hardcover_note': 'Case-laminate defaults (0.625" wrap, 0.375" hinge). Hardcover '
                          'allowances vary more between printers than paperback ones — '
                          'check yours before ordering a proof.',
    },
}

# Case-laminate allowances, shared because both retailers document the same
# numbers: the turn-in glued around the boards, the crease each side of the
# spine, and the board thickness a hardcover spine carries on top of the paper.
# Every one of them is editable on the form — this is the starting point, not a
# promise about a particular printer.
HARDCOVER = {'wrap': 0.625, 'hinge': 0.375, 'board': 0.06}

# A dust jacket wraps the finished case, so it is measured off the boards, not
# the block: `board_ext` is how far the board stands proud of the pages (an
# eighth of an inch is the trade norm), and `flap` is the folded-in end. Flaps
# run 3–4"; 3.5" is the common house figure. Jackets are printer-specific —
# among the retailers we preset, only IngramSpark prints them.
JACKET = {'flap': 3.5, 'board_ext': 0.125, 'hinge': 0.375}

# KDP's hardcover programme is narrower than its paperback one; the wrap builds
# either way, but a book outside these is one KDP will refuse.
_KDP_HARDCOVER_TRIMS = [(5.5, 8.5), (6.0, 9.0), (6.14, 9.21), (7.0, 10.0), (8.25, 11.0)]
_KDP_HARDCOVER_PAGES = (75, 550)


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

    if build_result.get('has_cover'):
        checks.append({
            'label': 'Cover on page 1', 'ok': False,
            'detail': ('This PDF opens with the cover — fine for reading on screen, '
                       'but KDP and IngramSpark would print it as the first inside '
                       'page. For a print upload, build press-ready (no cover) and '
                       'send the cover as a separate wrap')})

    dead = build_result.get('dead_links') or []
    if dead:
        shown = ', '.join(sorted(set(dead))[:4])
        more = len(set(dead)) - 4
        checks.append({
            'label': 'In-book links', 'ok': False,
            'detail': (f'{len(dead)} link(s) point nowhere and were left as plain '
                       f'text: {shown}' + (f' (+{more} more)' if more > 0 else '') +
                       ' — check the anchor spelling, or the chapter title it was '
                       'made from')})

    missing = build_result.get('notes_unplaced', 0)
    if missing:
        checks.append({
            'label': 'Footnotes', 'ok': False,
            'detail': (f'{missing} note(s) had no room on the page they belong to — '
                       'shorten them, or set the style to put notes at the back')})

    if page_count:
        kdp_ok = 24 <= page_count <= 828
        checks.append({'label': 'Page count', 'ok': kdp_ok,
                       'detail': (f'{page_count} pages — within KDP range (24–828)'
                                  if kdp_ok else
                                  f'{page_count} pages — outside KDP range (24–828)')})

    return checks


def _epubcheck_jar():
    """Path to epubcheck.jar if the user has installed one, else None.

    Optional by design: the structural checks in `epub.check` are ours and always
    run. This is the belt-and-braces pass with the reference implementation, for
    anyone who wants it before a shop upload.
    """
    env = os.environ.get('EPUBCHECK_JAR', '').strip()
    if env and os.path.exists(env):
        return env
    for base in (DATA_DIR, HERE):
        p = os.path.join(base, 'epubcheck.jar')
        if os.path.exists(p):
            return p
    return None


def _run_epubcheck(epub_path):
    """One check dict from the real epubcheck, or None if it isn't available."""
    jar = _epubcheck_jar()
    if not jar or not shutil.which('java'):
        return None
    try:
        import subprocess
        proc = subprocess.run(['java', '-jar', jar, '--quiet', '--failonwarnings',
                               epub_path],
                              capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {'label': 'epubcheck', 'ok': True,
                'detail': f'Could not run epubcheck ({exc}) — our own checks above still ran'}
    if proc.returncode == 0:
        return {'label': 'epubcheck', 'ok': True, 'detail': 'Valid EPUB 3 (reference validator)'}
    msg = (proc.stdout or proc.stderr or '').strip().splitlines()
    first = next((l for l in msg if l.strip()), 'see console for detail')
    return {'label': 'epubcheck', 'ok': False, 'detail': first[:160]}


def _press_report(pdf_name, build_result):
    """Press-check rows for a just-built interior, or None if it wasn't asked for.

    Only shown when the book was built press-ready: on an ordinary RGB build
    every row would read as a failure, when in fact the file is exactly what
    KDP and IngramSpark want.
    """
    if not pdf_name or not build_result or not build_result.get('press'):
        return None
    path = os.path.join(OUT_DIR, pdf_name)
    if not os.path.exists(path):
        return None
    try:
        return engine.press_check(path)
    except Exception:
        logging.exception('press check failed')
        return None


def _epub_checks(path):
    """Our EPUB checks for a file anywhere on disk, plus epubcheck if installed.

    Takes a path rather than a name in `OUT_DIR` because the publish package
    (#67) builds its ebook in a temp folder and zips it — the same rows have to
    reach the package page and `PUBLISH-SPEC.txt`.
    """
    try:
        checks = epub.check(path)
    except Exception:
        logging.exception('EPUB preflight failed')
        return None
    extra = _run_epubcheck(path)
    if extra:
        checks.append(extra)
    return checks


def _epub_preflight(epub_name):
    """Checks for a just-built EPUB, or None if this book didn't make one."""
    if not epub_name:
        return None
    path = os.path.join(OUT_DIR, epub_name)
    if not os.path.exists(path):
        return None
    return _epub_checks(path)


def _cover_jpeg_size(path):
    """(width, height) in pixels of a rendered cover JPEG, or None.

    Only for the spec sheet: a store listing asks for pixels, and the number
    depends on the style's trim, so it can't be stated once and reused.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


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
    # An illustration printed on every chapter opener: a filename in figures/
    # (or an absolute path). '' — the default — means no art, so every style
    # written before this feature opens exactly as it did.
    'chapter_art': {'image': '', 'position': 'above', 'width': 0.32,
                    'align': 'center', 'gap': 0.16, 'max_height': 1.6},
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
    'list': {'bullet': '•', 'number_format': '{n}.', 'indent': 0.25,
             'marker_gap': 0.22, 'item_gap': 3.0, 'space_around': 10.0,
             'font_size': 0, 'line_leading': 1.35},
    'quote': {'indent': 0.35, 'right_indent': 0.35, 'first_indent': 0.0,
              'font_size': 0, 'line_leading': 1.35, 'style': 'regular',
              'space_around': 11.0, 'para_gap': 4.0,
              'source_style': 'italic', 'source_align': 'right', 'source_gap': 3.0},
    'align': {'space_around': 9.0, 'indent': 0.0, 'para_gap': 3.0},
    # rules: "all" (a full grid) | "horizontal" | "header" (the book default —
    # a rule above, under the header and at the foot) | "none"
    'table': {'font_size': 0, 'line_leading': 1.3, 'header_style': 'bold',
              'rules': 'header', 'rule_width': 0.5, 'cell_pad_x': 5.0,
              'cell_pad_y': 3.0, 'space_around': 12.0, 'width': 1.0,
              'align': 'center', 'caption_size': 0, 'caption_style': 'italic',
              'caption_align': 'center', 'caption_gap': 5.0},
    # Links are clickable in both outputs. `underline` is the print setting;
    # `color`/`epub_underline` style them in the ebook only.
    'link': {'underline': False, 'color': '', 'epub_underline': True},
    'endnotes': {'placement': 'end',
                 'heading': 'Notes', 'group_by_chapter': True, 'font_size': 0,
                 'line_leading': 1.35, 'indent': 0.3, 'entry_gap': 3.0,
                 'group_gap': 12.0, 'marker_scale': 0.62,
                 'foot_gap': 10.0, 'foot_rule': True, 'foot_rule_width': 0.3,
                 'foot_max_height': 0.4},
    # type: glyph (typed characters) | ornament (a bundled vector mark) | image
    # (your own artwork). `ornament_width` is a fraction of the text column;
    # 0 means "use the ornament's own recommended width" — see ornaments.py.
    'scene_break': {'type': 'glyph', 'glyph': '* * *', 'size': 11.0, 'gap': 9.0,
                    'image': '', 'ornament': '', 'ornament_width': 0.0},
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


def _slug_or_blank(name):
    """`slugify` without a default, for callers that supply their own."""
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')


def slugify(name):
    return _slug_or_blank(name) or 'style'


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
        'chapter_art': {
            'image':      form.get('ca_image', '').strip(),
            'position':   form.get('ca_position', 'above'),
            'width':      _f(form, 'ca_width', 0.32),
            'align':      form.get('ca_align', 'center'),
            'gap':        _f(form, 'ca_gap', 0.16),
            'max_height': _f(form, 'ca_max_height', 1.6),
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
        'list': {
            'bullet':        form.get('li_bullet', '•') or '•',
            'number_format': form.get('li_number_format', '{n}.') or '{n}.',
            'indent':        _f(form, 'li_indent', 0.25),
            'marker_gap':    _f(form, 'li_marker_gap', 0.22),
            'item_gap':      _f(form, 'li_item_gap', 3.0),
            'space_around':  _f(form, 'li_space_around', 10.0),
            'font_size':     _f(form, 'li_font_size', 0),
            'line_leading':  _f(form, 'li_line_leading', 1.35),
        },
        'quote': {
            'indent':        _f(form, 'q_indent', 0.35),
            'right_indent':  _f(form, 'q_right_indent', 0.35),
            'first_indent':  _f(form, 'q_first_indent', 0.0),
            'font_size':     _f(form, 'q_font_size', 0),
            'line_leading':  _f(form, 'q_line_leading', 1.35),
            'style':         form.get('q_style', 'regular'),
            'space_around':  _f(form, 'q_space_around', 11.0),
            'para_gap':      _f(form, 'q_para_gap', 4.0),
            'source_style':  form.get('q_source_style', 'italic'),
            'source_align':  form.get('q_source_align', 'right'),
            'source_gap':    _f(form, 'q_source_gap', 3.0),
        },
        'align': {
            'space_around':  _f(form, 'al_space_around', 9.0),
            'indent':        _f(form, 'al_indent', 0.0),
            'para_gap':      _f(form, 'al_para_gap', 3.0),
        },
        'table': {
            'font_size':     _f(form, 'tb_font_size', 0),
            'line_leading':  _f(form, 'tb_line_leading', 1.3),
            'header_style':  form.get('tb_header_style', 'bold'),
            'rules':         form.get('tb_rules', 'header'),
            'rule_width':    _f(form, 'tb_rule_width', 0.5),
            'cell_pad_x':    _f(form, 'tb_cell_pad_x', 5.0),
            'cell_pad_y':    _f(form, 'tb_cell_pad_y', 3.0),
            'space_around':  _f(form, 'tb_space_around', 12.0),
            'width':         _f(form, 'tb_width', 1.0),
            'align':         form.get('tb_align', 'center'),
            'caption_size':  _f(form, 'tb_caption_size', 0),
            'caption_style': form.get('tb_caption_style', 'italic'),
            'caption_align': form.get('tb_caption_align', 'center'),
            'caption_gap':   _f(form, 'tb_caption_gap', 5.0),
        },
        'link': {
            'underline':      'lk_underline' in form,
            'color':          (form.get('lk_color', '') or '').strip(),
            'epub_underline': 'lk_epub_underline' in form,
        },
        'endnotes': {
            'placement':        form.get('en_placement', 'end'),
            'foot_gap':         _f(form, 'en_foot_gap', 10.0),
            'foot_rule':        'en_foot_rule' in form,
            'foot_rule_width':  _f(form, 'en_foot_rule_width', 0.3),
            'foot_max_height':  _f(form, 'en_foot_max_height', 0.4),
            'heading':          form.get('en_heading', 'Notes') or 'Notes',
            'group_by_chapter': 'en_group_by_chapter' in form,
            'font_size':        _f(form, 'en_font_size', 0),
            'line_leading':     _f(form, 'en_line_leading', 1.35),
            'indent':           _f(form, 'en_indent', 0.3),
            'entry_gap':        _f(form, 'en_entry_gap', 3.0),
            'group_gap':        _f(form, 'en_group_gap', 12.0),
            'marker_scale':     _f(form, 'en_marker_scale', 0.62),
        },
        'scene_break': {
            'type':  form.get('sb_type', 'glyph'),
            'glyph': form.get('s_glyph', '* * *') or '* * *',
            'size':  _f(form, 's_size', 11.0),
            'gap':   _f(form, 's_gap', 9.0),
            'image': form.get('sb_image', '').strip(),
            'ornament': (form.get('sb_ornament', '') or '').strip(),
            'ornament_width': _f(form, 'sb_ornament_width', 0.0),
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
            'cover_groups': group_cover_templates(items),
            # the front/back matter vocabulary, so the forms build themselves
            'matter_front': matter.FRONT,
            'matter_back': matter.BACK,
            'matter_keys': matter.KEYS,
            'app_version': APP_VERSION,
            # a cached answer only — no page render ever waits on the network
            'update_info': (check_for_update() if update_checks_on() else None),
            'scene_break_label': scene_break_label}


def scene_break_label(preset):
    """How a style's scene break reads on a spec card: the ornament's name, the
    image filename, or the glyph itself."""
    sb = preset.get('scene_break', {}) or {}
    kind = sb.get('type', 'glyph')
    if kind == 'ornament':
        d = ornaments.get(sb.get('ornament', ''))
        if d:
            return d['name']
    elif kind == 'image' and sb.get('image', '').strip():
        return os.path.basename(sb['image'].strip())
    return sb.get('glyph', '* * *')


@app.route('/about')
def about():
    settings = load_settings()
    return render_template('about.html', version=APP_VERSION,
                           checks_on=update_checks_on(),
                           update=check_for_update(),
                           checked_at=settings.get('update_checked_at'),
                           feed=UPDATE_FEED, page=UPDATE_PAGE)


@app.route('/about/updates', methods=['POST'])
def about_updates():
    """Turn the version check on or off. Off also forgets what it learned."""
    settings = load_settings()
    on = request.form.get('update_check') == '1'
    settings['update_check'] = on
    if not on:
        for k in ('update_checked_at', 'update_latest', 'update_url'):
            settings.pop(k, None)
    save_settings(settings)
    flash('Update checks are on. Typeset Studio will look once a day.' if on else
          'Update checks are off. Nothing leaves this machine.')
    return redirect(url_for('about'))


@app.route('/about/check', methods=['POST'])
def about_check():
    """Check now — an explicit ask, so it runs even when daily checks are off."""
    info = check_for_update(force=True)
    if not info:
        flash('Could not reach the update feed just now. Nothing else changed.')
    elif info.get('newer'):
        flash(f'Version {info["version"]} is available — you have {APP_VERSION}.')
    else:
        flash(f'You are up to date ({APP_VERSION}).')
    return redirect(url_for('about'))


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(resource_path(), 'app.ico',
                               mimetype='image/vnd.microsoft.icon')


@app.route('/')
def index():
    return render_template('index.html', presets=list_presets())


def ornament_tiles():
    """The bundled ornaments with a ready-to-drop-in SVG preview each, for the
    style editor's picker. Drawn from the same definitions the PDF uses, so a
    tile cannot promise a mark the book won't print."""
    return [{'id': d['id'], 'name': d['name'], 'note': d['note'],
             'width': d['width'],
             'svg': ornaments.svg(d['id'], color='currentColor')}
            for d in ornaments.DEFS]


@app.route('/editor/new')
def editor_new():
    return render_template('editor.html', pid=None, p=DEFAULTS, is_new=True,
                           fonts=list_fonts(), trim_presets=TRIM_PRESETS,
                           ornaments=ornament_tiles(), figures=list_figures())


@app.route('/editor/<pid>')
def editor(pid):
    return render_template('editor.html', pid=pid, p=load_preset(pid), is_new=False,
                           fonts=list_fonts(), trim_presets=TRIM_PRESETS,
                           ornaments=ornament_tiles(), figures=list_figures())


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


# Standard interior trims both KDP and IngramSpark accept, so a style can be set
# to a real size instead of a typo that fails at upload.
TRIM_PRESETS = [
    (4.25, 6.87, 'Mass market'),
    (5.0,  8.0,  'Digest'),
    (5.06, 7.81, 'A-format'),
    (5.25, 8.0,  'Small trade'),
    (5.5,  8.5,  'Trade — the common one'),
    (6.0,  9.0,  'Trade — the other common one'),
    (6.14, 9.21, 'Royal / B-format'),
    (6.69, 9.61, 'Crown quarto'),
    (7.0,  10.0, 'Large print / workbook'),
    (7.44, 9.69, 'Textbook'),
    (7.5,  9.25, 'Textbook (wide)'),
    (8.0,  10.0, 'Illustrated'),
    (8.25, 11.0, 'Letter — manuals, workbooks'),
]

# Large print, following the RNIB / NAVH guidance: 16pt minimum, generous
# leading, ragged right (a justified large-print page opens rivers that are much
# harder to track), no hyphenation, and room in the margins for a thumb.
LARGE_PRINT_MIN_SIZE = 16.0
LARGE_PRINT_TRIM = (7.0, 10.0)


def _scale_sizes(section, factor, keys):
    for k in keys:
        v = section.get(k)
        if isinstance(v, (int, float)) and v > 0:
            section[k] = round(v * factor, 1)


def make_large_print(preset):
    """Derive a large-print edition from an ordinary style.

    Everything typographic scales by one factor so the page keeps its
    proportions, then the accessibility rules are applied on top: a 16pt floor,
    ragged right, no hyphenation, wider margins, and a trim big enough to still
    hold a sensible line at that size — 16pt type in a mass-market trim would
    give about six words a line.
    """
    import copy
    lp = copy.deepcopy(preset)
    body = lp.setdefault('body', {})
    base = body.get('size', 11.0) or 11.0
    factor = max(1.0, LARGE_PRINT_MIN_SIZE / base)

    body['size'] = round(base * factor, 1)
    body['leading'] = round(body['size'] * 1.45, 1)
    body['justify'] = False          # ragged right is the recommendation
    body['hyphenate'] = False        # broken words are the hardest to track
    body['indent'] = round(body.get('indent', 0.3) * 1.2, 2)

    if lp.get('trim', {}).get('w', 6.0) < LARGE_PRINT_TRIM[0]:
        lp['trim'] = {'w': LARGE_PRINT_TRIM[0], 'h': LARGE_PRINT_TRIM[1]}
    m = lp.setdefault('margins', {})
    m['top'] = max(m.get('top', 0.75), 0.85)
    m['bottom'] = max(m.get('bottom', 0.8), 0.9)
    m['inside'] = max(m.get('inside', 0.85), 1.0)
    m['outside'] = max(m.get('outside', 0.6), 0.7)

    _scale_sizes(lp.get('chapter', {}), factor, ('number_size', 'title_size'))
    _scale_sizes(lp.get('part_divider', {}), factor, ('number_size', 'title_size'))
    _scale_sizes(lp.get('scene_break', {}), factor, ('size',))
    _scale_sizes(lp.get('running_head', {}), factor, ('size',))
    _scale_sizes(lp.get('folio', {}), factor, ('size',))
    for key in ('document_block', 'poem', 'list', 'quote', 'figure', 'endnotes'):
        _scale_sizes(lp.get(key, {}), factor,
                     ('font_size', 'header_size', 'title_size', 'caption_size'))

    name = preset.get('name', 'Style')
    # a trailing "(6×9)" in the name would now be a lie about the page
    name = re.sub(r'\s*\([\d.]+\s*[×x]\s*[\d.]+\)\s*$', '', name).strip()
    tw, th = lp['trim']['w'], lp['trim']['h']
    lp['name'] = (name if 'large print' in name.lower()
                  else f'{name} — Large Print ({tw:g}×{th:g})')
    lp['description'] = (f'Large-print edition: {body["size"]:g}pt, ragged right, '
                         f'wide margins. Derived from "{name}".')
    return lp


@app.route('/large-print/<pid>', methods=['POST'])
def large_print(pid):
    data = load_preset(pid)
    lp = make_large_print(data)
    new_id = unique_id(slugify(lp['name']))
    save_preset(new_id, lp)
    flash(f'Created “{lp["name"]}” — {lp["body"]["size"]:g}pt on a '
          f'{lp["trim"]["w"]:g}×{lp["trim"]["h"]:g}" page. Tweak it like any style.')
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
        **matter.blank(),
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


def _cover_page_jpeg(preset, meta, jpg_path):
    """Rasterise page 1 of a book's cover to a JPEG `EPUB_COVER_H` px tall.

    Whichever kind of cover the book has: a designed template, or uploaded art
    with the title overlay the writer set. The rasterised page is the cover as
    the book itself carries it, which is the only version worth sending to a
    shop. Typesets one cover page over a stub manuscript rather than the whole book.
    Raises on any failure (no PyMuPDF/Pillow, a render error) — callers decide
    whether a missing cover is fatal.
    """
    import fitz
    from PIL import Image
    pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(pdf_fd)
    try:
        cover_meta = dict(meta)
        cover_meta.update(front_matter='none', include_toc=False,
                          right_hand_starts=False)
        stub = manuscript.parse_markdown('# Cover\n\nCover.', smartquotes=False)
        engine.build_pdf(stub, preset, pdf_path, cover_meta)

        with fitz.open(pdf_path) as doc:
            page = doc[0]
            scale = EPUB_COVER_H / page.rect.height if page.rect.height else 1.0
            png = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                  alpha=False).tobytes('png')
        # JPEG, else a photographic-family cover makes a multi-megabyte ebook.
        Image.open(io.BytesIO(png)).convert('RGB').save(
            jpg_path, 'JPEG', quality=88, optimize=True)
    finally:
        try:
            os.remove(pdf_path)
        except OSError:
            pass


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

    jpg_fd, jpg_path = tempfile.mkstemp(suffix='.jpg')
    os.close(jpg_fd)
    try:
        try:
            _cover_page_jpeg(preset, meta, jpg_path)
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
        for p in (jpg_path,):
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
            'author': form.get('prev_author', 'Author Name'),
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
            **matter.blank(),
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


def hardcover_warnings(retailer, trim_w, trim_h, pages, paper):
    """What a retailer will refuse about this hardcover, in plain sentences.

    Advisory only — the wrap still builds, because a printer other than the one
    picked may well accept it. Only KDP publishes limits narrow enough to be
    worth checking; the others get their note and no false precision.
    """
    if retailer != 'kdp':
        return []
    out = []
    lo, hi = _KDP_HARDCOVER_PAGES
    if pages and not (lo <= pages <= hi):
        out.append(f'KDP hardcovers run {lo}–{hi} pages; this book is {pages}.')
    if not any(abs(trim_w - w) < 0.01 and abs(trim_h - h) < 0.01
               for w, h in _KDP_HARDCOVER_TRIMS):
        sizes = ', '.join(f'{w:g}×{h:g}' for w, h in _KDP_HARDCOVER_TRIMS)
        out.append(f'KDP hardcovers come in {sizes}" only; this is '
                   f'{trim_w:g}×{trim_h:g}".')
    if paper != 'white':
        out.append('KDP prints hardcovers on white paper only — the spine here '
                   'was worked out from a different stock.')
    return out


def _wrap_from_form(form, out_path, back_image=None):
    """Build a full print wrap (back + spine + front + bleed) from the cover editor form."""
    tpl = parse_cover_form(form)
    interior = engine.register_fonts(DEFAULTS)
    cf = engine._register_cover_fonts(tpl, interior)
    try:
        pages = max(int(_f(form, 'wrap_pages', 200)), 0)
    except (TypeError, ValueError):
        pages = 200
    dims = _wrap_dims(form, pages)
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
        'cover_jacket_blurb': form.get('wrap_flap_blurb', ''),
        'cover_author_bio':   form.get('wrap_flap_bio', ''),
        'cover_back_image':   back_image or '',
        'cover_back_image_w': _f(form, 'wrap_back_w', 1.5),
        'cover_back_image_y': _f(form, 'wrap_back_y', 0.4),
    }
    guides = form.get('wrap_guides') == '1'
    res = engine.build_cover_wrap(tpl, cf, meta, dims, out_path, guides=guides)
    return res, dims


def _wrap_dims(form, pages):
    """Wrap geometry (and the retailer's objections to it) from `wrap_*` fields.

    Shared by the cover editor's wrap export and the print package, which feeds
    it a plain dict built from the project — so a spine is worked out one way.
    """
    paper = form.get('wrap_paper', 'white')
    ppi = _PAPER.get(paper, _PAPER['white'])['ppi']
    retailer = form.get('wrap_retailer', 'kdp')
    rc = WRAP_RETAILERS.get(retailer, WRAP_RETAILERS['kdp'])
    binding = form.get('wrap_binding', 'paperback')
    if binding not in ('paperback', 'hardcover', 'jacket'):
        binding = 'paperback'
    hard = binding == 'hardcover'
    jacket = binding == 'jacket'
    trim_w = _f(form, 'wrap_trim_w', 6.0)
    trim_h = _f(form, 'wrap_trim_h', 9.0)
    # a case spine carries the boards as well as the paper — and a jacket wraps
    # that same case, so it takes the same spine
    spine_w = pages * ppi + (_f(form, 'wrap_board', HARDCOVER['board'])
                             if (hard or jacket) else 0.0)
    dims = {
        'trim_w': trim_w,
        'trim_h': trim_h,
        'spine_w': spine_w,
        'bleed':  _f(form, 'wrap_bleed', rc['bleed']),
        'pages':  pages,
        'spine_text_min': rc['spine_text_min'],
        'binding': binding,
        'wrap':   _f(form, 'wrap_turnin', HARDCOVER['wrap']),
        'hinge':  _f(form, 'wrap_hinge', HARDCOVER['hinge']),
        'flap':   _f(form, 'wrap_flap', JACKET['flap']),
        'board_ext': _f(form, 'wrap_board_ext', JACKET['board_ext']),
    }
    dims['warnings'] = (hardcover_warnings(retailer, trim_w, trim_h, pages, paper)
                        if (hard or jacket) else [])
    if jacket and retailer == 'kdp':
        dims['warnings'].append('KDP does not print dust jackets — this file is for '
                                'IngramSpark or another printer.')
    return dims


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
    kind = {'hardcover': '-case-wrap', 'jacket': '-jacket'}.get(
        request.form.get('wrap_binding'), '-wrap')
    name = slugify(request.form.get('name', 'cover')) + kind + '.pdf'
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
        if res['binding'] == 'hardcover':
            kind = 'case laminate · %g" wrap · %g" hinge' % (res['wrap'], res['hinge'])
        elif res['binding'] == 'jacket':
            kind = ('dust jacket · %g" flaps · %g" panels'
                    % (res['flap'], res['panel_w']))
        else:
            kind = 'paperback'
        info = (f"{dims['trim_w']:g}×{dims['trim_h']:g}\" {kind} · spine {res['spine_w']:g}\" · "
                f"full {res['wrap_w']:g}×{res['wrap_h']:g}\" · {spine_txt}")
        return jsonify({'ok': True, 'image': f'data:image/png;base64,{b64}', 'info': info,
                        'warnings': dims.get('warnings', [])})
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
# ------------------------------------------------------------ cover specs
# For writers designing their own wrap elsewhere: the dimensions for a style's
# trim, computed by the same `wrap_geometry` a designed wrap is built from.
COVER_SPEC_PAGES = (100, 200, 300, 400, 500)
COVER_DPI = 300
_BINDINGS = ('paperback', 'hardcover', 'jacket')


def _cover_spec(preset, args):
    """Wrap geometry for a style's trim, from query args that may be missing or junk."""
    try:
        pages = min(max(int(args.get('pages', 200)), 1), 2000)
    except (TypeError, ValueError):
        pages = 200
    retailer = args.get('retailer', 'kdp')
    retailer = retailer if retailer in WRAP_RETAILERS else 'kdp'
    binding = args.get('binding', 'paperback')
    binding = binding if binding in _BINDINGS else 'paperback'
    paper = args.get('paper', 'white')
    paper = paper if paper in _PAPER else 'white'
    dims = _wrap_dims({'wrap_retailer': retailer, 'wrap_binding': binding,
                       'wrap_paper': paper, 'wrap_trim_w': preset['trim']['w'],
                       'wrap_trim_h': preset['trim']['h']}, pages)
    return {'pages': pages, 'retailer': retailer, 'binding': binding, 'paper': paper,
            'dims': dims, 'geo': engine.wrap_geometry(dims)}


def _wrap_guide_lines(g):
    """Where to put guides in a design app: (label, inches from the left or bottom)."""
    xs = []
    if g['wrap']:
        xs.append(('Turn-in ends', g['wrap']))
    xs.append(('Left trim', g['edge']))
    if g['flap']:
        xs.append(('Fold: back flap | back cover', g['back_x']))
    if g['hinge']:
        xs += [('Back cover edge (hinge starts)', g['back_x'] + g['panel_w']),
               ('Spine starts', g['spine_x']),
               ('Spine ends', g['spine_x'] + g['spine_w']),
               ('Front cover edge (hinge ends)', g['front_x'])]
    else:
        xs += [('Fold: back cover | spine', g['spine_x']),
               ('Fold: spine | front cover', g['front_x'])]
    if g['flap']:
        xs.append(('Fold: front cover | front flap', g['front_x'] + g['panel_w']))
    xs.append(('Right trim', g['wrap_w'] - g['edge']))
    if g['wrap']:
        xs.append(('Turn-in ends', g['wrap_w'] - g['wrap']))
    ys = [('Bottom trim', g['edge']), ('Top trim', g['edge'] + g['panel_h'])]
    if g['wrap']:
        ys = [('Turn-in ends', g['wrap'])] + ys + [('Turn-in ends', g['wrap_h'] - g['wrap'])]
    return {'x': xs, 'y': ys}


@app.route('/style/<pid>/cover-specs')
def style_cover_specs(pid):
    preset = load_preset(pid)
    spec = _cover_spec(preset, request.args)
    rows = []
    for n in COVER_SPEC_PAGES:
        rg = _cover_spec(preset, {**request.args.to_dict(), 'pages': n})['geo']
        rows.append({'pages': n, 'spine_w': rg['spine_w'], 'wrap_w': rg['wrap_w'],
                     'wrap_h': rg['wrap_h'], 'spine_text': rg['spine_text']})
    g = spec['geo']
    return render_template('cover_specs.html', pid=pid, preset=preset, spec=spec, g=g,
                           px=engine.wrap_pixels(g, COVER_DPI), dpi=COVER_DPI, rows=rows,
                           guides=_wrap_guide_lines(g),
                           rc=WRAP_RETAILERS[spec['retailer']], retailers=WRAP_RETAILERS,
                           papers=_PAPER, safe=engine.WRAP_SAFE,
                           spine_safe=engine.WRAP_SPINE_SAFE, barcode=engine.BARCODE)


@app.route('/style/<pid>/cover-specs/template.pdf')
def style_cover_specs_template(pid):
    preset = load_preset(pid)
    spec = _cover_spec(preset, request.args)
    name = preset.get('name') or pid
    caption = (f'{name} - {preset["trim"]["w"]:g}" x {preset["trim"]["h"]:g}" - '
               f'{spec["pages"]} pages, {_PAPER[spec["paper"]]["label"]} - '
               f'{WRAP_RETAILERS[spec["retailer"]]["label"]}')
    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        engine.build_wrap_guide(spec['dims'], tmp, caption=caption)
        with open(tmp, 'rb') as f:
            data = f.read()
    finally:
        os.remove(tmp)
    fn = f'{slugify(name)}-{spec["binding"]}-{spec["pages"]}pp-cover-template.pdf'
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{fn}"'})


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
        raw = _norm_newlines(form['pasted'])
        stamp_p = datetime.now().strftime('%Y%m%d-%H%M%S')
        ms_path = os.path.join(UPLOAD_DIR, f'pasted-{stamp_p}.txt')
        with open(ms_path, 'w', encoding='utf-8', newline='') as pf:
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
        'press':          'press' in form,
        **{k: form.get(k, '').strip() for k in matter.KEYS},
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
            build_result = engine.build_pdf(ms, preset, os.path.join(OUT_DIR, out_name),
                                            meta, press=meta['press'])
            page_count   = build_result['page_count']
            if meta['press'] and build_result.get('press_error'):
                flash('This book has colour in it, so it was built the normal way: '
                      + build_result['press_error'])
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
    press     = _press_report(out_name, build_result)
    chapters  = len(ms['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=pid,
                           chapters=chapters, ms_path=ms_path, ms_type=ms_type,
                           cover_path=cover_path, from_project=None, fmt=fmt,
                           spec=spec, preflight=preflight, press=press,
                           epub_preflight=_epub_preflight(epub_name))


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
            **matter.blank(),
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


class _PreviewError(Exception):
    """A message meant for the user, not a stack trace."""


def _book_from_compose_form(tmp_files):
    """Read the compose form into (preset, manuscript, meta, total, truncated).

    Shared by the page-image preview and the ebook preview: both need exactly the
    same reading of the form as /generate does, and neither persists anything —
    uploads land in `tmp_files` for the caller to delete.
    """
    form = request.form
    pid  = form.get('preset')
    if not pid:
        raise _PreviewError('Pick a style first.')
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
                raise _PreviewError('python-docx is not installed. Run: pip install python-docx')
            except Exception as exc:
                raise _PreviewError(f'Could not read the Word file: {exc}')
        else:
            raw = open(tmp_ms, encoding='utf-8', errors='replace').read()
    elif form.get('pasted', '').strip():
        raw = form['pasted']
    elif form.get('use_sample'):
        raw = open(SAMPLE, encoding='utf-8').read()

    if not raw:
        raise _PreviewError('Add a manuscript first — upload a file, paste text, or tick the sample.')

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
        **{k: form.get(k, '').strip() for k in matter.KEYS},
    }

    ms = manuscript.parse_markdown(raw, smartquotes=meta['smartquotes'])
    chapters_total = len(ms['chapters'])
    truncated = chapters_total > PREVIEW_MAX_CHAPTERS
    if truncated:
        ms = {'chapters': ms['chapters'][:PREVIEW_MAX_CHAPTERS]}

    ms = manuscript.parse_markdown(raw, smartquotes=meta['smartquotes'])
    chapters_total = len(ms['chapters'])
    truncated = chapters_total > PREVIEW_MAX_CHAPTERS
    if truncated:
        ms = {'chapters': ms['chapters'][:PREVIEW_MAX_CHAPTERS]}
    return preset, ms, meta, chapters_total, truncated


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
        preset, ms, meta, chapters_total, truncated = \
            _book_from_compose_form(tmp_files)

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
    except _PreviewError as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    except Exception as exc:
        logging.error('generate preview failed: %s', traceback.format_exc())
        return jsonify({'ok': False, 'error': str(exc)})
    finally:
        for f in tmp_files:
            try:
                os.remove(f)
            except OSError:
                pass


# Reading-device viewports, in CSS pixels — the shapes a reflowable book has to
# survive. A phone is the cramped case, a tablet the roomy one, and the e-reader
# the one authors actually worry about.
PREVIEW_DEVICES = [
    {'id': 'phone',  'label': 'Phone',    'w': 375, 'h': 667, 'note': '6" phone'},
    {'id': 'reader', 'label': 'E-reader', 'w': 500, 'h': 690, 'note': '6" e-ink'},
    {'id': 'tablet', 'label': 'Tablet',   'w': 768, 'h': 1024, 'note': '10" tablet'},
]

_IMG_SRC_RE = re.compile(r'src="((?:images/|cover)[^"]+)"')


@app.route('/generate/epub-preview', methods=['POST'])
def generate_epub_preview():
    """Show the *ebook*, not the page images — the other half of a book build.

    Builds the real EPUB to a temp file and reads the documents back out of it,
    rather than re-rendering the chapters here. The zip is the artefact readers
    get, so previewing anything else would be previewing a guess: this way note
    markers, figures, links and matter pages are exactly what shipped.
    """
    tmp_files = []
    try:
        preset, ms, meta, chapters_total, truncated = \
            _book_from_compose_form(tmp_files)

        fd, tmp_epub = tempfile.mkstemp(suffix='.epub')
        os.close(fd)
        tmp_files.append(tmp_epub)
        epub.build_epub(ms, preset, tmp_epub, meta)

        import zipfile as _zip
        from xml.dom import minidom
        import posixpath

        docs = []
        with _zip.ZipFile(tmp_epub) as zf:
            opf_path = (minidom.parseString(zf.read('META-INF/container.xml'))
                        .getElementsByTagName('rootfile')[0].getAttribute('full-path'))
            base = posixpath.dirname(opf_path)
            opf = minidom.parseString(zf.read(opf_path))
            items = {el.getAttribute('id'): el.getAttribute('href')
                     for el in opf.getElementsByTagName('item')}
            order = [el.getAttribute('idref')
                     for el in opf.getElementsByTagName('itemref')]

            def full(href):
                return posixpath.normpath(posixpath.join(base, href)) if base else href

            css = zf.read(full('style.css')).decode('utf-8', 'replace') \
                if full('style.css') in zf.namelist() else ''

            # inline the art: an iframe built from a string can't fetch from a zip
            def inline_images(html, doc_href):
                def sub(m):
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(doc_href), m.group(1)))
                    name = full(target)
                    if name not in zf.namelist():
                        return m.group(0)
                    ext = os.path.splitext(name)[1].lower().lstrip('.')
                    mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                            'svg': 'image/svg+xml'}.get(ext, f'image/{ext}')
                    b64 = base64.b64encode(zf.read(name)).decode()
                    return f'src="data:{mime};base64,{b64}"'
                return _IMG_SRC_RE.sub(sub, html)

            for idref in order:
                href = items.get(idref)
                if not href or full(href) not in zf.namelist():
                    continue
                raw = zf.read(full(href)).decode('utf-8', 'replace')
                body = raw.split('<body>', 1)[-1].rsplit('</body>', 1)[0]
                docs.append({'href': href, 'html': inline_images(body, href)})

        return jsonify({
            'ok': True,
            'css': css,
            'docs': docs,
            'devices': PREVIEW_DEVICES,
            'chapters_total': chapters_total,
            'chapters_shown': len(ms['chapters']),
            'truncated': truncated,
        })
    except _PreviewError as exc:
        return jsonify({'ok': False, 'error': str(exc)})
    except Exception as exc:
        logging.error('epub preview failed: %s', traceback.format_exc())
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
        'press': form.get('press') == '1',
        **{k: form.get(k, '').strip() for k in matter.KEYS},
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
            # the draft about to be replaced is the one most worth keeping — an
            # upload here overwrites work that may exist nowhere else
            snapshot_manuscript(pid, _project_manuscript_text(proj, report_import=False),
                                reason='replaced', force=True)
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

        # Optional back-cover image for the print package's wrap
        old_back = proj.get('print_back_file', '')
        back = request.files.get('print_back_image')
        new_back = ''
        if back and back.filename:
            ext = os.path.splitext(secure_filename(back.filename))[1].lower()
            if ext in ('.jpg', '.jpeg', '.png'):
                new_back = pid + '-back' + ext
                back.save(os.path.join(PROJECT_MS_DIR, new_back))
                proj['print_back_file'] = new_back
        elif 'print_back_clear' in form:
            proj['print_back_file'] = ''
        if old_back and old_back != proj.get('print_back_file', ''):
            old_path = os.path.join(PROJECT_MS_DIR, old_back)
            if os.path.exists(old_path):
                os.remove(old_path)

        proj.update({
            'print_retailer':   form.get('print_retailer', 'kdp'),
            'print_binding':    form.get('print_binding', 'paperback'),
            'print_paper':      form.get('print_paper', 'white'),
            'print_blurb':      form.get('print_blurb', '').strip(),
            'print_flap_blurb': form.get('print_flap_blurb', '').strip(),
            'print_flap_bio':   form.get('print_flap_bio', '').strip(),
            'print_back_w':     _f(form, 'print_back_w', 1.5),
            'print_back_y':     _f(form, 'print_back_y', 0.4),
        })
        proj.update({
            'name':             form.get('name', '').strip() or proj['name'],
            'preset':           form.get('preset', proj['preset']),
            'format':      form.get('format', proj.get('format', 'pdf')),
            'include_toc': 'include_toc' in form,
            'smartquotes': 'smartquotes' in form,
            'press': 'press' in form,
            **{k: form.get(k, '').strip() for k in matter.KEYS},
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

    return render_template('project_edit.html', pid=pid, proj=proj, presets=presets,
                           wrap_retailers=WRAP_RETAILERS, papers=_PAPER)


# ---------------------------------------------------------- manuscript editor
STARTER_DRAFT = ("# Chapter One\n\n"
                 "Your story starts here. Delete this line and begin writing.\n\n"
                 "Use a blank line between paragraphs. Mark emphasis with *italics* or "
                 "**bold**, start a new chapter with a line like `# Chapter Two`, and drop a "
                 "scene break with `* * *` on its own line.\n")


def _project_manuscript_text(proj, report_import=True):
    """Return a project's manuscript as editable Markdown text ('' if none).

    `report_import=False` for the internal readers (snapshotting before a
    destructive change): they want the text, not a flashed import summary the
    user never asked for.
    """
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
                    if report_import:
                        _flash_import(rep)   # the page-rendering callers only
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


def _norm_newlines(text):
    """LF only. Manuscripts are stored as the writer's own source, so a stray
    CR is corruption, not formatting — and it compounds on every save."""
    return (text or '').replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n')


# ------------------------------------------------------- manuscript safety
# Once a book can be written *in* the app, the file on disk is the only copy of
# someone's work, and this is the code standing between them and losing it.
SNAPSHOT_GAP   = 180     # seconds between autosave snapshots of the same project
HISTORY_KEEP   = 40      # hard cap on snapshots per project
_SNAP_RE = re.compile(r'^(\d{8}-\d{6})-(\w+)\.md$')


def _atomic_write_text(path, text):
    """Write a file so that an interrupted write cannot destroy the old one.

    A plain `open(path, 'w')` truncates first: a crash, a full disk or a killed
    process between that and the write leaves an empty manuscript. Writing a
    temporary file in the same folder and then `os.replace`-ing it is atomic on
    both Windows and POSIX — after it, the file is either wholly the old text or
    wholly the new one.
    """
    folder = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())      # the bytes, not just the buffer
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _history_folder(pid):
    return os.path.join(HISTORY_DIR, secure_filename(pid))


def list_snapshots(pid):
    """Every kept snapshot of a project's manuscript, newest first."""
    folder = _history_folder(pid)
    out = []
    for fn in os.listdir(folder) if os.path.isdir(folder) else []:
        m = _SNAP_RE.match(fn)
        if not m:
            continue
        stamp, reason = m.group(1), m.group(2)
        path = os.path.join(folder, fn)
        try:
            text = open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        when = datetime.strptime(stamp, '%Y%m%d-%H%M%S')
        out.append({'stamp': stamp, 'reason': reason,
                    'when': when.strftime('%d %b %Y, %H:%M'),
                    'iso': when.isoformat(timespec='seconds'),
                    'words': _wordcount(text), 'chars': len(text)})
    out.sort(key=lambda s: s['stamp'], reverse=True)
    return out


def _thin_snapshots(pid):
    """Keep recent history dense and old history sparse.

    Everything from the last hour, then one an hour for a day, then one a day —
    and never more than HISTORY_KEEP files. A writer wants the last few minutes
    in detail and last Tuesday at all; keeping every autosave forever would do
    neither well.
    """
    folder = _history_folder(pid)
    snaps = sorted((s['stamp'] for s in list_snapshots(pid)), reverse=True)
    now = datetime.now()
    keep, seen = [], set()
    for stamp in snaps:
        when = datetime.strptime(stamp, '%Y%m%d-%H%M%S')
        age = (now - when).total_seconds()
        if age <= 3600:
            bucket = ('minute', stamp)                    # keep them all
        elif age <= 86400:
            bucket = ('hour', when.strftime('%Y%m%d-%H'))
        else:
            bucket = ('day', when.strftime('%Y%m%d'))
        if bucket in seen:
            continue
        seen.add(bucket)
        keep.append(stamp)
    keep = set(keep[:HISTORY_KEEP])
    for fn in os.listdir(folder) if os.path.isdir(folder) else []:
        m = _SNAP_RE.match(fn)
        if m and m.group(1) not in keep:
            try:
                os.remove(os.path.join(folder, fn))
            except OSError:
                pass


def snapshot_manuscript(pid, text, reason='edit', force=False):
    """Keep a copy of this text in the project's history. Returns its stamp or ''.

    Skipped when the text is identical to the newest snapshot (nothing happened)
    or when that snapshot is younger than SNAPSHOT_GAP — autosave fires every few
    seconds of typing, and a snapshot per keystroke-pause is noise, not history.
    `force` overrides the interval for the moments that matter: just before a
    restore, or before a manuscript is replaced wholesale.
    """
    text = _norm_newlines(text)
    if not text.strip():
        return ''                       # never snapshot an empty editor
    folder = _history_folder(pid)
    os.makedirs(folder, exist_ok=True)
    existing = list_snapshots(pid)
    if existing:
        newest = existing[0]
        prev_path = os.path.join(folder, f'{newest["stamp"]}-{newest["reason"]}.md')
        try:
            if open(prev_path, encoding='utf-8', errors='replace').read() == text:
                return ''
        except OSError:
            pass
        if not force:
            age = (datetime.now()
                   - datetime.strptime(newest['stamp'], '%Y%m%d-%H%M%S')).total_seconds()
            if age < SNAPSHOT_GAP:
                return ''
    # The stamp is the identity a restore is asked for by, so it has to be
    # unique: two snapshots in the same second (an autosave and a forced copy
    # before a restore) would otherwise both answer to it, and a restore could
    # hand back the wrong one. Step forward a second until it is free.
    taken = {s['stamp'] for s in existing}
    when = datetime.now()
    while when.strftime('%Y%m%d-%H%M%S') in taken:
        when += timedelta(seconds=1)
    stamp = when.strftime('%Y%m%d-%H%M%S')
    reason = re.sub(r'\W+', '', reason) or 'edit'
    _atomic_write_text(os.path.join(folder, f'{stamp}-{reason}.md'), text)
    _thin_snapshots(pid)
    return stamp


def read_snapshot(pid, stamp):
    """The text of one snapshot, or None if there is no such snapshot."""
    if not re.fullmatch(r'\d{8}-\d{6}', stamp or ''):
        return None
    folder = _history_folder(pid)
    for fn in os.listdir(folder) if os.path.isdir(folder) else []:
        m = _SNAP_RE.match(fn)
        if m and m.group(1) == stamp:
            try:
                return open(os.path.join(folder, fn), encoding='utf-8',
                            errors='replace').read()
            except OSError:
                return None
    return None


@app.route('/project/new-draft', methods=['POST'])
def project_new_draft():
    name = request.form.get('name', '').strip() or 'Untitled draft'
    pid = unique_project_id(slugify(name) or 'draft')
    presets = list_presets()
    ms_file = pid + '.md'
    with open(os.path.join(PROJECT_MS_DIR, ms_file), 'w',
              encoding='utf-8', newline='') as f:
        f.write(_norm_newlines(STARTER_DRAFT))
    now = datetime.now().isoformat(timespec='seconds')
    data = {
        'name': name, 'preset': presets[0]['id'] if presets else '',
        'title': name, 'subtitle': '', 'author': '', 'year': '', 'publisher': '',
        'front_matter': 'full', 'right_hand_starts': True,
        'cover_overlay': False, 'cover_color': 'light',
        'format': 'pdf', 'include_toc': False, 'smartquotes': True,
        **matter.blank(),
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
    # Normalise the line endings, and write them through untranslated.
    # A browser encodes a textarea's newlines as CRLF on submit, and a Windows
    # text-mode write then turns each of those into CR CR LF — so every autosave
    # grew the file another carriage return. Both halves are fixed here.
    text = _norm_newlines(request.form.get('text', ''))
    new_file = pid + '.md'
    _atomic_write_text(os.path.join(PROJECT_MS_DIR, new_file), text)
    snapshot_manuscript(pid, text)
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


@app.route('/project/<pid>/history')
def project_history(pid):
    """The kept versions of this project's manuscript, newest first."""
    load_project(pid)                     # 404s for an unknown project
    return jsonify({'ok': True, 'snapshots': list_snapshots(pid)})


@app.route('/project/<pid>/history/<stamp>')
def project_history_read(pid, stamp):
    """One version's text, for reading before deciding to go back to it."""
    load_project(pid)
    text = read_snapshot(pid, stamp)
    if text is None:
        return jsonify({'ok': False, 'error': 'That version is no longer kept.'}), 404
    return jsonify({'ok': True, 'text': text, 'words': _wordcount(text)})


@app.route('/project/<pid>/history/<stamp>/restore', methods=['POST'])
def project_history_restore(pid, stamp):
    """Put an older version back — after keeping the current one.

    Restoring is itself a change that could be the mistake, so the text being
    replaced is snapshotted first (forced past the interval). Going back is
    always undoable by restoring the snapshot this just made.
    """
    proj = load_project(pid)
    text = read_snapshot(pid, stamp)
    if text is None:
        return jsonify({'ok': False, 'error': 'That version is no longer kept.'}), 404
    current = _project_manuscript_text(proj, report_import=False)
    snapshot_manuscript(pid, current, reason='restore', force=True)
    new_file = pid + '.md'
    _atomic_write_text(os.path.join(PROJECT_MS_DIR, new_file), text)
    proj['manuscript_file'] = new_file
    proj['manuscript_type'] = 'markdown'
    proj['updated'] = datetime.now().isoformat(timespec='seconds')
    save_project_file(pid, proj)
    parsed = manuscript.parse_markdown(text, smartquotes=False)
    return jsonify({'ok': True, 'text': text, 'words': _wordcount(text),
                    'chapters': len(parsed['chapters']),
                    'snapshots': list_snapshots(pid)})


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
        **{k: proj.get(k, '') for k in matter.KEYS},
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
    raw, err = _project_source(proj)
    if err:
        flash(err)
        return redirect(url_for('projects'))
    meta, cover_path = _project_meta(proj)
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
            build_result = engine.build_pdf(ms_parsed, preset,
                                            os.path.join(OUT_DIR, out_name), meta,
                                            press=meta['press'])
            page_count   = build_result['page_count']
            if meta['press'] and build_result.get('press_error'):
                flash('This book has colour in it, so it was built the normal way: '
                      + build_result['press_error'])
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
    press     = _press_report(out_name, build_result)
    chapters  = len(ms_parsed['chapters'])
    return render_template('result.html', out_name=out_name, epub_name=epub_name,
                           meta=meta, preset=preset, preset_id=proj['preset'],
                           chapters=chapters, ms_path='', ms_type=ms_type,
                           cover_path=cover_path, from_project=pid, fmt=fmt,
                           spec=spec, preflight=preflight, press=press,
                           epub_preflight=_epub_preflight(epub_name))


def _project_source(proj):
    """A project's manuscript as Markdown: `(raw, '')`, or `('', reason)` if unreadable."""
    ms_type = proj.get('manuscript_type', 'file')
    ms_file = proj.get('manuscript_file', '')
    raw = None

    if ms_type == 'sample':
        raw = open(SAMPLE, encoding='utf-8').read()
    elif ms_file:
        ms_path = os.path.join(PROJECT_MS_DIR, ms_file)
        if not os.path.exists(ms_path):
            return '', 'Manuscript file not found — please replace it via Edit.'
        if ms_file.lower().endswith('.docx'):
            try:
                raw = manuscript.import_docx(ms_path)
            except Exception as exc:
                logging.error('docx import failed: %s', traceback.format_exc())
                return '', f'Could not read the Word file: {exc}'
        else:
            raw = open(ms_path, encoding='utf-8', errors='replace').read()

    if not raw:
        return '', 'No manuscript found for this project.'
    return raw, ''


def _project_meta(proj):
    """The build meta for a saved project, and the cover image path it points at."""
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
        'press':         proj.get('press', False),
        **{k: proj.get(k, '') for k in matter.KEYS},
    }
    return meta, cover_path


# ------------------------------------------------------------ send to print
# What a project remembers for its print package. The wrap's own allowances
# (turn-in, hinge, board, flap) stay at the house defaults; the cover editor's
# wrap export is still the place to hand-tune them.
PRINT_DEFAULTS = {
    'print_retailer': 'kdp', 'print_binding': 'paperback', 'print_paper': 'white',
    'print_blurb': '', 'print_flap_blurb': '', 'print_flap_bio': '',
    'print_back_file': '', 'print_back_w': 1.5, 'print_back_y': 0.4,
}
_WRAP_SUFFIX = {'paperback': '-cover-wrap', 'hardcover': '-case-wrap', 'jacket': '-jacket'}

# The two shapes a handoff package comes in. 'print' is #65 — the two PDFs a
# printer takes, flat in the folder. 'publish' (#67) adds the ebook edition and
# sorts everything into print/ and ebook/, so the two uploads can't get mixed up.
PACKAGE_SCOPES = ('print', 'publish')


def _art_resolution_check(res, w_in, h_in):
    """The check row for uploaded cover art at the size the wrap needs it.

    Flagged, never enforced, like every other row here — a writer may know the
    art is a placeholder, and a printer may take 250 dpi without complaint. But
    it says the number, because "looks fine on screen" is exactly how soft
    covers get printed.
    """
    size = f'{w_in:g}×{h_in:g}" front panel with bleed'
    if not res:
        return {'label': 'Cover art', 'ok': False,
                'detail': (f'The cover art could not be measured — check it is at least '
                           f'{int(round(w_in * 300))}×{int(round(h_in * 300))} px for the '
                           f'{size}')}
    px, need = res['px'], res['need']
    if res['ok']:
        return {'label': 'Cover art', 'ok': True,
                'detail': (f'{px[0]}×{px[1]} px — {res["dpi"]} dpi across the {size} '
                           f'(needs {need[0]}×{need[1]})')}
    return {'label': 'Cover art', 'ok': False,
            'detail': (f'{px[0]}×{px[1]} px is {res["dpi"]} dpi across the {size} — '
                       f'{"well under" if res["soft"] else "under"} the {res["want_dpi"]} dpi '
                       f'print wants, so it will print soft. '
                       f'Ask for {need[0]}×{need[1]} px or larger.')}


class PrintPackageError(ValueError):
    """A reason the package can't be built that the writer can fix in Edit."""


def build_print_package(proj, scope='print'):
    """Build everything a printer wants for a project and zip it into OUT_DIR.

    The order is the point: the interior is set first, press-ready and without
    its cover, and *its* page count sizes the spine — so the wrap can never be
    cut for a different book than the one inside it. Checks are collected, not
    enforced: a printer other than the one picked may accept what we flag.

    With ``scope='publish'`` the same build also emits the ebook edition (#67):
    the EPUB and the store-listing cover JPG, in an ``ebook/`` folder beside
    ``print/``. Both editions come out of the one parse and the one cover
    rasterisation, so the paperback and the Kindle file cannot drift apart.
    """
    publish = scope == 'publish'
    p = {**PRINT_DEFAULTS, **{k: proj[k] for k in PRINT_DEFAULTS if k in proj}}
    preset = load_preset(proj['preset'])
    raw, err = _project_source(proj)
    if err:
        raise PrintPackageError(err)
    meta, _ = _project_meta(proj)
    tpl = meta.get('cover_template_data')
    # Two kinds of cover reach a printer. A designed one paints the front panel
    # from its template; uploaded art *is* the front panel and the rest of the
    # wrap is built around it (#66). A book with no cover at all has nothing to
    # wrap the block in, and that is the only refusal left.
    art = engine._front_art(meta)
    if not art and (meta.get('cover_mode') != 'designed' or not tpl):
        raise PrintPackageError(
            f'{"Send to publish" if publish else "Send to print"} needs a cover — '
            'pick a cover template under Cover, or upload your own cover art.')
    if art:
        tpl = engine.image_wrap_template(art)

    ms = manuscript.parse_markdown(raw, smartquotes=meta.get('smartquotes', True))
    # slugify falls back to 'style', which is right for a preset and wrong on
    # every file in a print package — a title with no ASCII in it (Тайга) would
    # ship as style-interior.pdf. Fall through the project name to 'book'.
    base = (_slug_or_blank(meta['title']) or _slug_or_blank(proj.get('name', ''))
            or 'book')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    retailer = p['print_retailer'] if p['print_retailer'] in WRAP_RETAILERS else 'kdp'
    binding = p['print_binding'] if p['print_binding'] in _WRAP_SUFFIX else 'paperback'
    paper = p['print_paper'] if p['print_paper'] in _PAPER else 'white'

    # A publish package keeps the two editions in their own folders; a print
    # package stays flat, which is what a printer's upload form expects.
    pdir = 'print/' if publish else ''
    edir = 'ebook/'

    work = tempfile.mkdtemp()
    try:
        files = {}
        interior = os.path.join(work, f'{base}-interior.pdf')
        built = engine.build_pdf(ms, preset, interior, dict(meta), press=True)
        pages = built['page_count']
        files[pdir + os.path.basename(interior)] = interior

        checks = _preflight(built, preset, pages)
        if built.get('press_error'):
            checks.insert(0, {
                'label': 'Press-ready', 'ok': False,
                'detail': ('This book has colour in it, so the interior was built as an '
                           'ordinary RGB PDF: ' + built['press_error'])})
        press = engine.press_check(interior) if built.get('press') else None

        dims = _wrap_dims({'wrap_retailer': retailer, 'wrap_binding': binding,
                           'wrap_paper': paper,
                           'wrap_trim_w': preset['trim']['w'],
                           'wrap_trim_h': preset['trim']['h']}, pages)
        back = ''
        if p['print_back_file']:
            # a project file is editable by hand; this is the one print setting
            # that becomes a path, so it is read as a bare filename
            bp = os.path.join(PROJECT_MS_DIR,
                              secure_filename(os.path.basename(p['print_back_file'])))
            back = bp if os.path.exists(bp) else ''
        wmeta = dict(meta,
                     cover_blurb=p['print_blurb'],
                     cover_jacket_blurb=p['print_flap_blurb'],
                     cover_author_bio=p['print_flap_bio'],
                     cover_back_image=back,
                     cover_back_image_w=_f(p, 'print_back_w', 1.5),
                     cover_back_image_y=_f(p, 'print_back_y', 0.4))
        cf = engine._register_cover_fonts(tpl, engine.register_fonts(DEFAULTS))
        wrap = os.path.join(work, base + _WRAP_SUFFIX[binding] + '.pdf')
        wres = engine.build_cover_wrap(tpl, cf, wmeta, dims, wrap)
        files[pdir + os.path.basename(wrap)] = wrap
        for w in dims['warnings']:
            checks.append({'label': 'Cover wrap', 'ok': False, 'detail': w})

        # Uploaded art is the one thing in the package whose quality we cannot
        # set: a file that looked crisp on screen can print soft, and the only
        # place that shows is the printed copy. Measured against the rectangle
        # the wrap actually asks it to fill, bleed included.
        art_res = None
        if art:
            aw, ah = engine.front_art_size(engine.wrap_geometry(dims))
            art_res = engine.image_cover_check(art, aw, ah)
            checks.append(_art_resolution_check(art_res, aw, ah))
        if not wres['spine_text']:
            checks.append({'label': 'Spine text', 'ok': True,
                           'detail': (f'Left off — {pages} pages is under '
                                      f'{WRAP_RETAILERS[retailer]["label"]}’s minimum of '
                                      f'{WRAP_RETAILERS[retailer]["spine_text_min"]}')})

        # One rasterisation serves both editions: the file the writer uploads to
        # a store listing is byte-for-byte the cover inside the EPUB.
        front = os.path.join(work, f'{base}-cover.jpg' if publish
                             else f'{base}-front-cover.jpg')
        cover_jpg = ''
        try:
            _cover_page_jpeg(preset, meta, front)
            cover_jpg = front
            files[(edir if publish else '') + os.path.basename(front)] = front
        except Exception as exc:
            logging.exception('front cover JPG for the print package failed')
            checks.append({'label': 'Front cover image', 'ok': False,
                           'detail': (f'Could not render the store-listing JPG ({exc}) — '
                                      'the interior and wrap are unaffected')})

        epub_checks = None
        ebook_built = False
        cover_px = _cover_jpeg_size(cover_jpg) if cover_jpg else None
        if publish:
            ebook = os.path.join(work, f'{base}.epub')
            # Always the rendered JPG, and '' when it would not render — never the
            # project's own cover art. On a designed cover that art is the
            # *background plate* the template is drawn over: no title, no author.
            # Letting it through here would put a coverless-looking image on a shop
            # listing under a row that says the ebook has no cover at all. On an
            # uploaded cover (#66) the raw file is closer to a cover, but it is
            # still the one without the title overlay and uncropped to the trim —
            # the rasterised page is the cover this book has, so it is the only
            # thing that ships.
            emeta = dict(meta, cover_image=cover_jpg)
            try:
                epub.build_epub(ms, preset, ebook, emeta)
                files[edir + os.path.basename(ebook)] = ebook
                ebook_built = True
                epub_checks = _epub_checks(ebook)
                if epub_checks is None:
                    # The ebook ships either way; what it must not do is ship with
                    # the checks card simply missing, as if nothing were outstanding.
                    epub_checks = [{
                        'label': 'Ebook checks', 'ok': False,
                        'detail': ('The ebook could not be checked — it is in this '
                                   'package, but nothing here vouches for it')}]
                if not cover_jpg:
                    epub_checks.append({
                        'label': 'Ebook cover', 'ok': False,
                        'detail': ('The cover image could not be rendered, so the EPUB '
                                   'was built without one — shops want a cover')})
            except Exception as exc:
                logging.exception('EPUB for the publish package failed')
                checks.insert(0, {
                    'label': 'Ebook', 'ok': False,
                    'detail': (f'The EPUB could not be built ({exc}) — the print files '
                               'in this package are unaffected')})

        info = {
            # `publish` is what was asked for; `ebook` is what came out. Only the
            # second may promise an ebook edition on the page or the sheet.
            'scope': scope, 'publish': publish, 'ebook': ebook_built,
            'cover_kind': 'image' if art else 'designed',
            'cover_label': ('Uploaded art' if art
                            else (tpl.get('name') or meta.get('cover_template') or 'Designed')),
            'cover_art': art_res,
            'epub': (sorted(epub_checks, key=lambda c: c['ok']) if epub_checks
                     else epub_checks),
            'cover_px': cover_px,
            'title': meta['title'] or proj.get('name', ''), 'author': meta['author'],
            'retailer': retailer, 'retailer_label': WRAP_RETAILERS[retailer]['label'],
            'binding': binding, 'paper_label': _PAPER[paper]['label'],
            'trim_w': preset['trim']['w'], 'trim_h': preset['trim']['h'],
            'pages': pages, 'wrap': wres, 'bleed': dims['bleed'],
            'press_ready': bool(built.get('press')),
            'checks': sorted(checks, key=lambda c: c['ok']), 'press': press,
        }
        spec_name = 'PUBLISH-SPEC.txt' if publish else 'PRINT-SPEC.txt'
        spec = os.path.join(work, spec_name)
        with open(spec, 'w', encoding='utf-8') as f:
            f.write(_print_spec_text(info, sorted(files) + [spec_name]))
        files[spec_name] = spec

        import zipfile
        folder = f'{base}-{scope}'
        zip_name = f'{folder}-{stamp}.zip'
        with zipfile.ZipFile(os.path.join(OUT_DIR, zip_name), 'w',
                             zipfile.ZIP_DEFLATED) as z:
            for name, path in files.items():
                z.write(path, f'{folder}/{name}')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    info['zip_name'] = zip_name
    info['files'] = sorted(files)
    return info


_BINDING_LABEL = {'paperback': 'Paperback (perfect bound)',
                  'hardcover': 'Hardcover (case laminate)',
                  'jacket': 'Dust jacket'}

_UPLOAD_STEPS = {
    'kdp': [
        'In KDP, open the book’s Paperback (or Hardcover) Content page.',
        'Manuscript: upload the interior PDF.',
        'Book Cover: choose “Upload a cover you already have” and upload the wrap PDF.',
        'Make sure the trim size and paper type in KDP match this sheet — the spine was '
        'worked out from them.',
        'Launch the Previewer, fix anything it flags, and order a proof copy before '
        'you publish.',
    ],
    'ingramspark': [
        'In IngramSpark, set up the print title with the trim, binding and paper on '
        'this sheet.',
        'Upload the interior PDF as the interior file and the wrap PDF as the cover file.',
        'Generate IngramSpark’s cover template for this page count and check the spine '
        'width against it.',
        'Approve the eProof, then order a printed proof before release.',
    ],
    'generic': [
        'Send the interior PDF and the wrap PDF as separate files.',
        'Check the spine width and bleed against your printer’s own cover template for '
        'this page count.',
        'Order a printed proof before a full run.',
    ],
}


# Where the ebook half of a publish package goes. Keyed by the same retailer
# setting as the print half: both shops sell print and ebooks, and a writer who
# picked one for the paperback means the same one for the Kindle edition.
_EBOOK_STEPS = {
    'kdp': [
        'In KDP, open the book’s Kindle eBook Content page (a separate listing '
        'from the paperback, linked to it afterwards).',
        'Manuscript: upload the EPUB. KDP converts it; do not upload the print PDF.',
        'Kindle eBook Cover: choose “Upload a cover you already have” and upload '
        'the cover JPG.',
        'Use the Previewer to read a few chapters, the contents and the notes on a '
        'phone-sized screen before you publish.',
    ],
    'ingramspark': [
        'In IngramSpark, add an eBook format to the title (or set one up alongside '
        'the print title so the two share metadata).',
        'Upload the EPUB as the eBook file and the cover JPG as the eBook cover.',
        'IngramSpark validates the EPUB on upload — the checks on this sheet are the '
        'same ones, run before you got there.',
        'Approve the eProof before release.',
    ],
    'generic': [
        'The EPUB is a standard EPUB 3 file: Apple Books, Kobo, Google Play Books, '
        'Draft2Digital and Smashwords all take it as it is.',
        'Upload the cover JPG wherever the shop asks for a cover image.',
        'Read a few chapters in a real reader app before release.',
    ],
}


def _print_spec_text(info, names):
    """The plain-text sheet that travels in the package, for whoever uploads it."""
    w = info['wrap']
    lines = [
        f'{info["title"]}' + (f' — {info["author"]}' if info['author'] else ''),
        ('Publish package from Typeset Studio' if info.get('publish')
         else 'Print package from Typeset Studio'),
        '',
        'SPEC',
        f'  Printer      {info["retailer_label"]}',
        f'  Binding      {_BINDING_LABEL[info["binding"]]}',
        f'  Trim         {info["trim_w"]:g} x {info["trim_h"]:g} in',
        f'  Pages        {info["pages"]}',
        f'  Paper        {info["paper_label"]}',
        f'  Spine        {w["spine_w"]:.4f} in',
        f'  Cover wrap   {w["wrap_w"]:g} x {w["wrap_h"]:g} in (bleed {info["bleed"]:g} in)',
        f'  Spine text   {"yes" if w["spine_text"] else "no (too few pages)"}',
        f'  Cover        {info.get("cover_label", "Designed")}'
        + (f' ({info["cover_art"]["px"][0]}x{info["cover_art"]["px"][1]} px, '
           f'{info["cover_art"]["dpi"]} dpi on the front panel)'
           if info.get('cover_art') else ''),
        f'  Interior     {"press-ready (single-ink black, no cover)" if info["press_ready"] else "ordinary RGB — see checks"}',
    ]
    if info.get('ebook'):
        px = info.get('cover_px')
        lines.append('  Ebook        EPUB 3, reflowable — one file for every shop')
        lines.append(f'  Ebook cover  {px[0]}x{px[1]} px JPEG' if px else
                     '  Ebook cover  not rendered — see checks')
    lines += ['', 'FILES']
    lines += [f'  {n}' for n in names]
    if any(n.endswith('.jpg') for n in names):
        lines += ['', 'The cover JPG is the store-listing and marketing image, and it is '
                      'the cover inside the EPUB as well; printers only need the two PDFs.'
                  if info.get('ebook') else
                  'The front-cover JPG is for store listings and marketing; printers '
                  'only need the two PDFs.']
    rows = info['checks'] + (info['press'] or [])
    issues = issue_rows(rows)
    lines += ['', f'CHECKS ({len(issues)} to look at)' if issues else 'CHECKS (all clear)']
    for c in rows:
        mark = 'ok' if c['ok'] else ('--' if c.get('note') else '!!')
        lines.append(f'  [{mark}] {c["label"].strip()}: {c["detail"]}')
    if info.get('epub'):
        eissues = issue_rows(info['epub'])
        lines += ['', f'EBOOK CHECKS ({len(eissues)} to look at)' if eissues
                  else 'EBOOK CHECKS (all clear)']
        for c in info['epub']:
            mark = 'ok' if c['ok'] else ('--' if c.get('note') else '!!')
            lines.append(f'  [{mark}] {c["label"].strip()}: {c["detail"]}')
    lines += ['', 'UPLOADING THE PRINT EDITION' if info.get('ebook') else 'UPLOADING']
    lines += [f'  {i}. {s}' for i, s in enumerate(_UPLOAD_STEPS[info['retailer']], 1)]
    if info.get('ebook'):
        lines += ['', 'UPLOADING THE EBOOK EDITION']
        lines += [f'  {i}. {s}' for i, s in enumerate(_EBOOK_STEPS[info['retailer']], 1)]
    return '\n'.join(lines) + '\n'


@app.route('/project/<pid>/print-package', methods=['POST'])
def project_print_package(pid):
    proj = load_project(pid)
    scope = request.form.get('scope', 'print')
    if scope not in PACKAGE_SCOPES:
        scope = 'print'
    try:
        info = build_print_package(proj, scope)
    except PrintPackageError as exc:
        flash(str(exc))
        return redirect(url_for('project_edit', pid=pid))
    except Exception as exc:
        logging.error('print package failed: %s', traceback.format_exc())
        flash(f'{"Publish" if scope == "publish" else "Print"} package failed: {exc}')
        return redirect(url_for('projects'))
    proj['last_page_count'] = info['pages']
    # One slot for "the last handoff package", whichever kind it was — the
    # projects page offers it back as a download, and either kind supersedes.
    proj['last_print_package'] = info['zip_name']
    proj['last_package_scope'] = scope
    save_project_file(pid, proj)
    return render_template('print_package.html', pid=pid, proj=proj, info=info)


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


def _enable_context_menu(window=None):
    """Give the desktop window its right-click menu back.

    pywebview ties WebView2's default context menu to its own debug flag, so an
    installed build shipped with no context menu at all: right-clicking a word
    the spell checker had underlined offered nothing, and neither did
    right-clicking anything else. The menu is the whole of what is turned back
    on — devtools, the browser accelerator keys and the status bar stay off,
    which is why this reaches for the one setting rather than passing
    `debug=True` to `webview.start()`.

    Windows only, and it reads pywebview's internals to get there, so every step
    is guarded: if the shape of it changes the window still opens, just without
    a context menu again.

    `loaded` fires on a worker thread and CoreWebView2 may only be touched on the
    UI thread, so the change is marshalled across with `Invoke` — reaching for it
    directly raises, and the exception would be swallowed into a silent no-op.
    """
    try:
        from webview.platforms.winforms import BrowserView
        from System import Func, Object
    except Exception:
        return                                  # not the Windows/WebView2 backend

    def _turn_on(view):
        view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = True
        return True

    for inst in list(getattr(BrowserView, 'instances', {}).values()):
        try:
            view = inst.browser.webview
            view.Invoke(Func[Object](lambda v=view: _turn_on(v)))
        except Exception:
            logging.debug('could not enable the webview context menu', exc_info=True)


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
            win = webview.create_window('Typeset Studio', url,
                                        width=1180, height=820, min_size=(900, 640))
            # the WebView2 control only exists once the first page has loaded
            win.events.loaded += _enable_context_menu
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
