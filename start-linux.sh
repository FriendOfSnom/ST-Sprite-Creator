#!/usr/bin/env bash
# start-linux.sh — Linux launcher for ST Sprite Creator
set -euo pipefail

print_header() { echo; echo "================================="; echo "  $1"; echo "================================="; echo; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
print_header "ST Sprite Creator — Linux Launcher"
echo "Working directory: $SCRIPT_DIR"

# --- Check for Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Please install Python 3.10+ using your package manager."
    echo "  Fedora/Nobara: sudo dnf install python3"
    echo "  Ubuntu/Debian: sudo apt install python3"
    echo "  Arch:          sudo pacman -S python"
    exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Found Python $PY_VERSION"

# --- Check for tkinter (must be installed via system package manager)
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "ERROR: tkinter not found. Install it with your package manager:"
    echo "  Fedora/Nobara: sudo dnf install python3-tkinter"
    echo "  Ubuntu/Debian: sudo apt install python3-tk"
    echo "  Arch:          sudo pacman -S tk"
    exit 1
fi
echo "tkinter OK"

# --- Create venv if missing
VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python3"

if [[ ! -x "$VENV_PY" ]]; then
    print_header "Creating virtual environment (.venv)"
    python3 -m venv "$VENV_DIR"
fi
echo "Using virtual environment: $VENV_DIR"

# --- Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
deactivate_on_exit() { type deactivate >/dev/null 2>&1 && deactivate || true; }
trap deactivate_on_exit EXIT

# --- Install/update deps
print_header "Installing dependencies"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install -e . --quiet
echo "Dependencies up to date."

# --- Launch
print_header "Launching ST Sprite Creator"
python -m sprite_creator

echo; echo "Done."
