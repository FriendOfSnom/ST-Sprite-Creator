"""
Sprite Tester Module

Launches a minimal Ren'Py project to test newly created character sprites
using the Student Transfer character loading system. This validates that
the ST folder structure, character.yml, and custom transitions work correctly.

The test project is generated on-demand and uses the exact same character
loading code that Student Transfer uses (init -60/-50/-40 blocks).
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
import yaml
from PIL import Image as PILImage

from .sdk_utils import SDK_VERSION, SDK_FOLDER_NAME, download_and_setup_sdk
from sprite_creator.config import get_resource_path
from sprite_creator.logging_utils import log_info, log_error, log_warning, log_debug



def _get_writable_base() -> Path:
    """Get a writable base directory for project root operations."""
    if getattr(sys, 'frozen', False):
        # Frozen - use user's home directory
        return Path.home() / ".sprite_creator"
    else:
        # Development - use project root (tools/tester/__init__.py -> tools/tester -> tools -> repo root)
        return Path(__file__).parent.parent.parent


# Paths relative to this module (frozen-app compatible)
MODULE_DIR = Path(__file__).resolve().parent  # tools/tester/

# Template files (bundled with tester for standalone operation)
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Writable paths (for SDK and test project)
WRITABLE_BASE = _get_writable_base()

# Ensure writable base directory exists for frozen app
try:
    WRITABLE_BASE.mkdir(parents=True, exist_ok=True)
    # Log at module load time (logging may not be initialized yet)
    print(f"[Sprite Tester] Writable base: {WRITABLE_BASE}")
except Exception as e:
    print(f"[WARN] Could not create writable base directory {WRITABLE_BASE}: {e}")

# Ren'Py SDK location - check environment variable first, then default
SDK_DIR = Path(os.environ.get("RENPY_SDK_PATH", WRITABLE_BASE / SDK_FOLDER_NAME))

# Test project directory - use a temp directory for writable output
def _get_test_project_dir() -> Path:
    """Get the test project directory (writable location)."""
    if getattr(sys, 'frozen', False):
        # Frozen - use temp directory
        return Path(tempfile.gettempdir()) / "sprite_creator_test"
    else:
        # Development - use the existing location
        return Path(__file__).parent / "_test_project"

TEST_PROJECT_DIR = _get_test_project_dir()


def find_renpy_executable() -> Path | None:
    """Find the Ren'Py executable for the current platform."""
    if not SDK_DIR.exists():
        return None

    if platform.system() == "Windows":
        exe = SDK_DIR / "renpy.exe"
    else:
        exe = SDK_DIR / "renpy.sh"

    return exe if exe.exists() else None


def get_template_files() -> list[tuple[str, Path]]:
    """Get list of template files to copy."""
    files = [
        ("character.py", TEMPLATES_DIR / "character.py"),
        ("body.py", TEMPLATES_DIR / "body.py"),
        ("char_sprites.py", TEMPLATES_DIR / "char_sprites.py"),
        ("filtered_image.py", TEMPLATES_DIR / "filtered_image.py"),
        ("pymage_size.py", TEMPLATES_DIR / "pymage_size.py"),
        ("effects.rpy", TEMPLATES_DIR / "effects.rpy"),
    ]
    return [(name, path) for name, path in files if path.exists()]


def scan_character_folder(char_dir: Path) -> dict:
    """
    Scan the character folder to discover all poses, outfits, and expressions.
    Also determines the sprite dimensions from the first image found.
    Returns a dict with the discovered structure.
    """
    result = {
        "poses": {},
        "outfits": [],
        "expressions": [],
        "sprite_size": (832, 1248),  # Default, will be overwritten if we find an image
    }

    first_image_found = False

    # Scan for pose directories (single letters like 'a', 'b', 'c')
    for item in char_dir.iterdir():
        if item.is_dir() and len(item.name) == 1 and item.name.isalpha():
            pose_name = item.name
            pose_data = {
                "outfits": [],
                "faces": {},
            }

            # Scan outfits directory
            outfits_dir = item / "outfits"
            if outfits_dir.exists():
                for outfit_file in outfits_dir.iterdir():
                    if outfit_file.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                        outfit_name = outfit_file.stem
                        outfit_ext = outfit_file.suffix  # Store actual extension
                        pose_data["outfits"].append((outfit_name, outfit_ext))
                        if outfit_name not in result["outfits"]:
                            result["outfits"].append(outfit_name)

                        # Get image dimensions from first image found
                        if not first_image_found:
                            try:
                                with PILImage.open(outfit_file) as img:
                                    result["sprite_size"] = img.size
                                first_image_found = True
                            except Exception:
                                pass

            # Scan faces directory
            faces_dir = item / "faces"
            if faces_dir.exists():
                for face_subdir in faces_dir.iterdir():
                    if face_subdir.is_dir():
                        outfit_name = face_subdir.name
                        if outfit_name == "face":
                            outfit_name = ""  # Base outfit

                        expressions = []
                        for expr_file in face_subdir.iterdir():
                            if expr_file.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                                try:
                                    expr_idx = int(expr_file.stem)
                                    expr_ext = expr_file.suffix  # Store actual extension
                                    expressions.append((expr_idx, expr_ext))

                                    # Get image dimensions from first image found
                                    if not first_image_found:
                                        try:
                                            with PILImage.open(expr_file) as img:
                                                result["sprite_size"] = img.size
                                            first_image_found = True
                                        except Exception:
                                            pass
                                except ValueError:
                                    pass

                        if expressions:
                            # Sort by index, preserving the extension
                            pose_data["faces"][outfit_name] = sorted(expressions, key=lambda x: x[0])

            result["poses"][pose_name] = pose_data

    return result


def sanitize_var_name(name: str) -> str:
    """Convert a name to a valid Python variable name."""
    import re
    # Replace hyphens and spaces with underscores
    sanitized = name.replace("-", "_").replace(" ", "_")
    # Remove any other invalid characters
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)
    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized


def generate_test_script(char_name: str, char_data: dict, char_dir: Path) -> str:
    """
    Generate the script.rpy content for the test project.

    This generates Ren'Py code that matches Student Transfer's exact pattern:
    1. Creates Body/Pose objects in init -50
    2. Creates Person objects in init -40
    3. Registers images with define_sprite() in init -30 (like ST's script.rpy)
    4. Uses standard 'show' statements (not 'show expression')
    """
    # Create a valid Python variable name from the character name
    var_name = sanitize_var_name(char_name)

    display_name = char_data.get("display_name", char_name)
    scale = char_data.get("scale", 1.0)
    eye_line = char_data.get("eye_line", 0.5)
    name_color = char_data.get("name_color", "#ffffff")

    # Get poses from character.yml
    poses_config = char_data.get("poses", {})

    # Scan the actual folder structure
    folder_data = scan_character_folder(char_dir)

    # Get actual sprite dimensions
    sprite_width, sprite_height = folder_data["sprite_size"]
    sprite_center_x = sprite_width // 2
    # Use a reasonable anchor point near the top of the head
    sprite_center_y = int(sprite_height * 0.08)

    # Build outfit and expression lists
    all_outfits = folder_data["outfits"]
    first_pose = list(folder_data["poses"].keys())[0] if folder_data["poses"] else "a"

    # Generate the outfit registration code
    outfit_registrations = []
    face_registrations = []

    for pose_name, pose_data in folder_data["poses"].items():
        for outfit_name, outfit_ext in pose_data["outfits"]:
            outfit_path = f"images/characters/{char_name}/{pose_name}/outfits/{outfit_name}{outfit_ext}"
            outfit_registrations.append(f'    body.add_outfit("{pose_name}", "{outfit_name}", "{outfit_path}")')

        for face_outfit, expressions in pose_data["faces"].items():
            face_folder = "face" if not face_outfit else face_outfit
            for expr_idx, expr_ext in expressions:
                face_path = f"images/characters/{char_name}/{pose_name}/faces/{face_folder}/{expr_idx}{expr_ext}"
                if face_outfit:
                    face_registrations.append(
                        f'    body.add_face("{pose_name}", "{expr_idx}", BodyImageQualifier(body, {{"$": "{face_outfit}"}}), False, "{face_path}")'
                    )
                else:
                    face_registrations.append(
                        f'    body.add_face("{pose_name}", "{expr_idx}", BodyImageQualifier(body), False, "{face_path}")'
                    )

    outfit_code = "\n".join(outfit_registrations) if outfit_registrations else "    pass"
    face_code = "\n".join(face_registrations) if face_registrations else "    pass"

    # Build pose creation code
    pose_creations = []
    for pose_name in folder_data["poses"].keys():
        facing = poses_config.get(pose_name, {}).get("facing", "right")
        direction = 1 if facing == "right" else -1
        pose_creations.append(
            f'    body.add_pose(Pose("{pose_name}", ({sprite_width}, {sprite_height}), ({sprite_center_x}, {sprite_center_y}), {direction}))'
        )
    pose_code = "\n".join(pose_creations) if pose_creations else f'    body.add_pose(Pose("a", ({sprite_width}, {sprite_height}), ({sprite_center_x}, {sprite_center_y}), 1))'

    script = f'''# Auto-generated test script for sprite validation
# Character: {char_name}
# Uses the exact same pattern as Student Transfer

# ============================================================================
# GUI Init - Set screen resolution to match Student Transfer (1280x720)
# ============================================================================

init python:
    gui.init(1280, 720)

# ============================================================================
# Config - Disable developer mode and quit confirmation for clean testing
# ============================================================================

init -100 python:
    config.developer = False
    config.quit_action = Quit(confirm=False)
    # Skip the main menu and go directly to the game
    config.main_menu_music = None

# Skip main menu - jump directly to start
label main_menu:
    jump start

# ============================================================================
# Body Setup (init -50, same as ST)
# ============================================================================

init -50 python:
    from body import Body, Pose, BodyImageQualifier
    from filtered_image import FilterProperties
    from renpy.character import ADVCharacter

    # Initialize screenfilter (required by char_sprites.py)
    screenfilter = FilterProperties()

    # Create base ADV character (template for Person characters)
    adv = ADVCharacter(None)

    # Required store variables for standalone operation
    coordinate_grid_key_presses = 0
    phone_images = []
    protagonist = ""

    # Character storage (same as ST)
    bodies = {{}}
    characters = {{}}
    all_emotions = set()
    all_outfits = set()

    # Create Body for {char_name}
    body = Body(
        color="{name_color}",
        scale={scale},
        voice=None,
        default_outfit="{all_outfits[0] if all_outfits else ''}",
        eye_line={eye_line}
    )

    # Add poses
{pose_code}

    # Add outfits
{outfit_code}

    # Add faces (expressions)
{face_code}

    # Set body size and register
    body.set_size({sprite_width}, {sprite_height})
    for pose in body.poses.values():
        pose.init_size({sprite_center_x}, {sprite_height})

    bodies["{var_name}"] = body
    characters["{var_name}"] = "{display_name}"
    all_outfits.update(body.all_outfits)
    # Populate all_emotions from body.all_expressions (ST pattern)
    all_emotions.update(body.all_expressions)

# ============================================================================
# Person Creation (init -40, same as ST)
# ============================================================================

init -40 python:
    from char_sprites import Person

    {var_name} = Person("{var_name}", "{display_name}", "{var_name}")

# ============================================================================
# Image Registration (init -30, same as ST's script.rpy)
# ============================================================================

init -30 python:
    from char_sprites import CharacterSprite, define_sprite

    # Register images for each character/emotion combination (exactly like ST)
    for person_name in characters.keys():
        for emotion in all_emotions:
            define_sprite((person_name, emotion), CharacterSprite(person_name, emotion, False))
            define_sprite((person_name, emotion, 'blush'), CharacterSprite(person_name, emotion, True))

# ============================================================================
# Test Variables
# ============================================================================

init python:
    # Exchange transition (from ST effects.rpy)
    renpy.store.exchange = {{"master": Dissolve(0.18)}}

    # Background options: (display_name, is_solid, color_or_path)
    # Solid colors first, then image backgrounds from backgrounds/ folder
    test_backgrounds = [
        ("Black", True, "#1a1a2e"),
        ("White", True, "#ffffff"),
        ("Gray", True, "#808080"),
    ]

    # Add image backgrounds (will be loaded at runtime)
    import os
    bg_dir = os.path.join(config.gamedir, "backgrounds")
    if os.path.isdir(bg_dir):
        for fname in sorted(os.listdir(bg_dir)):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                display_name = os.path.splitext(fname)[0].replace("_", " ").title()
                bg_path = "backgrounds/" + fname
                test_backgrounds.append((display_name, False, bg_path))

    current_bg_idx = 0

    def get_current_bg_name():
        return test_backgrounds[current_bg_idx][0] if test_backgrounds else "Black"

    def cycle_background(direction):
        global current_bg_idx
        current_bg_idx = (current_bg_idx + direction) % len(test_backgrounds)
        update_background()

    def update_background():
        bg_name, is_solid, value = test_backgrounds[current_bg_idx]
        if is_solid:
            renpy.scene()
            renpy.show("bg_solid", what=Solid(value))
        else:
            renpy.scene()
            renpy.show("bg_image", what=Image(value))
        # Re-show the character on top
        update_sprite_no_transition()
        renpy.restart_interaction()

    def update_sprite_no_transition():
        # Show sprite without transition (used after background change)
        {var_name}.outfit = get_current_outfit()
        renpy.show("{var_name} " + get_current_emotion(), at_list=[sprite_center])

    # Test state
    test_char_name = "{var_name}"
    test_poses = sorted(bodies["{var_name}"].poses.keys()) if "{var_name}" in bodies else ["a"]
    current_pose_idx = 0
    current_expr_idx = 0
    current_outfit_idx = 0

    def get_current_pose():
        return test_poses[current_pose_idx] if test_poses else "a"

    def get_outfit_list():
        """Get list of outfits available for current pose."""
        pose_name = get_current_pose()
        body = bodies.get("{var_name}")
        if body and pose_name in body.poses:
            return sorted(body.poses[pose_name].outfits.keys())
        return []

    def get_current_outfit():
        """Get the currently selected outfit name."""
        outfits = get_outfit_list()
        if outfits and current_outfit_idx < len(outfits):
            return outfits[current_outfit_idx]
        elif outfits:
            return outfits[0]
        return ""

    def get_expression_keys():
        """Get sorted list of actual expression keys (e.g., [0, 1, 7, 14]) for current pose."""
        pose_name = get_current_pose()
        body = bodies.get("{var_name}")
        if body and pose_name in body.poses:
            # Get actual expression keys, sorted numerically
            keys = sorted(body.poses[pose_name].faces.keys(), key=lambda x: int(x) if str(x).isdigit() else 999)
            return keys if keys else [0]
        return [0]

    def get_current_expression_key():
        """Get the actual expression key at current_expr_idx."""
        keys = get_expression_keys()
        if current_expr_idx < len(keys):
            return keys[current_expr_idx]
        return keys[0] if keys else 0

    def get_current_emotion():
        return "{{}}_{{}}".format(get_current_pose(), get_current_expression_key())

    def cycle_pose(direction):
        global current_pose_idx, current_expr_idx, current_outfit_idx
        # Remember current expression KEY before changing pose
        old_outfit = get_current_outfit()
        old_expr_key = get_current_expression_key()
        current_pose_idx = (current_pose_idx + direction) % len(test_poses)
        # Try to keep same outfit if it exists in new pose
        new_outfits = get_outfit_list()
        if old_outfit in new_outfits:
            current_outfit_idx = new_outfits.index(old_outfit)
        else:
            current_outfit_idx = 0
        # Try to keep same expression KEY if it exists in new pose
        new_keys = get_expression_keys()
        if old_expr_key in new_keys:
            current_expr_idx = new_keys.index(old_expr_key)
        else:
            # Fall back to expression 0 if it exists, otherwise first available
            if 0 in new_keys:
                current_expr_idx = new_keys.index(0)
            else:
                current_expr_idx = 0
        update_sprite()

    def cycle_expression(direction):
        global current_expr_idx
        keys = get_expression_keys()
        current_expr_idx = (current_expr_idx + direction) % len(keys)
        update_sprite()

    def cycle_outfit(direction):
        global current_outfit_idx
        outfits = get_outfit_list()
        if outfits:
            current_outfit_idx = (current_outfit_idx + direction) % len(outfits)
            update_sprite()

    def update_sprite():
        # Update outfit and show new sprite with exchange transition
        {var_name}.outfit = get_current_outfit()
        renpy.show("{var_name} " + get_current_emotion(), at_list=[sprite_center])
        renpy.with_statement(exchange)
        renpy.restart_interaction()

# ============================================================================
# Character Transform (bottom-center positioning like ST)
# ============================================================================

transform sprite_center:
    xalign 0.5
    yalign 1.0

# ============================================================================
# Test Screen (simplified controls)
# ============================================================================

screen sprite_test():
    # Modal screen to capture all keyboard/mouse input
    modal True

    # Note: No solid background here - let the sprite show through
    # The sprite is shown on the master layer before this screen is called

    # Info panel
    frame:
        xalign 0.5
        ypos 20
        padding (20, 10)
        background Frame(Solid("#2d2d44"), 5, 5)

        vbox:
            spacing 5
            text "Sprite Tester" size 24 color "#ffffff" xalign 0.5
            text "Character: {display_name}" size 18 color "#aaaaaa" xalign 0.5
            hbox:
                xalign 0.5
                spacing 20
                text "Pose: [get_current_pose()]" size 16 color "#88ff88"
                text "Outfit: [get_current_outfit()]" size 16 color "#88ff88"
                text "Expression: [get_current_expression_key()]" size 16 color "#88ff88"
            hbox:
                xalign 0.5
                spacing 20
                text "Emotion: [get_current_emotion()]" size 14 color "#ffff88"
                text "Background: [get_current_bg_name()]" size 14 color "#88ffff"

    # Controls
    frame:
        xalign 0.5
        yalign 1.0
        yoffset -20
        padding (20, 15)
        background Frame(Solid("#2d2d44"), 5, 5)

        vbox:
            spacing 10
            hbox:
                xalign 0.5
                spacing 12
                textbutton "< Pose" action Function(cycle_pose, -1)
                textbutton "Pose >" action Function(cycle_pose, 1)
                null width 10
                textbutton "< Outfit" action Function(cycle_outfit, -1)
                textbutton "Outfit >" action Function(cycle_outfit, 1)
                null width 10
                textbutton "< Expr" action Function(cycle_expression, -1)
                textbutton "Expr >" action Function(cycle_expression, 1)
                null width 10
                textbutton "< BG" action Function(cycle_background, -1)
                textbutton "BG >" action Function(cycle_background, 1)

            text "L/R=Pose | Home/End=Outfit | U/D=Expr | PgUp/Dn=BG | Esc=Exit" size 13 color "#888888" xalign 0.5
            textbutton "Exit" action Return(True) xalign 0.5

    # Keyboard shortcuts (pygame key constants)
    key "K_LEFT" action Function(cycle_pose, -1)
    key "K_RIGHT" action Function(cycle_pose, 1)
    key "K_HOME" action Function(cycle_outfit, -1)
    key "K_END" action Function(cycle_outfit, 1)
    key "K_UP" action Function(cycle_expression, 1)
    key "K_DOWN" action Function(cycle_expression, -1)
    key "K_PAGEUP" action Function(cycle_background, -1)
    key "K_PAGEDOWN" action Function(cycle_background, 1)
    key "K_ESCAPE" action Return(True)

# ============================================================================
# Main Label
# ============================================================================

label start:
    # Set initial background (uses test_backgrounds[0])
    $ bg_name, is_solid, value = test_backgrounds[current_bg_idx]
    if is_solid:
        scene expression Solid(value)
    else:
        scene expression Image(value)

    # Set initial outfit and show character
    $ {var_name}.outfit = get_current_outfit()
    $ renpy.show("{var_name} " + get_current_emotion(), at_list=[sprite_center])

    # Show the test screen - it stays up until Exit is pressed
    # Navigation buttons update the sprite directly via update_sprite()
    call screen sprite_test()

    return
'''
    return script


def create_test_project(char_dir: Path) -> Path | None:
    """
    Create or update the test Ren'Py project for the given character.

    Returns the path to the test project, or None if creation failed.
    """
    # Validate character directory
    char_yml = char_dir / "character.yml"
    if not char_yml.exists():
        print(f"[ERROR] No character.yml found in {char_dir}")
        messagebox.showerror("Error", f"No character.yml found in:\n{char_dir}")
        return None

    # Load character data
    try:
        with open(char_yml, 'r', encoding='utf-8') as f:
            char_data = yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read character.yml: {e}")
        messagebox.showerror("Error", f"Failed to read character.yml:\n{e}")
        return None

    char_name = char_dir.name

    # Create test project structure
    game_dir = TEST_PROJECT_DIR / "game"
    images_dir = game_dir / "images" / "characters"

    # Clean and recreate
    try:
        if TEST_PROJECT_DIR.exists():
            shutil.rmtree(TEST_PROJECT_DIR)
        images_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[ERROR] Failed to create test project directory: {e}")
        messagebox.showerror("Error", f"Failed to create test project directory:\n{TEST_PROJECT_DIR}\n\n{e}")
        return None

    # Copy template files
    template_files = get_template_files()
    if not template_files:
        print(f"[ERROR] No template files found in {TEMPLATES_DIR}")
        messagebox.showerror(
            "Missing Templates",
            f"Required template files not found in:\n{TEMPLATES_DIR}\n\n"
            "Please ensure the sprite creator is properly installed."
        )
        return None

    for filename, src_path in template_files:
        dst_path = game_dir / filename
        shutil.copy2(src_path, dst_path)
        print(f"[INFO] Copied template: {filename}")

    # Copy background files for preview
    backgrounds_src = get_resource_path("data/reference_sprites/backgrounds")
    backgrounds_dst = game_dir / "backgrounds"
    if backgrounds_src.exists():
        backgrounds_dst.mkdir(parents=True, exist_ok=True)
        for bg_file in backgrounds_src.iterdir():
            if bg_file.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                shutil.copy2(bg_file, backgrounds_dst / bg_file.name)
                print(f"[INFO] Copied background: {bg_file.name}")

    # Patch effects.rpy to add missing imports (math, random)
    # In full ST these are imported elsewhere, but our minimal project needs them
    effects_path = game_dir / "effects.rpy"
    if effects_path.exists():
        with open(effects_path, 'r', encoding='utf-8') as f:
            effects_content = f.read()

        # Add imports right after "init -100 python:"
        if "import math" not in effects_content:
            effects_content = effects_content.replace(
                "init -100 python:\n",
                "init -100 python:\n    import math\n    import random\n"
            )
            with open(effects_path, 'w', encoding='utf-8') as f:
                f.write(effects_content)
            print("[INFO] Patched effects.rpy with missing imports")

    # Patch character.py to make yaml import optional
    # We don't use the yaml-dependent functions, just the constants
    character_path = game_dir / "character.py"
    if character_path.exists():
        with open(character_path, 'r', encoding='utf-8') as f:
            character_content = f.read()

        if "import yaml" in character_content and "yaml = None" not in character_content:
            # Replace direct yaml import with a try/except that sets yaml to None if unavailable
            character_content = character_content.replace(
                "import yaml",
                "try:\n    import yaml\nexcept ImportError:\n    yaml = None  # Not needed for tester"
            )
            with open(character_path, 'w', encoding='utf-8') as f:
                f.write(character_content)
            print("[INFO] Patched character.py to make yaml optional")

    # Copy character folder (skip Windows reserved names and legacy _backups)
    SKIP_NAMES = {"con", "prn", "aux", "nul", "_backups",
                  *(f"com{i}" for i in range(1, 10)),
                  *(f"lpt{i}" for i in range(1, 10))}

    def _ignore_reserved(directory, contents):
        """Skip files/dirs with Windows reserved device names or legacy _backups."""
        return {name for name in contents
                if name.lower() in SKIP_NAMES
                or Path(name).stem.lower() in SKIP_NAMES}

    char_dest = images_dir / char_name
    shutil.copytree(char_dir, char_dest, ignore=_ignore_reserved)
    log_info(f"Copied character: {char_name}")

    # Generate test script
    script_content = generate_test_script(char_name, char_data, char_dir)
    script_path = game_dir / "script.rpy"
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)
    print(f"[INFO] Generated test script: script.rpy")

    # Create minimal project.json (optional but nice to have)
    project_json = TEST_PROJECT_DIR / "project.json"
    with open(project_json, 'w', encoding='utf-8') as f:
        f.write('{"name": "Sprite Tester"}')

    return TEST_PROJECT_DIR


def _get_or_create_tk_root():
    """Get the existing Tk root or create a new hidden one.

    When called from the wizard, a Tk root already exists. Creating a second
    tk.Tk() on Windows causes messageboxes to be invisible behind the main
    window. This helper reuses the existing root when available.

    Returns:
        (root, created) - root widget and whether we created it (caller must destroy if True)
    """
    existing = tk._default_root
    if existing is not None:
        return existing, False
    root = tk.Tk()
    root.withdraw()
    return root, True


def launch_sprite_tester(char_dir: Path) -> bool:
    """
    Main entry point - launches the sprite tester for the given character.

    Called from pipeline.py after expression sheet generation.
    Returns True if testing was performed, False if skipped.
    """
    log_info(f"Sprite Tester: checking for Ren'Py SDK...")
    log_info(f"SDK_DIR: {SDK_DIR}")
    log_info(f"Frozen mode: {getattr(sys, 'frozen', False)}")

    # Check if Ren'Py SDK exists
    renpy_exe = find_renpy_executable()
    log_info(f"Ren'Py executable: {renpy_exe}")

    # If SDK not found, offer to download it
    if not renpy_exe:
        log_info("Ren'Py SDK not found, prompting for download...")

        root, created = _get_or_create_tk_root()

        result = messagebox.askyesno(
            "Ren'Py SDK Required",
            f"Ren'Py SDK not found at:\n{SDK_DIR}\n\n"
            f"Download Ren'Py {SDK_VERSION} SDK (~450MB)?\n\n"
            "This is required to test sprites in Ren'Py.\n"
            "You can also set RENPY_SDK_PATH environment variable\n"
            "to point to an existing SDK installation.",
            parent=root
        )
        if created:
            root.destroy()

        if result:
            log_info("User accepted SDK download, starting...")
            success = download_and_setup_sdk(SDK_DIR)
            if success:
                log_info("SDK download completed successfully")
                renpy_exe = find_renpy_executable()
                log_info(f"Ren'Py executable after download: {renpy_exe}")
            else:
                log_error("SDK download failed")
                # Show error dialog
                root, created = _get_or_create_tk_root()
                messagebox.showerror(
                    "SDK Download Failed",
                    f"Failed to download Ren'Py SDK.\n\n"
                    f"Please check your internet connection and try again.\n\n"
                    f"Check the log file for details:\n"
                    f"(logs/sprite_creator.log next to exe)\n\n"
                    f"You can also manually download the SDK from:\n"
                    f"https://www.renpy.org/latest.html\n\n"
                    f"And set the RENPY_SDK_PATH environment variable to point to it."
                )
                if created:
                    root.destroy()
                return False
        else:
            log_info("SDK download declined by user, skipping sprite test")
            return False

    if not renpy_exe:
        log_error("Ren'Py SDK still not found after download attempt")
        return False

    # Check if templates exist
    if not TEMPLATES_DIR.exists():
        log_error(f"Templates not found at {TEMPLATES_DIR}, skipping sprite test")
        return False

    # Ask user if they want to test
    root, created = _get_or_create_tk_root()

    char_name = char_dir.name
    log_info(f"Prompting user to test character '{char_name}'...")
    result = messagebox.askyesno(
        "Sprite Tester",
        f"Test character '{char_name}' in Ren'Py?\n\n"
        "This will launch the Student Transfer character system\n"
        "to validate outfit/expression switching with the exchange transition.",
        parent=root
    )

    if created:
        root.destroy()

    if not result:
        log_info("Sprite test skipped by user")
        return False

    # Create the test project
    log_info("Setting up sprite test project...")
    project_path = create_test_project(char_dir)

    if not project_path:
        log_error("Failed to create test project")
        return False

    # Launch Ren'Py
    log_info(f"Launching Ren'Py: {renpy_exe}")
    log_info(f"Project: {project_path}")

    try:
        # Run Ren'Py and wait for it to close
        result = subprocess.run(
            [str(renpy_exe), str(project_path)],
            cwd=str(SDK_DIR),
            check=False
        )
        log_info(f"Ren'Py exited with code: {result.returncode}")
        return True
    except Exception as e:
        log_error(f"Failed to launch Ren'Py: {e}")
        return False


# Allow running directly for testing
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m sprite_creator.tester <character_folder>")
        sys.exit(1)

    char_path = Path(sys.argv[1])
    if not char_path.exists():
        print(f"Error: Character folder not found: {char_path}")
        sys.exit(1)

    launch_sprite_tester(char_path)
