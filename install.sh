#!/bin/sh
# codedict installer for macOS and Linux:
#   curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh
# Installs into its own folder (no sudo, no PATH changes) and turns codedict on in Claude Code.
# Run it again to update. Uninstall: ~/.codedict/venv/bin/python -m codedict setup --remove
# Optional env vars: CODEDICT_REPO (pip source), CODEDICT_HOME (install folder), CODEDICT_SETTINGS (settings.json).
set -e
REPO="${CODEDICT_REPO:-git+https://github.com/Marqueos/codedict}"
VENV="${CODEDICT_HOME:-$HOME/.codedict}/venv"

BASE=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>/dev/null; then
    BASE="$c"; break
  fi
done
[ -n "$BASE" ] || { echo "Python 3.11+ not found. Install it (https://www.python.org/downloads/) and run this again." >&2; exit 1; }

PY="$VENV/bin/python"
[ -x "$PY" ] || [ -x "$VENV/Scripts/python.exe" ] || "$BASE" -m venv "$VENV" || {
  echo "Could not create $VENV. On Debian/Ubuntu: sudo apt install python3-venv" >&2; exit 1; }
[ -x "$PY" ] || PY="$VENV/Scripts/python.exe"  # Git Bash on Windows

"$PY" -m pip install --upgrade --quiet --disable-pip-version-check "$REPO"
if [ -n "$CODEDICT_SETTINGS" ]; then "$PY" -m codedict setup --settings "$CODEDICT_SETTINGS"; else "$PY" -m codedict setup; fi

echo
echo "Done. Open Claude Code in any git project: it indexes itself and answers code questions from the index."
echo "Command line: $(dirname "$PY")/codedict"
