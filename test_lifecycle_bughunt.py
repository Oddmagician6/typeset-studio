"""Startup, the data folder and settings  (run: python test_lifecycle_bughunt.py).

Joint bug hunt, round 5, section 24:

    24.1  the installer bundles only tracked files (no uploaded cover art)
    24.2  history pruning keeps a snapshot it couldn't read
    24.3  two saves in one second, even from two copies of the app, keep both
    24.4  seeding never replaces a file that appeared meanwhile
    24.5  a user's font under a newly bundled name is kept aside, not used
    24.6  a half-written parchment is made again
    24.7  the launchers retry an install that didn't finish
    24.8  settings changes are locked across copies of the app
    24.9  a settings file that can't be read is never written over
    24.10 the server's port is held from the moment it is chosen
    24.11 staged uploads are cleared after a while
    24.12 the clock going back doesn't stop snapshots
    24.13 a release candidate is older than its release
    24.14 a package folder left by a forced close is removed
"""

import sys, os, io, json, shutil, socket, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import logging; logging.disable(logging.CRITICAL)

import app as A
import engine
import bundle_files

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


TMP = tempfile.mkdtemp()
A.SETTINGS_PATH = os.path.join(TMP, 'settings.json')
A.HISTORY_DIR = os.path.join(TMP, 'history')
A.UPLOAD_DIR = os.path.join(TMP, 'uploads')
os.makedirs(A.UPLOAD_DIR)

# ---- 24.1 -------------------------------------------------------------------
print('24.1 only tracked files go into the installer')
repo = os.path.join(TMP, 'repo')
os.makedirs(os.path.join(repo, 'covers', 'assets'))
open(os.path.join(repo, 'covers', 'classic.json'), 'w').write('{}')
open(os.path.join(repo, 'covers', 'assets', 'private.jpg'), 'w').write('x')
open(os.path.join(repo, '.gitignore'), 'w').write('covers/assets/\n')
git = lambda *a: subprocess.run(['git', *a], cwd=repo, capture_output=True, check=True)
git('init', '-q'); git('add', '.')
datas = bundle_files.tracked_datas(['covers'], root=repo)
names = [os.path.basename(s) for s, _ in datas]
check('the tracked template is bundled', 'classic.json' in names, names)
check('the ignored cover art is not', 'private.jpg' not in names, names)
check('it lands in its own folder', all(d == 'covers' for _, d in datas), datas)
spec = open(os.path.join(HERE, 'typeset-studio.spec'), encoding='utf-8').read()
check('the spec builds its data list from tracked files', 'tracked_datas(' in spec
      and "('covers', 'covers')" not in spec)
try:
    bundle_files.tracked_datas(['covers'], root=TMP)        # not a git checkout
    check('outside a checkout the build stops', False)
except SystemExit:
    check('outside a checkout the build stops', True)

# ---- 24.2 / 24.3 / 24.12 ----------------------------------------------------
print('24.2 / 24.3 / 24.12 history')
pid = 'lifebook'
folder = A._history_folder(pid)
os.makedirs(folder)
recent = (A.datetime.now() - A.timedelta(minutes=10)).strftime('%Y%m%d-%H%M%S')
locked = os.path.join(folder, f'{recent}-edit.md')
open(locked, 'w', encoding='utf-8').write('older text')
real_open = open
def flaky_open(path, *a, **k):
    if os.path.abspath(str(path)) == os.path.abspath(locked):
        raise PermissionError(13, 'locked', path)
    return real_open(path, *a, **k)
A.open = flaky_open
try:
    A.snapshot_manuscript(pid, '# One\n\nNew text.\n', force=True)
finally:
    del A.open
check('a snapshot that could not be read survives the pruning', os.path.exists(locked))

# a second copy of the app holds a claim on the stamp this one wants
shutil.rmtree(folder); os.makedirs(folder)
now = A.datetime.now()
for k in range(3):
    st = (now + A.timedelta(seconds=k)).strftime('%Y%m%d-%H%M%S')
    open(os.path.join(folder, f'.{st}.claim'), 'w').close()
st = A.snapshot_manuscript(pid, 'first draft text', reason='conflict', force=True)
check('a stamp claimed by another copy is not taken', st and not os.path.exists(
      os.path.join(folder, f'.{st}.claim')), st)
st2 = A.snapshot_manuscript(pid, 'second draft text', reason='conflict', force=True)
files = [f for f in os.listdir(folder) if f.endswith('.md')]
check('two conflict copies in one second are both kept', len(files) == 2 and st != st2, files)
# a stamp held by a file of another reason is not reused either
shutil.rmtree(folder); os.makedirs(folder)
for k in range(5):
    st = (A.datetime.now() + A.timedelta(seconds=k)).strftime('%Y%m%d-%H%M%S')
    open(os.path.join(folder, f'{st}-edit.md'), 'w').write(f'text {k}')
before = set(os.listdir(folder))
A.open = flaky_open                         # (no path matches: nothing locked)
locked = os.path.join(folder, sorted(before)[-1])
try:
    st = A.snapshot_manuscript(pid, 'brand new text', reason='conflict', force=True)
finally:
    del A.open
check('an unreadable snapshot\'s stamp is not reused', st not in {f[:15] for f in before}
      and all(os.path.exists(os.path.join(folder, f)) for f in before), st)

shutil.rmtree(folder); os.makedirs(folder)
future = (A.datetime.now() + A.timedelta(minutes=55)).strftime('%Y%m%d-%H%M%S')
open(os.path.join(folder, f'{future}-edit.md'), 'w').write('before the clock went back')
st = A.snapshot_manuscript(pid, 'written after the clock went back')
check('a snapshot "in the future" does not stop the next one', bool(st), st)

# ---- 24.4 / 24.5 ------------------------------------------------------------
print('24.4 / 24.5 seeding')
s, d = os.path.join(TMP, 'bundled.json'), os.path.join(TMP, 'edited.json')
open(s, 'w').write('bundled'); open(d, 'w').write('the user edited this')
A._seed_copy(s, d)
check('a file that appeared meanwhile is not replaced',
      open(d).read() == 'the user edited this')
check('and no temporary copy is left', not [f for f in os.listdir(TMP) if '.seeding' in f])
os.remove(d)
A._seed_copy(s, d)
check('a missing file is seeded', open(d).read() == 'bundled')

bundle = os.path.join(TMP, 'bundle')
data_fonts = os.path.join(TMP, 'fonts')
os.makedirs(os.path.join(bundle, 'fonts')); os.makedirs(data_fonts)
open(os.path.join(bundle, 'fonts', 'Andika-Regular.ttf'), 'wb').write(b'bundled andika')
open(os.path.join(data_fonts, 'Andika-Regular.ttf'), 'wb').write(b'the user font')
real_rp, real_fd = A.resource_path, A.FONT_DIR
A.resource_path = lambda *p: os.path.join(bundle, *p)
A.FONT_DIR = data_fonts
try:
    A._seed_defaults()
    check('the bundled face takes its name',
          open(os.path.join(data_fonts, 'Andika-Regular.ttf'), 'rb').read() == b'bundled andika')
    check('the user font is kept under a new name',
          open(os.path.join(data_fonts, 'Andika-Regular-own.ttf'), 'rb').read() == b'the user font')
    check('the bundled fonts are remembered as seeded',
          'Andika-Regular.ttf' in A.load_settings().get('seeded_fonts', []))
    # once seeded, a later change in the library is the user's own: left alone
    open(os.path.join(data_fonts, 'Andika-Regular.ttf'), 'wb').write(b'changed later')
    A._seed_defaults()
    check('a seeded font changed later is not set aside again',
          open(os.path.join(data_fonts, 'Andika-Regular.ttf'), 'rb').read() == b'changed later'
          and not os.path.exists(os.path.join(data_fonts, 'Andika-Regular-own2.ttf')))
finally:
    A.resource_path, A.FONT_DIR = real_rp, real_fd
os.remove(A.SETTINGS_PATH)

# ---- 24.6 -------------------------------------------------------------------
print('24.6 parchment')
real_fig = engine.FIGURE_DIR
engine.FIGURE_DIR = os.path.join(TMP, 'figures')
os.makedirs(engine.FIGURE_DIR)
try:
    path = os.path.join(engine.FIGURE_DIR, engine.PARCHMENT)
    open(path, 'wb').write(b'\xff\xd8')                 # cut off after two bytes
    engine.ensure_parchment()
    check('a half-written parchment is made again', not engine.picture_unreadable(path)
          and os.path.getsize(path) > 10000)
    check('no partial file is left', not os.path.exists(path + '.part'))
finally:
    engine.FIGURE_DIR = real_fig

# ---- 24.7 -------------------------------------------------------------------
print('24.7 launchers')
bat = open(os.path.join(HERE, 'run.bat'), encoding='utf-8').read()
sh = open(os.path.join(HERE, 'run.sh'), encoding='utf-8').read()
check('run.bat installs until its marker is written', 'deps-installed' in bat
      and bat.index('if not exist ".venv\\deps-installed"') > bat.index('python -m venv .venv'))
check('run.sh likewise', 'if [ ! -f ".venv/deps-installed" ]' in sh
      and sh.index('echo ok > .venv/deps-installed') > sh.index('pip install -r requirements.txt'))

# ---- 24.8 / 24.9 ------------------------------------------------------------
print('24.8 / 24.9 settings')
io.open(A.SETTINGS_PATH, 'w', encoding='utf-8-sig').write(
    json.dumps({'deleted_defaults': {'presets': ['gothic']}, 'update_check': False}))
check('a settings file with a byte-order mark reads', A.load_settings().get('update_check') is False)
c = A.app.test_client()
c.post('/about/updates', data={'update_check': '1'})
got = A.load_settings()
check('a toggle keeps the other settings', got.get('update_check') is True
      and got.get('deleted_defaults') == {'presets': ['gothic']}, got)

real_read = A._read_settings
A._read_settings = lambda: (_ for _ in ()).throw(PermissionError(13, 'busy'))
before = open(A.SETTINGS_PATH, encoding='utf-8-sig').read()
try:
    r = c.post('/about/updates', data={'update_check': '0'}, follow_redirects=True)
finally:
    A._read_settings = real_read
check('a file that can\'t be read is not written over',
      open(A.SETTINGS_PATH, encoding='utf-8-sig').read() == before)
check('and the page says so', b'Could not save that setting' in r.data)

open(A.SETTINGS_PATH, 'w').write('{"update_check": tru')
with A.settings_change() as st:
    st['update_check'] = True
check('a damaged file is kept beside the new one',
      open(A.SETTINGS_PATH + '.damaged').read() == '{"update_check": tru'
      and A.load_settings() == {'update_check': True})

# another copy holds the lock: this one waits for it, then reads its write
lock = A.SETTINGS_PATH + '.lock'
open(lock, 'w').close()
def other_copy():
    time.sleep(0.3)
    A.save_settings({'update_check': True, 'deleted_defaults': {'covers': ['noir']}})
    os.remove(lock)
import threading
t = threading.Thread(target=other_copy); t.start()
with A.settings_change() as st:
    st['seeded_fonts'] = ['x.ttf']
t.join()
got = A.load_settings()
check('a change waits for another copy and keeps its write',
      got.get('deleted_defaults') == {'covers': ['noir']} and got.get('seeded_fonts') == ['x.ttf'], got)
open(lock, 'w').close()
old = time.time() - A._SETTINGS_LOCK_STALE - 5
os.utime(lock, (old, old))
with A.settings_change() as st:
    st['update_check'] = False
check('a lock left by a crash is taken over', A.load_settings().get('update_check') is False
      and not os.path.exists(lock))

# ---- 24.10 ------------------------------------------------------------------
print('24.10 ports')
a = A._bind_port(5050)
b = A._bind_port(5050)
try:
    check('a second copy is given a different port',
          a.getsockname()[1] != b.getsockname()[1], (a.getsockname(), b.getsockname()))
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', a.getsockname()[1]))
        taken = False
    except OSError:
        taken = True
    probe.close()
    check('the chosen port stays held', taken)
finally:
    a.close(); b.close()

# ---- 24.11 / 24.14 ----------------------------------------------------------
print('24.11 / 24.14 stale files')
old_up = os.path.join(A.UPLOAD_DIR, 'old-book.md')
new_up = os.path.join(A.UPLOAD_DIR, 'new-book.md')
for f in (old_up, new_up):
    open(f, 'w').write('x')
long_ago = time.time() - (A.UPLOAD_KEEP_DAYS + 1) * 86400
os.utime(old_up, (long_ago, long_ago))
old_pkg = tempfile.mkdtemp(prefix=A.PACKAGE_WORK_PREFIX)
open(os.path.join(old_pkg, 'book-interior.pdf'), 'w').write('%PDF')
new_pkg = tempfile.mkdtemp(prefix=A.PACKAGE_WORK_PREFIX)
hours_ago = time.time() - (A.PACKAGE_KEEP_HOURS + 1) * 3600
os.utime(old_pkg, (hours_ago, hours_ago))
A._sweep_stale()
check('an old staged upload is removed', not os.path.exists(old_up))
check('a fresh one stays', os.path.exists(new_up))
check('a package folder left by a forced close is removed', not os.path.exists(old_pkg))
check('one in use stays', os.path.exists(new_pkg))
shutil.rmtree(new_pkg, ignore_errors=True)
src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
check('package work folders carry the prefix', 'mkdtemp(prefix=PACKAGE_WORK_PREFIX)' in src)

# ---- 24.13 ------------------------------------------------------------------
print('24.13 versions')
check('a release is newer than its candidate', A.is_newer('1.14.10', '1.14.10rc1'))
check('a candidate is not newer than its release', not A.is_newer('1.14.10rc1', '1.14.10'))
check('1.14.10 is newer than 1.14.9', A.is_newer('1.14.10', '1.14.9'))
check('v1.10 is newer than 1.9.9', A.is_newer('v1.10', '1.9.9'))
check('the same version is not newer', not A.is_newer('1.14.2', 'v1.14.2'))
check('a beta of the next minor is newer', A.is_newer('1.15.0-beta.1', '1.14.9'))

shutil.rmtree(TMP, ignore_errors=True)
print()
print('FAILED: ' + ', '.join(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
