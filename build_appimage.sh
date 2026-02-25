#!/usr/bin/env bash
# build_appimage.sh — Build an AppImage for AI Sprite Creator
#
# Usage: bash build_appimage.sh
#
# Requirements: bash, wget/curl, file (usually pre-installed on Linux)
# Output:       dist/AI-Sprite-Creator-v<VERSION>-x86_64.AppImage
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
PYTHON_VERSION="3.12"
ARCH="x86_64"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Read version from config.py
APP_VERSION="$(python3 -c "
import re, pathlib
text = pathlib.Path('src/sprite_creator/config.py').read_text()
m = re.search(r'APP_VERSION\s*=\s*\"([^\"]+)\"', text)
print(m.group(1))
")"
echo "Building AI Sprite Creator v${APP_VERSION} AppImage"

BUILD_DIR="$SCRIPT_DIR/build/appimage"
APPDIR="$BUILD_DIR/squashfs-root"
DIST_DIR="$SCRIPT_DIR/dist"
OUTPUT_NAME="AI-Sprite-Creator-v${APP_VERSION}-${ARCH}.AppImage"

# appimagetool URL
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

print_header() { echo; echo "═══════════════════════════════════════"; echo "  $1"; echo "═══════════════════════════════════════"; echo; }

# ── Step 1: Clean & prepare ───────────────────────────────────────────────────
print_header "Step 1: Preparing build directory"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# ── Step 2: Download Python AppImage ──────────────────────────────────────────
print_header "Step 2: Downloading Python ${PYTHON_VERSION} AppImage"

# Resolve the latest manylinux2014 x86_64 AppImage filename from GitHub API
echo "Querying GitHub for latest Python ${PYTHON_VERSION} AppImage..."
PY_APPIMAGE_NAME="$(curl -sL "https://api.github.com/repos/niess/python-appimage/releases/tags/python${PYTHON_VERSION}" \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset['name']
    if 'manylinux2014_x86_64' in name and name.endswith('.AppImage'):
        print(name)
        break
")"
if [[ -z "$PY_APPIMAGE_NAME" ]]; then
    echo "ERROR: Could not find Python ${PYTHON_VERSION} AppImage on GitHub."
    exit 1
fi
PY_APPIMAGE_URL="https://github.com/niess/python-appimage/releases/download/python${PYTHON_VERSION}/${PY_APPIMAGE_NAME}"
PY_APPIMAGE="$BUILD_DIR/$PY_APPIMAGE_NAME"

echo "Found: $PY_APPIMAGE_NAME"
if [[ ! -f "$PY_APPIMAGE" ]]; then
    echo "Downloading from: $PY_APPIMAGE_URL"
    wget -q --show-progress -O "$PY_APPIMAGE" "$PY_APPIMAGE_URL"
else
    echo "Using cached: $PY_APPIMAGE"
fi
chmod +x "$PY_APPIMAGE"

# ── Step 3: Extract Python AppImage ───────────────────────────────────────────
print_header "Step 3: Extracting Python AppImage"
cd "$BUILD_DIR"
"./$PY_APPIMAGE_NAME" --appimage-extract >/dev/null 2>&1
cd "$SCRIPT_DIR"
echo "Extracted to: $APPDIR"

# Locate the Python binary inside the AppDir
APPDIR_PYTHON="$APPDIR/opt/python${PYTHON_VERSION}/bin/python${PYTHON_VERSION}"
if [[ ! -x "$APPDIR_PYTHON" ]]; then
    echo "ERROR: Python binary not found at $APPDIR_PYTHON"
    exit 1
fi
echo "Python binary: $APPDIR_PYTHON"

# ── Step 4: Install dependencies ──────────────────────────────────────────────
print_header "Step 4: Installing dependencies"
"$APPDIR_PYTHON" -m pip install --upgrade pip --quiet
"$APPDIR_PYTHON" -m pip install -r requirements.txt --quiet
echo "Dependencies installed."

# ── Step 5: Install the sprite_creator package ────────────────────────────────
print_header "Step 5: Installing sprite_creator package"
"$APPDIR_PYTHON" -m pip install . --quiet
echo "Package installed."

# ── Step 6: Copy tools/ directory ─────────────────────────────────────────────
print_header "Step 6: Bundling tools/ directory"
SITE_PACKAGES="$APPDIR/opt/python${PYTHON_VERSION}/lib/python${PYTHON_VERSION}/site-packages"
# Copy tools/ but exclude runtime artifacts, caches, and SDK downloads
# Mirrors the Windows .spec which only bundles source + templates (not _test_project)
rsync -a \
    --exclude='_test_project' \
    --exclude='__pycache__' \
    --exclude='renpy-*-sdk' \
    --exclude='*.pyc' \
    "$SCRIPT_DIR/tools/" "$SITE_PACKAGES/tools/"
echo "Copied tools/ to site-packages (excluding runtime artifacts)."

# ── Step 7: Create entrypoint ─────────────────────────────────────────────────
print_header "Step 7: Creating entrypoint"
cat > "$APPDIR/entrypoint.sh" << 'ENTRY'
#!/bin/bash
# AI Sprite Creator AppImage entrypoint
APPDIR="$(dirname "$(readlink -f "$0")")"
PYTHON_VERSION="3.12"
PYTHON_BIN="$APPDIR/opt/python${PYTHON_VERSION}/bin/python${PYTHON_VERSION}"

# Ensure tools/ is importable
SITE_PACKAGES="$APPDIR/opt/python${PYTHON_VERSION}/lib/python${PYTHON_VERSION}/site-packages"
export PYTHONPATH="${SITE_PACKAGES}:${PYTHONPATH:-}"

exec "$PYTHON_BIN" -m sprite_creator "$@"
ENTRY
chmod +x "$APPDIR/entrypoint.sh"
echo "Entrypoint created."

# ── Step 8: Set up .desktop file and icon ─────────────────────────────────────
print_header "Step 8: Configuring desktop integration"

# Copy our .desktop and icon, replacing the default python ones
cp "$SCRIPT_DIR/appimage/sprite-creator.desktop" "$APPDIR/sprite-creator.desktop"
cp "$SCRIPT_DIR/appimage/sprite-creator.png" "$APPDIR/sprite-creator.png"

# Remove the default python .desktop and icon so appimagetool uses ours
rm -f "$APPDIR"/python*.desktop
rm -f "$APPDIR"/python*.png

# Patch the existing AppRun to launch our app instead of bare python
# The original AppRun sets up TCL_LIBRARY, TK_LIBRARY, SSL_CERT_FILE, APPDIR
# We keep all that and just change the final exec line
sed -i 's|"$APPDIR/opt/python3.12/bin/python3.12" "$@"|exec "$APPDIR/entrypoint.sh" "$@"|' "$APPDIR/AppRun"

echo "Desktop integration configured."

# ── Step 9: Download appimagetool and package ─────────────────────────────────
print_header "Step 9: Packaging AppImage"
APPIMAGETOOL="$BUILD_DIR/appimagetool-${ARCH}.AppImage"
if [[ ! -f "$APPIMAGETOOL" ]]; then
    echo "Downloading appimagetool..."
    wget -q --show-progress -O "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
fi
chmod +x "$APPIMAGETOOL"

# Package the AppDir into an AppImage
ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$DIST_DIR/$OUTPUT_NAME"

# ── Done ──────────────────────────────────────────────────────────────────────
print_header "Build Complete!"
APPIMAGE_PATH="$DIST_DIR/$OUTPUT_NAME"
if [[ -f "$APPIMAGE_PATH" ]]; then
    SIZE_MB=$(du -m "$APPIMAGE_PATH" | cut -f1)
    echo "Output:   $APPIMAGE_PATH"
    echo "Size:     ${SIZE_MB} MB"
    echo ""
    echo "To run:"
    echo "  chmod +x \"$APPIMAGE_PATH\""
    echo "  ./$OUTPUT_NAME"
else
    echo "ERROR: AppImage not found at expected location!"
    exit 1
fi
