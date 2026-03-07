"""
Prompt builders for Gemini API requests.

All prompt generation logic for sprite creation, outfit changes, and expressions.
Prompts are preserved exactly as originally written per user request.
"""

import random
from typing import Dict, List, Optional

from ..config import GENDER_ARCHETYPES, ARCHETYPES


def get_archetype_prompt_phrase(archetype_label: str) -> str:
    """
    Get the prompt phrase for an archetype (used in fusion and prompt-based creation).

    Falls back to the archetype label if not found in ARCHETYPES dict.

    Args:
        archetype_label: Archetype name (e.g., "young woman", "motherly woman").

    Returns:
        Descriptive phrase for use in Gemini prompts.
    """
    if archetype_label in ARCHETYPES:
        return ARCHETYPES[archetype_label]["prompt_phrase"]
    return archetype_label  # Fallback to label if not found


# =============================================================================
# Outfit Description Generation - Dynamic via Gemini Text API
# =============================================================================

# Age ranges by archetype (used in Gemini text prompts)
AGE_RANGES = {
    "young woman": "18-20",
    "young man": "18-20",
    "adult woman": "20-35",
    "adult man": "20-35",
    "motherly woman": "35-50",
    "fatherly man": "35-50",
}

# Hair length descriptions for prompt clarity
HAIR_LENGTH_DESCRIPTIONS = {
    "super short": "above the ears",
    "short": "around chin length",
    "medium": "around shoulder length",
    "long": "past the shoulders to mid-back",
    "super long": "reaching the waist or beyond",
}

# Vibe words by (archetype, outfit_type) - plain adjectives for "with a {vibe} feel" structure
# IMPORTANT: Vibe words must match the outfit type! "Elegant" implies formal wear.
VIBE_WORDS = {
    # CASUAL - relaxed, everyday descriptors (includes "sexy")
    ("young woman", "casual"): ["cute", "flirty", "trendy", "playful", "sexy"],
    ("adult woman", "casual"): ["chic", "stylish", "effortless", "breezy", "sexy"],
    ("motherly woman", "casual"): ["charming", "effortless", "stylish", "breezy", "sexy"],
    ("young man", "casual"): ["chill", "fresh", "laid-back", "cool", "sexy"],
    ("adult man", "casual"): ["relaxed", "sharp", "effortless", "easy-going", "sexy"],
    ("fatherly man", "casual"): ["rugged", "sharp", "relaxed", "classic", "sexy"],

    # FORMAL - dressy, elegant descriptors (includes "sexy")
    ("young woman", "formal"): ["daring", "stylish", "pretty", "glamorous", "sexy"],
    ("adult woman", "formal"): ["chic", "elegant", "sophisticated", "stunning", "sexy"],
    ("motherly woman", "formal"): ["graceful", "stunning", "flattering", "elegant", "sexy"],
    ("young man", "formal"): ["fresh", "stylish", "sharp", "dapper", "sexy"],
    ("adult man", "formal"): ["sharp", "refined", "polished", "suave", "sexy"],
    ("fatherly man", "formal"): ["distinguished", "classic", "dapper", "refined", "sexy"],

    # ATHLETIC - sporty descriptors (includes "sexy")
    ("young woman", "athletic"): ["sporty", "fierce", "energetic", "athletic", "sexy"],
    ("adult woman", "athletic"): ["sleek", "sporty", "stylish", "athletic", "sexy"],
    ("motherly woman", "athletic"): ["sleek", "sporty", "fitted", "athletic", "sexy"],
    ("young man", "athletic"): ["sporty", "cool", "athletic", "fresh", "sexy"],
    ("adult man", "athletic"): ["sporty", "athletic", "sharp", "fitted", "sexy"],
    ("fatherly man", "athletic"): ["rugged", "athletic", "sporty", "sharp", "sexy"],

    # SWIMSUIT - beach/pool appropriate descriptors (includes "sexy")
    ("young woman", "swimsuit"): ["cute", "bold", "flirty", "stunning", "sexy"],
    ("adult woman", "swimsuit"): ["chic", "stylish", "alluring", "elegant", "sexy"],
    ("motherly woman", "swimsuit"): ["flattering", "elegant", "classic", "stylish", "sexy"],
    ("young man", "swimsuit"): ["cool", "trendy", "bold", "fun", "sexy"],
    ("adult man", "swimsuit"): ["sharp", "classic", "stylish", "bold", "sexy"],
    ("fatherly man", "swimsuit"): ["classic", "rugged", "bold", "casual", "sexy"],

    # UNDERWEAR - comfortable/loungewear descriptors (no "sexy" - handled by tier system)
    ("young woman", "underwear"): ["cute", "flirty", "trendy", "soft"],
    ("adult woman", "underwear"): ["chic", "elegant", "refined", "stylish"],
    ("motherly woman", "underwear"): ["elegant", "soft", "delicate", "stylish"],
    ("young man", "underwear"): ["comfy", "basic", "simple", "casual"],
    ("adult man", "underwear"): ["simple", "fitted", "basic", "classic"],
    ("fatherly man", "underwear"): ["fitted", "rugged", "simple", "classic"],

    # UNIFORM - professional/standard descriptors (no "sexy" - uniforms are standardized)
    ("young woman", "uniform"): ["neat", "crisp", "proper", "standard"],
    ("adult woman", "uniform"): ["professional", "neat", "crisp", "proper"],
    ("motherly woman", "uniform"): ["professional", "neat", "proper", "standard"],
    ("young man", "uniform"): ["neat", "crisp", "proper", "standard"],
    ("adult man", "uniform"): ["professional", "neat", "crisp", "sharp"],
    ("fatherly man", "uniform"): ["professional", "distinguished", "proper", "neat"],
}

# Garment types by (archetype, outfit_type) - specific clothing items
# IMPORTANT: Garment types must be clothing items ONLY - no adjectives or vibes
GARMENT_TYPES = {
    # FORMAL - Female (party, prom, homecoming, clubs, galas)
    ("young woman", "formal"): [
        "mini dress", "cocktail dress", "bodycon dress", "A-line dress", "halter dress",
        "off-shoulder dress", "backless dress", "corset dress", "satin dress", "sequin dress",
        "strapless dress", "slit dress", "wrap dress", "fitted women's suit", "satin top and dress pants",
    ],
    ("adult woman", "formal"): [
        "wrap dress", "midi dress", "cocktail dress", "off-shoulder dress", "satin dress",
        "halter dress", "bodycon dress", "backless dress", "one-shoulder dress", "slit dress",
        "sequin dress", "strapless dress", "plunge dress", "A-line dress", "fitted suit with pants",
    ],
    ("motherly woman", "formal"): [
        "A-line dress", "wrap dress", "maxi dress", "fit-and-flare dress", "off-shoulder dress",
        "flutter-sleeve dress", "lace dress", "satin dress", "cocktail dress", "midi dress",
        "halter dress", "draped dress", "pleated dress", "chiffon dress", "one-shoulder dress",
    ],
    ("young man", "formal"): [
        "slim-fit suit", "blazer and slacks", "dress shirt and vest", "tailored trousers and shirt",
        "suit and tie", "button-down and dress pants", "turtleneck and blazer", "mock neck and suit",
    ],
    ("adult man", "formal"): [
        "three-piece suit", "tuxedo", "double-breasted suit", "blazer and slacks",
        "suit and tie", "dress shirt and trousers", "waistcoat outfit", "mandarin collar suit",
    ],
    ("fatherly man", "formal"): [
        "three-piece suit", "double-breasted suit", "blazer and slacks", "suit and tie",
        "sport coat and slacks", "cardigan and dress shirt", "sweater vest and slacks", "tweed suit",
    ],

    # CASUAL - Female (everyday, hanging out, dates, errands in style)
    ("young woman", "casual"): [
        "sundress", "oversized sweater and leggings", "mini skirt and top", "romper",
        "crop top and jeans", "flowy blouse and shorts", "halter top and skirt",
        "off-shoulder top and jeans", "overalls", "wrap skirt and top", "cargo pants and fitted tee",
        "pleated skirt and crop top", "tank top and leggings", "crop top and mini skirt",
        "graphic tee and skirt", "oversized tshirt and shorts",
    ],
    ("adult woman", "casual"): [
        "blouse and slacks", "jeans and blouse", "sweater and trousers", "wide-leg pants and top",
        "wrap top and jeans", "turtleneck and jeans", "linen pants and top", "sundress",
        "cropped jean jacket and tank top", "cardigan and jeans", "off-shoulder top and pants",
        "blouse and shorts", "sweater and leggings", "fitted tee and slacks",
        "sleeveless top and jeans", "oversized tshirt and shorts",
    ],
    ("motherly woman", "casual"): [
        "sundress", "blouse and capris", "tank top and jeans", "linen pants and blouse",
        "wrap top and shorts", "v-neck tee and jeans", "off-shoulder top and pants",
        "maxi skirt and top", "leggings and tunic", "blouse and shorts", "fitted tee and slacks",
        "sleeveless blouse and jeans", "cropped pants and top", "halter top and jeans",
        "cardigan and sundress", "oversized tshirt and shorts",
    ],
    ("young man", "casual"): [
        "graphic tee and jeans", "hoodie and jeans", "button-up and chinos", "shorts and t-shirt",
        "layered tees and jeans", "polo and shorts", "bomber jacket outfit", "denim jacket and tee",
        "tank top and shorts", "joggers and sweatshirt",
    ],
    ("adult man", "casual"): [
        "henley and jeans", "button-down and jeans", "polo and chinos", "chinos and sweater",
        "sweater and jeans", "blazer and jeans", "quarter-zip and pants", "linen shirt and pants",
        "hoodie and chinos", "cardigan and t-shirt",
    ],
    ("fatherly man", "casual"): [
        "polo and khakis", "button-up and jeans", "sweater and slacks", "jeans and flannel",
        "vest and button-down", "cardigan and chinos", "pullover and jeans", "golf shirt and shorts",
        "fleece and khakis", "denim jacket outfit",
    ],

    # ATHLETIC - Female (shared across archetypes)
    ("young woman", "athletic"): [
        "sports bra and running shorts", "sports bra and leggings", "athletic shorts and tank",
        "workout tank and running shorts", "gym shorts and crop top", "compression leggings and top",
        "sports bra and joggers", "racerback tank and shorts", "bike shorts and tank",
        "sports bra and bike shorts", "cropped hoodie and running shorts", "running shorts and crop top",
    ],
    ("adult woman", "athletic"): [
        "sports bra and running shorts", "sports bra and leggings", "athletic shorts and tank",
        "workout tank and running shorts", "gym shorts and crop top", "compression leggings and top",
        "sports bra and joggers", "racerback tank and shorts", "bike shorts and tank",
        "sports bra and bike shorts", "cropped hoodie and running shorts", "running shorts and crop top",
    ],
    ("motherly woman", "athletic"): [
        "sports bra and running shorts", "sports bra and leggings", "athletic shorts and tank",
        "workout tank and running shorts", "gym shorts and crop top", "compression leggings and top",
        "sports bra and joggers", "racerback tank and shorts", "bike shorts and tank",
        "sports bra and bike shorts", "cropped hoodie and running shorts", "running shorts and crop top",
    ],
    # ATHLETIC - Male (shared across archetypes)
    ("young man", "athletic"): [
        "tank top and shorts", "athletic shirt and joggers", "gym shorts and tee",
        "compression shirt and shorts", "running shorts and singlet", "basketball shorts and jersey",
        "tank top and joggers", "sleeveless hoodie and shorts", "muscle tee and shorts",
        "track pants and jacket", "compression pants and tee", "athletic shorts and tank",
    ],
    ("adult man", "athletic"): [
        "tank top and shorts", "athletic shirt and joggers", "gym shorts and tee",
        "compression shirt and shorts", "running shorts and singlet", "basketball shorts and jersey",
        "tank top and joggers", "sleeveless hoodie and shorts", "muscle tee and shorts",
        "track pants and jacket", "compression pants and tee", "athletic shorts and tank",
    ],
    ("fatherly man", "athletic"): [
        "tank top and shorts", "athletic shirt and joggers", "gym shorts and tee",
        "compression shirt and shorts", "running shorts and singlet", "basketball shorts and jersey",
        "tank top and joggers", "sleeveless hoodie and shorts", "muscle tee and shorts",
        "track pants and jacket", "compression pants and tee", "athletic shorts and tank",
    ],

    # SWIMSUIT - Female (archetype-specific)
    ("young woman", "swimsuit"): [
        "bikini swimsuit", "high-waisted bikini swimsuit", "one-piece swimsuit",
        "bandeau bikini swimsuit", "triangle bikini swimsuit", "sporty one-piece swimsuit",
        "string bikini swimsuit", "halter bikini swimsuit", "cut-out one-piece swimsuit",
    ],
    ("adult woman", "swimsuit"): [
        "one-piece swimsuit", "bikini swimsuit", "halter one-piece swimsuit",
        "high-cut one-piece swimsuit", "two-piece swimsuit", "plunge one-piece swimsuit",
        "bandeau one-piece swimsuit", "underwire bikini swimsuit", "wrap swimsuit",
    ],
    ("motherly woman", "swimsuit"): [
        "one-piece swimsuit", "tankini swimsuit", "halter tankini swimsuit",
        "high-neck one-piece swimsuit", "wrap one-piece swimsuit", "ruched one-piece swimsuit",
        "boyshort bikini swimsuit", "modest bikini swimsuit", "swim dress",
    ],
    # SWIMSUIT - Male (shared across archetypes)
    ("young man", "swimsuit"): [
        "board shorts", "swim trunks", "swim briefs", "jammers",
        "swim shorts", "square-cut trunks", "volley shorts", "hybrid shorts",
    ],
    ("adult man", "swimsuit"): [
        "board shorts", "swim trunks", "swim briefs", "jammers",
        "swim shorts", "square-cut trunks", "volley shorts", "hybrid shorts",
    ],
    ("fatherly man", "swimsuit"): [
        "board shorts", "swim trunks", "swim briefs", "jammers",
        "swim shorts", "square-cut trunks", "volley shorts", "hybrid shorts",
    ],
}

# Color roles with weights for weighted random selection
COLOR_ROLES = [
    ("primary", 60),    # Main/dominant color - 60%
    ("secondary", 30),  # Supporting color - 30%
    ("detail", 10),     # Accent color - 10%
]

# Colors keyed by (archetype, outfit_type) for maximum relevance
# =============================================================================

# FORMAL COLORS - Female
FORMAL_COLORS = {
    "young woman": [
        "black", "navy", "burgundy", "emerald", "gold", "silver",
        "blush pink", "baby blue", "lavender", "hot pink", "coral",
        "mint green", "peach", "lilac", "sky blue", "rose",
        "champagne", "periwinkle", "fuchsia", "turquoise", "soft yellow",
    ],
    "adult woman": [
        "black", "navy", "burgundy", "emerald", "gold", "silver",
        "champagne", "wine red", "cobalt blue", "ivory", "plum",
        "forest green", "sapphire", "copper", "charcoal", "ruby red",
        "midnight blue", "bronze", "deep teal", "cream", "hunter green",
    ],
    "motherly woman": [
        "black", "navy", "burgundy", "emerald", "gold", "silver",
        "mauve", "teal", "rose gold", "slate blue", "dusty rose",
        "deep purple", "cranberry", "pearl", "olive", "aubergine",
        "taupe", "rich chocolate", "peacock blue", "merlot", "sage green",
    ],
    # Male formal colors
    "young man": [
        "black", "navy", "charcoal", "burgundy", "white",
        "royal blue", "forest green", "silver", "wine",
        "blush pink", "lavender", "mint", "gold",
    ],
    "adult man": [
        "black", "navy", "charcoal", "midnight blue", "burgundy",
        "slate", "forest green", "cream", "bronze",
        "plum", "teal", "champagne", "copper",
    ],
    "fatherly man": [
        "black", "navy", "charcoal", "brown", "grey",
        "slate", "forest green", "tan", "wine",
        "hunter green", "burgundy", "pearl grey",
    ],
}

# SWIMSUIT COLORS - Female
SWIMSUIT_COLORS = {
    "young woman": [
        "black", "navy", "white", "coral", "turquoise", "red",
        "hot pink", "neon orange", "electric blue", "lime green", "sunny yellow",
        "baby pink", "lavender", "mint", "peach", "sky blue",
        "tie-dye", "tropical print", "watermelon pink",
    ],
    "adult woman": [
        "black", "navy", "white", "coral", "turquoise", "red",
        "emerald", "cobalt blue", "cherry red", "royal blue",
        "olive", "rust", "bronze", "burgundy", "forest green",
        "animal print", "tropical print", "classic stripe",
    ],
    "motherly woman": [
        "black", "navy", "white", "coral", "turquoise", "red",
        "deep teal", "burgundy", "plum", "forest green", "royal blue",
        "slate blue", "olive", "rust", "berry", "deep coral",
        "subtle stripe", "classic navy and white", "muted floral",
    ],
    # Male swimsuit colors (shared across archetypes)
    "young man": [
        "navy", "black", "white", "red", "royal blue",
        "forest green", "orange", "teal", "grey", "burgundy",
        "tropical print", "stripe", "camo", "neon", "coral",
    ],
    "adult man": [
        "navy", "black", "white", "red", "royal blue",
        "forest green", "orange", "teal", "grey", "burgundy",
        "tropical print", "stripe", "camo", "neon", "coral",
    ],
    "fatherly man": [
        "navy", "black", "white", "red", "royal blue",
        "forest green", "orange", "teal", "grey", "burgundy",
        "tropical print", "stripe", "camo", "neon", "coral",
    ],
}

# CASUAL COLORS
CASUAL_COLORS = {
    "young woman": [
        "white", "black", "denim blue", "light pink", "lavender",
        "baby blue", "mint", "coral", "sunny yellow", "peach",
        "hot pink", "neon green", "tie-dye", "lilac", "tangerine",
    ],
    "adult woman": [
        "white", "black", "navy", "cream", "beige",
        "dusty rose", "sage", "terracotta", "mustard", "burgundy",
        "olive", "blush", "cobalt", "camel", "charcoal",
    ],
    "motherly woman": [
        "white", "black", "navy", "cream", "olive",
        "dusty blue", "mauve", "sage", "burgundy", "rust",
        "plum", "teal", "chocolate", "taupe", "forest green",
    ],
    "young man": [
        "white", "black", "navy", "grey", "denim blue",
        "red", "forest green", "burgundy", "mustard", "royal blue",
        "neon", "tie-dye", "camo", "orange", "purple",
    ],
    "adult man": [
        "white", "black", "navy", "grey", "olive",
        "charcoal", "burgundy", "sage", "rust", "camel",
        "cobalt", "plum", "teal", "cream", "terracotta",
    ],
    "fatherly man": [
        "white", "black", "navy", "grey", "khaki",
        "brown", "forest green", "burgundy", "slate", "tan",
        "maroon", "hunter green", "light blue", "beige", "charcoal",
    ],
}

# ATHLETIC COLORS
ATHLETIC_COLORS = {
    "young woman": [
        "black", "white", "hot pink", "coral", "turquoise",
        "neon yellow", "electric blue", "mint", "purple", "orange",
        "tie-dye", "ombre pink", "lavender", "lime green", "ruby",
    ],
    "adult woman": [
        "black", "white", "hot pink", "coral", "turquoise",
        "neon yellow", "electric blue", "mint", "purple", "orange",
        "tie-dye", "ombre pink", "lavender", "lime green", "ruby",
    ],
    "motherly woman": [
        "black", "white", "hot pink", "coral", "turquoise",
        "neon yellow", "electric blue", "mint", "purple", "orange",
        "tie-dye", "ombre pink", "lavender", "lime green", "ruby",
    ],
    "young man": [
        "black", "white", "navy", "grey", "red",
        "royal blue", "forest green", "orange", "charcoal", "lime",
        "camo", "neon yellow", "teal", "burgundy", "electric blue",
    ],
    "adult man": [
        "black", "white", "navy", "grey", "red",
        "royal blue", "forest green", "orange", "charcoal", "lime",
        "camo", "neon yellow", "teal", "burgundy", "electric blue",
    ],
    "fatherly man": [
        "black", "white", "navy", "grey", "red",
        "royal blue", "forest green", "orange", "charcoal", "lime",
        "camo", "neon yellow", "teal", "burgundy", "electric blue",
    ],
}

# Outfit colors to exclude based on the user's generation background color.
# Prevents outfit-background color clashes that confuse rembg during BG removal.
# Key: lowercase BG color name (portion before the hex code in BACKGROUND_COLOR_PRESETS).
# Value: set of outfit color strings (lowercase) to skip when picking a random color.
BG_CLASH_COLORS = {
    "black": {"black", "charcoal", "midnight blue"},
    "light grey": {"grey", "gray", "silver", "pearl grey", "slate", "light grey"},
    "lime green": {"lime green", "lime", "neon green", "mint green", "mint"},
    "blue": {"royal blue", "cobalt blue", "cobalt", "electric blue", "blue"},
}


def _filter_colors_for_bg(colors: list, background_color: str) -> list:
    """Remove colors that clash with the generation background. Falls back to unfiltered if all removed."""
    if not background_color:
        return colors
    bg_name = background_color.split("(")[0].strip().lower()
    clash_set = BG_CLASH_COLORS.get(bg_name, set())
    if not clash_set:
        return colors
    filtered = [c for c in colors if c.lower() not in clash_set]
    return filtered if filtered else colors


# Occasions - COMMENTED OUT for testing (outfit_type in prompt provides enough context)
# To restore: uncomment this dict and revert the prompt in generate_outfit_description()
# OCCASIONS = {
#     # FORMAL - 10 occasions per archetype
#     ("young woman", "formal"): [
#         "going to prom",
#         "attending a homecoming dance",
#         "going to a winter formal",
#         "attending a sorority formal",
#         "going to a graduation dinner",
#         "attending a sweet sixteen party",
#         "attending a theater premiere",
#         "attending a sorority philanthropy event",
#         "visiting an upscale restaurant",
#         "going to a debutante ball",
#     ],
#     ("adult woman", "formal"): [
#         "attending a cocktail party",
#         "going to a wedding as a guest",
#         "attending a gallery opening",
#         "going to a charity gala",
#         "attending an awards ceremony",
#         "going to a black-tie dinner",
#         "going to a film premiere",
#         "attending a book launch party",
#         "at a rooftop cocktail event",
#         "going to a museum gala",
#     ],
#     ("motherly woman", "formal"): [
#         "attending a gala",
#         "going to a special occasion dinner",
#         "attending a charity fundraiser",
#         "going to an anniversary celebration",
#         "attending an awards banquet",
#         "going to the opera or symphony",
#         "attending a retirement celebration",
#         "going to a country club dinner",
#         "at a scholarship banquet",
#         "attending a wine and cheese reception",
#     ],
#     ("young man", "formal"): [
#         "going to prom",
#         "attending a homecoming dance",
#         "going to a winter formal",
#         "attending a graduation dinner",
#         "going to a fraternity formal",
#         "attending a family wedding",
#         "attending a scholarship dinner",
#         "going to a charity concert",
#         "at a debutante ball",
#         "going to a fancy restaurant",
#     ],
#     ("adult man", "formal"): [
#         "attending a wedding as a guest",
#         "going to a business formal event",
#         "attending a cocktail party",
#         "going to a charity gala",
#         "attending an awards dinner",
#         "going to a formal date night",
#         "going to a networking gala",
#         "attending a client dinner",
#         "at a museum opening",
#         "going to a charity auction",
#     ],
#     ("fatherly man", "formal"): [
#         "attending a formal dinner",
#         "going to an awards ceremony",
#         "attending a charity gala",
#         "going to a business banquet",
#         "attending an anniversary dinner",
#         "going to the theater or opera",
#         "attending a retirement party",
#         "going to a country club event",
#         "at a professional conference dinner",
#         "attending a lodge ceremony",
#     ],
#
#     # CASUAL - 12 occasions per archetype
#     ("young woman", "casual"): [
#         "going to class",
#         "hanging out with friends",
#         "grabbing boba",
#         "going to the mall",
#         "attending a movie night",
#         "going on a casual date",
#         "studying at a coffee shop",
#         "going to weekend brunch",
#         "at a rooftop hangout",
#         "going to a flea market",
#         "at a bowling night",
#         "visiting an arcade",
#     ],
#     ("adult woman", "casual"): [
#         "at the farmers market",
#         "meeting for coffee at a cafe",
#         "doing some casual shopping",
#         "a relaxed weekend afternoon",
#         "working from home",
#         "meeting a friend for lunch",
#         "a casual day off",
#         "hanging out on the weekend",
#         "at a book signing",
#         "going to a craft fair",
#         "visiting a winery",
#         "at a trivia night",
#     ],
#     ("motherly woman", "casual"): [
#         "running errands",
#         "picking up the kids",
#         "at a school pickup",
#         "going to weekend activities",
#         "having coffee with neighbors",
#         "going to a casual lunch",
#         "doing weekend shopping",
#         "at a backyard barbecue",
#         "at a craft night",
#         "going to a bake sale",
#         "visiting a nursery",
#         "at a potluck dinner",
#     ],
#     ("young man", "casual"): [
#         "hanging out with friends",
#         "going to a casual party",
#         "catching a movie",
#         "playing video games with buddies",
#         "grabbing food with friends",
#         "going to a weekend hangout",
#         "attending a house party",
#         "chilling on campus",
#         "at a pickup basketball game",
#         "going to a concert",
#         "at a gaming tournament",
#         "visiting an escape room",
#     ],
#     ("adult man", "casual"): [
#         "going to weekend brunch",
#         "on a casual date",
#         "watching the game at a sports bar",
#         "attending a barbecue",
#         "hanging out with buddies",
#         "picking up groceries",
#         "going to a casual dinner",
#         "relaxing on the weekend",
#         "at a brewery tour",
#         "going to a car show",
#         "visiting a golf range",
#         "at a poker night",
#     ],
#     ("fatherly man", "casual"): [
#         "hosting a weekend barbecue",
#         "running errands",
#         "at a casual family outing",
#         "watching the game with friends",
#         "attending a neighborhood gathering",
#         "going to a casual lunch",
#         "doing weekend yard work",
#         "taking the family out",
#         "at a fishing trip",
#         "going to a home improvement store",
#         "visiting a classic car show",
#         "at a block party",
#     ],
#
#     # ATHLETIC
#     ("young woman", "athletic"): "going to yoga class or working out at the gym",
#     ("adult woman", "athletic"): "going for a morning run or attending a fitness class",
#     ("motherly woman", "athletic"): "going for a jog or doing yoga",
#     ("young man", "athletic"): "playing basketball or working out at the gym",
#     ("adult man", "athletic"): "going for a run or hitting the gym",
#     ("fatherly man", "athletic"): "going for a morning jog or playing golf",
#
#     # SWIMSUIT
#     ("young woman", "swimsuit"): "at the beach with friends or a pool party",
#     ("adult woman", "swimsuit"): "relaxing at a resort or on a beach vacation",
#     ("motherly woman", "swimsuit"): "at a family beach day or the neighborhood pool",
#     ("young man", "swimsuit"): "at the beach with friends or a pool party",
#     ("adult man", "swimsuit"): "at a beach resort or a pool club",
#     ("fatherly man", "swimsuit"): "at a family pool day or the beach with kids",
#
#     # UNDERWEAR
#     ("young woman", "underwear"): "lounging at home or getting ready for the day",
#     ("adult woman", "underwear"): "getting ready for a date night or relaxing at home",
#     ("motherly woman", "underwear"): "for everyday wear around the house",
#     ("young man", "underwear"): "lounging at home or getting ready for the day",
#     ("adult man", "underwear"): "for everyday basics or getting ready in the morning",
#     ("fatherly man", "underwear"): "for everyday wear around the house",
#
#     # UNIFORM
#     ("young woman", "uniform"): "Japanese school uniform",
#     ("adult woman", "uniform"): "working at an office or in a medical setting",
#     ("motherly woman", "uniform"): "working at an office or in a medical setting",
#     ("young man", "uniform"): "Japanese school uniform",
#     ("adult man", "uniform"): "working at an office or in a service industry",
#     ("fatherly man", "uniform"): "in a managerial role or professional setting",
# }


def _select_weighted_color_role() -> str:
    """Select a color role using weighted random selection."""
    total_weight = sum(weight for _, weight in COLOR_ROLES)
    rand_val = random.randint(1, total_weight)
    cumulative = 0
    for role, weight in COLOR_ROLES:
        cumulative += weight
        if rand_val <= cumulative:
            return role
    return "primary"  # Fallback


def _get_color_for_outfit(archetype_label: str, outfit_type: str, background_color: str = "") -> str:
    """Get a random color appropriate for the archetype and outfit type.

    Filters out colors that clash with the generation background color.
    """
    if outfit_type == "formal" and archetype_label in FORMAL_COLORS:
        colors = FORMAL_COLORS[archetype_label]
    elif outfit_type == "swimsuit" and archetype_label in SWIMSUIT_COLORS:
        colors = SWIMSUIT_COLORS[archetype_label]
    elif outfit_type == "casual" and archetype_label in CASUAL_COLORS:
        colors = CASUAL_COLORS[archetype_label]
    elif outfit_type == "athletic" and archetype_label in ATHLETIC_COLORS:
        colors = ATHLETIC_COLORS[archetype_label]
    else:
        # Fallback for underwear/uniform or missing entries
        colors = ["black", "white", "navy", "grey"]

    return random.choice(_filter_colors_for_bg(colors, background_color))


def generate_outfit_description(
    api_key: str,
    outfit_type: str,
    archetype_label: str,
    background_color: str = "",
) -> str:
    """
    Generate an outfit description using Gemini text API.

    Combines archetype-specific vibe words, garment types, age ranges, occasions,
    colors, and color roles to produce varied, attractive outfit descriptions.

    New prompt structure (v2.0):
    "Describe a new realistic outfit for a {gender_word} aged {age} {occasion},
    inspired by {garment_type} with a {vibe_word} feel, in one brief sentence.
    Keep it realistic while including {color} as a {color_role} color.
    Do not give a preamble before the outfit and do not describe what is being worn on the feet."

    Args:
        api_key: Google Gemini API key.
        outfit_type: Type of outfit (formal, casual, athletic, swimsuit, underwear, uniform).
        archetype_label: Character archetype (e.g., "young woman", "adult man").

    Returns:
        Generated outfit description string.
    """
    from .gemini_client import call_gemini_text

    # Strip trailing digits from renamed outfit keys (e.g., "formal2" → "formal")
    # This happens in add-to-existing mode when outfit names conflict
    base_type = outfit_type.rstrip("0123456789") or outfit_type

    # Get archetype-specific data
    age = AGE_RANGES.get(archetype_label, "20-35")
    gender_word = "woman" if archetype_label.endswith("woman") else "man"

    # Occasions removed — outfit_type provides enough category context
    # To restore: uncomment OCCASIONS dict and use the old prompt below
    # OLD PROMPT:
    # occasion_data = OCCASIONS.get((archetype_label, base_type), f"a {base_type} occasion")
    # occasion = random.choice(occasion_data) if isinstance(occasion_data, list) else occasion_data
    # prompt = (
    #     f"Describe a new realistic outfit for a {gender_word} aged {age} {occasion}, "
    #     f"inspired by {garment_type} with a {vibe_word} feel, in one brief sentence. "
    #     f"Keep it realistic while including {color} as a {color_role} color. "
    #     "Do not give a preamble before the outfit and do not describe what is being worn on the feet."
    # )

    # Get vibe word (plain adjective, no article)
    vibe_word = random.choice(VIBE_WORDS.get((archetype_label, base_type), ["stylish"]))

    # Get garment type
    garment_types = GARMENT_TYPES.get((archetype_label, base_type), None)
    if garment_types:
        garment_type = random.choice(garment_types)
    else:
        # Fallback for underwear/uniform which don't use garment types
        garment_type = base_type

    # ALWAYS get color and color role (no more 50% chance)
    color = _get_color_for_outfit(archetype_label, base_type, background_color)
    color_role = _select_weighted_color_role()

    # Build prompt (no occasions — outfit_type provides category context)
    prompt = (
        f"Describe a new realistic {base_type} outfit for a {gender_word} aged {age}, "
        f"inspired by {garment_type} with a {vibe_word} feel, in one brief sentence. "
        f"Keep it realistic while including {color} as a {color_role} color. "
        "Do not give a preamble before the outfit and do not describe what is being worn on the feet."
    )

    # Anti-layering rules for specific outfit+gender combos
    # Prevents Gemini from adding unnecessary blazers, cardigans, cover-ups
    is_female = gender_word == "woman"
    if base_type == "swimsuit":
        prompt += " Describe ONLY the swimwear itself. Do not pair it with shorts, pants, skirts, cover-ups, wraps, or any other non-swimwear items."
    elif base_type == "athletic":
        prompt += " Do not add jackets or heavy layers over athletic wear."
    elif is_female and base_type in ("formal", "casual"):
        prompt += " Do not describe layered outfits with blazers, suit jackets, or cardigans over dresses."

    # Call Gemini text API
    description = call_gemini_text(api_key, prompt, temperature=1.0)

    return description


# =============================================================================
# Archetype and Gender Utilities
# =============================================================================

def archetype_to_gender_style(archetype_label: str) -> str:
    """
    Given an archetype label, return gender style code 'f' or 'm'.

    Args:
        archetype_label: Archetype name (e.g., "young woman", "adult man").

    Returns:
        'f' for female archetypes, 'm' for male archetypes, 'f' as default.
    """
    for label, gender in GENDER_ARCHETYPES:
        if label == archetype_label:
            return gender
    return "f"  # Default to female


# =============================================================================
# Core Prompt Builders (DO NOT MODIFY - per user request)
# =============================================================================

def build_expression_prompt(
    expression_desc: str,
    background_color: str = "black (#000000)",
    add_to_existing: bool = False,
    archetype_label: str = "",
) -> str:
    """
    Prompt to change facial expression, keeping style and framing.

    Args:
        expression_desc: Description of the desired expression.
        background_color: Background color description (e.g., "magenta (#FF00FF)" or "black (#000000)").
        add_to_existing: If True, uses upscale instruction for add-to-character mode
            where source images are already scaled down.
        archetype_label: Character archetype (e.g., "young woman", "adult man").

    Returns:
        Prompt string for expression generation.
    """
    bg = background_color.split("(")[0].strip()  # Extract color name (magenta or black)
    age = AGE_RANGES.get(archetype_label, "20-35")
    archetype = archetype_label or "character"

    # Add-to-character mode only: upscale with artifact prevention
    enhancement_line = "Upscale and sharpen the image, but make sure no artifacts are left behind. " if add_to_existing else ""

    return (
        f"Edit the {archetype}'s expression and pose so they are clearly feeling {expression_desc} in a way that a {age} year old {archetype} would be. "
        "Don't change the size, proportions, framing, art style, or age of the character. "
        f"{enhancement_line}"
        "Keep the hair volume, hair outlines, and the hair style all the exact same. "
        f"Give the character a {bg} background behind them. "
        "Make sure the head, arms, hair, hands, and clothes are all kept within the image."
    )

def build_outfit_prompt(base_outfit_desc: str, gender_style: str, background_color: str = "black (#000000)", hair_length: str = "", archetype_label: str = "") -> str:
    """
    Prompt to change clothing to base_outfit_desc on the given pose.

    Args:
        base_outfit_desc: Description of the outfit to generate.
        gender_style: 'f' or 'm' for gender-appropriate wording.
        background_color: Background color description (e.g., "magenta (#FF00FF)" or "black (#000000)").
        hair_length: Hair length instruction (e.g., "short", "medium"). Empty string for no hair length control.
        archetype_label: Character archetype (e.g., "young woman", "adult man").

    Returns:
        Prompt string for outfit generation.
    """
    bg = background_color.split("(")[0].strip()  # Extract color name (magenta or black)
    archetype = archetype_label or "character"
    if hair_length:
        length_desc = HAIR_LENGTH_DESCRIPTIONS.get(hair_length.lower(), hair_length.lower())
        hair_instruction = f"Change the character's hairstyle completely. Give them a new {hair_length.lower()} length hairstyle that fits their new outfit yet keeps the same hair texture and color. Their hair should now be {length_desc}. "
    else:
        hair_instruction = "Change the character's hairstyle completely to give them a new hairstyle that fits their new outfit yet keeps the same hair color, length, and texture. "
    prompt = (
        f"Edit the {archetype}'s clothes so our {archetype} is wearing {base_outfit_desc}. "
        f"{hair_instruction}"
        "Don't change the size, proportions, framing, art style, or age of the character. "
        f"Give the character a {bg} background behind them. "
        "Make sure the head, arms, hair, hands, and clothes are all kept within the image."
    )

    # Anti-cover-up for swimwear: prevent Gemini from adding jackets/wraps over swimsuits
    SWIMWEAR_KEYWORDS = {"bikini", "swimsuit", "one-piece", "tankini", "monokini", "swim", "bathing suit"}
    desc_lower = base_outfit_desc.lower()
    if any(kw in desc_lower for kw in SWIMWEAR_KEYWORDS):
        prompt += " Do not add any cover-ups, jackets, cardigans, wraps, sarongs, or layering pieces over the swimwear."

    return prompt

def build_standard_school_uniform_prompt(
    archetype_label: str,
    gender_style: str,
    background_color: str = "black (#000000)",
    hair_length: str = "",
) -> str:
    """
    Build a standardized school-uniform prompt matching the rest of the outfit prompts.

    Uses archetype label and gender style to describe the character,
    then describes the school uniform in text. The cropped uniform reference
    image is used as visual backup.

    NOTE: Prompt wording updated to avoid triggering safety filters while maintaining functionality.

    Args:
        archetype_label: Character archetype (e.g., "young woman").
        gender_style: 'f' or 'm'.
        background_color: Background color description (e.g., "magenta (#FF00FF)" or "black (#000000)").
        hair_length: Hair length instruction (e.g., "short", "medium"). Empty string for no hair length control.

    Returns:
        Prompt string for standard school uniform generation.
    """
    if gender_style == "f":
        uniform_desc = (
            "a vibrant navy blue sleeveless blazer with a traditional waistcoat-style hem, outlined with thin gold piping along the lapels and bottom edge. "
            "The chest and breast area of the blazer is smooth, plain, undecorated fabric with nothing on it. "
            "A gold/orange rectangular crest patch is sewn onto the upper arm sleeve area. "
            "The only four buttons are gold in a double-breasted 2x2 arrangement positioned at the waist. "
            "Underneath is a white short-sleeved collared dress shirt with thin blue piping around the collar. "
            "A solid red necktie with no pattern. "
            "A short vibrant magenta-red plaid pleated skirt with a tartan pattern and gold trim at the bottom hem"
        )
    else:
        uniform_desc = (
            "a white short-sleeved collared dress shirt with thin dark piping on the collar edge. "
            "The chest and breast area of the shirt is smooth, plain, undecorated fabric with nothing on it. "
            "A gold/orange rectangular crest patch is sewn onto the upper arm sleeve area. "
            "A solid red necktie with two thin horizontal silver stripes. "
            "Dark navy blue dress trousers with a dark brown leather belt with a gold rectangular buckle. "
            "The shirt is neatly tucked into the trousers"
        )

    if hair_length:
        length_desc = HAIR_LENGTH_DESCRIPTIONS.get(hair_length.lower(), hair_length.lower())
        hair_instruction = f"Change the character's hairstyle completely. Give them a new {hair_length.lower()} length hairstyle that fits their new outfit yet keeps the same hair texture and color. Their hair should now be {length_desc}. "
    else:
        hair_instruction = "Change the character's hairstyle completely to give them a new hairstyle that fits their new outfit yet keeps the same hair color, length, and texture. "

    archetype = archetype_label or "character"
    # Match the structure of build_outfit_prompt which works correctly
    return (
        f"Edit the {archetype}'s clothes so our {archetype} is wearing {uniform_desc}. "
        f"{hair_instruction}"
        "Don't change the size, proportions, framing, art style, or age of the character. "
        f"Give the character a {background_color.split('(')[0].strip()} background behind them. "
        "Make sure the head, arms, hair, hands, and clothes are all kept within the image."
    )


def build_prompt_for_idea(concept: str, archetype_label: str, gender_style: str, background_color: str = "black (#000000)", hair_length: str = "") -> str:
    """
    Build text prompt used when generating a new character from a concept.

    NOTE: Prompt wording updated to avoid triggering safety filters while maintaining functionality.

    Args:
        concept: User's character concept description.
        archetype_label: Character archetype.
        gender_style: 'f' or 'm'.
        background_color: Background color description (e.g., "magenta (#FF00FF)" or "black (#000000)").
        hair_length: Hair length (e.g., "short", "medium").

    Returns:
        Prompt string for new character generation from text.
    """
    bg = background_color.split("(")[0].strip()  # Extract color name (magenta or black)
    archetype_phrase = get_archetype_prompt_phrase(archetype_label)
    return (
        f"Create concept sprite art for an original {archetype_phrase}, for a Japanese-style visual novel. "
        f"The character idea is: {concept} "
        "Match the art style and rendering quality of the input images so the new character has the same artist, vibrant colors, and overall styling. "
        "Have them facing mostly toward the viewer in a friendly, neutral pose, that would work as a base sprite. "
        "They should not be holding anything in their hands. "
        f"Give them a {hair_length.lower()} hairstyle. Keep the hair at {hair_length.lower()} length. Do not make it longer or shorter than that. "
        f"Give the character a {bg} background behind them. "
        "Make sure the head, arms, hair, hands, and clothes are all kept within the image."
    )


def build_normalize_image_prompt(background_color: str = "black (#000000)") -> str:
    """
    Prompt to normalize an uploaded image (sharpen, add background).

    Used in image mode to clean up the source image before further processing.

    Args:
        background_color: Background color string, e.g. "black (#000000)".

    Returns:
        Prompt string for image normalization.
    """
    bg = background_color.split("(")[0].strip()
    return (
        "Sharpen the image to at least 720p resolution if it is lower than that and "
        "correct any artifacts of blurriness. Don't change the size, proportions, "
        f"framing, or art style of the character. Give the character a {bg} "
        "background behind them. Make sure the head, arms, hair, hands, and clothes "
        "are all kept within the image."
    )


def build_normalize_existing_character_prompt(background_color: str = "black (#000000)") -> str:
    """
    Prompt to normalize an existing character image.

    Used in add-to-character mode where the character is already established.

    Args:
        background_color: Background color string, e.g. "black (#000000)".

    Returns:
        Prompt string for existing character normalization.
    """
    bg = background_color.split("(")[0].strip()
    return (
        "Sharpen the image to at least 720p resolution if it is lower than that and "
        "correct any artifacts of blurriness. Don't change the size, proportions, "
        f"framing, or art style of the character. Give the character a {bg} "
        "background behind them. Make sure the head, arms, hair, hands, and clothes "
        "are all kept within the image."
    )


def build_character_modification_prompt(user_instructions: str, background_color: str = "black (#000000)") -> str:
    """
    Prompt to modify a character based on user instructions.

    Used when user wants to change aspects of the character (hair, clothes, etc.)
    while maintaining the same art style.

    Args:
        user_instructions: User's description of desired changes.

    Returns:
        Prompt string for character modification.
    """
    return (
        f"Modify this character based on the following instructions: {user_instructions} "
        "Maintain the same art style, proportions, and overall character design. Apply "
        "the requested changes while keeping the character recognizable. Give the "
        f"character a {background_color.split('(')[0].strip()} background behind them. Make sure the head, arms, "
        "hair, hands, and clothes are all kept within the image."
    )


def build_fusion_prompt(archetype_label: str, gender_style: str, hair_length: str = "", background_color: str = "black (#000000)") -> str:
    """
    Prompt to create a fused character from two source images.

    Creates a new character that blends visual features from both input characters,
    suitable for creating children or combined characters.

    Args:
        archetype_label: Character archetype (e.g., "young woman", "adult man").
        gender_style: 'f' or 'm'.
        hair_length: Hair length (e.g., "short", "medium").

    Returns:
        Prompt string for character fusion.
    """
    archetype_phrase = get_archetype_prompt_phrase(archetype_label)
    hair_line = (
        f"- Blend the two hair colors, use parts of both character's hair styles, or create hair with both colors from the characters in it. The result should be a strictly {hair_length.lower()} hairstyle that incorporates both characters. Keep the hair at {hair_length.lower()} length. Do not make it longer or shorter than that. "
        if hair_length
        else "- Hair could blend both colors or take style from one and color from the other "
    )
    return (
        f"Using the two character images attached, create a completely new {archetype_phrase} that genetically blends both characters - as if this character is their child or sibling. "
        "DO NOT simply recolor one character or give them the other's clothes. This must be a TRUE FUSION with mixed physical features. "
        "Blend specific traits from BOTH characters: "
        "- Face shape from one, eye shape from the other "
        f"{hair_line}"
        f"- Body proportions should balance out while still looking like a completely new {archetype_phrase} "
        "Match the art style of the input images so the new character has the same artist, vibrant colors, and overall styling. "
        "Have the new character facing mostly toward the viewer in a friendly, neutral pose. "
        f"Give the character a {background_color.split('(')[0].strip()} background behind them. "
        "Make sure the head, arms, hair, hands, and clothes are all kept within the image."
    )


# =============================================================================
# Outfit Prompt Utilities
# =============================================================================
# Note: The old CSV-based load_outfit_prompts() function has been removed.
# See src/sprite_creator/data/_stashed_csv_system/README.md for rollback instructions.


def build_simple_outfit_description(outfit_key: str, gender_style: str) -> str:
    """
    Fallback generic outfit description if no CSV prompt is available.

    Args:
        outfit_key: Outfit type (formal, casual, uniform, athletic, swimsuit).
        gender_style: 'f' or 'm'.

    Returns:
        Generic outfit description string.
    """
    # Strip trailing digits from renamed keys (e.g., "formal2" → "formal")
    base_key = outfit_key.rstrip("0123456789") or outfit_key
    gender_word = "female character" if gender_style == "f" else "male character"

    if base_key == "formal":
        return (
            f"a slightly dressy outfit this {gender_word} would wear to a school dance "
            "or evening party, grounded and modern"
        )
    if base_key == "casual":
        return (
            f"a comfy everyday casual outfit this {gender_word} would wear to school "
            "or to hang out with friends"
        )
    if base_key == "uniform":
        return (
            f"a school or work uniform that fits this {gender_word}'s age and vibe, "
            "with clean lines and a coordinated look"
        )
    if base_key == "athletic":
        return (
            f"a sporty and practical athletic outfit this {gender_word} would wear "
            "for PE, training, or a casual game"
        )
    if base_key == "swimsuit":
        return (
            f"a modest but cute swimsuit this {gender_word} would wear to swim practice "
            "or a beach episode, nothing too revealing"
        )

    return f"a simple outfit that fits this {gender_word}'s personality"


def build_outfit_prompts_with_config(
    api_key: str,
    archetype_label: str,
    gender_style: str,
    selected_outfit_keys: List[str],
    outfit_prompt_config: Dict[str, Dict[str, Optional[str]]],
    background_color: str = "",
) -> Dict[str, str]:
    """
    Build one prompt per selected outfit_key, honoring per-outfit settings.

    For each key:
      - use_random=True: Generate dynamic outfit description via Gemini text API.
      - use_random=False: use custom_prompt (fallback if empty for safety).

    Special case: Underwear does NOT use Gemini text API due to high safety filter
    rates. Instead, it uses a tiered fallback system handled by pose_processor.
    This function returns a placeholder for underwear; the actual prompt is
    determined at generation time.

    Args:
        api_key: Google Gemini API key (required for random outfit generation).
        archetype_label: Character archetype.
        gender_style: 'f' or 'm'.
        selected_outfit_keys: List of outfit keys to generate.
        outfit_prompt_config: Per-outfit configuration settings.

    Returns:
        {outfit_key: prompt_text}
    """
    from ..config import UNDERWEAR_FALLBACK_TIERS

    prompts: Dict[str, str] = {}

    for key in selected_outfit_keys:
        config = outfit_prompt_config.get(key, {})
        use_random = bool(config.get("use_random", True))
        custom_prompt = config.get("custom_prompt")

        # Special handling for underwear - uses tier system, not Gemini text
        if key == "underwear" and use_random:
            # Return first tier prompt as placeholder; actual prompt determined at generation time
            tiers = UNDERWEAR_FALLBACK_TIERS.get(archetype_label, ["Pink undergarments"])
            prompts[key] = tiers[0] if tiers else "Pink undergarments"
            continue

        if use_random:
            # Generate dynamic outfit description via Gemini text API
            try:
                prompts[key] = generate_outfit_description(api_key, key, archetype_label, background_color)
            except Exception as e:
                print(f"[WARN] Failed to generate outfit description for {key}: {e}")
                # Fallback to generic description
                prompts[key] = build_simple_outfit_description(key, gender_style)
        else:
            # Use custom prompt, or fallback if empty
            prompts[key] = custom_prompt or build_simple_outfit_description(key, gender_style)

    return prompts
