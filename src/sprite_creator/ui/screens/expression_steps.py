"""
Expression wizard step (Step 10).

Handles expression generation and review for each outfit.
"""

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
    TEXT_DISABLED,
    ACCENT_COLOR,
    ERROR_TEXT,
    ERROR_BG,
    OVERLAY_BG,
    WARNING_TEXT,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
    get_backup_dir,
)
from ..tk_common import (
    create_primary_button,
    create_secondary_button,
    show_error_dialog,
)
from .base import WizardStep, WizardState
from ...logging_utils import log_info, log_error, log_generation_start, log_generation_complete


class ExpressionReviewStep(WizardStep):
    """
    Step 7: Expression Review.

    Generates and displays expressions for each outfit.
    Allows per-expression regeneration.
    """

    STEP_ID = "expression_review"
    STEP_TITLE = "Expressions"
    STEP_NUMBER = 7
    STEP_HELP = """Expression Review

This step shows all generated expressions for each outfit.

HOW THIS RELATES TO THE PREVIOUS STEP
The background removal settings (Tolerance/Depth) you set on the Outfit Review step were used to process these expressions. If backgrounds look good here, those settings worked well!

If backgrounds need work, use the "Remove BG" button below each expression to fix them individually.

IMPORTANT: You must review ALL outfits before proceeding.

═══════════════════════════════════════════════════
TROUBLESHOOTING - WHEN TO REGENERATE
═══════════════════════════════════════════════════

REGENERATE if you see any of these issues:

• Expression goes off-screen or is cropped weirdly
  The AI sometimes generates images that extend past the frame. Click "Regen" to try again.

• Bad framing / expression doesn't match others
  If one expression looks zoomed in/out differently, or the character is positioned differently, regenerate to get better consistency.

• Showing feet or different body position
  All expressions should match the base outfit's framing. If not, regenerate.

• Arm/body pixels look "eaten" or deleted
  This is caused by the automatic background removal (rembg) being too aggressive. You have two options:
  1. Click "Regen" - may produce a version that rembg handles better
  2. Use "Remove BG" to manually fix it (see below)

═══════════════════════════════════════════════════
HOW TO USE THE FLOOD FILL / TOUCH-UP TOOL
═══════════════════════════════════════════════════

Click "Remove BG" to open the editor:

1. CLICK on background areas to remove them
   Each click removes a connected area of similar color (flood fill).

2. ADJUST TOLERANCE (slider at top)
   - Low tolerance (10-30): Only removes very similar colors
   - High tolerance (50-80): Removes a wider range of colors
   Start with lower values to avoid accidentally removing parts of the character.

3. Work from OUTSIDE IN
   Click on the main background area first, then work toward edges.

4. For FINE DETAILS (hair strands, edges):
   Lower the tolerance and click carefully on remaining spots.

5. RESTART button: Undoes ALL your changes and starts over.

6. Click ACCEPT when the background is fully removed.

Tip: If you switched to "Manual Mode" on the previous step because rembg was eating arm pixels, the "Remove BG" tool here will start from the original black-background image, letting you manually remove the background while preserving the full character.

═══════════════════════════════════════════════════

NAVIGATION
Use the "< Prev" and "Next >" buttons to switch between outfits.

The progress indicator shows:
- Current outfit number and name
- How many outfits you've viewed

The Next button is disabled until you've viewed every outfit at least once.

EXPRESSION CARDS
Each card shows one expression with its number and description.

Expression 0 (neutral) cannot be regenerated - it uses the outfit image directly and is the base for all other expressions.

REGENERATION
Click "Regen" on any expression (except 0) to generate a new version. The AI will create a different interpretation of that expression while keeping the same outfit.

BACKGROUND REMOVAL
Each expression has a "Remove BG" button that opens a click-based flood-fill editor.

The starting point depends on the outfit's mode from the previous step:
- Auto mode: Starts from the rembg-processed result (use to touch up remaining artifacts)
- Manual mode: Starts from the original black-background image (use for full manual removal)

For existing outfits in add-to-character mode, expressions always use manual removal mode.

WORKFLOW
1. Use Prev/Next to view each outfit's expressions
2. Regenerate any expressions that don't look right
3. Use "Remove BG" to fix any background issues you notice
4. Once all outfits are viewed, click Next

Note: Changes are saved automatically. You can go back and forth between outfits without losing work.

ADD-TO-EXISTING MODE
When adding expressions to existing outfits:
- Existing outfits appear in the dropdown with "existing_" prefix
- Expression 0 (the original neutral) is shown as a read-only reference
- Only the expressions you selected in Step 4 are generated
- New expressions are saved directly to the existing character folder
- The reference card has a darker background to indicate it's not editable"""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._canvas: Optional[tk.Canvas] = None
        self._inner_frame: Optional[tk.Frame] = None
        self._outfit_frames: Dict[str, tk.Frame] = {}
        self._img_refs: List[ImageTk.PhotoImage] = []
        self._status_label: Optional[tk.Label] = None
        self._is_generating: bool = False
        self._current_outfit_idx: int = 0
        self._viewed_outfits: set = set()  # Track which outfits have been viewed
        self._progress_label: Optional[tk.Label] = None
        # Store cleanup data for manual BG removal: {"outfit_name": {"0": (orig_bytes, rembg_bytes), ...}}
        self._expression_cleanup_data: Dict[str, Dict[str, Tuple[bytes, bytes]]] = {}
        # Per-card loading: {(outfit_name, expr_key): card_frame}
        self._expr_card_frames: Dict[Tuple[str, str], tk.Frame] = {}
        self._expr_card_overlays: Dict[Tuple[str, str], tk.Frame] = {}
        self._regenerating_expr: Optional[Tuple[str, str]] = None  # (outfit, expr_key)

        # For add-to-existing mode: tracking existing outfit expression generation
        self._current_existing_outfit_idx: int = 0
        self._existing_outfit_keys: List[str] = []  # List of pose letters to extend

        # For selective regeneration (dirty outfits only)
        self._selective_dirty_outfits: List[str] = []
        self._selective_idx: int = 0

        # Rolling generation: show UI after first outfit completes, generate rest in background
        self._outfit_gen_status: Dict[str, str] = {}   # "pending"/"generating"/"complete"
        self._current_gen_outfit: Optional[str] = None  # outfit currently being generated
        self._current_gen_progress: str = ""             # live progress text for inline display
        self._first_outfit_shown: bool = False           # True after first outfit's cards shown
        self._loading_overlay: Optional[tk.Frame] = None  # Overlay on canvas for loading state

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Header
        header = tk.Frame(parent, bg=BG_COLOR)
        header.pack(fill="x", pady=(0, 8))

        tk.Label(
            header,
            text="Review Expressions",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(side="left")

        # Note: BG mode is determined per-outfit from the Outfits step
        # (removed global BG mode toggle that didn't do anything)

        # Progress indicator (centered) with prev/next arrows
        progress_frame = tk.Frame(parent, bg=BG_COLOR)
        progress_frame.pack(fill="x", pady=(0, 8))

        # Prev button
        self._prev_btn = create_secondary_button(
            progress_frame, "< Prev",
            self._prev_outfit,
            width=8
        )
        self._prev_btn.pack(side="left", padx=(20, 10))

        # Center progress label
        center_frame = tk.Frame(progress_frame, bg=BG_COLOR)
        center_frame.pack(side="left", expand=True)

        self._progress_label = tk.Label(
            center_frame,
            text="Outfit 1 of 1: Loading...",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=SECTION_FONT,
        )
        self._progress_label.pack()

        # Next button
        self._next_outfit_btn = create_secondary_button(
            progress_frame, "Next >",
            self._next_outfit,
            width=8
        )
        self._next_outfit_btn.pack(side="right", padx=(10, 20))

        # Inline tip
        tk.Label(
            parent,
            text="💡 Use 'Remove BG' button to fix background issues on any expression. "
                 "You must view ALL outfits before proceeding.",
            bg=BG_COLOR,
            fg=WARNING_TEXT,
            font=SMALL_FONT,
            wraplength=800,
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        # Scrollable canvas for expression cards (horizontal like outfits)
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

        # Status
        self._status_label = tk.Label(
            parent,
            text="",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=SMALL_FONT,
        )
        self._status_label.pack(pady=(8, 0))

        # Hidden outfit var for compatibility
        self._outfit_var = tk.StringVar(value="")

    def _on_frame_configure(self, event=None) -> None:
        """Update scroll region and bind mouse wheel."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        # Bind mouse wheel for horizontal scrolling
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", lambda e: self._canvas.xview_scroll(-1, "units"))
        self._canvas.bind_all("<Button-5>", lambda e: self._canvas.xview_scroll(1, "units"))

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel for horizontal scrolling."""
        # Don't scroll cards when a modal (Toplevel) has focus
        try:
            widget = event.widget
            if not isinstance(widget, str):
                top = widget.winfo_toplevel()
                if isinstance(top, tk.Toplevel):
                    return
        except Exception:
            pass
        self._canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _prev_outfit(self) -> None:
        """Navigate to previous outfit."""
        outfit_names = self._get_outfit_names()
        if not outfit_names:
            return
        current_idx = outfit_names.index(self._outfit_var.get()) if self._outfit_var.get() in outfit_names else 0
        if current_idx > 0:
            self._outfit_var.set(outfit_names[current_idx - 1])
            self._show_outfit_expressions()

    def _next_outfit(self) -> None:
        """Navigate to next outfit."""
        outfit_names = self._get_outfit_names()
        if not outfit_names:
            return
        current_idx = outfit_names.index(self._outfit_var.get()) if self._outfit_var.get() in outfit_names else 0
        if current_idx < len(outfit_names) - 1:
            self._outfit_var.set(outfit_names[current_idx + 1])
            self._show_outfit_expressions()

    def _update_progress_indicator(self) -> None:
        """Update the progress indicator label and buttons."""
        outfit_names = self._get_outfit_names()
        if not outfit_names:
            self._progress_label.configure(text="No outfits")
            return

        current_outfit = self._outfit_var.get()
        if current_outfit not in outfit_names:
            current_outfit = outfit_names[0]
            self._outfit_var.set(current_outfit)

        current_idx = outfit_names.index(current_outfit)
        total = len(outfit_names)

        # Mark as viewed — only count if outfit has completed expressions
        # (viewing a generating/pending outfit doesn't count)
        if current_outfit in self.state.expression_paths:
            self._viewed_outfits.add(current_outfit)

        # Format display name - for existing outfits show "Pose A" instead of "existing_a"
        display_name = current_outfit
        if current_outfit.startswith("existing_"):
            pose_letter = current_outfit.replace("existing_", "")
            display_name = f"Pose {pose_letter.upper()} (existing)"

        # Update label
        viewed_count = len(self._viewed_outfits)
        self._progress_label.configure(
            text=f"Outfit {current_idx + 1} of {total}: {display_name.capitalize()}"
        )

        # Update prev/next button states
        self._prev_btn.configure(state="normal" if current_idx > 0 else "disabled")
        self._next_outfit_btn.configure(state="normal" if current_idx < total - 1 else "disabled")

        # Update status to show progress and control wizard's Next button
        still_generating = self._is_generating
        if viewed_count < total:
            if still_generating:
                self._status_label.configure(
                    text=f"Generating remaining outfits... ({viewed_count}/{total} reviewed)"
                )
            else:
                self._status_label.configure(
                    text=f"Review all outfits before continuing ({viewed_count}/{total} viewed)"
                )
            # Disable wizard's Next button until all outfits are viewed
            self.wizard._next_btn.configure(state="disabled")
        else:
            self._status_label.configure(
                text=f"All {total} outfits reviewed. Click Next to continue."
            )
            # Enable wizard's Next button when all outfits are viewed
            self.wizard._next_btn.configure(state="normal")

    def on_enter(self) -> None:
        """Generate expressions when step becomes active.

        Smart regeneration logic:
        1. If no expressions exist yet → full generation (first time)
        2. If expressions_sequence changed since last generation → regenerate ALL
        3. If specific outfits are in outfits_needing_expression_regen → selective regen
        4. If nothing changed → show existing expressions (free forward navigation)
        """
        # Check if we already have expressions on disk
        has_existing_expressions = (
            self.state.expression_paths
            and len(self.state.expression_paths) > 0
            and all(
                p.exists()
                for paths in self.state.expression_paths.values()
                for p in paths.values()
            )
        )

        # Disable wizard's Next button initially (will be enabled once all outfits viewed)
        self.wizard._next_btn.configure(state="disabled")

        # Initialize outfit selection
        outfit_names = self._get_outfit_names()
        if outfit_names:
            self._outfit_var.set(outfit_names[0])

        # === Scenario 1: No expressions at all → full generation ===
        if not has_existing_expressions:
            log_info("EXPR: Decision=full_generation (no existing expressions)")
            self._viewed_outfits = set()
            self._start_expression_generation()
            return

        # === Scenario 2: Expression sequence changed → regenerate ALL ===
        if (self.state.last_expression_sequence and
                self.state.expressions_sequence != self.state.last_expression_sequence):
            log_info("EXPR: Decision=full_regen (expression sequence changed)")
            self._viewed_outfits = set()
            # Clear existing expression paths so full regen runs
            self.state.expression_paths = {}
            self._start_expression_generation()
            return

        # === Scenario 3: Specific outfits need expression regeneration ===
        dirty_outfits = self.state.outfits_needing_expression_regen.copy()
        if dirty_outfits:
            log_info(f"EXPR: Decision=selective_regen, dirty={dirty_outfits}")
            # Reset viewed status for dirty outfits so user must re-review
            self._viewed_outfits -= dirty_outfits
            self._start_selective_expression_generation(dirty_outfits)
            return

        # === Scenario 4: Nothing changed → show existing expressions ===
        log_info("EXPR: Decision=show_existing (nothing changed)")
        self._show_outfit_expressions()
        self._update_progress_indicator()
        return

    def on_leave(self) -> None:
        """Unbind mouse wheel and restore Next button when leaving this step."""
        # Restore wizard's Next button state
        self.wizard._next_btn.configure(state="normal")

        try:
            self._canvas.unbind_all("<MouseWheel>")
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")
        except Exception:
            pass

    def _get_outfit_names(self) -> List[str]:
        """Get list of outfit names that were actually generated.

        Uses generated_outfit_keys which tracks outfits that succeeded,
        handling cases where outfits like underwear may be skipped due to safety filters.

        Also includes existing outfits being extended (in add-to-existing mode).
        """
        names = []

        # New outfits (use generated_outfit_keys if available)
        if self.state.generated_outfit_keys:
            names.extend(self.state.generated_outfit_keys)
        else:
            # Fallback for backwards compatibility (shouldn't happen in normal flow)
            if self.state.use_base_as_outfit:
                names.append("base")
            names.extend(self.state.selected_outfits)

        # In add-to-existing mode, also include existing outfits being extended
        if self.state.is_adding_to_existing and self.state.existing_outfits_to_extend:
            for pose_letter in sorted(self.state.existing_outfits_to_extend.keys()):
                existing_name = f"existing_{pose_letter}"
                if existing_name not in names:
                    names.append(existing_name)

        return names

    def _on_all_expressions_complete(self) -> None:
        """Called when all expression generation (full or selective) is done."""
        log_info("EXPR: All expressions complete")
        # Snapshot the expression sequence so we can detect changes on re-entry
        self.state.last_expression_sequence = list(self.state.expressions_sequence)
        # Clear the dirty set since we've regenerated everything that was dirty
        self.state.outfits_needing_expression_regen.clear()
        self._current_gen_outfit = None

        if self._first_outfit_shown:
            # Rolling mode: UI is already visible. Refresh current outfit's cards
            # (in case user is viewing the last outfit that just completed)
            current_outfit = self._outfit_var.get()
            if current_outfit and current_outfit in self.state.expression_paths:
                self._show_outfit_expressions()
            self._update_progress_indicator()
        else:
            # Edge case: all outfits completed before UI was shown (e.g., single outfit)
            self._first_outfit_shown = True
            outfit_names = self._get_outfit_names()
            if outfit_names:
                self._outfit_var.set(outfit_names[0])
            self._show_outfit_expressions()

        self._status_label.configure(text="All expressions generated. Review and accept.")

    def _start_expression_generation(self) -> None:
        """Start generating expressions for all outfits (rolling generation).

        Shows full-screen overlay only for the first outfit. After it completes,
        the review UI appears and remaining outfits generate in the background.
        """
        if self._is_generating:
            return

        self._is_generating = True
        self._current_outfit_idx = 0
        self._first_outfit_shown = False
        self._current_gen_progress = ""
        self._current_gen_outfit = None

        # Initialize per-outfit generation status (new + existing outfits)
        self._outfit_gen_status.clear()
        if self.state.generated_outfit_keys:
            names = self.state.generated_outfit_keys.copy()
        else:
            names = []
            if self.state.use_base_as_outfit:
                names.append("base")
            names.extend(self.state.selected_outfits)
        # Include existing outfits in add-to-existing mode
        if self.state.is_adding_to_existing and self.state.existing_outfits_to_extend:
            for pose_letter in sorted(self.state.existing_outfits_to_extend.keys()):
                names.append(f"existing_{pose_letter}")
        for name in names:
            self._outfit_gen_status[name] = "pending"

        self._status_label.configure(text="Generating expressions...")
        self.show_loading("Generating expressions...")

        # Generate for first outfit, then chain to next
        self._generate_next_outfit()

    def _start_selective_expression_generation(self, dirty_outfits: set) -> None:
        """Regenerate expressions only for specific dirty outfits (rolling generation).

        Preserves existing expressions for clean outfits while regenerating
        only the outfits that were changed (e.g., via outfit regeneration).
        Clean outfits already have data, so we show the UI immediately and
        generate dirty outfits in the background with inline progress.
        """
        if self._is_generating:
            return

        self._is_generating = True
        self._selective_dirty_outfits = list(dirty_outfits)
        self._selective_idx = 0
        self._current_gen_progress = ""
        self._current_gen_outfit = None

        # Initialize per-outfit status for dirty outfits
        for name in self._selective_dirty_outfits:
            self._outfit_gen_status[name] = "pending"

        # Clean outfits already have expression data, so show the UI right away.
        # Navigate to a clean outfit if the current one is dirty.
        outfit_names = self._get_outfit_names()
        current = self._outfit_var.get()
        if current in dirty_outfits and outfit_names:
            # Try to navigate to a clean outfit so user sees cards immediately
            for name in outfit_names:
                if name not in dirty_outfits:
                    self._outfit_var.set(name)
                    break

        self._first_outfit_shown = True  # Skip full-screen overlay since clean outfits have data
        self._show_outfit_expressions()
        self._status_label.configure(text="Regenerating changed expressions...")

        self._generate_next_selective_outfit()

    def _generate_next_selective_outfit(self) -> None:
        """Generate expressions for the next dirty outfit in selective mode (rolling)."""
        if self._selective_idx >= len(self._selective_dirty_outfits):
            # All dirty outfits done
            self._is_generating = False
            if not self._first_outfit_shown:
                self.hide_loading()
            self._on_all_expressions_complete()
            return

        outfit_name = self._selective_dirty_outfits[self._selective_idx]
        outfit_num = self._selective_idx + 1
        total = len(self._selective_dirty_outfits)

        # Update status tracking
        self._outfit_gen_status[outfit_name] = "generating"
        self._current_gen_outfit = outfit_name
        self._current_gen_progress = ""

        self._status_label.configure(
            text=f"Regenerating expressions for {outfit_name}... ({outfit_num}/{total})"
        )

        def update_expression_progress(current: int, total_expr: int, expression_name: str):
            progress_text = (
                f"Outfit {outfit_num}/{total}: {outfit_name}\n"
                f"Expression {current}/{total_expr}: {expression_name.replace('_', ' ').title()}"
            )
            if not self._first_outfit_shown:
                # First dirty outfit: update full-screen overlay
                self.schedule_callback(lambda: self.show_loading(progress_text))
            else:
                # Subsequent: inline progress
                self._current_gen_progress = progress_text
                self.schedule_callback(lambda: self._update_inline_progress())

        def generate():
            try:
                expr_paths, cleanup_dict = self._do_expression_generation(outfit_name, update_expression_progress)
                self.schedule_callback(lambda n=outfit_name, p=expr_paths, c=cleanup_dict: self._on_selective_outfit_complete(n, p, c))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg))

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _on_selective_outfit_complete(self, outfit_name: str, expr_paths: Dict[str, Path], cleanup_dict: Dict[str, Tuple[bytes, bytes]]) -> None:
        """Handle completion of one selectively regenerated outfit's expressions (rolling)."""
        log_generation_complete(f"expressions_{outfit_name}", True, f"Regenerated {len(expr_paths)} expressions")

        # Update state (overwrites old paths for this outfit)
        if not self.state.expression_paths:
            self.state.expression_paths = {}
        self.state.expression_paths[outfit_name] = expr_paths

        # Update cleanup data
        self._expression_cleanup_data[outfit_name] = cleanup_dict

        # Update generation status
        self._outfit_gen_status[outfit_name] = "complete"

        if not self._first_outfit_shown:
            # First dirty outfit done — show review UI
            self._first_outfit_shown = True
            self.hide_loading()
            self._outfit_var.set(outfit_name)
            self._show_outfit_expressions()
        else:
            # Subsequent dirty outfit done — refresh if user is viewing it
            if self._outfit_var.get() == outfit_name:
                self._show_outfit_expressions()

        # Move to next dirty outfit
        self._selective_idx += 1
        self._generate_next_selective_outfit()

    def _generate_next_outfit(self) -> None:
        """Generate expressions for the next new outfit (rolling generation).

        First outfit shows full-screen overlay. After it completes, subsequent
        outfits generate in the background with inline progress updates.
        """
        # Get only NEW outfit names (not existing outfits being extended)
        if self.state.generated_outfit_keys:
            new_outfit_names = self.state.generated_outfit_keys.copy()
        else:
            new_outfit_names = []
            if self.state.use_base_as_outfit:
                new_outfit_names.append("base")
            new_outfit_names.extend(self.state.selected_outfits)

        if self._current_outfit_idx >= len(new_outfit_names):
            # All NEW outfits done - check if we need to handle existing outfits
            if self.state.is_adding_to_existing and self.state.existing_outfits_to_extend:
                log_info(f"EXPR: New outfits done. Starting existing outfits: {self.state.existing_outfits_to_extend}")
                self._existing_outfit_keys = sorted(self.state.existing_outfits_to_extend.keys())
                self._current_existing_outfit_idx = 0
                self._generate_next_existing_outfit()
            else:
                # All done
                if self.state.is_adding_to_existing:
                    log_info("EXPR: No existing outfits to extend (existing_outfits_to_extend is empty)")
                self._is_generating = False
                if not self._first_outfit_shown:
                    self.hide_loading()
                self._on_all_expressions_complete()
            return

        outfit_name = new_outfit_names[self._current_outfit_idx]
        outfit_num = self._current_outfit_idx + 1
        total_new = len(new_outfit_names)
        # Also count existing outfits for total progress
        total_existing = len(self.state.existing_outfits_to_extend) if self.state.is_adding_to_existing else 0
        total_outfits = total_new + total_existing

        # Update status tracking
        self._outfit_gen_status[outfit_name] = "generating"
        self._current_gen_outfit = outfit_name
        self._current_gen_progress = ""

        self._status_label.configure(
            text=f"Generating expressions for {outfit_name}... ({outfit_num}/{total_outfits})"
        )

        def update_expression_progress(current: int, total: int, expression_name: str):
            """Update progress — full overlay for first outfit, inline for subsequent."""
            progress_text = (
                f"Outfit {outfit_num}/{total_outfits}: {outfit_name}\n"
                f"Expression {current}/{total}: {expression_name.replace('_', ' ').title()}"
            )
            if not self._first_outfit_shown:
                # First outfit: update full-screen overlay
                self.schedule_callback(lambda: self.show_loading(progress_text))
            else:
                # Subsequent: store progress and update inline if user is viewing this outfit
                self._current_gen_progress = progress_text
                self.schedule_callback(lambda: self._update_inline_progress())

        def generate():
            try:
                expr_paths, cleanup_dict = self._do_expression_generation(outfit_name, update_expression_progress)
                self.schedule_callback(lambda n=outfit_name, p=expr_paths, c=cleanup_dict: self._on_outfit_expressions_complete(n, p, c))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg))

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _update_inline_progress(self) -> None:
        """Update the inline loading indicator if user is viewing the generating outfit.

        Instead of rebuilding the entire card set, just update the progress label
        text to avoid flickering from frequent rebuilds.
        """
        if not self._current_gen_outfit:
            return
        current_outfit = self._outfit_var.get()
        if current_outfit == self._current_gen_outfit:
            # Try to update existing progress label in the loading overlay
            if self._loading_overlay is not None:
                try:
                    for child in self._loading_overlay.winfo_children():
                        if isinstance(child, tk.Label) and child.cget("fg") == TEXT_SECONDARY:
                            if self._current_gen_progress:
                                child.configure(text=self._current_gen_progress)
                                return
                except (tk.TclError, Exception):
                    pass
            # Fallback: full rebuild if label not found (first time showing)
            self._show_outfit_expressions()

    def _do_expression_generation(self, outfit_name: str, progress_callback=None) -> Tuple[Dict[str, Path], Dict[str, Tuple[bytes, bytes]]]:
        """Generate expressions for one outfit."""
        from ...processing import generate_expressions_for_single_outfit_once

        log_info(f"EXPR_GEN: {len(self.state.expressions_sequence)} exprs for '{outfit_name}'")
        log_generation_start(f"expressions_{outfit_name}", count=len(self.state.expressions_sequence))

        # Find the outfit path
        outfit_names = self._get_outfit_names()
        idx = outfit_names.index(outfit_name)

        if idx >= len(self.state.outfit_paths):
            raise ValueError(f"No outfit path for {outfit_name}")

        outfit_path = self.state.outfit_paths[idx]

        # Determine paths - use next_pose_letter in add-to-existing mode
        if self.state.is_adding_to_existing:
            pose_letter = self.state.next_pose_letter or "a"
        else:
            pose_letter = "a"
        pose_dir = self.state.character_folder / pose_letter
        faces_root = pose_dir / "faces"
        faces_root.mkdir(parents=True, exist_ok=True)

        # Get cleanup settings from outfit review (if available)
        edge_cleanup_tolerance = None
        edge_cleanup_passes = None
        if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
            edge_cleanup_tolerance, edge_cleanup_passes = self.state.outfit_cleanup_settings[idx]

        # Get bg removal mode from outfit review
        bg_removal_mode = self._get_bg_mode_for_outfit(outfit_name)

        # Generate expressions - returns (path_list, cleanup_data_list, generated_keys, failed_keys)
        expr_path_list, cleanup_data_list, generated_keys, failed_keys = generate_expressions_for_single_outfit_once(
            api_key=self.state.api_key,
            pose_dir=pose_dir,
            outfit_path=outfit_path,
            faces_root=faces_root,
            expressions_sequence=self.state.expressions_sequence,
            edge_cleanup_tolerance=edge_cleanup_tolerance,
            edge_cleanup_passes=edge_cleanup_passes,
            for_interactive_review=True,  # Need cleanup_data for manual BG removal
            bg_removal_mode=bg_removal_mode,
            progress_callback=progress_callback,
            archetype_label=self.state.archetype_label,
        )

        if failed_keys:
            log_info(f"EXPR_GEN: Failed expressions for '{outfit_name}': {[(k, d) for k, d in failed_keys]}")

        # Convert lists to dicts keyed by expression key using generated_keys (fixes alignment bug)
        expr_paths: Dict[str, Path] = {}
        cleanup_dict: Dict[str, Tuple[bytes, bytes]] = {}
        for i, (path, key) in enumerate(zip(expr_path_list, generated_keys)):
            expr_paths[key] = path
            if i < len(cleanup_data_list):
                cleanup_dict[key] = cleanup_data_list[i]

        # Track failed expressions in state so the UI can show them
        if failed_keys:
            if not hasattr(self.state, 'failed_expressions') or self.state.failed_expressions is None:
                self.state.failed_expressions = set()
            for failed_key, failed_desc in failed_keys:
                self.state.failed_expressions.add((outfit_name, failed_key))

        # Fix expression 0's cleanup data - use outfit's original black-bg bytes instead of transparent
        # Expression 0 is just the outfit file, which at this point has transparent BG from rembg.
        # For manual BG removal to work, we need the original black-bg bytes from the outfit step.
        if "0" in cleanup_dict and self.state.outfit_cleanup_data and idx < len(self.state.outfit_cleanup_data):
            original_outfit_bytes, _ = self.state.outfit_cleanup_data[idx]
            if original_outfit_bytes and len(original_outfit_bytes) > 100:
                # Keep the rembg result as the second element (what's currently displayed)
                _, current_rembg = cleanup_dict["0"]
                cleanup_dict["0"] = (original_outfit_bytes, current_rembg)

        return expr_paths, cleanup_dict

    def _on_outfit_expressions_complete(self, outfit_name: str, expr_paths: Dict[str, Path], cleanup_dict: Dict[str, Tuple[bytes, bytes]]) -> None:
        """Handle completion of one outfit's expressions (rolling generation).

        First completion: remove full-screen overlay and show review UI.
        Subsequent completions: refresh cards if user is viewing that outfit.
        """
        log_generation_complete(f"expressions_{outfit_name}", True, f"Generated {len(expr_paths)} expressions")

        # Store in state
        if not self.state.expression_paths:
            self.state.expression_paths = {}
        self.state.expression_paths[outfit_name] = expr_paths

        # Store cleanup data for manual BG removal
        self._expression_cleanup_data[outfit_name] = cleanup_dict

        # Update generation status
        self._outfit_gen_status[outfit_name] = "complete"

        if not self._first_outfit_shown:
            # First outfit done — remove overlay and show review UI
            self._first_outfit_shown = True
            self.hide_loading()
            self._outfit_var.set(outfit_name)
            self._show_outfit_expressions()
        else:
            # Subsequent outfit done — refresh if user is viewing it
            if self._outfit_var.get() == outfit_name:
                self._show_outfit_expressions()

        # Chain to next outfit
        self._current_outfit_idx += 1
        self._generate_next_outfit()

    def _generate_next_existing_outfit(self) -> None:
        """Generate expressions for the next existing outfit (add-to-existing mode, rolling)."""
        if self._current_existing_outfit_idx >= len(self._existing_outfit_keys):
            # All done (both new and existing)
            log_info("EXPR_EXISTING: All existing outfit expressions complete")
            self._is_generating = False
            if not self._first_outfit_shown:
                self.hide_loading()
            self._on_all_expressions_complete()
            return

        pose_letter = self._existing_outfit_keys[self._current_existing_outfit_idx]
        existing_name = f"existing_{pose_letter}"
        log_info(f"EXPR_EXISTING: Starting pose {pose_letter}, expressions={self.state.existing_outfits_to_extend.get(pose_letter, [])}")

        # Calculate progress
        if self.state.generated_outfit_keys:
            total_new = len(self.state.generated_outfit_keys)
        else:
            total_new = len(self.state.selected_outfits) + (1 if self.state.use_base_as_outfit else 0)

        total_existing = len(self._existing_outfit_keys)
        total_outfits = total_new + total_existing
        current_num = total_new + self._current_existing_outfit_idx + 1

        # Update status tracking
        self._outfit_gen_status[existing_name] = "generating"
        self._current_gen_outfit = existing_name
        self._current_gen_progress = ""

        self._status_label.configure(
            text=f"Adding expressions to pose {pose_letter}... ({current_num}/{total_outfits})"
        )

        # Get expressions to add for this pose
        expressions_to_add = self.state.existing_outfits_to_extend.get(pose_letter, [])
        total_expr = len(expressions_to_add)

        def update_expression_progress(current: int, total: int, expression_name: str):
            """Update progress — full overlay for first outfit, inline for subsequent."""
            progress_text = (
                f"Outfit {current_num}/{total_outfits}: Pose {pose_letter.upper()}\n"
                f"Expression {current}/{total}: {expression_name.replace('_', ' ').title()}"
            )
            if not self._first_outfit_shown:
                self.schedule_callback(lambda: self.show_loading(progress_text))
            else:
                self._current_gen_progress = progress_text
                self.schedule_callback(lambda: self._update_inline_progress())

        def generate():
            try:
                expr_paths, cleanup_dict = self._do_existing_outfit_expression_generation(
                    pose_letter, expressions_to_add, update_expression_progress
                )
                self.schedule_callback(lambda n=existing_name, p=expr_paths, c=cleanup_dict: self._on_existing_outfit_complete(n, p, c))
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg))

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()

    def _do_existing_outfit_expression_generation(
        self,
        pose_letter: str,
        expressions_to_add: List[str],
        progress_callback=None
    ) -> Tuple[Dict[str, Path], Dict[str, Tuple[bytes, bytes]]]:
        """Generate expressions for an existing outfit.

        Uses the pose's faces/face/0.png (or 1.png) as the base image.
        Only generates the specified expressions (not all).
        Does NOT clear existing files or overwrite existing expressions.
        """
        from ...api.gemini_client import load_image_as_base64, call_gemini_image_edit
        from ...api.prompt_builders import build_expression_prompt
        from ...processing.image_utils import save_image_bytes_as_png
        from ...config import EXPRESSIONS_SEQUENCE

        log_info(f"EXPR_EXISTING: pose='{pose_letter}', exprs={expressions_to_add}")
        log_generation_start(f"existing_expressions_{pose_letter}", count=len(expressions_to_add))

        # Get the existing character folder
        char_folder = self.state.existing_character_folder
        pose_dir = char_folder / pose_letter
        faces_dir = pose_dir / "faces" / "face"

        # Find the base image - prefer full-size backup over scaled version
        # Backups are stored externally at ~/.sprite_creator/backups/<backup_id>/
        base_path = None
        use_backup = False

        # Priority 1: External backup storage (new location)
        backup_id = self.state.backup_id
        if backup_id:
            ext_backup_dir = get_backup_dir(backup_id) / pose_letter / "faces" / "face"
            if ext_backup_dir.is_dir():
                for ext in [".png", ".webp"]:
                    test_path = ext_backup_dir / f"0{ext}"
                    if test_path.exists():
                        base_path = test_path
                        use_backup = True
                        break

        # Priority 2: Legacy in-folder _backups (for old characters not yet migrated)
        if not base_path:
            legacy_backup_dir = char_folder / "_backups" / pose_letter / "faces" / "face"
            if legacy_backup_dir.is_dir():
                for ext in [".png", ".webp"]:
                    test_path = legacy_backup_dir / f"0{ext}"
                    if test_path.exists():
                        base_path = test_path
                        use_backup = True
                        break

        # Priority 3: existing face (may be scaled down)
        if not base_path:
            for expr_num in ["0", "1"]:
                for ext in [".png", ".webp"]:
                    test_path = faces_dir / f"{expr_num}{ext}"
                    if test_path.exists():
                        base_path = test_path
                        break
                if base_path:
                    break

        if not base_path:
            raise ValueError(f"No base expression (0 or 1) found in {faces_dir}")

        log_info(f"Using {'backup' if use_backup else 'existing'} base image for pose {pose_letter}: {base_path}")

        # Build expression sequence from MASTER list (EXPRESSIONS_SEQUENCE), not state.expressions_sequence
        # This is critical for add-to-existing mode where user may select different expressions
        # for existing poses than they selected for new outfits
        master_expr_dict = {key: desc for key, desc in EXPRESSIONS_SEQUENCE}

        # Also include any custom expressions from current session's expressions_sequence
        for key, desc in self.state.expressions_sequence:
            if key not in master_expr_dict:
                master_expr_dict[key] = desc

        filtered_sequence = [(key, master_expr_dict[key]) for key in expressions_to_add if key in master_expr_dict]

        # Warn about any expressions that couldn't be found
        missing_keys = [key for key in expressions_to_add if key not in master_expr_dict]
        if missing_keys:
            log_error("Expression lookup", f"Could not find descriptions for expression keys: {missing_keys}")

        log_info(f"Generating expressions for pose {pose_letter}: {[k for k, _ in filtered_sequence]}")

        if not filtered_sequence:
            log_info(f"No expressions to generate for pose {pose_letter}")
            return {}, {}

        # Load base image as b64 for Gemini
        image_b64 = load_image_as_base64(base_path)
        background_color = "solid black (#000000)"

        expr_paths: Dict[str, Path] = {}
        cleanup_dict: Dict[str, Tuple[bytes, bytes]] = {}

        total = len(filtered_sequence)
        for i, (expr_key, expr_desc) in enumerate(filtered_sequence):
            # Report progress
            if progress_callback:
                progress_callback(i + 1, total, expr_desc)

            out_stem = faces_dir / expr_key
            log_info(f"Generating expression {expr_key} for pose {pose_letter}: {expr_desc}")

            try:
                # Build prompt and call Gemini
                # Backups are always full-size, so no upscale/sharpen needed
                prompt = build_expression_prompt(expr_desc, background_color, add_to_existing=False, archetype_label=self.state.archetype_label)
                original_bytes = call_gemini_image_edit(
                    self.state.api_key, prompt, image_b64,
                    skip_background_removal=True,
                )

                if original_bytes:
                    # Existing outfits are always manual mode — save original
                    # black-bg image for user to manually remove background
                    final_path = save_image_bytes_as_png(original_bytes, out_stem)
                    expr_paths[expr_key] = final_path
                    cleanup_dict[expr_key] = (original_bytes, original_bytes)
                    log_info(f"Saved expression {expr_key} to {final_path}")
            except Exception as e:
                log_error("Expression generation", f"Failed to generate expression {expr_key}: {e}")
                # Continue to next expression

        log_generation_complete(f"existing_expressions_{pose_letter}", True, f"Generated {len(expr_paths)} expressions")
        return expr_paths, cleanup_dict

    def _on_existing_outfit_complete(self, outfit_name: str, expr_paths: Dict[str, Path], cleanup_dict: Dict[str, Tuple[bytes, bytes]]) -> None:
        """Handle completion of one existing outfit's expression generation (rolling)."""
        log_info(f"Existing outfit expressions complete: {outfit_name}")

        # Store in state
        if not self.state.expression_paths:
            self.state.expression_paths = {}
        self.state.expression_paths[outfit_name] = expr_paths

        # Store cleanup data for manual BG removal
        self._expression_cleanup_data[outfit_name] = cleanup_dict

        # Update generation status
        self._outfit_gen_status[outfit_name] = "complete"

        if not self._first_outfit_shown:
            # First outfit done — show review UI
            self._first_outfit_shown = True
            self.hide_loading()
            self._outfit_var.set(outfit_name)
            self._show_outfit_expressions()
        else:
            # Subsequent — refresh if user is viewing it
            if self._outfit_var.get() == outfit_name:
                self._show_outfit_expressions()

        # Move to next existing outfit
        self._current_existing_outfit_idx += 1
        self._generate_next_existing_outfit()

    def _on_generation_error(self, error: str, is_single_regen: bool = False) -> None:
        """Handle generation error.

        Args:
            error: Error message.
            is_single_regen: True if this error is from a single-expression
                regen (not from background outfit generation).
        """
        log_generation_complete("expressions", False, error)
        if is_single_regen and self._regenerating_expr is not None:
            # Single-expression regen error — hide card overlay, don't touch background gen
            outfit_name, expr_key = self._regenerating_expr
            self._hide_expr_card_loading(outfit_name, expr_key)
            self._regenerating_expr = None
        else:
            # Background outfit generation error
            self._is_generating = False
            if not self._first_outfit_shown:
                self.hide_loading()
        self._status_label.configure(text=f"Error: {error}", fg=ERROR_TEXT)
        show_error_dialog(self._canvas, "Generation Error", f"Failed to generate expressions:\n\n{error}")

    def _show_outfit_expressions(self) -> None:
        """Display expressions for the currently selected outfit (horizontal layout like outfits).

        If the outfit is still generating or pending, shows an inline loading
        indicator instead of cards. Cards appear when generation completes.
        """
        # Clear existing
        if self._loading_overlay is not None:
            self._loading_overlay.destroy()
            self._loading_overlay = None
        for widget in self._inner_frame.winfo_children():
            widget.destroy()
        self._img_refs.clear()
        self._expr_card_frames.clear()
        self._expr_card_overlays.clear()

        # Reset horizontal scroll to the start
        self._canvas.xview_moveto(0)

        # Update progress indicator
        self._update_progress_indicator()

        outfit_name = self._outfit_var.get()
        if not outfit_name:
            return

        # Check if this outfit's expressions are available yet
        if outfit_name not in self.state.expression_paths:
            # Show loading overlay centered on the canvas (not inside the
            # scrollable inner frame) so it's visible regardless of scroll.
            # All nav buttons (Prev/Next, Back/Cancel) remain fully usable.
            status = self._outfit_gen_status.get(outfit_name, "pending")
            loading_frame = tk.Frame(self._canvas, bg=BG_COLOR)

            if status == "generating":
                tk.Label(
                    loading_frame,
                    text=f"Generating expressions for {outfit_name.capitalize()}...",
                    bg=BG_COLOR, fg=ACCENT_COLOR, font=SECTION_FONT,
                ).pack(pady=(0, 12))
                # Show live progress if available
                if self._current_gen_progress:
                    tk.Label(
                        loading_frame,
                        text=self._current_gen_progress,
                        bg=BG_COLOR, fg=TEXT_SECONDARY, font=BODY_FONT,
                        justify="center",
                    ).pack()
            else:
                tk.Label(
                    loading_frame,
                    text=f"Waiting for {outfit_name.capitalize()}...",
                    bg=BG_COLOR, fg=TEXT_SECONDARY, font=SECTION_FONT,
                ).pack()
                tk.Label(
                    loading_frame,
                    text="Previous outfits are still being generated.",
                    bg=BG_COLOR, fg=TEXT_DISABLED, font=BODY_FONT,
                ).pack(pady=(8, 0))

            # Place as floating overlay centered on the canvas viewport
            loading_frame.place(relx=0.5, rely=0.35, anchor="center")
            self._loading_overlay = loading_frame
            return

        expr_paths = self.state.expression_paths[outfit_name]

        # Size images based on WINDOW height (reliable — set by apply_window_size)
        # instead of canvas height (unreliable — depends on multi-level canvas window
        # chain propagation that doesn't fully resolve even after update()).
        #
        # Overhead breakdown (expression cards have fewer controls than outfits):
        #   Wizard chrome:  header ~50 + footer ~45          =  95
        #   Content padding: content_frame pady 20×2          =  40
        #   Step header:     title ~45 + progress ~45 + tip ~35 = 125
        #   Card chrome:     h-scrollbar ~20 + card pad ~15   =  35
        #   Card controls:   caption + button row             =  70
        #                                              Total ≈ 365
        self._canvas.winfo_toplevel().update()
        win_h = self._canvas.winfo_toplevel().winfo_height()
        max_thumb_h = max(int((win_h - 365) * 0.90), 250)

        # Build horizontal row of cards (like outfits)
        col = 0

        # For existing outfits, show face 0 as non-editable reference first
        # Prefer backup (full-size) over character folder (may be scaled down)
        if outfit_name.startswith("existing_"):
            pose_letter = outfit_name.replace("existing_", "")
            face_0_path = None

            # Priority 1: External backup (full-size, pre-scale)
            backup_id = self.state.backup_id
            if backup_id:
                ext_backup_dir = get_backup_dir(backup_id) / pose_letter / "faces" / "face"
                if ext_backup_dir.is_dir():
                    for ext in [".png", ".webp"]:
                        path = ext_backup_dir / f"0{ext}"
                        if path.exists():
                            face_0_path = path
                            break

            # Priority 2: Legacy in-folder backups
            if not face_0_path and self.state.existing_character_folder:
                legacy_dir = self.state.existing_character_folder / "_backups" / pose_letter / "faces" / "face"
                if legacy_dir.is_dir():
                    for ext in [".png", ".webp"]:
                        path = legacy_dir / f"0{ext}"
                        if path.exists():
                            face_0_path = path
                            break

            # Priority 3: Character folder (may be scaled)
            if not face_0_path and self.state.existing_character_folder:
                for ext in [".png", ".webp"]:
                    path = self.state.existing_character_folder / pose_letter / "faces" / "face" / f"0{ext}"
                    if path.exists():
                        face_0_path = path
                        break

            if face_0_path:
                ref_card = self._build_reference_card(face_0_path, max_thumb_h)
                ref_card.grid(row=0, column=col, padx=10, pady=6)
                col += 1

        # Collect failed expression keys for this outfit
        failed_for_outfit = set()
        if self.state.failed_expressions:
            for (fail_outfit, fail_key) in self.state.failed_expressions:
                if fail_outfit == outfit_name:
                    failed_for_outfit.add(fail_key)

        # Build a combined list of all expression keys (successful + failed) for correct ordering
        all_expr_keys = set(expr_paths.keys()) | failed_for_outfit

        for expr_key in sorted(all_expr_keys, key=lambda x: int(x) if x.isdigit() else 999):
            if expr_key in expr_paths and expr_paths[expr_key].exists():
                card = self._build_expression_card(outfit_name, expr_key, expr_paths[expr_key], max_thumb_h)
            elif expr_key in failed_for_outfit:
                card = self._build_failed_expression_card(outfit_name, expr_key, max_thumb_h)
            else:
                continue
            card.grid(row=0, column=col, padx=10, pady=6)
            self._expr_card_frames[(outfit_name, expr_key)] = card
            col += 1

        # Tell the canvas how tall the cards actually are so the wizard-level
        # scrollbar can detect overflow (cards include image + controls below).
        # Then explicitly notify the wizard — changing the canvas requested height
        # updates _content_frame.winfo_reqheight() but doesn't trigger a <Configure>
        # event (actual size is controlled by the canvas window item, not pack).
        self._inner_frame.update_idletasks()
        self._canvas.configure(height=self._inner_frame.winfo_reqheight())
        if hasattr(self.wizard, '_on_content_configure'):
            self.wizard._on_content_configure()

    def _build_expression_card(self, outfit_name: str, expr_key: str, path: Path, max_h: int) -> tk.Frame:
        """Build a single expression card (matching outfit step style)."""
        card = tk.Frame(self._inner_frame, bg=CARD_BG, padx=6, pady=4)

        # Load image with height constraint (like outfit step)
        # Use bytes from cleanup_data if available (avoids file caching issues after edits)
        try:
            if (outfit_name in self._expression_cleanup_data and
                expr_key in self._expression_cleanup_data[outfit_name]):
                # Use the current (potentially edited) bytes from memory
                _, current_bytes = self._expression_cleanup_data[outfit_name][expr_key]
                img = Image.open(BytesIO(current_bytes)).convert("RGBA")
            else:
                # Fall back to reading from disk
                img = Image.open(BytesIO(path.read_bytes())).convert("RGBA")
            # Scale to fit max height while maintaining aspect ratio
            if img.height > max_h:
                ratio = max_h / img.height
                new_w = int(img.width * ratio)
                img = img.resize((new_w, max_h), Image.LANCZOS)

            # Create white background composite
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            composite = Image.alpha_composite(bg, img)

            tk_img = ImageTk.PhotoImage(composite)
            self._img_refs.append(tk_img)

            img_label = tk.Label(card, image=tk_img, bg=CARD_BG)
            img_label.pack()
        except Exception:
            tk.Label(card, text="Error", bg=CARD_BG, fg=ERROR_TEXT).pack()

        # Get expression description - check session expressions first, then master list
        expr_desc = None
        # First check current session's expressions
        for key, desc in self.state.expressions_sequence:
            if key == expr_key:
                expr_desc = desc
                break
        # Fallback to master expression list (for existing outfits)
        if not expr_desc:
            from ...config import EXPRESSIONS_SEQUENCE
            for key, desc in EXPRESSIONS_SEQUENCE:
                if key == expr_key:
                    expr_desc = desc
                    break

        # Format: "7: Happy" - show number and short emotion name
        if expr_desc:
            # Extract just the emotion keyword (first word or two)
            emotion_words = expr_desc.split()
            if emotion_words:
                # Use first 2-3 words for clarity
                short_emotion = " ".join(emotion_words[:3])
                # Capitalize for display
                short_emotion = short_emotion.capitalize()
                display_text = f"{expr_key}: {short_emotion}"
            else:
                display_text = expr_key
        else:
            display_text = expr_key

        # Caption with expression number and emotion type
        # Use wraplength to allow long text to wrap to multiple lines
        tk.Label(
            card,
            text=display_text,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            wraplength=140,
        ).pack(pady=(2, 2))

        # Buttons row (horizontal like outfits)
        btn_row = tk.Frame(card, bg=CARD_BG)
        btn_row.pack(pady=(2, 0))

        # Expression 0 (neutral) cannot be regenerated - it comes directly from the outfit
        if expr_key != "0":
            # Regenerate button
            create_secondary_button(
                btn_row, "Regen",
                lambda o=outfit_name, e=expr_key: self._regenerate_expression(o, e),
                width=6
            ).pack(side="left", padx=(0, 4))

        # Flip button - works for all expressions including 0
        create_secondary_button(
            btn_row, "Flip",
            lambda o=outfit_name, e=expr_key, p=path: self._flip_expression(o, e, p),
            width=5
        ).pack(side="left", padx=(0, 4))

        # BG removal button - always "Remove BG" for consistency
        create_secondary_button(
            btn_row, "Remove BG",
            lambda o=outfit_name, e=expr_key, p=path: self._open_manual_bg(o, e, p),
            width=10
        ).pack(side="left")

        return card

    def _build_failed_expression_card(self, outfit_name: str, expr_key: str, max_h: int) -> tk.Frame:
        """Build a card for a failed expression with error styling and retry button."""
        card = tk.Frame(self._inner_frame, bg=ERROR_BG, padx=6, pady=4,
                        highlightbackground=ERROR_TEXT, highlightthickness=2)

        # Create a placeholder image (dark gray with X)
        placeholder_w = 120
        placeholder_h = min(max_h, 200)
        placeholder = Image.new("RGBA", (placeholder_w, placeholder_h), (50, 50, 50, 255))
        # Draw an X on it
        from PIL import ImageDraw
        draw = ImageDraw.Draw(placeholder)
        margin = 30
        draw.line([(margin, margin), (placeholder_w - margin, placeholder_h - margin)],
                  fill=(255, 85, 85, 255), width=3)
        draw.line([(placeholder_w - margin, margin), (margin, placeholder_h - margin)],
                  fill=(255, 85, 85, 255), width=3)
        # Add "FAILED" text
        try:
            draw.text((placeholder_w // 2, placeholder_h // 2 + 20), "FAILED",
                       fill=(255, 85, 85, 255), anchor="mm")
        except Exception:
            pass  # Font anchor may not be available in older Pillow

        tk_img = ImageTk.PhotoImage(placeholder)
        self._img_refs.append(tk_img)

        img_label = tk.Label(card, image=tk_img, bg=ERROR_BG)
        img_label.pack()

        # Get expression description
        expr_desc = None
        for key, desc in self.state.expressions_sequence:
            if key == expr_key:
                expr_desc = desc
                break
        if not expr_desc:
            from ...config import EXPRESSIONS_SEQUENCE
            for key, desc in EXPRESSIONS_SEQUENCE:
                if key == expr_key:
                    expr_desc = desc
                    break

        if expr_desc:
            emotion_words = expr_desc.split()
            short_emotion = " ".join(emotion_words[:3]).capitalize() if emotion_words else expr_key
            display_text = f"{expr_key}: {short_emotion}"
        else:
            display_text = expr_key

        tk.Label(
            card, text=display_text,
            bg=ERROR_BG, fg=ERROR_TEXT, font=BODY_FONT, wraplength=140,
        ).pack(pady=(2, 0))

        tk.Label(
            card, text="Generation failed",
            bg=ERROR_BG, fg=ERROR_TEXT, font=SMALL_FONT,
        ).pack(pady=(0, 2))

        # Regen button to retry
        btn_row = tk.Frame(card, bg=ERROR_BG)
        btn_row.pack(pady=(2, 0))

        create_secondary_button(
            btn_row, "Retry",
            lambda o=outfit_name, e=expr_key: self._regenerate_expression(o, e),
            width=6
        ).pack(side="left")

        return card

    def _build_reference_card(self, path: Path, max_h: int) -> tk.Frame:
        """Build a non-editable reference card showing face 0 for existing outfits."""
        # Darker background to indicate non-editable
        card = tk.Frame(self._inner_frame, bg=CARD_BG, padx=6, pady=4)

        try:
            img = Image.open(path).convert("RGBA")
            # Scale to fit max height while maintaining aspect ratio
            if img.height > max_h:
                ratio = max_h / img.height
                new_w = int(img.width * ratio)
                img = img.resize((new_w, max_h), Image.LANCZOS)

            # Create white background composite
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            composite = Image.alpha_composite(bg, img)

            tk_img = ImageTk.PhotoImage(composite)
            self._img_refs.append(tk_img)

            img_label = tk.Label(card, image=tk_img, bg=CARD_BG)
            img_label.pack()
        except Exception:
            tk.Label(card, text="Error", bg=CARD_BG, fg=ERROR_TEXT).pack()

        # Caption indicating this is a reference
        tk.Label(
            card,
            text="0: Reference",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        ).pack(pady=(2, 2))

        # No buttons - this is read-only
        tk.Label(
            card,
            text="(existing)",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        ).pack()

        return card

    def _get_bg_mode_for_outfit(self, outfit_name: str) -> str:
        """Get the background removal mode for an outfit.

        For existing outfits (add-to-character mode), uses outfit_name as key.
        For regular outfits, uses numeric index.

        Returns:
            "rembg" for auto removal, "manual" for manual removal.
        """
        # For existing outfits (add-to-character), always use manual mode.
        # There are no saved tolerance/depth settings, so auto (rembg) is useless.
        if outfit_name.startswith("existing_"):
            return "manual"

        # For regular outfits, use numeric index
        outfit_names = self._get_outfit_names()
        outfit_idx = outfit_names.index(outfit_name) if outfit_name in outfit_names else 0
        return self.state.outfit_bg_modes.get(outfit_idx, "rembg")

    def _toggle_existing_bg_mode(self, outfit_name: str, expr_key: str) -> None:
        """Toggle between auto/manual BG removal mode for an existing outfit expression.

        When toggling to manual mode, reverts the expression to original Gemini output.
        When toggling to auto mode, applies rembg to get the processed version.
        """
        if not outfit_name.startswith("existing_"):
            return

        # Get current mode and cleanup data
        current_mode = self.state.outfit_bg_modes.get(outfit_name, "rembg")
        cleanup_data = self._expression_cleanup_data.get(outfit_name, {}).get(expr_key)

        if not cleanup_data:
            # Fallback: generate cleanup data from the file on disk
            expr_path = self.state.expression_paths.get(outfit_name, {}).get(expr_key)
            if not expr_path or not expr_path.exists():
                messagebox.showinfo("Toggle Mode", "No image file available for this expression.")
                return
            try:
                from ...api.gemini_client import strip_background_ai
                with open(expr_path, "rb") as f:
                    orig_bytes = f.read()
                rembg_bytes = strip_background_ai(orig_bytes)
                cleanup_data = (orig_bytes, rembg_bytes)
                if outfit_name not in self._expression_cleanup_data:
                    self._expression_cleanup_data[outfit_name] = {}
                self._expression_cleanup_data[outfit_name][expr_key] = cleanup_data
            except Exception as e:
                messagebox.showerror("Error", f"Could not prepare image for mode toggle: {e}")
                return

        original_bytes, rembg_bytes = cleanup_data

        # Toggle the mode
        new_mode = "manual" if current_mode == "rembg" else "rembg"
        self.state.outfit_bg_modes[outfit_name] = new_mode

        # Get the new bytes based on mode
        if new_mode == "manual":
            # Use original Gemini output (black background)
            new_bytes = original_bytes
        else:
            # Use rembg processed version
            new_bytes = rembg_bytes

        # Write to disk
        expr_path = self.state.expression_paths.get(outfit_name, {}).get(expr_key)
        if expr_path and expr_path.exists():
            try:
                expr_path.write_bytes(new_bytes)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update expression file: {e}")
                return

        # Refresh display
        self._show_outfit_expressions()
        mode_name = "manual (raw Gemini output)" if new_mode == "manual" else "auto (rembg processed)"
        self._status_label.configure(text=f"Switched expression {expr_key} to {mode_name}.")

    def _show_expr_card_loading(self, outfit_name: str, expr_key: str, message: str = "Regenerating...") -> None:
        """Show a loading overlay on a specific expression card."""
        key = (outfit_name, expr_key)
        if key not in self._expr_card_frames:
            return

        card = self._expr_card_frames[key]

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
            wraplength=150,
        ).place(relx=0.5, rely=0.5, anchor="center")

        self._expr_card_overlays[key] = overlay

    def _hide_expr_card_loading(self, outfit_name: str, expr_key: str) -> None:
        """Hide the loading overlay on a specific expression card."""
        key = (outfit_name, expr_key)
        if key in self._expr_card_overlays:
            try:
                self._expr_card_overlays[key].destroy()
            except tk.TclError:
                pass
            del self._expr_card_overlays[key]

    def _regenerate_expression(self, outfit_name: str, expr_key: str) -> None:
        """Regenerate a single expression.

        Allowed during background generation if the target outfit is already
        complete (different outfit is generating). Blocked only when the same
        outfit is currently being generated, or another single-expression regen
        is already in progress.
        """
        # Block if a single-expression regen is already running
        if self._regenerating_expr is not None:
            return

        # Block if THIS outfit is currently being generated in the background
        if self._is_generating and self._current_gen_outfit == outfit_name:
            return

        self._regenerating_expr = (outfit_name, expr_key)
        self._status_label.configure(text=f"Regenerating expression {expr_key}...")
        # Use per-card loading instead of full-screen overlay
        self._show_expr_card_loading(outfit_name, expr_key, "Regenerating\nexpression...")

        def regenerate():
            try:
                new_path, orig_bytes, rembg_bytes = self._do_single_expression_regen(outfit_name, expr_key)
                self.schedule_callback(
                    lambda o=outfit_name, e=expr_key, p=new_path, ob=orig_bytes, rb=rembg_bytes:
                        self._on_single_expr_complete(o, e, p, ob, rb)
                )
            except Exception as e:
                error_msg = str(e)
                self.schedule_callback(lambda msg=error_msg: self._on_generation_error(msg, is_single_regen=True))

        thread = threading.Thread(target=regenerate, daemon=True)
        thread.start()

    def _do_single_expression_regen(self, outfit_name: str, expr_key: str) -> Tuple[Path, Optional[bytes], Optional[bytes]]:
        """Regenerate a single expression.

        Returns:
            Tuple of (path, original_bytes, rembg_bytes). For existing outfits, all three
            are populated. For regular outfits, original_bytes and rembg_bytes are None.
        """
        from ...processing import regenerate_single_expression
        from ...api.gemini_client import load_image_as_base64, call_gemini_image_edit
        from ...api.prompt_builders import build_expression_prompt
        from ...processing.image_utils import save_image_bytes_as_png

        # Check if this is an existing outfit (add-to-existing mode)
        if outfit_name.startswith("existing_"):
            pose_letter = outfit_name.replace("existing_", "")
            char_folder = self.state.existing_character_folder
            faces_dir = char_folder / pose_letter / "faces" / "face"

            # Find base image (face 0 or 1)
            base_path = None
            for expr_num in ["0", "1"]:
                for ext in [".png", ".webp"]:
                    test_path = faces_dir / f"{expr_num}{ext}"
                    if test_path.exists():
                        base_path = test_path
                        break
                if base_path:
                    break

            if not base_path:
                raise ValueError(f"No base expression found in {faces_dir}")

            # Get expression description from MASTER list (for existing outfits)
            from ...config import EXPRESSIONS_SEQUENCE
            expr_desc = None
            # First check master list
            for key, desc in EXPRESSIONS_SEQUENCE:
                if key == expr_key:
                    expr_desc = desc
                    break
            # Then check current session's expressions (for custom expressions)
            if not expr_desc:
                for key, desc in self.state.expressions_sequence:
                    if key == expr_key:
                        expr_desc = desc
                        break

            if not expr_desc:
                raise ValueError(f"Expression {expr_key} not found in master list or session expressions")

            # Generate the expression
            image_b64 = load_image_as_base64(base_path)
            background_color = "solid black (#000000)"
            # Use add_to_existing=True for upscale instruction since source is already scaled
            prompt = build_expression_prompt(expr_desc, background_color, add_to_existing=True, archetype_label=self.state.archetype_label)

            original_bytes = call_gemini_image_edit(
                self.state.api_key, prompt, image_b64,
                skip_background_removal=True,
            )

            if original_bytes:
                # Existing outfits are always manual mode — save original
                # black-bg image for user to manually remove background
                out_stem = faces_dir / expr_key
                new_path = save_image_bytes_as_png(original_bytes, out_stem)
                return (new_path, original_bytes, original_bytes)
            else:
                raise ValueError(f"Failed to generate expression {expr_key}")

        # Regular outfit (not existing) - use standard regeneration
        outfit_names = self._get_outfit_names()
        # Filter to only new outfits for indexing
        new_outfit_names = [n for n in outfit_names if not n.startswith("existing_")]
        idx = new_outfit_names.index(outfit_name)
        outfit_path = self.state.outfit_paths[idx]

        # Determine output directory — use outfit_path.stem to match the folder
        # name created by initial generation (expression_generator.py uses
        # outfit_path.stem). Using the dropdown key (outfit_name) can differ in
        # case (e.g. "formal" vs "Formal") which creates a separate directory on
        # case-sensitive filesystems (Linux), orphaning the regenerated file.
        if self.state.is_adding_to_existing:
            pose_letter = self.state.next_pose_letter or "a"
        else:
            pose_letter = "a"
        pose_dir = self.state.character_folder / pose_letter
        outfit_stem = outfit_path.stem
        if outfit_stem.lower() == "base":
            out_dir = pose_dir / "faces" / "face"
        else:
            out_dir = pose_dir / "faces" / outfit_stem

        # Get cleanup settings from outfit review (if available)
        edge_cleanup_tolerance = None
        edge_cleanup_passes = None
        if self.state.outfit_cleanup_settings and idx < len(self.state.outfit_cleanup_settings):
            edge_cleanup_tolerance, edge_cleanup_passes = self.state.outfit_cleanup_settings[idx]

        # Get bg removal mode from outfit review
        bg_removal_mode = self._get_bg_mode_for_outfit(outfit_name)

        new_path = regenerate_single_expression(
            api_key=self.state.api_key,
            outfit_path=outfit_path,
            out_dir=out_dir,
            expressions_sequence=self.state.expressions_sequence,
            expr_key=expr_key,  # Pass the key directly (e.g., "7", "14")
            edge_cleanup_tolerance=edge_cleanup_tolerance,
            edge_cleanup_passes=edge_cleanup_passes,
            bg_removal_mode=bg_removal_mode,
            archetype_label=self.state.archetype_label,
        )

        # Regular outfits don't return cleanup data
        return (new_path, None, None)

    def _on_single_expr_complete(
        self, outfit_name: str, expr_key: str, new_path: Path,
        original_bytes: Optional[bytes] = None, rembg_bytes: Optional[bytes] = None
    ) -> None:
        """Handle single expression regeneration completion."""
        self._hide_expr_card_loading(outfit_name, expr_key)
        self._regenerating_expr = None

        # Update state - ensure the outfit dict exists for retry of failed expressions
        if outfit_name not in self.state.expression_paths:
            self.state.expression_paths[outfit_name] = {}
        self.state.expression_paths[outfit_name][expr_key] = new_path

        # Remove from failed expressions if it was there (successful retry)
        if self.state.failed_expressions:
            self.state.failed_expressions.discard((outfit_name, expr_key))

        # Update cleanup data
        if original_bytes is not None and rembg_bytes is not None:
            # Store new cleanup data (existing outfits provide this)
            if outfit_name not in self._expression_cleanup_data:
                self._expression_cleanup_data[outfit_name] = {}
            self._expression_cleanup_data[outfit_name][expr_key] = (original_bytes, rembg_bytes)
        else:
            # Clear cached bytes so display reads the new file from disk (regular outfits)
            if outfit_name in self._expression_cleanup_data:
                if expr_key in self._expression_cleanup_data[outfit_name]:
                    del self._expression_cleanup_data[outfit_name][expr_key]

        # Refresh display
        self._show_outfit_expressions()
        self._status_label.configure(text=f"Expression {expr_key} regenerated.")

    def _flip_expression(self, outfit_name: str, expr_key: str, path: Path) -> None:
        """Flip an expression image horizontally."""
        # Load image bytes from cleanup data or disk
        if (outfit_name in self._expression_cleanup_data and
            expr_key in self._expression_cleanup_data[outfit_name]):
            original_bytes, current_bytes = self._expression_cleanup_data[outfit_name][expr_key]
        else:
            current_bytes = path.read_bytes()
            original_bytes = current_bytes

        # Flip the image using PIL
        img = Image.open(BytesIO(current_bytes)).convert("RGBA")
        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)

        # Save back to bytes
        buf = BytesIO()
        flipped.save(buf, format="PNG")
        flipped_bytes = buf.getvalue()

        # Update cleanup data (keep original for potential future use)
        if outfit_name not in self._expression_cleanup_data:
            self._expression_cleanup_data[outfit_name] = {}
        self._expression_cleanup_data[outfit_name][expr_key] = (original_bytes, flipped_bytes)

        # Write to disk
        path.write_bytes(flipped_bytes)

        # Refresh display
        self._show_outfit_expressions()
        self._status_label.configure(text=f"Expression {expr_key} flipped.")

    def _open_manual_bg(self, outfit_name: str, expr_key: str, path: Path) -> None:
        """Open manual background removal for an expression."""
        # Block if THIS outfit is currently generating, but allow for completed outfits
        if self._is_generating and self._current_gen_outfit == outfit_name:
            return

        # Get original black-bg bytes from stored cleanup data
        if outfit_name not in self._expression_cleanup_data:
            self._expression_cleanup_data[outfit_name] = {}

        cleanup_data = self._expression_cleanup_data[outfit_name].get(expr_key)
        if not cleanup_data:
            # Fallback: generate cleanup data from the file on disk
            try:
                from ...api.gemini_client import strip_background_ai
                with open(path, "rb") as f:
                    orig_bytes = f.read()
                rembg_bytes = strip_background_ai(orig_bytes)
                cleanup_data = (orig_bytes, rembg_bytes)
                self._expression_cleanup_data[outfit_name][expr_key] = cleanup_data
            except Exception as e:
                messagebox.showerror("Error", f"Could not prepare image for manual BG edit: {e}")
                return

        original_bytes, rembg_bytes = cleanup_data

        # Determine which bytes to use based on outfit's BG mode
        # "Touch Up" mode (rembg): Start from rembg result, so Restart goes back to rembg output
        # "Remove BG" mode (manual): Start from original black-bg, so Restart goes back to original
        bg_mode = self._get_bg_mode_for_outfit(outfit_name)

        if bg_mode == "rembg":
            # Touch Up mode: use rembg result as starting point
            working_bytes = rembg_bytes
        else:
            # Manual mode: use original black-bg as starting point
            working_bytes = original_bytes

        # Verify bytes are valid
        if not working_bytes or len(working_bytes) < 100:
            messagebox.showerror("Error", "Image data is missing or invalid.")
            return

        # Check if the expression file path still exists (may have been moved by flattening)
        if not path.exists():
            log_error("Manual BG removal", f"Expression file no longer exists: {path}")
            messagebox.showerror(
                "File Not Found",
                f"The expression file no longer exists at:\n{path}\n\n"
                "This can happen if you navigated back after the character was finalized. "
                "The folder structure may have changed."
            )
            return

        # Write to temp file for manual editing - use a safe temp location
        # Use the expression file's directory if it exists
        temp_dir = path.parent
        if not temp_dir.exists():
            log_error("Manual BG removal", f"Directory no longer exists: {temp_dir}")
            messagebox.showerror(
                "Directory Not Found",
                f"The directory no longer exists:\n{temp_dir}\n\n"
                "This can happen if you navigated back after the character was finalized."
            )
            return

        temp_path = temp_dir / f"_temp_manual_{expr_key}.png"

        try:
            temp_path.write_bytes(working_bytes)
            log_info(f"Wrote temp file for manual BG edit: {temp_path} ({len(working_bytes)} bytes)")
        except Exception as e:
            log_error("Manual BG removal", f"Failed to write temp file: {e}")
            messagebox.showerror("Error", f"Failed to create temp file:\n{e}")
            return

        # Verify temp file was written
        if not temp_path.exists():
            log_error("Manual BG removal", "Temp file doesn't exist after writing")
            messagebox.showerror("Error", "Failed to create temp file for editing.")
            return

        from ..review_windows import click_to_remove_background
        accepted = click_to_remove_background(temp_path, threshold=30)

        if accepted:
            # Verify temp file still exists after editor closed
            if not temp_path.exists():
                log_error("Manual BG removal", f"Temp file missing after editor closed: {temp_path}")
                messagebox.showerror(
                    "Error",
                    "The edited file could not be found after the editor closed.\n"
                    "Please try again."
                )
                return

            # Read edited bytes from temp file
            try:
                edited_bytes = temp_path.read_bytes()
            except Exception as e:
                log_error("Manual BG removal", f"Failed to read temp file: {e}")
                messagebox.showerror("Error", f"Failed to read edited image:\n{e}")
                return

            # Verify we got valid edited bytes
            if not edited_bytes or len(edited_bytes) < 100:
                log_error("Manual BG removal", "Failed to read edited image - bytes empty or too small")
                messagebox.showerror("Error", "Failed to read edited image from temp file.")
                return

            # Write to the expression file on disk
            try:
                path.write_bytes(edited_bytes)
                log_info(f"Saved manually edited BG for {outfit_name}/{expr_key} ({len(edited_bytes)} bytes)")
            except Exception as e:
                log_error("Manual BG removal", f"Failed to save edited image: {e}")
                messagebox.showerror("Error", f"Failed to save edited image:\n{e}")
                return

            # Update cleanup data with edited result (keep original for future Restart, update current display bytes)
            self._expression_cleanup_data[outfit_name][expr_key] = (original_bytes, edited_bytes)

            # Force complete UI refresh - schedule it after the modal fully closes
            # This ensures the modal window is destroyed before we try to rebuild cards
            def refresh_display():
                # Clear and rebuild all expression cards
                self._show_outfit_expressions()
                # Force canvas to fully update
                self._canvas.update()
                self._inner_frame.update()
                self._status_label.configure(text=f"Manual BG removal applied to expression {expr_key}.")
                log_info(f"UI refreshed after manual BG edit for {expr_key}")

            # Use after(50) to let the modal window fully close before refreshing
            self.wizard.root.after(50, refresh_display)

        # Clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass  # Ignore cleanup errors

    def _on_regenerate_all(self) -> None:
        """Regenerate all expressions."""
        result = messagebox.askyesno(
            "Regenerate All",
            "This will regenerate all expressions for all outfits. Continue?"
        )
        if result:
            self.state.expression_paths = {}
            self._start_expression_generation()

    def _on_accept(self) -> None:
        """Accept all expressions."""
        if self._is_generating:
            messagebox.showwarning("Generation in Progress", "Please wait for generation to complete.")
            return

        self.request_next()

    def validate(self) -> bool:
        """Validate before advancing."""
        if self._is_generating:
            messagebox.showwarning("Generation in Progress", "Please wait for generation to complete.")
            return False

        if not self.state.expression_paths:
            messagebox.showerror("No Expressions", "No expressions have been generated.")
            return False

        # Check all outfits have been viewed
        outfit_names = self._get_outfit_names()
        if len(self._viewed_outfits) < len(outfit_names):
            unviewed = [name for name in outfit_names if name not in self._viewed_outfits]
            messagebox.showwarning(
                "Review All Outfits",
                f"Please review expressions for all outfits before continuing.\n\n"
                f"Not yet viewed: {', '.join(unviewed)}"
            )
            return False

        return True
