"""
Review windows for image approval and regeneration.

Provides UI for reviewing generated images with options to accept,
regenerate, or perform per-item actions.
"""

import sys
import tkinter as tk
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk, ImageDraw

from ..config import DATA_DIR
from ..api.gemini_client import cleanup_edge_halos, REMBG_EDGE_CLEANUP_TOLERANCE, REMBG_EDGE_CLEANUP_PASSES
from .tk_common import (
    BG_COLOR,
    TITLE_FONT,
    INSTRUCTION_FONT,
    WINDOW_MARGIN,
    center_and_clamp,
    wraplength_for,
    get_primary_screen,
)

# Path to game backgrounds for preview
BACKGROUNDS_DIR = DATA_DIR / "reference_sprites" / "backgrounds"


def _get_background_options() -> List[Tuple[str, Optional[Path]]]:
    """
    Get list of available background options for preview.

    Returns:
        List of (display_name, path_or_none) tuples.
        Black and white are built-in (path=None).
    """
    options = [
        ("Black", None),
        ("White", None),
    ]

    # Add game backgrounds from reference_sprites/backgrounds/
    if BACKGROUNDS_DIR.exists():
        for bg_path in sorted(BACKGROUNDS_DIR.iterdir()):
            if bg_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                options.append((bg_path.stem.replace("_", " ").title(), bg_path))

    return options


def _create_preview_with_background(
    img_bytes: bytes,
    bg_option: str,
    bg_path: Optional[Path],
    target_size: Tuple[int, int],
) -> Image.Image:
    """
    Create a preview image composited over the specified background.

    Args:
        img_bytes: PNG image bytes with transparency.
        bg_option: Background option name ("Black", "White", or custom).
        bg_path: Path to background image, or None for solid colors.
        target_size: Target (width, height) for the preview.

    Returns:
        Composited PIL Image ready for display.
    """
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")

    # Create background
    if bg_option == "Black":
        background = Image.new("RGBA", img.size, (0, 0, 0, 255))
    elif bg_option == "White":
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    elif bg_path and bg_path.exists():
        background = Image.open(bg_path).convert("RGBA")
        # Center-crop background to match character dimensions (preserve aspect ratio)
        bg_w, bg_h = background.size
        char_w, char_h = img.size
        # Scale up if background is smaller than character (maintain aspect ratio)
        if bg_w < char_w or bg_h < char_h:
            scale = max(char_w / bg_w, char_h / bg_h)
            background = background.resize(
                (int(bg_w * scale), int(bg_h * scale)),
                Image.LANCZOS
            )
            bg_w, bg_h = background.size
        # Center-crop to character dimensions
        left = (bg_w - char_w) // 2
        top = (bg_h - char_h) // 2
        background = background.crop((left, top, left + char_w, top + char_h))
    else:
        background = Image.new("RGBA", img.size, (0, 0, 0, 255))

    # Composite character over background
    composite = Image.alpha_composite(background, img)

    # Resize for display
    composite.thumbnail(target_size, Image.LANCZOS)
    return composite


def review_images_for_step(
    image_infos: List[Tuple[Path, str]],
    title_text: str,
    body_text: str,
    *,
    per_item_buttons: Optional[List[List[Tuple[str, str]]]] = None,
    show_global_regenerate: bool = True,
    cleanup_data: Optional[List[Tuple[bytes, bytes]]] = None,
    compact_mode: Optional[bool] = None,
    show_background_preview: bool = False,
    restore_state: Optional[Dict[str, object]] = None,
    bg_removal_modes: Optional[Dict[int, str]] = None,
) -> Dict[str, Optional[object]]:
    """
    Show a scrollable strip of images and return a decision dictionary.

    Creates a horizontal scrolling window displaying multiple images with
    captions and optional per-item action buttons.

    Args:
        image_infos: List of (image_path, caption) pairs.
        title_text: Window title text.
        body_text: Instructional text.
        per_item_buttons: Optional list (same length as image_infos) where each entry
            is a list of (button_label, action_code) tuples. For each image card,
            those buttons are rendered under the caption. Pressing one closes the
            window and returns a decision with:
                {"choice": "per_item", "index": idx, "action": action_code}
        show_global_regenerate: If True, show a global "Regenerate" button at the
            bottom that behaves like the old "regenerate all" behavior and returns:
                {"choice": "regenerate_all", ...}
        cleanup_data: Optional list of (original_bytes, rembg_bytes) tuples for each
            outfit. When provided, adds per-outfit edge cleanup controls (tolerance
            slider, depth slider, apply button) under each image card.
        compact_mode: If True, use compact layout (bigger images, smaller UI).
            Defaults to True when cleanup_data is provided, False otherwise.
        show_background_preview: If True, show background dropdown for preview even
            when cleanup_data is not provided. Images are loaded from disk for compositing.
        restore_state: Optional dict containing state to restore from a previous iteration:
            - cleanup_settings: list of (tolerance, depth) tuples
            - current_bytes: list of current edited bytes
            - background_selection: currently selected background name

    Returns:
        A dict with at least:
            choice: "accept", "cancel", "regenerate_all", or "per_item"
            index: index of the image (only for per_item)
            action: action_code string (only for per_item)
            final_bytes: Optional list of final bytes for each outfit (when cleanup_data provided)
            cleanup_settings: Optional list of (tolerance, depth) tuples for each outfit
    """
    decision: Dict[str, Optional[object]] = {
        "choice": "cancel",
        "index": None,
        "action": None,
        "final_bytes": None,
        "cleanup_settings": None,
        "current_bytes": None,        # Current edited bytes for state persistence
        "background_selection": None,  # Currently selected background for state persistence
    }

    # Track current state if cleanup_data provided (check early for layout decisions)
    has_cleanup = cleanup_data is not None and len(cleanup_data) == len(image_infos)

    # Background preview is available with cleanup_data OR when explicitly requested
    has_bg_preview = has_cleanup or show_background_preview

    # Determine if we should use compact layout (bigger images, less UI chrome)
    # Default to compact mode when cleanup_data is provided, but allow override
    use_compact = compact_mode if compact_mode is not None else has_cleanup

    root = tk.Tk()
    root.configure(bg=BG_COLOR)
    root.title("Review Step")

    sw, sh, *_ = get_primary_screen(root)
    wrap_len = wraplength_for(int(sw * 0.9))

    # Current bytes for each image (from cleanup_data or loaded from disk for bg preview)
    current_bytes: List[bytes] = []
    if has_cleanup:
        for orig_bytes, rembg_bytes in cleanup_data:
            current_bytes.append(rembg_bytes)
    elif show_background_preview:
        # Load from disk for background preview only (no cleanup controls)
        for img_path, _ in image_infos:
            try:
                current_bytes.append(img_path.read_bytes())
            except Exception:
                current_bytes.append(b"")

    # Background selection variables
    bg_options = _get_background_options()
    bg_var = tk.StringVar(value="White")
    bg_paths: Dict[str, Optional[Path]] = {name: path for name, path in bg_options}

    # Restore previous state if provided
    if restore_state:
        # Restore background selection
        if restore_state.get("background_selection"):
            bg_var.set(restore_state["background_selection"])
        # Restore current_bytes (edited bytes from previous iteration)
        if restore_state.get("current_bytes") and has_cleanup:
            restored_bytes = restore_state["current_bytes"]
            for i in range(min(len(current_bytes), len(restored_bytes))):
                current_bytes[i] = restored_bytes[i]

    # Compact header for compact mode, normal header otherwise
    if use_compact:
        # Row 0: Compact header with title and background dropdown inline
        header_frame = tk.Frame(root, bg=BG_COLOR)
        header_frame.grid(row=0, column=0, padx=10, pady=(4, 2), sticky="we")

        tk.Label(
            header_frame,
            text=title_text,
            font=TITLE_FONT,
            bg=BG_COLOR,
            fg="black",
        ).pack(side=tk.LEFT, padx=(0, 30))

        tk.Label(
            header_frame,
            text="Preview BG:",
            font=("", 9),
            bg=BG_COLOR,
            fg="gray30",
        ).pack(side=tk.LEFT, padx=(0, 4))

        bg_dropdown = tk.OptionMenu(header_frame, bg_var, *[name for name, _ in bg_options])
        bg_dropdown.config(width=12)
        bg_dropdown.pack(side=tk.LEFT)

        row_offset = 1
    else:
        # Normal mode - full instructions
        tk.Label(
            root,
            text=title_text,
            font=TITLE_FONT,
            bg=BG_COLOR,
            fg="black",
            wraplength=wrap_len,
            justify="center",
        ).grid(row=0, column=0, padx=10, pady=(10, 4), sticky="we")

        tk.Label(
            root,
            text=body_text,
            font=INSTRUCTION_FONT,
            bg=BG_COLOR,
            fg="black",
            wraplength=wrap_len,
            justify="center",
        ).grid(row=1, column=0, padx=10, pady=(0, 6), sticky="we")

        row_offset = 2

    # Scrollable canvas setup - maximize vertical space for compact mode
    canvas_w = int(sw * 0.94) - 2 * WINDOW_MARGIN
    canvas_h = int(sh * 0.84) if use_compact else int(sh * 0.60)

    outer = tk.Frame(root, bg=BG_COLOR)
    outer.grid(row=row_offset, column=0, padx=6, pady=4, sticky="nsew")
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_columnconfigure(0, weight=1)

    # Use BG_COLOR for canvas instead of black for cleaner look
    canvas = tk.Canvas(
        outer,
        width=canvas_w,
        height=canvas_h,
        bg=BG_COLOR,
        highlightthickness=0,
    )
    canvas.grid(row=0, column=0, sticky="nsew")

    h_scroll = tk.Scrollbar(outer, orient=tk.HORIZONTAL, command=canvas.xview)
    h_scroll.grid(row=1, column=0, sticky="we")
    canvas.configure(xscrollcommand=h_scroll.set)

    inner = tk.Frame(canvas, bg=BG_COLOR)
    canvas.create_window((0, 0), window=inner, anchor="nw")

    thumb_refs: List[ImageTk.PhotoImage] = []
    img_labels: List[tk.Label] = []  # Keep references to update images
    # For compact mode, use most of the canvas height for images (leave room for controls)
    # When cleanup controls are shown, leave more room; otherwise maximize image size
    if use_compact:
        max_thumb_height = int(canvas_h * 0.82) if has_cleanup else int(canvas_h * 0.90)
    else:
        max_thumb_height = min(600, canvas_h - 40)

    # Per-outfit cleanup state
    tolerance_vars: List[tk.IntVar] = []
    depth_vars: List[tk.IntVar] = []

    # Normalize per_item_buttons length if provided
    if per_item_buttons is not None:
        if len(per_item_buttons) < len(image_infos):
            per_item_buttons = per_item_buttons + [
                [] for _ in range(len(image_infos) - len(per_item_buttons))
            ]
    else:
        per_item_buttons = [[] for _ in image_infos]

    def make_item_handler(idx: int, action_code: str):
        """Create a button handler for per-item actions."""
        def _handler():
            decision["choice"] = "per_item"
            decision["index"] = idx
            decision["action"] = action_code
            if has_cleanup:
                decision["final_bytes"] = current_bytes.copy()
                # Capture cleanup settings for each outfit
                settings = []
                for i in range(len(tolerance_vars)):
                    settings.append((tolerance_vars[i].get(), depth_vars[i].get()))
                decision["cleanup_settings"] = settings
                # Capture state for restoration on next iteration
                decision["current_bytes"] = current_bytes.copy()
                decision["background_selection"] = bg_var.get()
            root.destroy()
        return _handler

    def update_preview(idx: int):
        """Update the preview image for image at index."""
        if not has_bg_preview or idx >= len(current_bytes) or not current_bytes[idx]:
            return

        bg_name = bg_var.get()
        bg_path = bg_paths.get(bg_name)
        preview_img = _create_preview_with_background(
            current_bytes[idx],
            bg_name,
            bg_path,
            (max_thumb_height, max_thumb_height),
        )
        tki = ImageTk.PhotoImage(preview_img)

        # Update the reference and label
        thumb_refs[idx] = tki
        img_labels[idx].configure(image=tki)

    def update_all_previews(*args):
        """Update all preview images when background changes."""
        for idx in range(len(image_infos)):
            update_preview(idx)

    def make_apply_cleanup_handler(idx: int):
        """Create a handler for the Apply Cleanup button."""
        def _handler():
            if not has_cleanup or idx >= len(cleanup_data):
                return

            original_bytes, rembg_bytes = cleanup_data[idx]
            tolerance = tolerance_vars[idx].get()
            depth = depth_vars[idx].get()

            # Apply cleanup with user's settings
            cleaned_bytes = cleanup_edge_halos(
                original_bytes=original_bytes,
                result_bytes=rembg_bytes,
                tolerance=tolerance,
                passes=depth,
            )

            # Update current state
            current_bytes[idx] = cleaned_bytes

            # Update preview
            update_preview(idx)

        return _handler

    # Bind background dropdown change (for cleanup mode or bg preview mode)
    if has_bg_preview:
        bg_var.trace_add("write", update_all_previews)

    # Create image cards
    for col_index, (img_path, caption) in enumerate(image_infos):
        try:
            if has_bg_preview and col_index < len(current_bytes) and current_bytes[col_index]:
                # Use current_bytes for preview (from cleanup or loaded from disk)
                img = Image.open(BytesIO(current_bytes[col_index])).convert("RGBA")
            else:
                img = Image.open(img_path).convert("RGBA")
        except Exception as e:
            print(f"[WARN] Failed to load {img_path}: {e}")
            continue

        # Create preview with background if bg preview mode (cleanup or explicit)
        if has_bg_preview and col_index < len(current_bytes) and current_bytes[col_index]:
            bg_name = bg_var.get()
            bg_path = bg_paths.get(bg_name)
            preview_img = _create_preview_with_background(
                current_bytes[col_index],
                bg_name,
                bg_path,
                (max_thumb_height, max_thumb_height),
            )
            tki = ImageTk.PhotoImage(preview_img)
        else:
            w, h = img.size
            scale = min(max_thumb_height / max(1, h), 1.0)
            tw, th = max(1, int(w * scale)), max(1, int(h * scale))
            thumb = img.resize((tw, th), Image.LANCZOS)
            tki = ImageTk.PhotoImage(thumb)

        thumb_refs.append(tki)

        card = tk.Frame(inner, bg=BG_COLOR)
        card.grid(row=0, column=col_index, padx=10, pady=6)

        # Image display
        img_label = tk.Label(card, image=tki, bg=BG_COLOR)
        img_label.pack()
        img_labels.append(img_label)

        # Caption (compact in compact mode)
        caption_font = ("", 9) if use_compact else INSTRUCTION_FONT
        tk.Label(
            card,
            text=caption,
            font=caption_font,
            bg=BG_COLOR,
            fg="black",
            wraplength=max_thumb_height + 40,
            justify="center",
        ).pack(pady=(1, 1))

        # Optional per-item buttons under each image
        btn_cfgs = per_item_buttons[col_index]
        if btn_cfgs:
            btn_row = tk.Frame(card, bg=BG_COLOR)
            btn_row.pack(pady=(0, 1))
            for label, action_code in btn_cfgs:
                # Button width based on mode - ensure enough space for labels
                btn_width = 22 if use_compact else 24
                tk.Button(
                    btn_row,
                    text=label,
                    width=btn_width,
                    command=make_item_handler(col_index, action_code),
                ).pack(side=tk.TOP, pady=1)

        # Per-outfit cleanup controls (if cleanup_data provided)
        if has_cleanup and col_index < len(cleanup_data):
            # Check if this outfit is in rembg mode or manual mode
            outfit_mode = bg_removal_modes.get(col_index, "rembg") if bg_removal_modes else "rembg"

            cleanup_frame = tk.Frame(card, bg=BG_COLOR)
            cleanup_frame.pack(pady=(2, 0), fill=tk.X)

            if outfit_mode == "rembg":
                # Show sliders for rembg mode
                # Tolerance slider (compact)
                tol_frame = tk.Frame(cleanup_frame, bg=BG_COLOR)
                tol_frame.pack(fill=tk.X, pady=(0, 0))

                tk.Label(tol_frame, text="Tol:", font=("", 8), bg=BG_COLOR, width=4, anchor="e").pack(side=tk.LEFT)

                # Use restored tolerance value if available, otherwise default
                restored_tol = REMBG_EDGE_CLEANUP_TOLERANCE
                if restore_state and restore_state.get("cleanup_settings"):
                    settings = restore_state["cleanup_settings"]
                    if col_index < len(settings):
                        restored_tol = settings[col_index][0]
                tol_var = tk.IntVar(value=restored_tol)
                tolerance_vars.append(tol_var)

                tol_slider = tk.Scale(
                    tol_frame,
                    from_=0,
                    to=150,
                    orient=tk.HORIZONTAL,
                    variable=tol_var,
                    length=140,
                    showvalue=True,
                    font=("", 7),
                    bg=BG_COLOR,
                    highlightthickness=0,
                )
                tol_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

                # Depth slider (compact)
                depth_frame = tk.Frame(cleanup_frame, bg=BG_COLOR)
                depth_frame.pack(fill=tk.X, pady=(0, 0))

                tk.Label(depth_frame, text="Dep:", font=("", 8), bg=BG_COLOR, width=4, anchor="e").pack(side=tk.LEFT)

                # Use restored depth value if available, otherwise default
                restored_depth = REMBG_EDGE_CLEANUP_PASSES
                if restore_state and restore_state.get("cleanup_settings"):
                    settings = restore_state["cleanup_settings"]
                    if col_index < len(settings):
                        restored_depth = settings[col_index][1]
                depth_var = tk.IntVar(value=restored_depth)
                depth_vars.append(depth_var)

                depth_slider = tk.Scale(
                    depth_frame,
                    from_=0,
                    to=50,
                    orient=tk.HORIZONTAL,
                    variable=depth_var,
                    length=140,
                    showvalue=True,
                    font=("", 7),
                    bg=BG_COLOR,
                    highlightthickness=0,
                )
                depth_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

                # Apply button (compact)
                tk.Button(
                    cleanup_frame,
                    text="Apply",
                    width=10,
                    command=make_apply_cleanup_handler(col_index),
                ).pack(pady=(2, 4))
            else:
                # Manual mode: show label instead of sliders
                tk.Label(
                    cleanup_frame,
                    text="Manual mode - use button to edit",
                    font=("", 8),
                    bg=BG_COLOR,
                    fg="gray50",
                ).pack(pady=(4, 8))
                # Still need placeholder vars for consistent indexing
                tolerance_vars.append(tk.IntVar(value=0))
                depth_vars.append(tk.IntVar(value=0))

    def _update_scrollregion(_event=None) -> None:
        """Update scrollable region when content changes."""
        inner.update_idletasks()
        bbox = canvas.bbox("all")
        if bbox:
            canvas.configure(scrollregion=bbox)

    inner.bind("<Configure>", _update_scrollregion)
    _update_scrollregion()

    # Action button handlers
    def accept() -> None:
        decision["choice"] = "accept"
        if has_cleanup:
            decision["final_bytes"] = current_bytes.copy()
            # Capture cleanup settings (tolerance, depth) for each outfit
            settings = []
            for i in range(len(tolerance_vars)):
                settings.append((tolerance_vars[i].get(), depth_vars[i].get()))
            decision["cleanup_settings"] = settings
        root.destroy()

    def regenerate_all() -> None:
        decision["choice"] = "regenerate_all"
        root.destroy()

    def cancel():
        decision["choice"] = "cancel"
        try:
            root.destroy()
        except Exception:
            pass

    # Bottom button row (compact in compact mode)
    btns = tk.Frame(root, bg=BG_COLOR)
    btn_pady = (2, 4) if use_compact else (6, 10)
    btns.grid(row=row_offset + 1, column=0, pady=btn_pady)

    btn_width = 14 if use_compact else 20
    tk.Button(btns, text="Accept All", width=btn_width, command=accept).pack(side=tk.LEFT, padx=8)

    if show_global_regenerate:
        tk.Button(btns, text="Regenerate All", width=btn_width, command=regenerate_all).pack(
            side=tk.LEFT, padx=8
        )

    tk.Button(btns, text="Cancel", width=btn_width, command=cancel).pack(
        side=tk.LEFT, padx=8
    )

    center_and_clamp(root)
    root.mainloop()
    return decision


def review_initial_base_pose(
    base_pose_path: Path,
    has_been_regenerated: bool = False,
) -> Tuple[str, bool, str]:
    """
    Review normalized base pose and decide whether to accept, regenerate, or cancel.

    Also allows user to choose whether to treat this base pose as an 'Original' outfit.
    Provides a text box for additional regeneration instructions and a reset button.

    Args:
        base_pose_path: Path to the base pose image to review.
        has_been_regenerated: If True, show "Reset to Original" button.

    Returns:
        (choice, use_as_outfit, additional_text) where:
            choice: "accept", "regenerate", "reset", or "cancel"
            use_as_outfit: Whether to keep this as an Original outfit
            additional_text: Optional text for regeneration instructions
    """
    root = tk.Tk()
    root.configure(bg=BG_COLOR)
    root.title("Review Normalized Base Pose")

    sw, sh, *_ = get_primary_screen(root)
    wrap_len = wraplength_for(int(sw * 0.9))

    instructions = (
        "Review the normalized base pose. Accept, regenerate, or cancel.\n"
        "Check the box below to also use this as an 'Original' outfit."
    )

    tk.Label(
        root,
        text=instructions,
        font=INSTRUCTION_FONT,
        bg=BG_COLOR,
        wraplength=wrap_len,
        justify="center",
    ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="we")

    # Image preview frame
    preview_frame = tk.Frame(root, bg=BG_COLOR)
    preview_frame.grid(row=1, column=0, padx=10, pady=(4, 4))

    max_size = int(sh * 0.65)  # 65% of screen height (reduced to make room for text box)

    # Load and display image directly (no background compositing)
    img = Image.open(base_pose_path).convert("RGBA")

    # Scale for display
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    img_tk = ImageTk.PhotoImage(img)

    img_label = tk.Label(preview_frame, image=img_tk, bg=BG_COLOR)
    img_label.pack()

    # Keep reference to prevent garbage collection
    root._preview_img = img_tk  # type: ignore[attr-defined]

    # Checkbox for using as outfit
    use_as_outfit_var = tk.IntVar(value=1)  # Default: keep as Base

    chk_frame = tk.Frame(root, bg=BG_COLOR)
    chk_frame.grid(row=2, column=0, padx=10, pady=(4, 4), sticky="w")

    tk.Checkbutton(
        chk_frame,
        text="Use this normalized base as an 'Original' outfit",
        variable=use_as_outfit_var,
        bg=BG_COLOR,
        anchor="w",
    ).pack(anchor="w")

    # Text entry for additional regeneration instructions
    text_frame = tk.Frame(root, bg=BG_COLOR)
    text_frame.grid(row=3, column=0, padx=10, pady=(4, 4), sticky="we")

    tk.Label(
        text_frame,
        text="Additional instructions for regeneration (optional):",
        font=("", 9),
        bg=BG_COLOR,
    ).pack(anchor="w")

    regen_text = tk.Text(text_frame, height=2, width=60, font=("", 9))
    regen_text.pack(pady=(2, 0), fill=tk.X)

    decision = {"choice": "accept", "use_as_outfit": True, "additional_text": ""}

    # Button handlers
    def on_accept():
        decision["choice"] = "accept"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        decision["additional_text"] = regen_text.get("1.0", tk.END).strip()
        root.destroy()

    def on_regenerate():
        decision["choice"] = "regenerate"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        decision["additional_text"] = regen_text.get("1.0", tk.END).strip()
        root.destroy()

    def on_reset():
        decision["choice"] = "reset"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        decision["additional_text"] = ""  # Clear text on reset
        root.destroy()

    def on_cancel():
        decision["choice"] = "cancel"
        try:
            root.destroy()
        except Exception:
            pass

    # Bottom buttons
    btns = tk.Frame(root, bg=BG_COLOR)
    btns.grid(row=4, column=0, pady=(6, 10))

    tk.Button(btns, text="Accept", width=16, command=on_accept).pack(
        side=tk.LEFT, padx=10
    )
    tk.Button(btns, text="Regenerate", width=16, command=on_regenerate).pack(
        side=tk.LEFT, padx=10
    )

    # Only show Reset button if we've regenerated at least once
    if has_been_regenerated:
        tk.Button(btns, text="Reset to Original", width=16, command=on_reset).pack(
            side=tk.LEFT, padx=10
        )

    tk.Button(btns, text="Cancel and Exit", width=16, command=on_cancel).pack(
        side=tk.LEFT, padx=10
    )

    center_and_clamp(root)
    root.mainloop()

    return decision["choice"], decision["use_as_outfit"], decision["additional_text"]


def click_to_remove_background(image_path: Path, threshold: int = 30) -> bool:
    """
    Interactive UI for manually removing black background by clicking.

    Shows the image and allows user to click on black areas to remove them.
    Each click performs a flood-fill removal of similar pixels.
    Updates display after each click.
    Provides "Restart" button to undo all changes and "Accept" button to save.

    Args:
        image_path: Path to the image file to process.
        threshold: Color similarity threshold for flood fill (default 30).

    Returns:
        True if user accepted changes, False if cancelled.
    """
    # Load original image
    original_img = Image.open(image_path).convert("RGBA")
    working_img = original_img.copy()

    # Undo history system
    history_stack: List[Image.Image] = []  # Stack of previous image states
    MAX_HISTORY_SIZE = 25  # Memory limit: ~25MB for typical sprites

    # Use Toplevel instead of Tk to avoid multiple Tk instance issues with PhotoImage
    # Get the existing Tk root if available, otherwise create one
    existing_root = tk._default_root
    if existing_root is None:
        root = tk.Tk()
    else:
        root = tk.Toplevel(existing_root)
        root.transient(existing_root)  # Keep on top of parent
        root.grab_set()  # Make modal
    root.configure(bg=BG_COLOR)
    root.title("Click to Remove Background")

    sw, sh, *_ = get_primary_screen(root)

    # Calculate display size — large but leave room for slider + buttons + chrome
    # Overhead: title bar ~32, slider ~70, buttons ~45, padding ~35, taskbar ~48 ≈ 230px
    original_w, original_h = working_img.size
    max_display_w = int(sw * 0.90)
    max_display_h = int(sh * 0.75)

    scale = min(max_display_w / original_w, max_display_h / original_h, 1.0)
    display_w = max(1, int(original_w * scale))
    display_h = max(1, int(original_h * scale))

    # Visible canvas area (may be smaller than image if screen is tiny)
    canvas_vis_w = min(display_w, max_display_w)
    canvas_vis_h = min(display_h, max_display_h)
    needs_h_scroll = display_w > canvas_vis_w
    needs_v_scroll = display_h > canvas_vis_h

    # Center all grid content
    root.grid_columnconfigure(0, weight=1)

    # Canvas with conditional scrollbars
    canvas_frame = tk.Frame(root, bg=BG_COLOR)
    canvas_frame.grid(row=0, column=0, padx=10, pady=(6, 4))

    if needs_v_scroll:
        v_scroll = tk.Scrollbar(canvas_frame, orient="vertical")
        v_scroll.pack(side="right", fill="y")

    if needs_h_scroll:
        h_scroll = tk.Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

    canvas = tk.Canvas(
        canvas_frame,
        width=canvas_vis_w,
        height=canvas_vis_h,
        bg="white",  # White background so transparent areas are visible
        highlightthickness=0,
        cursor="none",  # Hide default cursor
        scrollregion=(0, 0, display_w, display_h),
    )
    canvas.pack(fill="both", expand=True)

    if needs_v_scroll:
        canvas.configure(yscrollcommand=v_scroll.set)
        v_scroll.configure(command=canvas.yview)
    if needs_h_scroll:
        canvas.configure(xscrollcommand=h_scroll.set)
        h_scroll.configure(command=canvas.xview)

    # Mousewheel scrolling when scrollbars are active
    if needs_v_scroll:
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    # Threshold slider
    slider_frame = tk.Frame(root, bg=BG_COLOR)
    slider_frame.grid(row=1, column=0, padx=10, pady=(4, 2), sticky="we")

    threshold_label = tk.Label(
        slider_frame,
        text=f"Threshold: {threshold}",
        font=INSTRUCTION_FONT,
        bg=BG_COLOR
    )
    threshold_label.pack(side=tk.TOP, pady=(0, 2))

    threshold_var = tk.IntVar(value=threshold)
    threshold_slider = tk.Scale(
        slider_frame,
        from_=0,
        to=100,
        resolution=1,
        orient=tk.HORIZONTAL,
        variable=threshold_var,
        length=int(sw * 0.7),
        showvalue=True,
        command=lambda v: threshold_label.config(text=f"Threshold: {v}")
    )
    threshold_slider.pack(side=tk.TOP, fill=tk.X, padx=20)

    # Store references
    img_refs = {"current_tk": None, "crosshair_h": None, "crosshair_v": None}
    btn_refs = {"undo": None}

    def update_display():
        """Update canvas with current working image."""
        display_img = working_img.resize((display_w, display_h), Image.LANCZOS)
        # Explicitly set master to ensure PhotoImage is created in the correct Tk context
        img_refs["current_tk"] = ImageTk.PhotoImage(display_img, master=root)
        canvas.delete("image")
        canvas.create_image(0, 0, anchor="nw", image=img_refs["current_tk"], tags="image")

    def save_to_history():
        """Save current working image state to history stack."""
        nonlocal history_stack
        history_stack.append(working_img.copy())
        if len(history_stack) > MAX_HISTORY_SIZE:
            history_stack.pop(0)  # Remove oldest entry

    def on_undo():
        """Undo the last click by restoring previous image state."""
        nonlocal working_img, history_stack

        if not history_stack:
            return

        working_img = history_stack.pop()
        update_display()

        if not history_stack:
            btn_refs["undo"].config(state=tk.DISABLED)

    def flood_fill_remove(x: int, y: int):
        """Remove pixels similar to the clicked pixel using flood fill."""
        nonlocal working_img

        # Convert display coordinates to image coordinates
        img_x = int(x / scale)
        img_y = int(y / scale)

        # Clamp to image bounds
        img_x = max(0, min(img_x, working_img.width - 1))
        img_y = max(0, min(img_y, working_img.height - 1))

        # Get the target color
        target_pixel = working_img.getpixel((img_x, img_y))
        target_r, target_g, target_b = target_pixel[0], target_pixel[1], target_pixel[2]

        # Don't remove if already transparent (don't save to history either)
        if len(target_pixel) == 4 and target_pixel[3] < 10:
            return

        # Save current state to history before making changes
        save_to_history()

        # Enable undo button since we now have history
        if btn_refs["undo"]:
            btn_refs["undo"].config(state=tk.NORMAL)

        # Get current threshold from slider
        current_threshold = threshold_var.get()

        # Flood fill to find similar pixels
        # Alpha-aware: also removes semi-transparent pixels that are likely
        # leftover background from alpha matting
        pixels = working_img.load()
        width, height = working_img.size
        target_a = target_pixel[3] if len(target_pixel) == 4 else 255
        visited = set()
        queue = [(img_x, img_y)]

        while queue:
            px, py = queue.pop(0)

            if (px, py) in visited:
                continue
            if px < 0 or px >= width or py < 0 or py >= height:
                continue

            visited.add((px, py))

            current = pixels[px, py]
            cr, cg, cb = current[0], current[1], current[2]
            ca = current[3] if len(current) == 4 else 255

            # Skip already fully transparent
            if ca == 0:
                continue

            # Semi-transparent pixels (alpha < 128) are likely leftover
            # background from alpha matting — always remove and flood through
            is_semi_transparent = ca < 128

            # Check if pixel is similar to target using current threshold
            color_match = (abs(cr - target_r) <= current_threshold and
                           abs(cg - target_g) <= current_threshold and
                           abs(cb - target_b) <= current_threshold)

            if color_match or is_semi_transparent:
                # Make transparent
                pixels[px, py] = (cr, cg, cb, 0)

                # Add neighbors to queue
                queue.append((px + 1, py))
                queue.append((px - 1, py))
                queue.append((px, py + 1))
                queue.append((px, py - 1))

        update_display()

    def update_crosshair(event):
        """Update crosshair cursor position."""
        # Convert to canvas coordinates (accounts for scroll offset)
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)

        # Remove old crosshair
        if img_refs["crosshair_h"]:
            canvas.delete(img_refs["crosshair_h"])
        if img_refs["crosshair_v"]:
            canvas.delete(img_refs["crosshair_v"])

        # Draw new crosshair centered on mouse
        img_refs["crosshair_h"] = canvas.create_line(
            0, cy, display_w, cy,
            fill="red", width=1, tags="crosshair"
        )
        img_refs["crosshair_v"] = canvas.create_line(
            cx, 0, cx, display_h,
            fill="red", width=1, tags="crosshair"
        )

    def on_click(event):
        """Handle canvas click."""
        # Convert to canvas coordinates (accounts for scroll offset)
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)
        flood_fill_remove(cx, cy)

    # Track whether user accepted changes
    accepted = {"value": False}

    def on_restart():
        """Reset to original image."""
        nonlocal working_img, history_stack
        working_img = original_img.copy()
        history_stack.clear()  # Clear all history
        btn_refs["undo"].config(state=tk.DISABLED)  # Disable undo button
        update_display()

    def on_accept():
        """Save and close."""
        working_img.save(image_path, format="PNG", compress_level=0, optimize=False)
        print(f"[INFO] Saved manually cleaned background: {image_path}")
        accepted["value"] = True
        root.destroy()

    def on_cancel():
        """Close without saving."""
        try:
            root.destroy()
        except Exception:
            pass

    # Bind events
    canvas.bind("<Button-1>", on_click)
    canvas.bind("<Motion>", update_crosshair)

    # Initial display
    update_display()

    # Buttons
    btns = tk.Frame(root, bg=BG_COLOR)
    btns.grid(row=2, column=0, pady=(4, 8))

    btn_refs["undo"] = tk.Button(btns, text="Undo Last Click", width=16, command=on_undo, state=tk.DISABLED)
    btn_refs["undo"].pack(side=tk.LEFT, padx=10)

    tk.Button(btns, text="Restart", width=16, command=on_restart).pack(side=tk.LEFT, padx=10)
    tk.Button(btns, text="Accept", width=16, command=on_accept).pack(side=tk.LEFT, padx=10)
    tk.Button(btns, text="Cancel", width=16, command=on_cancel).pack(side=tk.LEFT, padx=10)

    center_and_clamp(root)

    # Use wait_window() for Toplevel to properly block until window closes
    # mainloop() doesn't block for Toplevel when a mainloop is already running
    root.wait_window()

    return accepted["value"]


def review_initial_base_pose_dual(
    auto_path: Path,
    manual_path: Path,
) -> Tuple[str, bool, str]:
    """
    Review both automatic and manual normalized base poses side-by-side.

    Displays both versions simultaneously and allows the user to:
    - Regenerate either version individually
    - Select which version to use for the rest of the pipeline
    - Toggle whether to use the normalized base as an 'Original' outfit

    Args:
        auto_path: Path to automatic mode (magenta background) image.
        manual_path: Path to manual mode (black background) image.

    Returns:
        (choice, use_as_outfit, selected_mode) where:
            choice: "accept", "regenerate_auto", "regenerate_manual", or "cancel"
            use_as_outfit: Whether to keep this as an Original outfit
            selected_mode: "automatic" or "manual" (which version was selected)
    """
    root = tk.Tk()
    root.configure(bg=BG_COLOR)
    root.title("Review Normalized Base Pose Options")

    sw, sh, *_ = get_primary_screen(root)
    wrap_len = wraplength_for(int(sw * 0.9))

    # Title/Instructions
    tk.Label(
        root,
        text=(
            "These are the normalized base poses Gemini created in both modes.\n\n"
            "LEFT: Automatic Mode (magenta background - auto background removal)\n"
            "RIGHT: Manual Mode (black background - click-to-remove later)\n\n"
            "Choose which version to use, or regenerate either one."
        ),
        font=TITLE_FONT,
        bg=BG_COLOR,
        fg="black",
        wraplength=wrap_len,
        justify="center",
    ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="we")

    # Image preview frame
    preview_frame = tk.Frame(root, bg=BG_COLOR)
    preview_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(4, 4))

    max_size = int(min(sw, sh) * 0.35)

    # Load and display automatic mode image
    auto_img = Image.open(auto_path).convert("RGBA")
    auto_img.thumbnail((max_size, max_size), Image.LANCZOS)
    auto_tk = ImageTk.PhotoImage(auto_img)

    auto_frame = tk.Frame(preview_frame, bg=BG_COLOR)
    auto_frame.pack(side=tk.LEFT, padx=20)
    tk.Label(auto_frame, image=auto_tk, bg=BG_COLOR).pack()
    tk.Label(
        auto_frame,
        text="Automatic Mode\n(Magenta Background)",
        font=INSTRUCTION_FONT,
        bg=BG_COLOR,
        fg="black",
    ).pack(pady=(4, 4))

    # Load and display manual mode image
    manual_img = Image.open(manual_path).convert("RGBA")
    manual_img.thumbnail((max_size, max_size), Image.LANCZOS)
    manual_tk = ImageTk.PhotoImage(manual_img)

    manual_frame = tk.Frame(preview_frame, bg=BG_COLOR)
    manual_frame.pack(side=tk.LEFT, padx=20)
    tk.Label(manual_frame, image=manual_tk, bg=BG_COLOR).pack()
    tk.Label(
        manual_frame,
        text="Manual Mode\n(Black Background)",
        font=INSTRUCTION_FONT,
        bg=BG_COLOR,
        fg="black",
    ).pack(pady=(4, 4))

    # Keep references to prevent garbage collection
    root._auto_img = auto_tk  # type: ignore[attr-defined]
    root._manual_img = manual_tk  # type: ignore[attr-defined]

    decision = {"choice": "cancel", "use_as_outfit": True, "selected_mode": "automatic"}

    # Checkbox for using as outfit
    use_as_outfit_var = tk.IntVar(value=1)
    chk_frame = tk.Frame(root, bg=BG_COLOR)
    chk_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(4, 4))
    tk.Checkbutton(
        chk_frame,
        text="Use this normalized base as an 'Original' outfit",
        variable=use_as_outfit_var,
        bg=BG_COLOR,
        anchor="w",
    ).pack(anchor="w")

    # Per-image regenerate buttons
    regen_btns_frame = tk.Frame(root, bg=BG_COLOR)
    regen_btns_frame.grid(row=3, column=0, columnspan=2, pady=(4, 4))

    def on_regen_auto():
        decision["choice"] = "regenerate_auto"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        root.destroy()

    def on_regen_manual():
        decision["choice"] = "regenerate_manual"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        root.destroy()

    tk.Button(
        regen_btns_frame,
        text="Regenerate Automatic",
        width=20,
        command=on_regen_auto,
    ).pack(side=tk.LEFT, padx=40)
    tk.Button(
        regen_btns_frame,
        text="Regenerate Manual",
        width=20,
        command=on_regen_manual,
    ).pack(side=tk.LEFT, padx=40)

    # Selection buttons
    def on_use_automatic():
        decision["choice"] = "accept"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        decision["selected_mode"] = "automatic"
        root.destroy()

    def on_use_manual():
        decision["choice"] = "accept"
        decision["use_as_outfit"] = bool(use_as_outfit_var.get())
        decision["selected_mode"] = "manual"
        root.destroy()

    def on_cancel():
        decision["choice"] = "cancel"
        try:
            root.destroy()
        except Exception:
            pass

    btns = tk.Frame(root, bg=BG_COLOR)
    btns.grid(row=4, column=0, columnspan=2, pady=(6, 10))

    tk.Button(btns, text="Use Automatic", width=16, command=on_use_automatic).pack(
        side=tk.LEFT, padx=10
    )
    tk.Button(btns, text="Use Manual", width=16, command=on_use_manual).pack(
        side=tk.LEFT, padx=10
    )
    tk.Button(btns, text="Cancel and Exit", width=16, command=on_cancel).pack(
        side=tk.LEFT, padx=10
    )

    center_and_clamp(root)
    root.mainloop()

    return decision["choice"], decision["use_as_outfit"], decision["selected_mode"]
