"""
Fusion wizard step.

Allows users to select two character images and merge them into a new character
using AI. Settings (voice/name/archetype) are collected here before fusion.
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional
from io import BytesIO

from PIL import Image, ImageTk

from ...config import (
    NAMES_CSV_PATH,
    GENDER_ARCHETYPES,
    BACKGROUND_COLOR_PRESETS,
    load_background_color,
    save_background_color,
    BG_COLOR,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    ERROR_TEXT,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
)
from ..tk_common import (
    create_primary_button,
    create_secondary_button,
)
from ..dialogs import load_name_pool, pick_random_name
from .base import WizardStep, WizardState
from ...api.exceptions import GeminiSafetyError
from ...logging_utils import log_info, log_error


# Image slot size (larger for better visibility)
SLOT_WIDTH = 420
SLOT_HEIGHT = 520


class FusionStep(WizardStep):
    """Step for character fusion - merges two images into a new character."""

    STEP_ID = "fusion"
    STEP_TITLE = "Fusion"
    STEP_TIP = (
        "Select two character images and fill in the settings, then click FUSION! "
        "to merge them into a new character. You can regenerate until you're happy with the result."
    )
    STEP_HELP = """Character Fusion

This step allows you to create a new character by merging two existing characters.

IMAGE SELECTION
Click the left and right image slots to browse for character images.
These will be combined to create a new fused character.

Tips for best results:
• Use images with similar art styles
• Characters with clear, visible features work best
• Front-facing poses produce more predictable results

SETTINGS
- Voice: Determines name pool and available archetypes
- Name: The character's name for the final output
- Archetype: Affects outfit generation style
- Hair Length (Girl voice only): Controls hair length in generated outfits

FUSION
Click the "FUSION!" button to generate the merged character.
You can regenerate multiple times until satisfied with the result.

The fused character will have:
- Combined visual features from both input images
- A solid background (ready for sprite processing)
- Art style matching the input images

WHAT HAPPENS NEXT
After clicking Next, you'll go to the Setup step where you can:
- Crop the image to mid-thigh level
- Optionally modify the fused character further
- No normalization is needed (fusion already has a solid background)

TROUBLESHOOTING
"Fusion button is disabled"
→ Make sure you've selected both images AND filled all settings

"Fusion failed" or error message
→ Try different source images with clearer features
→ Ensure images aren't too small (at least 512px recommended)
→ Check your API key is valid in the launcher settings

"Result doesn't look like either character"
→ Click FUSION! again - results vary each time
→ Try images with more distinct, prominent features"""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)

        # Settings variables
        self._voice_var: Optional[tk.StringVar] = None
        self._name_var: Optional[tk.StringVar] = None
        self._arch_var: Optional[tk.StringVar] = None
        self._arch_menu: Optional[tk.OptionMenu] = None
        self._hair_var: Optional[tk.StringVar] = None
        self._hair_frame: Optional[tk.Frame] = None
        self._hair_menu: Optional[tk.OptionMenu] = None
        self._bg_color_var: Optional[tk.StringVar] = None
        self._voice_indicator: Optional[tk.Label] = None
        self._name_entry: Optional[tk.Entry] = None

        # Image references (prevent GC)
        self._left_tk_img: Optional[ImageTk.PhotoImage] = None
        self._right_tk_img: Optional[ImageTk.PhotoImage] = None
        self._result_tk_img: Optional[ImageTk.PhotoImage] = None

        # Image labels for display
        self._left_label: Optional[tk.Label] = None
        self._right_label: Optional[tk.Label] = None
        self._result_label: Optional[tk.Label] = None

        # Status and buttons
        self._status_label: Optional[tk.Label] = None
        self._fusion_btn: Optional[tk.Button] = None

        # State
        self._is_generating: bool = False

        # Load name pools
        self._girl_names, self._boy_names = load_name_pool(NAMES_CSV_PATH)

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Character Fusion",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 8))

        self._build_tip_bar(parent)

        # Settings section (top)
        self._build_settings_section(parent)

        # Images section (middle)
        self._build_images_section(parent)

        # Fusion button and status (bottom)
        self._build_control_section(parent)

    def _build_settings_section(self, parent: tk.Frame) -> None:
        """Build the settings form (voice/name/archetype)."""
        settings_card = tk.Frame(parent, bg=CARD_BG, padx=30, pady=20)
        settings_card.pack(fill="x", padx=40, pady=(0, 20))

        tk.Label(
            settings_card,
            text="Configure the new character's settings",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        ).pack(pady=(0, 16))

        # Row container for all settings
        row_frame = tk.Frame(settings_card, bg=CARD_BG)
        row_frame.pack()

        # Voice selection
        voice_frame = tk.Frame(row_frame, bg=CARD_BG)
        voice_frame.pack(side="left", padx=(0, 30))

        tk.Label(
            voice_frame,
            text="Voice:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._voice_var = tk.StringVar(value="")

        girl_btn = create_secondary_button(
            voice_frame, "Girl", lambda: self._set_voice("girl"), width=8
        )
        girl_btn.pack(side="left", padx=(0, 4))

        boy_btn = create_secondary_button(
            voice_frame, "Boy", lambda: self._set_voice("boy"), width=8
        )
        boy_btn.pack(side="left")

        self._voice_indicator = tk.Label(
            voice_frame,
            text="",
            bg=CARD_BG,
            fg=ACCENT_COLOR,
            font=SMALL_FONT,
        )
        self._voice_indicator.pack(side="left", padx=(8, 0))

        # Name entry
        name_frame = tk.Frame(row_frame, bg=CARD_BG)
        name_frame.pack(side="left", padx=(0, 30))

        tk.Label(
            name_frame,
            text="Name:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._name_var = tk.StringVar(value="")
        self._name_entry = tk.Entry(
            name_frame,
            textvariable=self._name_var,
            font=BODY_FONT,
            width=18,
            bg="#1E1E1E",
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
        )
        self._name_entry.pack(side="left")

        # Archetype selection
        arch_frame = tk.Frame(row_frame, bg=CARD_BG)
        arch_frame.pack(side="left")

        tk.Label(
            arch_frame,
            text="Archetype:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._arch_var = tk.StringVar(value="")
        self._arch_menu = tk.OptionMenu(arch_frame, self._arch_var, "")
        self._arch_menu.configure(width=15, bg="#1E1E1E", fg=TEXT_COLOR)
        self._arch_menu.pack(side="left")

        # Hair length selection (girl voice only)
        HAIR_LENGTHS = ["Super Short", "Short", "Medium", "Long", "Super Long"]

        self._hair_frame = tk.Frame(row_frame, bg=CARD_BG)
        # Don't pack yet - visibility controlled by _update_hair_length_visibility

        tk.Label(
            self._hair_frame,
            text="Hair Length:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._hair_var = tk.StringVar(value="")
        self._hair_var.trace_add("write", lambda *_: self._update_fusion_button())
        self._hair_menu = tk.OptionMenu(self._hair_frame, self._hair_var, *HAIR_LENGTHS)
        self._hair_menu.configure(width=15, bg="#1E1E1E", fg=TEXT_COLOR)
        self._hair_menu.pack(side="left")

        # Background color selection (same row)
        bg_frame = tk.Frame(row_frame, bg=CARD_BG)
        bg_frame.pack(side="left", padx=(30, 0))

        tk.Label(
            bg_frame,
            text="BG:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
        ).pack(side="left", padx=(0, 8))

        self._bg_color_var = tk.StringVar(value=load_background_color())
        bg_color_menu = tk.OptionMenu(bg_frame, self._bg_color_var, *BACKGROUND_COLOR_PRESETS)
        bg_color_menu.configure(width=20, bg="#1E1E1E", fg=TEXT_COLOR)
        bg_color_menu.pack(side="left")

        tk.Label(
            bg_frame, text="Avoid your character's colors",
            bg=CARD_BG, fg=TEXT_SECONDARY, font=SMALL_FONT,
        ).pack(side="left", padx=(8, 0))

    def _build_images_section(self, parent: tk.Frame) -> None:
        """Build the image slots section."""
        images_frame = tk.Frame(parent, bg=BG_COLOR)
        images_frame.pack(fill="both", expand=True, padx=40)

        # Left image slot
        left_frame = tk.Frame(images_frame, bg=CARD_BG, padx=10, pady=10)
        left_frame.pack(side="left", padx=(0, 20))

        tk.Label(
            left_frame,
            text="Left Character",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 8))

        # Use a frame container for fixed pixel size
        left_slot = tk.Frame(left_frame, bg="#1E1E1E", width=SLOT_WIDTH, height=SLOT_HEIGHT)
        left_slot.pack_propagate(False)  # Prevent resizing
        left_slot.pack()

        self._left_label = tk.Label(
            left_slot,
            text="Click to\nbrowse...",
            bg="#1E1E1E",
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
            cursor="hand2",
        )
        self._left_label.pack(expand=True)
        self._left_label.bind("<Button-1>", lambda e: self._browse_left())
        left_slot.bind("<Button-1>", lambda e: self._browse_left())

        # Result image slot (center)
        result_frame = tk.Frame(images_frame, bg=CARD_BG, padx=10, pady=10)
        result_frame.pack(side="left", expand=True)

        tk.Label(
            result_frame,
            text="Fused Result",
            bg=CARD_BG,
            fg=ACCENT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 8))

        # Use a frame container for fixed pixel size
        result_slot = tk.Frame(result_frame, bg="#1E1E1E", width=SLOT_WIDTH, height=SLOT_HEIGHT)
        result_slot.pack_propagate(False)  # Prevent resizing
        result_slot.pack()

        self._result_label = tk.Label(
            result_slot,
            text="Result will\nappear here",
            bg="#1E1E1E",
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        )
        self._result_label.pack(expand=True)

        # Right image slot
        right_frame = tk.Frame(images_frame, bg=CARD_BG, padx=10, pady=10)
        right_frame.pack(side="right", padx=(20, 0))

        tk.Label(
            right_frame,
            text="Right Character",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=SECTION_FONT,
        ).pack(pady=(0, 8))

        # Use a frame container for fixed pixel size
        right_slot = tk.Frame(right_frame, bg="#1E1E1E", width=SLOT_WIDTH, height=SLOT_HEIGHT)
        right_slot.pack_propagate(False)  # Prevent resizing
        right_slot.pack()

        self._right_label = tk.Label(
            right_slot,
            text="Click to\nbrowse...",
            bg="#1E1E1E",
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
            cursor="hand2",
        )
        self._right_label.pack(expand=True)
        self._right_label.bind("<Button-1>", lambda e: self._browse_right())
        right_slot.bind("<Button-1>", lambda e: self._browse_right())

    def _build_control_section(self, parent: tk.Frame) -> None:
        """Build the fusion button and status area."""
        control_frame = tk.Frame(parent, bg=BG_COLOR)
        control_frame.pack(fill="x", padx=40, pady=(20, 0))

        # Fusion button (centered)
        self._fusion_btn = create_primary_button(
            control_frame,
            "FUSION!",
            self._run_fusion,
            width=20,
            large=True,
        )
        self._fusion_btn.pack()

        # Status label
        self._status_label = tk.Label(
            control_frame,
            text="Select two images and fill in settings to begin",
            bg=BG_COLOR,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._status_label.pack(pady=(10, 0))

    def _set_voice(self, voice: str) -> None:
        """Handle voice selection."""
        self._voice_var.set(voice)
        self.state.voice = voice
        self._voice_indicator.configure(text=f"({voice.capitalize()})")

        # Update archetype menu
        self._update_archetype_menu()

        # Update hair length visibility
        self._update_hair_length_visibility()

        # Set random name if empty
        if not self._name_var.get().strip():
            name = pick_random_name(voice, self._girl_names, self._boy_names)
            self._name_var.set(name)

        self._name_entry.focus_set()
        self._update_fusion_button()

    def _update_hair_length_visibility(self) -> None:
        """Show hair length dropdown for girl voice, hide for boy."""
        voice = self._voice_var.get() if self._voice_var else ""
        if voice == "girl":
            self._hair_frame.pack(side="left", padx=(30, 0))
        else:
            self._hair_frame.pack_forget()
            self._hair_var.set("")

    def _update_archetype_menu(self) -> None:
        """Update archetype menu based on voice."""
        menu = self._arch_menu["menu"]
        menu.delete(0, "end")

        voice = self._voice_var.get()
        if voice == "girl":
            labels = [label for (label, g) in GENDER_ARCHETYPES if g == "f"]
            self.state.gender_style = "f"
        elif voice == "boy":
            labels = [label for (label, g) in GENDER_ARCHETYPES if g == "m"]
            self.state.gender_style = "m"
        else:
            labels = []
            self.state.gender_style = ""

        self._arch_var.set(labels[0] if labels else "")
        for lbl in labels:
            menu.add_command(label=lbl, command=lambda v=lbl: self._arch_var.set(v))

    def _browse_left(self) -> None:
        """Browse for left character image."""
        path = filedialog.askopenfilename(
            title="Select Left Character Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.state.fusion_left_path = Path(path)
            self._display_image(Path(path), "left")
            self._update_fusion_button()

    def _browse_right(self) -> None:
        """Browse for right character image."""
        path = filedialog.askopenfilename(
            title="Select Right Character Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.state.fusion_right_path = Path(path)
            self._display_image(Path(path), "right")
            self._update_fusion_button()

    def _display_image(self, path: Path, slot: str) -> None:
        """Display an image in the specified slot."""
        try:
            img = Image.open(path).convert("RGBA")

            # Resize to fit slot while maintaining aspect ratio
            img.thumbnail((SLOT_WIDTH, SLOT_HEIGHT), Image.Resampling.LANCZOS)

            # Create PhotoImage
            tk_img = ImageTk.PhotoImage(img)

            # Update the appropriate label
            if slot == "left":
                self._left_tk_img = tk_img
                self._left_label.configure(image=tk_img, text="")
            elif slot == "right":
                self._right_tk_img = tk_img
                self._right_label.configure(image=tk_img, text="")
            elif slot == "result":
                self._result_tk_img = tk_img
                self._result_label.configure(image=tk_img, text="")

        except Exception as e:
            log_error("FusionStep", f"Failed to load image: {e}")
            messagebox.showerror("Error", f"Failed to load image:\n{e}")

    def _update_fusion_button(self) -> None:
        """Update fusion button state based on whether all inputs are ready."""
        has_left = self.state.fusion_left_path is not None
        has_right = self.state.fusion_right_path is not None
        has_voice = bool(self._voice_var.get())
        has_name = bool(self._name_var.get().strip())
        has_arch = bool(self._arch_var.get())
        has_hair = self._voice_var.get() != "girl" or bool(self._hair_var.get())
        has_result = self.state.fusion_result_image is not None

        if has_left and has_right and has_voice and has_name and has_arch and has_hair:
            self._fusion_btn.configure(state="normal")
            if has_result:
                # Fusion already done - user can proceed or re-fuse
                self._status_label.configure(
                    text="Fusion complete! Click Next to continue, or FUSION! to regenerate.",
                    fg=ACCENT_COLOR,
                )
            else:
                self._status_label.configure(
                    text="Ready to fuse! Click FUSION! to generate.",
                    fg=TEXT_SECONDARY,
                )
        else:
            self._fusion_btn.configure(state="disabled")
            missing = []
            if not has_left:
                missing.append("left image")
            if not has_right:
                missing.append("right image")
            if not has_voice:
                missing.append("voice")
            if not has_name:
                missing.append("name")
            if not has_arch:
                missing.append("archetype")
            if not has_hair:
                missing.append("hair length")
            self._status_label.configure(text=f"Missing: {', '.join(missing)}", fg=TEXT_SECONDARY)

    def _run_fusion(self) -> None:
        """Start the fusion process in a background thread."""
        if self._is_generating:
            return

        # Save settings to state
        self.state.voice = self._voice_var.get()
        self.state.display_name = self._name_var.get().strip()
        self.state.archetype_label = self._arch_var.get()
        self.state.hair_length = self._hair_var.get() if self._voice_var.get() == "girl" else ""

        # Save background color to config
        if self._bg_color_var and self._bg_color_var.get():
            save_background_color(self._bg_color_var.get())

        self._is_generating = True
        self._fusion_btn.configure(state="disabled")
        self._status_label.configure(text="Generating fused character...", fg=ACCENT_COLOR)
        self.show_loading("Fusing characters...")

        thread = threading.Thread(target=self._generate_fusion, daemon=True)
        thread.start()

    def _generate_fusion(self) -> None:
        """Generate the fused character in background thread."""
        try:
            from ...api.gemini_client import (
                call_gemini_fusion,
                load_image_as_base64,
            )
            from ...api.prompt_builders import build_fusion_prompt

            # Get API key
            api_key = self.state.api_key
            if not api_key:
                from ...api.gemini_client import get_api_key
                api_key = get_api_key(use_gui=True)

            # Load images
            left_b64 = load_image_as_base64(self.state.fusion_left_path)
            right_b64 = load_image_as_base64(self.state.fusion_right_path)

            # Build prompt
            from ...config import load_background_color
            prompt = build_fusion_prompt(
                archetype_label=self.state.archetype_label,
                gender_style=self.state.gender_style,
                hair_length=self.state.hair_length,
                background_color=load_background_color(),
            )

            # Call Gemini fusion API
            result_bytes = call_gemini_fusion(
                api_key=api_key,
                prompt=prompt,
                left_image_b64=left_b64,
                right_image_b64=right_b64,
                skip_background_removal=True,  # Keep black background
            )

            if result_bytes:
                # Convert to PIL Image
                result_img = Image.open(BytesIO(result_bytes)).convert("RGBA")
                self.state.fusion_result_image = result_img

                # Schedule UI update on main thread (thread-safe)
                self.schedule_callback(lambda: self._on_fusion_complete(result_img))
            else:
                self.schedule_callback(lambda: self._on_fusion_error("No image returned"))

        except GeminiSafetyError:
            msg = (
                "Gemini blocked this content due to safety filters.\n\n"
                "Try using different source images or descriptions."
            )
            log_error("Fusion blocked by safety filters")
            self.schedule_callback(lambda m=msg: self._on_fusion_error(m))
        except Exception as e:
            error_msg = str(e)
            log_error(f"Fusion failed: {error_msg}")
            self.schedule_callback(lambda m=error_msg: self._on_fusion_error(m))

    def _on_fusion_complete(self, result_img: Image.Image) -> None:
        """Handle successful fusion generation."""
        self._is_generating = False
        self.hide_loading()
        self._fusion_btn.configure(state="normal")
        self._status_label.configure(
            text="Fusion complete! Click Next to continue, or FUSION! to regenerate.",
            fg=ACCENT_COLOR,
        )

        # Display result
        img_copy = result_img.copy()
        img_copy.thumbnail((SLOT_WIDTH, SLOT_HEIGHT), Image.Resampling.LANCZOS)
        self._result_tk_img = ImageTk.PhotoImage(img_copy)
        self._result_label.configure(image=self._result_tk_img, text="")

        log_info("Character fusion complete")

    def _on_fusion_error(self, error: str) -> None:
        """Handle fusion error."""
        self._is_generating = False
        self.hide_loading()
        self._fusion_btn.configure(state="normal")
        self._status_label.configure(text=f"Fusion failed: {error[:50]}...", fg=ERROR_TEXT)
        log_error("Fusion", f"Failed: {error}")
        messagebox.showerror("Fusion Failed", f"Failed to generate fused character:\n{error}")

    def on_enter(self) -> None:
        """Restore state when entering this step."""
        # Restore settings
        if self.state.voice:
            self._voice_var.set(self.state.voice)
            self._voice_indicator.configure(text=f"({self.state.voice.capitalize()})")
            self._update_archetype_menu()

        if self.state.display_name:
            self._name_var.set(self.state.display_name)

        if self.state.archetype_label:
            self._arch_var.set(self.state.archetype_label)

        # Restore hair length and visibility
        if self.state.hair_length:
            self._hair_var.set(self.state.hair_length)
        self._update_hair_length_visibility()

        # Restore background color from config
        if self._bg_color_var:
            self._bg_color_var.set(load_background_color())

        # Restore images
        if self.state.fusion_left_path:
            self._display_image(self.state.fusion_left_path, "left")

        if self.state.fusion_right_path:
            self._display_image(self.state.fusion_right_path, "right")

        if self.state.fusion_result_image:
            img_copy = self.state.fusion_result_image.copy()
            img_copy.thumbnail((SLOT_WIDTH, SLOT_HEIGHT), Image.Resampling.LANCZOS)
            self._result_tk_img = ImageTk.PhotoImage(img_copy)
            self._result_label.configure(image=self._result_tk_img, text="")

        self._update_fusion_button()

    def validate(self) -> bool:
        """Validate that fusion is complete before proceeding."""
        # Check settings
        if not self._voice_var.get():
            messagebox.showerror("Missing Voice", "Please select a voice (Girl or Boy).")
            return False

        name_value = self._name_var.get().strip()
        if not name_value:
            messagebox.showerror("Missing Name", "Please enter a name for the character.")
            return False

        if not self._arch_var.get():
            messagebox.showerror("Missing Archetype", "Please select an archetype.")
            return False

        if self._voice_var.get() == "girl" and not self._hair_var.get():
            messagebox.showerror("Missing Hair Length", "Please select a hair length.")
            return False

        # Check that fusion has been run
        if self.state.fusion_result_image is None:
            messagebox.showerror(
                "No Fusion Result",
                "Please click FUSION! to generate the character before continuing."
            )
            return False

        # Save final settings to state
        self.state.voice = self._voice_var.get()
        self.state.display_name = name_value
        self.state.archetype_label = self._arch_var.get()
        self.state.hair_length = self._hair_var.get() if self._voice_var.get() == "girl" else ""
        self.state.source_mode = "fusion"

        # Save background color to config
        if self._bg_color_var and self._bg_color_var.get():
            save_background_color(self._bg_color_var.get())

        return True
