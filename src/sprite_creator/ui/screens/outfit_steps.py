"""
Outfit wizard steps (Steps 8-9).

These steps handle outfit generation and review:
- Step 8: Outfit Review with per-outfit regeneration and cleanup
- Step 9: Manual BG Removal Modal (embedded in step 8)
"""

import copy
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from ...config import (
    BG_COLOR,
    BG_SECONDARY,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    ERROR_TEXT,
    WARNING_TEXT,
    CAUTION_TEXT,
    OVERLAY_BG,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    DATA_DIR,
)
from ...api.gemini_client import (
    REMBG_EDGE_CLEANUP_TOLERANCE,
    REMBG_EDGE_CLEANUP_PASSES,
)
from ..tk_common import (
    create_primary_button,
    create_secondary_button,
    create_danger_button,
    show_error_dialog,
)
from .base import WizardStep, WizardState
from ...logging_utils import log_info, log_error, log_generation_start, log_generation_complete


class CustomRegenModal:
    """
    Modal dialog for entering a custom outfit description for regeneration.
    """

    def __init__(self, parent: tk.Tk, outfit_name: str, on_generate: callable):
        """
        Initialize the custom regen modal.

        Args:
            parent: Parent window
            outfit_name: Name of the outfit being regenerated (for title)
            on_generate: Callback with signature (prompt: str) -> None
        """
        self._parent = parent
        self._on_generate = on_generate
        self._result_prompt: Optional[str] = None

        # Create modal window
        self.window = tk.Toplevel(parent)
        self.window.title(f"Custom {outfit_name.capitalize()} Outfit")
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Configure window
        self.window.configure(bg=BG_COLOR)
        self.window.geometry("450x340")  # Taller to ensure buttons are visible
        self.window.resizable(False, False)

        self._build_ui(outfit_name)

        # Center on parent
        self.window.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.window.geometry(f"+{x}+{y}")

        # Make modal
        self.window.lift()
        self.window.focus_force()
        self.window.grab_set()

        # Focus text area
        self._text_area.focus_set()

    def _build_ui(self, outfit_name: str) -> None:
        """Build the modal UI."""
        main_frame = tk.Frame(self.window, bg=BG_COLOR, padx=20, pady=16)
        main_frame.pack(fill="both", expand=True)

        # Title
        tk.Label(
            main_frame,
            text=f"Describe the {outfit_name} outfit:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 8))

        # Instructions
        tk.Label(
            main_frame,
            text="Be specific about colors, style, and details.\n"
                 "Example: \"a red sundress with white polka dots and thin straps\"",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        # Text area with scrollbar
        text_frame = tk.Frame(main_frame, bg=BG_COLOR)
        text_frame.pack(fill="both", expand=True, pady=(0, 12))

        self._text_area = tk.Text(
            text_frame,
            height=5,
            width=50,
            font=BODY_FONT,
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            wrap="word",
            padx=8,
            pady=8,
        )
        self._text_area.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame, command=self._text_area.yview)
        scrollbar.pack(side="right", fill="y")
        self._text_area.configure(yscrollcommand=scrollbar.set)

        # Status label (for errors)
        self._status_var = tk.StringVar()
        self._status_label = tk.Label(
            main_frame,
            textvariable=self._status_var,
            bg=BG_COLOR,
            fg=ERROR_TEXT,
            font=SMALL_FONT,
        )
        self._status_label.pack(anchor="w", pady=(0, 8))

        # Buttons
        button_frame = tk.Frame(main_frame, bg=BG_COLOR)
        button_frame.pack(fill="x")

        self._generate_btn = create_primary_button(
            button_frame,
            "Generate",
            self._on_generate_click,
            width=12,
        )
        self._generate_btn.pack(side="right", padx=(8, 0))

        create_secondary_button(
            button_frame,
            "Cancel",
            self._on_cancel,
            width=10,
        ).pack(side="right")

        # Bind Enter (Ctrl+Enter to submit since Enter adds newline)
        self.window.bind("<Control-Return>", lambda e: self._on_generate_click())
        self.window.bind("<Escape>", lambda e: self._on_cancel())

    def _on_generate_click(self) -> None:
        """Handle Generate button click."""
        prompt = self._text_area.get("1.0", "end").strip()

        if not prompt:
            self._status_var.set("Please enter an outfit description.")
            return

        if len(prompt) < 5:
            self._status_var.set("Description is too short. Be more specific.")
            return

        self._result_prompt = prompt
        self._close()
        self._on_generate(prompt)

    def _on_cancel(self) -> None:
        """Handle cancel."""
        self._result_prompt = None
        self._close()

    def _close(self) -> None:
        """Close the modal."""
        self.window.grab_release()
        self.window.destroy()


class OutfitReviewStep(WizardStep):
    """
    Step 6: Outfit Review.

    Displays all generated outfits with per-outfit controls:
    - Regenerate (same prompt)
    - Regenerate (new prompt)
    - Cleanup BG (tolerance/depth sliders)
    - Switch to Manual BG removal

    Also provides global Accept/Regenerate All buttons.
    """

    STEP_ID = "outfit_review"
    STEP_TITLE = "Outfits"
    STEP_NUMBER = 6
    STEP_HELP = """Outfit Review

This step shows all generated outfits. Scroll horizontally to see them all.

IMPORTANT: You can do touch-ups on the NEXT step!
Don't worry about getting backgrounds perfect here. The Expression Review step has a "Remove BG" button for each expression, so you can fix any issues there.

Focus on:
• Approving outfits you like
• Tuning the Tolerance/Depth sliders to remove black halos around lineart and hair edges
• Making sure the sliders don't eat into clothing or body details

If there are still some leftover background spots INSIDE the character (like between hair strands or under arms), don't stress - you can clean those up with the flood-fill tool on the next step.

WHAT HAPPENS NEXT
When you click Next, you'll proceed to the Expression Review step, where expressions (facial variations) are generated for EACH outfit shown here. The Tolerance/Depth settings you set here will be used as defaults for expression background removal.

═══════════════════════════════════════════════════
TROUBLESHOOTING - WHEN TO REGENERATE
═══════════════════════════════════════════════════

REGENERATE if you see any of these issues:

• Image goes off-screen or is cropped weirdly
  The AI sometimes generates images that extend past the frame. Click "Regen Same Outfit" or "Regen New Outfit" to try again.

• Bad framing / not matching other outfits
  If one outfit looks zoomed in/out differently, or the character is positioned differently than others, regenerate to get better consistency.

• Showing feet or bottom of legs
  Your character should be cropped at mid-thigh (matching the base image). If feet are visible, regenerate.

• Arm/body pixels look "eaten" or deleted
  This is caused by the automatic background removal (rembg) being too aggressive. You have two options:
  1. Click "Regen Same Outfit" - may produce a version that rembg handles better
  2. Click "Switch to Manual BG Removal" - this keeps the original image with black background. You'll use the flood-fill tool on the next step to manually remove the background while preserving arm details.

═══════════════════════════════════════════════════

PREVIEW BACKGROUND (Top Right)
Use the dropdown to preview outfits on different backgrounds:
- Black/White: Solid colors to check edges
- Game backgrounds: If available, shows how outfits look in-game

OUTFIT CARDS
Each card shows one generated outfit with controls below.

REGENERATION BUTTONS
Regen Same Outfit: Generate a new image using the same outfit description. Useful if the pose or quality isn't right but you like the outfit concept.

Regen New Outfit: Generate with a completely different random outfit description. Use this to try a different look entirely. Only available for random outfits (not custom or ST Uniform).

Custom...: Opens a popup where you can type your own outfit description. Use this when you have a specific outfit in mind (e.g., "a blue denim jacket with a white t-shirt underneath"). Be descriptive about colors, style, and details for best results.

If your custom description triggers content filters, you'll see an error message and the current outfit will be kept - nothing is lost.

Note: Custom outfits only show "Regen Same Outfit" and "Custom..." buttons (no "Regen New Outfit" since the outfit was intentionally specified).

BACKGROUND REMOVAL (Auto Mode)
When an outfit shows the "rembg" sliders:

Tolerance (0-150): How aggressively to remove edge pixels.
- Low values (0-30): Only removes very similar colors
- High values (100+): Removes more, but may eat into the character
- Default: 50

Depth (0-50): How many cleanup passes to run.
- Low values (0-5): Light cleanup
- High values (20+): More aggressive edge cleaning
- Default: 5

Click "Apply" after adjusting sliders to see the result.

These settings carry forward to expression generation, so getting them right here saves time later.

MANUAL MODE
Click "Switch to Manual BG Removal" to use click-based removal instead. In manual mode, you click on areas to remove (flood-fill style).

Click "Switch to Auto BG Removal" to return to slider-based mode.

NAVIGATION
Use mouse wheel to scroll horizontally through outfits.

When satisfied with all outfits, click Next to proceed to expression generation."""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._canvas: Optional[tk.Canvas] = None
        self._inner_frame: Optional[tk.Frame] = None
        self._img_labels: List[tk.Label] = []
        self._thumb_refs: List[ImageTk.PhotoImage] = []
        self._current_bytes: List[bytes] = []
        self._tolerance_vars: List[tk.IntVar] = []
        self._depth_vars: List[tk.IntVar] = []
        self._bg_var: Optional[tk.StringVar] = None
        self._is_generating: bool = False
        self._original_preview_sizes: Dict[int, int] = {}  # Track original max_h per outfit
        self._card_frames: List[tk.Frame] = []  # Track card frames for per-card loading
        self._card_overlays: Dict[int, tk.Frame] = {}  # Active loading overlays
        self._regenerating_idx: Optional[int] = None  # Track which card is being regenerated

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Header row
        header = tk.Frame(parent, bg=BG_COLOR)
        header.pack(fill="x", pady=(0, 8))

        # Title
        tk.Label(
            header,
            text="Review Outfits",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(side="left")

        # Background preview dropdown
        bg_frame = tk.Frame(header, bg=BG_COLOR)
        bg_frame.pack(side="right")

        tk.Label(
            bg_frame,
            text="Preview BG:",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack(side="left", padx=(0, 4))

        self._bg_var = tk.StringVar(value="White")
        bg_options = self._get_background_options()
        bg_menu = tk.OptionMenu(bg_frame, self._bg_var, *[name for name, _ in bg_options])
        bg_menu.configure(width=12, bg=CARD_BG, fg=TEXT_COLOR)
        bg_menu.pack(side="left")
        self._bg_var.trace_add("write", lambda *_: self._update_all_previews())

        # Inline tip
        tk.Label(
            parent,
            text="💡 Tolerance/Depth settings here will apply to ALL expressions. "
                 "You can still fix individual expressions on the next step.",
            bg=BG_COLOR,
            fg=WARNING_TEXT,
            font=SMALL_FONT,
            wraplength=800,
            justify="left",
        ).pack(fill="x", pady=(0, 4))

        # Black background warning
        tk.Label(
            parent,
            text="⚠️ Black areas are the BACKGROUND — it has not been removed yet! "
                 "Use the Tolerance/Depth sliders and click Apply to remove it. "
                 "If black background remains, your character will have a large black box around them in-game.",
            bg=BG_COLOR,
            fg=CAUTION_TEXT,  # Bright yellow for visibility
            font=SMALL_FONT,
            wraplength=800,
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        # Scrollable canvas for outfit cards
        canvas_frame = tk.Frame(parent, bg=BG_COLOR)
        canvas_frame.pack(fill="both", expand=True)

        # Pack scrollbar FIRST so canvas gets proper remaining height
        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

        self._canvas = tk.Canvas(
            canvas_frame,
            bg=BG_COLOR,
            highlightthickness=0,
            xscrollcommand=h_scroll.set,
        )
        self._canvas.pack(fill="both", expand=True)
        h_scroll.configure(command=self._canvas.xview)

        self._inner_frame = tk.Frame(self._canvas, bg=BG_COLOR)
        self._canvas.create_window((0, 0), window=self._inner_frame, anchor="nw")
        self._inner_frame.bind("<Configure>", self._on_frame_configure)

        # Note: Accept All / Regenerate All buttons removed - use Next button to accept
        # Note: Status label removed to save vertical space

    def _get_background_options(self) -> List[Tuple[str, Optional[Path]]]:
        """Get available background options for preview."""
        from ...config import DATA_DIR
        options = [
            ("Black", None),
            ("White", None),
        ]
        # Add game backgrounds if available
        bg_dir = DATA_DIR / "reference_sprites" / "backgrounds"
        if bg_dir.is_dir():
            for p in sorted(bg_dir.iterdir()):
                if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    options.append((p.stem, p))
        return options

    def _on_frame_configure(self, event=None) -> None:
        """Update scroll region when content changes."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        # Bind mouse wheel for horizontal scrolling
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # Linux scroll bindings
        self._canvas.bind_all("<Button-4>", lambda e: self._canvas.xview_scroll(-1, "units"))
        self._canvas.bind_all("<Button-5>", lambda e: self._canvas.xview_scroll(1, "units"))

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel for horizontal scrolling."""
        # Don't scroll outfits when a modal (Toplevel) has focus — e.g. custom outfit popup
        try:
            widget = event.widget
            if isinstance(widget, str):
                # Tkinter sometimes passes widget path strings
                pass
            else:
                top = widget.winfo_toplevel()
                if isinstance(top, tk.Toplevel):
                    return
        except Exception:
            pass
        # Windows: event.delta is typically 120 or -120
        self._canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_enter(self) -> None:
        """Generate outfits when step becomes active.

        Smart regeneration: detects if outfit selections changed since last
        generation and regenerates only when needed.
        """
        # Check if we already have valid outfits on disk
        has_valid_outfits = (
            self.state.outfits_generated and
            self.state.outfit_paths and
            all(p.exists() for p in self.state.outfit_paths)
        )

        if has_valid_outfits:
            # Check if outfit selections changed since last generation
            current_keys = []
            if self.state.use_base_as_outfit:
                current_keys.append("base")
            current_keys.extend(self.state.selected_outfits)

            if current_keys != self.state.generated_outfit_keys:
                # Selections changed - need full regeneration
                self.state.outfits_generated = False
                self._start_outfit_generation()
                return

            # Check if base image changed since last generation
            base_changed = False
            if self.state.base_pose_path != self.state.last_base_pose_path:
                base_changed = True
            elif self.state.base_pose_path and self.state.base_pose_path.exists():
                current_mtime = os.path.getmtime(self.state.base_pose_path)
                if self.state.last_base_pose_mtime is None or current_mtime != self.state.last_base_pose_mtime:
                    base_changed = True

            if base_changed:
                self.state.outfits_generated = False
                self.state.base_pose_normalized_post_crop = False
                self._start_outfit_generation()
                return

            # Check if outfit prompt config changed (e.g. random→custom, or custom text edited)
            if self.state.outfit_prompt_config != self.state.last_outfit_prompt_config:
                self.state.outfits_generated = False
                self._start_outfit_generation()
                return

            # No changes - reuse existing outfits
            self._load_existing_outfits()
            return

        # No outfits yet, generate them
        self._start_outfit_generation()

    def _get_step_index(self) -> int:
        """Get this step's index in the wizard."""
        for i, step in enumerate(self.wizard._steps):
            if step is self:
                return i
        return -1

    def _start_outfit_generation(self) -> None:
        """Start generating all outfits in background."""
        if self._is_generating:
            return

        self._is_generating = True
        self.show_loading("Generating outfits...")

        def update_progress(current: int, total: int, outfit_name: str):
            """Update loading message with current progress."""
            self.schedule_callback(lambda: self.show_loading(
                f"Generating outfit {current}/{total}: {outfit_name.capitalize()}..."
            ))

        def generate():
            try:
                paths, cleanup_data, used_prompts = self._do_outfit_generation(update_progress)
                self.schedule_callback(lambda p=paths, c=cleanup_data, u=used_prompts: self._on_generation_complete(p, c, u))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg))

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _do_outfit_generation(self, progress_callback=None) -> Tuple[List[Path], List[Tuple[bytes, bytes]], Dict[str, str]]:
        """Perform outfit generation."""
        from ...processing import generate_outfits_once, get_unique_folder_name
        from ...api import build_outfit_prompts_with_config
        from ..api_setup import ensure_api_key

        log_info(f"OUTFIT_GEN: {len(self.state.selected_outfits)} outfits, base={self.state.use_base_as_outfit}")
        log_generation_start("outfits", count=len(self.state.selected_outfits))

        if not self.state.api_key:
            self.state.api_key = ensure_api_key()

        # Create character folder if it doesn't exist
        if not self.state.character_folder:
            if not self.state.output_root:
                raise ValueError("Output folder not set. Please select an output folder before generating.")
            self.state.character_folder = self.state.output_root / get_unique_folder_name(
                self.state.output_root, self.state.display_name
            )
        self.state.character_folder.mkdir(parents=True, exist_ok=True)

        # Copy base pose to character folder as base.png if not already there
        base_dest = self.state.character_folder / "base.png"
        if self.state.base_pose_path and self.state.base_pose_path.exists() and not base_dest.exists():
            import shutil
            shutil.copy2(self.state.base_pose_path, base_dest)
            # Update base_pose_path to point to the new location
            self.state.base_pose_path = base_dest

        # Re-normalize cropped image through Gemini so its dimensions match
        # generated output (~1MP). Without this, the Base outfit would use the
        # raw crop dimensions while all other outfits use Gemini's output size.
        if (
            self.state.base_pose_path
            and self.state.base_pose_path.exists()
            and self.state.cropped_image_path is not None
            and not self.state.base_pose_normalized_post_crop
        ):
            if progress_callback:
                progress_callback(0, len(self.state.selected_outfits), "Normalizing base image")

            from io import BytesIO
            from ...api.gemini_client import call_gemini_image_edit, load_image_as_base64
            from ...api.prompt_builders import build_normalize_existing_character_prompt

            image_b64 = load_image_as_base64(self.state.base_pose_path)
            prompt = build_normalize_existing_character_prompt()
            result_bytes = call_gemini_image_edit(
                api_key=self.state.api_key,
                prompt=prompt,
                image_b64=image_b64,
                skip_background_removal=True,  # Keep black BG, don't run rembg
            )

            # Overwrite base_pose_path with the normalized version
            normalized_img = Image.open(BytesIO(result_bytes)).convert("RGBA")
            normalized_img.save(self.state.base_pose_path, format="PNG",
                                compress_level=0, optimize=False)
            self.state.base_pose_normalized_post_crop = True

        # Build outfit prompts with configuration (uses Gemini text API for random mode)
        # Note: For underwear, this returns a placeholder; actual prompt determined at generation
        outfit_descriptions = build_outfit_prompts_with_config(
            self.state.api_key,
            self.state.archetype_label,
            self.state.gender_style,
            self.state.selected_outfits,
            self.state.outfit_prompt_config,
        )

        # Create outfits directory
        # In add-to-existing mode, use next available pose letter instead of "a"
        if self.state.is_adding_to_existing:
            pose_letter = self.state.next_pose_letter or "a"
        else:
            pose_letter = "a"
        outfits_dir = self.state.character_folder / pose_letter / "outfits"
        outfits_dir.mkdir(parents=True, exist_ok=True)

        # Generate outfits using the base pose
        # Returns (paths, cleanup_data, used_prompts) where used_prompts contains
        # the actual prompts that succeeded (important for underwear tier system)
        paths, cleanup_data, used_prompts = generate_outfits_once(
            api_key=self.state.api_key,
            base_pose_path=self.state.base_pose_path,
            outfits_dir=outfits_dir,
            gender_style=self.state.gender_style,
            outfit_descriptions=outfit_descriptions,
            outfit_prompt_config=self.state.outfit_prompt_config,
            archetype_label=self.state.archetype_label,
            include_base_outfit=self.state.use_base_as_outfit,
            for_interactive_review=True,
            progress_callback=progress_callback,
        )

        return paths, cleanup_data, used_prompts

    def _on_generation_complete(self, paths: List[Path], cleanup_data: List[Tuple[bytes, bytes]], used_prompts: Dict[str, str]) -> None:
        """Handle outfit generation completion."""
        self._is_generating = False
        self.hide_loading()

        log_generation_complete("outfits", True, f"Generated {len(paths)} outfits")

        self.state.outfit_paths = paths
        self.state.outfit_cleanup_data = cleanup_data
        self.state.outfits_generated = True  # Mark as generated to prevent regeneration on back

        # Store the actual prompts that succeeded (important for underwear tier system)
        self.state.outfit_prompts = used_prompts

        # Track which outfit keys actually succeeded (for expression step)
        # This handles cases where outfits like underwear may be skipped due to safety filters
        generated_keys = []
        if self.state.use_base_as_outfit:
            generated_keys.append("base")
        generated_keys.extend(used_prompts.keys())
        self.state.generated_outfit_keys = generated_keys

        # Detect skipped outfits
        expected_keys = list(self.state.selected_outfits)
        actually_generated = set(used_prompts.keys())
        skipped = [k for k in expected_keys if k not in actually_generated]
        log_info(f"OUTFIT_GEN: Done. Keys={generated_keys}, Skipped={skipped}")

        # Notify user about skipped outfits
        if skipped:
            names = ", ".join(k.replace("_", " ").title() for k in skipped)
            messagebox.showinfo(
                "Some Outfits Skipped",
                f"Could not generate: {names}\n\n"
                f"These were blocked by content filters. You can go back to Options "
                f"and try a different outfit type, or use 'Custom...' on another outfit."
            )

        # Save snapshots for change detection on re-entry
        self.state.last_outfit_prompt_config = copy.deepcopy(self.state.outfit_prompt_config)
        self.state.last_base_pose_path = self.state.base_pose_path
        self.state.last_base_pose_mtime = (
            os.path.getmtime(self.state.base_pose_path)
            if self.state.base_pose_path and self.state.base_pose_path.exists()
            else None
        )

        # Mark all generated outfits as needing expression regeneration
        # so the expression step knows to regenerate after full outfit regen
        for key in generated_keys:
            if key != "base":
                self.state.outfits_needing_expression_regen.add(key)

        # Initialize current bytes from rembg results
        self._current_bytes = [rembg_bytes for _, rembg_bytes in cleanup_data]
        self.state.current_outfit_bytes = self._current_bytes.copy()

        # Build outfit cards
        self._build_outfit_cards()

    def _on_generation_error(self, error: str) -> None:
        """Handle generation error."""
        self._is_generating = False
        log_generation_complete("outfits", False, error)
        # Hide per-card loading if regenerating single outfit, otherwise hide full-screen loading
        if self._regenerating_idx is not None:
            self._hide_card_loading(self._regenerating_idx)
            self._regenerating_idx = None
        else:
            self.hide_loading()
        show_error_dialog(self._canvas, "Generation Error", f"Failed to generate outfits:\n\n{error}")

    def _load_existing_outfits(self) -> None:
        """Load existing outfits from state."""
        # Load current bytes
        if self.state.current_outfit_bytes:
            self._current_bytes = self.state.current_outfit_bytes.copy()
        else:
            self._current_bytes = []
            for path in self.state.outfit_paths:
                if path.exists():
                    self._current_bytes.append(path.read_bytes())
                else:
                    self._current_bytes.append(b"")

        self._build_outfit_cards()

    def _build_outfit_cards(self) -> None:
        """Build UI cards for each outfit."""
        # Clear existing
        for widget in self._inner_frame.winfo_children():
            widget.destroy()
        self._img_labels.clear()
        self._thumb_refs.clear()
        self._tolerance_vars.clear()
        self._depth_vars.clear()
        self._original_preview_sizes.clear()
        self._card_frames.clear()
        self._card_overlays.clear()

        # Size images based on WINDOW height (reliable — set by apply_window_size)
        # instead of canvas height (unreliable — depends on multi-level canvas window
        # chain propagation that doesn't fully resolve even after update()).
        #
        # The image must fit inside the card WITH controls, and the card must
        # fit inside the visible area.  Overhead breakdown:
        #   Wizard chrome:  header ~50 + footer ~45          =  95
        #   Content padding: content_frame pady 20×2          =  40
        #   Step header:     title ~45 + tip ~25 + warning ~40 = 110
        #   Card chrome:     h-scrollbar ~20 + card pad ~15   =  35
        #   Card controls:   caption + regen + sliders + btn  = 140
        #                                              Total ≈ 420
        self._canvas.winfo_toplevel().update()
        win_h = self._canvas.winfo_toplevel().winfo_height()
        max_thumb_h = max(int((win_h - 420) * 0.90), 250)

        # Get outfit names (only those that succeeded generation)
        outfit_names = self.state.generated_outfit_keys.copy() if self.state.generated_outfit_keys else []

        # Build cards
        for idx, (path, name) in enumerate(zip(self.state.outfit_paths, outfit_names)):
            card = self._build_single_outfit_card(idx, path, name, max_thumb_h)
            card.grid(row=0, column=idx, padx=10, pady=6)
            self._card_frames.append(card)

        # Tell the canvas how tall the cards actually are so the wizard-level
        # scrollbar can detect overflow (cards include image + controls below).
        # Then explicitly notify the wizard — changing the canvas requested height
        # updates _content_frame.winfo_reqheight() but doesn't trigger a <Configure>
        # event (actual size is controlled by the canvas window item, not pack).
        self._inner_frame.update_idletasks()
        self._canvas.configure(height=self._inner_frame.winfo_reqheight())
        if hasattr(self.wizard, '_on_content_configure'):
            self.wizard._on_content_configure()

    def _build_single_outfit_card(self, idx: int, path: Path, name: str, max_h: int) -> tk.Frame:
        """Build a single outfit card with image and controls."""
        card = tk.Frame(self._inner_frame, bg=CARD_BG, padx=6, pady=4)

        # Load and display image
        img_bytes = self._current_bytes[idx] if idx < len(self._current_bytes) else path.read_bytes()
        preview = self._create_preview_image(img_bytes, max_h)
        self._thumb_refs.append(preview)
        self._original_preview_sizes[idx] = max_h  # Store for consistent updates

        img_label = tk.Label(card, image=preview, bg=CARD_BG)
        img_label.pack()
        self._img_labels.append(img_label)

        # Caption
        tk.Label(
            card,
            text=name.capitalize(),
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(pady=(1, 1))

        # === GROUP 1: Regenerate buttons (horizontal, not for base) ===
        if name.lower() != "base":
            # Check if this outfit uses standard_uniform mode (only one option, no "new outfit" needed)
            outfit_config = self.state.outfit_prompt_config.get(name.lower(), {})
            is_standard_uniform = outfit_config.get("use_standard_uniform", False)
            is_underwear = name.lower() == "underwear"
            # Custom = user-provided prompt from Options wizard or from "Custom..." button
            is_custom = (
                (not outfit_config.get("use_random", True) and not is_standard_uniform)
                or name.lower() in self.state.custom_outfit_prompts
            )

            regen_frame = tk.Frame(card, bg=CARD_BG)
            regen_frame.pack(pady=(1, 1))

            # Don't show "Regen Same Outfit" for underwear - the generation is too unreliable
            # and uses a tier system that won't produce the same result anyway
            if not is_underwear:
                create_secondary_button(
                    regen_frame, "Regen Same Outfit",
                    lambda i=idx: self._regenerate_outfit(i, same_prompt=True),
                    width=14
                ).pack(side="left", padx=(0, 4))

            # Only show "Regen New Outfit" for random outfits (not standard_uniform or custom)
            if not is_standard_uniform and not is_custom:
                create_secondary_button(
                    regen_frame, "Regen New Outfit",
                    lambda i=idx: self._regenerate_outfit(i, same_prompt=False),
                    width=14
                ).pack(side="left", padx=(0, 4))

            # Custom Regen button - always show for non-base outfits
            create_secondary_button(
                regen_frame, "Custom...",
                lambda i=idx, n=name: self._open_custom_regen_modal(i, n),
                width=8
            ).pack(side="left")

        # BG mode and cleanup controls
        mode = self.state.outfit_bg_modes.get(idx, "rembg")

        if mode == "rembg":
            # === GROUP 2: Cleanup sliders + Apply (all horizontal) ===
            cleanup_frame = tk.Frame(card, bg=CARD_BG)
            cleanup_frame.pack(pady=(1, 1))

            # Tolerance label and slider
            tk.Label(cleanup_frame, text="Tolerance:", font=("", 8), bg=CARD_BG, fg=TEXT_SECONDARY).pack(side="left")

            restored_tol = REMBG_EDGE_CLEANUP_TOLERANCE
            if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
                restored_tol = self.state.outfit_cleanup_settings[idx][0]
            tol_var = tk.IntVar(value=restored_tol)
            self._tolerance_vars.append(tol_var)

            tk.Scale(
                cleanup_frame, from_=0, to=150, orient="horizontal",
                variable=tol_var, length=280, showvalue=True,
                font=("", 7), bg=CARD_BG, highlightthickness=0
            ).pack(side="left")

            # Depth label and slider
            tk.Label(cleanup_frame, text="Depth:", font=("", 8), bg=CARD_BG, fg=TEXT_SECONDARY).pack(side="left", padx=(4, 0))

            restored_depth = REMBG_EDGE_CLEANUP_PASSES
            if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
                restored_depth = self.state.outfit_cleanup_settings[idx][1]
            depth_var = tk.IntVar(value=restored_depth)
            self._depth_vars.append(depth_var)

            tk.Scale(
                cleanup_frame, from_=0, to=50, orient="horizontal",
                variable=depth_var, length=280, showvalue=True,
                font=("", 7), bg=CARD_BG, highlightthickness=0
            ).pack(side="left")

            # Apply button
            create_secondary_button(
                cleanup_frame, "Apply",
                lambda i=idx: self._apply_cleanup(i),
                width=6
            ).pack(side="left", padx=(4, 0))

            # === GROUP 3: BG Mode Switch ===
            create_secondary_button(
                card, "Switch to Manual BG Removal",
                lambda i=idx: self._switch_to_manual(i),
                width=24
            ).pack(pady=(1, 0))
        else:
            # Manual mode - no sliders, just buttons
            tk.Label(
                card,
                text="Manual mode",
                bg=CARD_BG,
                fg=TEXT_SECONDARY,
                font=("", 8),
            ).pack(pady=(1, 0))

            # Placeholders for vars (to keep index alignment) - restore previous values to preserve settings
            restored_tol = REMBG_EDGE_CLEANUP_TOLERANCE
            restored_depth = REMBG_EDGE_CLEANUP_PASSES
            if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
                restored_tol = self.state.outfit_cleanup_settings[idx][0]
                restored_depth = self.state.outfit_cleanup_settings[idx][1]
            self._tolerance_vars.append(tk.IntVar(value=restored_tol))
            self._depth_vars.append(tk.IntVar(value=restored_depth))

            # === BG Mode Switch (no Edit button - BG removal handled in Expressions step) ===
            create_secondary_button(
                card, "Switch to Auto BG Removal",
                lambda i=idx: self._switch_to_auto(i),
                width=24
            ).pack(pady=(1, 0))

        return card

    def _create_preview_image(self, img_bytes: bytes, max_h: int) -> ImageTk.PhotoImage:
        """Create a preview image with current background."""
        try:
            img = Image.open(BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (100, 100), (128, 128, 128, 255))

        bg_name = self._bg_var.get() if self._bg_var else "White"
        bg_options = dict(self._get_background_options())
        bg_path = bg_options.get(bg_name)

        # Create background
        if bg_name == "Black":
            bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
        elif bg_name == "White":
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        elif bg_path and bg_path.exists():
            bg = Image.open(bg_path).convert("RGBA")
            # Center-bottom crop background to match character dimensions
            bg_w, bg_h = bg.size
            char_w, char_h = img.size
            # Scale up if background is smaller than character
            if bg_w < char_w or bg_h < char_h:
                scale = max(char_w / bg_w, char_h / bg_h)
                bg = bg.resize((int(bg_w * scale), int(bg_h * scale)), Image.LANCZOS)
                bg_w, bg_h = bg.size
            # Center-bottom crop to character dimensions
            left = (bg_w - char_w) // 2
            top = bg_h - char_h  # Bottom-aligned instead of center
            bg = bg.crop((left, top, left + char_w, top + char_h))
        else:
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))

        # Composite — constrain by height only; width can be whatever the
        # aspect ratio needs since cards scroll horizontally.
        composite = Image.alpha_composite(bg, img)
        if composite.height > max_h:
            ratio = max_h / composite.height
            new_w = int(composite.width * ratio)
            composite = composite.resize((new_w, max_h), Image.LANCZOS)

        return ImageTk.PhotoImage(composite)

    def _update_preview(self, idx: int) -> None:
        """Update preview for a single outfit."""
        if idx >= len(self._current_bytes) or idx >= len(self._img_labels):
            return

        # Use stored size to prevent shrinking
        max_h = self._original_preview_sizes.get(idx, 450)
        preview = self._create_preview_image(self._current_bytes[idx], max_h)
        self._thumb_refs[idx] = preview
        self._img_labels[idx].configure(image=preview)

    def _update_all_previews(self) -> None:
        """Update all previews (e.g., when background changes)."""
        for idx in range(len(self._img_labels)):
            self._update_preview(idx)

    def _apply_cleanup(self, idx: int) -> None:
        """Apply cleanup with current slider settings."""
        if idx >= len(self.state.outfit_cleanup_data):
            return

        from ...api.gemini_client import cleanup_edge_halos

        original_bytes, rembg_bytes = self.state.outfit_cleanup_data[idx]
        tol = self._tolerance_vars[idx].get()
        depth = self._depth_vars[idx].get()

        cleaned = cleanup_edge_halos(original_bytes, rembg_bytes, tolerance=tol, passes=depth)
        self._current_bytes[idx] = cleaned
        self.state.current_outfit_bytes = self._current_bytes.copy()

        self._update_preview(idx)

    def _save_cleanup_settings(self) -> None:
        """Save current slider values to state (preserves settings when switching modes)."""
        if not self._tolerance_vars or not self._depth_vars:
            return
        settings = []
        for idx in range(len(self._tolerance_vars)):
            settings.append((self._tolerance_vars[idx].get(), self._depth_vars[idx].get()))
        self.state.outfit_cleanup_settings = settings

    def _switch_to_manual(self, idx: int) -> None:
        """Switch outfit to manual BG removal mode."""
        # Save current cleanup settings before rebuilding (preserves slider values)
        self._save_cleanup_settings()

        self.state.outfit_bg_modes[idx] = "manual"
        # Revert to original black bg bytes for manual editing
        if idx < len(self.state.outfit_cleanup_data) and self.state.outfit_cleanup_data[idx][0]:
            original_bytes, _ = self.state.outfit_cleanup_data[idx]
            self._current_bytes[idx] = original_bytes
            self.state.current_outfit_bytes = self._current_bytes.copy()
        elif idx < len(self.state.outfit_paths) and self.state.outfit_paths[idx].exists():
            # Fallback: read from file if cleanup_data is missing
            self._current_bytes[idx] = self.state.outfit_paths[idx].read_bytes()
            self.state.current_outfit_bytes = self._current_bytes.copy()
        self._build_outfit_cards()  # Rebuild to show manual UI

    def _switch_to_auto(self, idx: int) -> None:
        """Switch outfit back to auto (rembg) mode."""
        # Save current cleanup settings before rebuilding (preserves slider values)
        self._save_cleanup_settings()

        self.state.outfit_bg_modes[idx] = "rembg"
        # Reset to rembg result
        if idx < len(self.state.outfit_cleanup_data):
            _, rembg_bytes = self.state.outfit_cleanup_data[idx]
            self._current_bytes[idx] = rembg_bytes
            self.state.current_outfit_bytes = self._current_bytes.copy()
        self._build_outfit_cards()

    def _show_card_loading(self, idx: int, message: str = "Regenerating...") -> None:
        """Show a loading overlay on a specific card."""
        if idx < 0 or idx >= len(self._card_frames):
            return

        card = self._card_frames[idx]

        # Create semi-transparent overlay frame
        overlay = tk.Frame(card, bg=OVERLAY_BG)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Loading message
        tk.Label(
            overlay,
            text=message,
            bg=OVERLAY_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            wraplength=200,
        ).place(relx=0.5, rely=0.5, anchor="center")

        self._card_overlays[idx] = overlay

    def _hide_card_loading(self, idx: int) -> None:
        """Hide the loading overlay on a specific card."""
        if idx in self._card_overlays:
            try:
                self._card_overlays[idx].destroy()
            except tk.TclError:
                pass
            del self._card_overlays[idx]

    def _regenerate_outfit(self, idx: int, same_prompt: bool = True) -> None:
        """Regenerate a single outfit."""
        if self._is_generating:
            return

        self._is_generating = True
        self._regenerating_idx = idx  # Track which card is being regenerated
        # Use per-card loading instead of full-screen overlay
        self._show_card_loading(idx, "Regenerating\noutfit...")

        def regenerate():
            try:
                new_path, new_cleanup, used_prompt = self._do_single_regeneration(idx, same_prompt)
                self.schedule_callback(lambda i=idx, p=new_path, c=new_cleanup, u=used_prompt: self._on_single_regen_complete(i, p, c, u))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg))

        thread = threading.Thread(target=regenerate, daemon=True)
        thread.start()

    def _do_single_regeneration(self, idx: int, same_prompt: bool) -> Tuple[Path, Tuple[bytes, bytes], str]:
        """
        Regenerate a single outfit.

        For underwear with same_prompt=True: Try cached prompt up to 4 times.
        For underwear with same_prompt=False: Start fresh from Tier 0.
        For other outfits: Standard regeneration logic.

        Returns:
            Tuple of (path, (original_bytes, rembg_bytes), used_prompt)

        Raises:
            RuntimeError: If regeneration fails after all attempts.
        """
        from ...processing import generate_single_outfit
        from ...api import build_outfit_prompts_with_config

        # Use generated_outfit_keys which only includes outfits that succeeded
        outfit_names = self.state.generated_outfit_keys.copy() if self.state.generated_outfit_keys else []

        outfit_key = outfit_names[idx]
        log_info(f"OUTFIT_REGEN: '{outfit_key}', same={same_prompt}")
        # Use next_pose_letter in add-to-existing mode
        if self.state.is_adding_to_existing:
            pose_letter = self.state.next_pose_letter or "a"
        else:
            pose_letter = "a"
        outfits_dir = self.state.character_folder / pose_letter / "outfits"
        config = self.state.outfit_prompt_config.get(outfit_key, {})
        use_random = config.get("use_random", True)

        # =====================================================================
        # UNDERWEAR: Special regeneration handling
        # =====================================================================
        if outfit_key == "underwear" and use_random:
            if same_prompt:
                # "Regen Same Outfit": Try the cached prompt once
                cached_prompt = self.state.outfit_prompts.get(outfit_key) if self.state.outfit_prompts else None

                if cached_prompt:
                    print(f"[Underwear Regen] Using cached prompt: \"{cached_prompt}\"")
                    result = generate_single_outfit(
                        api_key=self.state.api_key,
                        base_pose_path=self.state.base_pose_path,
                        outfits_dir=outfits_dir,
                        gender_style=self.state.gender_style,
                        outfit_key=outfit_key,
                        outfit_desc=cached_prompt,
                        outfit_prompt_config=self.state.outfit_prompt_config,
                        archetype_label=self.state.archetype_label,
                        for_interactive_review=True,
                    )
                    if result is not None:
                        new_path, original_bytes, rembg_bytes, used_prompt = result
                        return new_path, (original_bytes, rembg_bytes), used_prompt

                    # Attempt failed
                    raise RuntimeError(
                        f"Could not regenerate underwear.\n\n"
                        f"The prompt \"{cached_prompt}\" was blocked by safety filters.\n\n"
                        f"Try \"Regen New Outfit\" instead for a different underwear style."
                    )

            # "Regen New Outfit" OR no cached prompt: Start fresh from Tier 0
            # The tier system will be invoked by generate_single_outfit
            result = generate_single_outfit(
                api_key=self.state.api_key,
                base_pose_path=self.state.base_pose_path,
                outfits_dir=outfits_dir,
                gender_style=self.state.gender_style,
                outfit_key=outfit_key,
                outfit_desc="",  # Empty - tier system will pick prompts
                outfit_prompt_config=self.state.outfit_prompt_config,
                archetype_label=self.state.archetype_label,
                for_interactive_review=True,
            )

            if result is None:
                raise RuntimeError(
                    f"Failed to generate underwear outfit.\n\n"
                    f"All tier prompts were blocked by safety filters."
                )

            new_path, original_bytes, rembg_bytes, used_prompt = result
            # Update stored prompt with what actually worked
            if not self.state.outfit_prompts:
                self.state.outfit_prompts = {}
            self.state.outfit_prompts[outfit_key] = used_prompt
            return new_path, (original_bytes, rembg_bytes), used_prompt

        # =====================================================================
        # NON-UNDERWEAR: Standard regeneration
        # =====================================================================
        if same_prompt and self.state.outfit_prompts and outfit_key in self.state.outfit_prompts:
            # Use existing prompt
            outfit_desc = self.state.outfit_prompts[outfit_key]
        elif not same_prompt and outfit_key in self.state.custom_outfit_prompts and outfit_key in self.state.outfit_prompts:
            # "Regen New Outfit" but user set a custom prompt - reuse it
            outfit_desc = self.state.outfit_prompts[outfit_key]
        else:
            # Generate new random prompt via Gemini text API
            new_prompt_dict = build_outfit_prompts_with_config(
                self.state.api_key,
                self.state.archetype_label,
                self.state.gender_style,
                [outfit_key],
                self.state.outfit_prompt_config,
            )
            outfit_desc = new_prompt_dict[outfit_key]

        result = generate_single_outfit(
            api_key=self.state.api_key,
            base_pose_path=self.state.base_pose_path,
            outfits_dir=outfits_dir,
            gender_style=self.state.gender_style,
            outfit_key=outfit_key,
            outfit_desc=outfit_desc,
            outfit_prompt_config=self.state.outfit_prompt_config,
            archetype_label=self.state.archetype_label,
            for_interactive_review=True,
        )

        if result is None:
            raise RuntimeError(f"Failed to regenerate outfit: {outfit_key}")

        new_path, original_bytes, rembg_bytes, used_prompt = result
        # Update stored prompts with what was actually used
        if not self.state.outfit_prompts:
            self.state.outfit_prompts = {}
        self.state.outfit_prompts[outfit_key] = used_prompt
        return new_path, (original_bytes, rembg_bytes), used_prompt

    def _on_single_regen_complete(self, idx: int, new_path: Path, cleanup_data: Tuple[bytes, bytes], used_prompt: str) -> None:
        """Handle single outfit regeneration completion."""
        self._is_generating = False
        self._hide_card_loading(idx)
        self._regenerating_idx = None

        # Save current cleanup settings before rebuilding (preserves other outfits' settings)
        self._save_cleanup_settings()

        # Update state for regenerated outfit only
        self.state.outfit_paths[idx] = new_path
        self.state.outfit_cleanup_data[idx] = cleanup_data
        _, rembg_bytes = cleanup_data
        self._current_bytes[idx] = rembg_bytes
        self.state.current_outfit_bytes = self._current_bytes.copy()

        # Update the cached prompt with what actually worked (important for underwear)
        # Use generated_outfit_keys which only includes outfits that succeeded
        outfit_names = self.state.generated_outfit_keys.copy() if self.state.generated_outfit_keys else []
        outfit_key = outfit_names[idx]
        if not self.state.outfit_prompts:
            self.state.outfit_prompts = {}
        self.state.outfit_prompts[outfit_key] = used_prompt

        # Mark this outfit's expressions as needing regeneration
        self.state.outfits_needing_expression_regen.add(outfit_key)

        # After regeneration, switch back to auto mode for this outfit
        # (regen always produces auto-removed BG as the result)
        self.state.outfit_bg_modes[idx] = "rembg"

        # Reset cleanup settings for regenerated outfit to defaults (since it's a new image)
        if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
            self.state.outfit_cleanup_settings[idx] = (REMBG_EDGE_CLEANUP_TOLERANCE, REMBG_EDGE_CLEANUP_PASSES)

        # Rebuild cards to show correct UI for mode
        self._build_outfit_cards()

    def _open_custom_regen_modal(self, idx: int, outfit_name: str) -> None:
        """Open the custom regeneration modal for an outfit."""
        if self._is_generating:
            return

        def on_generate(custom_prompt: str):
            self._regenerate_outfit_with_custom_prompt(idx, outfit_name, custom_prompt)

        CustomRegenModal(self.wizard.root, outfit_name, on_generate)

    def _regenerate_outfit_with_custom_prompt(self, idx: int, outfit_name: str, custom_prompt: str) -> None:
        """Regenerate an outfit with a user-provided custom prompt."""
        if self._is_generating:
            return

        self._is_generating = True
        self._regenerating_idx = idx  # Track which card is being regenerated
        # Use per-card loading instead of full-screen overlay
        self._show_card_loading(idx, f"Generating\ncustom\n{outfit_name}...")

        def regenerate():
            try:
                new_path, new_cleanup, used_prompt = self._do_custom_regeneration(idx, custom_prompt)
                self.schedule_callback(lambda i=idx, p=new_path, c=new_cleanup, u=used_prompt: self._on_single_regen_complete(i, p, c, u))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_custom_regen_error(msg))

        thread = threading.Thread(target=regenerate, daemon=True)
        thread.start()

    def _do_custom_regeneration(self, idx: int, custom_prompt: str) -> Tuple[Path, Tuple[bytes, bytes], str]:
        """
        Regenerate an outfit with a custom user-provided prompt.

        Args:
            idx: Outfit index
            custom_prompt: User's custom outfit description

        Returns:
            Tuple of (path, (original_bytes, rembg_bytes), used_prompt)

        Raises:
            RuntimeError: If regeneration fails (e.g., safety filter blocked).
        """
        from ...processing import generate_single_outfit

        outfit_names = self.state.generated_outfit_keys.copy() if self.state.generated_outfit_keys else []
        outfit_key = outfit_names[idx]
        log_info(f"OUTFIT_CUSTOM: '{outfit_key}', prompt={custom_prompt[:100]}")
        # Use next_pose_letter in add-to-existing mode
        if self.state.is_adding_to_existing:
            pose_letter = self.state.next_pose_letter or "a"
        else:
            pose_letter = "a"
        outfits_dir = self.state.character_folder / pose_letter / "outfits"

        # Use the custom prompt directly
        result = generate_single_outfit(
            api_key=self.state.api_key,
            base_pose_path=self.state.base_pose_path,
            outfits_dir=outfits_dir,
            gender_style=self.state.gender_style,
            outfit_key=outfit_key,
            outfit_desc=custom_prompt,
            outfit_prompt_config=self.state.outfit_prompt_config,
            archetype_label=self.state.archetype_label,
            for_interactive_review=True,
        )

        if result is None:
            raise RuntimeError(
                f"The AI declined to generate this outfit.\n\n"
                f"Your description may have triggered content filters.\n\n"
                f"Try a different description."
            )

        new_path, original_bytes, rembg_bytes, used_prompt = result

        # Update stored prompt with the custom prompt that worked
        if not self.state.outfit_prompts:
            self.state.outfit_prompts = {}
        self.state.outfit_prompts[outfit_key] = custom_prompt

        # Track that this outfit has a user-provided custom prompt
        self.state.custom_outfit_prompts.add(outfit_key)

        return new_path, (original_bytes, rembg_bytes), used_prompt

    def _on_custom_regen_error(self, error: str) -> None:
        """Handle custom regeneration error - show message but keep current image."""
        self._is_generating = False
        if self._regenerating_idx is not None:
            self._hide_card_loading(self._regenerating_idx)
            self._regenerating_idx = None
        show_error_dialog(
            self._canvas,
            "Generation Failed",
            f"{error}\n\nThe current outfit image has been kept."
        )

    def _on_regenerate_all(self) -> None:
        """Regenerate all outfits."""
        result = messagebox.askyesno(
            "Regenerate All",
            "This will regenerate all outfits. Continue?"
        )
        if result:
            self._start_outfit_generation()

    def _on_accept(self) -> None:
        """Accept all outfits and continue."""
        if self._is_generating:
            messagebox.showwarning("Generation in Progress", "Please wait for generation to complete.")
            return

        # Save current bytes to disk
        for idx, path in enumerate(self.state.outfit_paths):
            if idx < len(self._current_bytes):
                path.write_bytes(self._current_bytes[idx])

        # Save cleanup settings
        settings = []
        for idx in range(len(self._tolerance_vars)):
            settings.append((self._tolerance_vars[idx].get(), self._depth_vars[idx].get()))
        self.state.outfit_cleanup_settings = settings

        self.request_next()

    def on_leave(self) -> None:
        """Save current bytes to disk and unbind mouse wheel when leaving this step."""
        # Save current bytes to disk so expression generation uses correct images
        # This ensures expression 0 (copied from outfit file) matches what user saw
        for idx, path in enumerate(self.state.outfit_paths):
            if idx < len(self._current_bytes) and self._current_bytes[idx]:
                path.write_bytes(self._current_bytes[idx])

        try:
            self._canvas.unbind_all("<MouseWheel>")
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")
        except Exception:
            pass  # Ignore if already unbound

    def validate(self) -> bool:
        """Validate before advancing."""
        if self._is_generating:
            messagebox.showwarning("Generation in Progress", "Please wait for generation to complete.")
            return False

        if not self.state.outfit_paths:
            messagebox.showerror("No Outfits", "No outfits have been generated.")
            return False

        return True

    def is_dirty(self) -> bool:
        return True

    def get_dirty_steps(self) -> list:
        return [9, 10]  # Expression steps
