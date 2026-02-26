# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ST Sprite Creator

Build with:
    pyinstaller sprite_creator.spec

Or use build_exe.py for a more automated process.
"""

import os
import sys
from pathlib import Path

# Detect platform
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'

# Project paths
SPEC_DIR = Path(SPECPATH)
SRC_DIR = SPEC_DIR / 'src'
PACKAGE_DIR = SRC_DIR / 'sprite_creator'

# Get certifi certificate path for SSL in frozen app
try:
    import certifi
    CERTIFI_PATH = certifi.where()
except ImportError:
    CERTIFI_PATH = None

block_cipher = None

# Analysis - find all imports
a = Analysis(
    [str(SRC_DIR / 'sprite_creator' / 'run.py')],
    pathex=[str(SRC_DIR), str(SPEC_DIR)],
    binaries=[],
    datas=[
        # Data files
        (str(PACKAGE_DIR / 'data' / 'names.csv'), 'data'),
        (str(PACKAGE_DIR / 'data' / 'reference_sprites'), 'data/reference_sprites'),
        # Tester templates only (not the _test_project - it's generated at runtime)
        (str(SPEC_DIR / 'tools' / 'tester' / 'templates'), 'tools/tester/templates'),
    ] + ([(CERTIFI_PATH, 'certifi')] if CERTIFI_PATH else []),
    hiddenimports=[
        # Core dependencies
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageFilter',
        'PIL.ImageOps',
        'pandas',
        'yaml',
        'pyyaml',
        'requests',
        'bs4',
        'beautifulsoup4',
        # SSL certificates (for SDK download in frozen app)
        'certifi',
        # rembg and its dependencies
        'rembg',
        'rembg.session_factory',
        'rembg.sessions',
        'rembg.sessions.u2net',
        'onnxruntime',
        'cv2',
        'scipy',
        'scipy.special',
        'scipy.ndimage',
        'skimage',
        'skimage.morphology',
        'pooch',
        # tkinter (usually bundled but be explicit)
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'notebook',
        'jupyter',
        'pytest',
        'sphinx',
        # Exclude heavy ML frameworks not needed by rembg (it uses onnxruntime)
        'torch',
        'torchvision',
        'torchaudio',
        'tensorflow',
        'tensorflow_hub',
        'keras',
        'jax',
        'jaxlib',
        # Exclude transformers (not needed)
        'transformers',
        'tokenizers',
        'huggingface_hub',
        # Exclude h5py (TensorFlow related)
        'h5py',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ST Sprite Creator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon if desired
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ST Sprite Creator',
)
