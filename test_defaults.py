"""Deleting a bundled style or cover template sticks  (run: python test_defaults.py).

The installed app keeps the styles and cover templates it ships with in its own
bundle and copies any that are missing into the user's data folder at each
start - so a deleted one came straight back. The user's call (2026-10-06): a
delete sticks, and a "Restore defaults" button brings them back. Checked with a
bundle folder apart from the data folder, as installed:

    STICKS    a deleted bundled style / cover is not copied back at the next start;
              one the user made is not remembered; a new one an update ships is
    RESTORE   the list page names what was deleted and offers Restore defaults;
              it brings back only what is missing (an edited one is left as edited)
    EDGES     dev (bundle and data the same folder) offers nothing; a settings file
              with the list mangled by hand is read as no list
"""

import sys, os, json, glob, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='ts-defaults-')
BUNDLE = os.path.join(tmp, 'bundle')
DATA = os.path.join(tmp, 'data')
STYLES = ['classic-literary', 'mass-market', 'thriller-crime']
COVERS = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(HERE, 'covers', '*.json')))[:2]
os.makedirs(os.path.join(BUNDLE, 'presets'))
os.makedirs(os.path.join(BUNDLE, 'covers'))
for s in STYLES:
    shutil.copy(os.path.join(HERE, 'presets', s + '.json'), os.path.join(BUNDLE, 'presets'))
for c in COVERS:
    shutil.copy(os.path.join(HERE, 'covers', c + '.json'), os.path.join(BUNDLE, 'covers'))

real_resource_path = A.resource_path
A.resource_path = lambda *parts: os.path.join(BUNDLE, *parts)
A.PRESET_DIR = os.path.join(DATA, 'presets')
A.COVER_DIR = os.path.join(DATA, 'covers')
A.FONT_DIR = os.path.join(DATA, 'fonts')
A.PROJECT_DIR = os.path.join(DATA, 'projects')
A.PROJECT_MS_DIR = os.path.join(A.PROJECT_DIR, 'manuscripts')
A.HISTORY_DIR = os.path.join(A.PROJECT_DIR, 'history')
A.OUT_DIR = os.path.join(DATA, 'out')
A.COVER_THUMB_DIR = os.path.join(A.OUT_DIR, '_cover_thumbs')
A.SETTINGS_PATH = os.path.join(DATA, 'settings.json')
for d in (A.PRESET_DIR, A.COVER_DIR, A.FONT_DIR, A.PROJECT_MS_DIR, A.HISTORY_DIR,
          A.COVER_THUMB_DIR):
    os.makedirs(d, exist_ok=True)
A.app.config['TESTING'] = True
client = A.app.test_client()

def has(folder, ident):
    return os.path.exists(os.path.join(A._data_folder(folder), ident + '.json'))

def page(url):
    return client.get(url).get_data(as_text=True)

try:
    print('[STICKS: a deleted default stays deleted]')
    A._seed_defaults()
    check('first start copies every default', all(has('presets', s) for s in STYLES)
          and all(has('covers', c) for c in COVERS))
    check('nothing to restore yet', 'Restore defaults' not in page('/'))

    client.post('/delete/mass-market', data={'confirm': '1'})
    client.post(f'/cover/delete/{COVERS[0]}', data={'confirm': '1'})
    check('the style is deleted', not has('presets', 'mass-market'))
    A._seed_defaults()                                     # the next start
    check('... and stays deleted after a restart', not has('presets', 'mass-market'))
    check('the cover stays deleted after a restart', not has('covers', COVERS[0]))
    check('the others are still there', has('presets', 'classic-literary')
          and has('covers', COVERS[1]))

    mine = A.parse_preset_form({'name': 'My own'})
    A.save_preset('my-own', mine)
    client.post('/delete/my-own', data={'confirm': '1'})
    check('a style the user made is not remembered as a default',
          A._deleted_defaults('presets') == {'mass-market'}, A._deleted_defaults('presets'))

    shutil.copy(os.path.join(HERE, 'presets', 'gothic-horror.json'),
                os.path.join(BUNDLE, 'presets'))           # an update ships a new one
    A._seed_defaults()
    check('a new default an update ships is still copied', has('presets', 'gothic-horror'))

    print('\n[RESTORE: the button brings them back]')
    styles = page('/')
    check('the styles page names the deleted default', 'Restore defaults' in styles
          and 'Mass Market Paperback' in styles.split('class="restore-bar"', 1)[-1][:600])
    check('the covers page names its deleted default', 'Restore defaults' in page('/covers'))

    edited = A.load_preset('classic-literary')
    edited['description'] = 'My edits'
    A.save_preset('classic-literary', edited)
    r = client.post('/defaults/presets/restore', follow_redirects=True)
    body = r.get_data(as_text=True)
    check('restore brings the deleted style back', has('presets', 'mass-market'))
    check('... byte for byte', open(os.path.join(A.PRESET_DIR, 'mass-market.json'), 'rb').read()
          == open(os.path.join(BUNDLE, 'presets', 'mass-market.json'), 'rb').read())
    check('... and says which', 'Restored 1 style' in body and 'Mass Market Paperback' in body)
    check('an edited default is left as edited',
          A.load_preset('classic-literary')['description'] == 'My edits')
    check('the deletion is forgotten', A._deleted_defaults('presets') == set())
    check('the bar is gone', 'Restore defaults' not in page('/'))
    check('covers are untouched by the styles button', not has('covers', COVERS[0]))
    client.post('/defaults/covers/restore')
    check('the covers button restores the cover', has('covers', COVERS[0]))
    check('restoring nothing says so', 'No styles were missing' in
          client.post('/defaults/presets/restore', follow_redirects=True).get_data(as_text=True))
    check('only styles and covers can be restored',
          client.post('/defaults/fonts/restore').status_code == 404)

    print('\n[EDGES]')
    with open(A.SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'deleted_defaults': ['mass-market']}, f)     # mangled by hand
    check('a mangled list is no list', A._deleted_defaults('presets') == set())
    client.post('/delete/mass-market', data={'confirm': '1'})
    check('... and the next delete writes a good one',
          A._deleted_defaults('presets') == {'mass-market'})
    A.resource_path = real_resource_path
    A.PRESET_DIR = os.path.join(HERE, 'presets')
    check('dev (bundle is the data) offers nothing to restore',
          A.restorable_defaults('presets') == [] and A._bundled_ids('presets') == set())
finally:
    A.resource_path = real_resource_path
    shutil.rmtree(tmp, ignore_errors=True)

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
