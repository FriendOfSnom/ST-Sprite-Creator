"""Allow running the tester as: python -m tools.tester <character_folder>"""

import sys
from pathlib import Path
from . import launch_sprite_tester

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tools.tester <character_folder>")
        sys.exit(1)

    char_path = Path(sys.argv[1])
    if not char_path.exists():
        print(f"Error: Character folder not found: {char_path}")
        sys.exit(1)

    launch_sprite_tester(char_path)