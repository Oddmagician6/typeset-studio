#!/usr/bin/env bash
# Start Typeset Studio on macOS or Linux. The Windows twin is run.bat.
#
# First run makes a private .venv beside this script and installs the
# requirements into it; after that it just starts the app. Nothing is installed
# system-wide.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    # 3.10+ is the floor: the app uses newer syntax than 3.9 has
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  cat <<'MSG'

Python 3.10 or newer was not found.

  macOS   brew install python   (or python.org/downloads)
  Debian  sudo apt install python3 python3-venv
  Fedora  sudo dnf install python3

Then run this file again.
MSG
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting up a private workspace. This happens once and takes a minute..."
  # Debian/Ubuntu split venv into its own package; say so rather than failing raw
  if ! "$PY" -m venv .venv; then
    echo "Could not create the virtual environment."
    echo "On Debian/Ubuntu: sudo apt install python3-venv"
    exit 1
  fi
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi

cat <<'MSG'

============================================================
 Typeset Studio is starting.
 A browser tab will open at http://127.0.0.1:5050
 Keep this window open while you work; Ctrl-C stops it.
============================================================

MSG

exec .venv/bin/python app.py
