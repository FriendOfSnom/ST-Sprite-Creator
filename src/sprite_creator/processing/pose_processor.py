"""
Pose processing and outfit generation.

Handles outfit generation, pose flattening, and character.yml writing.
"""

import random
import shutil
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml
from PIL import Image

from ..api.exceptions import GeminiAPIError, GeminiSafetyError
from ..api.gemini_client import (
    call_gemini_image_edit,
    call_gemini_text_or_refs,
    load_image_as_base64,
    strip_background_ai,
    cleanup_edge_halos,
    REMBG_EDGE_CLEANUP_TOLERANCE,
    REMBG_EDGE_CLEANUP_PASSES,
)
from ..api.prompt_builders import (
    build_outfit_prompt,
    build_standard_school_uniform_prompt,
)
from ..config import (
    FEMALE_ARCHETYPES,
    UNDERWEAR_COLORS,
    UNDERWEAR_TIER0_PROMPTS,
    UNDERWEAR_FALLBACK_TIERS,
)
from .image_utils import (
    save_image_bytes_as_png,
    get_standard_uniform_reference_images,
)


def write_character_yml(
    path: Path,
    display_name: str,
    voice: str,
    eye_line: float,
    name_color: str,
    scale: float,
    poses: Dict[str, Dict[str, str]],
    *,
    game: Optional[str] = None,
    archetype: Optional[str] = None,
    hair_length: Optional[str] = None,
    sprite_creator_poses: Optional[List[str]] = None,
    original_size: Optional[List[int]] = None,
    backup_id: Optional[str] = None,
) -> None:
    """
    Write final character metadata YAML in organizer format.

    Args:
        path: Path to character.yml file.
        display_name: Character's display name.
        voice: Character voice ("girl"/"boy", converted to "male" if "boy").
        eye_line: Eye line ratio (0.0-1.0).
        name_color: Hex color for name display.
        scale: Character scale multiplier.
        poses: Dict of pose letters to pose metadata.
        game: Optional game name to include in metadata.
        archetype: Optional archetype label (e.g., "Young Woman", "Adult Man").
        sprite_creator_poses: Optional list of pose letters created by Sprite Creator.
        original_size: Optional [width, height] of original full-size images before scaling.
        backup_id: Optional UUID key for external backup storage.
    """
    v = (voice or "").lower()
    voice_out = "male" if v == "boy" else voice

    data = {
        "display_name": display_name,
        "eye_line": round(float(eye_line), 4),
        "name_color": name_color,
        "poses": poses,
        "scale": float(scale),
        "voice": voice_out,
    }
    if game:
        data["game"] = game
    if archetype:
        data["archetype"] = archetype
    if hair_length:
        data["hair_length"] = hair_length
    if sprite_creator_poses:
        data["sprite_creator_poses"] = sorted(sprite_creator_poses)
    if original_size:
        data["original_size"] = original_size
    if backup_id:
        data["backup_id"] = backup_id

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)

    print(f"[INFO] Wrote character YAML to: {path}")


def _generate_outfit_with_safety_recovery(
    api_key: str,
    base_pose_path: Path,
    gender_style: str,
    outfit_key: str,
    outfit_desc: str,
    archetype_label: str,
    outfit_prompt_config: Dict[str, Dict[str, Optional[str]]],
    skip_background_removal: bool = False,
    tier_progress_callback: Optional[Callable[[int, int], None]] = None,
    hair_length: str = "",
) -> Optional[Tuple[bytes, str]]:
    """
    Generate outfit with multi-tier safety error recovery.

    For underwear (random mode): Uses dedicated tier system from the start.
      - Tier 0: 2 random attempts (color + prompt for females, just prompt for males)
      - Tier 1-N: Ordered fallback from UNDERWEAR_FALLBACK_TIERS
      - Skip gracefully if all tiers fail

    For non-underwear or custom underwear: Simple retry logic.

    AI background removal is automatically applied unless skip_background_removal=True.

    Args:
        api_key: Gemini API key.
        base_pose_path: Path to base pose image.
        gender_style: 'f' or 'm'.
        outfit_key: Outfit identifier.
        outfit_desc: Initial outfit description/prompt.
        archetype_label: Character archetype.
        outfit_prompt_config: Per-outfit configuration.
        skip_background_removal: If True, return raw Gemini output without rembg.
        hair_length: Hair length for styling (e.g., "short", "medium"). Empty for no control.

    Returns:
        Tuple of (image_bytes, successful_prompt) if successful, None if all tiers fail.
    """
    image_b64 = load_image_as_base64(base_pose_path)
    tried_prompts = set()
    # Use black background for clean AI removal
    background_color = "solid black (#000000)"

    def try_generate(desc: str, tier_name: str) -> Optional[bytes]:
        tried_prompts.add(desc)
        try:
            prompt = build_outfit_prompt(desc, gender_style, background_color, hair_length=hair_length)
            return call_gemini_image_edit(api_key, prompt, image_b64, skip_background_removal)
        except GeminiSafetyError as e:
            print(f"[WARN] {tier_name}: Safety error during '{outfit_key}' generation")
            print(f"[WARN] Blocked prompt: \"{desc[:100]}{'...' if len(desc) > 100 else ''}\"")
            if e.safety_ratings:
                print(f"[WARN] Safety ratings: {e.safety_ratings}")
            return None
        except GeminiAPIError as e:
            print(f"[WARN] {tier_name}: API error during '{outfit_key}' generation: {e}")
            return None

    config = outfit_prompt_config.get(outfit_key, {})
    use_random = config.get("use_random", True)

    # =========================================================================
    # UNDERWEAR: Special tier system (only when using random mode)
    # =========================================================================
    if outfit_key == "underwear" and use_random:
        is_female = archetype_label in FEMALE_ARCHETYPES
        tier0_prompts = UNDERWEAR_TIER0_PROMPTS.get(archetype_label, [])
        fallback_tiers = UNDERWEAR_FALLBACK_TIERS.get(archetype_label, ["Pink undergarments"])

        # Calculate total attempts for progress reporting
        total_attempts = 2 + len(fallback_tiers)
        current_attempt = 0

        # Tier 0: 2 random attempts with variety
        for attempt in range(2):
            current_attempt += 1
            if tier_progress_callback:
                tier_progress_callback(current_attempt, total_attempts)

            if tier0_prompts:
                base_prompt = random.choice(tier0_prompts)
            else:
                base_prompt = fallback_tiers[0] if fallback_tiers else "Pink undergarments"

            if is_female:
                color = random.choice(UNDERWEAR_COLORS)
                prompt_to_try = f"{color} {base_prompt.lower()}"
            else:
                prompt_to_try = base_prompt

            print(f"  [Underwear] Tier 0 attempt {attempt + 1}: \"{prompt_to_try}\"")
            img_bytes = try_generate(prompt_to_try, f"Tier 0.{attempt + 1}")
            if img_bytes:
                return (img_bytes, prompt_to_try)

        # Tier 1-N: Ordered fallback through tiers
        for tier_idx, tier_prompt in enumerate(fallback_tiers):
            if tier_prompt in tried_prompts:
                continue

            current_attempt += 1
            if tier_progress_callback:
                tier_progress_callback(current_attempt, total_attempts)

            print(f"  [Underwear] Tier {tier_idx + 1}: \"{tier_prompt}\"")
            img_bytes = try_generate(tier_prompt, f"Tier {tier_idx + 1}")
            if img_bytes:
                return (img_bytes, tier_prompt)

        # All underwear tiers exhausted
        print(
            f"[WARN] All underwear tiers exhausted for '{archetype_label}'. "
            "Skipping underwear outfit."
        )
        return None

    # =========================================================================
    # NON-UNDERWEAR (or custom underwear): Standard generation with simple retry
    # =========================================================================
    print(f"  [Safety] Attempting '{outfit_key}' generation...")
    img_bytes = try_generate(outfit_desc, "Tier 1")
    if img_bytes:
        return (img_bytes, outfit_desc)

    # Retry once
    print(f"[INFO] Tier 1 Recovery: Retrying same prompt once...")
    img_bytes = try_generate(outfit_desc, "Tier 1 Retry")
    if img_bytes:
        print(f"[INFO] Tier 1 Recovery: Retry succeeded")
        return (img_bytes, outfit_desc)

    print(f"[WARN] Tier 1 Recovery: Retry failed for '{outfit_key}'")

    # All tiers exhausted - return None to skip gracefully
    print(
        f"[WARN] All recovery tiers exhausted for outfit '{outfit_key}' "
        f"(archetype: {archetype_label}). Skipping this outfit."
    )
    return None


def generate_single_outfit(
    api_key: str,
    base_pose_path: Path,
    outfits_dir: Path,
    gender_style: str,
    outfit_key: str,
    outfit_desc: str,
    outfit_prompt_config: Dict[str, Dict[str, Optional[str]]],
    archetype_label: str,
    for_interactive_review: bool = False,
    tier_progress_callback: Optional[Callable[[int, int], None]] = None,
    hair_length: str = "",
) -> Optional[Path] | Optional[Tuple[Path, bytes, bytes, str]]:
    """
    Generate or regenerate a single outfit image for the given key.

    This is used both by the bulk outfit generator and by the
    per-outfit "regenerate" buttons in the review window.
    AI background removal is automatically applied.

    Args:
        api_key: Gemini API key.
        base_pose_path: Path to base pose image.
        outfits_dir: Directory to save outfits.
        gender_style: 'f' or 'm'.
        outfit_key: Outfit identifier.
        outfit_desc: Outfit description/prompt.
        outfit_prompt_config: Per-outfit configuration.
        archetype_label: Character archetype.
        for_interactive_review: If True, return (path, original_bytes, rembg_bytes, used_prompt)
            so the review UI can apply custom edge cleanup settings.

    Returns:
        If for_interactive_review=False: Path to saved outfit, or None if failed.
        If for_interactive_review=True: (path, original_bytes, rembg_bytes, used_prompt), or None if failed.
    """
    outfits_dir.mkdir(parents=True, exist_ok=True)

    config = outfit_prompt_config.get(outfit_key, {})

    # Special handling for standardized school uniform
    # Check use_standard_uniform flag directly - works for "uniform", "uniform2", etc.
    if config.get("use_standard_uniform"):
        result = generate_standard_uniform_outfit(
            api_key,
            base_pose_path,
            outfits_dir,
            gender_style,
            archetype_label,
            outfit_desc,
            outfit_key=outfit_key,  # Pass key for correct filename (uniform2, etc.)
            for_interactive_review=for_interactive_review,
            hair_length=hair_length,
        )
        if result is None:
            return None
        if for_interactive_review:
            final_path, original_bytes, rembg_bytes = result
            print(f"  Saved standardized outfit '{outfit_key}' to: {final_path}")
            # Standard uniform uses the outfit_desc as the prompt
            return (final_path, original_bytes, rembg_bytes, outfit_desc)
        else:
            print(f"  Saved standardized outfit '{outfit_key}' to: {result}")
            return result

    # Normal text-prompt-based outfit with safety recovery
    out_stem = outfits_dir / outfit_key.capitalize()

    try:
        if for_interactive_review:
            # Get raw Gemini output (no rembg yet)
            result = _generate_outfit_with_safety_recovery(
                api_key,
                base_pose_path,
                gender_style,
                outfit_key,
                outfit_desc,
                archetype_label,
                outfit_prompt_config,
                skip_background_removal=True,
                tier_progress_callback=tier_progress_callback,
                hair_length=hair_length,
            )

            if result is None:
                print(f"[WARN] Skipping outfit '{outfit_key}' - could not generate safely")
                return None

            original_bytes, used_prompt = result

            # Run rembg without edge cleanup (user will apply cleanup in review UI)
            rembg_bytes = strip_background_ai(original_bytes, skip_edge_cleanup=True)

            # Save rembg result initially (may be updated after review)
            final_path = save_image_bytes_as_png(rembg_bytes, out_stem)
            print(f"  Saved outfit '{outfit_key}' to: {final_path}")
            return (final_path, original_bytes, rembg_bytes, used_prompt)
        else:
            # Normal flow: full background removal with default edge cleanup
            result = _generate_outfit_with_safety_recovery(
                api_key,
                base_pose_path,
                gender_style,
                outfit_key,
                outfit_desc,
                archetype_label,
                outfit_prompt_config,
                tier_progress_callback=tier_progress_callback,
                hair_length=hair_length,
            )

            if result is None:
                print(f"[WARN] Skipping outfit '{outfit_key}' - could not generate safely")
                return None

            img_bytes, _ = result  # Don't need the prompt for non-interactive

            final_path = save_image_bytes_as_png(img_bytes, out_stem)
            print(f"  Saved outfit '{outfit_key}' to: {final_path}")
            return final_path
    except GeminiSafetyError as e:
        # This should not happen (recovery should handle it), but just in case
        print(f"[ERROR] Unrecovered safety error for outfit '{outfit_key}': {e}")
        raise


def generate_standard_uniform_outfit(
    api_key: str,
    base_pose_path: Path,
    outfits_dir: Path,
    gender_style: str,
    archetype_label: str,
    outfit_desc: str,  # Kept for signature compatibility
    outfit_key: str = "uniform",  # The actual outfit key (uniform, uniform2, etc.)
    for_interactive_review: bool = False,
    hair_length: str = "",
) -> Path | Tuple[Path, bytes, bytes]:
    """
    Generate the standardized school uniform outfit using reference images.

    Uses the base pose as the main character to keep, and a cropped uniform
    reference image (gender-specific) as visual guidance.
    AI background removal is automatically applied.

    Args:
        api_key: Gemini API key.
        base_pose_path: Path to base pose image.
        outfits_dir: Directory to save outfits.
        gender_style: 'f' or 'm'.
        archetype_label: Character archetype.
        outfit_desc: Not used directly, kept for compatibility.
        for_interactive_review: If True, return (path, original_bytes, rembg_bytes).

    Returns:
        If for_interactive_review=False: Path to saved uniform outfit.
        If for_interactive_review=True: (path, original_bytes, rembg_bytes).
    """
    outfits_dir.mkdir(parents=True, exist_ok=True)
    # Use black background for clean AI removal
    background_color = "solid black (#000000)"

    # Collect the uniform reference image(s) for this gender
    uniform_refs = get_standard_uniform_reference_images(gender_style)

    if not uniform_refs:
        # Fallback to normal outfit prompt path
        print("[WARN] No uniform reference found, falling back to normal prompt-based uniform.")
        image_b64 = load_image_as_base64(base_pose_path)
        prompt = build_outfit_prompt(outfit_desc, gender_style, background_color, hair_length=hair_length)

        if for_interactive_review:
            original_bytes = call_gemini_image_edit(api_key, prompt, image_b64, skip_background_removal=True)
            rembg_bytes = strip_background_ai(original_bytes, skip_edge_cleanup=True)
            out_stem = outfits_dir / outfit_key.capitalize()
            final_path = save_image_bytes_as_png(rembg_bytes, out_stem)
            print(f"  Saved fallback prompt-based uniform to: {final_path}")
            return (final_path, original_bytes, rembg_bytes)
        else:
            img_bytes = call_gemini_image_edit(api_key, prompt, image_b64)
            out_stem = outfits_dir / outfit_key.capitalize()
            final_path = save_image_bytes_as_png(img_bytes, out_stem)
            print(f"  Saved fallback prompt-based uniform to: {final_path}")
            return final_path

    # Log which uniform reference exists (for debugging)
    uniform_ref = uniform_refs[0]
    print(f"[INFO] Found uniform reference: {uniform_ref} (using detailed text prompt instead)")

    # Build unified, standardized uniform prompt with detailed description
    uniform_prompt = build_standard_school_uniform_prompt(
        archetype_label,
        gender_style,
        background_color,
        hair_length=hair_length,
    )

    # Use call_gemini_image_edit (like casual/athletic outfits) to properly edit
    # the base pose. The detailed text description guides the uniform generation.
    image_b64 = load_image_as_base64(base_pose_path)

    if for_interactive_review:
        original_bytes = call_gemini_image_edit(
            api_key,
            uniform_prompt,
            image_b64,
            skip_background_removal=True,
        )
        rembg_bytes = strip_background_ai(original_bytes, skip_edge_cleanup=True)
        out_stem = outfits_dir / outfit_key.capitalize()
        final_path = save_image_bytes_as_png(rembg_bytes, out_stem)
        print(f"  Saved standardized school uniform to: {final_path}")
        return (final_path, original_bytes, rembg_bytes)
    else:
        img_bytes = call_gemini_image_edit(
            api_key,
            uniform_prompt,
            image_b64,
        )
        out_stem = outfits_dir / outfit_key.capitalize()
        final_path = save_image_bytes_as_png(img_bytes, out_stem)
        print(f"  Saved standardized school uniform to: {final_path}")
        return final_path


def generate_outfits_once(
    api_key: str,
    base_pose_path: Path,
    outfits_dir: Path,
    gender_style: str,
    outfit_descriptions: Dict[str, str],
    outfit_prompt_config: Dict[str, Dict[str, Optional[str]]],
    archetype_label: str,
    include_base_outfit: bool = True,
    for_interactive_review: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    hair_length: str = "",
) -> List[Path] | Tuple[List[Path], List[Tuple[bytes, bytes]], Dict[str, str]]:
    """
    Generate outfits for a pose.

    Layout:
      - If include_base_outfit=True: copies base pose as Base.png.
      - For each outfit_descriptions[key], generate <Key>.png.

    AI background removal is automatically applied to all generated outfits.

    Args:
        api_key: Gemini API key.
        base_pose_path: Path to base pose image.
        outfits_dir: Directory to save outfits.
        gender_style: 'f' or 'm'.
        outfit_descriptions: Dict of outfit keys to descriptions.
        outfit_prompt_config: Per-outfit configuration.
        archetype_label: Character archetype.
        include_base_outfit: Whether to include base pose as an outfit.
        for_interactive_review: If True, return cleanup data for review UI.

    Returns:
        If for_interactive_review=False: List of paths to generated outfit images.
        If for_interactive_review=True: (paths, cleanup_data, used_prompts) where cleanup_data is
            list of (original_bytes, rembg_bytes) tuples for each outfit, and used_prompts is
            a dict mapping outfit keys to the actual prompts that succeeded.
    """
    outfits_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    cleanup_data: List[Tuple[bytes, bytes]] = []
    used_prompts: Dict[str, str] = {}

    # Optional: include base pose as "Base.png" outfit (with background removal)
    if include_base_outfit:
        base_bytes = base_pose_path.read_bytes()  # Original with solid background
        base_out_path = (outfits_dir / "Base").with_suffix(".png")

        if for_interactive_review:
            # Run rembg without edge cleanup (user will apply cleanup in review UI)
            rembg_bytes = strip_background_ai(base_bytes, skip_edge_cleanup=True)
            # Save rembg result initially (may be updated after review)
            base_img = Image.open(BytesIO(rembg_bytes)).convert("RGBA")
            base_img.save(base_out_path, format="PNG", compress_level=0, optimize=False)
            paths.append(base_out_path)
            cleanup_data.append((base_bytes, rembg_bytes))
            # Base outfit has no prompt
        else:
            # Normal flow: full background removal with default edge cleanup
            processed_bytes = strip_background_ai(base_bytes)
            base_img = Image.open(BytesIO(processed_bytes)).convert("RGBA")
            base_img.save(base_out_path, format="PNG", compress_level=0, optimize=False)
            paths.append(base_out_path)

    # Generate each selected outfit key
    total_outfits = len(outfit_descriptions)
    for idx, (key, desc) in enumerate(outfit_descriptions.items()):
        # Report progress
        if progress_callback:
            progress_callback(idx + 1, total_outfits, key)

        # Create tier progress callback for underwear to report attempt numbers
        def _tier_cb(attempt: int, total: int, outfit=key) -> None:
            if progress_callback:
                progress_callback(idx + 1, total_outfits, f"{outfit} (Attempt {attempt} of {total})")

        result = generate_single_outfit(
            api_key,
            base_pose_path,
            outfits_dir,
            gender_style,
            key,
            desc,
            outfit_prompt_config,
            archetype_label,
            for_interactive_review=for_interactive_review,
            tier_progress_callback=_tier_cb if key == "underwear" else None,
            hair_length=hair_length,
        )

        if result is None:
            continue

        if for_interactive_review:
            final_path, original_bytes, rembg_bytes, prompt_used = result
            paths.append(final_path)
            cleanup_data.append((original_bytes, rembg_bytes))
            used_prompts[key] = prompt_used
        else:
            paths.append(result)

    if for_interactive_review:
        return (paths, cleanup_data, used_prompts)
    return paths


def flatten_pose_outfits_to_letter_poses(
    char_dir: Path,
    starting_letter: str = "a",
) -> List[str]:
    """
    Flatten pose/outfit combos into separate letter poses with single outfits.

    Input:
        <char>/a/outfits/OutfitName.png
        <char>/a/faces/face/*.webp
        <char>/a/faces/OutfitName/*.webp

    Output:
        <char>/a, /b, /c, ... each with outfits/<OutfitName>.png (transparent base)
        and faces/face/0.webp..N.webp

    Args:
        char_dir: Character directory.
        starting_letter: First letter to use for pose assignment (default 'a').
            Use this when adding to an existing character (e.g., 'd' if existing has a,b,c).

    Returns:
        List of final pose letters (sorted).
    """
    original_pose_dirs = [
        p for p in char_dir.iterdir()
        if p.is_dir() and len(p.name) == 1 and p.name.isalpha()
    ]
    original_pose_dirs.sort(key=lambda p: p.name)

    tmp_root = char_dir / "_tmp_pose_flattened"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    letters = [chr(ord("a") + i) for i in range(26)]
    # Start from the specified letter
    start_index = ord(starting_letter.lower()) - ord('a')
    next_index = max(0, min(start_index, 25))  # Clamp to valid range

    def _next_letter() -> Optional[str]:
        nonlocal next_index
        if next_index >= len(letters):
            return None
        letter = letters[next_index]
        next_index += 1
        return letter

    final_pose_letters: List[str] = []

    for pose_dir in original_pose_dirs:
        outfits_dir = pose_dir / "outfits"
        faces_root = pose_dir / "faces"

        if not outfits_dir.is_dir() or not faces_root.is_dir():
            continue

        for outfit_path in sorted(outfits_dir.iterdir()):
            if not outfit_path.is_file():
                continue
            if outfit_path.suffix.lower() not in (".png", ".webp"):
                continue

            outfit_name = outfit_path.stem
            if outfit_name.lower() == "base":
                src_expr_dir = faces_root / "face"
            else:
                src_expr_dir = faces_root / outfit_name

            if not src_expr_dir.is_dir():
                print(
                    f"[WARN] No expression folder for pose '{pose_dir.name}', "
                    f"outfit '{outfit_name}' at {src_expr_dir}; skipping."
                )
                continue

            pose_letter = _next_letter()
            if pose_letter is None:
                print(
                    "[WARN] Ran out of pose letters (more than 26 combinations); "
                    "skipping remaining outfits."
                )
                break

            new_pose_dir = tmp_root / pose_letter
            new_faces_dir = new_pose_dir / "faces" / "face"
            new_outfits_dir = new_pose_dir / "outfits"
            new_faces_dir.mkdir(parents=True, exist_ok=True)
            new_outfits_dir.mkdir(parents=True, exist_ok=True)

            # Copy expression files
            for src in sorted(src_expr_dir.iterdir()):
                if not src.is_file():
                    continue
                dest = new_faces_dir / src.name
                shutil.copy2(src, dest)

            # Create transparent outfit base
            try:
                outfit_img = Image.open(outfit_path).convert("RGBA")
                w, h = outfit_img.size
                transparent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                out_name = outfit_path.stem + outfit_path.suffix.lower()
                transparent.save(new_outfits_dir / out_name)
            except Exception as e:
                print(
                    f"[WARN] Failed to create transparent outfit for "
                    f"{pose_dir.name}/{outfit_name}: {e}"
                )
                continue

            final_pose_letters.append(pose_letter)
            print(
                f"[INFO] Created pose '{pose_letter}' from "
                f"orig pose '{pose_dir.name}', outfit '{outfit_name}'"
            )

    # Remove original pose directories
    for pose_dir in original_pose_dirs:
        try:
            shutil.rmtree(pose_dir)
        except Exception as e:
            print(f"[WARN] Failed to remove original pose folder {pose_dir}: {e}")

    # Move flattened poses to character directory
    for new_pose_dir in sorted(tmp_root.iterdir(), key=lambda p: p.name):
        if not new_pose_dir.is_dir():
            continue
        target = char_dir / new_pose_dir.name
        if target.exists():
            try:
                shutil.rmtree(target)
            except Exception:
                pass
        shutil.move(str(new_pose_dir), str(target))

    # Clean up temp directory
    try:
        shutil.rmtree(tmp_root)
    except Exception:
        pass

    final_pose_letters.sort()
    return final_pose_letters
