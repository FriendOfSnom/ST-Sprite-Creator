#!/usr/bin/env python3
"""
Entry point for PyInstaller frozen executable.

This wrapper module properly initializes the package context
so relative imports work correctly in the frozen app.
"""

import os
import sys
from pathlib import Path

# Fix for windowed (console=False) PyInstaller builds:
# sys.stdout and sys.stderr are None when there's no console,
# which crashes any library that tries to print (e.g., rembg/onnxruntime).
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Force UTF-8 encoding on stdout/stderr as early as possible.
# On non-English Windows (e.g. Japanese cp932), the default encoding can't
# handle characters like \u202f that appear in Gemini API responses,
# causing UnicodeEncodeError deep in the generation pipeline.
# errors="replace" means unencodable chars become '?' instead of crashing.
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path so 'tools/' is importable
# In frozen mode, tools are bundled at the _internal root level
if getattr(sys, 'frozen', False):
    _root = Path(sys._MEIPASS)
else:
    _root = Path(__file__).resolve().parent.parent.parent  # src/sprite_creator/run.py -> repo root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

if __name__ == "__main__":
    # Import and run the main function from the package
    from sprite_creator.__main__ import main
    main()
