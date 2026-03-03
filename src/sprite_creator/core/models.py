"""
Data models for the sprite creator.

Contains dataclasses that represent the state and configuration
of characters and the wizard workflow.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class CharacterConfig:
    """
    Configuration for a character to be generated.

    This represents the user's choices about what kind of character
    to create, separate from the wizard UI state.
    """
    name: str = ""
    voice: str = ""  # "girl" or "boy"
    archetype_label: str = ""  # e.g., "Young Woman", "Adult Man"
    gender_style: str = ""  # "f" or "m"
    concept_text: str = ""  # Text description for prompt-based generation
    outfits: List[str] = field(default_factory=list)
    expressions: List[Tuple[str, str]] = field(default_factory=list)
    outfit_prompts: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class WizardState:
    """
    Complete state container for the wizard.

    Tracks all data collected and generated throughout the sprite creation
    process, including setup data, generated artifacts, and navigation state.
    """

    # === Setup Data (Steps 1-4) ===
    source_mode: str = "image"  # "image", "prompt", or "fusion"
    image_path: Optional[Path] = None
    source_image: Optional[Any] = None  # PIL Image for image mode (possibly cropped)
    generated_character_image: Optional[Any] = None  # PIL Image for prompt mode
    normalized_image: Optional[Any] = None  # PIL Image after normalization (from SettingsStep)

    # Fusion mode data
    fusion_left_path: Optional[Path] = None
    fusion_right_path: Optional[Path] = None
    fusion_result_image: Optional[Any] = None  # PIL Image from fusion generation
    voice: str = ""
    display_name: str = ""
    archetype_label: str = ""
    gender_style: str = ""
    concept_text: str = ""  # Only for prompt mode
    hair_length: str = ""  # Hair length for female archetypes (super short/short/medium/long/super long)
    selected_outfits: List[str] = field(default_factory=list)
    expressions_sequence: List[Tuple[str, str]] = field(default_factory=list)
    outfit_prompt_config: Dict[str, Dict] = field(default_factory=dict)

    # === Generation Data (Steps 5-10) ===

    # Step 5: Crop
    crop_y: Optional[int] = None
    cropped_image_path: Optional[Path] = None
    base_pose_normalized_post_crop: bool = False  # True after cropped image re-normalized via Gemini

    # Step 6-7: Base generation
    base_pose_path: Optional[Path] = None
    original_base_bytes: Optional[bytes] = None  # For reset functionality
    use_base_as_outfit: bool = True  # Whether to include the original image as the "Original" outfit
    base_has_been_regenerated: bool = False
    base_regen_instructions: str = ""

    # Step 8: Outfit generation
    outfits_generated: bool = False  # Flag to prevent regeneration on back navigation
    outfit_paths: List[Path] = field(default_factory=list)
    outfit_cleanup_data: List[Tuple[bytes, bytes]] = field(default_factory=list)  # (original, rembg)
    current_outfit_bytes: List[bytes] = field(default_factory=list)
    outfit_bg_modes: Dict[int, str] = field(default_factory=dict)  # index -> "rembg" or "manual"
    outfit_cleanup_settings: List[Tuple[int, int]] = field(default_factory=list)  # (tolerance, depth)
    outfit_prompts: Dict[str, str] = field(default_factory=dict)  # key -> current prompt text
    custom_outfit_prompts: Set[str] = field(default_factory=set)  # outfit keys with user-provided custom prompts
    generated_outfit_keys: List[str] = field(default_factory=list)  # Keys of outfits that succeeded
    last_outfit_prompt_config: Dict[str, Dict] = field(default_factory=dict)  # snapshot for change detection
    last_base_pose_path: Optional[Path] = None  # snapshot of base_pose_path at generation time
    last_base_pose_mtime: Optional[float] = None  # file mtime of base_pose_path at generation time

    # Step 10: Expression generation (per outfit)
    expression_paths: Dict[str, Dict[str, Path]] = field(default_factory=dict)  # outfit -> {expr: path}
    outfits_needing_expression_regen: Set[str] = field(default_factory=set)  # outfit keys whose expressions are stale
    last_expression_sequence: List[Tuple[str, str]] = field(default_factory=list)  # snapshot of expressions_sequence at last generation
    failed_expressions: Set[Tuple[str, str]] = field(default_factory=set)  # (outfit_name, expr_key) pairs that failed generation

    # === Finalization Data (Steps 11-12) ===
    eye_line_ratio: Optional[float] = None
    name_color: Optional[str] = None
    scale_factor: float = 1.0
    apply_scale_to_images: bool = True  # If True, resize all images and set scale to 1.0 (default: ON)
    image_height: Optional[int] = None  # If set, crops sprite display in-game to this many pixels from top

    # === Output ===
    output_root: Optional[Path] = None
    character_folder: Optional[Path] = None
    api_key: Optional[str] = None

    # === Add to Existing Character Mode ===
    is_adding_to_existing: bool = False  # True when in "add to existing" mode
    existing_character_folder: Optional[Path] = None  # The selected existing character folder
    existing_character_data: Dict[str, Any] = field(default_factory=dict)  # Parsed character.yml data
    existing_poses: Dict[str, Any] = field(default_factory=dict)  # Scanned pose data from folder
    existing_scale: float = 1.0  # Scale from existing character.yml
    existing_eye_line: float = 0.0  # Eye line from existing character.yml
    existing_voice: str = ""  # Voice from existing character.yml (preserved at finalization)
    existing_name_color: str = "#ffffff"  # Name color from existing character.yml
    next_pose_letter: str = "a"  # Next available pose letter (d, e, f, etc.)
    selected_base_sprite: Optional[Any] = None  # PIL Image user selected as reference for new outfits
    sprite_creator_poses: List[str] = field(default_factory=list)  # Pose letters created by Sprite Creator (can add expressions to these)
    existing_outfits_to_extend: Dict[str, List[str]] = field(default_factory=dict)  # {pose_letter: [expr_nums]}
    backup_id: Optional[str] = None  # UUID key for external backup storage (~/.sprite_creator/backups/)

    # === Navigation State ===
    current_step: int = 0
    dirty_from_step: Optional[int] = None  # Steps >= this need regeneration

    def mark_dirty_from(self, step_index: int) -> None:
        """
        Mark that steps from the given index onwards need regeneration.

        Used when user navigates back and makes changes that invalidate
        later generated content.
        """
        if self.dirty_from_step is None or step_index < self.dirty_from_step:
            self.dirty_from_step = step_index

    def clear_dirty(self) -> None:
        """Clear the dirty flag after regeneration has been handled."""
        self.dirty_from_step = None

    def is_step_dirty(self, step_index: int) -> bool:
        """Check if a step needs regeneration."""
        return self.dirty_from_step is not None and step_index >= self.dirty_from_step

    def get_preselected_dict(self) -> Dict:
        """
        Get character info as a dict for pipeline compatibility.

        Returns dict with voice, display_name, archetype_label, gender_style,
        selected_outfits, expressions_sequence, outfit_prompt_config.
        """
        return {
            "voice": self.voice,
            "display_name": self.display_name,
            "archetype_label": self.archetype_label,
            "gender_style": self.gender_style,
            "selected_outfits": self.selected_outfits,
            "expressions_sequence": self.expressions_sequence,
            "outfit_prompt_config": self.outfit_prompt_config,
        }

    def to_character_config(self) -> CharacterConfig:
        """Convert wizard state to a CharacterConfig."""
        return CharacterConfig(
            name=self.display_name,
            voice=self.voice,
            archetype_label=self.archetype_label,
            gender_style=self.gender_style,
            concept_text=self.concept_text,
            outfits=list(self.selected_outfits),
            expressions=list(self.expressions_sequence),
            outfit_prompts=dict(self.outfit_prompt_config),
        )
