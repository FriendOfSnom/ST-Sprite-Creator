"""
Settings wizard step (Step 2).

Collects voice, name, and archetype settings before the Setup step.
Runs normalization when advancing to the next step (for image mode).
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional

from PIL import Image

from ...config import (
    NAMES_CSV_PATH,
    GENDER_ARCHETYPES,
    BG_COLOR,
    CARD_BG,
    TEXT_COLOR,
    TEXT_SECONDARY,
    ACCENT_COLOR,
    WARNING_TEXT,
    PAGE_TITLE_FONT,
    SECTION_FONT,
    BODY_FONT,
    SMALL_FONT,
)
from ..tk_common import (
    create_secondary_button,
)
from ..dialogs import load_name_pool, pick_random_name
from .base import WizardStep, WizardState
from ...logging_utils import log_info, log_error


class SettingsStep(WizardStep):
    """Step 2: Collect voice, name, and archetype settings."""

    STEP_ID = "settings"
    STEP_TITLE = "Settings"
    STEP_NUMBER = 2
    STEP_HELP = """Character Settings

This step configures your character's basic information.

VOICE (Required)
Click "Girl" or "Boy" to set the character's voice. This determines:
- Which name pool is used for random names
- Which archetypes are available
- Pronoun references in some prompts

NAME (Required)
A random name is suggested when you pick a voice. You can type any name you want.
This appears in the final character.yml file.

ARCHETYPE (Required)
Affects the style of generated outfits:
- Young Woman/Man: School-age styling, unlocks "ST Uniform" option
- Adult Woman/Man: Professional, mature clothing styles
- Motherly/Fatherly: Older character styling

Click Next when all fields are filled. For image mode, this will also
normalize your image (sharpen resolution, add black background).

ADD-TO-EXISTING MODE
When adding content to an existing character:
- Name is pre-filled and cannot be changed (from character.yml)

For characters CREATED by Sprite Creator (has archetype saved):
- Voice and archetype are also locked (shown in gray)
- All settings come from the original character.yml

For characters NOT created by Sprite Creator:
- Voice/archetype must be selected (for AI prompt generation)
- Original voice setting is preserved at finalization"""

    def __init__(self, wizard, state: WizardState):
        super().__init__(wizard, state)
        self._voice_var: Optional[tk.StringVar] = None
        self._name_var: Optional[tk.StringVar] = None
        self._arch_var: Optional[tk.StringVar] = None
        self._arch_menu: Optional[tk.OptionMenu] = None
        self._voice_indicator: Optional[tk.Label] = None
        self._name_entry: Optional[tk.Entry] = None
        self._status_label: Optional[tk.Label] = None

        # For normalization
        self._is_normalizing: bool = False
        self._normalized_image: Optional[Image.Image] = None

        # Load name pools
        self._girl_names, self._boy_names = load_name_pool(NAMES_CSV_PATH)

    def should_skip(self) -> bool:
        """Skip if in fusion mode (settings are embedded in SourceStep's fusion panel)."""
        return self.state.source_mode == "fusion"

    def build_ui(self, parent: tk.Frame) -> None:
        parent.configure(bg=BG_COLOR)

        # Title
        tk.Label(
            parent,
            text="Character Settings",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=PAGE_TITLE_FONT,
        ).pack(pady=(0, 24))

        # Center container for form
        center_frame = tk.Frame(parent, bg=BG_COLOR)
        center_frame.pack(expand=True)

        # Card-style container
        form_card = tk.Frame(center_frame, bg=CARD_BG, padx=40, pady=30)
        form_card.pack()

        tk.Label(
            form_card,
            text="Fill out all fields before continuing",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=BODY_FONT,
        ).pack(pady=(0, 20))

        # Voice selection
        voice_frame = tk.Frame(form_card, bg=CARD_BG)
        voice_frame.pack(fill="x", pady=(0, 16))

        tk.Label(
            voice_frame,
            text="Voice:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            width=12,
            anchor="e",
        ).pack(side="left", padx=(0, 12))

        self._voice_var = tk.StringVar(value="")

        # Check if character was created by this app (has archetype in character.yml)
        is_sprite_creator_character = (
            self.state.is_adding_to_existing and self.state.archetype_label
        )

        if is_sprite_creator_character:
            # Read-only voice display for Sprite Creator characters
            self._voice_var.set(self.state.voice)
            voice_label = tk.Label(
                voice_frame,
                textvariable=self._voice_var,
                font=BODY_FONT,
                width=15,
                bg="#1E1E1E",
                fg=TEXT_SECONDARY,  # Dimmed to indicate read-only
                anchor="w",
                padx=4,
            )
            voice_label.pack(side="left")
            self._voice_indicator = tk.Label(
                voice_frame,
                text="(from character.yml)",
                bg=CARD_BG,
                fg=TEXT_SECONDARY,
                font=BODY_FONT,
            )
            self._voice_indicator.pack(side="left", padx=(12, 0))
        else:
            # Interactive voice buttons
            girl_btn = create_secondary_button(
                voice_frame, "Girl", lambda: self._set_voice("girl"), width=10
            )
            girl_btn.pack(side="left", padx=(0, 8))

            boy_btn = create_secondary_button(
                voice_frame, "Boy", lambda: self._set_voice("boy"), width=10
            )
            boy_btn.pack(side="left")

            self._voice_indicator = tk.Label(
                voice_frame,
                text="",
                bg=CARD_BG,
                fg=ACCENT_COLOR,
                font=BODY_FONT,
            )
            self._voice_indicator.pack(side="left", padx=(12, 0))

        # Name entry
        name_frame = tk.Frame(form_card, bg=CARD_BG)
        name_frame.pack(fill="x", pady=(0, 16))

        tk.Label(
            name_frame,
            text="Name:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            width=12,
            anchor="e",
        ).pack(side="left", padx=(0, 12))

        self._name_var = tk.StringVar(value="")

        # In add-to-existing mode, name is read-only (pre-filled from character.yml)
        if self.state.is_adding_to_existing:
            self._name_entry = tk.Label(
                name_frame,
                textvariable=self._name_var,
                font=BODY_FONT,
                width=25,
                bg="#1E1E1E",
                fg=TEXT_SECONDARY,  # Dimmed to indicate read-only
                anchor="w",
                padx=4,
            )
            self._name_entry.pack(side="left")
            # Pre-fill from state
            self._name_var.set(self.state.display_name)
            tk.Label(
                name_frame,
                text="(from character.yml)",
                bg=CARD_BG,
                fg=TEXT_SECONDARY,
                font=BODY_FONT,
            ).pack(side="left", padx=(12, 0))
        else:
            self._name_entry = tk.Entry(
                name_frame,
                textvariable=self._name_var,
                font=BODY_FONT,
                width=25,
                bg="#1E1E1E",
                fg=TEXT_COLOR,
                insertbackground=TEXT_COLOR,
            )
            self._name_entry.pack(side="left")

        # Archetype selection
        arch_frame = tk.Frame(form_card, bg=CARD_BG)
        arch_frame.pack(fill="x", pady=(0, 16))

        tk.Label(
            arch_frame,
            text="Archetype:",
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=BODY_FONT,
            width=12,
            anchor="e",
        ).pack(side="left", padx=(0, 12))

        self._arch_var = tk.StringVar(value="")

        if is_sprite_creator_character:
            # Read-only archetype display for Sprite Creator characters
            self._arch_var.set(self.state.archetype_label)
            arch_label = tk.Label(
                arch_frame,
                textvariable=self._arch_var,
                font=BODY_FONT,
                width=20,
                bg="#1E1E1E",
                fg=TEXT_SECONDARY,  # Dimmed to indicate read-only
                anchor="w",
                padx=4,
            )
            arch_label.pack(side="left")
            tk.Label(
                arch_frame,
                text="(from character.yml)",
                bg=CARD_BG,
                fg=TEXT_SECONDARY,
                font=BODY_FONT,
            ).pack(side="left", padx=(8, 0))
            self._arch_menu = None  # No menu needed
        else:
            # Interactive archetype menu
            self._arch_menu = tk.OptionMenu(arch_frame, self._arch_var, "")
            self._arch_menu.configure(width=20, bg="#1E1E1E", fg=TEXT_COLOR)
            self._arch_menu.pack(side="left")

        # Status label
        self._status_label = tk.Label(
            form_card,
            text="",
            bg=CARD_BG,
            fg=TEXT_SECONDARY,
            font=SMALL_FONT,
        )
        self._status_label.pack(pady=(16, 0))

    def _set_voice(self, voice: str) -> None:
        """Handle voice selection."""
        self._voice_var.set(voice)
        self.state.voice = voice
        self._voice_indicator.configure(text=f"({voice.capitalize()} selected)")

        # Update archetype menu
        self._update_archetype_menu()

        # Set random name if empty
        if not self._name_var.get().strip():
            name = pick_random_name(voice, self._girl_names, self._boy_names)
            self._name_var.set(name)

        self._name_entry.focus_set()

    def _update_archetype_menu(self) -> None:
        """Update archetype menu based on voice."""
        # Skip if archetype is read-only (Sprite Creator character)
        if self._arch_menu is None:
            # Just update gender_style from the existing archetype
            voice = self._voice_var.get()
            if voice == "girl":
                self.state.gender_style = "f"
            elif voice == "boy":
                self.state.gender_style = "m"
            return

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

        self._arch_var.set("")
        menu.add_command(label="-- Select --", command=lambda: None)
        for lbl in labels:
            menu.add_command(label=lbl, command=lambda v=lbl: self._arch_var.set(v))

    def on_enter(self) -> None:
        """Restore values from state if available."""
        # Check if character was created by this app (has archetype in character.yml)
        is_sprite_creator_character = (
            self.state.is_adding_to_existing and self.state.archetype_label
        )

        if self.state.voice:
            self._voice_var.set(self.state.voice)
            # Only update indicator for non-Sprite Creator characters
            if not is_sprite_creator_character:
                self._voice_indicator.configure(text=f"({self.state.voice.capitalize()} selected)")
            self._update_archetype_menu()

        if self.state.display_name:
            self._name_var.set(self.state.display_name)

        if self.state.archetype_label:
            self._arch_var.set(self.state.archetype_label)
            # Set gender_style from archetype for Sprite Creator characters
            if is_sprite_creator_character:
                for label, gender in GENDER_ARCHETYPES:
                    if label == self.state.archetype_label:
                        self.state.gender_style = gender
                        break

        # For add-to-existing mode, show helpful status
        if self.state.is_adding_to_existing:
            if is_sprite_creator_character:
                self._status_label.configure(
                    text=f"Adding to: {self.state.display_name} (settings locked from original)",
                    fg=ACCENT_COLOR
                )
            else:
                self._status_label.configure(
                    text=f"Adding content to: {self.state.display_name}",
                    fg=ACCENT_COLOR
                )
        else:
            self._status_label.configure(text="")

    def validate(self) -> bool:
        """Validate settings and start normalization if in image mode."""
        # Check voice
        if not self._voice_var.get():
            messagebox.showerror("Missing Voice", "Please select a voice (Girl or Boy).")
            return False

        # Check name
        name_value = self._name_var.get().strip()
        if not name_value:
            messagebox.showerror("Missing Name", "Please enter a name for the character.")
            return False

        # Check archetype
        if not self._arch_var.get():
            messagebox.showerror("Missing Archetype", "Please select an archetype.")
            return False

        # Save to state
        self.state.voice = self._voice_var.get()
        self.state.display_name = name_value
        self.state.archetype_label = self._arch_var.get()

        log_info(f"SETTINGS: Name={self.state.display_name}, Archetype={self.state.archetype_label}, Voice={self.state.voice}, Gender={self.state.gender_style}, Mode={self.state.source_mode}")

        # For image mode, run normalization before advancing
        # (Skip for add-to-existing mode - we use existing images)
        if self.state.source_mode == "image" and self.state.image_path and not self.state.is_adding_to_existing:
            # Check if already normalized (either locally or in state from previous run)
            already_normalized = (
                self._normalized_image is not None
                or self.state.normalized_image is not None
            )
            if not already_normalized and not self._is_normalizing:
                self._start_normalization()
                return False  # Don't advance yet - will advance after normalization completes

        return True

    def _start_normalization(self) -> None:
        """Start image normalization in background thread."""
        if self._is_normalizing:
            return

        self._is_normalizing = True
        self._status_label.configure(text="Normalizing image...", fg=TEXT_SECONDARY)
        self.show_loading("Normalizing image...")

        # Run normalization in background thread
        thread = threading.Thread(target=self._run_normalization, daemon=True)
        thread.start()

    def _run_normalization(self) -> None:
        """Run image normalization in background thread."""
        try:
            from io import BytesIO
            from ...api.gemini_client import get_api_key, call_gemini_image_edit
            from ...api.prompt_builders import build_normalize_image_prompt
            from ...api.gemini_client import load_image_as_base64

            # Get API key
            api_key = self.state.api_key or get_api_key(use_gui=True)

            # Load source image as base64
            image_b64 = load_image_as_base64(self.state.image_path)

            # Build normalization prompt
            prompt = build_normalize_image_prompt()

            # Call Gemini to normalize
            result_bytes = call_gemini_image_edit(
                api_key=api_key,
                prompt=prompt,
                image_b64=image_b64,
                skip_background_removal=True,  # Don't remove BG at this step
            )

            if result_bytes:
                # Convert bytes to PIL Image
                self._normalized_image = Image.open(BytesIO(result_bytes)).convert("RGBA")
                # Store in state for SetupStep to use
                self.state.normalized_image = self._normalized_image
                # Schedule UI update on main thread (thread-safe)
                self.schedule_callback(self._on_normalization_complete)
            else:
                self.schedule_callback(lambda: self._on_normalization_error("No image returned"))

        except Exception as e:
            error_msg = str(e)
            log_error(f"Normalization failed: {error_msg}")
            self.schedule_callback(lambda: self._on_normalization_error(error_msg))

    def _on_normalization_complete(self) -> None:
        """Handle successful normalization."""
        self._is_normalizing = False
        self.hide_loading()
        self._status_label.configure(text="Image normalized!", fg=ACCENT_COLOR)
        log_info("Image normalization complete")

        # Now advance to next step
        self.wizard.go_next()

    def _on_normalization_error(self, error: str) -> None:
        """Handle normalization error - continue anyway with original image."""
        self._is_normalizing = False
        self.hide_loading()
        self._status_label.configure(text=f"Normalization skipped: {error[:40]}...", fg=WARNING_TEXT)
        log_error(f"Normalization failed, continuing with original: {error}")

        # Set normalized_image to None so SetupStep falls back to original
        self.state.normalized_image = None

        # Continue to next step anyway
        self.wizard.go_next()
