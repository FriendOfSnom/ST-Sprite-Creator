"""
Expression generation and character creation workflows.

Handles expression generation for outfits, regeneration of individual expressions,
and prompt-based character generation.
"""

import random
import sys
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from PIL import Image

from ..config import (
    EXPRESSIONS_SEQUENCE,
    REF_SPRITES_DIR,
    SAFETY_FALLBACK_EXPRESSION_PROMPTS,
)

from ..api.exceptions import GeminiAPIError, GeminiSafetyError
from ..api.gemini_client import (
    call_gemini_image_edit,
    call_gemini_text_or_refs,
    cleanup_edge_halos,
    load_image_as_base64,
    strip_background_ai,
    REMBG_EDGE_CLEANUP,
)
from ..api.prompt_builders import (
    build_expression_prompt,
    build_prompt_for_idea,
)
from ..ui.review_windows import review_images_for_step, click_to_remove_background
from .image_utils import (
    save_img_as_png,
    save_image_bytes_as_png,
    get_reference_images_for_archetype,
)


def _generate_expression_with_safety_recovery(
    api_key: str,
    image_b64: str,
    expr_index: int,
    expr_key: str,
    expr_desc: str,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
    for_interactive_review: bool = False,
    bg_removal_mode: str = "rembg",
    archetype_label: str = "",
) -> Union[Optional[bytes], Optional[Tuple[bytes, bytes]]]:
    """
    Generate expression with 2-tier safety error recovery.

    Tier 1: Retry same prompt once
    Tier 2: Use modestly worded fallback (if available)

    AI background removal is automatically applied unless for_interactive_review=True,
    in which case both original and rembg bytes are returned.

    Args:
        api_key: Gemini API key.
        image_b64: Base64-encoded source image.
        expr_index: Numeric index of expression (for logging).
        expr_key: Expression key string (e.g., "7", "8").
        expr_desc: Expression description.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).
        for_interactive_review: If True, return (original_bytes, rembg_bytes) tuple.
        archetype_label: Character archetype (e.g., "young woman", "adult man").

    Returns:
        If for_interactive_review=False: Image bytes with transparent BG, or None if failed.
        If for_interactive_review=True: (original_bytes, rembg_bytes) tuple, or None if failed.
    """
    # Use black background for clean AI removal (consistent with outfits)
    background_color = "solid black (#000000)"

    def try_generate(desc: str, tier_name: str) -> Union[Optional[bytes], Optional[Tuple[bytes, bytes]]]:
        try:
            prompt = build_expression_prompt(desc, background_color, archetype_label=archetype_label)
            if for_interactive_review:
                # Get original bytes without rembg
                original_bytes = call_gemini_image_edit(
                    api_key, prompt, image_b64,
                    skip_background_removal=True,
                )
                if bg_removal_mode == "manual":
                    # Manual mode: skip rembg, return original bytes for both
                    return (original_bytes, original_bytes)
                else:
                    # Rembg mode: apply rembg, then edge cleanup with user's settings
                    rembg_bytes = strip_background_ai(original_bytes, skip_edge_cleanup=True)
                    if REMBG_EDGE_CLEANUP:
                        cleaned_bytes = cleanup_edge_halos(
                            original_bytes=original_bytes,
                            result_bytes=rembg_bytes,
                            tolerance=edge_cleanup_tolerance if edge_cleanup_tolerance is not None else 0,
                            passes=edge_cleanup_passes if edge_cleanup_passes is not None else 0,
                        )
                    else:
                        cleaned_bytes = rembg_bytes
                    return (original_bytes, cleaned_bytes)
            else:
                if bg_removal_mode == "manual":
                    # Manual mode: skip background removal entirely
                    return call_gemini_image_edit(
                        api_key, prompt, image_b64,
                        skip_background_removal=True,
                    )
                else:
                    return call_gemini_image_edit(
                        api_key, prompt, image_b64,
                        edge_cleanup_tolerance=edge_cleanup_tolerance,
                        edge_cleanup_passes=edge_cleanup_passes,
                    )
        except GeminiSafetyError as e:
            print(f"[WARN] {tier_name}: Safety error for expression {expr_index} ('{expr_key}')")
            print(f"[WARN] Blocked description: \"{desc}\"")
            if e.safety_ratings:
                print(f"[WARN] Safety ratings: {e.safety_ratings}")
            return None
        except GeminiAPIError as e:
            print(f"[WARN] {tier_name}: API error for expression {expr_index} ('{expr_key}'): {e}")
            return None

    # Tier 1: Try original description
    result = try_generate(expr_desc, "Tier 1")
    if result:
        return result

    # Tier 1 Retry: Same description, one more time
    print(f"[INFO] Tier 1 Recovery: Retrying expression {expr_index} once...")
    result = try_generate(expr_desc, "Tier 1 Retry")
    if result:
        print(f"[INFO] Tier 1 Recovery: Retry succeeded")
        return result

    print(f"[WARN] Tier 1 Recovery: Retry failed for expression {expr_index}")

    # Tier 2: Use fallback description (if available)
    fallback = SAFETY_FALLBACK_EXPRESSION_PROMPTS.get(expr_key)
    if fallback:
        print(f"[INFO] Tier 2 Recovery: Using modest fallback for expression {expr_index}")
        print(f"[INFO] Fallback description: \"{fallback}\"")

        result = try_generate(fallback, "Tier 2")
        if result:
            print(f"[INFO] Tier 2 Recovery: Fallback succeeded")
            return result

        print(f"[WARN] Tier 2 Recovery: Fallback also blocked")
    else:
        print(f"[INFO] Tier 2 Recovery: No fallback available for expression {expr_index}")

    # All attempts failed
    print(f"[WARN] Skipping expression {expr_index} - all recovery attempts failed")
    return None


def generate_expressions_for_single_outfit_once(
    api_key: str,
    pose_dir: Path,
    outfit_path: Path,
    faces_root: Path,
    expressions_sequence: Optional[List[Tuple[str, str]]] = None,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
    for_interactive_review: bool = False,
    bg_removal_mode: str = "rembg",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    archetype_label: str = "",
) -> Union[List[Path], Tuple[List[Path], List[Tuple[bytes, bytes]]]]:
    """
    Generate a full expression set for a single outfit in a single pose.

    Layout (pose 'a', outfit 'Base'):
        a/outfits/Base.png
        a/faces/face/0.png ... N.png
    For non-base outfits (e.g. 'Formal'):
        a/faces/Formal/0.webp ... N.webp

    0.png is always the neutral outfit image itself.
    AI background removal is automatically applied.

    Args:
        api_key: Gemini API key.
        pose_dir: Pose directory.
        outfit_path: Path to outfit image.
        faces_root: Root directory for face images.
        expressions_sequence: List of (key, description) tuples for expressions.
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).
        for_interactive_review: If True, return (paths, cleanup_data) for manual BG removal.

    Returns:
        If for_interactive_review=False: List of paths to expression images.
        If for_interactive_review=True: (paths, cleanup_data) where cleanup_data is
            list of (original_bytes, rembg_bytes) tuples.
    """
    faces_root.mkdir(parents=True, exist_ok=True)
    if expressions_sequence is None:
        expressions_sequence = EXPRESSIONS_SEQUENCE

    generated_paths: List[Path] = []
    cleanup_data: List[Tuple[bytes, bytes]] = []
    generated_keys: List[str] = []  # Track which expression keys actually generated
    failed_keys: List[Tuple[str, str]] = []  # Track (key, desc) of failed expressions

    if not outfit_path.is_file() or outfit_path.suffix.lower() not in (".png", ".webp"):
        if for_interactive_review:
            return (generated_paths, cleanup_data, generated_keys, failed_keys)
        return generated_paths

    outfit_name = outfit_path.stem
    if outfit_name.lower() == "base":
        out_dir = faces_root / "face"
    else:
        out_dir = faces_root / outfit_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] Generating expressions for pose '{pose_dir.name}', "
        f"outfit '{outfit_name}'"
    )

    # Clear existing expression files
    for f in list(out_dir.iterdir()):
        if f.is_file():
            try:
                f.unlink()
            except Exception:
                pass

    # Save neutral expression (0) as the outfit itself
    neutral_stem = out_dir / "0"
    outfit_img = Image.open(outfit_path).convert("RGBA")
    neutral_path = save_img_as_png(outfit_img, neutral_stem)
    generated_paths.append(neutral_path)
    generated_keys.append(expressions_sequence[0][0])  # Neutral key (usually "0")
    print(f"  [Expr] Using outfit as neutral '0' -> {neutral_path}")

    # For neutral (0), the "original" is the outfit bytes (already has transparent BG)
    if for_interactive_review:
        outfit_bytes = outfit_path.read_bytes()
        cleanup_data.append((outfit_bytes, outfit_bytes))  # Same bytes for both

    # Generate remaining expressions
    image_b64 = load_image_as_base64(outfit_path)
    total_expressions = len(expressions_sequence)

    for idx, (orig_key, desc) in enumerate(expressions_sequence[1:], start=1):
        # Use the original key (e.g., "7", "14") not the enumeration index
        out_stem = out_dir / str(orig_key)

        # Report progress (idx is 1-based after skip neutral)
        if progress_callback:
            progress_callback(idx, total_expressions - 1, orig_key)

        result = _generate_expression_with_safety_recovery(
            api_key,
            image_b64,
            idx,
            orig_key,
            desc,
            edge_cleanup_tolerance=edge_cleanup_tolerance,
            edge_cleanup_passes=edge_cleanup_passes,
            for_interactive_review=for_interactive_review,
            bg_removal_mode=bg_removal_mode,
            archetype_label=archetype_label,
        )

        if result:
            if for_interactive_review:
                original_bytes, rembg_bytes = result
                final_path = save_image_bytes_as_png(rembg_bytes, out_stem)
                generated_paths.append(final_path)
                cleanup_data.append((original_bytes, rembg_bytes))
            else:
                final_path = save_image_bytes_as_png(result, out_stem)
                generated_paths.append(final_path)
            generated_keys.append(orig_key)
            print(
                f"  [Expr] Saved {pose_dir.name}/{outfit_name} "
                f"expression '{orig_key}' -> {final_path}"
            )
        else:
            # Expression was skipped (already logged by helper)
            failed_keys.append((orig_key, desc))
            print(
                f"  [Expr] FAILED {pose_dir.name}/{outfit_name} "
                f"expression '{orig_key}' ({desc})"
            )

    if for_interactive_review:
        return (generated_paths, cleanup_data, generated_keys, failed_keys)
    return generated_paths


def regenerate_single_expression(
    api_key: str,
    outfit_path: Path,
    out_dir: Path,
    expressions_sequence: List[Tuple[str, str]],
    expr_key: str,
    edge_cleanup_tolerance: Optional[int] = None,
    edge_cleanup_passes: Optional[int] = None,
    bg_removal_mode: str = "rembg",
    archetype_label: str = "",
) -> Path:
    """
    Regenerate a single expression image for one outfit.

    expr_key is the expression key (e.g., "0", "1", "7", "14") which is also
    the filename stem.

    AI background removal is automatically applied.

    Args:
        api_key: Gemini API key.
        outfit_path: Path to outfit image.
        out_dir: Directory to save expression.
        expressions_sequence: List of expression definitions.
        expr_key: Key of expression to regenerate (e.g., "0", "7", "14").
        edge_cleanup_tolerance: Custom tolerance for edge cleanup (uses default if None).
        edge_cleanup_passes: Custom passes for edge cleanup (uses default if None).

    Returns:
        Path to regenerated expression image with transparent background.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Neutral 0 is always just the outfit itself; no need to call Gemini
    if expr_key == "0":
        outfit_img = Image.open(outfit_path).convert("RGBA")
        neutral_stem = out_dir / "0"
        neutral_path = save_img_as_png(outfit_img, neutral_stem)
        print(f"  [Expr] Regenerated neutral expression 0 -> {neutral_path}")
        return neutral_path

    # Find the expression description by key
    desc = None
    for key, description in expressions_sequence:
        if key == expr_key:
            desc = description
            break

    if desc is None:
        raise ValueError(f"Expression key '{expr_key}' not found in expressions_sequence.")

    image_b64 = load_image_as_base64(outfit_path)
    out_stem = out_dir / str(expr_key)

    img_bytes = _generate_expression_with_safety_recovery(
        api_key,
        image_b64,
        int(expr_key) if expr_key.isdigit() else 0,  # For logging/internal use
        expr_key,
        desc,
        edge_cleanup_tolerance=edge_cleanup_tolerance,
        edge_cleanup_passes=edge_cleanup_passes,
        bg_removal_mode=bg_removal_mode,
        archetype_label=archetype_label,
    )

    if img_bytes:
        final_path = save_image_bytes_as_png(img_bytes, out_stem)
        print(
            f"  [Expr] Regenerated expression '{expr_key}' "
            f"for '{outfit_path.stem}' -> {final_path}"
        )
        return final_path
    else:
        # All recovery attempts failed - raise error for user-initiated regeneration
        raise GeminiSafetyError(
            f"Expression '{expr_key}' could not be generated - all recovery attempts failed"
        )


def generate_and_review_expressions_for_pose(
    api_key: str,
    char_dir: Path,
    pose_dir: Path,
    pose_label: str,
    expressions_sequence: List[Tuple[str, str]],
    cleanup_settings: Optional[Dict[Path, Tuple[int, int]]] = None,
    bg_removal_modes: Optional[Dict[Path, str]] = None,
    archetype_label: str = "",
) -> None:
    """
    For a given pose directory (e.g., 'a'), iterate each outfit and:

      - Generate expression set (once per outfit).
      - Show review window.
      - Allow:
          * Accept (keep all as-is),
          * Regenerate all expressions for that outfit,
          * Regenerate a single expression via buttons under each image,
          * Cancel the whole pipeline.

    AI background removal is automatically applied.

    Args:
        api_key: Gemini API key.
        char_dir: Character directory.
        pose_dir: Pose directory.
        pose_label: Pose label for display.
        expressions_sequence: List of expression definitions.
        cleanup_settings: Optional dict mapping outfit path to (tolerance, passes) tuple.
            If provided, the settings are used for edge cleanup on generated expressions.
    """
    outfits_dir = pose_dir / "outfits"
    faces_root = pose_dir / "faces"
    outfits_dir.mkdir(parents=True, exist_ok=True)
    faces_root.mkdir(parents=True, exist_ok=True)

    for outfit_path in sorted(outfits_dir.iterdir()):
        if not outfit_path.is_file():
            continue
        if outfit_path.suffix.lower() not in (".png", ".webp"):
            continue

        outfit_name = outfit_path.stem

        # Get cleanup settings for this outfit (if provided)
        outfit_tolerance = None
        outfit_passes = None
        if cleanup_settings and outfit_path in cleanup_settings:
            outfit_tolerance, outfit_passes = cleanup_settings[outfit_path]
            print(f"  [INFO] Using cleanup settings for {outfit_name}: tolerance={outfit_tolerance}, passes={outfit_passes}")

        # Get background removal mode for this outfit
        outfit_mode = bg_removal_modes.get(outfit_path, "rembg") if bg_removal_modes else "rembg"
        if outfit_mode == "manual":
            print(f"  [INFO] Using manual background removal mode for {outfit_name}")

        # Determine the folder where the expression images for this outfit live
        if outfit_name.lower() == "base":
            out_dir = faces_root / "face"
        else:
            out_dir = faces_root / outfit_name

        # First, build the full expression set once (with cleanup_data for manual BG removal)
        result = generate_expressions_for_single_outfit_once(
            api_key,
            pose_dir,
            outfit_path,
            faces_root,
            expressions_sequence=expressions_sequence,
            edge_cleanup_tolerance=outfit_tolerance,
            edge_cleanup_passes=outfit_passes,
            for_interactive_review=True,
            bg_removal_mode=outfit_mode,
            archetype_label=archetype_label,
        )
        expr_paths_initial, expr_cleanup_data, _gen_keys, _fail_keys = result

        # Build mapping from path to cleanup_data index
        path_to_cleanup_idx: Dict[Path, int] = {p: i for i, p in enumerate(expr_paths_initial)}

        while True:
            # Collect current expression images from disk, sorted by index
            expr_paths: List[Path] = []
            for p in sorted(out_dir.iterdir(), key=lambda q: q.stem):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in (".png", ".webp"):
                    continue
                expr_paths.append(p)

            # Ensure numeric ordering (0, 1, 2, ...)
            expr_paths.sort(key=lambda q: int(q.stem))

            infos = [
                (
                    p,
                    f"Pose {pose_label} – {outfit_name} – expression {p.stem} "
                    f"({expressions_sequence[int(p.stem)][0] if int(p.stem) < len(expressions_sequence) else '?'})",
                )
                for p in expr_paths
            ]

            # Build cleanup_data list matching current expr_paths order
            review_cleanup_data: List[Tuple[bytes, bytes]] = []
            for p in expr_paths:
                cleanup_idx = path_to_cleanup_idx.get(p)
                if cleanup_idx is not None and cleanup_idx < len(expr_cleanup_data):
                    review_cleanup_data.append(expr_cleanup_data[cleanup_idx])
                else:
                    # Fallback: use current file bytes for both
                    fallback_bytes = p.read_bytes()
                    review_cleanup_data.append((fallback_bytes, fallback_bytes))

            # Buttons under each expression based on outfit mode
            if outfit_mode == "rembg":
                per_buttons: List[List[Tuple[str, str]]] = [
                    [("Regen expression", "regen_expr"), ("Cleanup BG", "edit_bg")]
                    for _ in expr_paths
                ]
            else:
                per_buttons: List[List[Tuple[str, str]]] = [
                    [("Regen expression", "regen_expr"), ("Manual BG removal", "use_original_manual")]
                    for _ in expr_paths
                ]

            decision = review_images_for_step(
                infos,
                f"Review Expressions for Pose {pose_label} – {outfit_name}",
                (
                    "These expressions are generated for this single pose/outfit.\n"
                    "Accept them, regenerate all, regenerate a single expression, or cancel."
                ),
                per_item_buttons=per_buttons,
                show_global_regenerate=True,
                compact_mode=True,
                show_background_preview=True,
                # No cleanup_data = no sliders (cleanup settings decided at outfit stage)
            )

            choice = decision.get("choice")

            if choice == "accept":
                # Save final bytes with any cleanup settings
                final_bytes_list = decision.get("final_bytes")
                if final_bytes_list:
                    for i, path in enumerate(expr_paths):
                        if i < len(final_bytes_list):
                            path.write_bytes(final_bytes_list[i])
                break
            if choice == "cancel":
                sys.exit(0)

            if choice == "regenerate_all":
                # Wipe and rebuild the whole expression set for this outfit
                result = generate_expressions_for_single_outfit_once(
                    api_key,
                    pose_dir,
                    outfit_path,
                    faces_root,
                    expressions_sequence=expressions_sequence,
                    edge_cleanup_tolerance=outfit_tolerance,
                    edge_cleanup_passes=outfit_passes,
                    for_interactive_review=True,
                    bg_removal_mode=outfit_mode,
                    archetype_label=archetype_label,
                )
                expr_paths_initial, expr_cleanup_data, _gen_keys, _fail_keys = result
                path_to_cleanup_idx = {p: i for i, p in enumerate(expr_paths_initial)}
                continue

            if choice == "per_item":
                idx_obj = decision.get("index")
                action = decision.get("action")
                if idx_obj is None:
                    continue
                idx = int(idx_obj)
                if idx < 0 or idx >= len(expr_paths):
                    continue

                # Handle edit background action
                if action == "edit_bg":
                    expr_path = expr_paths[idx]
                    # Launch click-to-remove tool for manual background editing
                    click_to_remove_background(expr_path, threshold=30)
                    # Image is updated in-place if user accepted; refresh UI
                    continue

                # Handle regenerate action (with automatic BG removal)
                if action == "regen_expr":
                    # Get the expression key from the file stem (e.g., "7" from "7.png")
                    expr_key = expr_paths[idx].stem

                    # Verify the key exists in expressions_sequence
                    key_exists = any(key == expr_key for key, _ in expressions_sequence)
                    if not key_exists:
                        continue

                    regenerate_single_expression(
                        api_key,
                        outfit_path,
                        out_dir,
                        expressions_sequence,
                        expr_key,
                        edge_cleanup_tolerance=outfit_tolerance,
                        edge_cleanup_passes=outfit_passes,
                        bg_removal_mode=outfit_mode,
                        archetype_label=archetype_label,
                    )
                    # Loop to show the updated images
                    continue

                # Handle manual BG removal using saved original bytes (no Gemini call)
                if action == "use_original_manual":
                    expr_path = expr_paths[idx]
                    cleanup_idx = path_to_cleanup_idx.get(expr_path)
                    if cleanup_idx is not None and cleanup_idx < len(expr_cleanup_data):
                        original_bytes, rembg_bytes = expr_cleanup_data[cleanup_idx]
                        # Save original bytes (with black BG) to file for manual editing
                        expr_path.write_bytes(original_bytes)
                        # Open manual removal UI
                        accepted = click_to_remove_background(expr_path, threshold=30)
                        if accepted:
                            # Read the manually edited result and update cleanup_data
                            new_bytes = expr_path.read_bytes()
                            expr_cleanup_data[cleanup_idx] = (original_bytes, new_bytes)
                            print(f"  Applied manual BG removal: {expr_path}")
                        else:
                            # User cancelled - restore rembg version
                            expr_path.write_bytes(rembg_bytes)
                    continue


def generate_initial_character_from_prompt(
    api_key: str,
    concept: str,
    archetype_label: str,
    output_root: Optional[Path] = None,
    out_stem: Optional[Path] = None,
    gender_style: Optional[str] = None,
    hair_length: str = "",
) -> Path:
    """
    Use Gemini + reference sprites to generate a base character image
    from a text concept.

    Output path (if out_stem not provided):
        <output_root>/_prompt_sources/<slug>.png

    Args:
        api_key: Gemini API key.
        concept: User's character concept description.
        archetype_label: Character archetype.
        output_root: Root output directory (used if out_stem not provided).
        out_stem: Direct output path stem (without extension).
        gender_style: Optional gender style override ("f" or "m").

    Returns:
        Path to generated character image.
    """
    from ..api.prompt_builders import archetype_to_gender_style

    # Use provided gender_style or derive from archetype
    if not gender_style:
        gender_style = archetype_to_gender_style(archetype_label)

    refs = get_reference_images_for_archetype(archetype_label)
    if refs:
        print(f"[INFO] Using {len(refs)} reference sprite(s) for archetype '{archetype_label}'.")
    else:
        print(
            f"[WARN] No reference sprites found for archetype '{archetype_label}'. "
            "Gemini will rely on the text prompt alone."
        )

    # Use black background for clean AI removal (consistent with outfits)
    full_prompt = build_prompt_for_idea(concept, archetype_label, gender_style, background_color="solid black (#000000)", hair_length=hair_length)
    print("[Gemini] Generating new character from text prompt...")
    img_bytes = call_gemini_text_or_refs(api_key, full_prompt, refs)

    # Determine output path
    if out_stem is None:
        if output_root is None:
            raise ValueError("Either out_stem or output_root must be provided")
        rand_token = hex(random.getrandbits(32))[2:]
        slug = f"{archetype_label.replace(' ', '_')}_{rand_token}"
        prompt_src_dir = output_root / "_prompt_sources"
        prompt_src_dir.mkdir(parents=True, exist_ok=True)
        out_stem = prompt_src_dir / slug
    else:
        # Ensure parent directory exists
        out_stem.parent.mkdir(parents=True, exist_ok=True)

    final_path = save_image_bytes_as_png(img_bytes, out_stem)

    print(f"[INFO] Saved prompt-generated source sprite to: {final_path}")
    return final_path
