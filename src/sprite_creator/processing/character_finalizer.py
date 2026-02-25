"""
Character finalization utilities.

Handles expression sheet generation for completed characters.
"""

import sys
from pathlib import Path


def generate_expression_sheets_for_root(root_folder: Path) -> None:
    """
    Generate expression sheets for the given folder.

    This is used at the end of the pipeline so that a newly created character
    immediately has expression sheets available for Ren'Py scripting.

    Args:
        root_folder: Character folder or root directory containing character folders.
    """
    if not root_folder.is_dir():
        print(f"[WARN] Not generating expression sheets; '{root_folder}' is not a directory.")
        return

    try:
        # Import and call the expression sheets main function directly
        # This works in both development and frozen (PyInstaller) mode
        from tools.expression_sheets import main as run_expression_sheets

        # Temporarily set sys.argv for the expression sheets script
        original_argv = sys.argv
        sys.argv = ["expression_sheets", str(root_folder)]

        print(f"[INFO] Generating expression sheets for: {root_folder}")
        run_expression_sheets()
        print("[INFO] Expression sheets generated successfully.")

        # Restore original argv
        sys.argv = original_argv

    except Exception as e:
        print(f"[WARN] Could not generate expression sheets: {e}")
