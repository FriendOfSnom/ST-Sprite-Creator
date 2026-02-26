"""
API module for Gemini interactions.

Handles all communication with Google Gemini API including:
- Authentication and configuration
- Image generation and editing
- Retry logic and error handling
- Prompt building
"""

from .gemini_client import (
    get_api_key,
    call_gemini_image_edit,
    call_gemini_text_or_refs,
    load_config,
    save_config,
    interactive_api_key_setup,
    strip_background_ai,
    strip_background_threshold,
    cleanup_edge_halos,
    REMBG_EDGE_CLEANUP_TOLERANCE,
    REMBG_EDGE_CLEANUP_PASSES,
)

from .background_removal_legacy import strip_background_legacy

from .uploader import upload_character_zip

from .prompt_builders import (
    build_expression_prompt,
    build_outfit_prompt,
    build_standard_school_uniform_prompt,
    build_prompt_for_idea,
    archetype_to_gender_style,
    build_outfit_prompts_with_config,
    build_simple_outfit_description,
    generate_outfit_description,
)

__all__ = [
    # Client functions
    "get_api_key",
    "call_gemini_image_edit",
    "call_gemini_text_or_refs",
    "load_config",
    "save_config",
    "interactive_api_key_setup",
    # Background removal
    "strip_background_ai",
    "strip_background_threshold",
    "strip_background_legacy",
    "cleanup_edge_halos",
    "REMBG_EDGE_CLEANUP_TOLERANCE",
    "REMBG_EDGE_CLEANUP_PASSES",
    # Prompt builders
    "build_expression_prompt",
    "build_outfit_prompt",
    "build_standard_school_uniform_prompt",
    "build_prompt_for_idea",
    "archetype_to_gender_style",
    "build_outfit_prompts_with_config",
    "build_simple_outfit_description",
    "generate_outfit_description",
    # Upload
    "upload_character_zip",
]
