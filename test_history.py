"""Manuscript safety tests  (run: python test_history.py).

Once a book can be written *in* the app, the file on disk is the only copy of
someone's work. Two things stand between a writer and losing it, and both are
checked here against the filesystem rather than against a return value:

* the save is **atomic** — an interrupted write leaves the old text whole,
  where a plain truncating write leaves an empty manuscript;
* every few minutes the text is **kept**, and going back to a kept version is
  itself undoable.

The autosave bug fixed in #57 is why this file leans on the destructive cases:
that one silently mangled a real project, and nothing noticed.
"""

import sys, os, io, re, json, shutil, time, tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import logging; logging.disable(logging.INFO)

import app as A

fails = []
def check(name, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + str(detail)) if not cond else ''))
    if not cond:
        fails.append(name)


PID = '_test_history_project'
MS_PATH = os.path.join(A.PROJECT_MS_DIR, PID + '.md')
HIST = A._history_folder(PID)
PROJ_JSON = os.path.join(A.PROJECT_DIR, PID + '.json')

DRAFT1 = '# One\n\nThe first draft of the chapter, which is the thing worth keeping.\n'
DRAFT2 = DRAFT1 + '\nA second paragraph, added later.\n'
DRAFT3 = '# One\n\nEverything above deleted by mistake.\n'


def cleanup():
    for p in (MS_PATH, PROJ_JSON):
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(HIST):
        shutil.rmtree(HIST)


def snap_files():
    return sorted(os.listdir(HIST)) if os.path.isdir(HIST) else []


def backdate(stamp_from, minutes):
    """Rename a snapshot to look older, so the interval and thinning are testable
    without the test sleeping for real."""
    for fn in snap_files():
        m = A._SNAP_RE.match(fn)
        if m and m.group(1) == stamp_from:
            when = datetime.strptime(stamp_from, '%Y%m%d-%H%M%S') - timedelta(minutes=minutes)
            new = when.strftime('%Y%m%d-%H%M%S') + '-' + m.group(2) + '.md'
            os.replace(os.path.join(HIST, fn), os.path.join(HIST, new))
            return new[:15]
    return None


cleanup()
try:
    # ------------------------------------------------------------ atomic write
    print('the write')
    target = os.path.join(A.PROJECT_MS_DIR, '_atomic_test.md')
    A._atomic_write_text(target, DRAFT1)
    check('writes the text', open(target, encoding='utf-8').read() == DRAFT1)
    A._atomic_write_text(target, DRAFT2)
    check('replaces it whole', open(target, encoding='utf-8').read() == DRAFT2)
    check('leaves no temp files behind',
          not [f for f in os.listdir(A.PROJECT_MS_DIR) if f.endswith('.tmp')],
          [f for f in os.listdir(A.PROJECT_MS_DIR) if f.endswith('.tmp')])

    # the case a truncating write loses: the write itself fails part-way
    class Boom(Exception):
        pass

    real_replace = os.replace
    def exploding_replace(*a, **kw):
        raise Boom('disk full')
    os.replace = exploding_replace
    try:
        A._atomic_write_text(target, 'THIS SHOULD NEVER LAND')
    except Boom:
        pass
    finally:
        os.replace = real_replace
    check('a failed write leaves the old text untouched',
          open(target, encoding='utf-8').read() == DRAFT2,
          open(target, encoding='utf-8').read()[:40])
    check('and cleans up after itself',
          not [f for f in os.listdir(A.PROJECT_MS_DIR) if f.endswith('.tmp')])
    check('newlines are written through untranslated',
          b'\r' not in open(target, 'rb').read())
    os.remove(target)

    # ------------------------------------------------------------ snapshots
    print('what gets kept')
    s1 = A.snapshot_manuscript(PID, DRAFT1)
    check('the first save is kept', s1 and len(snap_files()) == 1, snap_files())
    check('nothing is kept for text that has not changed',
          A.snapshot_manuscript(PID, DRAFT1) == '' and len(snap_files()) == 1)
    check('nor for a change inside the interval',
          A.snapshot_manuscript(PID, DRAFT2) == '' and len(snap_files()) == 1,
          snap_files())
    backdate(s1, 10)
    s2 = A.snapshot_manuscript(PID, DRAFT2)
    check('but a change after it is', s2 and len(snap_files()) == 2, snap_files())
    check('an empty editor is never kept', A.snapshot_manuscript(PID, '   ') == '')
    check('force keeps it regardless of the interval',
          A.snapshot_manuscript(PID, DRAFT3, reason='restore', force=True) != '')
    check('the reason is recorded in the name',
          any('-restore.md' in f for f in snap_files()), snap_files())

    snaps = A.list_snapshots(PID)
    check('history lists newest first',
          [s['stamp'] for s in snaps] == sorted((s['stamp'] for s in snaps), reverse=True))
    check('each version reports its size', all(s['words'] > 0 for s in snaps), snaps)
    check('a version can be read back', A.read_snapshot(PID, s2) == DRAFT2)
    check('an unknown version reads as nothing',
          A.read_snapshot(PID, '19990101-000000') is None)
    check('a malformed stamp cannot escape the folder',
          A.read_snapshot(PID, '../../../etc/passwd') is None)

    # ------------------------------------------------------------ thinning
    print('the thinning')
    cleanup()
    os.makedirs(HIST, exist_ok=True)
    now = datetime.now()
    made = []
    for mins in (2, 8, 20, 45,           # this hour: all kept
                 70, 100, 130, 200,      # earlier today: one an hour
                 1500, 1560, 3000):      # older: one a day
        when = now - timedelta(minutes=mins)
        stamp = when.strftime('%Y%m%d-%H%M%S')
        A._atomic_write_text(os.path.join(HIST, f'{stamp}-edit.md'),
                             f'# One\n\nVersion from {mins} minutes ago.\n')
        made.append((mins, stamp))
    A._thin_snapshots(PID)
    kept = {s['stamp'] for s in A.list_snapshots(PID)}
    recent = [st for mins, st in made if mins <= 45]
    check('everything from the last hour survives',
          all(st in kept for st in recent), sorted(kept))
    check('the older ones are thinned, not kept whole',
          len(kept) < len(made), (len(kept), len(made)))
    check('but each older period keeps one',
          len(kept) >= len(recent) + 2, sorted(kept))
    check('the newest of all is always there', made[0][1] in kept)

    # the hard cap
    cleanup()
    os.makedirs(HIST, exist_ok=True)
    for i in range(A.HISTORY_KEEP + 15):
        stamp = (now - timedelta(seconds=i * 30)).strftime('%Y%m%d-%H%M%S')
        A._atomic_write_text(os.path.join(HIST, f'{stamp}-edit.md'), f'# v{i}\n')
    A._thin_snapshots(PID)
    check('the cap is enforced', len(A.list_snapshots(PID)) <= A.HISTORY_KEEP,
          len(A.list_snapshots(PID)))

    # ------------------------------------------------------------ the routes
    print('the editor')
    cleanup()
    A.app.config['TESTING'] = True
    client = A.app.test_client()
    A.save_project_file(PID, {'name': 'History test', 'preset': 'classic-literary',
                              'title': 'History test', 'manuscript_file': PID + '.md',
                              'manuscript_type': 'markdown'})
    A._atomic_write_text(MS_PATH, DRAFT1)

    r = client.post(f'/project/{PID}/write/save', data={'text': DRAFT1})
    check('a save through the app is kept', r.get_json()['ok'] and len(snap_files()) == 1,
          snap_files())
    check('the file on disk is what was typed',
          open(MS_PATH, encoding='utf-8').read() == DRAFT1)

    first = A.list_snapshots(PID)[0]['stamp']
    backdate(first, 10)
    first = A.list_snapshots(PID)[0]['stamp']
    # now the writer deletes half the book and it autosaves
    client.post(f'/project/{PID}/write/save', data={'text': DRAFT3})
    check('the mistake is saved too, as it must be',
          open(MS_PATH, encoding='utf-8').read() == DRAFT3)

    j = client.get(f'/project/{PID}/history').get_json()
    check('the history route lists both', j['ok'] and len(j['snapshots']) == 2,
          j.get('snapshots'))
    j = client.get(f'/project/{PID}/history/{first}').get_json()
    check('a version can be read through the app', j['ok'] and j['text'] == DRAFT1)
    check('an unknown version 404s',
          client.get(f'/project/{PID}/history/19990101-000000').status_code == 404)

    j = client.post(f'/project/{PID}/history/{first}/restore').get_json()
    check('restoring gives the old text back', j['ok'] and j['text'] == DRAFT1, j.get('error'))
    check('and writes it to the file', open(MS_PATH, encoding='utf-8').read() == DRAFT1)
    # the guarantee is that the replaced text is still reachable — here it already
    # was, as its own autosave snapshot, so no duplicate copy is made
    check('the text the restore replaced is still in history',
          any(A.read_snapshot(PID, s['stamp']) == DRAFT3 for s in A.list_snapshots(PID)),
          [s['reason'] for s in A.list_snapshots(PID)])
    check('restoring an unknown version 404s',
          client.post(f'/project/{PID}/history/19990101-000000/restore').status_code == 404)

    # the case that matters: work done since the last snapshot, then a restore.
    # Those minutes are in no snapshot yet, and the restore is about to overwrite
    # them — this is where the forced copy earns its place.
    DRAFT4 = DRAFT1 + '\nA paragraph written in the last two minutes.\n'
    client.post(f'/project/{PID}/write/save', data={'text': DRAFT4})
    check('recent work is inside the interval, so not yet kept',
          all(A.read_snapshot(PID, s['stamp']) != DRAFT4 for s in A.list_snapshots(PID)))
    n_before = len(A.list_snapshots(PID))
    client.post(f'/project/{PID}/history/{first}/restore')
    check('restoring keeps it first, so going back is undoable',
          len(A.list_snapshots(PID)) == n_before + 1
          and any(s['reason'] == 'restore' for s in A.list_snapshots(PID)),
          [s['reason'] for s in A.list_snapshots(PID)])
    undo = next(s['stamp'] for s in A.list_snapshots(PID) if s['reason'] == 'restore')
    check('and what it kept is exactly the work that was replaced',
          A.read_snapshot(PID, undo) == DRAFT4)
    check('which restores back, so the round trip loses nothing',
          client.post(f'/project/{PID}/history/{undo}/restore').get_json()['text'] == DRAFT4)

    page = client.get(f'/project/{PID}/write').get_data(as_text=True)
    check('the editor shows the history panel', 'id="history"' in page and 'History' in page)
    check('and knows where to load it from', f'/project/{PID}/history' in page)

    # replacing the manuscript by upload: the draft it overwrites may exist
    # nowhere else, so it is kept first — the same forced copy as a restore.
    import io as _io
    UNSAVED = '# One\n\nWork done since the last version was kept.\n'
    A._atomic_write_text(MS_PATH, UNSAVED)
    n_before = len(A.list_snapshots(PID))
    client.post(f'/project/{PID}/edit', data={
        'name': 'History test', 'preset': 'classic-literary', 'title': 'History test',
        'manuscript': (_io.BytesIO(b'# Replaced\n\nA different book entirely.\n'),
                       'other.md')}, follow_redirects=True)
    check('an upload that replaces the draft keeps the draft first',
          len(A.list_snapshots(PID)) == n_before + 1
          and any(s['reason'] == 'replaced' for s in A.list_snapshots(PID)),
          [s['reason'] for s in A.list_snapshots(PID)])
    kept_stamp = next(s['stamp'] for s in A.list_snapshots(PID) if s['reason'] == 'replaced')
    check('and what it kept is the text that was there',
          A.read_snapshot(PID, kept_stamp) == UNSAVED)
    check('every kept version has its own stamp',
          len({s['stamp'] for s in A.list_snapshots(PID)}) == len(A.list_snapshots(PID)),
          [s['stamp'] for s in A.list_snapshots(PID)])
finally:
    cleanup()
    for f in list(os.listdir(A.PROJECT_MS_DIR)):
        if f.startswith(PID):
            os.remove(os.path.join(A.PROJECT_MS_DIR, f))

print('\n' + ('ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
