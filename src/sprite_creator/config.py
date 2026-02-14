#!/usr/bin/env python3
"""
constants.py

All global paths, constants, and static tables for the Gemini sprite pipeline.
"""

import sys
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATION INFO
# ═══════════════════════════════════════════════════════════════════════════════
APP_NAME = "AI Sprite Creator"
APP_VERSION = "1.0.5"


def get_resource_path(relative_path: str = "") -> Path:
    """
    Get the path to a resource, handling both development and frozen (PyInstaller) modes.

    In development: Returns path relative to the sprite_creator package directory.
    When frozen: Returns path relative to PyInstaller's _MEIPASS temp directory.

    Args:
        relative_path: Path relative to the base directory (e.g., "data/names.csv")

    Returns:
        Absolute Path to the resource
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled .exe - PyInstaller extracts to _MEIPASS
        base_path = Path(sys._MEIPASS)
    else:
        # Running in development - use the package directory
        base_path = Path(__file__).resolve().parent

    if relative_path:
        return base_path / relative_path
    return base_path


# Base directory for this package (or frozen bundle)
SPRITE_CREATOR_DIR = get_resource_path()

# Data directory (contains CSVs and reference sprites)
DATA_DIR = get_resource_path("data")

# Paths for configuration and data files
CONFIG_PATH = Path.home() / ".st_gemini_config.json"
# OUTFIT_CSV_PATH deprecated - outfit prompts now in individual files per archetype+outfit
NAMES_CSV_PATH = DATA_DIR / "names.csv"
REF_SPRITES_DIR = DATA_DIR / "reference_sprites"

# External backup storage (keeps character folders clean for ST game compatibility)
BACKUPS_BASE_DIR = Path.home() / ".sprite_creator" / "backups"


def get_backup_dir(backup_id: str) -> Path:
    """Get external backup directory for a character's backup_id (from character.yml)."""
    return BACKUPS_BASE_DIR / backup_id


def generate_backup_id() -> str:
    """Generate a new unique backup ID for a character."""
    return uuid.uuid4().hex[:12]

# Gemini API constants
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_IMAGE_MODEL}:generateContent"
)

# ═══════════════════════════════════════════════════════════════════════════════
# DARK THEME COLOR SCHEME
# ═══════════════════════════════════════════════════════════════════════════════
BG_COLOR = "#2B2B2B"              # Main window background
BG_SECONDARY = "#1E1E1E"          # Darker areas (header, footer)
CARD_BG = "#3C3C3C"               # Card/panel backgrounds
CARD_BG_HOVER = "#4A4A4A"         # Card hover state
CARD_BG_SELECTED = "#4A90D9"      # Selected card background

TEXT_COLOR = "#FFFFFF"            # Primary text
TEXT_SECONDARY = "#A0A0A0"        # Secondary/muted text
TEXT_DISABLED = "#666666"         # Disabled text

ACCENT_COLOR = "#4A90D9"          # Blue accent for primary buttons
ACCENT_HOVER = "#5BA0E9"          # Primary button hover
PRIMARY_COLOR = "#4A90D9"         # Alias for accent (backwards compatibility)
SECONDARY_COLOR = "#666666"       # Secondary button background
SECONDARY_HOVER = "#777777"       # Secondary button hover
DANGER_COLOR = "#D94A4A"          # Red for destructive actions
DANGER_HOVER = "#E95A5A"          # Danger button hover
SUCCESS_COLOR = "#4AD94A"         # Green for success states

LINE_COLOR = "#00E5FF"            # Cyan accent for highlights
HIGHLIGHT_COLOR = "#00E5FF"       # Interactive element highlights
BORDER_COLOR = "#555555"          # Subtle borders

# ═══════════════════════════════════════════════════════════════════════════════
# FONT DEFINITIONS (Segoe UI for modern Windows look)
# ═══════════════════════════════════════════════════════════════════════════════
FONT_FAMILY = "Segoe UI"

# Title fonts (large, prominent)
TITLE_FONT = (FONT_FAMILY, 24, "bold")       # Main screen titles
PAGE_TITLE_FONT = (FONT_FAMILY, 20, "bold")  # Page/wizard step titles
SECTION_FONT = (FONT_FAMILY, 16, "bold")     # Section headers

# Body fonts (medium, readable)
BODY_FONT = (FONT_FAMILY, 12)                # Regular body text
BODY_FONT_BOLD = (FONT_FAMILY, 12, "bold")   # Emphasized body text

# Small fonts (compact, secondary)
SMALL_FONT = (FONT_FAMILY, 10)               # Labels, hints, secondary text
SMALL_FONT_BOLD = (FONT_FAMILY, 10, "bold")  # Small emphasized text

# Button fonts
BUTTON_FONT = (FONT_FAMILY, 11)              # Standard buttons
BUTTON_FONT_LARGE = (FONT_FAMILY, 13, "bold") # Large action buttons

# Legacy aliases (backwards compatibility)
INSTRUCTION_FONT = BODY_FONT

# Layout constants
WINDOW_MARGIN = 10
WRAP_PADDING = 40
CARD_PADDING = 16
CARD_RADIUS = 8  # For styling reference (tkinter doesn't support border-radius natively)

# Outfit keys:
# Base is always included by the pipeline, but you can choose which additional
# outfits to generate. These keys should match outfit_key values in the CSV.
ALL_OUTFIT_KEYS: List[str] = ["formal", "casual", "uniform", "athletic", "swimsuit", "underwear"]

# Default subset used when the user does not change anything.
OUTFIT_KEYS: List[str] = ["formal", "casual"]

# Default ordered list of expressions we actually use per outfit.
# The first entry is always neutral.
EXPRESSIONS_SEQUENCE: List[Tuple[str, str]] = [
    # CORE (0-7) - Must-haves for any VN
    ("0",  "neutral and relaxed with a soft smile"),
    ("1",  "neutral with mouth open as if talking"),
    ("2",  "happy and cheerful"),
    ("3",  "sad and worried"),
    ("4",  "angry or really annoyed"),
    ("5",  "surprised with wide eyes"),
    ("6",  "embarrassed with a bright red blush"),
    ("7",  "confused with a raised eyebrow and questioning look"),
    # EXTENDED (8-12) - Common additions
    ("8",  "laughing at a good joke"),
    ("9",  "scared and terrified with wide fearful eyes"),
    ("10", "crying and bawling"),
    ("11", "skeptical and doubtful with narrowed eyes"),
    ("12", "deep in thought, pensive"),
    # PERSONALITY (13-14)
    ("13", "confident with an almost smug look"),
    ("14", "playful, giving a wink"),
    # SITUATIONAL (15-16)
    ("15", "sleepy and tired with half-lidded drowsy eyes"),
    ("16", "aroused and blushing heavily"),
]


# Archetypes and their gender style codes (used by UI dropdowns)
GENDER_ARCHETYPES: List[Tuple[str, str]] = [
    ("young woman", "f"),
    ("adult woman", "f"),
    ("motherly woman", "f"),
    ("young man", "m"),
    ("adult man", "m"),
    ("fatherly man", "m"),
]

# Extended archetype data for prompt generation (used by fusion and prompt-based creation)
# The prompt_phrase is what Gemini sees - includes age and style descriptors
ARCHETYPES: Dict[str, Dict[str, str]] = {
    "young woman": {
        "gender": "f",
        "prompt_phrase": "cute young woman aged 18-22 with a slim figure and youthful face",
    },
    "adult woman": {
        "gender": "f",
        "prompt_phrase": "attractive woman aged 25-32 with a curvy figure, full bust, wide hips, and a confident alluring expression",
    },
    "motherly woman": {
        "gender": "f",
        "prompt_phrase": "beautiful mature woman aged 35-45 with a voluptuous figure, very large bust, wide pronounced hips, and a warm seductive MILF appeal",
    },
    "young man": {
        "gender": "m",
        "prompt_phrase": "handsome young man aged 18-22 with a lean athletic build, youthful features, and a fresh clean look",
    },
    "adult man": {
        "gender": "m",
        "prompt_phrase": "attractive man aged 25-32 with an athletic muscular build, defined jawline, and confident rugged appeal",
    },
    "fatherly man": {
        "gender": "m",
        "prompt_phrase": "handsome mature man aged 35-45 with a broad solid build, distinguished features, and warm DILF appeal",
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# UNDERWEAR TIER SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════
# Underwear prompts bypass Gemini text generation entirely due to high safety filter rates.
# Uses a tiered fallback system: Tier 0 (random with variety) -> Tier 1-N (ordered fallback)

# Female archetypes that get color variety in Tier 0
FEMALE_ARCHETYPES: List[str] = ["young woman", "adult woman", "motherly woman"]

# Color pool for female Tier 0 variety
UNDERWEAR_COLORS: List[str] = [
    "White", "Black", "Pink", "Cream", "Light blue", "Lavender",
    "Gray", "Yellow", "Mint", "Coral", "Red", "Navy"
]

# Non-bottom tier prompts for Tier 0 random selection (excludes most reliable fallback)
UNDERWEAR_TIER0_PROMPTS: Dict[str, List[str]] = {
    "young woman": ["Trendy underwear", "Trendy undergarments", "Cute undergarments"],
    "adult woman": ["Chic underwear", "Stylish underwear", "Elegant underwear"],
    "motherly woman": ["Comfortable undergarments", "Practical undergarments"],
    "young man": ["Simple undergarments", "Basic undergarments"],
    "adult man": ["Simple undergarments", "Basic undergarments"],
    "fatherly man": ["Simple undergarments", "Basic undergarments"],
}

# Ordered fallback tiers (Tier 1 through N) - tried in order when Tier 0 fails
UNDERWEAR_FALLBACK_TIERS: Dict[str, List[str]] = {
    "young woman": [
        "Trendy underwear",
        "Trendy undergarments",
        "Cute undergarments",
        "Pink undergarments",
        "Modern undergarments",
        "Lace trim bikini",
    ],
    "adult woman": [
        "Chic underwear",
        "Stylish underwear",
        "Elegant underwear",
        "Pink undergarments",
        "Modern undergarments",
        "Lace trim bikini",
    ],
    "motherly woman": [
        "Comfortable undergarments",
        "Practical undergarments",
        "Modest undergarments",
        "Modern undergarments",
        "Lace trim bikini",
    ],
    "young man": [
        "Simple undergarments",
        "Basic undergarments",
        "Cotton underwear",
    ],
    "adult man": [
        "Simple undergarments",
        "Basic undergarments",
        "Cotton underwear",
    ],
    "fatherly man": [
        "Simple undergarments",
        "Basic undergarments",
        "Cotton underwear",
    ],
}

# Safety fallback prompts for expressions that may trigger safety filters
# Maps expression key to a safer alternative description
SAFETY_FALLBACK_EXPRESSION_PROMPTS: Dict[str, str] = {
    "6": "embarrassed with a soft pink blush on the cheeks",
    "16": "flustered and blushing with a shy, warm expression",
}
