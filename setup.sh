#!/bin/bash
# Installs what this program needs on a Mac: Python 3.9 or newer (if missing) and the program itself.
# Safe to run again. Needs an internet connection. Uses no AI requests.
set -e
cd "$(dirname "$0")"

fail() { echo; echo "$1"; exit 1; }

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    path=$(command -v "$candidate" 2>/dev/null) || continue
    if "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "$path"
      return 0
    fi
  done
  return 1
}

echo "== 1/3 Python =="
if PYTHON=$(find_python); then
  echo "[ok] $("$PYTHON" --version) ($PYTHON)"
elif command -v brew >/dev/null 2>&1; then
  echo "Python 3.9 or newer was not found. Installing Python 3.12 with Homebrew..."
  brew install python@3.12
  PYTHON=$(find_python) || fail "Python was installed but could not be found. Close this window and double-click Start.command again."
else
  fail "Python 3.9 or newer was not found, and Homebrew is not installed.
Install Python from https://www.python.org/downloads/ (the macOS installer), then run this again."
fi

echo
echo "== 2/3 This program =="
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv

# pip downloads this program's parts from the internet. Its own messages are kept out of sight unless something
# unexpected happens. A blocked network (common at work) gets one plain explanation and a way to fix it right here.
LOG=$(mktemp)
PIP_NETWORK="--retries 2 --timeout 20"
install_program() { PYTHONWARNINGS=ignore .venv/bin/python -m pip install --quiet $PIP_NETWORK -e . >"$LOG" 2>&1; }

.venv/bin/python -m pip install --quiet $PIP_NETWORK --upgrade pip >/dev/null 2>&1 || true
echo "Installing. This takes a minute or two the first time..."
if install_program; then
  echo "[ok] installed"
elif .venv/bin/jobapply --version >/dev/null 2>&1; then
  echo "[ok] already installed (could not reach the download site to look for updates, which is fine)"
elif grep -q -E "NameResolutionError|Failed to resolve|Max retries|timed out|Connection" "$LOG"; then
  echo
  echo "This Mac cannot reach pypi.org, where this program's parts are downloaded."
  echo "- No internet? Connect, then run this again."
  echo "- On a work or school network that blocks it? Ask IT for the \"PyPI mirror\" web address and paste it below."
  echo
  read -r -p "Mirror address (or just press Enter to stop): " MIRROR || true
  [ -n "$MIRROR" ] || fail "Stopped. Run this again when you have an internet connection or the address."
  case "$MIRROR" in
    http://*|https://*) ;;
    *) fail "That does not look like a web address (it should start with https://). Run this again to retry." ;;
  esac
  .venv/bin/python -m pip config --site set global.index-url "$MIRROR" >/dev/null
  install_program || { cat "$LOG"; fail "Still could not install the program's parts. The lines above say what went wrong."; }
  echo "[ok] installed (the address is remembered for next time, inside this folder's private environment)"
else
  cat "$LOG"
  fail "Could not install the program's parts. The lines above say what went wrong."
fi

echo
echo "== 3/3 A browser =="
BROWSER=$(.venv/bin/python -c 'from jobapply.browser import find_browser; print(find_browser() or "")')
if [ -n "$BROWSER" ]; then
  echo "[ok] $BROWSER"
else
  echo "[!!] Neither BrowserOS neo nor Google Chrome was found."
  if command -v brew >/dev/null 2>&1; then
    read -r -p "Install Google Chrome now with Homebrew? (y/n) " ANSWER
    case "$ANSWER" in
      [Yy]*) brew install --cask google-chrome ;;
      *) echo "Skipped. Install Chrome from https://www.google.com/chrome/ before step 3." ;;
    esac
  else
    echo "Install Google Chrome from https://www.google.com/chrome/ before step 3."
  fi
fi

echo
echo "Installed. Opening the control panel..."
