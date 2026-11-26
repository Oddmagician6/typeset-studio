"""Which of the repository's data files go into the PyInstaller bundle.

Only files git tracks are shipped. The working folders (covers/, presets/,
fonts/, ...) also collect things a source run adds: uploaded cover art under
covers/assets/, user styles, user fonts. Git ignores those, and a build made
from a checkout that has been used must never carry them into an installer.
"""

import os
import subprocess


def tracked_files(folder, root='.'):
    """The paths (relative to `root`) git tracks under `folder`. Raises
    SystemExit when git can't answer: guessing could ship private files."""
    try:
        out = subprocess.run(['git', 'ls-files', '-z', '--', folder], cwd=root,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f'bundle_files: cannot list the tracked files in {folder!r} '
                         f'({e}); build from a git checkout.')
    paths = [p for p in out.decode('utf-8').split('\0') if p]
    return [p for p in paths if os.path.isfile(os.path.join(root, p))]


def tracked_datas(folders, root='.'):
    """PyInstaller `datas` entries for the tracked files under each folder,
    each landing at its own relative folder inside the bundle."""
    datas = []
    for folder in folders:
        files = tracked_files(folder, root)
        if not files:
            raise SystemExit(f'bundle_files: no tracked files in {folder!r}')
        for p in files:
            datas.append((os.path.join(root, p), os.path.dirname(p).replace('\\', '/')))
    return datas
